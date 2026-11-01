"""Local models through llama.cpp: finds GGUF files, runs llama-server.exe and streams chats.

Every loaded model has its own llama-server on its own port (see server_for): chats with different models
can answer at the same time. A model nobody is using is unloaded when the next one would not fit next to it
in video memory, or when more than `max_loaded` models would be loaded. A file whose name contains "mmproj" next to a model
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
import providers

APP_DIR = Path(__file__).resolve().parent.parent  # the program folder; the code lives in app/
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


_GGUF_SCALARS = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
_metadata_cache = {}


def gguf_metadata(path, wanted=("tokenizer.chat_template",)):
    """The wanted string/number keys of a GGUF file's header (big arrays such as the vocabulary are skipped)."""
    import struct
    path = Path(path)
    key = (str(path), path.stat().st_mtime, tuple(wanted))
    if key in _metadata_cache:
        return _metadata_cache[key]
    found = {}
    with path.open("rb") as handle:
        def read(fmt):
            size = struct.calcsize(fmt)
            return struct.unpack(fmt, handle.read(size))[0]

        def text():
            return handle.read(read("<Q")).decode("utf-8", "replace")

        def value(kind, keep):
            if kind == 8:
                return text() if keep else handle.seek(read("<Q"), 1)
            if kind == 9:
                item_kind, count = read("<I"), read("<Q")
                if item_kind in _GGUF_SCALARS:
                    handle.seek(struct.calcsize(_GGUF_SCALARS[item_kind]) * count, 1)
                else:
                    for _ in range(count):
                        value(item_kind, False)
                return None
            return read(_GGUF_SCALARS[kind])

        if handle.read(4) != b"GGUF":
            raise RuntimeError(f"Не GGUF-файл: {path.name}")
        read("<I"); read("<Q")
        for _ in range(read("<Q")):
            name = text()
            result = value(read("<I"), name in wanted)
            if name in wanted:
                found[name] = result
                if len(found) == len(wanted):
                    break
    _metadata_cache[key] = found
    return found


def thinking_modes(model):
    """(values, default) for the model's thinking switch, from its chat template.
    values: [] when it cannot be switched; default: True/False/effort, None when unknown."""
    if providers.is_provider_model(model):
        return [], None
    entry = model_files().get(model)
    if not entry:
        return [], None
    template = str(gguf_metadata(entry[0]).get("tokenizer.chat_template") or "")
    if "reasoning_effort" in template or "<|channel|>" in template:
        return ["low", "medium", "high"], "medium"
    if "enable_thinking" in template:
        return [True, False], True
    if "<think>" in template or "thinking" in template.lower():
        return [], True   # thinks every time
    return [], False


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
    stop_model(name)
    files = _own_files(name, entries)
    roots = [MODELS_DIR.resolve(), HF_MODELS_DIR.resolve()]
    freed = 0
    for item in files:
        if not any(root in item.resolve().parents for root in roots):
            raise RuntimeError(f"Файл лежит вне папки моделей и не будет удалён: {item}")
        freed += item.stat().st_size
        item.unlink()
    folder = files[0].parent
    while folder.resolve() not in roots and not any(folder.iterdir()):
        folder.rmdir()
        folder = folder.parent
    return freed


reserved_vram = [0]   # video memory the voice models hold, set by the companion (they share the GPU with the model)


def memory_estimates(names=None, context=None):
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
        params = params_for(name)
        estimates[name] = memory_estimate.estimate(weights, memory_estimate.local_metadata(path), context or params["ctx_size"],
                                                   projector.stat().st_size if projector else 0,
                                                   kv_share=KV_SHARE[params["kv_type"]], reserved=reserved_vram[0],
                                                   vram_limit=params["vram_limit_gb"] * 2 ** 30)
    # Calibration: where real speeds are known, the median ratio real/estimated corrects the other estimates.
    measured = measured_speeds()
    ratios = sorted(measured[name] / estimate["speed"] for name, estimate in estimates.items()
                    if name in measured and estimate["speed"] > 0)
    factor = min(2.0, max(0.3, ratios[len(ratios) // 2])) if ratios else 1.0
    for name, estimate in estimates.items():
        if name in measured:
            estimate["speed"], estimate["measured"] = measured[name], True
        else:
            estimate["speed"] = round(estimate["speed"] * factor, 1)
    return estimates


# ---------- model parameters ----------
# The balanced preset: llama.cpp's own sampling defaults, a 16K context and automatic GPU fitting.
DEFAULT_PARAMS = {
    # loading (changing these restarts the model)
    "ctx_size": 16384, "gpu_layers": -1, "flash_attn": "auto", "kv_type": "f16", "threads": 0,
    "batch": 2048, "ubatch": 512, "mmap": True, "mlock": False, "n_cpu_moe": 0,
    "vram_limit_gb": 0.0, "ram_limit_gb": 0.0, "speculative": "auto",
    # answers
    "temperature": 0.7, "top_k": 40, "top_p": 0.95, "min_p": 0.05, "typical_p": 1.0,
    "repeat_penalty": 1.0, "repeat_last_n": 64, "presence_penalty": 0.0, "frequency_penalty": 0.0,
    "dry_multiplier": 0.0, "dry_base": 1.75, "dry_allowed_length": 2, "xtc_probability": 0.0, "xtc_threshold": 0.1,
    "mirostat": 0, "mirostat_tau": 5.0, "mirostat_eta": 0.1, "seed": -1, "max_tokens": -1,
    # conversation memory
    "compress_context": True,
}
PRESETS = {
    "balanced": {},
    "precise": {"temperature": 0.3, "top_p": 0.9, "min_p": 0.1, "repeat_penalty": 1.05},
    "creative": {"temperature": 1.0, "top_p": 0.98, "min_p": 0.03, "xtc_probability": 0.5, "dry_multiplier": 0.8},
    "economy": {"ctx_size": 8192, "kv_type": "q8_0", "flash_attn": "on"},
}
PARAM_LIMITS = {
    "ctx_size": (512, 1048576), "gpu_layers": (-1, 999), "threads": (0, 256), "batch": (32, 16384), "ubatch": (32, 8192),
    "n_cpu_moe": (0, 999), "vram_limit_gb": (0.0, 512.0), "ram_limit_gb": (0.0, 2048.0),
    "temperature": (0.0, 5.0), "top_k": (0, 1000), "top_p": (0.0, 1.0), "min_p": (0.0, 1.0), "typical_p": (0.0, 1.0),
    "repeat_penalty": (0.5, 3.0), "repeat_last_n": (-1, 8192), "presence_penalty": (-2.0, 2.0), "frequency_penalty": (-2.0, 2.0),
    "dry_multiplier": (0.0, 5.0), "dry_base": (1.0, 4.0), "dry_allowed_length": (1, 64), "xtc_probability": (0.0, 1.0),
    "xtc_threshold": (0.0, 0.5), "mirostat": (0, 2), "mirostat_tau": (0.0, 20.0), "mirostat_eta": (0.0, 1.0),
    "seed": (-1, 2 ** 31 - 1), "max_tokens": (-1, 1048576),
}
KV_SHARE = {"f16": 1.0, "q8_0": 0.53, "q4_0": 0.28}
CHOICES = {"flash_attn": ("auto", "on", "off"), "kv_type": ("f16", "q8_0", "q4_0"), "speculative": ("auto", "ngram", "off")}
SERVER_KEYS = ("ctx_size", "gpu_layers", "flash_attn", "kv_type", "threads", "batch", "ubatch", "mmap", "mlock",
               "n_cpu_moe", "vram_limit_gb", "ram_limit_gb", "speculative")
SAMPLING_KEYS = ("temperature", "top_k", "top_p", "min_p", "typical_p", "repeat_penalty", "repeat_last_n", "presence_penalty",
                 "frequency_penalty", "dry_multiplier", "dry_base", "dry_allowed_length", "xtc_probability", "xtc_threshold",
                 "mirostat", "mirostat_tau", "mirostat_eta", "seed")

model_params = {}   # settings["model_params"]: {"*": changes for every model, "<model>": changes for one model}


def clean_params(values):
    """Only known keys, with values of the right type inside their limits."""
    clean = {}
    for key, value in (values or {}).items():
        if key not in DEFAULT_PARAMS:
            continue
        default = DEFAULT_PARAMS[key]
        try:
            if key in CHOICES:
                value = str(value) if str(value) in CHOICES[key] else default
            elif isinstance(default, bool):
                value = bool(value)
            elif isinstance(default, int):
                value = int(float(value))
            else:
                value = float(value)
        except (TypeError, ValueError):
            continue
        if key in PARAM_LIMITS:
            low, high = PARAM_LIMITS[key]
            value = min(max(value, low), high)
        clean[key] = value
    return clean


def params_for(model):
    """The parameters a model runs with: the preset, then the changes for all models, then its own."""
    return {**DEFAULT_PARAMS, **clean_params(model_params.get("*")), **clean_params(model_params.get(model))}


def context_size(model=""):
    return params_for(model)["ctx_size"]


def has_mtp(gguf):
    """True when the model carries multi-token-prediction heads (Qwen3.5/3.6 "MTP", GLM): llama.cpp can use them
    to draft several tokens at once, ~1.4× faster with exactly the same answers."""
    arch = gguf_metadata(gguf, ("general.architecture",)).get("general.architecture", "")
    return bool(gguf_metadata(gguf, (f"{arch}.nextn_predict_layers",)).get(f"{arch}.nextn_predict_layers"))


def _server_options(model, params, projector, gguf=None):
    """llama-server arguments for the loading parameters."""
    import memory_estimate
    options = ["-c", str(params["ctx_size"]), "-np", "1", "-fa", params["flash_attn"]]
    if params["speculative"] != "off" and gguf is not None:
        kinds = (["draft-mtp"] if has_mtp(gguf) else []) + (["ngram-mod"] if params["speculative"] == "ngram" else [])
        if kinds:
            options += ["--spec-type", ",".join(kinds)]
    if params["gpu_layers"] >= 0:
        options += ["-ngl", str(params["gpu_layers"])]
    if params["kv_type"] != "f16":
        options += ["-ctk", params["kv_type"], "-ctv", params["kv_type"]]
    if params["threads"] > 0:
        options += ["-t", str(params["threads"])]
    if params["batch"] != DEFAULT_PARAMS["batch"]:
        options += ["-b", str(params["batch"])]
    if params["ubatch"] != DEFAULT_PARAMS["ubatch"]:
        options += ["-ub", str(params["ubatch"])]
    if not params["mmap"]:
        options.append("--no-mmap")
    if params["mlock"]:
        options.append("--mlock")
    if params["n_cpu_moe"] > 0:
        options += ["-ncmoe", str(params["n_cpu_moe"])]
    total_vram = memory_estimate.gpu_memory()
    if params["vram_limit_gb"] > 0 and total_vram:
        # --fit offloads as many layers as fit while leaving this much video memory free
        margin = max(256, int((total_vram - params["vram_limit_gb"] * 2 ** 30) / 2 ** 20))
        options += ["-fit", "on", "-fitt", str(margin)]
    return options


def check_ram_limit(model, params):
    """Refuse to load a model whose part outside video memory needs more RAM than the limit allows."""
    limit = params["ram_limit_gb"]
    if limit <= 0:
        return
    import memory_estimate
    estimate = memory_estimates([model], context=params["ctx_size"]).get(model)
    if not estimate:
        return
    vram = memory_estimate.gpu_memory()
    if params["vram_limit_gb"] > 0:
        vram = min(vram, params["vram_limit_gb"] * 2 ** 30) if vram else params["vram_limit_gb"] * 2 ** 30
    in_ram = max(0, estimate["total"] - max(0, vram - 2 ** 30))
    if in_ram > limit * 2 ** 30:
        raise RuntimeError(f"Модель «{model}» не помещается в лимит оперативной памяти: ей нужно около "
                           f"{in_ram / 2 ** 30:.1f} ГБ ОЗУ, лимит {limit:g} ГБ. Уменьши контекст, подними лимит "
                           f"или выбери модель поменьше.")


def sampling_payload(params):
    """The answer parameters as llama-server request fields."""
    payload = {key: params[key] for key in SAMPLING_KEYS}
    if params["max_tokens"] > 0:
        payload["max_tokens"] = params["max_tokens"]
    if payload["seed"] < 0:
        payload.pop("seed")
    return payload


def server_installed():
    return SERVER_EXE.exists()


def has_vision(model):
    if providers.is_provider_model(model):
        return True  # cloud and other local programs: their API refuses images itself when a model cannot see
    entry = model_files().get(model)
    return bool(entry and entry[1])


class LlamaServer:
    """Owns one llama-server.exe process and the model in it."""

    def __init__(self, port=PORT):
        self.port = port
        self.base_url = f"http://{HOST}:{port}"
        self._process = None
        self._model = ""
        self._lock = threading.Lock()
        self._options = []
        self.in_use = 0          # answers streaming from this server right now
        self.claimed = ""        # the model this server is being started for (between choosing and loading)
        self.last_used = 0.0

    @property
    def context_size(self):
        return context_size(self._model)

    @property
    def loaded_model(self):
        return self._model if self._process and self._process.poll() is None else ""

    def _healthy(self, timeout=1.5):
        try:
            with urllib.request.urlopen(self.base_url + "/health", timeout=timeout) as response:
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
            entry = model_files().get(model)
            if not entry:
                raise RuntimeError(f"Модель «{model}» не найдена в папке моделей: {MODELS_DIR}")
            gguf, projector = entry
            params = params_for(model)
            options = _server_options(model, params, projector, gguf)
            if self.loaded_model == model and self._options == options and self._healthy():
                return
            if not server_installed():
                raise RuntimeError(f"Не найден llama-server.exe: {SERVER_EXE}")
            check_ram_limit(model, params)
            self._stop_locked()
            args = [str(SERVER_EXE), "-m", str(gguf), "--host", HOST, "--port", str(self.port), "--no-webui"] + options
            if projector:
                args += ["--mmproj", str(projector)]
            if _port_busy(self.port):
                free_port(self.port, APP_DIR)
            if _port_busy(self.port):
                raise RuntimeError(f"Порт {self.port} занят другой программой, llama-server не может запуститься.")
            if on_status:
                on_status(f"Загрузка модели {model}")
            log_file = SERVER_LOG.open("ab")
            log_file.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(args)}\n".encode("utf-8"))
            log_file.flush()
            self._process = process_job.own(subprocess.Popen(args, cwd=str(SERVER_EXE.parent), stdout=log_file, stderr=subprocess.STDOUT,
                                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)))
            self._model = model
            self._options = options
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


SERVER = LlamaServer()                  # the first server; more are added for models loaded at the same time
SERVERS = [SERVER]
EXTRA_PORTS = list(range(47860, 47868))
max_loaded = [3]                         # models kept loaded at once (setting "max_loaded_models")
_pool_lock = threading.Lock()


def loaded_models():
    return [server.loaded_model for server in SERVERS if server.loaded_model]


def model_in_use(model):
    return any(server.in_use and server.loaded_model == model for server in SERVERS)


def stop_model(model):
    for server in SERVERS:
        if server.loaded_model == model:
            server.stop()


def stop_all():
    for server in SERVERS:
        server.stop()


def _vram_need(model):
    estimate = memory_estimates([model]).get(model)
    return estimate["total"] if estimate else 0


def server_for(model):
    """The server that has (or will load) this model. Idle models are unloaded when the new one would not fit
    next to them in video memory or the limit of loaded models is reached; models that are answering stay."""
    import memory_estimate
    with _pool_lock:
        for server in SERVERS:
            if server.loaded_model == model or server.claimed == model:
                return server
        gpu = memory_estimate.gpu_memory()
        room = gpu * 0.95 - reserved_vram[0] if gpu else 0
        need = _vram_need(model)
        busy = [server for server in SERVERS if server.loaded_model or server.claimed]
        for server in sorted(busy, key=lambda item: item.last_used):
            if server.in_use or server.claimed:
                continue
            others = sum(_vram_need(item.loaded_model or item.claimed) for item in busy if item is not server)
            too_many = len(busy) >= max(1, max_loaded[0])
            if too_many or (room and others + _vram_need(server.loaded_model) + need > room):
                server.stop()
                busy.remove(server)
        free = [server for server in SERVERS if not (server.loaded_model or server.claimed)]
        if free:
            target = free[0]
        elif len(SERVERS) < 1 + len(EXTRA_PORTS):
            target = LlamaServer(EXTRA_PORTS[len(SERVERS) - 1])
            SERVERS.append(target)
        else:
            raise RuntimeError("Сейчас отвечают другие модели, свободного места для ещё одной нет. Дождись их ответов.")
        target.claimed = model
        return target


def _to_openai(messages):
    """Ollama-style messages ({"images": [base64]}) → OpenAI chat format with image parts; tool calls and
    tool results pass through."""
    converted = []
    for message in messages:
        images = message.get("images") or []
        content = message.get("content", "")
        if images:
            parts = [{"type": "text", "text": content}] if content else []
            parts += [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}} for image in images]
            item = {"role": message.get("role", "user"), "content": parts}
        else:
            item = {"role": message.get("role", "user"), "content": content}
        if message.get("tool_calls"):
            item["tool_calls"] = [{"id": call["id"], "type": "function",
                                   "function": {"name": call["name"], "arguments": json.dumps(call["arguments"], ensure_ascii=False)}}
                                  for call in message["tool_calls"]]
        if message.get("role") == "tool":
            item["tool_call_id"] = message.get("tool_call_id", "")
        converted.append(item)
    return converted

def collect_tool_calls(delta, calls):
    """Add one streamed delta's tool-call fragments to `calls` ({index: {"id", "name", "arguments"}})."""
    for fragment in delta.get("tool_calls") or []:
        slot = calls.setdefault(fragment.get("index", len(calls)), {"id": "", "name": "", "arguments": ""})
        slot["id"] = fragment.get("id") or slot["id"]
        function = fragment.get("function") or {}
        slot["name"] += function.get("name") or ""
        slot["arguments"] += function.get("arguments") or ""


def finished_tool_calls(calls):
    """The collected calls as [{"id", "name", "arguments": dict}] in order."""
    result = []
    for index in sorted(calls):
        call = calls[index]
        try:
            arguments = json.loads(call["arguments"] or "{}")
        except ValueError:
            arguments = {"_raw": call["arguments"]}
        result.append({"id": call["id"] or f"call_{index}", "name": call["name"], "arguments": arguments if isinstance(arguments, dict) else {}})
    return [call for call in result if call["name"]]



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


_THINK_TAGS = (("<think>", "</think>"), ("<thinking>", "</thinking>"), ("[THINK]", "[/THINK]"), ("<|begin_of_thought|>", "<|end_of_thought|>"))


def split_thinking(text):
    """(thought, answer) of a reply whose model wrote its reasoning into the answer text between tags
    instead of the separate reasoning field. An unclosed tag means it is still thinking; a closing tag
    without an opening one means the template opened it."""
    thought, answer = [], str(text)
    for opening, closing in _THINK_TAGS:
        if closing in answer and opening not in answer.split(closing, 1)[0]:
            head, answer = answer.split(closing, 1)
            thought.append(head)
        while opening in answer:
            before, rest = answer.split(opening, 1)
            if closing in rest:
                inner, after = rest.split(closing, 1)
                thought.append(inner); answer = before + after
            else:
                thought.append(rest); answer = before
    return "".join(thought).strip(), answer.lstrip() if thought else answer


def chat(model, messages, think="__auto__", timeout=600, on_status=None, on_thinking=None,
         cancel_event=None, on_response=None, on_text=None, overrides=None, tools=None, tool_calls=None):
    """Stream one answer; returns the final text. `think`: "__auto__", True/False or an effort level.
    `on_text` gets the whole answer written so far after every new piece. With `tools` (OpenAI format) the
    model may call them instead: the calls are appended to the `tool_calls` list."""
    if providers.is_provider_model(model):  # Ollama, LM Studio, cloud: their own servers
        return providers.chat(model, messages, timeout, on_status, on_thinking, cancel_event, on_response, on_text,
                              overrides, {**sampling_payload(params_for(model)), "max_tokens": params_for(model)["max_tokens"]},
                              tools, tool_calls)
    if any(message.get("images") for message in messages) and not has_vision(model):
        raise RuntimeError("model does not support images: у этой модели нет файла mmproj рядом с GGUF, "
                           "поэтому она не видит картинки и экран.")
    server = server_for(model)
    try:
        server.ensure(model, on_status=on_status, cancel_event=cancel_event)
    finally:
        server.claimed = ""
    server.in_use += 1
    server.last_used = time.monotonic()
    try:
        return _stream(server, model, messages, think, timeout, on_status, on_thinking, cancel_event, on_response, on_text, overrides,
                       tools, tool_calls)
    finally:
        server.in_use -= 1
        server.last_used = time.monotonic()


def _stream(server, model, messages, think, timeout, on_status, on_thinking, cancel_event, on_response, on_text, overrides,
            tools=None, tool_calls=None):
    payload = {"messages": _to_openai(messages), "stream": True, **sampling_payload(params_for(model)), **(overrides or {})}
    if tools:
        payload["tools"] = tools
    calls = {}
    if think in (True, False, "true", "false"):
        payload["chat_template_kwargs"] = {"enable_thinking": think in (True, "true")}
        if think in (False, "false"):
            payload["reasoning_budget"] = 0
    elif isinstance(think, str) and think not in ("", "__auto__"):
        payload["reasoning_effort"] = think
        payload["chat_template_kwargs"] = {"reasoning_effort": think}  # gpt-oss reads it from the template
    request = urllib.request.Request(server.base_url + "/v1/chat/completions", data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
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
                    collect_tool_calls(delta, calls)
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
                        inline, visible = split_thinking("".join(parts))
                        if inline:  # reasoning written into the answer: show it as thinking, never as the answer
                            if on_thinking:
                                on_thinking("".join(thinking_parts) + inline)
                            if not visible.strip():
                                continue
                        if on_text:
                            on_text(visible)
                        if stage != "generating":
                            if on_status:
                                on_status("Модель пишет ответ")
                            stage = "generating"
                if cancel_event is not None and cancel_event.is_set():
                    raise InterruptedError("Запрос прерван пользователем")
                inline, visible = split_thinking("".join(parts))
                if (thinking_parts or inline) and on_thinking:
                    on_thinking("".join(thinking_parts) + inline)
                if tool_calls is not None:
                    tool_calls.extend(finished_tool_calls(calls))
                return visible.strip()
            finally:
                if on_response:
                    on_response(None)
    except (AttributeError, ValueError, OSError) as error:
        # the stop button closes the connection under the reader: http.client then fails in odd ways
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Запрос прерван пользователем") from error
        if isinstance(error, urllib.error.HTTPError):
            raise _llama_http_error(error) from error
        raise RuntimeError(f"Связь с llama.cpp оборвалась: {error}") from error


def _llama_http_error(error):
    try:
        body = json.loads(error.read().decode("utf-8", errors="replace"))
        detail = (body.get("error") or {}).get("message", "") if isinstance(body.get("error"), dict) else str(body.get("error", ""))
    except Exception:
        detail = ""
    return RuntimeError(f"llama.cpp HTTP {error.code}: {detail or error.reason}")
