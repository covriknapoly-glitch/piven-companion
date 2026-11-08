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

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if __name__ == "__main__":
    from app import paths
    paths.migrate()

from app.chat import engine as core
from app.chat.engine import (APP_DIR, APP_NAME, COMFY_DEFAULT_WORKFLOW, COMPANION_SYSTEM_PROMPT, DATA_DIR, LOG_PATH,
                            THINKING_LEVELS, CompanionCore, acquire_instance_lock, bounded_int, encode_chat_image,
                            log, list_models, backend_problem, model_thinking)
from app.models import huggingface
from app.models import llama
from app.models import memory_fit
from app.tools import mcp
from app.models import logos
from app.models import integrations
from app.tools import toolbox as tools
from app.voice import install

UI_INDEX = APP_DIR / "ui" / "dist" / "index.html"
WINDOW_TITLE = "PIVEN Companion"
MAX_IMAGE_BYTES = 12_000_000
MAX_UPLOAD_BYTES = 20_000_000
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")
APP_ICON = APP_DIR / "assets" / "piven.ico"
APP_ID = "PIVEN.Companion"


def style_title_bar(window, caption="#111111", text="#eeeeee", dark=True):
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = wintypes.HWND(int(window.native.Handle.ToInt64()))
        dwm = ctypes.windll.dwmapi

        def set_attribute(attribute, value):
            data = ctypes.c_int(value)
            return dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data))

        def colorref(color):
            rgb = int(color.strip().lstrip("#"), 16)
            return ((rgb & 0xFF) << 16) | (rgb & 0xFF00) | ((rgb >> 16) & 0xFF)

        set_attribute(20, 1 if dark else 0)
        results = [set_attribute(35, colorref(caption)),
                   set_attribute(36, colorref(text)),
                   set_attribute(34, colorref(caption))]
        return all(result == 0 for result in results)
    except Exception as error:
        log(f"title bar styling skipped: {error}")
        return False


def set_window_icon(window):
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        hwnd = int(window.native.Handle.ToInt64())
        for kind, metric in ((0, 49), (1, 11)):
            size = user32.GetSystemMetrics(metric)
            icon = user32.LoadImageW(None, str(APP_ICON), 1, size, size, 0x10)
            user32.SendMessageW(hwnd, 0x0080, kind, icon)
    except Exception as error:
        log(f"window icon skipped: {error}")


IMAGE_ONLY_PROMPTS = {False: "Посмотри на это изображение и коротко расскажи, что на нём.",
                      True: "Посмотри на эти изображения и коротко расскажи, что на них."}


class WebCompanion(CompanionCore):

    def __init__(self):
        self.route_events_by_chat = True
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
        self._allowed_files = set()
        self._confirm = None
        self._confirm_answer = threading.Event()
        self._browser_request = None
        self.tray = None
        self._quitting = False
        self._hidden = False
        self._confirm_result = False
        self._hf = {"state": "idle", "percent": 0, "message": "", "tag": "", "path": "", "error": ""}
        self._hf_cancel = threading.Event()
        self._voice = {"kind": "", "id": "", "state": "idle", "percent": 0, "message": "", "error": ""}
        self._voice_cancel = threading.Event()

    def _changed(self):
        self._version += 1

    def _show_error(self, chat_id, text):
        if chat_id == self.active_chat_id:
            self._record("error", str(text))
        else:
            self.append_to_chat(chat_id, "error", str(text))
            self._changed()

    def known_files(self):
        with self._state_lock:
            files = {str(path) for chat in self.chats for item in chat.get("items", []) for path in item.get("images") or []}
            return files | self._allowed_files

    def snapshot(self):
        with self._state_lock:
            active = self._active_chat() or {}
            chats = sorted(reversed(self.chats), key=lambda chat: not chat.get("pinned"))
            return {
                "version": self._version,
                "activeChatId": self.active_chat_id,
                "chats": [{"id": chat.get("id"), "title": chat.get("title") or "Новый чат",
                           "pinned": bool(chat.get("pinned")), "count": len(chat.get("items", [])),
                           "busy": chat.get("id") in self._busy_chats, "unread": bool(chat.get("unread")),
                           "model": chat.get("model", ""), "updated": chat.get("updated", 0),
                           "code": bool(chat.get("code_on")), "root": str(chat.get("code_root") or ""),
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
                "dictation": self.dictation,
                "code": self._code_state(active),
                "confirm": self._confirm,
                "downloads": self._downloads(),
                "browserRequest": self._browser_request,
                "activity": self._activity,
                "status": self._status,
                "reasoning": self._reasoning,
                "notice": self._notice,
                "models": self._models,
                "modelsError": self._models_error,
                "queue": [{"text": str(entry[0]), "images": len(entry[3] or [])} for entry in self.pending_text_prompts],
                "settings": {
                    "model": self.settings.get("model", ""),
                    "speechEnabled": bool(self.speech_enabled),
                    "heavyMode": self.heavy_mode,
                    "projectRoot": self.settings.get("project_root", ""),
                    "comfyUrl": self.settings.get("comfy_url", ""),
                    "voice": self.settings.get("voice", ""),
                    "theme": self.settings.get("canvas_theme", ""),
                    "systemPrompt": self.settings.get("system_prompt", ""),
                    "integrations": dict(self.settings.get("integrations_enabled", {})),
                    "thinkingLevel": self.settings.get("thinking_levels", {}).get(self.settings.get("model", ""), "__auto__"),
                },
            }

    def _code_state(self, chat):
        root = str(chat.get("code_root") or "")
        mode = self._code_mode(chat, root)
        return {"on": bool(chat.get("code_on")), "root": root, "mode": mode, "trusted": mode != "ask"}

    @staticmethod
    def _attach_undo(items, record):
        answer = next((item for item in reversed(items) if isinstance(item, dict) and item.get("role") == "assistant"), None)
        if answer is not None:
            answer["undo"] = record

    def _background_event(self, chat_id, kind, value):
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
        elif kind == "code_picture":
            self.append_to_chat(chat_id, "system", "Снимок результата", [str(value)])
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
        if not self.tray or not self.settings.get("notifications", True):
            return
        try:
            from app.window import tray
            if self._hidden or tray.foreground_title() != WINDOW_TITLE:
                self.tray.notify(title, " ".join(core.speech_text(text).split())[:220])
        except Exception as error:
            log(f"notification error: {error}")

    def tool_browser(self):
        return ModelBrowser(self)

    def _downloads(self):
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

    def _call_flags(self):
        hearing = self.running and not self.mic_muted and time.monotonic() - getattr(self, "last_mic_activity", 0.0) < 0.9
        return bool(self.tts_playing.is_set()), bool(hearing), bool(self.mic_muted)

    def pump_events(self):
        with self._state_lock:
            flags = self._call_flags()
            if flags != getattr(self, "_last_call_flags", None):
                self._last_call_flags = flags
                self._changed()
            if self.busy != (self._busy_since is not None):
                self._busy_since = time.time() if self.busy else None
                self._changed()
            while True:
                try:
                    kind, value = self.events.get_nowait()
                except Exception:
                    break
                if kind == "chat_event":
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
                elif kind == "code_picture":
                    self._record("system", "Снимок результата", [str(value)])
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
                elif kind == "chats_code":
                    self._changed()
                elif kind == "asr":
                    self.handle_transcript(value, self.settings.get("model", "").strip())
                elif kind in ("stopped", "capture_failed"):
                    self.running = False
                    self._activity = "Прослушивание остановлено"
                elif kind == "request_done":
                    self._save_conversation()
                    self.busy = False
                    if self.pending_code_prompts:
                        text = "\n".join(f"- {item}" for item in self.pending_code_prompts) if len(self.pending_code_prompts) > 1 else self.pending_code_prompts[0]
                        self.pending_code_prompts.clear()
                        self.busy = True
                        self._activity = "Агент берётся за новые сообщения"
                        threading.Thread(target=self._run_coding_agent, args=(text, self.settings.get("model", "").strip()), daemon=True).start()
                    elif self.pending_text_prompts:
                        text, model, images, image_paths = self.pending_text_prompts.pop(0)
                        self.busy = True; self.selected_model = model
                        self._record("user", "" if text in IMAGE_ONLY_PROMPTS.values() else text, image_paths)
                        self._activity = "Думает · отвечает на сообщение из очереди"
                        threading.Thread(target=self.ask_model, args=(text, images or None, self.speech_enabled),
                                         daemon=True).start()

    def _route_for(self, text, has_images=False):
        chat = self._active_chat() or {}
        if chat.get("code_on") and not self.running:
            return "code"
        route = self._detect_composer_route(text, has_images=has_images)
        if route == "chat" and not has_images and self._continues_code(chat, text):
            route = "code"
        return "chat" if route == "code" and chat.get("code_declined") else route

    def send(self, text, image_paths=None):
        text = str(text or "").strip()
        allowed = self.known_files()
        image_paths = [str(path) for path in (image_paths or []) if str(path) in allowed and Path(str(path)).is_file()]
        if not text and not image_paths:
            return {"ok": False, "error": "Пустое сообщение."}
        route = self._route_for(text, has_images=bool(image_paths))
        if image_paths and route == "code":
            return self._send_with_images(text, image_paths)
        if image_paths and self._detect_composer_route(text) == "video":
            with self._state_lock:
                if self.busy:
                    return {"ok": False, "error": "Дождись завершения текущего действия."}
                self._record("user", text, image_paths)
                self._activity = "Видео по картинке · запуск ComfyUI"
                self._start_video_generation(text, image_paths[0])
            return {"ok": True, "route": "video"}
        if image_paths:
            return self._send_with_images(text, image_paths)
        with self._state_lock:
            self._notice = ""
            if route == "audio":
                return {"ok": False, "error": "Генерация музыки и звуков пока не поддерживается."}
            if route in ("image", "video") and not self._integration_enabled("comfyui"):
                return {"ok": False, "error": "Интеграция ComfyUI выключена. Включи её в настройках."}
            if route not in ("image", "video") and not self._integration_enabled("models"):
                return {"ok": False, "error": "Локальная модель выключена. Включи её в настройках."}
            model = self.settings.get("model", "").strip()
            if route not in ("image", "video") and not model:
                return {"ok": False, "error": "Сначала выбери модель."}
            if self.busy:
                if route == "code" and (self._active_chat() or {}).get("code_on"):
                    with self.agent_inbox_lock:
                        live = self.agent_inbox
                        if live is not None:
                            live.append(text)
                    if live is not None:
                        self._record("user", text)
                        self._activity = "Сообщение передано агенту, он учтёт его в работе"; self._changed()
                        return {"ok": True, "live": True}
                    self.pending_code_prompts.append(text)
                    self._record("user", text)
                    self._activity = "Сообщение учтётся в следующем шаге"; self._changed()
                    return {"ok": True, "live": True}
                if route != "chat":
                    return {"ok": False, "error": "Дождись завершения текущего действия."}
                self.pending_text_prompts.append((text, model, None, []))
                self._activity = "Сообщение добавлено в очередь"; self._changed()
                return {"ok": True, "queued": True}
            self.action_cancel.clear()
            self._active_response = None
            self.selected_model = model
            self._record("user", text)
            if route == "code" and not (self._active_chat() or {}).get("code_on"):
                self._record("code", self.code_offer_card(text))
                return {"ok": True, "route": "offer"}
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
                self._activity = "Агент берётся за работу"
                threading.Thread(target=self._run_coding_agent, args=(text, model), daemon=True).start()
            else:
                self._activity = "Думает"
                threading.Thread(target=self.ask_model, args=(text, None, self.speech_enabled), daemon=True).start()
            self._changed()
            return {"ok": True, "route": route}

    def _watch_providers(self):
        while True:
            time.sleep(15)
            try:
                if integrations.retry_lost():
                    self.refresh_models(providers=False)
            except Exception as exc:
                log(f"providers reconnect error: {exc}")

    def refresh_models(self, providers=True):
        try:
            if providers:
                integrations.refresh()
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
        if not self._integration_enabled("models"):
            return {"ok": False, "error": "Локальная модель выключена. Включи её в настройках."}
        model = self.settings.get("model", "").strip()
        if not model:
            return {"ok": False, "error": "Сначала выбери модель."}
        if not text:
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
            self._active_response = None
            self.busy = True; self.selected_model = model; self._activity = "Думает"
            threading.Thread(target=self.ask_model, args=(text, image_data, self.speech_enabled), daemon=True).start()
            self._changed()
            return {"ok": True, "route": "chat"}

    def _confirm_download(self, url, destination):
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

    def _confirm_command(self, command, reason, can_trust, kind="command"):
        cancel = self.action_cancel
        with self._state_lock:
            self._confirm_answer.clear()
            self._confirm_result = False
            self._confirm = {"id": uuid.uuid4().hex, "kind": "command", "command": str(command), "reason": str(reason), "canTrust": bool(can_trust), "folder": str((self._code_chat() or {}).get("code_root", "")), "edit": kind == "edit"}
            self._changed()
            self._notify("PIVEN спрашивает", f"Можно выполнить команду? {command}")
        deadline = time.monotonic() + 3600
        answered = False
        while not cancel.is_set() and time.monotonic() < deadline and not answered:
            answered = self._confirm_answer.wait(timeout=0.2)
        with self._state_lock:
            self._confirm = None
            self._changed()
            return self._confirm_result if answered else False

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
                path = huggingface.download_model(repo_id, record, token, progress, self._hf_cancel)
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
        catalogue = install.ASR_MODELS if kind == "asr" else install.TTS_MODELS if kind == "tts" else None
        extra = extra if isinstance(extra, dict) else {}
        if catalogue is None or (model_id not in catalogue and not (extra.get("file") or extra.get("repo") or extra.get("engine"))):
            return {"ok": False, "error": "Неизвестная модель."}
        with self._state_lock:
            if self._voice["state"] == "running":
                return {"ok": False, "error": "Уже идёт установка."}
            if kind == "tts" and not install.tts_packages_ready() and (self.running or self.tts_playing.is_set()):
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
                installed = install.install(kind, model_id, progress, self._voice_cancel, extra, token)
                with self._state_lock:
                    self._voice.update(state="done", percent=100, installed=installed, message="Готово", ended=time.monotonic())
                    key = {"asr": "asr_model", "tts": "tts_model"}[kind]
                    if not self.settings.get(key):
                        self.settings[key] = install.chosen_model(kind, installed)
                        self._save_settings()
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
    search_lock = threading.Lock()

    def __init__(self, app):
        self.app = app
        self.searched = None

    def _ready(self, make, wait=15):
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            browser = getattr(self.app, "_web_api", None) and make(self.app._web_api)
            if browser is not None and browser.ready:
                return browser
            time.sleep(0.25)
        raise RuntimeError("встроенный браузер не открылся")

    def _browser(self, wait=15):
        return self._ready(lambda api: api._native_browser(), wait)

    def _load(self, browser, url):
        browser.navigate(url)
        deadline = time.monotonic() + 30
        time.sleep(0.6)
        while time.monotonic() < deadline and browser.state().get("loading"):
            time.sleep(0.25)
        return self.text(browser)

    def open(self, url):
        with self.app._state_lock:
            self.app._browser_request = {"url": url, "nonce": time.time()}
            self.app._changed()
        self.searched = None
        return self._load(self._browser(), url)

    def search(self, url):
        """Runs outside the window, so the panel stays closed and the user's own page stays where it was."""
        with self.search_lock:
            browser = self.app._web_api._search_browser()
            browser.start_offscreen()
            self.searched = self._ready(lambda api: api._search_browser())
            return self._load(self.searched, url)

    def text(self, browser=None):
        browser = browser or self.searched or self._browser()
        text = browser.read_text() or ""
        text = re.sub(r"\n{3,}", "\n\n", text)
        return browser.state().get("title", ""), text

    @staticmethod
    def _looks_the_same(earlier, before, after):
        """Compares fingerprints. Text and canvas count only if they were idle before the click."""
        def parts(value):
            return (str(value) + "|||").split("|||")[:2]
        idle = parts(earlier)[1] == parts(before)[1]
        return parts(before)[0] == parts(after)[0] and (not idle or parts(before)[1] == parts(after)[1])

    @classmethod
    def _click_through(cls, browser, next_click, signature, press, limit=14):
        """Presses each control once and records the result."""
        def errors():
            try:
                return json.loads(browser.run_script("JSON.stringify(window.__pivenErrors||[])") or "[]")
            except Exception:
                return []
        rows, dead, broken, started = [], 0, 0, time.monotonic()
        for _ in range(limit):
            if time.monotonic() - started > 25:
                break
            try:
                item = json.loads(browser.run_script(next_click) or "null")
                if not item:
                    break
                earlier = browser.run_script(signature)
                time.sleep(0.15)
                before, known = browser.run_script(signature), errors()
                info = json.loads(browser.run_script(press) or "{}")
                time.sleep(0.45)
                after, now = browser.run_script(signature), errors()
            except Exception as error:
                rows.append(f"(stopped: {error})")
                break
            fresh = now[len(known):] if len(now) >= len(known) else now
            title = f"{item.get('name')} «{item.get('label')}»".replace(" «»", "")
            if fresh:
                broken += 1
                rows.append(f"{title}: ERROR after the click: " + "; ".join(str(entry)[:160] for entry in fresh[:3]))
            elif info.get("disabled"):
                rows.append(f"{title}: is disabled")
            elif cls._looks_the_same(earlier, before, after):
                dead += 1
                rows.append(f"{title}: NOTHING HAPPENED" + (f", another element ({info['covered']}) lies on top of it and takes the click" if info.get("covered") else ", no error and nothing visible changed on the screen (a class or variable that changes nothing on screen does not count)"))
            else:
                rows.append(f"{title}: ok, the page changed")
        return {"rows": rows, "dead": dead, "broken": broken}

    def check_page(self, url, wait, script, screenshot, after_seconds=1, after_script="", explore=True):
        """Runs the page outside the window for the coding agent and reports how it went."""
        import io
        from PIL import Image
        from app.window.browser import PAGE_CLICK, PAGE_NEXT_CLICK, PAGE_PICTURE, PAGE_PROBE, PAGE_SIGNATURE
        with self.search_lock:
            browser = self.app._web_api._search_browser()
            browser.start_offscreen()
            browser = self._ready(lambda api: api._search_browser())
            browser.watch_page_errors()
            browser.navigate(url)
            time.sleep(0.6)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and browser.state().get("loading"):
                time.sleep(0.25)
            time.sleep(wait)
            report = {}

            def run(code):
                wrapped = f"(function(){{try{{var r=(function(){{{code}\n}})();return r===undefined?'done, nothing returned':(typeof r==='string'?r:JSON.stringify(r));}}catch(e){{return 'Script error: '+e.message;}}}})()"
                try:
                    return browser.run_script(wrapped)
                except Exception as error:
                    return f"Script error: {error}"
            if script.strip():
                report["script"] = run(script)
            before = browser.run_script(PAGE_PICTURE)
            time.sleep(max(0.5, after_seconds))
            after = browser.run_script(PAGE_PICTURE)
            if before:
                report["moving"] = before != after
            if after_script.strip():
                report["after"] = run(after_script)
            if explore:
                report["clicks"] = self._click_through(browser, PAGE_NEXT_CLICK, PAGE_SIGNATURE, PAGE_CLICK)
            report["page"] = json.loads(browser.run_script(PAGE_PROBE) or "{}")
            report["errors"] = json.loads(browser.run_script("JSON.stringify(window.__pivenErrors||[])") or "[]")
            try:
                data = browser.capture()
                image = Image.open(io.BytesIO(data)).convert("RGB")
                image.thumbnail((900, 700))
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=75)
                report["picture"] = base64.b64encode(buffer.getvalue()).decode("ascii")
                if screenshot:
                    report["image"] = report["picture"]
            except Exception as error:
                log(f"page capture error: {error}")
            browser.navigate("about:blank")
            return report


class WebApi:

    def __init__(self, app):
        self._app = app
        self._browser = None
        self._hidden_browser = None
        app._web_api = self

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
            code = bool((app._active_chat() or {}).get("code_on"))
            empty = next((chat for chat in reversed(app.chats) if not chat.get("items") and not chat.get("messages")
                          and bool(chat.get("code_on")) == code), None)
            if empty is not None:
                app.select_chat(empty["id"])
            else:
                app.create_chat(code)
            app._changed()
        return {"ok": True}

    def code_mode(self, on):
        """Switches code mode and opens a chat of that kind."""
        app = self._app
        on = bool(on)
        with app._state_lock:
            if bool((app._active_chat() or {}).get("code_on")) != on:
                app.open_chat_of_kind(on)
                app._changed()
        return {"ok": True}

    def answer_plan(self, index, accept):
        app = self._app
        with app._state_lock:
            items = app.dialogue_items
            index = int(index)
            chat = app._active_chat()
            if chat is None or not 0 <= index < len(items) or items[index].get("role") != "code":
                return {"ok": False, "error": "Это предложение уже неактуально."}
            try:
                card = json.loads(items[index]["text"])
            except ValueError:
                return {"ok": False, "error": "Это предложение уже неактуально."}
            if card.get("kind") != "plan_ready" or card.get("answered"):
                return {"ok": False, "error": "Это предложение уже неактуально."}
            if app.busy:
                return {"ok": False, "error": "Дождись завершения текущего действия."}
            card["answered"] = "go" if accept else "keep"
            items[index]["text"] = json.dumps(card, ensure_ascii=False)
            if accept:
                chat["code_mode"] = "edits"
            app._save_conversation(); app._changed()
            return app.send("Выполни этот план.") if accept else {"ok": True}

    def cancel_queued(self, index):
        app = self._app
        with app._state_lock:
            index = int(index)
            if not 0 <= index < len(app.pending_text_prompts):
                return {"ok": False}
            del app.pending_text_prompts[index]
            app._changed()
        return {"ok": True}

    def answer_code_offer(self, index, accept):
        app = self._app
        with app._state_lock:
            items = app.dialogue_items
            index = int(index)
            chat = app._active_chat()
            if chat is None or not 0 <= index < len(items) or items[index].get("role") != "code":
                return {"ok": False, "error": "Это предложение уже неактуально."}
            try:
                card = json.loads(items[index]["text"])
            except ValueError:
                return {"ok": False, "error": "Это предложение уже неактуально."}
            if card.get("kind") != "offer" or card.get("answered"):
                return {"ok": False, "error": "Это предложение уже неактуально."}
            if app.busy:
                return {"ok": False, "error": "Дождись завершения текущего действия."}
            model = app.settings.get("model", "").strip()
            if not model:
                return {"ok": False, "error": "Сначала выбери модель."}
            card["answered"] = "code" if accept else "chat"
            items[index]["text"] = json.dumps(card, ensure_ascii=False)
            if accept:
                chat["code_on"] = True
            else:
                chat["code_declined"] = True
            request = str(card.get("request") or "")
            app.action_cancel.clear()
            app._active_response = None
            app.selected_model = model
            app.busy = True
            app._save_conversation()
            if accept:
                app._activity = "Агент берётся за работу"
                threading.Thread(target=app._run_coding_agent, args=(request, model), daemon=True).start()
            else:
                app._activity = "Думает"
                threading.Thread(target=app.ask_model, args=(request, None, app.speech_enabled), daemon=True).start()
            app._changed()
        return {"ok": True}

    def chat_kind(self, chat_id, code):
        app = self._app
        with app._state_lock:
            chat = next((item for item in app.chats if item.get("id") == str(chat_id)), None)
            if chat is None:
                return {"ok": False, "error": "Чат не найден."}
            if code:
                chat["code_on"] = True
            else:
                chat.pop("code_on", None)
            app._save_conversation(); app._changed()
        return {"ok": True}

    def set_model(self, name):
        app = self._app
        name = str(name or "").strip()
        with app._state_lock:
            if name not in app._models:
                return {"ok": False, "error": "Такой модели нет в папке моделей."}
            app.settings["model"] = name
            if not app.busy:
                app.selected_model = name
            chat = app._active_chat()
            if chat is not None:
                chat["model"] = name
                app._save_conversation()
            app._save_settings(); app._changed()
        return {"ok": True}

    def set_speech(self, enabled):
        app = self._app
        with app._state_lock:
            app.speech_enabled = bool(enabled); app.settings["speech_enabled"] = bool(enabled)
            app._save_settings(); app._changed()
        return {"ok": True}

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
            "voices": install.tts_voices(settings.get("tts_model")),
            "screenInterval": settings.get("screen_interval", 35),
            "micDevice": settings.get("mic_device", ""),
            "voiceSample": settings.get("voice_sample", ""),
            "voiceSampleText": settings.get("voice_sample_text", ""),
            "micSensitivity": settings.get("mic_sensitivity", 68),
            "bargeIn": bool(settings.get("barge_in", True)),
            "closeToTray": bool(settings.get("close_to_tray", True)),
            "maxLoadedModels": settings.get("max_loaded_models", 3),
            "heavyMode": bool(settings.get("heavy_mode")),
            "notifications": bool(settings.get("notifications", True)),
            "microphones": microphones,
            "micError": mic_error,
            "comfyUrl": settings.get("comfy_url", ""),
            "comfyWorkflow": settings.get("comfy_workflow", ""),
            "comfyVideoWorkflow": settings.get("comfy_video_workflow", ""),
            "projectRoot": settings.get("project_root", ""),
            "integrations": dict(settings.get("integrations_enabled", {})),
            "dataDir": str(DATA_DIR),
        }

    def update_settings(self, patch):
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
                changes["max_loaded_models"] = max(1, min(10, int(value or 1)))
            elif key == "heavyMode":
                if app.any_busy:
                    errors[key] = "Сначала дождись конца ответа."
                else:
                    changes["heavy_mode"] = bool(value)
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
                if not str(value or "").strip():
                    changes["project_root"] = ""
                elif not folder.is_dir():
                    errors[key] = "Такой папки нет."
                else:
                    changes["project_root"] = str(folder)
            elif key == "integrations":
                current = dict(app.settings.get("integrations_enabled", {}))
                for name in ("models", "comfyui"):
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
                if "heavy_mode" in changes or "max_loaded_models" in changes:
                    app.apply_heavy_mode()
                if "integrations_enabled" in changes and not changes["integrations_enabled"].get("models", True):
                    app.pending_text_prompts.clear()
                    if app.busy:
                        app.action_cancel.set()
                app._save_settings()
                app._changed()
        return {"ok": not errors, "errors": errors, "saved": sorted(changes)}

    def thinking_options(self, model):
        app = self._app
        model = str(model or "")
        cached = app.settings.get("thinking_capabilities", {}).get(model)
        if cached is None or cached.get("version") != 3 or (integrations.is_provider_model(model) and not cached.get("values")):
            try:
                values, default = model_thinking(model)
            except Exception as error:
                return {"values": [], "default": None, "current": "__auto__", "error": str(error)}
            cached = {"values": values, "default": default, "version": 3}
            with app._state_lock:
                app.settings.setdefault("thinking_capabilities", {})[model] = cached
                app._save_settings()
        current = app.settings.get("thinking_levels", {}).get(model, "__auto__")
        if current != "__auto__" and current not in cached.get("values", []):
            current = False if current is False and False in cached.get("values", []) else "__auto__"
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
                levels.pop(model, None); THINKING_LEVELS.pop(model, None)
            else:
                levels[model] = value; THINKING_LEVELS[model] = value
            app._save_settings(); app._changed()
        return {"ok": True}

    def pick_path(self, kind):
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

    def set_title_theme(self, caption, text, dark):
        window = self._app.window
        return {"ok": bool(window is not None and style_title_bar(window, caption, text, bool(dark)))}

    def code_set(self, values):
        app = self._app
        values = values if isinstance(values, dict) else {}
        with app._state_lock:
            chat = app._active_chat()
            if chat is None:
                return {"ok": False, "error": "Нет чата."}
            if "on" in values:
                chat["code_on"] = bool(values["on"])
            if "root" in values:
                root = str(values["root"] or "").strip()
                if root and not Path(root).is_dir():
                    return {"ok": False, "error": "Такой папки нет."}
                chat["code_root"] = str(Path(root).resolve()) if root else ""
                if root:
                    chat["code_on"] = True
            if "mode" in values:
                if values["mode"] not in ("ask", "edits", "plan", "free"):
                    return {"ok": False, "error": "Такого режима нет."}
                chat["code_mode"] = values["mode"]
                app.settings["code_mode_last"] = values["mode"]
                app._save_settings()
            app._save_conversation(); app._changed()
        return {"ok": True}

    def code_pick_folder(self):
        path = self.pick_path("folder")
        return self.code_set({"root": path}) if path else {"ok": False, "cancelled": True}

    def code_open_folder(self):
        root = str((self._app._active_chat() or {}).get("code_root") or "")
        if not root or not Path(root).is_dir():
            return {"ok": False, "error": "Папка проекта ещё не создана."}
        os.startfile(root)
        return {"ok": True}

    def code_files(self):
        from app.tools.coding import CodeTools
        root = str((self._app._active_chat() or {}).get("code_root") or "")
        if not root or not Path(root).is_dir():
            return {"root": "", "files": []}
        tools = CodeTools(root, APP_DIR, DATA_DIR)
        files = []
        for item in tools._walk():
            if item.is_file():
                try:
                    files.append({"path": tools._show(item), "size": item.stat().st_size})
                except OSError:
                    pass
                if len(files) >= 1000:
                    break
        return {"root": root, "files": files}

    def code_read(self, path):
        from app.tools.coding import CodeTools
        root = str((self._app._active_chat() or {}).get("code_root") or "")
        if not root:
            return {"ok": False, "error": "Нет папки проекта."}
        tools = CodeTools(root, APP_DIR, DATA_DIR)
        try:
            target = tools._path(path, must_exist=True)
            return {"ok": True, "text": tools._text(target)[:400_000], "full": str(target)}
        except (ValueError, OSError) as error:
            return {"ok": False, "error": str(error)}

    def code_preview(self, path):
        from app.tools import preview
        from app.tools.coding import CodeTools
        root = str((self._app._active_chat() or {}).get("code_root") or "")
        tools = CodeTools(root or ".", APP_DIR, DATA_DIR)
        try:
            target = tools._path(path, must_exist=True)
        except (ValueError, OSError) as error:
            return {"ok": False, "error": str(error)}
        return {"ok": True, "url": preview.url_for(target, tools.root)}

    def code_undo(self, index):
        app = self._app
        with app._state_lock:
            items = app.dialogue_items
            index = int(index)
            if not 0 <= index < len(items) or items[index].get("role") != "code":
                return {"ok": False, "error": "Нечего отменять."}
            try:
                card = json.loads(items[index]["text"])
                if card.get("undone"):
                    return {"ok": False, "error": "Эти изменения уже отменены."}
                restored, kept = app.code_undo(card.get("checkpoint", ""))
            except (ValueError, OSError) as error:
                return {"ok": False, "error": f"Не удалось отменить: {error}"}
            card["undone"] = True
            card["kept"] = [Path(path).name for path in kept][:20]
            items[index]["text"] = json.dumps(card, ensure_ascii=False)
            app._save_conversation(); app._changed()
        return {"ok": True, "restored": len(restored), "kept": len(kept)}

    def route_hint(self, text):
        app = self._app
        text = str(text or "")
        route = app._route_for(text)
        labels = {"presentation": "соберёт презентацию", "image": "нарисует через ComfyUI",
                  "video": "снимет видео через ComfyUI", "audio": "аудио пока не поддерживается"}
        if route == "code":
            root = (app._active_chat() or {}).get("code_root", "")
            label = "предложит режим кода" if not (app._active_chat() or {}).get("code_on") else f"поработает с кодом в папке {Path(root).name}" if root else "создаст проект и напишет код сам"
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
            chat["titled"] = True
            app._save_conversation(); app._changed()
        return {"ok": True}

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
            files = huggingface.list_gguf_files(str(repo))
            return {"ok": True, "files": files if isinstance(files, list) else []}
        except Exception as error:
            return {"ok": False, "error": str(error), "files": []}

    def memory_download_model(self, repo="", file_path="", size=0):
        app = self._app
        from app.chat import memory as long_memory
        if getattr(app, "_memory_job", {}).get("state") == "running":
            return {"ok": False, "error": "Уже скачивается."}
        app._memory_job = {"state": "running", "percent": 0, "message": "Подключение"}
        cancel = threading.Event()
        app._memory_cancel = cancel

        def work():
            try:
                source, name = (str(repo), str(file_path)) if repo and file_path else (long_memory.EMBED_REPO, long_memory.EMBED_FILE)
                record = next(item for item in huggingface.list_gguf_files(source) if item["path"] == name)
                total = int(record.get("size") or size or 0)
                target = app.memory.folder / "model" / Path(name).name
                huggingface._download_file(source, name.split("/"), target, total, "", cancel,
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

    def run_code(self, language, code, stdin=""):
        from app.window import workspace
        return workspace.run_code(APP_DIR, str(language), str(code), str(stdin or ""))

    def presentation_slides(self, path):
        from app.window import workspace
        path = str(path or "")
        if path not in self._app.known_files() or not path.lower().endswith(".pptx"):
            return {"ok": False, "slides": [], "error": "Этот файл не из чата."}
        try:
            return {"ok": True, "slides": workspace.presentation_slides(path)}
        except Exception as error:
            return {"ok": False, "slides": [], "error": f"Не удалось прочитать презентацию: {error}"}

    def tools_status(self):
        app = self._app
        servers = []
        for entry in app.settings.get("mcp_servers", []):
            server = mcp.servers.get(entry.get("name"))
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
            mcp.configure(servers)
            app._save_settings()
        if not clean["enabled"]:
            return {"ok": True, "tools": 0}
        try:
            return {"ok": True, "tools": len(mcp.servers[name].tools())}
        except Exception as error:
            mcp.servers[name].error = str(error)
            return {"ok": False, "error": f"Сервер сохранён, но не ответил: {error}"}

    def delete_mcp_server(self, name):
        app = self._app
        with app._state_lock:
            app.settings["mcp_servers"] = [item for item in app.settings.get("mcp_servers", []) if item.get("name") != name]
            mcp.configure(app.settings["mcp_servers"])
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

    def providers_status(self):
        return {"providers": integrations.status()}

    def _provider_reply(self, provider, key_saved=False):
        self._app.refresh_models(providers=False)
        row = next(item for item in integrations.status() if item["id"] == provider)
        return {"ok": not row["error"], "error": row["error"], "models": row["models"], "keySaved": key_saved}

    def reconnect_provider(self, provider):
        provider = str(provider)
        if provider not in integrations.PROVIDERS:
            return {"ok": False, "error": "Неизвестный сервис."}
        integrations.reconnect(provider)
        return self._provider_reply(provider)

    def set_provider(self, provider, enabled=None, url=None, key=None):
        app = self._app
        provider = str(provider)
        if provider not in integrations.PROVIDERS:
            return {"ok": False, "error": "Неизвестный сервис."}
        if key:
            key = integrations.clean_key(key)
            if not key:
                return {"ok": False, "error": "Это не похоже на API-ключ."}
            refused = integrations.try_key(provider, key)
            if refused:
                return {"ok": False, "error": refused, "rejected": True}
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
                saved["key"] = integrations.seal(key)
            app.settings["providers"][provider] = saved
            integrations.config[provider] = saved
            app._save_settings()
        integrations.reconnect(provider)
        return self._provider_reply(provider, key_saved=bool(key))

    def model_params(self, model=""):
        app = self._app
        model = str(model or app.settings.get("model", ""))
        saved = app.settings.get("model_params", {})
        return {"model": model, "defaults": llama.DEFAULT_PARAMS, "limits": llama.PARAM_LIMITS,
                "choices": {key: list(values) for key, values in llama.CHOICES.items()},
                "presets": llama.PRESETS, "serverKeys": list(llama.SERVER_KEYS),
                "all": saved.get("*", {}), "own": saved.get(model, {}), "effective": llama.params_for(model),
                "cloud": integrations.is_provider_model(model),
                "autoTitles": bool(app.settings.get("auto_titles", True))}

    def set_model_params(self, scope, values, replace=False):
        app = self._app
        scope = str(scope or "*")
        values = values if isinstance(values, dict) else {}
        with app._state_lock:
            saved = app.settings.setdefault("model_params", {})
            current = {} if replace else dict(saved.get(scope, {}))
            current.update(llama.clean_params(values))
            base = llama.DEFAULT_PARAMS if scope == "*" else {**llama.DEFAULT_PARAMS, **saved.get("*", {})}
            current = {key: value for key, value in current.items() if base.get(key) != value}
            if current:
                saved[scope] = current
            else:
                saved.pop(scope, None)
            llama.model_params.clear()
            llama.model_params.update(saved)
            app._save_settings(); app._changed()
        return {"ok": True}

    def recommended_model(self):
        try:
            found = huggingface.recommended(memory_fit.gpu_memory())
        except Exception as error:
            return {"ok": False, "error": str(error)}
        return {"ok": bool(found), **(found or {}), "error": "" if found else "Нет связи с Hugging Face."}

    def set_language(self, language):
        if language not in ("ru", "en"):
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
        app = self._app
        if app.any_busy or app.running:
            return {"ok": False, "error": "Сначала дождись конца ответа и заверши звонок."}
        keep = ("model", "asr_model", "tts_model", "project_root", "tray_hint_shown")
        with app._state_lock:
            kept = {key: app.settings[key] for key in keep if key in app.settings}
            core.SETTINGS_PATH.write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")
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
        path = str(path or "")
        file = Path(path)
        if path not in self._app.known_files() or not file.is_file():
            return ""
        mime = mimetypes.guess_type(file.name)[0] or ""
        if not mime.startswith(("image/", "video/")):
            return ""
        if file.stat().st_size > (MAX_IMAGE_BYTES * 5 if mime.startswith("video/") else MAX_IMAGE_BYTES):
            return ""
        return f"data:{mime};base64," + base64.b64encode(file.read_bytes()).decode("ascii")

    def open_file(self, path):
        path = str(path or "")
        if path not in self._app.known_files() or not Path(path).is_file():
            return {"ok": False}
        os.startfile(path)
        return {"ok": True}

    def save_copy(self, path):
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
        app = self._app
        with app._state_lock:
            cut = app.cut_history_at(int(index))
            if cut is None:
                return {"ok": False, "error": "Это сообщение нельзя изменить: идёт ответ или оно уже в кратком содержании."}
            _old_text, images = cut
            images = [path for path in images if Path(path).is_file()]
            app._allowed_files |= set(images)
            app._changed()
        return app.send(text, images)

    def speak(self, text):
        threading.Thread(target=self._app._speak, args=(str(text or ""),), daemon=True).start()
        return {"ok": True}

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
            self._app.stop_listening(); self._app.running = False; self._app._changed()
        return {"ok": True}

    def start_dictation(self):
        app = self._app
        with app._state_lock:
            error = app.start_dictation()
            app._changed()
        return {"ok": not error, "error": error, "needsModel": not install.ready("asr", app.settings.get("asr_model"))}

    def stop_dictation(self):
        with self._app._state_lock:
            self._app.stop_dictation(); self._app._changed()
        return {"ok": True}

    def answer_command(self, confirm_id, answer):
        app = self._app
        with app._state_lock:
            if not app._confirm or app._confirm.get("id") != confirm_id:
                return {"ok": False}
            app._confirm_result = answer if answer in ("once", "project") else False
        app._confirm_answer.set()
        return {"ok": True}

    def answer_confirmation(self, confirm_id, approved):
        app = self._app
        with app._state_lock:
            if not app._confirm or app._confirm.get("id") != confirm_id:
                return {"ok": False}
            app._confirm_result = bool(approved)
        app._confirm_answer.set()
        return {"ok": True}

    @staticmethod
    def _web_url(url):
        clean = str(url or "").strip()
        return clean if re.match(r"^https?://[^\s]+$", clean, re.I) else ""

    def open_url(self, url):
        import webbrowser
        clean = self._web_url(url)
        if not clean:
            return {"ok": False, "error": "Это не адрес сайта."}
        webbrowser.open(clean)
        return {"ok": True}

    def _native_browser(self):
        if self._browser is None and self._app.window is not None:
            from app.window import browser as native_browser
            self._browser = native_browser.NativeBrowser(self._app.window, str(DATA_DIR / "browser_profile"))
        return self._browser

    def _search_browser(self):
        if self._hidden_browser is None and self._app.window is not None:
            from app.window import browser as native_browser
            self._hidden_browser = native_browser.NativeBrowser(self._app.window, str(DATA_DIR / "browser_profile"))
        return self._hidden_browser

    def browser_place(self, x, y, width, height, visible):
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

    def answer_poll(self, answers):
        return self.send("\n".join(f"{question} — {choice}" for question, choice in answers))

    def hf_search(self, query, token=""):
        try:
            return {"ok": True, "models": huggingface.search_models(query, str(token or "").strip())}
        except Exception as error:
            return {"ok": False, "error": str(error), "models": []}

    def hf_files(self, repo_id, token=""):
        try:
            files = huggingface.list_gguf_files(repo_id, str(token or "").strip())
            tag = huggingface.suggested_tag(repo_id, files[0]["path"]) if files else ""
            return {"ok": True, "files": files, "tag": tag}
        except Exception as error:
            return {"ok": False, "error": str(error), "files": []}

    def hf_suggest_tag(self, repo_id, file_path):
        return huggingface.suggested_tag(repo_id, file_path)

    def hf_start(self, repo_id, record, tag, token=""):
        return self._app.start_hf_download(str(repo_id or ""), record if isinstance(record, dict) else {},
                                           str(tag or ""), str(token or "").strip())

    def hf_status(self):
        with self._app._state_lock:
            return dict(self._app._hf)

    def hf_cancel(self):
        self._app._hf_cancel.set()
        return {"ok": True}

    def voice_status(self):
        app = self._app
        with app._state_lock:
            job = dict(app._voice)
            selected = {"asr": app.settings.get("asr_model"), "tts": app.settings.get("tts_model")}
        catalogue = install.status()
        for kind in ("asr", "tts"):
            catalogue[kind]["selected"] = selected[kind]
        return {**catalogue, "job": job, "gpu": memory_fit.gpu_memory()}

    def voice_install(self, kind, model_id, extra=None, token=""):
        return self._app.start_voice_install(str(kind or ""), str(model_id or ""), extra, str(token or "").strip())

    def model_description(self, repo_id, token=""):
        repo_id = str(repo_id or "")
        if repo_id.startswith("audiocpp:"):
            return {"text": "", "source": ""}
        return huggingface.model_description(repo_id, str(token or "").strip())

    def voice_search(self, kind, query, token=""):
        try:
            return {"ok": True, "models": install.search(str(kind), str(query or ""), str(token or "").strip())}
        except Exception as error:
            return {"ok": False, "error": str(error), "models": []}

    def voice_details(self, kind, repo, engine, token=""):
        try:
            return {"ok": True, **install.details(str(kind), str(repo), str(engine), str(token or "").strip())}
        except Exception as error:
            return {"ok": False, "error": str(error)}

    def restart_app(self):
        threading.Timer(0.3, restart_program, (self._app,)).start()
        return {"ok": True}

    def voice_select(self, kind, model_id):
        app = self._app
        key = {"asr": "asr_model", "tts": "tts_model"}.get(str(kind))
        if not key or not install.known(kind, model_id):
            return {"ok": False, "error": "Неизвестная модель."}
        if not install.ready(kind, model_id):
            return {"ok": False, "error": "Сначала скачай эту модель."}
        with app._state_lock:
            changed = app.settings.get(key) != model_id
            app.settings[key] = model_id
            if kind == "tts":
                voices = [value for value, _ in install.tts_voices(model_id)]
                if app.settings.get("voice") not in voices:
                    app.settings["voice"] = voices[0]
            app._save_settings(); app._changed()
        return {"ok": True, "error": "", "restart": changed}

    def delete_model(self, name):
        app = self._app
        name = str(name or "")
        if llama.model_in_use(name):
            return {"ok": False, "error": "Эта модель сейчас отвечает. Дождись конца ответа или останови его."}
        try:
            freed = llama.delete_model(name)
        except Exception as error:
            return {"ok": False, "error": str(error)}
        app.refresh_models()
        app._changed()
        return {"ok": True, "freed": freed}

    def voice_delete(self, kind, model_id):
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
        if selected:
            app._stop_owned_model_process("asr_process" if kind == "asr" else "tts_process", "голосовая модель")
        try:
            freed = install.delete(kind, model_id)
        except Exception as error:
            return {"ok": False, "error": str(error)}
        if selected:
            with app._state_lock:
                app.settings[key] = install.chosen_model(kind)
                app._save_settings()
        app._changed()
        return {"ok": True, "freed": freed}

    def voice_engine_delete(self, engine):
        app = self._app
        if app._voice.get("state") == "running":
            return {"ok": False, "error": "Сначала дождись конца загрузки."}
        try:
            freed = install.delete_engine(str(engine or ""))
        except Exception as error:
            log(f"voice engine delete error: {error}")
            return {"ok": False, "error": str(error)}
        app._changed()
        return {"ok": True, "freed": freed}

    def disk_usage(self):
        try:
            sizes = llama.model_sizes()
            voice = install.disk_usage()
            return {"ok": True, "models": [{"name": name, "bytes": size} for name, size in sorted(sizes.items(), key=lambda item: -item[1])],
                    "voiceModels": voice["models"], "engines": voice["engines"]}
        except Exception as error:
            log(f"disk usage error: {error}")
            return {"ok": False, "error": str(error), "models": [], "voiceModels": 0, "engines": []}

    @staticmethod
    def _model_features(wanted=None):
        features = {}
        for name in llama.model_files():
            if wanted is not None and name not in wanted:
                continue
            try:
                values, default = llama.thinking_modes(name)
            except Exception:
                values, default = [], None
            features[name] = {"vision": llama.has_vision(name), "thinking": bool(values) or default is True,
                              "context": llama.context_size(name)}
        return features

    def model_memory(self, names=None):
        try:
            wanted = None if names is None else {str(name) for name in names}
            reserved = self._app.voice_vram()
            llama.reserved_vram[0] = reserved
            return {"gpu": memory_fit.gpu_memory(), "context": llama.context_size(self._app.settings.get("model", "")),
                    "models": llama.memory_estimates(wanted), "voiceReserved": reserved, "voiceCall": self._app.voice_vram(True, True),
                    "features": self._model_features(wanted)}
        except Exception as error:
            log(f"model memory error: {error}")
            return {"gpu": 0, "context": 0, "models": {}}

    def context_usage(self, draft=""):
        try:
            app = self._app
            model = str(app.settings.get("model", ""))
            with app._state_lock:
                messages = list(app.messages)
                summary = str(app._chat_summary() or "")
                live = dict(app._live_turns.get(app.active_chat_id) or {})
            work = app.code_usage.get(app.active_chat_id)
            if work and work["model"] == model and (app._active_chat() or {}).get("code_on"):
                # Project chats report the agent's working memory.
                parts = {"system": work["parts"]["system"], "summary": 0, "skills": 0, "tools": work["parts"]["tools"], "history": work["parts"]["history"], "images": 0}
                return {"ok": True, "model": model, "cloud": integrations.is_provider_model(model), "exact": llama.counts_exactly(model), "parts": parts, "used": sum(parts.values()),
                        "turns": work["turns"], "images": 0, "toolCount": 0, "serversWaiting": [], "limit": work["limit"],
                        "historyShare": 1 - 0.3, "compress": True}
            turns = messages[1:]
            live_texts = [text for text in (live.get("question"), live.get("answer")) if text]

            def tokens(text):
                return llama.count_tokens(model, text, unloaded=True)
            images = sum(len(item.get("images") or []) for item in turns)
            skills_text = tools_text = ""
            tools_names, waiting = 0, []
            if app.settings.get("tools_enabled", True):
                try:
                    toolbox = tools.ToolBox(APP_DIR, DATA_DIR, None if app.heavy_mode else app.tool_browser(), may_open_sites=False, use_mcp=not app.heavy_mode,
                                            memory=app.memory if app.settings.get("memory_enabled", True) else None)
                    specs = toolbox.specs(start_servers=False)
                    skills_text = toolbox.skills_prompt()
                    tools_text = json.dumps(specs, ensure_ascii=False)
                    tools_names, waiting = len(specs), list(toolbox.unstarted)
                except Exception as error:
                    log(f"context tools count error: {error}")
            system = str(messages[0].get("content", "")) if messages else ""
            parts = {"system": tokens(system + app._language_rule(app.settings.get("ui_language", "ru")) + app._date_rule()),
                     "summary": tokens(summary),
                     "skills": tokens(skills_text),
                     "tools": tokens(tools_text),
                     "history": (tokens("\n".join(str(item.get("content", "")) for item in turns))
                                 + sum(llama.count_tokens(model, text) for text in live_texts) + llama.count_tokens(model, draft)),
                     "images": llama.IMAGE_TOKENS * images}
            cloud = integrations.is_provider_model(model)
            return {"ok": True, "model": model, "cloud": cloud, "exact": llama.counts_exactly(model), "parts": parts, "used": sum(parts.values()),
                    "turns": len(turns) + len(live_texts), "images": images, "toolCount": tools_names, "serversWaiting": waiting,
                    "limit": 0 if cloud or not model else llama.context_size(model),
                    "historyShare": core.HISTORY_SHARE, "compress": bool(llama.params_for(model)["compress_context"]) if model and not cloud else False}
        except Exception as error:
            log(f"context usage error: {error}")
            return {"ok": False, "error": str(error)}

    def hf_memory(self, repo_id, file_path, size, token=""):
        try:
            meta = memory_fit.remote_metadata(str(repo_id), str(file_path), str(token or "").strip())
            context = llama.context_size()
            return {"gpu": memory_fit.gpu_memory(), "context": context,
                    "estimate": memory_fit.estimate(int(size or 0), meta, context),
                    "known": bool(meta), "voiceCall": self._app.voice_vram(True, True)}
        except Exception as error:
            log(f"hf memory error: {error}")
            return {"gpu": 0, "context": 0, "estimate": None, "known": False}

    def model_logos(self, names, authors=None, architectures=None):
        names = [str(name) for name in names or []][:200]
        architectures = dict(architectures) if isinstance(architectures, dict) else {}
        try:
            local = llama.model_files()
            for name in names:
                if name in local and name not in architectures:
                    architectures[name] = llama.gguf_metadata(local[name][0], ("general.architecture",)).get("general.architecture", "")
        except Exception as error:
            log(f"model architecture error: {error}")
        try:
            return logos.logos(names, authors if isinstance(authors, dict) else {}, architectures)
        except Exception as error:
            log(f"model logos error: {error}")
            return {}

    def voice_cancel(self):
        self._app._voice_cancel.set()
        return {"ok": True}

    def copy_text(self, text):
        import subprocess
        subprocess.run(["clip"], input=str(text).encode("utf-16-le"), check=False,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"ok": True}


def restart_program(app):
    flags = 0x00000008 | 0x00000200 | 0x01000000
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    subprocess.Popen([str(pythonw if pythonw.is_file() else sys.executable), str(Path(__file__).resolve()), "--restarted"],
                     cwd=str(APP_DIR), creationflags=flags, close_fds=True)
    app._quitting = True
    if app.window is not None:
        app.window.destroy()


def _show_event():
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.CreateEventW.restype = kernel32.OpenEventW.restype = wintypes.HANDLE
    kernel32.CreateEventW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.OpenEventW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.SetEvent.argtypes = kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    return kernel32, "Local\\PIVENCompanionShow-" + str(uuid.uuid5(uuid.NAMESPACE_URL, str(DATA_DIR).lower()))


def ask_running_copy_to_show():
    import ctypes
    kernel32, name = _show_event()
    handle = kernel32.OpenEventW(0x0002, False, name)
    if not handle:
        return False
    ctypes.windll.user32.AllowSetForegroundWindow(-1)
    done = kernel32.SetEvent(handle)
    kernel32.CloseHandle(handle)
    return bool(done)


def listen_for_second_launch(show):
    kernel32, name = _show_event()
    handle = kernel32.CreateEventW(None, False, False, name)

    def wait():
        while kernel32.WaitForSingleObject(handle, 0xFFFFFFFF) == 0:
            try:
                show()
            except Exception as error:
                log(f"second launch show error: {error}")
    if handle:
        threading.Thread(target=wait, daemon=True).start()


def main():
    import ctypes
    import webview
    if not UI_INDEX.is_file():
        webview.create_window(APP_NAME, html="<h3 style='font-family:Segoe UI'>Не найдена сборка ui/dist. "
                                             "Запусти ui\\scripts\\build.cmd.</h3>")
        webview.start()
        return
    restarted = "--restarted" in sys.argv
    if not acquire_instance_lock(wait=30 if restarted else 0):
        if not restarted and ask_running_copy_to_show():
            return
        if restarted or not acquire_instance_lock(wait=10):
            webview.create_window(APP_NAME, html="<body style='background:#111;color:#eee'><h3 style='font-family:Segoe UI'>PIVEN уже запущен, но не отвечает. "
                                                 "Закрой его через значок в трее (правая кнопка → «Выйти») и открой снова.</h3></body>", width=620, height=200)
            webview.start()
            return
    shutil.rmtree(core.DATA_DIR / "webview" / "EBWebView" / "Default" / "Cache", ignore_errors=True)
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    app = WebCompanion()
    threading.Thread(target=app.refresh_models, daemon=True).start()
    threading.Thread(target=app._watch_providers, daemon=True).start()
    window = webview.create_window(WINDOW_TITLE, url=str(UI_INDEX), js_api=WebApi(app),
                                   width=1440, height=900, min_size=(960, 640), background_color="#0a0a0a")
    app.window = window
    window.events.shown += lambda: (set_window_icon(window), style_title_bar(window))

    def open_window():
        app._hidden = False
        window.show()
        hwnd = int(window.native.Handle.ToInt64())
        if ctypes.windll.user32.IsIconic(hwnd):
            window.restore()
        ctypes.windll.user32.SetForegroundWindow(hwnd)

    listen_for_second_launch(open_window)

    def quit_program():
        app._quitting = True
        window.destroy()

    try:
        from app.window import tray
        app.tray = tray.Tray(APP_ICON, WINDOW_TITLE, open_window, quit_program)
    except Exception as error:
        log(f"tray icon error: {error}")

    def on_closing():
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
    webview.start(private_mode=False, storage_path=str(core.DATA_DIR / "webview"))


if __name__ == "__main__":
    main()
