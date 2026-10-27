"""Voice engines: which program runs a speech model, and the Python environment each one lives in. No UI code.

Every engine gets its own venv under kitten-tts-openwebui/engines/<engine>/.venv so their pinned
dependencies (one wants transformers 4.46, another 5.x) never collide. The shared venv with PyTorch
for CUDA is linked in through a .pth file, so PyTorch is downloaded once; an engine that needs other
versions of a package gets its own copy, which comes first on its path.

hf_voice_server.py, started with the engine's python, holds the code that loads and runs each model.
"""
from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import process_job

APP_DIR = Path(__file__).resolve().parent.parent  # the program folder; the code lives in app/
VOICE_DIR = APP_DIR / "kitten-tts-openwebui"
SHARED_VENV = VOICE_DIR / ".venv"
SHARED_PYTHON = SHARED_VENV / "Scripts" / "python.exe"
SHARED_SITE = SHARED_VENV / "Lib" / "site-packages"
ENGINES_DIR = VOICE_DIR / "engines"
BUNDLED_PYTHON = APP_DIR / "runtime" / "Python311" / "python.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

TORCH_INDEX = "https://download.pytorch.org/whl/cu130"
TORCH_PACKAGES = ["torch==2.14.1", "torchaudio==2.11.0"]
SHARED_PACKAGES = ["qwen-tts==0.1.1", "piper-tts==1.8.0", "fastapi", "uvicorn", "soundfile", "imageio-ffmpeg",
                   "python-multipart", "huggingface_hub", "accelerate", "librosa"]

# id: label, roles, pip packages for the engine's own venv (None: runs in the shared venv),
# packages installed without their dependencies (pins that would replace the CUDA PyTorch),
# and a short note shown in the settings.
ENGINES = {
    "nemo": {"label": "NeMo-Speech", "roles": {"asr"}, "pip": None, "note": "Parakeet и Nemotron от NVIDIA в формате GGUF."},
    "qwen": {"label": "Qwen3-TTS", "roles": {"tts"}, "pip": None, "note": "Модели Qwen3-TTS: готовые голоса, голос по описанию и клонирование."},
    "transformers": {"label": "Transformers", "roles": {"asr", "tts"}, "pip": None,
                     "note": "Whisper, wav2vec2, MMS, VITS, Bark, CSM и другие модели библиотеки Transformers."},
    "piper": {"label": "Piper", "roles": {"tts"}, "pip": None, "note": "Лёгкие голоса Piper, работают на процессоре."},
    "faster-whisper": {"label": "faster-whisper", "roles": {"asr"}, "pip": ["faster-whisper==1.2.1"],
                       "note": "Whisper в формате CTranslate2, быстрее обычного."},
    "qwen-asr": {"label": "Qwen3-ASR", "roles": {"asr"}, "pip": ["qwen-asr==0.0.6"], "note": "Распознавание речи Qwen3-ASR."},
    "kokoro": {"label": "Kokoro", "roles": {"tts"}, "pip": ["kokoro==0.9.4", "misaki[en]>=0.9.4"],
               "note": "Kokoro-82M: английский, испанский, французский, хинди, итальянский, японский, португальский, китайский."},
    "chatterbox": {"label": "Chatterbox", "roles": {"tts"},
                   "pip": ["librosa==0.11.0", "s3tokenizer", "transformers==5.2.0", "diffusers==0.29.0", "resemble-perth>=1.0.0",
                           "conformer==0.3.2", "safetensors", "pyloudnorm", "omegaconf", "spacy-pkuseg", "pykakasi==2.3.0"],
                   "no_deps": ["chatterbox-tts==0.1.7"], "note": "Chatterbox от Resemble AI, 23 языка с русским, клонирует голос."},
    "f5-tts": {"label": "F5-TTS", "roles": {"tts"}, "pip": ["f5-tts==1.1.22"], "note": "F5-TTS и E2-TTS, клонируют голос по образцу."},
    "coqui": {"label": "Coqui TTS", "roles": {"tts"}, "pip": ["coqui-tts[codec]==0.28.0"], "note": "XTTS-v2 (17 языков с русским) и другие модели Coqui."},
    "voxcpm": {"label": "VoxCPM", "roles": {"tts"}, "pip": ["voxcpm==2.0.3"], "note": "VoxCPM от OpenBMB."},
    "parler": {"label": "Parler-TTS", "roles": {"tts"}, "pip": ["parler-tts==0.2.3"], "note": "Parler-TTS: голос задаётся описанием."},
    "omnivoice": {"label": "OmniVoice", "roles": {"tts"}, "pip": ["omnivoice==0.2.1"], "note": "OmniVoice от k2-fsa."},
    "audiocpp": {"label": "audio.cpp", "roles": {"asr", "tts"}, "pip": None, "native": True,
                 "note": "Нативный движок на 130 семейств: GigaAM, CosyVoice3, IndexTTS2, VibeVoice, Fish Audio, XTTS, Kokoro и другие."},
}

# audio.cpp: the Windows CUDA 13 release from GitHub, checked against the release's SHA-256 digests.
AUDIOCPP_VERSION = "v0.9.3"
AUDIOCPP_DIR = ENGINES_DIR / "audiocpp"
AUDIOCPP_ASSETS = [
    (f"https://github.com/0xShug0/audio.cpp/releases/download/{AUDIOCPP_VERSION}/audio-{AUDIOCPP_VERSION}-bin-windows-x64-cuda13.3.zip",
     277_336_614, "0bd3988be10c31ec078c40df2bd0d4266e660804f6d5083aeb05d1309d091e43"),
    (f"https://github.com/0xShug0/audio.cpp/releases/download/{AUDIOCPP_VERSION}/audio-{AUDIOCPP_VERSION}-cudart-windows-x64-cuda13.3.zip",
     575_457_454, "839eb20f684a8aab64895b1e466b32ce9b29dfc19dc1ce15b2ef35218512ac0a"),
]


def audiocpp_server():
    found = sorted(AUDIOCPP_DIR.rglob("audiocpp_server.exe")) if AUDIOCPP_DIR.is_dir() else []
    return found[0] if found else None


def ensure_audiocpp(progress, cancel_event):
    """Download and unpack audio.cpp with its CUDA runtime next to the other engines."""
    if audiocpp_server() is not None:
        return 0
    import shutil
    import zipfile
    from voice_install import _download
    total = sum(size for _, size, _ in AUDIOCPP_ASSETS)
    done = 0
    AUDIOCPP_DIR.mkdir(parents=True, exist_ok=True)
    for url, size, digest in AUDIOCPP_ASSETS:
        archive = ENGINES_DIR / url.rsplit("/", 1)[1]
        if not (archive.is_file() and archive.stat().st_size == size):
            _download(url, archive, size, digest, cancel_event,
                      lambda received: progress(40 * (done + received) / total, f"Скачиваю audio.cpp: {(done + received) / 2**20:.0f} из {total / 2**20:.0f} МБ"))
        progress(40 * (done + size) / total, "Распаковываю audio.cpp")
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(AUDIOCPP_DIR)
        archive.unlink(missing_ok=True)
        done += size
    server = audiocpp_server()
    if server is None:
        shutil.rmtree(AUDIOCPP_DIR, ignore_errors=True)
        raise RuntimeError("В архиве audio.cpp нет audiocpp_server.exe.")
    # The CUDA runtime DLLs must sit next to the server.
    for dll in AUDIOCPP_DIR.rglob("*.dll"):
        if dll.parent != server.parent and not (server.parent / dll.name).exists():
            shutil.copy2(dll, server.parent / dll.name)
    ensure_espeak(cancel_event)
    return 40


def espeak_paths():
    """(library, data folder) of the eSpeak-ng copy audio.cpp uses for phonemes, or (None, None)."""
    library, data = AUDIOCPP_DIR / "espeak-ng.dll", AUDIOCPP_DIR / "espeak-ng-data"
    return (library, data) if library.is_file() and data.is_dir() else (None, None)


def ensure_espeak(cancel_event):
    """eSpeak-ng for Kokoro, Piper, Kitten and other phoneme-based families: the Windows build packaged in
    the espeakng-loader wheel from PyPI (GPL-3.0), unpacked next to audiocpp_server.exe."""
    if espeak_paths()[0] is not None:
        return
    import json as _json
    import urllib.request
    import zipfile
    from voice_install import _download
    with urllib.request.urlopen("https://pypi.org/pypi/espeakng-loader/json", timeout=30) as response:
        release = _json.loads(response.read().decode("utf-8"))
    wheel = next(item for item in release["urls"] if item["filename"].endswith("win_amd64.whl"))
    archive = ENGINES_DIR / wheel["filename"]
    _download(wheel["url"], archive, wheel["size"], wheel["digests"]["sha256"], cancel_event, lambda received: None)
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if name.startswith("espeakng_loader/") and not name.endswith(".py"):
                target = AUDIOCPP_DIR / name[len("espeakng_loader/"):]
                if name.endswith("/"):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.read(name))
    archive.unlink(missing_ok=True)
    library = AUDIOCPP_DIR / "espeak-ng.dll"
    if library.is_file():
        import shutil
        shutil.copy2(library, AUDIOCPP_DIR / "libespeak-ng.dll")  # the other common name

# Search hits: (engine, test). Tests see the library name, tags, model type and the repository id.
LIBRARY_ENGINES = {"ctranslate2": "faster-whisper", "kokoro": "kokoro", "chatterbox": "chatterbox", "f5-tts": "f5-tts",
                   "coqui": "coqui", "voxcpm": "voxcpm", "parler-tts": "parler", "omnivoice": "omnivoice", "piper": "piper",
                   "qwen-tts": "qwen", "qwen-asr": "qwen-asr"}
MODEL_TYPE_ENGINES = {"qwen3_asr": "qwen-asr", "qwen3_tts": "qwen", "parler_tts": "parler", "omnivoice": "omnivoice"}
NAME_ENGINES = [(r"faster-whisper|ctranslate2|-ct2\b", "faster-whisper"), (r"kokoro", "kokoro"), (r"chatterbox", "chatterbox"),
                (r"f5-?tts|e2-?tts", "f5-tts"), (r"xtts|coqui", "coqui"), (r"voxcpm", "voxcpm"), (r"parler", "parler"),
                (r"omnivoice", "omnivoice"), (r"piper", "piper"), (r"qwen3-asr", "qwen-asr")]
# Transformers models the generic pipelines can actually run.
TRANSFORMERS_TTS_TYPES = {"vits", "bark", "seamless_m4t", "seamless_m4t_v2", "csm", "dia", "fastspeech2_conformer"}
NOT_ON_WINDOWS = {"mlx": "формат MLX, он только для Mac", "mlx-audio": "формат MLX, он только для Mac",
                  "coreml": "формат Core ML, он только для Mac и iPhone", "whisperkit": "WhisperKit, он только для Mac и iPhone",
                  "vllm": "сервер vLLM, он работает только на Linux", "transformers.js": "формат для браузера (transformers.js)",
                  "executorch": "формат для телефонов (ExecuTorch)", "litert": "формат для телефонов (LiteRT)",
                  "pyannote-audio": "это не распознавание речи, а разделение говорящих"}


def engine_for(kind, item):
    """(engine id or "", reason) for a Hugging Face search hit."""
    tags = set(item.get("tags", []))
    library = item.get("library_name") or ""
    model_type = (item.get("config") or {}).get("model_type") or ""
    name = item["id"].lower()
    for key in (library, *sorted(tags)):
        if key in NOT_ON_WINDOWS:
            return "", NOT_ON_WINDOWS[key]
    candidates = [MODEL_TYPE_ENGINES.get(model_type), LIBRARY_ENGINES.get(library)]
    candidates += [engine for pattern, engine in NAME_ENGINES if re.search(pattern, name)]
    if kind == "asr" and "gguf" in tags:
        candidates.append("nemo")
    if library == "transformers" and model_type and (kind == "asr" or model_type in TRANSFORMERS_TTS_TYPES):
        candidates.append("transformers")
    for engine in candidates:
        if engine and kind in ENGINES[engine]["roles"]:
            return engine, ""
    if library == "transformers" and kind == "tts":
        return "", f"модель «{model_type or 'без типа'}» со своим кодом, общий движок Transformers её не запустит"
    if "onnx" in tags:
        return "", "формат ONNX без описания движка"
    return "", f"движок {library or 'не указан'}: такой в программу пока не встроен"


def venv_dir(engine):
    return SHARED_VENV if ENGINES[engine]["pip"] is None else ENGINES_DIR / engine / ".venv"


def python_for(engine):
    return venv_dir(engine) / "Scripts" / "python.exe"


def _marker(engine):
    return venv_dir(engine) / "piven-engine-ready.txt"


def shared_ready():
    return SHARED_PYTHON.is_file() and all((SHARED_SITE / name).is_dir() for name in ("torch", "qwen_tts", "fastapi", "uvicorn", "piper"))


def ready(engine):
    if engine == "nemo":
        from voice_install import ASR_EXE
        return ASR_EXE.is_file()
    if engine == "audiocpp":
        return audiocpp_server() is not None
    if ENGINES[engine]["pip"] is None:
        return shared_ready()
    return shared_ready() and _marker(engine).is_file()


def run(command, cancel_event, on_line, env=None, cwd=None):
    """Run a console command without a window; stops it on cancel. Raises on a non-zero exit."""
    process = subprocess.Popen(command, cwd=str(cwd or VOICE_DIR), env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
                               text=True, encoding="utf-8", errors="replace")
    process_job.own(process)
    tail = []

    def watch():
        while process.poll() is None:
            if cancel_event.is_set():
                process.kill()
                return
            time.sleep(0.3)
    threading.Thread(target=watch, daemon=True).start()
    for line in process.stdout:
        line = line.strip()
        if line:
            tail = (tail + [line])[-8:]
            on_line(line)
    process.wait()
    if cancel_event.is_set():
        raise InterruptedError("Установка отменена.")
    if process.returncode:
        raise RuntimeError("Команда завершилась с ошибкой:\n" + "\n".join(tail))


def _short(line):
    return line if len(line) < 140 else line[:137] + "…"


def _pip(python):
    return [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--progress-bar", "off"]


def ensure_shared(progress, cancel_event):
    """The shared venv with PyTorch for CUDA, Qwen3-TTS, Transformers and Piper; returns where the progress bar is."""
    if shared_ready():
        return 0
    if not SHARED_PYTHON.is_file():
        progress(1, "Создаю Python-окружение")
        python = BUNDLED_PYTHON if BUNDLED_PYTHON.is_file() else Path(sys.executable)
        run([str(python), "-m", "venv", str(SHARED_VENV)], cancel_event, lambda line: None)
    if not (SHARED_SITE / "torch").is_dir():
        progress(3, "Скачиваю PyTorch с CUDA, это самая долгая часть")
        run(_pip(SHARED_PYTHON) + TORCH_PACKAGES + ["--index-url", TORCH_INDEX], cancel_event,
            lambda line: progress(3, "PyTorch · " + _short(line)))
    progress(35, "Ставлю общие пакеты голоса")
    run(_pip(SHARED_PYTHON) + SHARED_PACKAGES, cancel_event, lambda line: progress(35, "Пакеты · " + _short(line)))
    return 40


def ensure_engine(engine, progress, cancel_event):
    """Install an engine (and the shared venv first); returns where the progress bar is afterwards."""
    start = ensure_shared(progress, cancel_event)
    info = ENGINES[engine]
    if info["pip"] is None or ready(engine):
        return start
    folder = venv_dir(engine)
    python = python_for(engine)
    if not python.is_file():
        progress(start + 1, f"Создаю окружение {info['label']}")
        base = BUNDLED_PYTHON if BUNDLED_PYTHON.is_file() else Path(sys.executable)
        run([str(base), "-m", "venv", str(folder)], cancel_event, lambda line: None)
    # Link the shared packages in after the engine's own ones, so PyTorch is reused unless the engine pins another.
    (folder / "Lib" / "site-packages" / "piven_shared.pth").write_text(str(SHARED_SITE) + "\n", encoding="utf-8")
    progress(start + 3, f"Ставлю {info['label']}")
    if info.get("no_deps"):
        run(_pip(python) + ["--no-deps"] + info["no_deps"], cancel_event, lambda line: progress(start + 3, f"{info['label']} · " + _short(line)))
    run(_pip(python) + info["pip"] + ["--extra-index-url", TORCH_INDEX], cancel_event,
        lambda line: progress(start + 3, f"{info['label']} · " + _short(line)))
    _marker(engine).write_text("ok\n", encoding="utf-8")
    return start + 10
