"""Local models through llama.cpp: finds GGUF files, runs llama-server.exe and streams chats.

One model is loaded at a time. Asking for another model restarts the server with it; asking the
same model again reuses the running server. A file whose name contains "mmproj" next to a model
is its vision projector and is passed with --mmproj, so the model can see images.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import process_job

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OllamaCompanion"
SERVER_EXE = APP_DIR / "llama.cpp" / "bin" / "llama-server.exe"
MODELS_DIR = DATA_DIR / "models"
HF_MODELS_DIR = DATA_DIR / "huggingface_models"
SERVER_LOG = DATA_DIR / "llama-server.log"
HOST = "127.0.0.1"
PORT = 47831  # uncommon on purpose, see companion_core TTS_PORT
BASE_URL = f"http://{HOST}:{PORT}"
MIN_MODEL_BYTES = 50 * 1024 * 1024  # skips empty or broken downloads

MODELS_DIR.mkdir(parents=True, exist_ok=True)


def model_files():
    """{model name: (gguf path, mmproj path or None)} for every usable GGUF on disk."""
    found = {}
    for root in (MODELS_DIR, HF_MODELS_DIR):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.gguf")):
            name = path.name.lower()
            if "mmproj" in name or path.stat().st_size < MIN_MODEL_BYTES:
                continue
            # multi-part models: load from the first part only
            if "-of-" in name and "-00001-of-" not in name:
                continue
            projectors = [item for item in path.parent.glob("*.gguf") if "mmproj" in item.name.lower()]
            label = path.stem.replace("-00001-of-", " (части) ").split(" (части) ")[0]
            if label in found:
                label = f"{path.parent.name}/{label}"
            found[label] = (path, projectors[0] if projectors else None)
    return found


def list_models():
    return list(model_files().keys())


def _model_parts(path):
    if "-00001-of-" in path.name:
        return sorted(path.parent.glob(path.name.replace("-00001-of-", "-*-of-")))
    return [path]


def _own_files(name, entries=None):
    """The files that belong to one model: its GGUF (all parts) and its mmproj unless another model shares it."""
    entries = entries or model_files()
    path, projector = entries[name]
    files = _model_parts(path)
    if projector and not any(other != name and shared == projector for other, (_, shared) in entries.items()):
        files.append(projector)
    return files


def model_sizes():
    """{model name: bytes on disk} for every local model."""
    entries = model_files()
    return {name: sum(item.stat().st_size for item in _own_files(name, entries)) for name in entries}


def delete_model(name):
    """Delete a local model's files and returns the bytes freed; stops the server first if it has it loaded."""
    entries = model_files()
    if name not in entries:
        raise RuntimeError("Такой модели нет в папке моделей.")
    if SERVER.loaded_model == name:
        SERVER.stop()
    files = _own_files(name, entries)
    roots = [MODELS_DIR.resolve(), HF_MODELS_DIR.resolve()]
    freed = 0
    for item in files:
        if not any(root in item.resolve().parents for root in roots):
            raise RuntimeError(f"Файл лежит вне папки моделей, не трогаю его: {item}")
        freed += item.stat().st_size
        item.unlink()
    folder = files[0].parent
    while folder.resolve() not in roots and not any(folder.iterdir()):
        folder.rmdir()
        folder = folder.parent
    return freed


def memory_estimates(names=None):
    """{model name: memory_estimate.estimate(...)} for local models at the server's context size."""
    import memory_estimate
    estimates = {}
    for name, (path, projector) in model_files().items():
        if names is not None and name not in names:
            continue
        parts = [path]
        if "-00001-of-" in path.name:
            parts = sorted(path.parent.glob(path.name.replace("-00001-of-", "-*-of-")))
        weights = sum(part.stat().st_size for part in parts)
        estimates[name] = memory_estimate.estimate(weights, memory_estimate.local_metadata(path), SERVER.context_size,
                                                   projector.stat().st_size if projector else 0)
    measured = measured_speeds()
    for name, estimate in estimates.items():
        if name in measured:
            estimate["speed"], estimate["measured"] = measured[name], True
    return estimates


def server_installed():
    return SERVER_EXE.exists()


def has_vision(model):
    entry = model_files().get(model)
    return bool(entry and entry[1])


class LlamaServer:
    """Owns the llama-server.exe process."""

    def __init__(self):
        self._process = None
        self._model = ""
        self._lock = threading.Lock()
        self.context_size = 16384

    @property
    def loaded_model(self):
        return self._model if self._process and self._process.poll() is None else ""

    def _healthy(self, timeout=1.5):
        try:
            with urllib.request.urlopen(BASE_URL + "/health", timeout=timeout) as response:
                return response.status == 200
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def stop(self):
        with self._lock:
            self._stop_locked()

    def _stop_locked(self):
        process, self._process, self._model = self._process, None, ""
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()

    def ensure(self, model, on_status=None, cancel_event=None):
        """Start (or reuse) the server for this model; returns when it answers /health."""
        with self._lock:
            if self.loaded_model == model and self._healthy():
                return
            if not server_installed():
                raise RuntimeError(f"Не найден llama-server.exe: {SERVER_EXE}")
            entry = model_files().get(model)
            if not entry:
                raise RuntimeError(f"Модель «{model}» не найдена в папке моделей: {MODELS_DIR}")
            self._stop_locked()
            gguf, projector = entry
            args = [str(SERVER_EXE), "-m", str(gguf), "--host", HOST, "--port", str(PORT),
                    "-c", str(self.context_size), "--no-webui"]
            if projector:
                args += ["--mmproj", str(projector)]
            if _port_busy():
                free_port(PORT, APP_DIR)
            if _port_busy():
                raise RuntimeError(f"Порт {PORT} занят другой программой, llama-server не может запуститься.")
            if on_status:
                on_status(f"Загружаю модель {model}")
            log_file = SERVER_LOG.open("ab")
            log_file.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(args)}\n".encode("utf-8"))
            log_file.flush()
            self._process = process_job.own(subprocess.Popen(args, cwd=str(SERVER_EXE.parent), stdout=log_file, stderr=subprocess.STDOUT,
                                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)))
            self._model = model
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                if cancel_event is not None and cancel_event.is_set():
                    self._stop_locked()
                    raise InterruptedError("Запрос прерван пользователем")
                if self._process.poll() is not None:
                    self._process = None
                    self._model = ""
                    raise RuntimeError("llama-server закрылся при загрузке модели. Подробности в журнале: " + str(SERVER_LOG))
                if self._healthy():
                    return
                time.sleep(0.5)
            self._stop_locked()
            raise RuntimeError("Модель не загрузилась за 10 минут. Подробности в журнале: " + str(SERVER_LOG))


def free_port(port, owner_dir):
    """Stop a server of ours left listening on `port` by a window that was closed without shutting it down.
    Only processes whose executable lies under `owner_dir` are touched; returns True when one was stopped."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        listing = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=10, creationflags=flags).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    pids = {parts[-1] for parts in (line.split() for line in listing.splitlines())
            if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3] == "LISTENING"}
    stopped = False
    for pid in pids:
        try:
            path = subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-Process -Id {int(pid)}).Path"],
                                  capture_output=True, text=True, timeout=15, creationflags=flags).stdout.strip()
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
        if path and Path(path).resolve().is_relative_to(Path(owner_dir).resolve()):
            subprocess.run(["taskkill", "/PID", pid, "/F", "/T"], capture_output=True, creationflags=flags)
            stopped = True
    deadline = time.monotonic() + 5
    while stopped and _port_busy(port) and time.monotonic() < deadline:
        time.sleep(0.2)
    return stopped


def _port_busy(port=PORT):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.3)
        return probe.connect_ex((HOST, port)) == 0


SERVER = LlamaServer()


def _to_openai(messages):
    """Ollama-style messages ({"images": [base64]}) → OpenAI chat format with image parts."""
    converted = []
    for message in messages:
        images = message.get("images") or []
        content = message.get("content", "")
        if images:
            parts = [{"type": "text", "text": content}] if content else []
            parts += [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}} for image in images]
            converted.append({"role": message.get("role", "user"), "content": parts})
        else:
            converted.append({"role": message.get("role", "user"), "content": content})
    return converted


SPEED_PATH = DATA_DIR / "model_speed.json"
_speed_lock = threading.Lock()


def _record_speed(model, timings):
    """Keep the generation speed of the last few answers per model (tokens per second)."""
    rate, count = timings.get("predicted_per_second"), timings.get("predicted_n") or 0
    if not isinstance(rate, (int, float)) or rate <= 0 or count < 16:
        return
    with _speed_lock:
        try:
            data = json.loads(SPEED_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        data[model] = (list(data.get(model, [])) + [round(float(rate), 1)])[-5:]
        try:
            SPEED_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass


def measured_speeds():
    """{model: median tokens per second of its recent answers}."""
    try:
        data = json.loads(SPEED_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {model: sorted(rates)[len(rates) // 2] for model, rates in data.items() if rates}


def chat(model, messages, think="__auto__", timeout=600, on_status=None, on_thinking=None,
         cancel_event=None, on_response=None, on_text=None):
    """Stream one answer; returns the final text. `think`: "__auto__", True/False or an effort level.
    `on_text` gets the whole answer written so far after every new piece."""
    if any(message.get("images") for message in messages) and not has_vision(model):
        raise RuntimeError("model does not support images: у этой модели нет файла mmproj рядом с GGUF, "
                           "поэтому она не видит картинки и экран.")
    SERVER.ensure(model, on_status=on_status, cancel_event=cancel_event)
    payload = {"messages": _to_openai(messages), "stream": True, "temperature": 0.7}
    if think in (True, False, "true", "false"):
        payload["chat_template_kwargs"] = {"enable_thinking": think in (True, "true")}
        if think in (False, "false"):
            payload["reasoning_budget"] = 0
    elif isinstance(think, str) and think not in ("", "__auto__"):
        payload["reasoning_effort"] = think
    request = urllib.request.Request(BASE_URL + "/v1/chat/completions", data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if on_response:
                on_response(response)
            try:
                parts, thinking_parts = [], []
                last_thinking_update, stage = 0.0, None
                for raw in response:
                    if cancel_event is not None and cancel_event.is_set():
                        raise InterruptedError("Запрос прерван пользователем")
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    if isinstance(chunk.get("timings"), dict):
                        _record_speed(model, chunk["timings"])
                    choices = chunk.get("choices") or []
                    delta = (choices[0].get("delta") or {}) if choices else {}
                    thought = delta.get("reasoning_content") or ""
                    if thought:
                        thinking_parts.append(thought)
                        now = time.monotonic()
                        if on_thinking and now - last_thinking_update >= 0.12:
                            on_thinking("".join(thinking_parts))
                            last_thinking_update = now
                        if stage != "thinking":
                            if on_status:
                                on_status("Модель обдумывает ответ")
                            stage = "thinking"
                    piece = delta.get("content") or ""
                    if piece:
                        parts.append(piece)
                        if on_text:
                            on_text("".join(parts))
                        if stage != "generating":
                            if on_status:
                                on_status("Модель пишет ответ")
                            stage = "generating"
                if cancel_event is not None and cancel_event.is_set():
                    raise InterruptedError("Запрос прерван пользователем")
                if thinking_parts and on_thinking:
                    on_thinking("".join(thinking_parts))
                return "".join(parts).strip()
            finally:
                if on_response:
                    on_response(None)
    except urllib.error.HTTPError as error:
        try:
            body = json.loads(error.read().decode("utf-8", errors="replace"))
            detail = (body.get("error") or {}).get("message", "") if isinstance(body.get("error"), dict) else str(body.get("error", ""))
        except Exception:
            detail = ""
        raise RuntimeError(f"llama.cpp HTTP {error.code}: {detail or error.reason}") from error
