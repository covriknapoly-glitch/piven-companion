from __future__ import annotations

import json
import os
import re
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app import paths
from app.voice import engines

DATA_DIR = paths.DATA_DIR
SPECS_CACHE = DATA_DIR / f"audiocpp_specs_{engines.AUDIOCPP_VERSION}.json"
MODELS_DIR = engines.AUDIOCPP_DIR / "models"
DEFAULT_REPO = "audio-cpp/audio.cpp-gguf"
USER_AGENT = "PIVEN-Companion/1.0"
TASKS = {"asr": {"asr"}, "tts": {"tts", "clone", "clon", "design", "vdes"}}
NON_COMMERCIAL = re.compile(r"xtts|f5|fish|openaudio")

_lock = threading.Lock()
_specs: dict | None = None
_trees: dict = {}


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=30) as response:
        return response.read()


def specs(cached_only=False):
    global _specs
    with _lock:
        if _specs is not None:
            return _specs
    local = engines.AUDIOCPP_DIR / "model_specs"
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
    elif cached_only:
        return {}
    else:
        tag = engines.AUDIOCPP_VERSION
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
    for code in spec.get("languages") or []:
        if str(code).lower().split("-")[0] == "ru":
            return code
    return "auto" if "auto" in (spec.get("languages") or []) else ""


def gguf_packages(spec):
    return [package for package in spec.get("packages") or []
            if package.get("format") == "gguf"
            and any(name.lower().endswith(".gguf") for name in package.get("files") or [])]


def search(kind, query, cached_only=False, repo=""):
    words = [word for word in str(query or "").lower().split() if word]
    hits = []
    for family, spec in specs(cached_only=cached_only).items():
        packages = gguf_packages(spec)
        if not (set(spec.get("tasks") or []) & TASKS.get(kind, set())) or not packages:
            continue
        repositories = sorted({_repo(package) for package in packages})
        package_names = {name.casefold() for package in packages
                         if (name := package.get("target_directory", "")).lower().endswith("-gguf")}
        if repo and repo.casefold() not in {source.casefold() for source in repositories}:
            if kind != "asr" or repo.rsplit("/", 1)[-1].casefold() not in package_names:
                continue
        text = " ".join([family, spec.get("display_name", ""), spec.get("description", "")]).lower()
        if all(word in text for word in words):
            russian = bool(language(spec))
            restricted = bool(NON_COMMERCIAL.search(family))
            hits.append({"id": f"audiocpp:{family}", "title": spec.get("display_name", family), "downloads": 0, "gated": False,
                         "repositories": repositories, "packageNames": sorted(package_names),
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


def file_package(kind, repo, path):
    for family, spec in specs(cached_only=True).items():
        if set(spec.get("tasks") or []) & TASKS[kind]:
            for package in gguf_packages(spec):
                if _repo(package).casefold() == repo.casefold() and path in package.get("files", []):
                    return family, package["id"]
    return None


def required_sidecars(spec, embedded):
    source = next((source for source in spec.get("sources", []) if source.get("format") == "gguf"), {})
    required = {value.removeprefix("model:") for value in (source.get("files") or {}).values()
                if isinstance(value, str) and value.startswith("model:")}
    return sorted(required.difference(embedded))


def details(family, kind):
    spec = specs().get(family)
    if not spec or not (set(spec.get("tasks") or []) & TASKS.get(kind, set())):
        return {"supported": False, "reason": "audio.cpp не знает такую модель."}
    packages = gguf_packages(spec)
    recommended = (spec.get("ui") or {}).get("recommended_package")
    packages.sort(key=lambda package: (package.get("id") != recommended, not package.get("default")))
    files = []
    for package in packages:
        try:
            sizes = _tree(_repo(package))
        except Exception:
            sizes = {}
        files.append({"path": package["id"], "label": package.get("display_name", package["id"]),
                      **({"languages": package["languages"]} if isinstance(package.get("languages"), list) else {}),
                      "size": sum(sizes.get(name, 0) for name in package.get("files") or [])})
    note = spec.get("description", "")
    return {"supported": bool(files), "engine": "audiocpp", "files": files, "bytes": files[0]["size"] if files else 0,
            "licenseRepo": _repo(packages[0]) if packages else "",
            **({"license": "только некоммерческое использование (лицензия исходной модели)"} if NON_COMMERCIAL.search(family) else {}),
            "voices": voices(spec), "reason": "" if files else "У этой модели нет готового GGUF-пакета.",
            "note": note, "languages": spec.get("languages") or [], "languagesComplete": True}


def package_dir(package):
    return MODELS_DIR / package.get("target_directory", package["id"])


def install(kind, family, package_id, progress, cancel_event, token=""):
    from app.voice.install import _download
    spec = specs().get(family) or {}
    package = next((item for item in gguf_packages(spec) if item["id"] == package_id), None)
    if package is None or not (set(spec.get("tasks") or []) & TASKS.get(kind, set())):
        raise ValueError("Для этой задачи нужен совместимый GGUF-пакет audio.cpp.")
    start = engines.ensure_audiocpp(progress, cancel_event)
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
    if not ggufs:
        raise RuntimeError("В скачанном пакете audio.cpp нет GGUF-файла.")
    path = ggufs[0] if len(files) == 1 and len(ggufs) == 1 else folder
    return {"engine": "audiocpp", "family": family, "package": package_id, "task": task_for(spec, kind), "path": str(path),
            "repo": repo, "title": package.get("display_name", spec.get("display_name", family)), "bytes": total,
            "voices": voices(spec), "language": language(spec), "clone": can_clone(spec),
            "note": f"audio.cpp · {spec.get('description', '')[:200]}", "license": "см. страницу модели"}
