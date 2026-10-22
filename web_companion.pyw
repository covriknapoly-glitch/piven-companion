"""PIVEN Companion with the React interface (modern-ui) in a pywebview window over CompanionCore.

The page talks to Python only through WebApi below: it polls `poll` for a state
snapshot and sends commands; chats and settings are the same files the Qt window uses.
"""
from __future__ import annotations

import base64
import mimetypes
import os
import sys
import threading
import time
from pathlib import Path

import companion_core  # sets up the bundled package paths before anything else
import re
from companion_core import (APP_DIR, APP_NAME, COMFY_DEFAULT_WORKFLOW, COMPANION_SYSTEM_PROMPT, DATA_DIR, LOG_PATH,
                            OLLAMA_THINK_LEVELS, CompanionCore, acquire_instance_lock, bounded_int, log,
                            ollama_get, ollama_model_thinking)

UI_INDEX = APP_DIR / "modern-ui" / "dist" / "index.html"
MAX_IMAGE_BYTES = 12_000_000
# Native title bar colours (caption, text, border) matching the page's sidebar per theme.
TITLE_BAR_COLORS = {True: (0x0D0D0F, 0xF0F0EE, 0x232327), False: (0xDFE0E3, 0x0C0C0E, 0xC9CACF)}


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

    # ---------- state ----------
    def _changed(self):
        self._version += 1

    def snapshot(self):
        with self._state_lock:
            active = self._active_chat() or {}
            # Newest first (chats are stored in creation order), pinned ones on top.
            chats = sorted(reversed(self.chats), key=lambda chat: not chat.get("pinned"))
            return {
                "version": self._version,
                "activeChatId": self.active_chat_id,
                "chats": [{"id": chat.get("id"), "title": chat.get("title") or "Новый чат",
                           "pinned": bool(chat.get("pinned")), "count": len(chat.get("items", []))}
                          for chat in chats],
                "items": [{"role": item.get("role", "system"), "text": str(item.get("text", "")),
                           "images": [str(path) for path in item.get("images") or []]}
                          for item in self.dialogue_items if isinstance(item, dict)],
                "chatTitle": active.get("title") or "Новый чат",
                "busy": bool(self.busy),
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
    def pump_events(self):
        """Apply queued worker events, mirroring CompanionApp._drain_events."""
        with self._state_lock:
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
    def send(self, text):
        text = str(text or "").strip()
        if not text:
            return {"ok": False, "error": "Пустое сообщение."}
        route = self._detect_composer_route(text)
        with self._state_lock:
            self._notice = ""
            if route in ("video", "audio"):
                return {"ok": False, "error": "Сейчас через ComfyUI подключена генерация изображений. Для видео и аудио нужен отдельный workflow."}
            if route == "image" and not self._integration_enabled("comfyui"):
                return {"ok": False, "error": "Интеграция ComfyUI выключена. Включи её в настройках Компаньона."}
            if route != "image" and not self._integration_enabled("ollama"):
                return {"ok": False, "error": "Интеграция Ollama выключена. Включи её в настройках Компаньона."}
            model = self.settings.get("model", "").strip()
            if route != "image" and not model:
                return {"ok": False, "error": "Сначала выбери модель Ollama."}
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
            names = [item.get("name") for item in ollama_get("/api/tags", timeout=3).get("models", [])
                     if isinstance(item.get("name"), str)]
            error = ""
        except Exception as exc:
            names, error = [], f"Ollama не отвечает: {exc}"
        with self._state_lock:
            self._models, self._models_error = names, error
            self._status = f"Ollama на связи, моделей: {len(names)}" if names else (error or "В Ollama нет моделей")
            if names and self.settings.get("model") not in names and not self.settings.get("model"):
                self.settings["model"] = names[0]
            self._changed()

    def _confirm_download(self, url, destination):
        # Downloads need a real confirmation dialog; the web window has none yet.
        self._notice = "Скачивание файлов пока подтверждается только в обычном окне Компаньона."
        return False


class WebApi:
    """Methods callable from JavaScript as window.pywebview.api.<name>()."""

    def __init__(self, app):
        self._app = app

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
                return {"ok": False, "error": "Такой модели нет в Ollama."}
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
            "voices": ["Russian"],
            "screenInterval": settings.get("screen_interval", 35),
            "micDevice": settings.get("mic_device", ""),
            "micSensitivity": settings.get("mic_sensitivity", 68),
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
            elif key == "voice":
                changes["voice"] = str(value or "Russian")[:60]
            elif key == "screenInterval":
                changes["screen_interval"] = bounded_int(value, 35, 10, 600)
            elif key == "micDevice":
                changes["mic_device"] = str(value or "")[:200]
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
                values, default = ollama_model_thinking(model)
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
        """Return a data: URL for an image that belongs to the active chat."""
        app = self._app
        path = str(path or "")
        with app._state_lock:
            known = {str(image) for item in app.dialogue_items for image in item.get("images") or []}
        file = Path(path)
        if path not in known or not file.is_file() or file.stat().st_size > MAX_IMAGE_BYTES:
            return ""
        mime = mimetypes.guess_type(file.name)[0] or ""
        if not mime.startswith("image/"):
            return ""
        return f"data:{mime};base64," + base64.b64encode(file.read_bytes()).decode("ascii")

    def open_file(self, path):
        """Open a generated image or presentation from the active chat with its Windows app."""
        app = self._app
        path = str(path or "")
        with app._state_lock:
            known = {str(image) for item in app.dialogue_items for image in item.get("images") or []}
        if path not in known or not Path(path).is_file():
            return {"ok": False}
        os.startfile(path)
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
                                   width=1440, height=900, min_size=(960, 640), background_color="#07141b")
    app.window = window
    window.events.shown += lambda: style_title_bar(window, dark=True)
    window.events.closing += lambda: app.shutdown()
    webview.start(private_mode=False, storage_path=str(companion_core.DATA_DIR / "webview"))


if __name__ == "__main__":
    main()
