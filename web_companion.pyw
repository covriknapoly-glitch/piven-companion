"""PIVEN Companion with the React interface (modern-ui) in a pywebview window over CompanionCore.

The page talks to Python only through WebApi below: it polls `poll` for a state
snapshot and sends commands; chats and settings are the same files the Qt window uses.
"""
from __future__ import annotations

import base64
import mimetypes
import os
import re
import shutil
import threading
import time
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
import model_logos
import voice_install

UI_INDEX = APP_DIR / "modern-ui" / "dist" / "index.html"
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


class WebCompanion(CompanionCore):
    """Plays the role of the Qt window's `_drain_events` for the web interface."""

    def __init__(self):
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
        self._confirm_answer = threading.Event()
        self._confirm_result = False
        self._hf = {"state": "idle", "percent": 0, "message": "", "tag": "", "path": "", "error": ""}
        self._hf_cancel = threading.Event()
        self._voice = {"kind": "", "id": "", "state": "idle", "percent": 0, "message": "", "error": ""}
        self._voice_cancel = threading.Event()

    # ---------- state ----------
    def _changed(self):
        self._version += 1

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
                           "preview": next((" ".join(str(item.get("text", "")).split())[:90]
                                            for item in reversed(chat.get("items", []))
                                            if item.get("role") in ("assistant", "user") and item.get("text")), "")}
                          for chat in chats],
                "items": [{"role": item.get("role", "system"), "text": str(item.get("text", "")),
                           "images": [str(path) for path in item.get("images") or []]}
                          for item in self.dialogue_items if isinstance(item, dict)],
                "chatTitle": active.get("title") or "Новый чат",
                "busy": bool(self.busy),
                "busySince": self._busy_since or 0,
                "listening": {"running": bool(self.running),
                              "options": dict(zip(("mic", "loopback", "screen", "proactive"), map(bool, self.capture_options)))},
                "call": dict(zip(("speaking", "hearing", "muted"), self._call_flags())),
                "confirm": self._confirm,
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
                elif kind == "presentation_created":
                    self._record("assistant", f"Презентация готова · {Path(value).name}", [str(value)])
                    self._activity = "Презентация создана"
                elif kind == "error":
                    self._record("system", value); self._activity = "Ошибка"; self._reasoning = ""
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
                        self._record("user", text, image_paths)
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
        if image_paths:
            # Same path as the Qt window: attached pictures always go to the model as a question about them.
            return self._send_with_images(text, image_paths)
        with self._state_lock:
            self._notice = ""
            if route in ("video", "audio"):
                return {"ok": False, "error": "Сейчас через ComfyUI подключена генерация изображений. Для видео и аудио нужен отдельный workflow."}
            if route == "image" and not self._integration_enabled("comfyui"):
                return {"ok": False, "error": "Интеграция ComfyUI выключена. Включи её в настройках Компаньона."}
            if route != "image" and not self._integration_enabled("ollama"):
                return {"ok": False, "error": "Локальная модель выключена. Включи её в настройках Компаньона."}
            model = self.settings.get("model", "").strip()
            if route != "image" and not model:
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
                self._activity = "Распознал запрос на изображение · запускает ComfyUI"
                self._start_image_generation(text)
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
                self._activity = "Распознал задачу по проекту · агент изучает файлы"
                threading.Thread(target=self._run_coding_agent, args=(text, model, str(project_root)), daemon=True).start()
            else:
                self._activity = "Думает"
                threading.Thread(target=self.ask_model, args=(text, None, self.speech_enabled), daemon=True).start()
            self._changed()
            return {"ok": True, "route": route}

    def refresh_models(self):
        try:
            names = list_models()
            error = backend_problem()
        except Exception as exc:
            names, error = [], f"Не удалось прочитать папку моделей: {exc}"
        with self._state_lock:
            self._models, self._models_error = names, error
            self._status = f"llama.cpp, моделей: {len(names)}" if names else (error or "Нет моделей")
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
            text = ("Посмотри на эти изображения и коротко расскажи, что на них." if len(image_paths) > 1
                    else "Посмотри на это изображение и коротко расскажи, что на нём.")
        try:
            image_data = [encode_chat_image(path) for path in image_paths]
        except Exception as error:
            return {"ok": False, "error": f"Не удалось подготовить изображение: {error}"}
        with self._state_lock:
            if self.busy:
                self.pending_text_prompts.append((text, model, image_data, image_paths))
                self._activity = "Сообщение добавлено в очередь"; self._changed()
                return {"ok": True, "queued": True}
            self._record("user", text, image_paths)
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
        answered = self._confirm_answer.wait(timeout=600)
        with self._state_lock:
            self._confirm = None
            self._changed()
            return answered and self._confirm_result

    def _run_approved_download(self, item, screenshot_size, display_size):
        with self._state_lock:
            self._activity = "Скачиваю файл"
            self._changed()
        return super()._run_approved_download(item, screenshot_size, display_size)

    def start_hf_download(self, repo_id, record, tag, token):
        with self._state_lock:
            if self._hf["state"] == "running":
                return {"ok": False, "error": "Модель уже скачивается."}
            if self.busy or self.running:
                return {"ok": False, "error": "Сначала останови текущую задачу и прослушивание."}
            self._hf = {"state": "running", "percent": 0, "message": "Подключаюсь к Hugging Face", "tag": tag, "path": "", "error": ""}
            self._hf_cancel.clear()

        def progress(percent, message):
            with self._state_lock:
                self._hf.update(percent=max(0, min(100, int(percent))), message=str(message))

        def work():
            try:
                path = hf_models.download_model(repo_id, record, token, progress, self._hf_cancel)
                with self._state_lock:
                    self._hf.update(state="done", percent=100, message="Модель готова", path=path)
                self.refresh_models()
                name = Path(path).stem
                with self._state_lock:
                    if name in self._models:
                        self.settings["model"] = name
                        self._save_settings(); self._changed()
            except Exception as error:
                with self._state_lock:
                    self._hf.update(state="cancelled" if isinstance(error, InterruptedError) else "error", error=str(error))
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
            self._voice = {"kind": kind, "id": model_id, "state": "running", "percent": 0, "message": "Подключаюсь", "error": "", "installed": ""}
            self._voice_cancel.clear()

        def progress(percent, message):
            with self._state_lock:
                self._voice.update(percent=max(0, min(100, int(percent))), message=str(message))

        def work():
            try:
                installed = voice_install.install(kind, model_id, progress, self._voice_cancel, extra, token)
                with self._state_lock:
                    self._voice.update(state="done", percent=100, installed=installed)
            except BaseException as error:
                log(f"Voice install {kind}/{model_id} failed: {error}")
                with self._state_lock:
                    self._voice.update(state="cancelled" if isinstance(error, InterruptedError) else "error", error=str(error))
        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}


class WebApi:
    """Methods callable from JavaScript as window.pywebview.api.<name>()."""

    def __init__(self, app):
        self._app = app
        self._browser = None

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
            if app.busy:
                return {"ok": False, "error": "Дождись завершения текущего действия."}
            ok = app.select_chat(str(chat_id)) is not None
            app._changed()
        return {"ok": ok}

    def new_chat(self):
        app = self._app
        with app._state_lock:
            if app.busy:
                return {"ok": False, "error": "Дождись завершения текущего действия."}
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
            "microphones": microphones,
            "micError": mic_error,
            "comfyUrl": settings.get("comfy_url", ""),
            "comfyWorkflow": settings.get("comfy_workflow", ""),
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
        if cached is None:
            try:
                values, default = model_thinking(model)
            except Exception as error:
                return {"values": [], "default": None, "current": "__auto__", "error": str(error)}
            cached = {"values": values, "default": default}
            with app._state_lock:
                app.settings.setdefault("thinking_capabilities", {})[model] = cached
                app._save_settings()
        current = app.settings.get("thinking_levels", {}).get(model, "__auto__")
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
        labels = {"presentation": "соберу презентацию", "image": "нарисую через ComfyUI",
                  "video": "видео пока не умею", "audio": "аудио пока не умею"}
        if route == "code":
            label = f"поработаю с кодом в папке {Path(app.settings.get('project_root', str(APP_DIR))).name or 'проекта'}"
        elif route == "chat" and app._is_computer_request(text):
            label = "сделаю на компьютере"
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
            app._save_conversation(); app._changed()
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
        if path not in self._app.known_files() or not file.is_file() or file.stat().st_size > MAX_IMAGE_BYTES:
            return ""
        mime = mimetypes.guess_type(file.name)[0] or ""
        if not mime.startswith("image/"):
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
            if app.busy:
                return {"ok": False, "error": "Дождись завершения текущего действия."}
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

    def voice_select(self, kind, model_id):
        app = self._app
        key = {"asr": "asr_model", "tts": "tts_model"}.get(str(kind))
        if not key or not voice_install.known(kind, model_id):
            return {"ok": False, "error": "Неизвестная модель."}
        if not voice_install.ready(kind, model_id):
            return {"ok": False, "error": "Сначала скачай эту модель."}
        with app._state_lock:
            app.settings[key] = model_id
            if kind == "tts":
                voices = [value for value, _ in voice_install.tts_voices(model_id)]
                if app.settings.get("voice") not in voices:
                    app.settings["voice"] = voices[0]
            app._save_settings(); app._changed()
        note = "Новая модель распознавания включится со следующего звонка." if kind == "asr" and app.running else ""
        return {"ok": True, "error": note}

    def delete_model(self, name):
        """Delete a local chat model from disk."""
        app = self._app
        name = str(name or "")
        if app.busy and llama_backend.SERVER.loaded_model == name:
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

    def model_memory(self, names=None):
        """Estimated video memory of local models once loaded, and the GPU's total."""
        try:
            wanted = None if names is None else {str(name) for name in names}
            return {"gpu": memory_estimate.gpu_memory(), "context": llama_backend.SERVER.context_size,
                    "models": llama_backend.memory_estimates(wanted)}
        except Exception as error:
            log(f"model memory error: {error}")
            return {"gpu": 0, "context": 0, "models": {}}

    def hf_memory(self, repo_id, file_path, size, token=""):
        """The same estimate for a file on Hugging Face, from the first megabytes of its header."""
        try:
            meta = memory_estimate.remote_metadata(str(repo_id), str(file_path), str(token or "").strip())
            return {"gpu": memory_estimate.gpu_memory(), "context": llama_backend.SERVER.context_size,
                    "estimate": memory_estimate.estimate(int(size or 0), meta, llama_backend.SERVER.context_size),
                    "known": bool(meta)}
        except Exception as error:
            log(f"hf memory error: {error}")
            return {"gpu": 0, "context": 0, "estimate": None, "known": False}

    def model_logos(self, names, authors=None):
        names = [str(name) for name in names or []][:200]
        try:
            return model_logos.logos(names, authors if isinstance(authors, dict) else {})
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


def main():
    import webview
    if not UI_INDEX.is_file():
        webview.create_window(APP_NAME, html="<h3 style='font-family:Segoe UI'>Не найдена сборка modern-ui/dist. "
                                             "Запусти modern-ui\\scripts\\build.cmd.</h3>")
        webview.start()
        return
    if not acquire_instance_lock():
        webview.create_window(APP_NAME, html="<h3 style='font-family:Segoe UI'>Компаньон уже открыт (обычное или веб-окно). "
                                             "Закрой его, чтобы не перезаписать чаты.</h3>", width=620, height=200)
        webview.start()
        return
    app = WebCompanion()
    threading.Thread(target=app.refresh_models, daemon=True).start()
    window = webview.create_window("PIVEN Companion", url=str(UI_INDEX), js_api=WebApi(app),
                                   width=1440, height=900, min_size=(960, 640), background_color="#0a0a0a")
    app.window = window
    window.events.shown += lambda: style_title_bar(window, dark=True)
    window.events.closing += lambda: app.shutdown()
    webview.start(private_mode=False, storage_path=str(companion_core.DATA_DIR / "webview"))


if __name__ == "__main__":
    main()
