"""PIVEN Companion with the React interface (modern-ui) in a pywebview window over CompanionCore.

The page talks to Python only through WebApi below: it polls `poll` for a state
snapshot and sends commands; chats and settings are the same files the Qt window uses.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

import companion_core  # sets up the bundled package paths before anything else
from companion_core import (APP_DIR, APP_NAME, COMFY_DEFAULT_WORKFLOW, COMPANION_SYSTEM_PROMPT, DATA_DIR, LOG_PATH,
                            OLLAMA_THINK_LEVELS, CompanionCore, acquire_instance_lock, bounded_int, encode_chat_image,
                            log, list_models, backend_problem, model_thinking)
import hf_models
import twitch_core
import llama_backend
import memory_estimate
import mcp_client
import model_logos
import providers
import tools
import voice_install

UI_INDEX = APP_DIR / "modern-ui" / "dist" / "index.html"
WINDOW_TITLE = "PIVEN Companion"
MAX_IMAGE_BYTES = 12_000_000
MAX_UPLOAD_BYTES = 20_000_000
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")
# Native title bar colours (caption, text, border) matching the page's sidebar per theme.
TITLE_BAR_COLORS = {True: (0x0A0A0A, 0xEEEEEE, 0x262626), False: (0xFFFFFF, 0x1A1A1A, 0xE3E3E3)}


def style_title_bar(window, dark=True):
    """Colour the Windows 11 caption via DWM so it does not stay white above the dark page."""
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = wintypes.HWND(int(window.native.Handle.ToInt64()))
        dwm = ctypes.windll.dwmapi

        def set_attribute(attribute, value):
            data = ctypes.c_int(value)
            return dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data))

        def colorref(rgb):  # DWM expects 0x00BBGGRR
            return ((rgb & 0xFF) << 16) | (rgb & 0xFF00) | ((rgb >> 16) & 0xFF)

        caption, text, border = TITLE_BAR_COLORS[bool(dark)]
        set_attribute(20, 1 if dark else 0)  # DWMWA_USE_IMMERSIVE_DARK_MODE
        results = [set_attribute(35, colorref(caption)),  # DWMWA_CAPTION_COLOR
                   set_attribute(36, colorref(text)),     # DWMWA_TEXT_COLOR
                   set_attribute(34, colorref(border))]   # DWMWA_BORDER_COLOR
        return all(result == 0 for result in results)
    except Exception as error:
        log(f"title bar styling skipped: {error}")
        return False


# What the model is asked when a picture is sent without a message (keyed by "more than one picture").
# The chat itself shows just the pictures, not this text.
IMAGE_ONLY_PROMPTS = {False: "Посмотри на это изображение и коротко расскажи, что на нём.",
                      True: "Посмотри на эти изображения и коротко расскажи, что на них."}


class WebCompanion(CompanionCore):
    """Plays the role of the Qt window's `_drain_events` for the web interface."""

    def __init__(self):
        self.route_events_by_chat = True  # answers can run in several chats at once (see ChatEvents)
        self.init_core()
        self.selected_model = self.settings.get("model", "")
        self.window = None
        self._state_lock = threading.RLock()
        self._version = 1
        self._activity = "Готов к работе"
        self._status = ""
        self._reasoning = ""
        self._notice = ""
        self._models = []
        self._models_error = ""
        self._busy_since = None
        # Files the page may show, open or attach: chat images plus what the user picked or pasted.
        self._allowed_files = set()
        # A pending download confirmation, answered from the page (see _confirm_download).
        self._confirm = None
        self._error = None  # the last failed answer {"chat", "text", "id"}: shown under its chat for ERROR_SECONDS, never saved
        self._confirm_answer = threading.Event()
        self._browser_request = None  # the model asked to show a page: {"url", "nonce"}; the page opens its panel
        self.tray = None          # the notification-area icon (tray.Tray), when it could be created
        self._quitting = False    # True once the user really quits (tray menu, restart); closing only hides then
        self._hidden = False
        self._confirm_result = False
        self._hf = {"state": "idle", "percent": 0, "message": "", "tag": "", "path": "", "error": ""}
        self._hf_cancel = threading.Event()
        self._voice = {"kind": "", "id": "", "state": "idle", "percent": 0, "message": "", "error": ""}
        self._voice_cancel = threading.Event()

    # ---------- state ----------
    def _changed(self):
        self._version += 1

    ERROR_SECONDS = 20

    def _show_error(self, chat_id, text):
        """Show a failed answer under its chat for a while instead of writing it into the history. Under the state lock."""
        error_id = uuid.uuid4().hex
        self._error = {"chat": chat_id, "text": str(text), "id": error_id}
        self._changed()

        def clear():
            with self._state_lock:
                if self._error and self._error["id"] == error_id:
                    self._error = None
                    self._changed()
        timer = threading.Timer(self.ERROR_SECONDS, clear)
        timer.daemon = True
        timer.start()

    def known_files(self):
        with self._state_lock:
            files = {str(path) for chat in self.chats for item in chat.get("items", []) for path in item.get("images") or []}
            return files | self._allowed_files

    def snapshot(self):
        with self._state_lock:
            active = self._active_chat() or {}
            # Newest first (chats are stored in creation order), pinned ones on top.
            chats = sorted(reversed(self.chats), key=lambda chat: not chat.get("pinned"))
            return {
                "version": self._version,
                "activeChatId": self.active_chat_id,
                "chats": [{"id": chat.get("id"), "title": chat.get("title") or "Новый чат",
                           "pinned": bool(chat.get("pinned")), "count": len(chat.get("items", [])),
                           "busy": chat.get("id") in self._busy_chats, "unread": bool(chat.get("unread")),
                           "model": chat.get("model", ""), "updated": chat.get("updated", 0),
                           "preview": next((" ".join(str(item.get("text", "")).split())[:90]
                                            for item in reversed(chat.get("items", []))
                                            if item.get("role") in ("assistant", "user") and item.get("text")), "")}
                          for chat in chats],
                "items": [{"role": item.get("role", "system"), "text": str(item.get("text", "")),
                           "images": [str(path) for path in item.get("images") or []],
                           "undo": len(item.get("undo") or [])}
                          for item in self.dialogue_items if isinstance(item, dict)],
                "chatTitle": active.get("title") or "Новый чат",
                "busy": bool(self.busy),
                "busySince": self._busy_since or 0,
                "listening": {"running": bool(self.running),
                              "options": dict(zip(("mic", "loopback", "screen", "proactive"), map(bool, self.capture_options)))},
                "call": dict(zip(("speaking", "hearing", "muted"), self._call_flags())),
                "confirm": self._confirm,
                "error": self._error["text"] if self._error and self._error["chat"] == self.active_chat_id else "",
                "downloads": self._downloads(),
                "browserRequest": self._browser_request,
                "activity": self._activity,
                "status": self._status,
                "reasoning": self._reasoning,
                "notice": self._notice,
                "models": self._models,
                "modelsError": self._models_error,
                "settings": {
                    "model": self.settings.get("model", ""),
                    "speechEnabled": bool(self.speech_enabled),
                    "projectRoot": self.settings.get("project_root", ""),
                    "comfyUrl": self.settings.get("comfy_url", ""),
                    "voice": self.settings.get("voice", ""),
                    "theme": self.settings.get("canvas_theme", ""),
                    "systemPrompt": self.settings.get("system_prompt", ""),
                    "integrations": dict(self.settings.get("integrations_enabled", {})),
                    "thinkingLevel": self.settings.get("thinking_levels", {}).get(self.settings.get("model", ""), "__auto__"),
                },
            }

    @staticmethod
    def _attach_undo(items, record):
        """Give the latest answer of a chat the files and folders its request made (for its undo button)."""
        answer = next((item for item in reversed(items) if isinstance(item, dict) and item.get("role") == "assistant"), None)
        if answer is not None:
            answer["undo"] = record

    def _background_event(self, chat_id, kind, value):
        """An event of an answer whose chat is not on screen: its cards go to that chat. Under the state lock."""
        chat = next((item for item in self.chats if item.get("id") == chat_id), None)
        title = chat.get("title", "") if chat else ""
        if kind == "message":
            role, content, _voice = value
            self.append_to_chat(chat_id, role, content)
            if role == "assistant":
                self._notify(f"Ответ в чате «{title}»", content)
        elif kind == "error":
            self._show_error(chat_id, value)
        elif kind == "undo_ready" and chat:
            self._attach_undo(chat.get("items", []), value)
            self._save_conversation()
        elif kind == "generated_image":
            self.append_to_chat(chat_id, "assistant", "Изображение создано через ComfyUI.", [str(value)])
        elif kind == "presentation_created":
            self.append_to_chat(chat_id, "assistant", f"Презентация готова · {Path(value).name}", [str(value)])
        elif kind == "generated_video":
            self.append_to_chat(chat_id, "assistant", "Видео готово.", [str(value)])
        elif kind == "computer_action":
            action, screenshot_size, display_size = value[:3]
            try:
                result = self._execute_computer_actions(action, screenshot_size, display_size, str(value[3]) if len(value) > 3 else "")
            except Exception as error:
                result = f"Не удалось выполнить действие на компьютере: {error}"
            self.append_to_chat(chat_id, "system", result)
        elif kind == "request_done":
            self._busy_chats.discard(chat_id)
        else:
            return
        self._changed()

    def _notify(self, title, text):
        """A Windows notification, only when the window is hidden or another window is in front."""
        if not self.tray or not self.settings.get("notifications", True):
            return
        try:
            import tray
            if self._hidden or tray.foreground_title() != WINDOW_TITLE:
                self.tray.notify(title, " ".join(companion_core.speech_text(text).split())[:220])
        except Exception as error:
            log(f"notification error: {error}")

    def tool_browser(self):
        return ModelBrowser(self)

    def _downloads(self):
        """Running downloads (and ones that ended a moment ago) for the left panel. Called under the state lock."""
        now = time.monotonic()
        rows = []
        for kind, job in (("model", self._hf), ("voice", self._voice)):
            state = job.get("state", "idle")
            if state == "idle" or (state != "running" and now - job.get("ended", now) > 12):
                continue
            title = job.get("tag") or job.get("id") or ""
            rows.append({"kind": kind, "title": title, "state": state, "percent": job.get("percent", 0),
                         "message": job.get("error") if state in ("error", "cancelled") else job.get("message", "")})
        return rows

    def _record(self, role, text, images=None):
        self.record_dialogue_item(role, text, images)
        self._changed()

    # ---------- events from core workers ----------
    def _call_flags(self):
        """(speaking, hearing, muted) for the call panel; hearing = the microphone heard a voice just now."""
        hearing = self.running and not self.mic_muted and time.monotonic() - getattr(self, "last_mic_activity", 0.0) < 0.9
        return bool(self.tts_playing.is_set()), bool(hearing), bool(self.mic_muted)

    def pump_events(self):
        """Apply queued worker events, mirroring CompanionApp._drain_events."""
        with self._state_lock:
            flags = self._call_flags()
            if flags != getattr(self, "_last_call_flags", None):
                self._last_call_flags = flags
                self._changed()
            # The page counts the elapsed seconds itself from this wall-clock start time.
            if self.busy != (self._busy_since is not None):
                self._busy_since = time.time() if self.busy else None
                self._changed()
            while True:
                try:
                    kind, value = self.events.get_nowait()
                except Exception:
                    break
                if kind == "chat_event":  # from an answer thread: applies here only if its chat is on screen
                    chat_id, kind, value = value[0], value[1], (value[2] if len(value) > 2 else None)
                    if chat_id != self.active_chat_id:
                        self._background_event(chat_id, kind, value)
                        continue
                self._changed()
                if kind == "status":
                    self._status = str(value)
                elif kind in ("activity", "generation_progress") and value:
                    self._activity = str(value)
                elif kind == "generation_started":
                    self._activity = "ComfyUI готовит изображение"
                elif kind == "reasoning":
                    self._reasoning = str(value)
                elif kind in ("reasoning_clear", "reasoning_remove"):
                    self._reasoning = ""
                elif kind == "message":
                    role, content, voice = value
                    if role == "assistant":
                        self._activity = "Ответ получен"; self._reasoning = ""
                        self._notify("PIVEN ответил", content)
                    self._record(role, content)
                    if voice:
                        threading.Thread(target=self._speak, args=(content,), daemon=True).start()
                elif kind == "computer_action":
                    action, screenshot_size, display_size = value[:3]
                    request_text = str(value[3]) if len(value) > 3 else ""
                    try:
                        result = self._execute_computer_actions(action, screenshot_size, display_size, request_text)
                        self._activity = "Действие на компьютере выполнено"
                    except Exception as error:
                        result = f"Не удалось выполнить действие на компьютере: {error}"
                        self._activity = "Ошибка действия на компьютере"
                        log(f"computer skill action error: {error}")
                    self._record("system", result)
                    self.messages.append({"role": "assistant", "content": result})
                    self._save_conversation()
                elif kind == "generated_image":
                    self._record("assistant", "Изображение создано через ComfyUI.", [str(value)])
                    self._activity = "Изображение готово"
                    self._notify("Изображение готово", "Картинка создана через ComfyUI.")
                elif kind == "generated_video":
                    self._record("assistant", "Видео готово.", [str(value)])
                    self._activity = "Видео готово"
                    self._notify("Видео готово", Path(value).name)
                elif kind == "presentation_created":
                    self._record("assistant", f"Презентация готова · {Path(value).name}", [str(value)])
                    self._activity = "Презентация создана"
                    self._notify("Презентация готова", Path(value).name)
                elif kind == "error":
                    self._show_error(self.active_chat_id, value); self._activity = "Ошибка"; self._reasoning = ""
                    self._notify("Ошибка", str(value))
                elif kind == "undo_ready":
                    self._attach_undo(self.dialogue_items, value)
                    self._save_conversation()
                elif kind == "chats_changed":
                    self._changed()
                elif kind == "action_interrupted":
                    self._activity = "Запрос прерван"; self._reasoning = ""
                elif kind == "asr":
                    self.handle_transcript(value, self.settings.get("model", "").strip())
                elif kind in ("stopped", "capture_failed"):
                    self.running = False
                    self._activity = "Прослушивание остановлено"
                elif kind == "request_done":
                    self._save_conversation()
                    self.busy = False
                    if self.pending_text_prompts:
                        text, model, images, image_paths = self.pending_text_prompts.pop(0)
                        self.busy = True; self.selected_model = model
                        self._record("user", "" if text in IMAGE_ONLY_PROMPTS.values() else text, image_paths)
                        self._activity = "Думает · отвечает на сообщение из очереди"
                        threading.Thread(target=self.ask_model, args=(text, images or None, self.speech_enabled),
                                         daemon=True).start()

    # ---------- commands ----------
    def send(self, text, image_paths=None):
        text = str(text or "").strip()
        allowed = self.known_files()
        image_paths = [str(path) for path in (image_paths or []) if str(path) in allowed and Path(str(path)).is_file()]
        if not text and not image_paths:
            return {"ok": False, "error": "Пустое сообщение."}
        route = self._detect_composer_route(text, has_images=bool(image_paths))
        if image_paths and self._detect_composer_route(text) == "video":  # "сделай видео из этой картинки"
            with self._state_lock:
                if self.busy:
                    return {"ok": False, "error": "Дождись завершения текущего действия."}
                self._record("user", text, image_paths)
                self._activity = "Видео по картинке · запуск ComfyUI"
                self._start_video_generation(text, image_paths[0])
            return {"ok": True, "route": "video"}
        if image_paths:
            # Same path as the Qt window: attached pictures always go to the model as a question about them.
            return self._send_with_images(text, image_paths)
        with self._state_lock:
            self._notice = ""
            if route == "audio":
                return {"ok": False, "error": "Генерация музыки и звуков пока не поддерживается."}
            if route in ("image", "video") and not self._integration_enabled("comfyui"):
                return {"ok": False, "error": "Интеграция ComfyUI выключена. Включи её в настройках Компаньона."}
            if route not in ("image", "video") and not self._integration_enabled("ollama"):
                return {"ok": False, "error": "Локальная модель выключена. Включи её в настройках Компаньона."}
            model = self.settings.get("model", "").strip()
            if route not in ("image", "video") and not model:
                return {"ok": False, "error": "Сначала выбери модель."}
            if self.busy:
                if route != "chat":
                    return {"ok": False, "error": "Дождись завершения текущего действия."}
                self.pending_text_prompts.append((text, model, None, []))
                self._activity = "Сообщение добавлено в очередь"; self._changed()
                return {"ok": True, "queued": True}
            self.action_cancel.clear()
            self._active_ollama_response = None
            self.selected_model = model
            self._record("user", text)
            if route == "image":
                self._activity = "Запрос на изображение · запуск ComfyUI"
                self._start_image_generation(text)
                return {"ok": True, "route": route}
            if route == "video":
                self._activity = "Запрос на видео · запуск ComfyUI"
                self._start_video_generation(text)
                return {"ok": True, "route": route}
            self.busy = True
            if route == "presentation":
                self._activity = "Собирает презентацию · готовит содержание"
                threading.Thread(target=self._run_presentation_agent, args=(text, model), daemon=True).start()
            elif route == "code":
                project_root = Path(self.settings.get("project_root", str(APP_DIR))).expanduser()
                if not project_root.is_dir():
                    self.busy = False
                    self._record("system", "Рабочая папка проекта не найдена. Выбери её в настройках Компаньона → Код.")
                    return {"ok": False, "route": route}
                self._activity = "Задача по проекту · агент изучает файлы"
                threading.Thread(target=self._run_coding_agent, args=(text, model, str(project_root)), daemon=True).start()
            else:
                self._activity = "Думает"
                threading.Thread(target=self.ask_model, args=(text, None, self.speech_enabled), daemon=True).start()
            self._changed()
            return {"ok": True, "route": route}

    def refresh_models(self):
        try:
            providers.refresh()  # asks Ollama, LM Studio and the cloud services that are switched on
        except Exception as exc:
            log(f"providers refresh error: {exc}")
        try:
            names = list_models()
            error = backend_problem()
        except Exception as exc:
            names, error = [], f"Не удалось прочитать папку моделей: {exc}"
        with self._state_lock:
            self._models, self._models_error = names, error
            self._status = f"Моделей: {len(names)}" if names else (error or "Нет моделей")
            if names and self.settings.get("model") not in names:
                self.settings["model"] = names[0]
            self._changed()

    def _send_with_images(self, text, image_paths):
        if not self._integration_enabled("ollama"):
            return {"ok": False, "error": "Локальная модель выключена. Включи её в настройках Компаньона."}
        model = self.settings.get("model", "").strip()
        if not model:
            return {"ok": False, "error": "Сначала выбери модель."}
        if not text:
            # The model needs something to answer; the chat shows only the picture.
            text = IMAGE_ONLY_PROMPTS[len(image_paths) > 1]
        try:
            image_data = [encode_chat_image(path) for path in image_paths]
        except Exception as error:
            return {"ok": False, "error": f"Не удалось подготовить изображение: {error}"}
        with self._state_lock:
            if self.busy:
                self.pending_text_prompts.append((text, model, image_data, image_paths))
                self._activity = "Сообщение добавлено в очередь"; self._changed()
                return {"ok": True, "queued": True}
            self._record("user", "" if text in IMAGE_ONLY_PROMPTS.values() else text, image_paths)
            self.action_cancel.clear()
            self._active_ollama_response = None
            self.busy = True; self.selected_model = model; self._activity = "Думает"
            threading.Thread(target=self.ask_model, args=(text, image_data, self.speech_enabled), daemon=True).start()
            self._changed()
            return {"ok": True, "route": "chat"}

    def _confirm_download(self, url, destination):
        """Ask the page and wait for the answer; called from the model's worker thread, never from poll."""
        with self._state_lock:
            self._confirm_answer.clear()
            self._confirm_result = False
            self._confirm = {"id": uuid.uuid4().hex, "kind": "download", "url": str(url), "destination": str(destination)}
            self._changed()
            self._notify("PIVEN спрашивает", f"Можно скачать файл? {url}")
        answered = self._confirm_answer.wait(timeout=600)
        with self._state_lock:
            self._confirm = None
            self._changed()
            return answered and self._confirm_result

    def _run_approved_download(self, item, screenshot_size, display_size):
        with self._state_lock:
            self._activity = "Скачивание файла"
            self._changed()
        return super()._run_approved_download(item, screenshot_size, display_size)

    def start_hf_download(self, repo_id, record, tag, token):
        with self._state_lock:
            if self._hf["state"] == "running":
                return {"ok": False, "error": "Модель уже скачивается."}
            self._hf = {"state": "running", "percent": 0, "message": "Подключение к Hugging Face", "tag": tag, "path": "", "error": ""}
            self._changed()
            self._hf_cancel.clear()

        def progress(percent, message):
            with self._state_lock:
                self._hf.update(percent=max(0, min(100, int(percent))), message=str(message))
                self._changed()

        def work():
            try:
                path = hf_models.download_model(repo_id, record, token, progress, self._hf_cancel)
                with self._state_lock:
                    self._hf.update(state="done", percent=100, message="Модель готова", path=path, ended=time.monotonic())
                    self._changed()
                    self._notify("Загрузка завершена", f"Модель {self._hf.get('tag') or Path(path).stem} скачана.")
                self.refresh_models()
                name = Path(path).stem
                with self._state_lock:
                    if name in self._models and not self.busy:
                        self.settings["model"] = name
                        self._save_settings(); self._changed()
            except Exception as error:
                with self._state_lock:
                    self._hf.update(state="cancelled" if isinstance(error, InterruptedError) else "error", error=str(error), ended=time.monotonic())
                    self._changed()
        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    def start_voice_install(self, kind, model_id, extra=None, token=""):
        """Download a built-in voice model by id, or (with `extra`) one found by search: model_id is then its repository."""
        catalogue = voice_install.ASR_MODELS if kind == "asr" else voice_install.TTS_MODELS if kind == "tts" else None
        extra = extra if isinstance(extra, dict) else {}
        if catalogue is None or (model_id not in catalogue and not (extra.get("file") or extra.get("repo") or extra.get("engine"))):
            return {"ok": False, "error": "Неизвестная модель."}
        with self._state_lock:
            if self._voice["state"] == "running":
                return {"ok": False, "error": "Уже идёт установка."}
            # The TTS install may rewrite the venv the running voice server uses.
            if kind == "tts" and not voice_install.tts_packages_ready() and (self.running or self.tts_playing.is_set()):
                return {"ok": False, "error": "Сначала заверши звонок и озвучку."}
            self._voice = {"kind": kind, "id": model_id, "state": "running", "percent": 0, "message": "Подключение", "error": "", "installed": ""}
            self._changed()
            self._voice_cancel.clear()

        def progress(percent, message):
            with self._state_lock:
                self._voice.update(percent=max(0, min(100, int(percent))), message=str(message))
                self._changed()

        def work():
            try:
                installed = voice_install.install(kind, model_id, progress, self._voice_cancel, extra, token)
                with self._state_lock:
                    self._voice.update(state="done", percent=100, installed=installed, message="Готово", ended=time.monotonic())
                    self._changed()
                    self._notify("Загрузка завершена", f"Голосовая модель {model_id} скачана.")
            except BaseException as error:
                log(f"Voice install {kind}/{model_id} failed: {error}")
                with self._state_lock:
                    self._voice.update(state="cancelled" if isinstance(error, InterruptedError) else "error", error=str(error), ended=time.monotonic())
                    self._changed()
        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}


class ModelBrowser:
    """The built-in browser as the model's tool: opens the panel on the page if it is closed, loads the address
    and reads the page text."""

    def __init__(self, app):
        self.app = app

    def _browser(self, wait=15):
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            browser = getattr(self.app, "_web_api", None) and self.app._web_api._native_browser()
            if browser is not None and browser.ready:
                return browser
            time.sleep(0.25)
        raise RuntimeError("встроенный браузер не открылся")

    def open(self, url):
        with self.app._state_lock:
            self.app._browser_request = {"url": url, "nonce": time.time()}
            self.app._changed()
        browser = self._browser()
        browser.navigate(url)
        deadline = time.monotonic() + 30
        time.sleep(0.6)
        while time.monotonic() < deadline and browser.state().get("loading"):
            time.sleep(0.25)
        return self.text(browser)

    def text(self, browser=None):
        browser = browser or self._browser()
        text = browser.read_text() or ""
        text = re.sub(r"\n{3,}", "\n\n", text)
        return browser.state().get("title", ""), text


class WebApi:
    """Methods callable from JavaScript as window.pywebview.api.<name>()."""

    def __init__(self, app):
        self._app = app
        self._browser = None
        app._web_api = self  # the model's browser tool reaches the browser panel through it

    def poll(self, known_version=0):
        app = self._app
        app.pump_events()
        if int(known_version or 0) == app._version:
            return {"version": app._version, "unchanged": True}
        return app.snapshot()

    def state(self):
        return self._app.snapshot()

    def refresh_models(self):
        self._app.refresh_models()
        return self._app.snapshot()

    def send(self, text):
        return self._app.send(text)

    def interrupt(self):
        return {"ok": self._app.interrupt_current_action()}

    def select_chat(self, chat_id):
        app = self._app
        with app._state_lock:
            ok = app.select_chat(str(chat_id)) is not None
            app._changed()
        return {"ok": ok}

    def new_chat(self):
        app = self._app
        with app._state_lock:
            # Reuse an untouched chat instead of piling up empty «Новый чат» entries.
            empty = next((chat for chat in reversed(app.chats) if not chat.get("items") and not chat.get("messages")), None)
            if empty is not None:
                app.select_chat(empty["id"])
            else:
                app.create_chat()
            app._changed()
        return {"ok": True}

    def set_model(self, name):
        app = self._app
        name = str(name or "").strip()
        with app._state_lock:
            if name not in app._models:
                return {"ok": False, "error": "Такой модели нет в папке моделей."}
            app.settings["model"] = name; app.selected_model = name
            chat = app._active_chat()
            if chat is not None:
                chat["model"] = name  # each chat remembers its model
                app._save_conversation()
            app._save_settings(); app._changed()
        return {"ok": True}

    def set_speech(self, enabled):
        app = self._app
        with app._state_lock:
            app.speech_enabled = bool(enabled); app.settings["speech_enabled"] = app.speech_enabled
            app._save_settings(); app._changed()
        return {"ok": True}

    # ---------- settings (same keys and side effects as the Qt settings dialog) ----------
    def settings_details(self):
        app = self._app
        settings = app.settings
        microphones, mic_error = [], ""
        try:
            import soundcard
            for microphone in soundcard.all_microphones(include_loopback=False):
                if microphone.name not in microphones:
                    microphones.append(microphone.name)
        except Exception as error:
            mic_error = f"Список микрофонов недоступен: {error}"
        return {
            "systemPrompt": settings.get("system_prompt", ""),
            "defaultSystemPrompt": COMPANION_SYSTEM_PROMPT,
            "speechEnabled": bool(app.speech_enabled),
            "voice": settings.get("voice", "Russian"),
            "voices": voice_install.tts_voices(settings.get("tts_model")),
            "screenInterval": settings.get("screen_interval", 35),
            "micDevice": settings.get("mic_device", ""),
            "voiceSample": settings.get("voice_sample", ""),
            "voiceSampleText": settings.get("voice_sample_text", ""),
            "micSensitivity": settings.get("mic_sensitivity", 68),
            "bargeIn": bool(settings.get("barge_in", True)),
            "closeToTray": bool(settings.get("close_to_tray", True)),
            "maxLoadedModels": settings.get("max_loaded_models", 3),
            "notifications": bool(settings.get("notifications", True)),
            "microphones": microphones,
            "micError": mic_error,
            "comfyUrl": settings.get("comfy_url", ""),
            "comfyWorkflow": settings.get("comfy_workflow", ""),
            "comfyVideoWorkflow": settings.get("comfy_video_workflow", ""),
            "projectRoot": settings.get("project_root", ""),
            "twitchChannel": settings.get("twitch_channel", ""),
            "integrations": dict(settings.get("integrations_enabled", {})),
            "dataDir": str(DATA_DIR),
        }

    def update_settings(self, patch):
        """Validate and apply a partial settings change, then save settings.json."""
        app = self._app
        if not isinstance(patch, dict):
            return {"ok": False, "errors": {"_": "Некорректный запрос."}}
        errors, changes = {}, {}
        for key, value in patch.items():
            if key == "systemPrompt":
                text = str(value or "").strip()
                if len(text) > 20000:
                    errors[key] = "Слишком длинный промпт (больше 20 000 символов)."
                else:
                    changes["system_prompt"] = text or COMPANION_SYSTEM_PROMPT
            elif key == "speechEnabled":
                changes["speech_enabled"] = bool(value)
            elif key == "bargeIn":
                changes["barge_in"] = bool(value)
            elif key == "maxLoadedModels":
                changes["max_loaded_models"] = max(1, min(8, int(value or 1)))
                llama_backend.max_loaded[0] = changes["max_loaded_models"]
            elif key == "closeToTray":
                changes["close_to_tray"] = bool(value)
            elif key == "notifications":
                changes["notifications"] = bool(value)
            elif key == "voice":
                changes["voice"] = str(value or "Russian")[:60]
            elif key == "screenInterval":
                changes["screen_interval"] = bounded_int(value, 35, 10, 600)
            elif key == "micDevice":
                changes["mic_device"] = str(value or "")[:200]
            elif key == "voiceSample":
                path = str(value or "").strip()
                if path and not (Path(path).is_file() and path.lower().endswith(".wav")):
                    errors[key] = "Нужен существующий файл .wav."
                else:
                    changes["voice_sample"] = path
            elif key == "voiceSampleText":
                changes["voice_sample_text"] = str(value or "")[:2000]
            elif key == "micSensitivity":
                changes["mic_sensitivity"] = bounded_int(value, 68, 1, 100)
            elif key == "comfyUrl":
                url = str(value or "").strip().rstrip("/")
                if not re.fullmatch(r"https?://[^\s/]+(:\d+)?(/\S*)?", url or "x"):
                    errors[key] = "Нужен адрес вида http://127.0.0.1:8188"
                else:
                    changes["comfy_url"] = url
            elif key == "comfyWorkflow":
                workflow = Path(str(value or "").strip()).expanduser()
                if not str(value or "").strip():
                    changes["comfy_workflow"] = str(COMFY_DEFAULT_WORKFLOW)
                elif not workflow.is_file() or workflow.suffix.lower() != ".json":
                    errors[key] = "Файл не найден или это не .json."
                else:
                    changes["comfy_workflow"] = str(workflow)
            elif key == "comfyVideoWorkflow":
                workflow = Path(str(value or "").strip()).expanduser()
                if not str(value or "").strip():
                    changes["comfy_video_workflow"] = ""
                elif not workflow.is_file() or workflow.suffix.lower() != ".json":
                    errors[key] = "Файл не найден или это не .json."
                else:
                    changes["comfy_video_workflow"] = str(workflow)
            elif key == "projectRoot":
                folder = Path(str(value or "").strip()).expanduser()
                if not str(value or "").strip() or not folder.is_dir():
                    errors[key] = "Такой папки нет."
                else:
                    changes["project_root"] = str(folder)
            elif key == "twitchChannel":
                channel = str(value or "").strip().lstrip("#")
                if channel and not re.fullmatch(r"[A-Za-z0-9_]{1,25}", channel):
                    errors[key] = "Только латиница, цифры и _, до 25 символов."
                else:
                    changes["twitch_channel"] = channel
            elif key == "integrations":
                current = dict(app.settings.get("integrations_enabled", {}))
                for name in ("ollama", "comfyui", "twitch"):
                    if isinstance(value, dict) and name in value:
                        current[name] = bool(value[name])
                changes["integrations_enabled"] = current
            else:
                errors[key] = "Эту настройку отсюда менять нельзя."
        if changes:
            with app._state_lock:
                app.settings.update(changes)
                app.speech_enabled = app.settings["speech_enabled"]
                app.screen_interval_seconds = app.settings["screen_interval"]
                app.mic_device = app.settings["mic_device"]
                app.mic_sensitivity = app.settings["mic_sensitivity"]
                app.barge_in = app.settings["barge_in"]
                app.messages[0]["content"] = app._effective_system_prompt(app.settings["system_prompt"])
                if "integrations_enabled" in changes and not changes["integrations_enabled"].get("ollama", True):
                    app.pending_text_prompts.clear()
                    if app.busy:
                        app.action_cancel.set()
                app._save_settings()
                app._changed()
        return {"ok": not errors, "errors": errors, "saved": sorted(changes)}

    def thinking_options(self, model):
        """Reasoning levels the model advertises; cached in settings like the Qt window does."""
        app = self._app
        model = str(model or "")
        cached = app.settings.get("thinking_capabilities", {}).get(model)
        if cached is None or cached.get("version") != 2:   # version 1 knew only on/off for most models
            try:
                values, default = model_thinking(model)
            except Exception as error:
                return {"values": [], "default": None, "current": "__auto__", "error": str(error)}
            cached = {"values": values, "default": default, "version": 2}
            with app._state_lock:
                app.settings.setdefault("thinking_capabilities", {})[model] = cached
                app._save_settings()
        current = app.settings.get("thinking_levels", {}).get(model, "__auto__")
        if current != "__auto__" and current not in cached.get("values", []):
            current = False if current is False and False in cached.get("values", []) else "__auto__"  # "on" from before levels
        return {"values": cached.get("values", []), "default": cached.get("default"), "current": current, "error": ""}

    def set_thinking(self, model, value):
        app = self._app
        model = str(model or "")
        options = app.settings.get("thinking_capabilities", {}).get(model, {}).get("values", [])
        if value != "__auto__" and value not in options:
            return {"ok": False, "error": "Модель не поддерживает такой уровень."}
        with app._state_lock:
            levels = app.settings.setdefault("thinking_levels", {})
            if value == "__auto__":
                levels.pop(model, None); OLLAMA_THINK_LEVELS.pop(model, None)
            else:
                levels[model] = value; OLLAMA_THINK_LEVELS[model] = value
            app._save_settings(); app._changed()
        return {"ok": True}

    def pick_path(self, kind):
        """Native folder/file picker for the code folder and the ComfyUI workflow."""
        import webview
        window = self._app.window
        if window is None:
            return ""
        if kind == "folder":
            result = window.create_file_dialog(webview.FOLDER_DIALOG)
        elif kind == "audio":
            result = window.create_file_dialog(webview.OPEN_DIALOG, file_types=("Запись голоса (*.wav)", "Все файлы (*.*)"))
        else:
            result = window.create_file_dialog(webview.OPEN_DIALOG, file_types=("ComfyUI workflow (*.json)", "Все файлы (*.*)"))
        return str(result[0]) if result else ""

    def open_data_folder(self, what="folder"):
        target = LOG_PATH if what == "log" and LOG_PATH.exists() else DATA_DIR
        os.startfile(str(target))
        return {"ok": True}

    def set_title_theme(self, dark):
        """Called by the page whenever its light/dark theme changes."""
        window = self._app.window
        return {"ok": bool(window is not None and style_title_bar(window, bool(dark)))}

    def route_hint(self, text):
        """Which action the companion would take for this text, shown under the composer."""
        app = self._app
        text = str(text or "")
        route = app._detect_composer_route(text)
        # Shown only when the companion will do something other than just answer.
        labels = {"presentation": "соберёт презентацию", "image": "нарисует через ComfyUI",
                  "video": "снимет видео через ComfyUI", "audio": "аудио пока не поддерживается"}
        if route == "code":
            label = f"поработает с кодом в папке {Path(app.settings.get('project_root', str(APP_DIR))).name or 'проекта'}"
        elif route == "chat" and app._is_computer_request(text):
            label = "сделает на компьютере"
        else:
            label = labels.get(route, "")
        return {"route": route, "label": label}

    def rename_chat(self, chat_id, title):
        app = self._app
        title = " ".join(str(title or "").split())[:80]
        with app._state_lock:
            chat = next((item for item in app.chats if item.get("id") == chat_id), None)
            if chat is None or not title:
                return {"ok": False, "error": "Не удалось переименовать чат."}
            chat["title"] = title
            chat["titled"] = True  # the model no longer names it
            app._save_conversation(); app._changed()
        return {"ok": True}

    # ---------- long-term memory ----------
    def memory_status(self):
        app = self._app
        job = dict(getattr(app, "_memory_job", {}) or {})
        return {"enabled": bool(app.settings.get("memory_enabled", True)), "facts": app.memory.facts(), "counts": app.memory.counts(),
                "modelReady": app.memory.model_ready(), "modelSize": "≈ 610 МБ", "modelName": app.memory.model_path.name, "job": job}

    def memory_set_enabled(self, enabled):
        with self._app._state_lock:
            self._app.settings["memory_enabled"] = bool(enabled); self._app._save_settings()
        return {"ok": True}

    def memory_add_fact(self, text):
        return {"ok": bool(self._app.memory.add("fact", str(text or "")))}

    def memory_delete(self, entry_id):
        self._app.memory.delete(int(entry_id))
        return {"ok": True}

    def memory_clear(self, kind=""):
        self._app.memory.clear(str(kind) or None)
        return {"ok": True}

    def memory_search_models(self, query=""):
        """Embedding models on Hugging Face (GGUF, sentence similarity / feature extraction), most downloaded first."""
        import json as json_module
        found = {}
        for task in ("sentence-similarity", "feature-extraction"):
            params = urllib.parse.urlencode([("search", str(query or "")), ("filter", "gguf"), ("pipeline_tag", task),
                                             ("sort", "downloads"), ("direction", "-1"), ("limit", "40")])
            try:
                with urllib.request.urlopen(urllib.request.Request("https://huggingface.co/api/models?" + params,
                                                                   headers={"User-Agent": "PIVEN-Companion/1.0"}), timeout=20) as response:
                    for item in json_module.loads(response.read().decode("utf-8")):
                        found.setdefault(item["id"], item.get("downloads", 0))
            except Exception as error:
                return {"ok": False, "error": f"Поиск не удался: {error}", "models": []}
        models = sorted(({"id": repo, "downloads": downloads} for repo, downloads in found.items()), key=lambda item: -item["downloads"])
        return {"ok": True, "models": models[:50]}

    def memory_model_files(self, repo):
        try:
            files = hf_models.list_gguf_files(str(repo))
            return {"ok": True, "files": files if isinstance(files, list) else []}
        except Exception as error:
            return {"ok": False, "error": str(error), "files": []}

    def memory_download_model(self, repo="", file_path="", size=0):
        """Download the embedding model (the user pressed the button that shows its size), then index the memory."""
        app = self._app
        import memory as long_memory
        if getattr(app, "_memory_job", {}).get("state") == "running":
            return {"ok": False, "error": "Уже скачивается."}
        app._memory_job = {"state": "running", "percent": 0, "message": "Подключение"}
        cancel = threading.Event()
        app._memory_cancel = cancel

        def work():
            try:
                source, name = (str(repo), str(file_path)) if repo and file_path else (long_memory.EMBED_REPO, long_memory.EMBED_FILE)
                record = next(item for item in hf_models.list_gguf_files(source) if item["path"] == name)
                total = int(record.get("size") or size or 0)
                target = app.memory.folder / "model" / Path(name).name
                hf_models._download_file(source, name.split("/"), target, total, "", cancel,
                                         lambda received: app._memory_job.update(percent=int(received * 100 / max(total, 1)),
                                                                                 message=f"Скачивание: {received / 2**20:.0f} из {total / 2**20:.0f} МБ"),
                                         lambda message: app._memory_job.update(message=message))
                app.memory.use_model(target)
                app._memory_job.update(message="Память переводится на поиск по смыслу")
                app.memory.index_missing(lambda done, total: app._memory_job.update(percent=int(done * 100 / max(total, 1)),
                                                                                     message=f"Обработка памяти: {done} из {total}"))
                app._memory_job = {"state": "done", "percent": 100, "message": "Готово: память ищет по смыслу"}
            except Exception as error:
                app._memory_job = {"state": "error", "percent": 0, "message": str(error)}
        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    def memory_cancel(self):
        cancel = getattr(self._app, "_memory_cancel", None)
        if cancel:
            cancel.set()
        return {"ok": True}

    # ---------- right-hand workspace ----------
    def run_code(self, language, code, stdin=""):
        """Run the editor's code on the user's click (in a temporary folder, time-limited)."""
        import workspace
        return workspace.run_code(APP_DIR, str(language), str(code), str(stdin or ""))

    def presentation_slides(self, path):
        """Slides of a presentation from the chat, for the viewer in the workspace."""
        import workspace
        path = str(path or "")
        if path not in self._app.known_files() or not path.lower().endswith(".pptx"):
            return {"ok": False, "slides": [], "error": "Этот файл не из чата."}
        try:
            return {"ok": True, "slides": workspace.presentation_slides(path)}
        except Exception as error:
            return {"ok": False, "slides": [], "error": f"Не удалось прочитать презентацию: {error}"}

    # ---------- tools: MCP servers and skills ----------
    def tools_status(self):
        app = self._app
        servers = []
        for entry in app.settings.get("mcp_servers", []):
            server = mcp_client.servers.get(entry.get("name"))
            servers.append({**{key: entry.get(key, "") for key in ("name", "command", "url")}, "env": entry.get("env") or {},
                            "enabled": entry.get("enabled", True), "error": server.error if server else "",
                            "tools": len(server._tools) if server and server._tools is not None else None})
        skills = [{"name": name, "folder": "", "description": description, "builtin": True, "body": ""} for name, description in tools.BUILTIN_SKILLS]
        skills += [{key: skill[key] for key in ("name", "folder", "description", "builtin", "body")}
                  for skill in tools.list_skills(APP_DIR, DATA_DIR) if skill["folder"] != "computer-control"]
        return {"enabled": bool(app.settings.get("tools_enabled", True)), "servers": servers, "skills": skills}

    def set_tools_enabled(self, enabled):
        with self._app._state_lock:
            self._app.settings["tools_enabled"] = bool(enabled); self._app._save_settings()
        return {"ok": True}

    def save_mcp_server(self, entry, old_name=""):
        """Add or change one MCP server ({name, command | url, env, enabled}); checks it by asking for its tools."""
        app = self._app
        entry = entry if isinstance(entry, dict) else {}
        name = re.sub(r"[^A-Za-z0-9_-]", "-", str(entry.get("name") or "").strip())[:32]
        command, url = str(entry.get("command") or "").strip(), str(entry.get("url") or "").strip()
        if not name or not (command or url):
            return {"ok": False, "error": "Нужны название и команда запуска (или адрес сервера)."}
        if url and not url.startswith(("http://", "https://")):
            return {"ok": False, "error": "Адрес должен начинаться с http:// или https://"}
        env = {str(k): str(v) for k, v in (entry.get("env") or {}).items() if str(k).strip()}
        clean = {"name": name, "command": "" if url else command, "url": url, "env": env, "enabled": bool(entry.get("enabled", True))}
        with app._state_lock:
            servers = [item for item in app.settings.get("mcp_servers", []) if item.get("name") not in (name, old_name)]
            servers.append(clean)
            app.settings["mcp_servers"] = servers
            mcp_client.configure(servers)
            app._save_settings()
        if not clean["enabled"]:
            return {"ok": True, "tools": 0}
        try:
            return {"ok": True, "tools": len(mcp_client.servers[name].tools())}
        except Exception as error:
            mcp_client.servers[name].error = str(error)
            return {"ok": False, "error": f"Сервер сохранён, но не ответил: {error}"}

    def delete_mcp_server(self, name):
        app = self._app
        with app._state_lock:
            app.settings["mcp_servers"] = [item for item in app.settings.get("mcp_servers", []) if item.get("name") != name]
            mcp_client.configure(app.settings["mcp_servers"])
            app._save_settings()
        return {"ok": True}

    def save_skill(self, name, description, instructions):
        try:
            return {"ok": True, "folder": tools.save_skill(DATA_DIR, name, description, instructions)}
        except Exception as error:
            return {"ok": False, "error": str(error)}

    def delete_skill(self, folder):
        try:
            tools.delete_skill(DATA_DIR, folder)
            return {"ok": True}
        except Exception as error:
            return {"ok": False, "error": str(error)}

    # ---------- other programs and cloud services ----------
    def providers_status(self):
        return {"providers": providers.status()}

    def set_provider(self, provider, enabled=None, url=None, key=None):
        """Change one provider. key: None keeps the saved one, "" removes it. Then its models are asked for."""
        app = self._app
        provider = str(provider)
        if provider not in providers.PROVIDERS:
            return {"ok": False, "error": "Неизвестный сервис."}
        with app._state_lock:
            saved = dict(app.settings.setdefault("providers", {}).get(provider, {}))
            if enabled is not None:
                saved["enabled"] = bool(enabled)
            if url is not None:
                url = str(url).strip().rstrip("/")
                if url and not url.startswith(("http://", "https://")):
                    return {"ok": False, "error": "Адрес должен начинаться с http:// или https://"}
                saved["url"] = url
            if key is not None:
                saved["key"] = providers.seal(key)
            app.settings["providers"][provider] = saved
            providers.config[provider] = saved
            app._save_settings()
        app.refresh_models()
        row = next(item for item in providers.status() if item["id"] == provider)
        return {"ok": not row["error"], "error": row["error"], "models": row["models"]}

    # ---------- model parameters ----------
    def model_params(self, model=""):
        """Everything the parameters page needs: preset values, limits, the changes for all models and for this one."""
        app = self._app
        model = str(model or app.settings.get("model", ""))
        saved = app.settings.get("model_params", {})
        return {"model": model, "defaults": llama_backend.DEFAULT_PARAMS, "limits": llama_backend.PARAM_LIMITS,
                "choices": {key: list(values) for key, values in llama_backend.CHOICES.items()},
                "presets": llama_backend.PRESETS, "serverKeys": list(llama_backend.SERVER_KEYS),
                "all": saved.get("*", {}), "own": saved.get(model, {}), "effective": llama_backend.params_for(model),
                "autoTitles": bool(app.settings.get("auto_titles", True))}

    def set_model_params(self, scope, values, replace=False):
        """Save parameter changes for all models (scope "*") or one model; `replace` drops the earlier ones
        (a preset or a reset). The running model restarts with them on its next answer when loading ones changed."""
        app = self._app
        scope = str(scope or "*")
        values = values if isinstance(values, dict) else {}
        with app._state_lock:
            saved = app.settings.setdefault("model_params", {})
            current = {} if replace else dict(saved.get(scope, {}))
            current.update(llama_backend.clean_params(values))
            # nothing equal to the preset needs keeping
            base = llama_backend.DEFAULT_PARAMS if scope == "*" else {**llama_backend.DEFAULT_PARAMS, **saved.get("*", {})}
            current = {key: value for key, value in current.items() if base.get(key) != value}
            if current:
                saved[scope] = current
            else:
                saved.pop(scope, None)
            llama_backend.model_params.clear()
            llama_backend.model_params.update(saved)
            app._save_settings(); app._changed()
        return {"ok": True}

    def recommended_model(self):
        """The first model to download, chosen for this computer's video card (the welcome screen)."""
        try:
            found = hf_models.recommended(memory_estimate.gpu_memory())
        except Exception as error:
            return {"ok": False, "error": str(error)}
        return {"ok": bool(found), **(found or {}), "error": "" if found else "Нет связи с Hugging Face."}

    def set_language(self, language):
        """The interface language; the model answers in it too."""
        if language not in ("ru", "en", "zh", "es"):
            return {"ok": False}
        with self._app._state_lock:
            if self._app.settings.get("ui_language") != language:
                self._app.settings["ui_language"] = language; self._app._save_settings()
        return {"ok": True}

    def set_auto_titles(self, enabled):
        with self._app._state_lock:
            self._app.settings["auto_titles"] = bool(enabled)
            self._app._save_settings()
        return {"ok": True}

    def reset_settings(self):
        """Back to the recommended settings. Chats, downloaded models and the chosen chat, voice and
        recognition models stay; everything else (prompt, voice, microphone, parameters, integrations) resets."""
        app = self._app
        if app.any_busy or app.running:
            return {"ok": False, "error": "Сначала дождись конца ответа и заверши звонок."}
        keep = ("model", "asr_model", "tts_model", "project_root", "tray_hint_shown")
        with app._state_lock:
            kept = {key: app.settings[key] for key in keep if key in app.settings}
            companion_core.SETTINGS_PATH.write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")
            app._load_settings(getattr(app, "_theme_ids", None))
            app._save_settings(); app._changed()
        return {"ok": True}

    def pin_chat(self, chat_id, pinned):
        app = self._app
        with app._state_lock:
            chat = next((item for item in app.chats if item.get("id") == chat_id), None)
            if chat is None:
                return {"ok": False}
            chat["pinned"] = bool(pinned)
            app._save_conversation(); app._changed()
        return {"ok": True}

    def image_data(self, path):
        """Return a data: URL for an image from a chat or one the user attached."""
        path = str(path or "")
        file = Path(path)
        if path not in self._app.known_files() or not file.is_file():
            return ""
        mime = mimetypes.guess_type(file.name)[0] or ""
        if not mime.startswith(("image/", "video/")):  # short generated videos play from a data URL too
            return ""
        if file.stat().st_size > (MAX_IMAGE_BYTES * 5 if mime.startswith("video/") else MAX_IMAGE_BYTES):
            return ""
        return f"data:{mime};base64," + base64.b64encode(file.read_bytes()).decode("ascii")

    def open_file(self, path):
        """Open a generated image or presentation with its Windows app."""
        path = str(path or "")
        if path not in self._app.known_files() or not Path(path).is_file():
            return {"ok": False}
        os.startfile(path)
        return {"ok": True}

    def save_copy(self, path):
        """Save a copy of a chat file (image, presentation) where the user chooses."""
        import webview
        path = str(path or "")
        source = Path(path)
        window = self._app.window
        if path not in self._app.known_files() or not source.is_file() or window is None:
            return {"ok": False, "error": "Файл не найден."}
        downloads = Path.home() / "Downloads"
        result = window.create_file_dialog(webview.SAVE_DIALOG, directory=str(downloads if downloads.is_dir() else Path.home()),
                                           save_filename=source.name)
        target = result if isinstance(result, str) else (result[0] if result else "")
        if not target:
            return {"ok": False, "cancelled": True}
        destination = Path(target)
        if destination.suffix.lower() != source.suffix.lower():
            destination = destination.with_suffix(source.suffix)
        try:
            shutil.copy2(source, destination)
        except OSError as error:
            return {"ok": False, "error": f"Не удалось сохранить: {error}"}
        return {"ok": True, "path": str(destination)}

    # ---------- chats ----------
    def delete_chat(self, chat_id):
        app = self._app
        with app._state_lock:
            if str(chat_id) in app._busy_chats:
                return {"ok": False, "error": "В этом чате ещё идёт ответ. Дождись его или останови."}
            app.delete_chat(str(chat_id)); app._changed()
        return {"ok": True}

    def export_chat(self, chat_id, markdown=True):
        import webview
        app = self._app
        chat = next((item for item in app.chats if item.get("id") == chat_id), None)
        if chat is None or app.window is None:
            return {"ok": False, "error": "Чат не найден."}
        suffix = ".md" if markdown else ".txt"
        safe_name = re.sub(r'[<>:"/\\|?*]+', "_", chat.get("title") or "Чат").strip(" .") or "Чат"
        result = app.window.create_file_dialog(webview.SAVE_DIALOG, save_filename=safe_name + suffix,
                                               file_types=("Markdown (*.md)",) if markdown else ("Текстовый файл (*.txt)",))
        target = result if isinstance(result, str) else (result[0] if result else "")
        if not target:
            return {"ok": False, "cancelled": True}
        destination = Path(target)
        if destination.suffix.lower() != suffix:
            destination = destination.with_suffix(suffix)
        try:
            destination.write_text(app.export_chat_text(chat_id, markdown), encoding="utf-8")
        except OSError as error:
            return {"ok": False, "error": f"Не удалось сохранить файл: {error}"}
        return {"ok": True, "path": str(destination)}

    def search_messages(self, query):
        with self._app._state_lock:
            return self._app.search_messages(query)

    def retry_last(self):
        app = self._app
        with app._state_lock:
            ok = app.retry_last_answer(app.settings.get("model", "").strip())
            app._changed()
        return {"ok": ok, "error": "" if ok else "Нечего повторять или идёт другое действие."}

    def undo_files(self, index):
        """Delete the files and folders the request behind one answer made (only ones unchanged since)."""
        app = self._app
        with app._state_lock:
            items = app.dialogue_items
            item = items[int(index)] if 0 <= int(index) < len(items) else None
            record = (item or {}).get("undo") or []
            if not record:
                return {"ok": False, "error": "Здесь нечего отменять."}
            try:
                removed, kept = app.undo_files(record)
            except OSError as error:
                return {"ok": False, "error": f"Не удалось удалить: {error}"}
            item.pop("undo", None)
            note = f"Отменено: удалено файлов и папок — {len(removed)}."
            if kept:
                note += f" Оставлено {len(kept)}: они изменены после этого или в папке есть другие файлы."
            app._record("system", note)
        return {"ok": True}

    def edit_message(self, index, text):
        """Replace one of the user's messages: it and everything after it leave the chat, the new text is sent."""
        app = self._app
        with app._state_lock:
            cut = app.cut_history_at(int(index))
            if cut is None:
                return {"ok": False, "error": "Это сообщение нельзя изменить: идёт ответ или оно уже в кратком содержании."}
            _old_text, images = cut
            images = [path for path in images if Path(path).is_file()]
            app._allowed_files |= set(images)   # they left the chat's items with the old message; they go with the new one
            app._changed()
        return app.send(text, images)

    def speak(self, text):
        threading.Thread(target=self._app._speak, args=(str(text or ""),), daemon=True).start()
        return {"ok": True}

    # ---------- attachments ----------
    def pick_images(self):
        import webview
        window = self._app.window
        if window is None:
            return []
        result = window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=True,
                                           file_types=("Изображения (*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.gif;*.tif;*.tiff)",))
        paths = [str(path) for path in (result or []) if str(path).lower().endswith(IMAGE_SUFFIXES)]
        with self._app._state_lock:
            self._app._allowed_files.update(paths)
        return paths

    def save_upload(self, name, data_b64):
        """Store an image pasted or dropped into the page, return its local path."""
        name = str(name or "image.png")
        suffix = Path(name).suffix.lower() if Path(name).suffix.lower() in IMAGE_SUFFIXES else ".png"
        try:
            data = base64.b64decode(str(data_b64 or ""), validate=True)
        except ValueError:
            return {"ok": False, "error": "Не удалось прочитать файл."}
        if not data or len(data) > MAX_UPLOAD_BYTES:
            return {"ok": False, "error": "Картинка пустая или больше 20 МБ."}
        folder = DATA_DIR / "pasted_images"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}{suffix}"
        path.write_bytes(data)
        try:
            from PIL import Image
            with Image.open(path) as image:
                image.verify()
        except Exception:
            path.unlink(missing_ok=True)
            return {"ok": False, "error": "Это не изображение."}
        with self._app._state_lock:
            self._app._allowed_files.add(str(path))
        return {"ok": True, "path": str(path)}

    def send_message(self, text, image_paths):
        return self._app.send(text, image_paths)

    # ---------- listening ----------
    def start_listening(self, options):
        app = self._app
        options = options if isinstance(options, dict) else {}
        with app._state_lock:
            error = app.start_listening(tuple(bool(options.get(key)) for key in ("mic", "loopback", "screen", "proactive")),
                                        app.settings.get("model", "").strip())
            app._changed()
        return {"ok": not error, "error": error}

    def set_mic_muted(self, muted):
        with self._app._state_lock:
            self._app.mic_muted = bool(muted); self._app._changed()
        return {"ok": True}

    def stop_listening(self):
        with self._app._state_lock:
            # Hang up at once; the capture thread finishes in the background (start_listening waits for it).
            self._app.stop_listening(); self._app.running = False; self._app._changed()
        return {"ok": True}

    def answer_confirmation(self, confirm_id, approved):
        app = self._app
        with app._state_lock:
            if not app._confirm or app._confirm.get("id") != confirm_id:
                return {"ok": False}
            app._confirm_result = bool(approved)
        app._confirm_answer.set()
        return {"ok": True}

    # ---------- Twitch (token is used for the one request and never stored) ----------
    def twitch_status(self):
        settings = self._app.settings
        return {"status": twitch_core.limit_status(settings), "channel": settings.get("twitch_channel", ""),
                "enabled": settings.get("integrations_enabled", {}).get("twitch", True),
                "maxChars": twitch_core.MAX_MESSAGE_CHARS}

    def open_twitch_help(self):
        import webbrowser
        webbrowser.open("https://dev.twitch.tv/docs/chat/authenticating/")
        return {"ok": True}

    # ---------- built-in browser pane ----------
    @staticmethod
    def _web_url(url):
        clean = str(url or "").strip()
        return clean if re.match(r"^https?://[^\s]+$", clean, re.I) else ""

    def open_url(self, url):
        """Open an http(s) address in the system browser."""
        import webbrowser
        clean = self._web_url(url)
        if not clean:
            return {"ok": False, "error": "Это не адрес сайта."}
        webbrowser.open(clean)
        return {"ok": True}

    def _native_browser(self):
        if self._browser is None and self._app.window is not None:
            import native_browser
            self._browser = native_browser.NativeBrowser(self._app.window, str(DATA_DIR / "browser_profile"))
        return self._browser

    def browser_place(self, x, y, width, height, visible):
        """Lay the browser control over the page's empty box (coordinates in device pixels)."""
        browser = self._native_browser()
        if browser is None:
            return {"ok": False, "error": "Окно ещё не готово."}
        browser.place(float(x), float(y), float(width), float(height), bool(visible))
        return {"ok": True}

    def browser_go(self, url):
        clean = self._web_url(url)
        browser = self._native_browser()
        if not clean or browser is None:
            return {"ok": False, "error": "Это не адрес сайта."}
        browser.navigate(clean)
        return {"ok": True}

    def browser_command(self, name):
        browser = self._native_browser()
        if browser is not None and name in ("back", "forward", "reload", "stop"):
            browser.command(name)
        return {"ok": True}

    def browser_state(self):
        browser = self._native_browser()
        return browser.state() if browser else {"url": "", "title": "", "loading": False, "canBack": False, "canForward": False, "notice": ""}

    def twitch_poll(self, channel, question, choices, seconds, token):
        """Start a poll for the stream's viewers (the token is used for this request only and not stored)."""
        app = self._app
        channel = str(channel or app.settings.get("twitch_channel", "")).strip().lstrip("#")
        if not app.settings.get("integrations_enabled", {}).get("twitch", True):
            return {"ok": False, "error": "Интеграция Twitch выключена в настройках."}
        if not twitch_core.valid_channel(channel):
            return {"ok": False, "error": "Укажи свой канал в настройках → Интеграции."}
        if not str(token or "").strip():
            return {"ok": False, "error": "Вставь OAuth-токен с разрешением channel:manage:polls."}
        try:
            return {"ok": True, "message": twitch_core.create_poll(channel, str(question), list(choices or []), int(seconds or 120), str(token).strip())}
        except Exception as error:
            return {"ok": False, "error": str(error)}

    def answer_poll(self, question, choice):
        """The user picked an option on a poll card: it goes to the model as their message."""
        return self.send(f"Мой ответ на опрос «{question}»: {choice}")

    def twitch_send(self, channel, message, token):
        app = self._app
        channel = str(channel or "").strip().lstrip("#")
        message = str(message or "").strip()
        token = str(token or "").strip()
        if not app.settings.get("integrations_enabled", {}).get("twitch", True):
            return {"ok": False, "error": "Интеграция Twitch выключена в настройках."}
        if not twitch_core.valid_channel(channel):
            return {"ok": False, "error": "Название канала: только латинские буквы, цифры и _."}
        if not token:
            return {"ok": False, "error": "Вставь OAuth-токен с разрешением user:write:chat."}
        if not message or len(message) > twitch_core.MAX_MESSAGE_CHARS:
            return {"ok": False, "error": f"Сообщение от 1 до {twitch_core.MAX_MESSAGE_CHARS} символов."}
        with app._state_lock:
            allowed, why = twitch_core.reserve_slot(app.settings, channel, message, app._save_settings)
        if not allowed:
            return {"ok": False, "error": why, "status": twitch_core.limit_status(app.settings)}
        try:
            result = twitch_core.send_once(channel, message, token)
            return {"ok": True, "message": result, "status": twitch_core.limit_status(app.settings)}
        except Exception as error:
            return {"ok": False, "error": str(error), "status": twitch_core.limit_status(app.settings)}

    # ---------- Hugging Face models ----------
    def hf_search(self, query, token=""):
        try:
            return {"ok": True, "models": hf_models.search_models(query, str(token or "").strip())}
        except Exception as error:
            return {"ok": False, "error": str(error), "models": []}

    def hf_files(self, repo_id, token=""):
        try:
            files = hf_models.list_gguf_files(repo_id, str(token or "").strip())
            tag = hf_models.suggested_tag(repo_id, files[0]["path"]) if files else ""
            return {"ok": True, "files": files, "tag": tag}
        except Exception as error:
            return {"ok": False, "error": str(error), "files": []}

    def hf_suggest_tag(self, repo_id, file_path):
        return hf_models.suggested_tag(repo_id, file_path)

    def hf_start(self, repo_id, record, tag, token=""):
        return self._app.start_hf_download(str(repo_id or ""), record if isinstance(record, dict) else {},
                                           str(tag or ""), str(token or "").strip())

    def hf_status(self):
        with self._app._state_lock:
            return dict(self._app._hf)

    def hf_cancel(self):
        self._app._hf_cancel.set()
        return {"ok": True}

    # ---------- voice engines ----------
    def voice_status(self):
        app = self._app
        with app._state_lock:
            job = dict(app._voice)
            selected = {"asr": app.settings.get("asr_model"), "tts": app.settings.get("tts_model")}
        catalogue = voice_install.status()
        for kind in ("asr", "tts"):
            catalogue[kind]["selected"] = selected[kind]
        return {**catalogue, "job": job, "gpu": memory_estimate.gpu_memory()}

    def voice_install(self, kind, model_id, extra=None, token=""):
        return self._app.start_voice_install(str(kind or ""), str(model_id or ""), extra, str(token or "").strip())

    def model_description(self, repo_id, token=""):
        """A short description of a Hugging Face model from its card (for chat and voice models)."""
        repo_id = str(repo_id or "")
        if repo_id.startswith("audiocpp:"):
            return {"text": "", "source": ""}
        return hf_models.model_description(repo_id, str(token or "").strip())

    def voice_search(self, kind, query, token=""):
        try:
            return {"ok": True, "models": voice_install.search(str(kind), str(query or ""), str(token or "").strip())}
        except Exception as error:
            return {"ok": False, "error": str(error), "models": []}

    def voice_details(self, kind, repo, engine, token=""):
        try:
            return {"ok": True, **voice_install.details(str(kind), str(repo), str(engine), str(token or "").strip())}
        except Exception as error:
            return {"ok": False, "error": str(error)}

    def restart_app(self):
        """Close the program and open it again (after changing the voice or recognition model)."""
        threading.Timer(0.3, restart_program, (self._app,)).start()
        return {"ok": True}

    def voice_select(self, kind, model_id):
        app = self._app
        key = {"asr": "asr_model", "tts": "tts_model"}.get(str(kind))
        if not key or not voice_install.known(kind, model_id):
            return {"ok": False, "error": "Неизвестная модель."}
        if not voice_install.ready(kind, model_id):
            return {"ok": False, "error": "Сначала скачай эту модель."}
        with app._state_lock:
            changed = app.settings.get(key) != model_id
            app.settings[key] = model_id
            if kind == "tts":
                voices = [value for value, _ in voice_install.tts_voices(model_id)]
                if app.settings.get("voice") not in voices:
                    app.settings["voice"] = voices[0]
            app._save_settings(); app._changed()
        # A running voice server keeps the old model until the program restarts; the page offers to do it now.
        return {"ok": True, "error": "", "restart": changed}

    def delete_model(self, name):
        """Delete a local chat model from disk."""
        app = self._app
        name = str(name or "")
        if llama_backend.model_in_use(name):
            return {"ok": False, "error": "Эта модель сейчас отвечает. Дождись конца ответа или останови его."}
        try:
            freed = llama_backend.delete_model(name)
        except Exception as error:
            return {"ok": False, "error": str(error)}
        app.refresh_models()
        app._changed()
        return {"ok": True, "freed": freed}

    def voice_delete(self, kind, model_id):
        """Delete a downloaded voice model from disk; the one in use falls back to the standard model."""
        app = self._app
        kind, model_id = str(kind), str(model_id)
        key = {"asr": "asr_model", "tts": "tts_model"}.get(kind)
        if not key:
            return {"ok": False, "error": "Неизвестный вид модели."}
        job = app._voice
        if job.get("state") == "running" and job.get("id") == model_id:
            return {"ok": False, "error": "Эта модель сейчас скачивается."}
        selected = app.settings.get(key) == model_id
        if selected and (app.running or app.tts_playing.is_set()):
            return {"ok": False, "error": "Модель сейчас используется. Заверши звонок и повтори."}
        if selected:  # its server may hold the files open
            app._stop_owned_model_process("asr_process" if kind == "asr" else "tts_process", "голосовая модель")
        try:
            freed = voice_install.delete(kind, model_id)
        except Exception as error:
            return {"ok": False, "error": str(error)}
        if selected:
            with app._state_lock:
                app.settings[key] = voice_install.DEFAULT_ASR if kind == "asr" else voice_install.DEFAULT_TTS
                app._save_settings()
        app._changed()
        return {"ok": True, "freed": freed}

    def disk_usage(self):
        """What the program's models and voice engines take on disk."""
        try:
            sizes = llama_backend.model_sizes()
            voice = voice_install.disk_usage()
            return {"ok": True, "models": [{"name": name, "bytes": size} for name, size in sorted(sizes.items(), key=lambda item: -item[1])],
                    "voiceModels": voice["models"], "engines": voice["engines"]}
        except Exception as error:
            log(f"disk usage error: {error}")
            return {"ok": False, "error": str(error), "models": [], "voiceModels": 0, "engines": []}

    @staticmethod
    def _model_features(wanted=None):
        """{model: {"vision", "thinking", "context"}} of local models for the marks in the model menu."""
        features = {}
        for name in llama_backend.model_files():
            if wanted is not None and name not in wanted:
                continue
            try:
                values, default = llama_backend.thinking_modes(name)
            except Exception:
                values, default = [], None
            features[name] = {"vision": llama_backend.has_vision(name), "thinking": bool(values) or default is True,
                              "context": llama_backend.context_size(name)}
        return features

    def model_memory(self, names=None):
        """Estimated video memory of local models once loaded, and the GPU's total."""
        try:
            wanted = None if names is None else {str(name) for name in names}
            reserved = self._app.voice_vram()
            llama_backend.reserved_vram[0] = reserved
            return {"gpu": memory_estimate.gpu_memory(), "context": llama_backend.context_size(self._app.settings.get("model", "")),
                    "models": llama_backend.memory_estimates(wanted), "voiceReserved": reserved,
                    "features": self._model_features(wanted)}
        except Exception as error:
            log(f"model memory error: {error}")
            return {"gpu": 0, "context": 0, "models": {}}

    def context_usage(self):
        """How much of the model's context the current chat fills, by the same estimate the app uses to decide
        what to fold into the summary (about CHARS_PER_TOKEN characters per token, a fixed cost per picture)."""
        try:
            app = self._app
            model = str(app.settings.get("model", ""))
            with app._state_lock:
                messages = list(app.messages)
                summary = str(app._chat_summary() or "")
            turns = messages[1:]
            per_token = companion_core.CHARS_PER_TOKEN

            def tokens(characters):
                return int(round(characters / per_token))
            images = sum(len(item.get("images") or []) for item in turns)
            # What an ordinary answer adds: the skill list in the instructions and the tool definitions sent along.
            skills_chars = tools_chars = 0
            tools_names, waiting = 0, []
            if app.settings.get("tools_enabled", True):
                try:
                    toolbox = tools.ToolBox(APP_DIR, DATA_DIR, app.tool_browser(),
                                            memory=app.memory if app.settings.get("memory_enabled", True) else None)
                    specs = toolbox.specs(start_servers=False)  # servers that are not running are not started just to count
                    skills_chars = len(toolbox.skills_prompt())
                    tools_chars = len(json.dumps(specs, ensure_ascii=False))
                    tools_names, waiting = len(specs), list(toolbox.unstarted)
                except Exception as error:
                    log(f"context tools count error: {error}")
            parts = {"system": tokens(len(str(messages[0].get("content", ""))) if messages else 0),
                     "summary": tokens(len(summary)),
                     "skills": tokens(skills_chars),
                     "tools": tokens(tools_chars),
                     "history": tokens(sum(len(str(item.get("content", ""))) for item in turns)),
                     "images": tokens(1500 * images)}
            cloud = providers.is_provider_model(model)
            return {"ok": True, "model": model, "cloud": cloud, "parts": parts, "used": sum(parts.values()),
                    "turns": len(turns), "images": images, "toolCount": tools_names, "serversWaiting": waiting,
                    "limit": 0 if cloud or not model else llama_backend.context_size(model),
                    "historyShare": companion_core.HISTORY_SHARE, "compress": bool(llama_backend.params_for(model)["compress_context"]) if model and not cloud else False}
        except Exception as error:
            log(f"context usage error: {error}")
            return {"ok": False, "error": str(error)}

    def hf_memory(self, repo_id, file_path, size, token=""):
        """The same estimate for a file on Hugging Face, from the first megabytes of its header."""
        try:
            meta = memory_estimate.remote_metadata(str(repo_id), str(file_path), str(token or "").strip())
            context = llama_backend.context_size()
            return {"gpu": memory_estimate.gpu_memory(), "context": context,
                    "estimate": memory_estimate.estimate(int(size or 0), meta, context),
                    "known": bool(meta)}
        except Exception as error:
            log(f"hf memory error: {error}")
            return {"gpu": 0, "context": 0, "estimate": None, "known": False}

    def model_logos(self, names, authors=None, architectures=None):
        names = [str(name) for name in names or []][:200]
        architectures = dict(architectures) if isinstance(architectures, dict) else {}
        try:
            local = llama_backend.model_files()
            for name in names:  # a local model: its own GGUF says what it is built on
                if name in local and name not in architectures:
                    architectures[name] = llama_backend.gguf_metadata(local[name][0], ("general.architecture",)).get("general.architecture", "")
        except Exception as error:
            log(f"model architecture error: {error}")
        try:
            return model_logos.logos(names, authors if isinstance(authors, dict) else {}, architectures)
        except Exception as error:
            log(f"model logos error: {error}")
            return {}

    def voice_cancel(self):
        self._app._voice_cancel.set()
        return {"ok": True}

    def copy_text(self, text):
        # WebView2 clipboard access from a file page is unreliable; use the Windows clipboard.
        import subprocess
        subprocess.run(["clip"], input=str(text).encode("utf-16-le"), check=False,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"ok": True}


def restart_program(app):
    """Start a fresh copy of this window and close this one; the new copy waits for the instance lock."""
    flags = 0x00000008 | 0x00000200 | 0x01000000  # detached, own process group, outside our job object
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    subprocess.Popen([str(pythonw if pythonw.is_file() else sys.executable), str(Path(__file__).resolve()), "--restarted"],
                     cwd=str(APP_DIR), creationflags=flags, close_fds=True)
    app._quitting = True
    if app.window is not None:
        app.window.destroy()


def main():
    import webview
    if not UI_INDEX.is_file():
        webview.create_window(APP_NAME, html="<h3 style='font-family:Segoe UI'>Не найдена сборка modern-ui/dist. "
                                             "Запусти modern-ui\\scripts\\build.cmd.</h3>")
        webview.start()
        return
    if not acquire_instance_lock(wait=30 if "--restarted" in sys.argv else 0):
        webview.create_window(APP_NAME, html="<h3 style='font-family:Segoe UI'>Компаньон уже открыт (обычное или веб-окно). "
                                             "Закрой его, чтобы не перезаписать чаты.</h3>", width=620, height=200)
        webview.start()
        return
    # The page is served from the same address on every start without cache headers, so WebView2 may keep an
    # older build of app.js and app.css. Its HTTP cache is dropped before the window opens (storage stays).
    shutil.rmtree(companion_core.DATA_DIR / "webview" / "EBWebView" / "Default" / "Cache", ignore_errors=True)
    app = WebCompanion()
    threading.Thread(target=app.refresh_models, daemon=True).start()
    window = webview.create_window(WINDOW_TITLE, url=str(UI_INDEX), js_api=WebApi(app),
                                   width=1440, height=900, min_size=(960, 640), background_color="#0a0a0a")
    app.window = window
    window.events.shown += lambda: style_title_bar(window, dark=True)

    def open_window():
        app._hidden = False
        window.show(); window.restore()

    def quit_program():
        app._quitting = True
        window.destroy()

    try:
        import tray
        app.tray = tray.Tray(APP_DIR / "assets" / "piven.ico", WINDOW_TITLE, open_window, quit_program)
    except Exception as error:
        log(f"tray icon error: {error}")

    def on_closing():
        # The close button hides the window to the tray (setting "close_to_tray"); the tray menu quits for real.
        if app.tray and app.settings.get("close_to_tray", True) and not app._quitting:
            window.hide(); app._hidden = True
            if not app.settings.get("tray_hint_shown"):
                app.tray.notify("PIVEN работает в фоне", "Значок в трее: щелчок открывает окно, правая кнопка — «Выйти».")
                with app._state_lock:
                    app.settings["tray_hint_shown"] = True; app._save_settings()
            return False
        app.shutdown()
        if app.tray:
            app.tray.close()
    window.events.closing += on_closing
    webview.start(private_mode=False, storage_path=str(companion_core.DATA_DIR / "webview"))


if __name__ == "__main__":
    main()
