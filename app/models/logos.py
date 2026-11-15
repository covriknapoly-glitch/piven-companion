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

# Accounts that only republish other people's models as GGUF; for them the icon comes from the model they converted.
REPUBLISHERS = {"mradermacher", "bartowski", "lmstudio-community", "thebloke", "quantfactory", "second-state", "ggml-org", "mungert",
                "devquasar", "tensorblock", "noctrex", "bullerwins", "richarderkhov", "maziyarpanahi", "gaianet", "nexaai", "featherless-ai-quants",
                "quantized", "legraphista", "afrideva", "duyntnet"}

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


def _get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def _base_model(repo):
    """The model a GGUF copy was made from, as written in its Hugging Face card; None when Hugging Face didn't answer."""
    try:
        info = _get_json(f"https://huggingface.co/api/models/{urllib.parse.quote(repo, safe='/')}")
    except Exception:
        return None
    base = (info.get("cardData") or {}).get("base_model")
    if isinstance(base, list):
        base = base[0] if base else ""
    if not base:
        tags = [str(tag)[len("base_model:"):] for tag in info.get("tags") or [] if str(tag).startswith("base_model:")]
        base = next((tag.rsplit(":", 1)[-1] for tag in tags if "/" in tag), "")
    return str(base or "") if "/" in str(base or "") else ""


def repo_owner(repo):
    """Whose icon to show for a downloaded repo: its owner, or for a plain GGUF copy, the owner of the original model.
    An empty answer means "ask again later", so a network hiccup isn't remembered as the copier's icon."""
    owner = repo.split("/", 1)[0]
    seen = {repo.lower()}
    while owner.lower() in REPUBLISHERS:
        base = _base_model(repo)
        if base is None:
            return ""
        if not base or base.lower() in seen:
            break
        seen.add(base.lower())
        repo, owner = base, base.split("/", 1)[0]
    return owner


def logos(names, authors=None, architectures=None, repos=None):
    authors, architectures, repos = authors or {}, architectures or {}, repos or {}
    with _lock:
        cache = _load()
        unknown = sorted({repo for repo in repos.values() if repo and f"repo:{repo}" not in cache})
    if unknown:
        # A model downloaded from Hugging Face gets the icon of whoever made it there, not a guess from its architecture:
        # fine-tunes keep the base model's architecture, so they all used to show the Qwen or Llama logo.
        with ThreadPoolExecutor(max_workers=8) as pool:
            owners = dict(zip(unknown, pool.map(repo_owner, unknown)))
        with _lock:
            cache.update({f"repo:{repo}": owner for repo, owner in owners.items() if owner})
    with _lock:
        owner_of = {name: cache.get(f"repo:{repos[name]}", "") for name in names if repos.get(name)}
    wanted = {name: owner_of.get(name) or organisation(name, authors.get(name, ""), architectures.get(name, "")) for name in names}
    with _lock:
        cache = _load()
        missing = sorted({org for org in wanted.values() if org and org not in cache and org not in _misses})
        changed = bool(unknown)
    if missing:
        with ThreadPoolExecutor(max_workers=8) as pool:
            found = dict(zip(missing, pool.map(_fetch, missing)))
        with _lock:
            cache.update({org: url for org, url in found.items() if url})
            _misses.update(org for org, url in found.items() if not url)
        changed = True
    if changed:
        with _lock:
            try:
                CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
            except OSError:
                pass
    with _lock:
        return {name: cache.get(org, "") if org else "" for name, org in wanted.items()}
