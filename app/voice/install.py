from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from app import paths, processes
from app.models import download
from app.models.huggingface import REPO_PATTERN
from pathlib import Path

from app.voice import engines as voice_engines

APP_DIR = Path(__file__).resolve().parents[2]
VOICE_DIR = APP_DIR / "voice-engines"
ASR_DIR = VOICE_DIR / "nemo-speech"
ASR_EXE = ASR_DIR / "bin" / "nemo-speech.exe"
ASR_MODELS_DIR = VOICE_DIR / "models"
VOSK_DIR = ASR_MODELS_DIR / "vosk"
TTS_DIR = VOICE_DIR / "qwen-tts"
TTS_PYTHON = VOICE_DIR / ".venv" / "Scripts" / "python.exe"
TTS_HF_HOME = TTS_DIR / "models" / "hf"
BUNDLED_PYTHON = APP_DIR / "runtime" / "Python311" / "python.exe"

NEMO_VERSION = "0.2.0"
NEMO_ZIP = f"nemo-speech-{NEMO_VERSION}-windows-x86_64-cuda.zip"
NEMO_URL = f"https://github.com/NVIDIA/NeMo-Speech.cpp/releases/download/v{NEMO_VERSION}/{NEMO_ZIP}"
NEMO_SIZE = 102_183_465
NEMO_SHA256 = "9ffe5e842c39a7d3211f3b2c3b3aa1bca8c0b2455d96d961ed5f22ec5108f98d"

TTS_PACKAGES_SIZE = "около 3,5 ГБ"

ASR_MODELS = {
    "parakeet-tdt": {
        "title": "Parakeet TDT 0.6B v3", "repo": "nvidia/parakeet-tdt-0.6b-v3",
        "revision": "541d1f99c6b0c3cd0b11a95167540bb8edefd82b", "file": "parakeet-tdt-0.6b-v3.q8_0.gguf",
        "bytes": 713_975_456, "sha256": "e3880d0aaaaf2c308ea2c35016b2b895c423eb3fda924c1b463d1c19b7f4d32e",
        "language": "ru", "note": "25 европейских языков, включая русский. Быстрая, сама ставит знаки препинания.",
        "license": "CC-BY-4.0"},
    "nemotron-3.5": {
        "title": "Nemotron 3.5 ASR 0.6B", "repo": "nvidia/nemotron-3.5-asr-streaming-0.6b",
        "revision": "1c8deaecc64b91f034d73e08dd8b64625eb3395d", "file": "nemotron-3.5-asr-streaming-0.6b.q8_0.gguf",
        "bytes": 741_548_352, "sha256": "a5c435f294eea8f88ce68dd27b8c3bfea7f777cb2fbba04fcd30eaa555f429ae",
        "language": "ru-RU", "note": "Новее, больше 40 языков, включая русский.",
        "license": "NVIDIA Open Model License"},
    "parakeet-ctc": {
        "title": "Parakeet CTC 1.1B", "repo": "nvidia/parakeet-ctc-1.1b",
        "revision": "20e63a0fed6aedba145b74b826dbd41df0941730", "file": "parakeet-ctc-1.1b.q8_0.gguf",
        "bytes": 1_178_100_960, "sha256": "6584fc0fdacf1c220401ea4c3a1d5b44454b655c141cb8672178072c203d92b8",
        "language": "en", "note": "Только английский. Крупнее и точнее на английской речи.",
        "license": "CC-BY-4.0"},
    "nemotron-en": {
        "title": "Nemotron Speech EN 0.6B", "repo": "nvidia/nemotron-speech-streaming-en-0.6b",
        "revision": "ebe59e5a817142986528bbbee5dba8db7b38ed50", "file": "nemotron-speech-streaming-en-0.6b.q8_0.gguf",
        "bytes": 699_872_960, "sha256": "d9a01898d2a611c8764e23a1c2f45e70bbd5a425dc4de93692ac951dd603812d",
        "language": "en-US", "note": "Только английский.",
        "license": "NVIDIA Open Model License"},
}
DEFAULT_ASR = "parakeet-tdt"
VOSK_DOWNLOADS = "https://alphacephei.com/vosk/models/"
VOSK_MODELS = {
    "vosk:vosk-model-small-ru-0.22": {
        "title": "Vosk Small Russian", "language": "ru", "bytes": 46_236_750,
        "note": "Лёгкое распознавание русской речи на процессоре.", "keywords": "russian русский русская речь"},
    "vosk:vosk-model-small-en-us-0.15": {
        "title": "Vosk Small English (US)", "language": "en", "bytes": 41_205_931,
        "note": "Лёгкое распознавание английской речи на процессоре.", "keywords": "english английский английская речь"},
}

TTS_MODELS = {
    "voicedesign-1.7b": {
        "title": "Qwen3-TTS 1.7B VoiceDesign", "repo": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign", "mode": "design",
        "bytes": 4_520_163_832, "note": "Голос по описанию: тёплый мужской русский голос.", "license": "Apache 2.0"},
    "customvoice-1.7b": {
        "title": "Qwen3-TTS 1.7B CustomVoice", "repo": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice", "mode": "custom",
        "bytes": 4_520_218_951, "note": "Семь готовых голосов на выбор, говорят по-русски.", "license": "Apache 2.0"},
    "customvoice-0.6b": {
        "title": "Qwen3-TTS 0.6B CustomVoice", "repo": "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice", "mode": "custom",
        "bytes": 2_498_388_392, "note": "Легче и быстрее, те же семь голосов.", "license": "Apache 2.0"},
}
DEFAULT_TTS = "voicedesign-1.7b"
QWEN_TTS_MODES = {"custom_voice": "custom", "voice_design": "design", "base": "base"}

ASR_RUNTIME_EXTRA = 400 * 2**20
TTS_RUNTIME_EXTRA = 1200 * 2**20

USER_AGENT = "PIVEN-Companion/1.0"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


CUSTOM_PREFIX = "hf:"
CUSTOM_ASR_DIR = ASR_MODELS_DIR / "hf"
TTS_SEARCH_SKIP_TAGS = {"mlx", "openvino", "gguf", "onnx", "coreml", "litert"}


def _asr_language(name):
    return "ru-RU" if "nemotron" in name.lower() else "ru"


def custom_asr_models():
    found = {}
    for path in sorted(CUSTOM_ASR_DIR.glob("*/*.gguf")):
        repo = path.parent.name.replace("--", "/", 1)
        found[f"{CUSTOM_PREFIX}{repo}/{path.name}"] = {
            "title": path.stem, "repo": repo, "path": path, "bytes": path.stat().st_size,
            "language": _asr_language(path.name), "note": f"С Hugging Face: {repo}.", "license": "см. страницу модели"}
    return found


def _tts_config(repo):
    snapshots = _tts_cache(repo) / "snapshots"
    for snapshot in sorted(snapshots.iterdir()) if snapshots.is_dir() else []:
        if (snapshot / "model.safetensors").is_file() and (snapshot / "config.json").is_file():
            try:
                return json.loads((snapshot / "config.json").read_text(encoding="utf-8"))
            except Exception:
                return None
    return None


def _speakers(config):
    talker = (config or {}).get("talker_config", {})
    dialects = talker.get("spk_is_dialect", {}) or {}
    return [name for name in (talker.get("spk_id", {}) or {}) if not dialects.get(name)]


def custom_tts_models():
    found = {}
    builtin = {info["repo"] for info in TTS_MODELS.values()}
    for cache in sorted((TTS_HF_HOME / "hub").glob("models--*")):
        repo = cache.name[len("models--"):].replace("--", "/", 1)
        if repo in builtin:
            continue
        config = _tts_config(repo)
        kind = (config or {}).get("tts_model_type")
        if not config or config.get("model_type") != "qwen3_tts" or kind not in QWEN_TTS_MODES:
            continue
        found[f"{CUSTOM_PREFIX}{repo}"] = {
            "title": repo.split("/")[-1], "repo": repo, "mode": QWEN_TTS_MODES[kind],
            "bytes": _folder_size(cache), "note": f"С Hugging Face: {repo}.", "license": "см. страницу модели"}
    return found


ENGINE_LABELS = {key: info["label"] for key, info in voice_engines.ENGINES.items()}
CPU_ENGINES = {"piper", "vosk"}
REGISTRY_PATH = paths.DATA_DIR / "voice_models.json"
PIPER_DIR = VOICE_DIR / "piper"
SNAPSHOT_DIR = VOICE_DIR / "hf-models"
RUNTIME_EXTRA = {("asr", "nemo"): 400 * 2**20, ("tts", "qwen"): 1200 * 2**20, ("tts", "piper"): 0}
DEFAULT_EXTRA = 800 * 2**20


LICENSE_NAMES = {"apache-2.0": "Apache 2.0", "mit": "MIT", "cc-by-4.0": "CC-BY-4.0", "cc-by-sa-4.0": "CC-BY-SA-4.0", "cc0-1.0": "CC0",
                 "bsd-3-clause": "BSD-3", "gpl-3.0": "GPL-3.0", "agpl-3.0": "AGPL-3.0", "openrail": "OpenRAIL", "creativeml-openrail-m": "OpenRAIL-M",
                 "coqui-public-model-license": "Coqui CPML", "cpml": "Coqui CPML", "other": "своя лицензия", "unknown": "не указана"}
NON_COMMERCIAL = ("coqui-public-model-license", "cpml")
_licenses = {}


def license_code(item):
    for tag in item.get("tags") or []:
        if str(tag).startswith("license:") and str(tag) != "license:other":
            return str(tag)[8:].lower()
    card = item.get("cardData") or {}
    value = card.get("license") if isinstance(card, dict) else ""
    code = str(value[0] if isinstance(value, list) and value else value or "").lower()
    if code in ("", "other") and isinstance(card, dict) and card.get("license_name"):
        return str(card["license_name"]).lower()
    return code


def non_commercial(code):
    return "-nc" in code or code in NON_COMMERCIAL


def license_text(code):
    if not code:
        return "не указана, см. страницу модели"
    name = LICENSE_NAMES.get(code, code.upper() if code.startswith("cc-") else code)
    return f"{name} · только некоммерческое использование" if non_commercial(code) else name


def repo_license(repo, token=""):
    if repo not in _licenses:
        try:
            _licenses[repo] = license_text(license_code(_hf_json(f"/api/models/{urllib.parse.quote(repo, safe='/')}", token)))
        except Exception:
            return ""
    return _licenses[repo]


def _registry():
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        return {"asr": dict(data.get("asr", {})), "tts": dict(data.get("tts", {}))}
    except Exception:
        return {"asr": {}, "tts": {}}


def _register(kind, model_id, info):
    if info.get("license", "см. страницу модели") == "см. страницу модели" and info.get("repo"):
        info = {**info, "license": repo_license(info["repo"]) or "см. страницу модели"}
    data = _registry()
    data[kind][model_id] = {key: str(value) if isinstance(value, Path) else value for key, value in info.items()}
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _current_path(saved):
    path = Path(saved)
    if path.exists():
        return path
    try:
        return VOICE_DIR / path.relative_to(APP_DIR / "voice")
    except ValueError:
        return path


def _registered(kind):
    found = {}
    for model_id, info in _registry()[kind].items():
        info = dict(info)
        if info.get("engine") in ("piper", "audiocpp", "transcribe"):
            info["path"] = _current_path(info["path"])
            folder_package = info["engine"] == "audiocpp" and info["path"].is_dir() and any(info["path"].rglob("*.gguf"))
            if not info["path"].is_file() and not folder_package:
                continue
        elif info.get("path"):
            info["path"] = _current_path(info["path"])
            if not (info["path"] / ".piven-complete").is_file():
                continue
        elif not _snapshot_ready(info.get("repo", "")):
            continue
        found[model_id] = info
    return found


def asr_catalogue():
    return {**{key: {"engine": "nemo", **info} for key, info in ASR_MODELS.items()},
            **{key: {"engine": "nemo", **info} for key, info in custom_asr_models().items()}, **_registered("asr")}


def tts_catalogue():
    return {**{key: {"engine": "qwen", **info} for key, info in TTS_MODELS.items()},
            **{key: {"engine": "qwen", **info} for key, info in custom_tts_models().items()}, **_registered("tts")}


def known(kind, model_id):
    return model_id in (asr_catalogue() if kind == "asr" else tts_catalogue())


def supports_gguf(kind, info):
    if kind == "asr" and info.get("engine") == "nemo":
        return str(info.get("path") or info.get("file", "")).lower().endswith(".gguf")
    if kind == "asr" and info.get("engine") == "transcribe":
        return str(info.get("path", "")).lower().endswith(".gguf")
    if info.get("engine") != "audiocpp" or not info.get("path"):
        return False
    path = Path(info["path"])
    return path.suffix.lower() == ".gguf" if path.is_file() else path.is_dir() and any(path.rglob("*.gguf"))


def chosen_model(kind, saved=""):
    catalogue, installed = (asr_catalogue(), _asr_installed) if kind == "asr" else (tts_catalogue(), _tts_installed)
    catalogue = {key: info for key, info in catalogue.items() if supports_gguf(kind, info)}
    if saved in catalogue and installed(saved):
        return saved
    return next((key for key in catalogue if installed(key)), "")


def asr_model(model_id):
    return asr_catalogue().get(model_id) or {"engine": "nemo", **ASR_MODELS[DEFAULT_ASR]}


def tts_model(model_id):
    return tts_catalogue().get(model_id) or {"engine": "qwen", **TTS_MODELS[DEFAULT_TTS]}


def asr_model_path(model_id):
    info = asr_model(model_id)
    return info.get("path") or ASR_MODELS_DIR / info["file"]


def clone_only(info):
    if info.get("engine") != "audiocpp":
        return False
    family = info.get("family")
    return family == "cosyvoice3" or (family == "qwen3_tts" and "base" in str(info.get("title", "")).lower())


def tts_voices(model_id):
    if not model_id:
        return []
    info = tts_model(model_id)
    if not supports_gguf("tts", info):
        return []
    if clone_only(info):
        return [("sample", "Мой образец голоса")]
    voices = [(name, name) for name in info.get("voices") or []]
    sample = [("sample", "Мой образец голоса")] if info.get("clone") else []
    return (voices or [("default", "Голос модели")]) + sample


def _asr_installed(model_id):
    info = asr_model(model_id)
    if info["engine"] != "nemo":
        return model_id in _registered("asr")
    path = asr_model_path(model_id)
    return path.is_file() and path.stat().st_size == info["bytes"]


def _snapshot_ready(repo):
    snapshots = _tts_cache(repo) / "snapshots"
    return bool(repo) and snapshots.is_dir() and any((snapshot / "config.json").is_file() for snapshot in snapshots.iterdir())


def _tts_cache(repo):
    return TTS_HF_HOME / "hub" / ("models--" + repo.replace("/", "--"))


def _tts_installed(model_id):
    info = tts_model(model_id)
    if info["engine"] != "qwen":
        return model_id in _registered("tts")
    return _qwen_weights_ready(info["repo"])


def _qwen_weights_ready(repo):
    snapshots = _tts_cache(repo) / "snapshots"
    return snapshots.is_dir() and any((snapshot / "model.safetensors").is_file() for snapshot in snapshots.iterdir())


def tts_packages_ready():
    return voice_engines.shared_ready()


def ready(kind, model_id):
    if not known(kind, model_id):
        return False
    info = asr_model(model_id) if kind == "asr" else tts_model(model_id)
    if not supports_gguf(kind, info):
        return False
    installed = _asr_installed(model_id) if kind == "asr" else _tts_installed(model_id)
    return installed and voice_engines.ready(info["engine"])


def _remove(target):
    target = Path(target)
    if not paths.inside(target, [VOICE_DIR, TTS_DIR / "models"]):
        raise RuntimeError(f"Путь вне папок озвучки и не будет удалён: {target}")
    if target.is_dir():
        size = _folder_size(target)
        shutil.rmtree(target)
        return size
    if target.is_file():
        size = target.stat().st_size
        target.unlink()
        return size
    return 0


def delete(kind, model_id):
    if not known(kind, model_id):
        raise RuntimeError("Такой модели нет в списке.")
    info = asr_model(model_id) if kind == "asr" else tts_model(model_id)
    engine = info["engine"]
    if engine == "nemo":
        targets = [asr_model_path(model_id)]
    elif engine == "qwen":
        targets = [_tts_cache(info["repo"])]
    elif engine == "piper":
        path = Path(info["path"])
        targets = [path, path.with_name(path.name + ".json")]
    elif engine == "audiocpp":
        from app.voice import catalog
        path = Path(info["path"])
        folder = path if path.is_dir() else path.parent
        inside = paths.inside(folder, [catalog.MODELS_DIR, ASR_MODELS_DIR / "audiocpp"])
        targets = [folder if inside else path]
    elif info.get("path"):
        targets = [Path(info["path"])]
    else:
        targets = [_tts_cache(info["repo"])]
    freed = sum(_remove(target) for target in targets)
    if engine == "nemo" and model_id.startswith(CUSTOM_PREFIX):
        folder = targets[0].parent
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    data = _registry()
    if data[kind].pop(model_id, None) is not None:
        REGISTRY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return freed


def disk_usage():
    models = 0
    legacy = []
    for kind, catalogue, installed in (("asr", asr_catalogue(), _asr_installed), ("tts", tts_catalogue(), _tts_installed)):
        for key, info in catalogue.items():
            if installed(key):
                size = info.get("bytes") or 0
                models += size
                if not supports_gguf(kind, info):
                    legacy.append({"id": key, "kind": kind, "title": info["title"], "bytes": size})
    engines = []
    if voice_engines.SHARED_VENV.is_dir():
        engines.append({"id": "shared", "label": "Общие пакеты (PyTorch и др.)", "bytes": _folder_size(voice_engines.SHARED_VENV)})
    archive = VOICE_DIR / NEMO_ZIP
    nemo_size = (_folder_size(ASR_DIR) if ASR_DIR.is_dir() else 0) + (archive.stat().st_size if archive.is_file() else 0)
    engines.append({"id": "nemo", "label": "NeMo-Speech", "bytes": nemo_size})
    for folder in sorted(voice_engines.ENGINES_DIR.iterdir()) if voice_engines.ENGINES_DIR.is_dir() else []:
        if folder.is_dir():
            size = _folder_size(folder) - (_folder_size(folder / "models") if folder.name == "audiocpp" else 0)
            label = voice_engines.ENGINES.get(folder.name, {}).get("label", folder.name)
            engines.append({"id": folder.name, "label": label, "bytes": size})
    used = _engines_in_use()
    return {"models": models, "legacy": legacy, "engines": [{**item, "removable": _engine_unused(item["id"], used)} for item in engines if item["bytes"]]}


def _engines_in_use():
    return ({info["engine"] for key, info in asr_catalogue().items() if _asr_installed(key)}
            | {info["engine"] for key, info in tts_catalogue().items() if _tts_installed(key)})


def _engine_unused(engine, used):
    if engine == "shared":
        return not used - {"nemo", "audiocpp", "vosk", "transcribe"}
    return engine not in used


def delete_engine(engine):
    known_engine = engine == "shared" or engine in voice_engines.ENGINES
    if not known_engine:
        raise RuntimeError("Неизвестный движок.")
    if not _engine_unused(engine, _engines_in_use()):
        raise RuntimeError("Этот движок нужен скачанной модели.")
    if engine == "shared":
        targets = [voice_engines.SHARED_VENV]
    elif engine == "nemo":
        targets = [ASR_DIR, VOICE_DIR / NEMO_ZIP, VOICE_DIR / "nemo-speech-extract"]
    else:
        folder = voice_engines.ENGINES_DIR / engine
        targets = [item for item in folder.iterdir() if item.name != "models"] if engine == "audiocpp" and folder.is_dir() else [folder]
    return sum(_remove(target) for target in targets)


def _gigabytes(size):
    return f"{size / 1e9:.1f}".replace(".", ",") + " ГБ"


def status():
    def row(kind, key, info, installed):
        return {"id": key, "title": info["title"], "note": info["note"], "license": info["license"],
                "source": info.get("source") or f"huggingface.co/{info['repo']}", "size": _gigabytes(info["bytes"]), "engine": ENGINE_LABELS[info["engine"]],
                "memory": 0 if info["engine"] in CPU_ENGINES else info["bytes"] + RUNTIME_EXTRA.get((kind, info["engine"]), DEFAULT_EXTRA),
                "installed": installed, "custom": key not in ASR_MODELS and key not in TTS_MODELS, "bytes": info["bytes"]}
    asr = [row("asr", key, info, True) for key, info in asr_catalogue().items() if supports_gguf("asr", info) and _asr_installed(key)]
    tts = [row("tts", key, info, True) for key, info in tts_catalogue().items() if supports_gguf("tts", info) and _tts_installed(key)]
    return {
        "asr": {"models": asr, "engine": bool(asr) or ASR_EXE.is_file(),
                "engineNote": "Движок распознавания скачается вместе с выбранной моделью."},
        "tts": {"models": tts, "engine": voice_engines.ready("audiocpp"),
                "engineNote": "Движок audio.cpp установится вместе с первой моделью GGUF."},
    }


def _hf_json(path, token="", timeout=30, next_page=None):
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request("https://huggingface.co" + path, headers=headers), timeout=timeout) as response:
        if next_page is not None:
            match = re.search(r'<([^>]+)>;\s*rel="next"', response.headers.get("Link", ""))
            if match:
                cursor, *_ = urllib.parse.parse_qs(urllib.parse.urlsplit(match[1]).query).get("cursor", [""])
                if cursor:
                    next_page.append(cursor)
        return json.loads(response.read().decode("utf-8"))


def _repo_files(repo, token="", timeout=30):
    path = f"/api/models/{urllib.parse.quote(repo, safe='/')}/tree/main?recursive=1"
    files, seen = [], set()
    cursor = ""
    while cursor not in seen:
        seen.add(cursor)
        page = []
        query = path + ("&" + urllib.parse.urlencode({"cursor": cursor}) if cursor else "")
        files.extend(item for item in _hf_json(query, token, timeout=timeout, next_page=page) if item.get("type") == "file")
        if not page:
            break
        cursor = page[0]
    return files


def classify(kind, item):
    task = item.get("pipeline_tag")
    if kind == "asr" and task in ("text-to-speech", "text-to-audio"):
        return None, "Эта модель генерирует аудио. Проверь её во вкладке озвучки."
    if kind == "tts" and task == "automatic-speech-recognition":
        return None, "Эта модель распознаёт речь. Проверь её во вкладке распознавания."
    tags = item.get("tags") or []
    names = [record.get("rfilename") or "" for record in item.get("siblings") or []]
    if any(_is_gguf(name) for name in names) or (not names and "gguf" in tags):
        return "auto", ""
    return None, "Для голоса нужен совместимый GGUF-файл."


def _hf_repo(query):
    repo = query.rstrip("/")
    if REPO_PATTERN.fullmatch(repo):
        return repo
    if "://" not in query:
        query = "https://" + query
    try:
        url = urllib.parse.urlsplit(query)
    except ValueError:
        return None
    if url.scheme not in ("http", "https") or url.netloc.lower() not in ("huggingface.co", "www.huggingface.co", "hf.co"):
        return None
    parts = urllib.parse.unquote(url.path).strip("/").split("/")
    if len(parts) == 2 or (len(parts) >= 4 and parts[2] in ("tree", "blob", "resolve") and parts[3] == "main"):
        repo = "/".join(parts[:2])
        if REPO_PATTERN.fullmatch(repo) and parts[0] not in ("spaces", "datasets", "collections"):
            return repo
    raise ValueError("Вставь ссылку на страницу модели Hugging Face или укажи автор/модель.")


def _hf_hit(item, engine):
    code = license_code(item)
    if code:
        _licenses[item["id"]] = license_text(code)
    return {"id": item["id"], "downloads": item.get("downloads") or 0, "likes": item.get("likes") or 0,
            "gated": bool(item.get("gated")), "engine": engine, "engineLabel": "GGUF" if engine == "auto" else ENGINE_LABELS.get(engine, ""),
            "license": license_text(code) if code else "", "nonCommercial": non_commercial(code)}


def _builtin_asr(repo):
    return next(((key, info) for key, info in ASR_MODELS.items() if info["repo"].casefold() == repo.casefold()), (None, None))


def _builtin_asr_hit(info):
    return {**_hf_hit({"id": info["repo"]}, "nemo"),
            "title": info["title"], "license": info["license"]}


def _find_hf_repo(kind, repo, token):
    encoded = urllib.parse.quote(repo, safe="/")
    try:
        item = _hf_json(f"/api/models/{encoded}", token)
    except urllib.error.HTTPError as error:
        if error.code not in (401, 403, 404):
            raise
        raise ValueError("Модель не найдена или для неё нужен токен Hugging Face.") from error
    item = {**item, "id": item.get("id") or item.get("modelId") or repo}
    engine, reason = classify(kind, item)
    return {**_hf_hit(item, engine), "direct": True, "problem": reason}


def search(kind, query, token="", recent=False, warnings=None, cursor="", next_page=None):
    from app.voice import catalog
    wanted = str(query or "").strip()
    repo = _hf_repo(wanted)
    if repo:
        if kind == "asr":
            _, source = _builtin_asr(repo)
            if source:
                return [{**_builtin_asr_hit(source), "direct": True, "problem": ""}]
        try:
            packaged = catalog.search(kind, "", cached_only=kind == "asr", repo=repo)
        except OSError:
            packaged = []
        if packaged:
            if any(repo.casefold() == source.casefold() for hit in packaged for source in hit["repositories"]):
                return [{**hit, "direct": len(packaged) == 1} for hit in packaged]
            return [_find_hf_repo(kind, repo, token), *packaged]
        return [_find_hf_repo(kind, repo, token)]

    hits = []
    hf_failed = False
    if kind in ("asr", "tts"):
        task = "automatic-speech-recognition" if kind == "asr" else "text-to-speech"
        params = {
            "filter": ("gguf", task), "limit": 16,
            "sort": "createdAt" if recent else "downloads", "direction": -1,
        }
        if wanted:
            params["search"] = wanted
        if cursor:
            params["cursor"] = cursor
        page = []

        def listing():
            return _hf_json("/api/models?" + urllib.parse.urlencode(params, doseq=True), token, timeout=12, next_page=page)

        try:
            try:
                items = listing()
            except (TimeoutError, urllib.error.URLError) as error:
                if cursor or isinstance(error, urllib.error.HTTPError):
                    raise
                page.clear()
                params.update({"filter": "gguf", "pipeline_tag": task, "limit": 8,
                               "expand": ("tags", "pipeline_tag", "downloads", "likes", "gated")})
                items = listing()
            for item in items:
                engine, reason = classify(kind, item)
                if engine:
                    hits.append(_hf_hit(item, engine))
                elif kind == "tts" and "gguf" in (item.get("tags") or []):
                    hits.append({**_hf_hit(item, None), "problem": reason})
            if next_page is not None:
                next_page.extend(page)
        except (OSError, ValueError):
            hf_failed = True
            if warnings is not None:
                warnings.append("Каталог Hugging Face не загрузился. Показаны доступные результаты.")

    if kind == "asr" and not cursor and (wanted or not recent or hf_failed):
        online = {row["id"].casefold(): row for row in hits}
        official = []
        terms = wanted.casefold().split()
        for key, source in ASR_MODELS.items():
            repo = source["repo"].casefold()
            if repo in online or all(term in f"{key} {repo} {source['title'].casefold()}" for term in terms):
                hit = _builtin_asr_hit(source)
                row = online.pop(repo, hit)
                official.append({**hit, "downloads": row["downloads"], "likes": row["likes"]})
        hits = official + list(online.values())

    packaged = []
    try:
        if not cursor and (not recent or hf_failed):
            packaged = catalog.search(kind, wanted, cached_only=hf_failed)
        if hits:
            by_repo = {}
            for package in catalog.search(kind, "", cached_only=True):
                sources = [repo.casefold() for repo in package["repositories"]]
                if kind == "asr":
                    sources.extend(package.get("packageNames", []))
                for source in sources:
                    by_repo.setdefault(source, []).append(package)
            routed = []
            for hit in hits:
                repo = hit["id"].casefold()
                match = by_repo.get(repo) or by_repo.get(repo.rsplit("/", 1)[-1])
                official = kind == "asr" and _builtin_asr(repo)[1] is not None
                if match and not official:
                    routed.extend(match)
                routed.append(hit)
            hits = routed
    except (OSError, ValueError, KeyError):
        if warnings is not None and not warnings:
            warnings.append("Каталог GGUF-пакетов audio.cpp не загрузился.")
    ordered = packaged + hits
    return list({row["id"]: row for row in ordered}.values())


WEIGHT_SUFFIXES = (".safetensors", ".bin", ".pt", ".pth", ".ckpt")
CHATTERBOX_FILES = ("t3_mtl23ls_v2.safetensors", "ve.pt", "s3gen.pt", "conds.pt")


def _snapshot_files(engine, files):
    if engine == "faster-whisper":
        return list(files)
    keep = _weights(files)
    if engine != "transformers":
        has_safetensors = any(item["path"].endswith(".safetensors") for item in files)
        keep = [item for item in files if item in keep or (item["path"].endswith((".pt", ".pth"))
                and not item["path"].startswith(("onnx/", "openvino/", "coreml/")))]
        keep = [item for item in keep if not (has_safetensors and item["path"].endswith(".bin"))]
    if engine == "chatterbox" and any(item["path"] == CHATTERBOX_FILES[0] for item in files):
        return [item for item in files if item["path"] in CHATTERBOX_FILES or ("/" not in item["path"] and item["path"].endswith(".json"))]
    if engine == "f5-tts":
        folders = sorted({str(Path(item["path"]).parent) for item in keep if item["path"].endswith((".safetensors", ".pt"))},
                         key=lambda name: ("v1" not in name.lower(), "no_zero" in name.lower() or "bigvgan" in name.lower(), name))
        if folders:
            chosen = folders[0]
            keep = [item for item in keep if str(Path(item["path"]).parent) in (chosen, ".")
                    and not (item["path"].endswith(".pt") and any(other["path"] == item["path"][:-3] + ".safetensors" for other in keep))]
    return keep


def _weights(files):
    names = [item["path"] for item in files]
    skip = (".onnx", ".onnx_data", ".msgpack", ".h5", ".ot", ".gguf", ".tflite", ".mlmodel", ".pte")
    has_safetensors = any(name.endswith(".safetensors") for name in names)
    keep = [item for item in files
            if not item["path"].lower().endswith(skip) and not item["path"].startswith(("onnx/", "openvino/", "coreml/"))
            and not (has_safetensors and item["path"].endswith((".bin", ".pt", ".pth")))]
    return keep


def engine_note(engine):
    if engine not in voice_engines.ENGINES or voice_engines.ready(engine):
        return ""
    label = voice_engines.ENGINES[engine]["label"]
    if engine == "nemo":
        return f"Движок {label} ещё не скачан: он поставится вместе с моделью ({_gigabytes(NEMO_SIZE)}, GitHub)."
    if engine == "audiocpp":
        size = sum(asset[1] for asset in voice_engines.AUDIOCPP_ASSETS)
        return f"Движок {label} ещё не скачан: он поставится вместе с моделью ({_gigabytes(size)}, GitHub)."
    if engine == "transcribe":
        return "Движок transcribe.cpp и его пакеты установятся вместе с первой моделью."
    if engine == "vosk":
        return "Vosk установится вместе с моделью. Для распознавания достаточно процессора."
    if not voice_engines.shared_ready():
        return f"Движок {label} ещё не скачан: вместе с моделью поставятся PyTorch и пакеты голоса ({TTS_PACKAGES_SIZE}, PyPI и download.pytorch.org)."
    return f"Движок {label} ещё не скачан: его пакеты поставятся вместе с моделью (PyPI)."


def details(kind, repo, engine, token=""):
    found = _details(kind, repo, engine, token)
    found["engineNote"] = engine_note(found.get("engine") or engine) if found.get("supported") else ""
    if found.get("supported") and REPO_PATTERN.fullmatch(repo):
        try:
            item = _hf_json(f"/api/models/{urllib.parse.quote(repo, safe='/')}?expand=cardData&expand=tags", token, timeout=8)
            card = item.get("cardData")
            declared = card.get("language") if isinstance(card, dict) else None
            languages = [declared] if isinstance(declared, str) else declared
            if isinstance(languages, list) and languages and all(isinstance(code, str) for code in languages):
                found.update(languages=languages, languagesComplete=True)
            else:
                found["languages"] = [tag.removeprefix("language:") for tag in item.get("tags") or []
                                      if isinstance(tag, str) and (tag.startswith("language:") or re.fullmatch(r"[a-z]{2}", tag))]
            code = license_code(item)
            if code:
                _licenses[repo] = license_text(code)
        except (OSError, ValueError):
            pass
    if "license" not in found:
        source = repo if engine != "audiocpp" else found.get("licenseRepo", "")
        found["license"] = repo_license(source, token) if source else ""
    return found


def _details(kind, repo, engine, token=""):
    if engine == "audiocpp" and repo.startswith("audiocpp:"):
        from app.voice import catalog
        return catalog.details(repo.split(":", 1)[1], kind)
    if kind in ("asr", "tts") and REPO_PATTERN.fullmatch(repo):
        _, source = _builtin_asr(repo) if kind == "asr" else (None, None)
        try:
            files = _repo_files(repo, token, timeout=8 if source else 30)
        except (OSError, ValueError):
            if not source:
                raise
            files = []
        ggufs = [{"path": item["path"], "size": item.get("size") or 0} for item in files
                 if _is_gguf(item["path"])]
        if source:
            ggufs = [{"path": source["file"], "size": source["bytes"]}] + [
                item for item in ggufs if item["path"] != source["file"]]
            return {"supported": True, "engine": "nemo", "files": ggufs, "bytes": source["bytes"], "license": source["license"]}
        if not ggufs:
            return {"supported": False, "reason": "В репозитории нет GGUF-файлов."}
        ggufs.sort(key=lambda item: (0 if "q8_0" in item["path"].lower() else 1, item["path"]))
        return {"supported": True, "engine": "auto", "files": ggufs, "bytes": ggufs[0]["size"]}
    return {"supported": False, "reason": "Для голоса поддерживаются только совместимые модели GGUF.", "license": ""}


def tts_details(repo, token=""):
    files = _repo_files(repo, token)
    config = _hf_json(f"/{urllib.parse.quote(repo, safe='/')}/raw/main/config.json", token)
    kind = config.get("tts_model_type")
    supported = config.get("model_type") == "qwen3_tts" and kind in QWEN_TTS_MODES \
        and any(item["path"] == "model.safetensors" for item in files)
    reason = "" if supported else "Эта модель не в формате Qwen3-TTS, который умеет запускать программа."
    return {"supported": supported, "reason": reason, "mode": QWEN_TTS_MODES.get(kind, "design"),
            "voices": _speakers(config), "bytes": sum(item.get("size") or 0 for item in files)}


def _download(url, destination, size, sha256, cancel_event, on_bytes, token="", on_wait=None, validate=None):
    partial = destination.with_name(destination.name + ".download")
    headers = {"User-Agent": USER_AGENT, **({"Authorization": f"Bearer {token}"} if token else {})}
    try:
        received = download.fetch(url, partial, headers, cancel_event, on_bytes, on_wait or _wait_note, expected_size=size)
        if size and received != size:
            raise RuntimeError(f"Файл {destination.name} скачался не полностью: {received} из {size} байт.")
        if sha256:
            digest = hashlib.sha256()
            with partial.open("rb") as handle:
                for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != sha256:
                raise RuntimeError(f"Контрольная сумма {destination.name} не совпала, файл повреждён.")
        if validate:
            validate(partial)
        os.replace(partial, destination)
    except (InterruptedError, RuntimeError):
        partial.unlink(missing_ok=True)
        raise


def _wait_note(message):
    show = getattr(_wait_note, "progress", None)
    if show:
        show(message)


def _install_nemo(progress, cancel_event, share):
    archive = VOICE_DIR / NEMO_ZIP
    if not (archive.is_file() and archive.stat().st_size == NEMO_SIZE):
        _download(NEMO_URL, archive, NEMO_SIZE, NEMO_SHA256, cancel_event,
                  lambda received: progress(share * received / NEMO_SIZE, f"Скачивание NeMo-Speech: {received / 2**20:.0f} МБ"))
    progress(share, "Распаковываю NeMo-Speech")
    extract = VOICE_DIR / "nemo-speech-extract"
    shutil.rmtree(extract, ignore_errors=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(extract)
    inner = next((path for path in extract.iterdir() if (path / "bin" / "nemo-speech.exe").is_file()), None)
    if inner is None:
        raise RuntimeError("В архиве NeMo-Speech нет nemo-speech.exe.")
    shutil.rmtree(ASR_DIR, ignore_errors=True)
    shutil.move(str(inner), str(ASR_DIR))
    shutil.rmtree(extract, ignore_errors=True)
    archive.unlink(missing_ok=True)


def install_asr(model_id, progress, cancel_event, file=None, token="", staged=None):
    if file:
        repo = model_id
        path = CUSTOM_ASR_DIR / repo.replace("/", "--") / Path(file["path"]).name
        quoted = "/".join(urllib.parse.quote(part, safe="") for part in file["path"].split("/"))
        info = {"title": path.stem, "bytes": int(file.get("size") or 0), "sha256": "",
                "url": f"https://huggingface.co/{urllib.parse.quote(repo, safe='/')}/resolve/main/{quoted}"}
        model_id = f"{CUSTOM_PREFIX}{repo}/{path.name}"
        installed = path.is_file() and path.stat().st_size == info["bytes"]
        if installed:
            try:
                _validate_nemo_file(path)
            except RuntimeError:
                installed = False
    else:
        info = asr_model(model_id)
        path = asr_model_path(model_id)
        info = {**info, "url": f"https://huggingface.co/{info['repo']}/resolve/{info['revision']}/{info['file']}"}
        installed = _asr_installed(model_id)
    share = 0
    if not ASR_EXE.is_file():
        share = 100 * NEMO_SIZE / (NEMO_SIZE + info["bytes"])
        _install_nemo(progress, cancel_event, share)
    if not installed:
        if staged is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, path)
        else:
            _download(info["url"], path, info["bytes"], info["sha256"], cancel_event,
                      lambda received: progress(share + (100 - share) * received / max(info["bytes"], 1),
                                                f"Скачивание {info['title']}: {received / 2**20:.0f} из {info['bytes'] / 2**20:.0f} МБ"), token,
                      validate=_validate_nemo_file if file else None)
    progress(100, f"{info['title']} готова")
    return model_id


def _run(command, cancel_event, on_line, env=None):
    process = subprocess.Popen(command, cwd=str(VOICE_DIR), env=env, stdin=subprocess.DEVNULL,
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


def _folder_size(folder):
    total, stack = 0, [str(folder)]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
        except OSError:
            continue
    return total


def _ensure_packages(progress, cancel_event, engine="qwen"):
    return voice_engines.ensure_engine(engine, progress, cancel_event)


NETWORK_MARKS = ("ConnectionError", "ConnectTimeout", "ReadTimeout", "Timeout", "MaxRetryError", "Max retries",
                 "NameResolutionError", "getaddrinfo", "RemoteDisconnected", "IncompleteRead", "ProtocolError",
                 "Connection aborted", "Connection reset", "LocalEntryNotFoundError", "HTTP Error 5", "502", "503", "504")


def _snapshot(repo, title, size, start, progress, cancel_event, token="", ignore=None, local_dir=None):
    cache = Path(local_dir) if local_dir else _tts_cache(repo)
    stop = threading.Event()

    def measure():
        while not stop.wait(1.5):
            done = _folder_size(cache)
            progress(start + (99 - start) * min(done / max(size, 1), 1),
                     f"Скачивание {title}: {done / 2**30:.1f} из {size / 2**30:.1f} ГБ")
    threading.Thread(target=measure, daemon=True).start()
    env = os.environ.copy()
    env.update({"HF_HOME": str(TTS_HF_HOME), "PYTHONUTF8": "1", "HF_HUB_DISABLE_PROGRESS_BARS": "1"})
    if token:
        env["HF_TOKEN"] = token
    target = f", local_dir={json.dumps(str(local_dir))}" if local_dir else ""
    call = f"from huggingface_hub import snapshot_download; snapshot_download({json.dumps(repo)}, ignore_patterns={json.dumps(ignore or [])}{target})"
    try:
        pause = 2.0
        while True:
            try:
                _run([str(TTS_PYTHON), "-c", call], cancel_event, lambda line: None, env=env)
                break
            except RuntimeError as error:
                if not any(mark in str(error) for mark in NETWORK_MARKS):
                    raise
                progress(start + (99 - start) * min(_folder_size(cache) / max(size, 1), 1), download.WAIT_MESSAGE)
                if cancel_event.wait(pause):
                    raise InterruptedError("Установка отменена.")
                pause = min(pause * 2, 30.0)
    finally:
        stop.set()


def install_tts(model_id, progress, cancel_event, repo=None, size=0, token=""):
    if repo:
        info = {"title": repo.split("/")[-1], "repo": repo, "bytes": int(size or 0) or 1}
        model_id = f"{CUSTOM_PREFIX}{repo}"
        installed = _qwen_weights_ready(repo) and _tts_config(repo) is not None
    else:
        info = tts_model(model_id)
        installed = _tts_installed(model_id)
    start = _ensure_packages(progress, cancel_event)
    if not installed:
        _snapshot(info["repo"], info["title"], info["bytes"], start, progress, cancel_event, token)
    progress(100, f"{info['title']} готова")
    return model_id


IGNORE_FOR_TRANSFORMERS = ["*.onnx", "*.onnx_data", "*.msgpack", "*.h5", "*.ot", "*.gguf", "*.tflite", "*.mlmodel",
                           "onnx/*", "openvino/*", "coreml/*"]


def install_snapshot(kind, repo, engine, size, progress, cancel_event, token="", voices=None):
    start = _ensure_packages(progress, cancel_event, engine)
    files = _repo_files(repo, token)
    keep = {item["path"] for item in _snapshot_files(engine, files)}
    ignore = [item["path"] for item in files if item["path"] not in keep]
    title = repo.split("/")[-1]
    folder = SNAPSHOT_DIR / repo.replace("/", "--")
    _snapshot(repo, title, int(size or 0), start, progress, cancel_event, token, ignore, folder)
    (folder / ".piven-complete").write_text("ok\n", encoding="utf-8")
    model_id = f"{engine}:{repo}"
    _register(kind, model_id, {"engine": engine, "repo": repo, "path": folder, "title": title, "bytes": _folder_size(folder),
                               "language": "ru", "voices": voices or [],
                               "note": f"{ENGINE_LABELS[engine]}, с Hugging Face: {repo}.", "license": "см. страницу модели"})
    progress(100, f"{title} готова")
    return model_id


def install_vosk(model_id, progress, cancel_event):
    if model_id not in VOSK_MODELS:
        raise ValueError("Неизвестная модель Vosk.")
    info = VOSK_MODELS[model_id]
    slug = model_id.removeprefix("vosk:")
    folder = VOSK_DIR / slug
    start = _ensure_packages(progress, cancel_event, "vosk")
    if not (folder / ".piven-complete").is_file():
        VOSK_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="download-", dir=VOSK_DIR) as staging:
            staging = Path(staging)
            archive = staging / (slug + ".zip")
            _download(VOSK_DOWNLOADS + archive.name, archive, info["bytes"], "", cancel_event,
                      lambda received: progress(start + (94 - start) * min(received / info["bytes"], 1),
                                                f"Скачивание {info['title']}: {received / 2**20:.0f} МБ"))
            progress(95, f"Распаковываю {info['title']}")
            with zipfile.ZipFile(archive) as bundle:
                for item in bundle.infolist():
                    if cancel_event.is_set():
                        raise InterruptedError("Установка отменена.")
                    if item.filename.startswith(slug + "/"):
                        bundle.extract(item, staging)
            extracted = staging / slug
            if not (extracted / "am" / "final.mdl").is_file() or not (extracted / "conf" / "model.conf").is_file():
                raise RuntimeError("В архиве нет файлов модели Vosk.")
            if cancel_event.is_set():
                raise InterruptedError("Установка отменена.")
            (extracted / ".piven-complete").write_text("ok\n", encoding="utf-8")
            os.replace(extracted, folder)
    _register("asr", model_id, {"engine": "vosk", "path": folder, "title": info["title"], "bytes": _folder_size(folder),
                                "language": info["language"], "note": info["note"], "license": "Apache 2.0",
                                "source": "alphacephei.com/vosk/models"})
    progress(100, f"{info['title']} готова")
    return model_id


def install_piper(repo, file, progress, cancel_event, token=""):
    start = _ensure_packages(progress, cancel_event, "piper")
    folder = PIPER_DIR / repo.replace("/", "--")
    voice_path = folder / file["path"]
    paths = {item["path"]: item.get("size") or 0 for item in _repo_files(repo, token)}
    config = file["path"] + ".json" if file["path"] + ".json" in paths else str(Path(file["path"]).parent / "config.json").replace("\\", "/").lstrip("./")
    targets = [(file["path"], voice_path), (config, Path(str(voice_path) + ".json"))]
    total = sum(paths.get(source, 0) for source, _ in targets) or 1
    done = 0
    for source, target in targets:
        quoted = "/".join(urllib.parse.quote(part, safe="") for part in source.split("/"))
        url = f"https://huggingface.co/{urllib.parse.quote(repo, safe='/')}/resolve/main/{quoted}"
        _download(url, target, paths.get(source, 0), "", cancel_event,
                  lambda received: progress(start + (100 - start) * (done + received) / total, f"Скачивание голоса Piper: {(done + received) / 2**20:.0f} МБ"), token)
        done += paths.get(source, 0)
    title = f"{repo.split('/')[-1]} · {Path(file['path']).stem}" if Path(file["path"]).stem != "model" else repo.split("/")[-1]
    model_id = f"piper:{repo}/{file['path']}"
    _register("tts", model_id, {"engine": "piper", "repo": repo, "path": voice_path, "title": title, "bytes": voice_path.stat().st_size,
                                "note": f"Голос Piper с Hugging Face: {repo}. Работает на процессоре.", "license": "см. страницу модели"})
    progress(100, f"{title} готова")
    return model_id


def _safe_relative(path):
    return bool(isinstance(path, str) and not re.search(r'[\\:<>|?*"\x00-\x1f]', path)
                and all(part and part == part.rstrip(". ") for part in path.split("/")))


def _is_gguf(path):
    return _safe_relative(path) and path.lower().endswith(".gguf") and "mmproj" not in path.lower()


def validate_install(kind, model_id, extra):
    engine = extra.get("engine", "")
    file = extra.get("file")
    path = file.get("path", "") if isinstance(file, dict) else ""
    if kind in ("asr", "tts") and engine == "audiocpp" and model_id.startswith("audiocpp:") and isinstance(path, str) and path:
        return
    if kind == "asr" and not file and model_id in ASR_MODELS:
        return
    if (kind in ("asr", "tts") and engine in ("", "auto", "nemo", "transcribe", "audiocpp")
            and _is_gguf(path) and REPO_PATTERN.fullmatch(model_id)
            and all(part == part.rstrip(".") for part in model_id.split("/"))):
        return
    raise ValueError("Для голоса поддерживаются только совместимые модели GGUF.")


def _nemo_compatibility(metadata):
    architecture = metadata.get("general.architecture")
    if architecture == "asr":
        head = metadata.get("asr.head_type", "ctc")
        return "" if head in ("ctc", "rnnt", "tdt") else f"NeMo-Speech не поддерживает тип распознавания {head}."
    if architecture == "parakeet-ctc" or (not architecture and any(key.startswith("parakeet-ctc.") for key in metadata)):
        return ""
    if architecture == "nemo":
        return "Это старый GGUF NeMo. Нужна версия модели, экспортированная в формат ASR для NeMo-Speech.cpp."
    if architecture:
        return f"Выбранный GGUF-файл несовместим с NeMo-Speech. Архитектура файла: {architecture}."
    return None


def _validate_nemo_file(path):
    from app.models import memory_fit
    error = _nemo_compatibility(memory_fit.local_metadata(path, prefix_bytes=16 << 20))
    if error is None:
        raise RuntimeError("Скачанный файл не содержит читаемого заголовка GGUF для NeMo-Speech.")
    if error:
        raise RuntimeError(error)


TRANSCRIBE_ASR_ARCHITECTURES = {
    "whisper", "parakeet", "cohere_asr", "canary", "canary_qwen", "qwen3_asr",
    "moonshine", "moonshine_streaming", "sensevoice", "funasr_nano", "gigaam", "medasr",
    "moss", "granite_speech", "granite_speech_nar", "granite_speech5_ctc", "voxtral", "voxtral_realtime",
}


def _gguf_runtime(kind, metadata):
    from app.voice import catalog

    architecture = metadata.get("general.architecture")
    family = metadata.get("audiocpp.model_spec.family")
    if isinstance(family, str) and re.fullmatch(r"[a-z0-9_]+", family):
        spec = catalog.specs().get(family) or {}
        if set(spec.get("tasks") or []) & catalog.TASKS[kind]:
            embedded = metadata.get("audiocpp.embedded_files.names")
            sidecars = catalog.required_sidecars(spec, embedded if isinstance(embedded, list) else [])
            return {"engine": "audiocpp", "family": family, "sidecars": sidecars}
        return {"reason": f"Семейство audio.cpp «{family}» недоступно для этой задачи."}
    if kind == "asr" and _nemo_compatibility(metadata) == "":
        return {"engine": "nemo"}
    if kind == "asr" and isinstance(architecture, str) and architecture in TRANSCRIBE_ASR_ARCHITECTURES:
        return {"engine": "transcribe"}
    if architecture in ("audiocpp", None):
        return {"retryable": True, "reason": "Не удалось определить движок по заголовку GGUF. Повтори проверку."}
    return {"reason": f"Для архитектуры «{architecture}» нет подходящего движка в PIVEN для этой задачи."}


def _resolve_voice_file(kind, repo, path, token):
    from app.models import memory_fit
    from app.voice import catalog

    builtin_id, source = _builtin_asr(repo) if kind == "asr" else (None, None)
    if source and source["file"] == path:
        return {"engine": "nemo", "builtin": builtin_id}
    package = catalog.file_package(kind, repo, path)
    if package:
        return {"engine": "audiocpp", "family": package[0], "package": package[1]}
    if re.search(r"-\d{5}-of-\d{5}\.gguf$", path, re.IGNORECASE):
        return {"reason": "Для этого GGUF нужны все части модели. Выбери цельный файл или готовый пакет."}
    route = _gguf_runtime(kind, memory_fit.remote_metadata(repo, path, token, prefix_bytes=2 << 20))
    return _voice_sidecars(repo, path, route, token)


def _voice_sidecars(repo, path, route, token):
    required = route.get("sidecars")
    if not required:
        return route
    directory = path.rpartition("/")[0]
    prefix = f"{directory}/" if directory else ""
    sizes = {item["path"]: item.get("size") or 0 for item in _repo_files(repo, token, timeout=8)}
    missing = [name for name in required if not _safe_relative(name) or prefix + name not in sizes]
    if missing:
        return {"reason": f"Для audio.cpp не хватает файлов: {', '.join(missing)}."}
    return {**route, "sidecars": [(name, prefix + name, sizes[prefix + name]) for name in required]}


def check_file(kind, repo, path, token=""):
    validate_install(kind, repo, {"engine": "auto", "file": {"path": path}})
    route = _resolve_voice_file(kind, repo, path, token)
    engine = route.get("engine", "")
    return {"supported": bool(engine), "engine": engine, "engineName": ENGINE_LABELS.get(engine, ""),
            "engineNote": engine_note(engine) if engine else "", "reason": route.get("reason", ""),
            "retryable": bool(route.get("retryable"))}


def _voice_file_url(repo, path):
    return f"https://huggingface.co/{urllib.parse.quote(repo, safe='/')}/resolve/main/{urllib.parse.quote(path, safe='/')}"


def install_external_gguf(kind, repo, file, route, progress, cancel_event, token, staged=None):
    from app.models import memory_fit
    from app.voice import catalog

    engine = route["engine"]
    relative_path = file["path"]
    size = int(file.get("size") or 0)
    repo_key = repo.casefold()
    if engine == "transcribe" and repo_key.startswith("handy-computer/"):
        repo_key = repo_key.split("/", 1)[1]
    target = ASR_MODELS_DIR / engine / repo_key / relative_path
    if engine == "audiocpp":
        relative = Path(relative_path)
        target = ASR_MODELS_DIR / engine / kind / repo_key / relative.parent / (relative.stem + ".package") / relative.name
    installed_id = f"{engine}:{repo_key}/{relative_path}"
    ensure = voice_engines.ensure_transcribe if engine == "transcribe" else voice_engines.ensure_audiocpp
    start = ensure(progress, cancel_event)

    def validate(path):
        confirmed = _gguf_runtime(kind, memory_fit.local_metadata(path, prefix_bytes=16 << 20))
        staged_dependencies = {name for name, _, _ in route.get("sidecars", [])}
        if (confirmed.get("engine") != engine or confirmed.get("family") != route.get("family")
                or set(confirmed.get("sidecars", [])) - staged_dependencies):
            raise RuntimeError("Заголовок скачанного GGUF не совпал с результатом проверки совместимости.")

    if not (_registered(kind).get(installed_id) and target.stat().st_size == size):
        if staged is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, target)
        else:
            _download(_voice_file_url(repo, relative_path), target, size, "", cancel_event,
                      lambda received: progress(start + (99 - start) * received / max(size, received, 1),
                                                f"Скачивание {target.stem}: {received / 2**20:.0f} МБ"), token, validate=validate)
    for name, source, expected_size in route.get("sidecars", []):
        dependency = target.parent / name
        if not dependency.is_file() or dependency.stat().st_size != expected_size:
            _download(_voice_file_url(repo, source), dependency, expected_size, "", cancel_event,
                      lambda received: progress(99, f"Скачивание {name}: {received / 2**20:.0f} МБ"), token)
    info = {"engine": engine, "path": target, "repo": repo, "title": target.stem,
            "bytes": target.stat().st_size + sum(size for _, _, size in route.get("sidecars", [])), "language": "auto",
            "note": f"GGUF · {ENGINE_LABELS[engine]}", "license": repo_license(repo, token)}
    if engine == "audiocpp":
        family = route["family"]
        spec = catalog.specs()[family]
        info.update(family=family, task=catalog.task_for(spec, kind), language=catalog.language(spec),
                    voices=catalog.voices(spec), clone=catalog.can_clone(spec))
    _register(kind, installed_id, info)
    progress(100, f"{target.stem} готова")
    return installed_id


def _install_audio_package(kind, family, package, progress, cancel_event, token):
    from app.voice import catalog

    entry = catalog.install(kind, family, package, progress, cancel_event, token)
    installed_id = f"audiocpp:{family}/{entry['package']}"
    _register(kind, installed_id, entry)
    progress(100, f"{entry['title']} готова")
    return installed_id


def _install_after_header_check(kind, repo, file, progress, cancel_event, token):
    from app.models import memory_fit

    ASR_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".voice-gguf-", dir=ASR_MODELS_DIR) as temporary:
        staged = Path(temporary) / "weights.gguf"
        size = int(file.get("size") or 0)
        _download(_voice_file_url(repo, file["path"]), staged, size, "", cancel_event,
                  lambda received: progress(80 * received / max(size, received, 1),
                                            f"Скачивание GGUF для проверки: {received / 2**20:.0f} МБ"), token)
        route = _voice_sidecars(repo, file["path"],
                                _gguf_runtime(kind, memory_fit.local_metadata(staged, prefix_bytes=16 << 20)), token)
        if not route.get("engine"):
            raise ValueError(route.get("reason", "Не удалось проверить совместимость GGUF."))
        if cancel_event.is_set():
            raise InterruptedError("Установка отменена.")
        file = {**file, "size": staged.stat().st_size}

        def finishing(percent, message):
            progress(80 + 0.2 * percent, message)

        if route["engine"] == "nemo":
            return install_asr(repo, finishing, cancel_event, file, token, staged=staged)
        return install_external_gguf(kind, repo, file, route, finishing, cancel_event, token, staged=staged)


def install(kind, model_id, progress, cancel_event, extra=None, token=""):
    extra = extra or {}
    validate_install(kind, model_id, extra)
    reported, report = [0], progress

    def progress(percent, message):
        reported[0] = percent
        report(percent, message)
    _wait_note.progress = lambda message: report(reported[0], message)
    file = extra.get("file")
    if model_id.startswith("audiocpp:"):
        return _install_audio_package(kind, model_id.split(":", 1)[1], file["path"], progress, cancel_event, token)
    if not file:
        return install_asr(model_id, progress, cancel_event, token=token)
    route = _resolve_voice_file(kind, model_id, file["path"], token)
    if route.get("builtin"):
        return install_asr(route["builtin"], progress, cancel_event, token=token)
    if route.get("package"):
        return _install_audio_package(kind, route["family"], route["package"], progress, cancel_event, token)
    if route.get("engine") == "nemo":
        return install_asr(model_id, progress, cancel_event, file, token)
    if route.get("engine"):
        return install_external_gguf(kind, model_id, file, route, progress, cancel_event, token)
    if route.get("retryable"):
        return _install_after_header_check(kind, model_id, file, progress, cancel_event, token)
    raise ValueError(route["reason"])
