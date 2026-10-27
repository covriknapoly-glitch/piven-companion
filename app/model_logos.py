"""Logos for model names: the developer's Hugging Face avatar (Qwen, Meta, Google, NVIDIA...). No UI code.

The family is guessed from the model or repository name, so a GGUF re-upload by bartowski still shows
the Qwen logo. Avatar links are fetched once per organisation and kept in DATA_DIR/model_logos.json;
the images themselves load from the Hugging Face CDN. Nothing is bundled with the program.
"""
from __future__ import annotations

import json
import re
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from llama_backend import DATA_DIR

CACHE_PATH = DATA_DIR / "model_logos.json"
USER_AGENT = "PIVEN-Companion/1.0"

# (pattern in a lower-case model name, Hugging Face organisation); first match wins.
FAMILIES = [
    # Meta: the meta-models avatar is centred, the meta-llama one sits off to the right.
    (r"muse[-_ ]?(glimmer|spark)|llama|codellama", "meta-models"), (r"qwen|qwq", "Qwen"), (r"gemma|gemini", "google"),
    (r"mistral|mixtral|ministral|devstral|magistral|codestral|pixtral", "mistralai"),
    (r"deepseek", "deepseek-ai"), (r"\bphi[-_]?\d|phi-", "microsoft"), (r"granite", "ibm-granite"),
    (r"gpt-oss", "openai"), (r"nemotron|parakeet|magpie|canary", "nvidia"), (r"glm|chatglm", "zai-org"),
    (r"smollm", "HuggingFaceTB"), (r"kimi", "moonshotai"), (r"minimax", "MiniMaxAI"), (r"\byi[-_]", "01-ai"),
    (r"command[-_]?r|aya", "CohereLabs"), (r"olmo|tulu", "allenai"), (r"falcon", "tiiuae"),
    (r"internlm|internvl", "internlm"), (r"hermes", "NousResearch"), (r"exaone", "LGAI-EXAONE"),
    (r"ernie", "baidu"), (r"hunyuan", "tencent"), (r"seed[-_]?oss", "ByteDance-Seed"), (r"lfm", "LiquidAI"),
]

_lock = threading.Lock()
_cache: dict[str, str] | None = None
_misses: set[str] = set()  # failed lookups this session (offline, unknown org); retried next launch


def organisation(name, author=""):
    """Developer organisation for a model or repository name; falls back to the uploader."""
    text = str(name or "").lower()
    for pattern, org in FAMILIES:
        if re.search(pattern, text):
            return org
    return str(author or "")


def _load():
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            _cache = {}
    return _cache


def _fetch(org):
    for kind in ("organizations", "users"):
        url = f"https://huggingface.co/api/{kind}/{urllib.parse.quote(org, safe='')}/avatar"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=8) as response:
                avatar = json.loads(response.read().decode("utf-8")).get("avatarUrl", "")
                if str(avatar).startswith("https://"):
                    return avatar
        except Exception:
            continue
    return ""


def logos(names, authors=None):
    """{name: avatar URL or ""} for the given model names (authors: optional {name: uploader})."""
    authors = authors or {}
    wanted = {name: organisation(name, authors.get(name, "")) for name in names}
    with _lock:
        cache = _load()
        missing = sorted({org for org in wanted.values() if org and org not in cache and org not in _misses})
    if missing:
        with ThreadPoolExecutor(max_workers=8) as pool:
            found = dict(zip(missing, pool.map(_fetch, missing)))
        with _lock:
            cache.update({org: url for org, url in found.items() if url})
            _misses.update(org for org, url in found.items() if not url)
            try:
                CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
            except OSError:
                pass
    with _lock:
        return {name: cache.get(org, "") if org else "" for name, org in wanted.items()}
