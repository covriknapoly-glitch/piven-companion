from __future__ import annotations

import json
import re
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from app.models.llama import DATA_DIR

CACHE_PATH = DATA_DIR / "model_logos.json"
USER_AGENT = "PIVEN-Companion/1.0"

FAMILIES = [
    (r"muse[-_ ]?(glimmer|spark)|llama|codellama", "meta-models"), (r"qwen|qwq", "Qwen"), (r"gemma|gemini", "google"),
    (r"mistral|mixtral|ministral|devstral|magistral|codestral|pixtral", "mistralai"),
    (r"deepseek", "deepseek-ai"), (r"\bphi[-_]?\d|phi-", "microsoft"), (r"granite", "ibm-granite"),
    (r"gpt-oss", "openai"), (r"nemotron|parakeet|magpie|canary", "nvidia"), (r"glm|chatglm", "zai-org"),
    (r"smollm", "HuggingFaceTB"), (r"kimi", "moonshotai"), (r"minimax", "MiniMaxAI"), (r"\byi[-_]", "01-ai"),
    (r"command[-_]?r|aya", "CohereLabs"), (r"olmo|tulu", "allenai"), (r"falcon", "tiiuae"),
    (r"internlm|internvl", "internlm"), (r"hermes", "NousResearch"), (r"exaone", "LGAI-EXAONE"),
    (r"ernie", "baidu"), (r"hunyuan", "tencent"), (r"seed[-_]?oss", "ByteDance-Seed"), (r"lfm", "LiquidAI"),
]

ARCHITECTURES = {
    "qwen": "Qwen", "gemma": "google", "llama4": "meta-models", "mistral": "mistralai", "pixtral": "mistralai",
    "phi": "microsoft", "granite": "ibm-granite", "gpt-oss": "openai", "gptoss": "openai", "nemotron": "nvidia",
    "glm": "zai-org", "chatglm": "zai-org", "deepseek": "deepseek-ai", "olmo": "allenai", "falcon": "tiiuae",
    "internlm": "internlm", "exaone": "LGAI-EXAONE", "ernie": "baidu", "hunyuan": "tencent", "seed_oss": "ByteDance-Seed",
    "lfm": "LiquidAI", "minimax": "MiniMaxAI", "command-r": "CohereLabs", "cohere": "CohereLabs", "smollm": "HuggingFaceTB",
    "kimi": "moonshotai", "arcee": "arcee-ai", "apertus": "swiss-ai", "starcoder": "bigcode", "mamba": "state-spaces",
    "rwkv": "RWKV", "bailing": "inclusionAI", "dots1": "rednote-hilab", "jamba": "ai21labs", "plamo": "pfnet",
}
SHARED_ARCHITECTURES = {
    "deepseek2": [(r"glm", "zai-org"), (r"kimi", "moonshotai")],
    "llama": [(r"smollm", "HuggingFaceTB"), (r"\byi[-_]", "01-ai"), (r"falcon", "tiiuae"), (r"mistral|mixtral", "mistralai"),
              (r"granite", "ibm-granite"), (r"exaone", "LGAI-EXAONE"), (r"internlm", "internlm")],
}

_lock = threading.Lock()
_cache: dict[str, str] | None = None
_misses: set[str] = set()


def organisation(name, author="", architecture=""):
    text = str(name or "").lower()
    arch = str(architecture or "").lower()
    provider, _, rest = text.partition(":")
    if rest and provider in ("openai", "anthropic", "gemini", "openrouter", "ollama", "lmstudio", "custom"):
        if provider in ("openai", "anthropic", "gemini"):
            return {"openai": "openai", "anthropic": "Anthropic", "gemini": "google"}[provider]
        text = rest.split("/", 1)[-1] if provider == "openrouter" else rest
        if provider == "openrouter" and rest.startswith(("anthropic/", "openai/", "google/")):
            return {"anthropic": "Anthropic", "openai": "openai", "google": "google"}[rest.split("/", 1)[0]]
    if arch:
        for pattern, org in SHARED_ARCHITECTURES.get(arch, []):
            if re.search(pattern, text):
                return org
        if arch == "llama":
            return "meta-models"
        for prefix in sorted(ARCHITECTURES, key=len, reverse=True):
            if arch.startswith(prefix):
                return ARCHITECTURES[prefix]
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


def logos(names, authors=None, architectures=None):
    authors, architectures = authors or {}, architectures or {}
    wanted = {name: organisation(name, authors.get(name, ""), architectures.get(name, "")) for name in names}
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
