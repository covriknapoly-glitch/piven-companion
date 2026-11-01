"""Find GGUF models on Hugging Face and download them into the llama.cpp models folder. No UI code.

A model is ready to use as soon as its file is on disk: llama_backend scans the folder. If the
repository also has a vision projector (a file with "mmproj" in its name), it is downloaded next to
the model so the companion can look at images and the screen.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import resumable
from llama_backend import MODELS_DIR

USER_AGENT = "PIVEN-Companion/1.0"
REPO_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def _headers(token=""):
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get_json(url, token="", timeout=45):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=_headers(token)), timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            body = error.read().decode("utf-8", errors="replace")[:600]
        except Exception:
            body = str(error)
        raise RuntimeError(f"Hugging Face HTTP {error.code}: {body or error.reason}") from error


AUDIO_TASKS = {"text-to-speech", "automatic-speech-recognition", "text-to-audio", "audio-to-audio",
               "audio-classification", "voice-activity-detection"}
AUDIO_WORDS = re.compile(r"(?:^|[-_/ ])(?:tts|asr|whisper|parakeet|stt|speech|voice|vocoder|kokoro|outetts|orpheus|piper)(?:$|[-_/ .\d])", re.I)


def is_audio_model(model):
    """A speech recognition or synthesis model (they are searched in the voice window, not among chat models)."""
    if str(model.get("pipeline_tag") or "") in AUDIO_TASKS:
        return True
    if any(str(tag) in AUDIO_TASKS for tag in model.get("tags") or []):
        return True
    return bool(AUDIO_WORDS.search(str(model.get("id") or model.get("modelId") or "")))


_descriptions = {}
QUANT_CARD = re.compile(r"(?:static quants|weighted/imatrix|\bquants? of|quantizations? of|quantized version|"
                        r"gguf (?:version|files|format) of|original model:|llamacpp imatrix|converted to gguf|unsure how to use gguf)", re.I)


def _readme_summary(repo_id, token=""):
    """The first prose paragraphs of a model card: no front matter, headings, tables, images, links or code."""
    url = f"https://huggingface.co/{urllib.parse.quote(repo_id, safe='/')}/raw/main/README.md"
    request = urllib.request.Request(url, headers={**_headers(token), "Range": "bytes=0-65535"})
    with urllib.request.urlopen(request, timeout=20) as response:
        text = response.read().decode("utf-8", "replace")
    text = re.sub(r"\A---.*?\n---\s*\n", "", text, flags=re.S)
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"(?m)^#+ .*$", "\n", text)
    paragraphs = []
    for block in re.split(r"\n\s*\n", text):
        lines = [line.strip() for line in block.splitlines()]
        if not lines or lines[0].startswith(("#", "|", ">", "-", "*", "1.")) or "|" in block[:200]:
            continue
        prose = " ".join(" ".join(lines).replace("**", "").replace("__", "").replace("`", "").split())
        if len(prose) >= 60:
            paragraphs.append(prose)
        if sum(len(item) for item in paragraphs) > 500:
            break
    summary = " ".join(paragraphs)
    return summary[:700].rsplit(" ", 1)[0] + "…" if len(summary) > 700 else summary


def _base_model(repo_id, token=""):
    """The repository a model was made from (its card's base_model), or None."""
    try:
        info = _get_json(f"https://huggingface.co/api/models/{urllib.parse.quote(repo_id, safe='/')}", token)
    except Exception:
        return None
    base = (info.get("cardData") or {}).get("base_model") if isinstance(info, dict) else None
    base = base[0] if isinstance(base, list) and base else base
    return base if isinstance(base, str) and REPO_PATTERN.fullmatch(base) and base != repo_id else None


def model_description(repo_id, token=""):
    """A short description of a repository for the download window. GGUF repositories are conversions whose
    cards only list quants, and fine-tunes often have empty cards: then the card of the model they were made
    from is used, following base_model up to three steps."""
    repo_id = str(repo_id or "").strip()
    if repo_id in _descriptions:
        return _descriptions[repo_id]
    result = {"text": "", "source": repo_id}
    # where to look: for a GGUF conversion its originals first (base_model, up to three steps), its own card last
    chain, source = [], repo_id
    for _ in range(4):
        chain.append(source)
        source = _base_model(source, token)
        if not source or "gguf" not in chain[0].lower():
            break
    for source in (chain[1:] + chain[:1]) if len(chain) > 1 else chain:
        try:
            text = _readme_summary(source, token)
        except Exception:
            text = ""
        if text and not QUANT_CARD.search(text[:400]):
            result.update(text=text, source=source)
            break
    _descriptions[repo_id] = result
    return result


# First-launch suggestions by video memory (GB): repositories tried in order, the first one that exists wins.
RECOMMENDED = [
    (20, ["unsloth/Qwen3.6-35B-A3B-GGUF", "unsloth/Qwen3.8-27B-GGUF", "bartowski/google_gemma-4-26B-A4B-it-GGUF"]),
    (10, ["unsloth/Qwen3.5-9B-GGUF", "bartowski/google_gemma-4-12b-it-GGUF", "unsloth/gemma-4-12b-it-GGUF"]),
    (6, ["unsloth/Qwen3.5-4B-GGUF", "bartowski/google_gemma-4-E4B-it-GGUF", "unsloth/gemma-4-E4B-it-GGUF"]),
    (0, ["bartowski/google_gemma-4-E2B-it-GGUF", "unsloth/Qwen3.5-2B-GGUF", "unsloth/gemma-4-E2B-it-GGUF"]),
]


def recommended(gpu_bytes, token=""):
    """A good first model for this computer: {"repo", "record", "tag", "size", "why"} or None when offline."""
    gigabytes = gpu_bytes / 2**30
    for minimum, repos in RECOMMENDED:
        if gigabytes < minimum:
            continue
        for repo in repos:
            try:
                files = list_gguf_files(repo, token)
            except Exception:
                continue
            files = files if isinstance(files, list) else []
            pick = next((item for item in files if "q4_k_m" in item["path"].lower()), None) or next(
                (item for item in files if "q4" in item["path"].lower()), None)
            if pick:
                why = (f"подходит видеокарте с {gigabytes:.0f} ГБ памяти" if gpu_bytes else "работает даже без видеокарты")
                return {"repo": repo, "record": pick, "tag": suggested_tag(repo, pick["path"]), "size": pick.get("size", 0), "why": why}
    return None


def search_models(query, token=""):
    """GGUF repositories matching the query, most downloaded first."""
    query = str(query or "").strip()
    if len(query) < 2:
        raise ValueError("Введи хотя бы два символа для поиска.")
    params = urllib.parse.urlencode([
        ("search", query), ("filter", "gguf"), ("sort", "downloads"), ("direction", "-1"), ("limit", "60"),
        ("expand[]", "downloads"), ("expand[]", "likes"), ("expand[]", "siblings"),
        ("expand[]", "pipeline_tag"), ("expand[]", "tags"), ("expand[]", "gguf"),
    ])
    results = _get_json("https://huggingface.co/api/models?" + params, token)
    if not isinstance(results, list):
        raise RuntimeError("Hugging Face вернул неожиданный формат результатов.")
    if not results:
        # Some GGUF repos are not tagged; fall back to scanning their file lists.
        params = urllib.parse.urlencode([
            ("search", query), ("sort", "downloads"), ("direction", "-1"), ("limit", "100"),
            ("expand[]", "downloads"), ("expand[]", "likes"), ("expand[]", "siblings"),
            ("expand[]", "pipeline_tag"), ("expand[]", "tags"), ("expand[]", "gguf"),
        ])
        candidates = _get_json("https://huggingface.co/api/models?" + params, token)
        results = [model for model in candidates if isinstance(model, dict)
                   and any(str(file.get("rfilename", file.get("path", ""))).lower().endswith(".gguf")
                           for file in model.get("siblings", []) if isinstance(file, dict))]
    models = []
    for model in results:
        repo_id = str(model.get("id") or model.get("modelId") or "")
        if repo_id and not is_audio_model(model):  # voice models have their own search
            models.append({"id": repo_id, "downloads": model.get("downloads"), "likes": model.get("likes"),
                           "gated": bool(model.get("gated")),
                           "arch": str((model.get("gguf") or {}).get("architecture") or "")})
    return models


def _repo_ggufs(repo_id, token=""):
    repo_id = str(repo_id or "").strip().strip("/")
    if not REPO_PATTERN.fullmatch(repo_id):
        raise ValueError("Введи ID репозитория в формате автор/модель.")
    encoded_repo = urllib.parse.quote(repo_id, safe="/")
    # Expanded tree responses are capped at 50 entries by HF; asking for 1000 with expand=true returns HTTP 400.
    records = _get_json(f"https://huggingface.co/api/models/{encoded_repo}/tree/main?recursive=true&limit=1000", token, 40)
    if not isinstance(records, list):
        raise RuntimeError("Hugging Face вернул неожиданный список файлов.")
    return [{"path": item.get("path", ""), "size": item.get("size") or (item.get("lfs") or {}).get("size")}
            for item in records if isinstance(item, dict) and item.get("type") == "file"
            and str(item.get("path", "")).lower().endswith(".gguf")]


def list_gguf_files(repo_id, token=""):
    """Model files in a repository (projectors left out); the Q4_K_M quantisation comes first."""
    files = [item for item in _repo_ggufs(repo_id, token) if "mmproj" not in item["path"].lower()]
    files.sort(key=lambda item: (0 if "q4_k_m" in item["path"].lower() else 1, item["path"].lower()))
    return files


def _pick_projector(files):
    projectors = [item for item in files if "mmproj" in item["path"].lower()]
    projectors.sort(key=lambda item: (0 if "f16" in item["path"].lower() else 1, item.get("size") or 0))
    return projectors[0] if projectors else None


def suggested_tag(repo_id, file_path):
    """Kept for the dialog: the name the model will have in the list (the file name without .gguf)."""
    return os.path.splitext(os.path.basename(str(file_path or "model.gguf")))[0]


def _safe_parts(path):
    parts = str(path or "").replace("\\", "/").split("/")
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError("Путь к файлу из репозитория некорректен.")
    return parts


def download_model(repo_id, record, token="", progress=lambda percent, message: None, cancel_event=None):
    """Download the GGUF (and the repo's vision projector, if any) into MODELS_DIR. Returns the model path."""
    repo_id = str(repo_id or "").strip().strip("/")
    if not REPO_PATTERN.fullmatch(repo_id):
        raise ValueError("Введи ID репозитория в формате автор/модель.")
    folder = MODELS_DIR / repo_id.replace("/", "--")
    jobs = [record]
    try:
        projector = _pick_projector(_repo_ggufs(repo_id, token))
    except Exception:
        projector = None
    if projector and not any("mmproj" in item.name.lower() for item in folder.glob("*.gguf")):
        jobs.append(projector)
    total_bytes = sum(int(item.get("size") or 0) for item in jobs) or 1
    done_bytes = 0
    destination_of_model = None
    for job in jobs:
        parts = _safe_parts(job.get("path"))
        destination = folder.joinpath(parts[-1])
        destination_of_model = destination_of_model or destination
        expected = job.get("size")
        if destination.is_file() and isinstance(expected, (int, float)) and destination.stat().st_size == expected:
            done_bytes += int(expected)
            continue
        label = "файла для картинок (mmproj)" if job is not record else "модели"
        done_bytes += _download_file(repo_id, parts, destination, expected, token, cancel_event,
                                     lambda received, base=done_bytes, what=label: progress(
                                         min(99, int((base + received) * 100 / total_bytes)),
                                         f"Скачивание {what}: {(base + received) / 1024 ** 3:.2f} из {total_bytes / 1024 ** 3:.2f} ГБ"),
                                     lambda message, base=done_bytes: progress(min(99, int(base * 100 / total_bytes)), message))
    progress(100, "Модель готова")
    return str(destination_of_model)


def _download_file(repo_id, parts, destination, expected, token, cancel_event, on_bytes, on_wait=lambda message: None):
    """Download one file; a lost connection pauses it and it continues from the same place (also after a restart)."""
    partial = destination.with_name(destination.name + ".download")
    file_path = "/".join(urllib.parse.quote(part, safe="") for part in parts)
    url = f"https://huggingface.co/{urllib.parse.quote(repo_id, safe='/')}/resolve/main/{file_path}?download=true"
    try:
        received = resumable.fetch(url, partial, _headers(token), cancel_event, on_bytes, on_wait, chunk=8 * 1024 * 1024)
        if isinstance(expected, (int, float)) and expected > 0 and received != expected:
            raise RuntimeError(f"Размер скачанного файла не совпадает с Hugging Face: {received} из {int(expected)} байт.")
        os.replace(partial, destination)
        return received
    except (InterruptedError, RuntimeError):  # cancelled or broken: start over next time
        partial.unlink(missing_ok=True)
        raise
