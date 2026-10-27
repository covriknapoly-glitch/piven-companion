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


def search_models(query, token=""):
    """GGUF repositories matching the query, most downloaded first."""
    query = str(query or "").strip()
    if len(query) < 2:
        raise ValueError("Введи хотя бы два символа для поиска.")
    params = urllib.parse.urlencode([
        ("search", query), ("filter", "gguf"), ("sort", "downloads"), ("direction", "-1"), ("limit", "40"),
        ("expand[]", "downloads"), ("expand[]", "likes"), ("expand[]", "siblings"),
    ])
    results = _get_json("https://huggingface.co/api/models?" + params, token)
    if not isinstance(results, list):
        raise RuntimeError("Hugging Face вернул неожиданный формат результатов.")
    if not results:
        # Some GGUF repos are not tagged; fall back to scanning their file lists.
        params = urllib.parse.urlencode([
            ("search", query), ("sort", "downloads"), ("direction", "-1"), ("limit", "100"),
            ("expand[]", "downloads"), ("expand[]", "likes"), ("expand[]", "siblings"),
        ])
        candidates = _get_json("https://huggingface.co/api/models?" + params, token)
        results = [model for model in candidates if isinstance(model, dict)
                   and any(str(file.get("rfilename", file.get("path", ""))).lower().endswith(".gguf")
                           for file in model.get("siblings", []) if isinstance(file, dict))]
    models = []
    for model in results:
        repo_id = str(model.get("id") or model.get("modelId") or "")
        if repo_id:
            models.append({"id": repo_id, "downloads": model.get("downloads"), "likes": model.get("likes"),
                           "gated": bool(model.get("gated"))})
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
        label = "файл для картинок (mmproj)" if job is not record else "модель"
        done_bytes += _download_file(repo_id, parts, destination, expected, token, cancel_event,
                                     lambda received, base=done_bytes, what=label: progress(
                                         min(99, int((base + received) * 100 / total_bytes)),
                                         f"Скачиваю {what}: {(base + received) / 1024 ** 3:.2f} из {total_bytes / 1024 ** 3:.2f} ГБ"))
    progress(100, "Модель готова")
    return str(destination_of_model)


def _download_file(repo_id, parts, destination, expected, token, cancel_event, on_bytes):
    partial = destination.with_name(destination.name + ".download")
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_path = "/".join(urllib.parse.quote(part, safe="") for part in parts)
    url = f"https://huggingface.co/{urllib.parse.quote(repo_id, safe='/')}/resolve/main/{file_path}?download=true"
    received = 0
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=_headers(token)), timeout=60) as response:
            with partial.open("wb") as output:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise InterruptedError("Загрузка отменена.")
                    chunk = response.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    received += len(chunk)
                    on_bytes(received)
        if isinstance(expected, (int, float)) and expected > 0 and received != expected:
            raise RuntimeError(f"Размер скачанного файла не совпадает с Hugging Face: {received} из {int(expected)} байт.")
        os.replace(partial, destination)
        return received
    except Exception:
        try:
            partial.unlink(missing_ok=True)
        except Exception:
            pass
        raise
