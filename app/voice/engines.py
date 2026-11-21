from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from app import processes

APP_DIR = Path(__file__).resolve().parents[2]
VOICE_DIR = APP_DIR / "voice-engines"
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

ENGINES = {
    "nemo": {"label": "NeMo-Speech", "roles": {"asr"}, "pip": None, "note": "Parakeet и Nemotron от NVIDIA в формате GGUF."},
    "transcribe": {"label": "transcribe.cpp", "roles": {"asr"}, "native": True, "pip": None},
    "qwen": {"label": "Qwen3-TTS", "roles": {"tts"}, "pip": None, "note": "Модели Qwen3-TTS: готовые голоса, голос по описанию и клонирование."},
    "transformers": {"label": "Transformers", "roles": {"asr", "tts"}, "pip": None,
                     "note": "Whisper, wav2vec2, MMS, VITS, Bark, CSM и другие модели библиотеки Transformers."},
    "piper": {"label": "Piper", "roles": {"tts"}, "pip": None, "note": "Лёгкие голоса Piper, работают на процессоре."},
    "vosk": {"label": "Vosk", "roles": {"asr"}, "standalone": True,
             "pip": ["vosk==0.3.45", "numpy", "soundfile", "fastapi", "uvicorn", "python-multipart"],
             "note": "Лёгкие офлайн-модели русского и английского для процессора."},
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

AUDIOCPP_VERSION = "v0.9.3"
TRANSCRIBE_VERSION = "0.4.1"
TRANSCRIBE_ARCHIVE = f"transcribe-native-{TRANSCRIBE_VERSION}-windows-x86_64-cpu-vulkan.tar.gz"
TRANSCRIBE_SIZE = 18_052_295
TRANSCRIBE_SHA256 = "272eb97795048ccb557c85bb9dd44c9e530e1c928443114c39816a8a5f76269d"
TRANSCRIBE_WHEEL = f"transcribe_cpp-{TRANSCRIBE_VERSION}-py3-none-any.whl"
TRANSCRIBE_WHEEL_URL = "https://files.pythonhosted.org/packages/60/df/55b97bec42c43f44a3d1bf1d4bbaf32b8bb1f99f444f4d49bfe6ca4224f4/" + TRANSCRIBE_WHEEL
TRANSCRIBE_WHEEL_SHA256 = "a4bb6ffb8eac16875daec12a8b3b9598024a34d1c10507cff51f0c42400eab5d"
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


def transcribe_library():
    return ENGINES_DIR / "transcribe" / f"native-{TRANSCRIBE_VERSION}" / "transcribe.dll"


def transcribe_bindings():
    return transcribe_library().parent.parent / TRANSCRIBE_WHEEL


def ensure_transcribe(progress, cancel_event):
    import tarfile
    import tempfile
    from app.voice.install import _download

    library = transcribe_library()
    if ready("transcribe"):
        return 0
    if not library.is_file():
        folder = library.parent.parent
        archive = folder / TRANSCRIBE_ARCHIVE
        _download(f"https://github.com/handy-computer/transcribe.cpp/releases/download/v{TRANSCRIBE_VERSION}/{TRANSCRIBE_ARCHIVE}",
                  archive, TRANSCRIBE_SIZE, TRANSCRIBE_SHA256, cancel_event,
                  lambda received: progress(10 * received / TRANSCRIBE_SIZE, "Скачивание transcribe.cpp"))
        with tempfile.TemporaryDirectory(dir=folder) as temporary:
            with tarfile.open(archive) as bundle:
                bundle.extractall(temporary, filter="data")
            extracted = Path(temporary) / "transcribe-native-windows-x86_64-cpu-vulkan"
            if not (extracted / library.name).is_file():
                raise RuntimeError("В архиве transcribe.cpp нет transcribe.dll.")
            extracted.replace(library.parent)
        archive.unlink(missing_ok=True)
    bindings = transcribe_bindings()
    if not bindings.is_file():
        progress(10, "Скачивание Python-обвязки transcribe.cpp")
        _download(TRANSCRIBE_WHEEL_URL, bindings, 0, TRANSCRIBE_WHEEL_SHA256, cancel_event, lambda received: None)
    return 12


def ensure_audiocpp(progress, cancel_event):
    if audiocpp_server() is not None:
        return 0
    import shutil
    import zipfile
    from app.voice.install import _download
    total = sum(size for _, size, _ in AUDIOCPP_ASSETS)
    done = 0
    AUDIOCPP_DIR.mkdir(parents=True, exist_ok=True)
    for url, size, digest in AUDIOCPP_ASSETS:
        archive = ENGINES_DIR / url.rsplit("/", 1)[1]
        if not (archive.is_file() and archive.stat().st_size == size):
            _download(url, archive, size, digest, cancel_event,
                      lambda received: progress(40 * (done + received) / total, f"Скачивание audio.cpp: {(done + received) / 2**20:.0f} из {total / 2**20:.0f} МБ"))
        progress(40 * (done + size) / total, "Распаковываю audio.cpp")
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(AUDIOCPP_DIR)
        archive.unlink(missing_ok=True)
        done += size
    server = audiocpp_server()
    if server is None:
        shutil.rmtree(AUDIOCPP_DIR, ignore_errors=True)
        raise RuntimeError("В архиве audio.cpp нет audiocpp_server.exe.")
    for dll in AUDIOCPP_DIR.rglob("*.dll"):
        if dll.parent != server.parent and not (server.parent / dll.name).exists():
            shutil.copy2(dll, server.parent / dll.name)
    ensure_espeak(cancel_event)
    return 40


def espeak_paths():
    library, data = AUDIOCPP_DIR / "espeak-ng.dll", AUDIOCPP_DIR / "espeak-ng-data"
    return (library, data) if library.is_file() and data.is_dir() else (None, None)


def ensure_espeak(cancel_event):
    if espeak_paths()[0] is not None:
        return
    import json as _json
    import urllib.request
    import zipfile
    from app.voice.install import _download
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
        shutil.copy2(library, AUDIOCPP_DIR / "libespeak-ng.dll")

LIBRARY_ENGINES = {"ctranslate2": "faster-whisper", "kokoro": "kokoro", "chatterbox": "chatterbox", "f5-tts": "f5-tts",
                   "coqui": "coqui", "voxcpm": "voxcpm", "parler-tts": "parler", "omnivoice": "omnivoice", "piper": "piper",
                   "qwen-tts": "qwen", "qwen-asr": "qwen-asr"}
MODEL_TYPE_ENGINES = {"qwen3_asr": "qwen-asr", "qwen3_tts": "qwen", "parler_tts": "parler", "omnivoice": "omnivoice"}
NAME_ENGINES = [(r"faster-whisper|ctranslate2|-ct2\b", "faster-whisper"), (r"kokoro", "kokoro"), (r"chatterbox", "chatterbox"),
                (r"f5-?tts|e2-?tts", "f5-tts"), (r"xtts|coqui", "coqui"), (r"voxcpm", "voxcpm"), (r"parler", "parler"),
                (r"omnivoice", "omnivoice"), (r"piper", "piper"), (r"qwen3-asr", "qwen-asr")]
TRANSFORMERS_TTS_TYPES = {"vits", "bark", "seamless_m4t", "seamless_m4t_v2", "csm", "dia", "fastspeech2_conformer"}
TRANSFORMERS_ASR_TYPES = {"whisper", "wav2vec2", "wav2vec2-bert", "wav2vec2-conformer", "hubert", "wavlm",
                          "data2vec-audio", "sew", "sew-d", "unispeech", "unispeech-sat", "mctct", "parakeet_ctc",
                          "speech_to_text", "speech-encoder-decoder", "moonshine", "granite_speech", "kyutai_speech_to_text",
                          "seamless_m4t", "seamless_m4t_v2", "speecht5"}
NOT_ON_WINDOWS = {"mlx": "формат MLX, он только для Mac", "mlx-audio": "формат MLX, он только для Mac",
                  "coreml": "формат Core ML, он только для Mac и iPhone", "whisperkit": "WhisperKit, он только для Mac и iPhone",
                  "vllm": "сервер vLLM, он работает только на Linux", "transformers.js": "формат для браузера (transformers.js)",
                  "executorch": "формат для телефонов (ExecuTorch)", "litert": "формат для телефонов (LiteRT)",
                  "pyannote-audio": "это не распознавание речи, а разделение говорящих"}


def engine_for(kind, item):
    tags = set(item.get("tags") or [])
    library = item.get("library_name") or ""
    model_type = (item.get("config") or {}).get("model_type") or ""
    task = item.get("pipeline_tag")
    if task == "automatic-speech-recognition" and kind == "tts":
        return "", "Эта модель предназначена для распознавания речи. Открой вкладку распознавания."
    if task in ("text-to-speech", "text-to-audio") and kind == "asr":
        return "", "Эта модель генерирует аудио. Проверь её во вкладке озвучки."
    if library in NOT_ON_WINDOWS:
        return "", NOT_ON_WINDOWS[library]
    files = {record.get("rfilename") or "" for record in item.get("siblings") or []}
    has_weights = any(name.endswith((".safetensors", ".bin")) for name in files)
    if not library and not has_weights:
        for tag in sorted(tags):
            if tag in NOT_ON_WINDOWS:
                return "", NOT_ON_WINDOWS[tag]
    candidates = [MODEL_TYPE_ENGINES.get(model_type), LIBRARY_ENGINES.get(library)]
    if kind == "asr" and ({"config.json", "model.bin", "vocabulary.json"} <= files or "ctranslate2" in tags):
        candidates.append("faster-whisper")
    candidates += [engine for pattern, engine in NAME_ENGINES if re.search(pattern, item["id"].lower())]
    if kind == "asr" and "gguf" in tags and not has_weights:
        candidates.append("nemo")
    if model_type in (TRANSFORMERS_ASR_TYPES if kind == "asr" else TRANSFORMERS_TTS_TYPES):
        candidates.append("transformers")
    for engine in candidates:
        if engine and kind in ENGINES[engine]["roles"]:
            return engine, ""
    if library == "transformers" and model_type:
        return "", f"Движок Transformers пока не поддерживает «{model_type}» для этой задачи."
    if "onnx" in tags:
        return "", "формат ONNX без описания движка"
    if model_type:
        return "", f"Для архитектуры «{model_type}» нет совместимого движка."
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
        from app.voice.install import ASR_EXE
        return ASR_EXE.is_file()
    if engine == "audiocpp":
        return audiocpp_server() is not None
    if engine == "transcribe":
        return transcribe_library().is_file() and transcribe_bindings().is_file()
    if ENGINES[engine]["pip"] is None:
        return shared_ready()
    if ENGINES[engine].get("standalone"):
        return python_for(engine).is_file() and _marker(engine).is_file()
    return shared_ready() and _marker(engine).is_file()


def run(command, cancel_event, on_line, env=None, cwd=None):
    process = subprocess.Popen(command, cwd=str(cwd or VOICE_DIR), env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
                               text=True, encoding="utf-8", errors="replace")
    processes.own(process)
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


def link_shared(engine):
    site_dir = venv_dir(engine) / "Lib" / "site-packages"
    (site_dir / "piven_shared.pth").write_text(os.path.relpath(SHARED_SITE, site_dir) + "\n", encoding="utf-8")


def _pip(python):
    return [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--progress-bar", "off"]


def ensure_shared(progress, cancel_event):
    if shared_ready():
        return 0
    if not SHARED_PYTHON.is_file():
        progress(1, "Создание Python-окружения")
        python = BUNDLED_PYTHON if BUNDLED_PYTHON.is_file() else Path(sys.executable)
        run([str(python), "-m", "venv", str(SHARED_VENV)], cancel_event, lambda line: None)
    if not (SHARED_SITE / "torch").is_dir():
        progress(3, "Скачивание PyTorch с CUDA — это самая долгая часть")
        run(_pip(SHARED_PYTHON) + TORCH_PACKAGES + ["--index-url", TORCH_INDEX], cancel_event,
            lambda line: progress(3, "PyTorch · " + _short(line)))
    progress(35, "Установка общих пакетов голоса")
    run(_pip(SHARED_PYTHON) + SHARED_PACKAGES, cancel_event, lambda line: progress(35, "Пакеты · " + _short(line)))
    return 40


def ensure_engine(engine, progress, cancel_event):
    info = ENGINES[engine]
    standalone = info.get("standalone")
    start = 0 if standalone else ensure_shared(progress, cancel_event)
    if info["pip"] is None or ready(engine):
        return start
    folder = venv_dir(engine)
    python = python_for(engine)
    if not python.is_file():
        progress(start + 1, f"Создание окружения {info['label']}")
        base = BUNDLED_PYTHON if BUNDLED_PYTHON.is_file() else Path(sys.executable)
        run([str(base), "-m", "venv", str(folder)], cancel_event, lambda line: None)
    if not standalone:
        link_shared(engine)
    progress(start + 3, f"Установка {info['label']}")
    if info.get("no_deps"):
        run(_pip(python) + ["--no-deps"] + info["no_deps"], cancel_event, lambda line: progress(start + 3, f"{info['label']} · " + _short(line)))
    packages = _pip(python) + info["pip"]
    if not standalone:
        packages += ["--extra-index-url", TORCH_INDEX]
    run(packages, cancel_event,
        lambda line: progress(start + 3, f"{info['label']} · " + _short(line)))
    _marker(engine).write_text("ok\n", encoding="utf-8")
    return start + 10
