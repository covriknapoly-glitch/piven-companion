"""The audio.cpp model catalogue: speech recognition and speech models from its model specs. No UI code.

audio.cpp ships a JSON spec per model family (model_specs/<family>.json) with its tasks, languages,
built-in voices and downloadable GGUF packages. Before the engine is installed the specs of the pinned
release are read from GitHub once and cached in DATA_DIR.
"""
from __future__ import annotations

import json
import os
import re
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import voice_engines

DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OllamaCompanion"
SPECS_CACHE = DATA_DIR / f"audiocpp_specs_{voice_engines.AUDIOCPP_VERSION}.json"
MODELS_DIR = voice_engines.AUDIOCPP_DIR / "models"
DEFAULT_REPO = "audio-cpp/audio.cpp-gguf"
USER_AGENT = "PIVEN-Companion/1.0"
TASKS = {"asr": {"asr"}, "tts": {"tts", "clone", "clon", "design", "vdes"}}
# Families left out: Kokoro's server path cannot find eSpeak's data in the release build (the Python
# Kokoro engine runs the same model).
SKIP_FAMILIES = {"kokoro_tts"}
# The specs carry no license. Families whose original weights are for non-commercial use only:
# XTTS (Coqui CPML), F5-TTS (CC-BY-NC-4.0), Fish-Speech / OpenAudio (CC-BY-NC-SA-4.0).
NON_COMMERCIAL = re.compile(r"xtts|f5|fish|openaudio")

_lock = threading.Lock()
_specs: dict | None = None
_trees: dict = {}


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=30) as response:
        return response.read()


def specs():
    """{family: spec} for every family audio.cpp knows."""
    global _specs
    with _lock:
        if _specs is not None:
            return _specs
    local = voice_engines.AUDIOCPP_DIR / "model_specs"
    found = {}
    if local.is_dir():
        for path in local.glob("*.json"):
            try:
                spec = json.loads(path.read_text(encoding="utf-8"))
                found[spec.get("family", path.stem)] = spec
            except Exception:
                continue
    elif SPECS_CACHE.is_file():
        found = json.loads(SPECS_CACHE.read_text(encoding="utf-8"))
    else:
        tag = voice_engines.AUDIOCPP_VERSION
        listing = json.loads(_get(f"https://api.github.com/repos/0xShug0/audio.cpp/contents/model_specs?ref={tag}"))
        names = [item["name"] for item in listing if item["name"].endswith(".json")]

        def fetch(name):
            try:
                return json.loads(_get(f"https://raw.githubusercontent.com/0xShug0/audio.cpp/{tag}/model_specs/{name}"))
            except Exception:
                return None
        with ThreadPoolExecutor(max_workers=12) as pool:
            for spec in pool.map(fetch, names):
                if spec and spec.get("family"):
                    found[spec["family"]] = spec
        SPECS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        SPECS_CACHE.write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
    with _lock:
        _specs = found
    return found


def kind_of(spec):
    tasks = set(spec.get("tasks") or [])
    if tasks & TASKS["asr"]:
        return "asr"
    if tasks & TASKS["tts"]:
        return "tts"
    return ""


def task_for(spec, kind):
    tasks = list(spec.get("tasks") or [])
    if kind == "asr":
        return "asr"
    return "tts" if "tts" in tasks else next((task for task in tasks if task in TASKS["tts"]), "tts")


def voices(spec):
    builtin = (spec.get("ui") or {}).get("builtin_voices") or []
    if builtin:
        return list(builtin)
    for option in (spec.get("options") or {}).get("request", []):
        if option.get("name") in ("voice_id", "voice", "speaker") and option.get("values"):
            return list(option["values"])
    return []


def can_clone(spec):
    capabilities = spec.get("capabilities") or {}
    return any("speaker_reference" in values or "reference_audio" in values for values in capabilities.values() if isinstance(values, list))


def language(spec):
    """The code to ask for Russian, or "" when the family does not list it."""
    for code in spec.get("languages") or []:
        if str(code).lower().split("-")[0] == "ru":
            return code
    return "auto" if "auto" in (spec.get("languages") or []) else ""


def search(kind, query):
    """Families matching every word of the query, as search hits."""
    words = [word for word in str(query or "").lower().split() if word]
    hits = []
    for family, spec in specs().items():
        if family in SKIP_FAMILIES or kind_of(spec) != kind or not any(package.get("format") == "gguf" for package in spec.get("packages") or []):
            continue
        text = " ".join([family, spec.get("display_name", ""), spec.get("description", "")]).lower()
        if all(word in text for word in words):
            russian = bool(language(spec))
            restricted = bool(NON_COMMERCIAL.search(family))
            hits.append({"id": f"audiocpp:{family}", "title": spec.get("display_name", family), "downloads": 0, "gated": False,
                         "engine": "audiocpp", "engineLabel": "audio.cpp", "reason": "", "nonCommercial": restricted,
                         "license": "только некоммерческое использование (лицензия исходной модели)" if restricted else "",
                         "note": ("есть русский · " if russian else "") + spec.get("description", "")[:160]})
    hits.sort(key=lambda hit: hit["note"].startswith("есть русский"), reverse=True)
    return hits


def _tree(repo):
    with _lock:
        if repo in _trees:
            return _trees[repo]
    items = json.loads(_get(f"https://huggingface.co/api/models/{urllib.parse.quote(repo, safe='/')}/tree/main?recursive=1"))
    sizes = {item["path"]: item.get("size") or 0 for item in items if item.get("type") == "file"}
    with _lock:
        _trees[repo] = sizes
    return sizes


def _repo(package):
    download = package.get("download") or {}
    return download.get("repo") or DEFAULT_REPO


def details(family):
    spec = specs().get(family)
    if not spec:
        return {"supported": False, "reason": "audio.cpp не знает такую модель."}
    packages = [package for package in spec.get("packages") or [] if package.get("format") == "gguf"]
    recommended = (spec.get("ui") or {}).get("recommended_package")
    packages.sort(key=lambda package: (package.get("id") != recommended, not package.get("default")))
    files = []
    for package in packages:
        try:
            sizes = _tree(_repo(package))
        except Exception:
            sizes = {}
        files.append({"path": package["id"], "label": package.get("display_name", package["id"]),
                      "size": sum(sizes.get(name, 0) for name in package.get("files") or [])})
    note = spec.get("description", "")
    langs = ", ".join(spec.get("languages") or [])
    return {"supported": bool(files), "engine": "audiocpp", "files": files, "bytes": files[0]["size"] if files else 0,
            "licenseRepo": _repo(packages[0]) if packages else "",
            **({"license": "только некоммерческое использование (лицензия исходной модели)"} if NON_COMMERCIAL.search(family) else {}),
            "voices": voices(spec), "reason": "" if files else "У этой модели нет готового GGUF-пакета.",
            "note": f"{note} Языки: {langs or 'не указаны'}." + ("" if language(spec) else " Русского в списке языков нет.")}


def package_dir(package):
    return MODELS_DIR / package.get("target_directory", package["id"])


def install(kind, family, package_id, progress, cancel_event, token=""):
    """Download one package of a family; returns the registry entry for it."""
    from voice_install import _download
    spec = specs()[family]
    package = next(item for item in spec.get("packages") or [] if item["id"] == package_id)
    start = voice_engines.ensure_audiocpp(progress, cancel_event)
    repo = _repo(package)
    sizes = _tree(repo)
    files = package.get("files") or []
    total = sum(sizes.get(name, 0) for name in files) or 1
    folder = package_dir(package)
    prefix = (package.get("strip_prefix") or "").strip("/")
    done = 0
    for name in files:
        relative = name[len(prefix) + 1:] if prefix and name.startswith(prefix + "/") else name
        target = folder / relative
        size = sizes.get(name, 0)
        if not (target.is_file() and target.stat().st_size == size):
            quoted = "/".join(urllib.parse.quote(part, safe="") for part in name.split("/"))
            url = f"https://huggingface.co/{urllib.parse.quote(repo, safe='/')}/resolve/main/{quoted}"
            _download(url, target, size, "", cancel_event,
                      lambda received: progress(start + (99 - start) * (done + received) / total,
                                                f"Скачивание {spec.get('display_name', family)}: {(done + received) / 2**20:.0f} из {total / 2**20:.0f} МБ"), token)
        done += size
    ggufs = [path for path in folder.rglob("*.gguf")]
    path = ggufs[0] if len(files) == 1 and len(ggufs) == 1 else folder
    return {"engine": "audiocpp", "family": family, "package": package_id, "task": task_for(spec, kind), "path": str(path),
            "repo": repo, "title": package.get("display_name", spec.get("display_name", family)), "bytes": total,
            "voices": voices(spec), "language": language(spec), "clone": can_clone(spec),
            "note": f"audio.cpp · {spec.get('description', '')[:200]}", "license": "см. страницу модели"}
