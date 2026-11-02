from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import zipfile

from app import processes
from app.models import download
from pathlib import Path

from app.voice import engines as voice_engines

APP_DIR = Path(__file__).resolve().parents[2]
VOICE_DIR = APP_DIR / "voice-engines"
ASR_DIR = VOICE_DIR / "nemo-speech"
ASR_EXE = ASR_DIR / "bin" / "nemo-speech.exe"
ASR_MODELS_DIR = VOICE_DIR / "models"
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

CUSTOM_SPEAKERS = {"ryan": "Ryan · мужской", "aiden": "Aiden · мужской", "uncle_fu": "Uncle Fu · мужской, низкий",
                   "vivian": "Vivian · женский", "serena": "Serena · женский", "ono_anna": "Ono Anna · женский",
                   "sohee": "Sohee · женский"}
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
        if not config or config.get("model_type") != "qwen3_tts" or kind not in ("custom_voice", "voice_design"):
            continue
        found[f"{CUSTOM_PREFIX}{repo}"] = {
            "title": repo.split("/")[-1], "repo": repo, "mode": "custom" if kind == "custom_voice" else "design",
            "bytes": _folder_size(cache), "note": f"С Hugging Face: {repo}.", "license": "см. страницу модели"}
    return found


ENGINE_LABELS = {key: info["label"] for key, info in voice_engines.ENGINES.items()}
CLONING_ENGINES = {"chatterbox", "f5-tts", "coqui", "voxcpm", "omnivoice"}
REGISTRY_PATH = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OllamaCompanion" / "voice_models.json"
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


def _registered(kind):
    found = {}
    for model_id, info in _registry()[kind].items():
        info = dict(info)
        if info.get("engine") in ("piper", "audiocpp"):
            info["path"] = Path(info["path"])
            if not info["path"].is_file():
                continue
        elif info.get("path"):
            info["path"] = Path(info["path"])
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


def asr_model(model_id):
    return asr_catalogue().get(model_id) or {"engine": "nemo", **ASR_MODELS[DEFAULT_ASR]}


def tts_model(model_id):
    return tts_catalogue().get(model_id) or {"engine": "qwen", **TTS_MODELS[DEFAULT_TTS]}


def asr_model_path(model_id):
    info = asr_model(model_id)
    return info.get("path") or ASR_MODELS_DIR / info["file"]


def clone_only(info):
    return info.get("engine") == "audiocpp" and info.get("family") == "qwen3_tts" and "base" in str(info.get("title", "")).lower()


def tts_voices(model_id):
    info = tts_model(model_id)
    if clone_only(info):
        return [("sample", "Мой образец голоса")]
    if info["engine"] != "qwen":
        voices = [(name, name) for name in info.get("voices") or []]
        sample = [("sample", "Мой образец голоса")] if info["engine"] in CLONING_ENGINES or info.get("clone") else []
        return (voices or [("default", "Голос модели")]) + sample
    if info["mode"] != "custom":
        return [("Russian", "Русский мужской")]
    if info["repo"] in {item["repo"] for item in TTS_MODELS.values()}:
        return list(CUSTOM_SPEAKERS.items())
    return [(name, CUSTOM_SPEAKERS.get(name, name.replace("_", " ").title())) for name in _speakers(_tts_config(info["repo"]))]


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
    if tts_model(model_id)["engine"] != "qwen":
        return model_id in _registered("tts")
    snapshots = _tts_cache(tts_model(model_id)["repo"]) / "snapshots"
    return snapshots.is_dir() and any((snapshot / "model.safetensors").is_file() for snapshot in snapshots.iterdir())


def tts_packages_ready():
    return voice_engines.shared_ready()


def ready(kind, model_id):
    if not known(kind, model_id):
        return False
    info = asr_model(model_id) if kind == "asr" else tts_model(model_id)
    installed = _asr_installed(model_id) if kind == "asr" else _tts_installed(model_id)
    return installed and voice_engines.ready(info["engine"])


def _remove(target):
    target = Path(target)
    roots = [VOICE_DIR.resolve(), (TTS_DIR / "models").resolve()]
    if not any(root in target.resolve().parents for root in roots):
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
        inside = catalog.MODELS_DIR.resolve() in folder.resolve().parents
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
    for kind, catalogue, installed in (("asr", asr_catalogue(), _asr_installed), ("tts", tts_catalogue(), _tts_installed)):
        models += sum(info.get("bytes") or 0 for key, info in catalogue.items() if installed(key))
    engines = []
    if voice_engines.SHARED_VENV.is_dir():
        engines.append({"label": "Общие пакеты (PyTorch и др.)", "bytes": _folder_size(voice_engines.SHARED_VENV)})
    if ASR_DIR.is_dir():
        engines.append({"label": "NeMo-Speech", "bytes": _folder_size(ASR_DIR)})
    for folder in sorted(voice_engines.ENGINES_DIR.iterdir()) if voice_engines.ENGINES_DIR.is_dir() else []:
        if folder.is_dir():
            size = _folder_size(folder) - (_folder_size(folder / "models") if folder.name == "audiocpp" else 0)
            label = voice_engines.ENGINES.get(folder.name, {}).get("label", folder.name)
            engines.append({"label": label, "bytes": size})
    return {"models": models, "engines": [item for item in engines if item["bytes"]]}


def _gigabytes(size):
    return f"{size / 1e9:.1f}".replace(".", ",") + " ГБ"


def status():
    def row(kind, key, info, installed):
        return {"id": key, "title": info["title"], "note": info["note"], "license": info["license"],
                "source": f"huggingface.co/{info['repo']}", "size": _gigabytes(info["bytes"]), "engine": ENGINE_LABELS[info["engine"]],
                "memory": 0 if info["engine"] == "piper" else info["bytes"] + RUNTIME_EXTRA.get((kind, info["engine"]), DEFAULT_EXTRA),
                "installed": installed, "custom": key not in ASR_MODELS and key not in TTS_MODELS, "bytes": info["bytes"]}
    asr = [row("asr", key, info, _asr_installed(key)) for key, info in asr_catalogue().items()]
    tts = [row("tts", key, info, _tts_installed(key)) for key, info in tts_catalogue().items()]
    return {
        "asr": {"models": asr, "engine": ASR_EXE.is_file(),
                "engineNote": f"Программа NeMo-Speech ({_gigabytes(NEMO_SIZE)}, GitHub NVIDIA) скачается вместе с первой моделью."},
        "tts": {"models": tts, "engine": tts_packages_ready(),
                "engineNote": f"Python-пакеты PyTorch и qwen-tts ({TTS_PACKAGES_SIZE}, PyPI и download.pytorch.org) поставятся вместе с первой моделью."},
    }


def _hf_json(path, token=""):
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request("https://huggingface.co" + path, headers=headers), timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _repo_files(repo, token=""):
    return [item for item in _hf_json(f"/api/models/{urllib.parse.quote(repo, safe='/')}/tree/main?recursive=1", token)
            if item.get("type") == "file"]


def classify(kind, item):
    engine, reason = voice_engines.engine_for(kind, item)
    return engine or None, reason


def search(kind, query, token=""):
    text = urllib.parse.quote(str(query or "").strip())
    tag = "automatic-speech-recognition" if kind == "asr" else "text-to-speech"
    items = _hf_json(f"/api/models?search={text}&pipeline_tag={tag}&limit=100&full=true&config=true&sort=downloads&direction=-1", token)
    hits = []
    for item in items:
        if "tiny-random" in item["id"]:
            continue
        engine, reason = classify(kind, item)
        code = license_code(item)
        if code:
            _licenses[item["id"]] = license_text(code)
        hits.append({"id": item["id"], "downloads": item.get("downloads", 0), "gated": bool(item.get("gated")),
                     "engine": engine or "", "engineLabel": ENGINE_LABELS.get(engine, ""), "reason": reason,
                     "license": license_text(code) if code else "", "nonCommercial": non_commercial(code)})
    hits.sort(key=lambda hit: not hit["engine"])
    if str(query or "").strip():
        try:
            from app.voice import catalog
            hits += catalog.search(kind, query)
        except Exception:
            pass
    return hits


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


def details(kind, repo, engine, token=""):
    found = _details(kind, repo, engine, token)
    if "license" not in found:
        source = repo if engine != "audiocpp" else found.get("licenseRepo", "")
        found["license"] = repo_license(source, token) if source else ""
    return found


def _details(kind, repo, engine, token=""):
    if engine == "audiocpp":
        from app.voice import catalog
        return catalog.details(repo.split(":", 1)[1])
    files = _repo_files(repo, token)
    if engine == "nemo":
        ggufs = [{"path": item["path"], "size": item.get("size") or 0} for item in files
                 if item["path"].lower().endswith(".gguf") and "mmproj" not in item["path"].lower()]
        if not ggufs:
            return {"supported": False, "reason": "В репозитории нет GGUF-файлов."}
        from app.models import memory_fit
        smallest = min(ggufs, key=lambda item: item["size"])
        arch = memory_fit.remote_metadata(repo, smallest["path"], token).get("general.architecture", "")
        if arch != "asr":
            return {"supported": False, "reason": f"Этот GGUF сделан для другой программы (архитектура «{arch or 'неизвестна'}»), NeMo-Speech его не откроет. "
                                                  "Поищи ту же модель в формате Transformers, обычно это репозиторий без «gguf» в названии."}
        ggufs.sort(key=lambda item: (0 if "q8_0" in item["path"].lower() else 1, item["path"]))
        return {"supported": True, "engine": "nemo", "files": ggufs, "bytes": ggufs[0]["size"]}
    if engine == "qwen":
        result = tts_details(repo, token)
        return {**result, "engine": "qwen"}
    if engine == "piper":
        paths = {item["path"] for item in files}
        voices = [{"path": item["path"], "size": (item.get("size") or 0)} for item in files
                  if item["path"].endswith(".onnx") and (item["path"] + ".json" in paths
                                                        or str(Path(item["path"]).parent / "config.json").replace("\\", "/").lstrip("./") in paths)]
        if not voices:
            return {"supported": False, "reason": "В репозитории нет голоса Piper (файла .onnx с настройками .json)."}
        return {"supported": True, "engine": "piper", "files": voices, "bytes": voices[0]["size"]}
    if engine in voice_engines.ENGINES:
        keep = _snapshot_files(engine, files)
        if not any(item["path"].endswith(WEIGHT_SUFFIXES) for item in keep):
            formats = sorted({Path(item["path"]).suffix for item in files if Path(item["path"]).suffix in (".gguf", ".onnx", ".mlmodel", ".tflite")})
            return {"supported": False, "reason": "В репозитории нет весов safetensors или PyTorch, которые нужны движку "
                    + ENGINE_LABELS.get(engine, engine) + (f" (здесь только {', '.join(formats)})." if formats else ".")}
        voices = sorted(Path(item["path"]).stem for item in files if engine == "kokoro" and item["path"].startswith("voices/") and item["path"].endswith(".pt"))
        return {"supported": True, "engine": engine, "voices": voices, "bytes": sum(item.get("size") or 0 for item in keep)}
    return {"supported": False, "reason": "Для этой модели нет движка."}


def tts_details(repo, token=""):
    files = _repo_files(repo, token)
    config = _hf_json(f"/{urllib.parse.quote(repo, safe='/')}/raw/main/config.json", token)
    kind = config.get("tts_model_type")
    supported = config.get("model_type") == "qwen3_tts" and kind in ("custom_voice", "voice_design") \
        and any(item["path"] == "model.safetensors" for item in files)
    reason = "" if supported else ("Это Base-модель: она клонирует голос по образцу записи, такое пока не поддерживается."
                                   if kind == "base" else "Эта модель не в формате Qwen3-TTS, который умеет запускать программа.")
    return {"supported": supported, "reason": reason, "mode": "custom" if kind == "custom_voice" else "design",
            "voices": _speakers(config), "bytes": sum(item.get("size") or 0 for item in files)}


def _download(url, destination, size, sha256, cancel_event, on_bytes, token="", on_wait=None):
    partial = destination.with_name(destination.name + ".download")
    headers = {"User-Agent": USER_AGENT, **({"Authorization": f"Bearer {token}"} if token else {})}
    try:
        received = download.fetch(url, partial, headers, cancel_event, on_bytes, on_wait or _wait_note)
        if size and received != size:
            raise RuntimeError(f"Файл {destination.name} скачался не полностью: {received} из {size} байт.")
        if sha256:
            digest = hashlib.sha256()
            with partial.open("rb") as handle:
                for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != sha256:
                raise RuntimeError(f"Контрольная сумма {destination.name} не совпала, файл повреждён.")
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


def install_asr(model_id, progress, cancel_event, file=None, token=""):
    if file:
        repo = model_id
        path = CUSTOM_ASR_DIR / repo.replace("/", "--") / Path(file["path"]).name
        quoted = "/".join(urllib.parse.quote(part, safe="") for part in file["path"].split("/"))
        info = {"title": path.stem, "bytes": int(file.get("size") or 0), "sha256": "",
                "url": f"https://huggingface.co/{urllib.parse.quote(repo, safe='/')}/resolve/main/{quoted}"}
        model_id = f"{CUSTOM_PREFIX}{repo}/{path.name}"
        installed = path.is_file() and path.stat().st_size == info["bytes"]
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
        _download(info["url"], path, info["bytes"], info["sha256"], cancel_event,
                  lambda received: progress(share + (100 - share) * received / max(info["bytes"], 1),
                                            f"Скачивание {info['title']}: {received / 2**20:.0f} из {info['bytes'] / 2**20:.0f} МБ"), token)
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
        installed = (_tts_cache(repo) / "snapshots").is_dir() and _tts_config(repo) is not None
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


def install(kind, model_id, progress, cancel_event, extra=None, token=""):
    extra = extra or {}
    reported, report = [0], progress

    def progress(percent, message):
        reported[0] = percent
        report(percent, message)
    _wait_note.progress = lambda message: report(reported[0], message)
    engine = extra.get("engine", "")
    if engine == "audiocpp":
        from app.voice import catalog
        family = model_id.split(":", 1)[1]
        entry = catalog.install(kind, family, extra["file"]["path"], progress, cancel_event, token)
        installed_id = f"audiocpp:{family}/{entry['package']}"
        _register(kind, installed_id, entry)
        progress(100, f"{entry['title']} готова")
        return installed_id
    if engine in voice_engines.ENGINES and engine not in ("nemo", "qwen", "piper"):
        return install_snapshot(kind, model_id, engine, extra.get("size", 0), progress, cancel_event, token, extra.get("voices"))
    if engine == "piper" and kind == "tts":
        return install_piper(model_id, extra["file"], progress, cancel_event, token)
    if kind == "asr" and (model_id in ASR_MODELS or extra.get("file")):
        return install_asr(model_id, progress, cancel_event, extra.get("file"), token)
    if kind == "tts" and (model_id in TTS_MODELS or extra.get("repo")):
        return install_tts(model_id, progress, cancel_event, extra.get("repo"), extra.get("size", 0), token)
    raise ValueError(f"Неизвестная модель: {kind}/{model_id}")
