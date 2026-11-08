from __future__ import annotations

import base64
import ctypes
import json
import re
import threading
import time
import urllib.error
import urllib.request
from ctypes import wintypes

PROVIDERS = {
    "ollama": {"title": "Ollama", "kind": "openai", "url": "http://127.0.0.1:11434/v1", "key": False, "local": True},
    "lmstudio": {"title": "LM Studio", "kind": "openai", "url": "http://127.0.0.1:1234/v1", "key": False, "local": True},
    "openai": {"title": "OpenAI", "kind": "openai", "url": "https://api.openai.com/v1", "key": True},
    "anthropic": {"title": "Anthropic (Claude)", "kind": "anthropic", "url": "https://api.anthropic.com/v1", "key": True},
    "gemini": {"title": "Google Gemini", "kind": "openai", "url": "https://generativelanguage.googleapis.com/v1beta/openai", "key": True},
    "openrouter": {"title": "OpenRouter", "kind": "openai", "url": "https://openrouter.ai/api/v1", "key": True},
    "custom": {"title": "Свой сервер (OpenAI API)", "kind": "openai", "url": "", "key": True, "optional_key": True},
}
USER_AGENT = "PIVEN-Companion/1.0"
config = {}
_models = {}
_errors = {}
_reasoning = {}
_kinds = {}
_next_try = {}
_gaps = {}
_lock = threading.Lock()
RETRY_WAITS = (1, 3)
RETRY_STATUSES = (408, 425, 500, 502, 503, 504, 529)
RECONNECT_FIRST, RECONNECT_LONGEST = 30, 300
KEY_PAGES = {
    "openai": "https://platform.openai.com/api-keys",
    "anthropic": "https://console.anthropic.com/settings/keys",
    "gemini": "https://aistudio.google.com/apikey",
    "openrouter": "https://openrouter.ai/settings/keys",
}


class KeyRejected(RuntimeError):
    """The service refused the key, so asking again will not help."""


class _Lost(RuntimeError):
    """The connection dropped before the service answered anything."""


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data, protect):
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    source = _Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
    result = _Blob()
    call = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not call(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(result)):
        raise OSError("DPAPI не смог обработать ключ")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)


def seal(key):
    key = str(key or "").strip()
    return base64.b64encode(_dpapi(key.encode("utf-8"), True)).decode("ascii") if key else ""


def unseal(stored):
    try:
        return _dpapi(base64.b64decode(stored), False).decode("utf-8") if stored else ""
    except Exception:
        return ""


def clean_key(text):
    """Keys get pasted with quotes, line breaks, «Bearer» or a whole NAME=value line."""
    text = re.sub(r"^\s*(?:export\s+)?[A-Za-z_]*KEY\s*[=:]\s*", "", str(text or ""))
    text = re.sub(r"^\s*(?:authorization\s*:\s*)?bearer\s+", "", text, flags=re.I)
    return re.sub(r"[^\x21-\x7e]", "", text).strip("\"'`")


def settings_of(provider):
    info = PROVIDERS[provider]
    saved = config.get(provider) or {}
    return {"enabled": bool(saved.get("enabled", False)), "url": str(saved.get("url") or info["url"]).rstrip("/"),
            "key": unseal(saved.get("key", ""))}


def is_provider_model(name):
    return str(name or "").split(":", 1)[0] in PROVIDERS and ":" in str(name or "")


def split(name):
    provider, model = str(name).split(":", 1)
    return provider, model


def _headers(provider, key):
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    if PROVIDERS[provider]["kind"] == "anthropic":
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    elif key:
        headers["Authorization"] = f"Bearer {key}"
    if provider == "openrouter":
        headers.update({"HTTP-Referer": "https://github.com/covriknapoly-glitch/piven-companion", "X-Title": "PIVEN Companion"})
    return headers


def _get(url, headers, timeout=15):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_error(error):
    try:
        text = error.read().decode("utf-8", "replace")
        try:
            body = json.loads(text)
            body = body[0] if isinstance(body, list) and body else body
            detail = body.get("error") if isinstance(body, dict) else body
            detail = detail.get("message") if isinstance(detail, dict) else detail
        except ValueError:
            detail = text.strip()[:300]
    except Exception:
        detail = ""
    if error.code in (401, 403):
        return f"ключ не подошёл ({error.code}){': ' + str(detail) if detail else ''}"
    if error.code == 429:
        return "превышен лимит запросов или закончились деньги на счёте" + (f" ({detail})" if detail else "")
    return f"HTTP {error.code}{': ' + str(detail) if detail else ''}"


_server_start_tried = {}


def _lms_path():
    import shutil
    from pathlib import Path
    candidate = Path.home() / ".lmstudio" / "bin" / "lms.exe"
    return str(candidate) if candidate.is_file() else shutil.which("lms")


def _start_lmstudio_server(url):
    import subprocess
    from urllib.parse import urlparse
    now = time.monotonic()
    if now - _server_start_tried.get("lmstudio", -1e9) < 60:
        return "сервер LM Studio не запущен"
    _server_start_tried["lmstudio"] = now
    lms = _lms_path()
    if not lms:
        return "сервер LM Studio не запущен: включи его в самой программе (раздел Developer → Start Server)"
    port = urlparse(url).port or 1234
    try:
        subprocess.run([lms, "server", "start", "--port", str(port)], capture_output=True, timeout=60,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as error:
        return f"не удалось запустить сервер LM Studio ({error})"
    return ""


def fetch_models(provider, key=None, start_server=True):
    options = settings_of(provider)
    info = PROVIDERS[provider]
    if key is not None:
        options["key"] = key
    if not options["url"]:
        raise RuntimeError("не указан адрес сервера")
    if info["key"] and not info.get("optional_key") and not options["key"]:
        raise KeyRejected("сохранённый ключ не расшифровать, введи его заново" if (config.get(provider) or {}).get("key") else "нужен API-ключ")
    local_timeout = 5 if info.get("local") else 15
    try:
        try:
            data = _get(options["url"] + "/models", _headers(provider, options["key"]), timeout=local_timeout)
        except (urllib.error.URLError, OSError) as error:
            if provider != "lmstudio" or not start_server or isinstance(error, urllib.error.HTTPError):
                raise
            problem = _start_lmstudio_server(options["url"])
            if problem:
                raise RuntimeError(problem) from error
            data = _get(options["url"] + "/models", _headers(provider, options["key"]), timeout=local_timeout)
    except urllib.error.HTTPError as error:
        message = _http_error(error)
        if error.code in (401, 403) or (error.code == 400 and re.search(r"api.?key", message, re.I)):
            raise KeyRejected(message) from error
        raise RuntimeError(message) from error
    except (urllib.error.URLError, OSError) as error:
        raise RuntimeError("программа не запущена" if info.get("local") else f"нет связи: {getattr(error, 'reason', error)}") from error
    items = data.get("data") if isinstance(data, dict) else data
    ids = [str(item.get("id") or "") for item in items or [] if isinstance(item, dict)]
    if provider == "openrouter":
        _reasoning[provider] = {str(item.get("id")): _openrouter_thinking(item) for item in items or [] if isinstance(item, dict)
                                and "reasoning" in (item.get("supported_parameters") or [])}
    if info.get("local"):
        ids = [i for i in ids if "embed" not in i.lower()]
    if provider == "openai":
        ids = [i for i in ids if i.startswith(("gpt-", "o1", "o3", "o4", "chatgpt")) and not any(
            word in i for word in ("audio", "realtime", "transcribe", "tts", "image", "search", "embedding"))]
    if provider == "gemini":
        ids = [i.split("/", 1)[1] if i.startswith("models/") else i for i in ids]
        ids = [i for i in ids if i.startswith("gemini") and "embedding" not in i and "image" not in i]
    return sorted({i for i in ids if i})


def _forget_trouble(provider):
    for store in (_errors, _kinds, _next_try, _gaps):
        store.pop(provider, None)


def refresh_one(provider, start_server=True):
    if not settings_of(provider)["enabled"]:
        with _lock:
            _models.pop(provider, None)
            _forget_trouble(provider)
        return False
    try:
        found = fetch_models(provider, start_server=start_server)
    except Exception as error:
        rejected = isinstance(error, KeyRejected)
        with _lock:
            if rejected:
                _models[provider] = []
            else:
                _models.setdefault(provider, [])
            _errors[provider], _kinds[provider] = str(error), "key" if rejected else "lost"
        return False
    with _lock:
        _models[provider] = found
        _forget_trouble(provider)
    return True


def reconnect(provider):
    """The user asked, so nothing waits for its turn."""
    with _lock:
        _next_try.pop(provider, None)
        _gaps.pop(provider, None)
    _server_start_tried.pop(provider, None)
    return refresh_one(provider)


def retry_lost():
    """Brings back services that dropped out. A refused key is left alone: only the user can fix it."""
    now = time.monotonic()
    with _lock:
        due = [provider for provider, kind in _kinds.items() if kind == "lost" and now >= _next_try.get(provider, 0)]
    healed = False
    for provider in due:
        if refresh_one(provider, start_server=False):
            healed = True
            continue
        with _lock:
            if _kinds.get(provider) == "lost":
                gap = min(_gaps.get(provider, RECONNECT_FIRST / 2) * 2, RECONNECT_LONGEST)
                _gaps[provider], _next_try[provider] = gap, time.monotonic() + gap
    return healed


def try_key(provider, key):
    """What the service said against this key; empty if it works or the service could not be reached to judge it."""
    try:
        fetch_models(provider, key=key, start_server=False)
    except KeyRejected as error:
        return str(error)
    except Exception:
        pass
    return ""


def refresh():
    workers = [threading.Thread(target=refresh_one, args=(provider,), daemon=True) for provider in PROVIDERS]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    return model_names()


def model_names():
    with _lock:
        return [f"{provider}:{model}" for provider, ids in _models.items() for model in ids]


SITES = {"ollama": "https://ollama.com/download", "lmstudio": "https://lmstudio.ai/download"}


def installed(provider):
    import os
    import shutil
    from pathlib import Path
    if not PROVIDERS[provider].get("local"):
        return True
    local, home = Path(os.environ.get("LOCALAPPDATA", "")), Path.home()
    places = {"ollama": [local / "Programs" / "Ollama" / "ollama.exe"],
              "lmstudio": [local / "Programs" / "LM Studio" / "LM Studio.exe", home / ".lmstudio" / "bin" / "lms.exe",
                           local / "Programs" / "lm-studio" / "LM Studio.exe"]}[provider]
    command = {"ollama": "ollama", "lmstudio": "lms"}[provider]
    return any(path.is_file() for path in places) or bool(shutil.which(command))


def status():
    rows = []
    for provider, info in PROVIDERS.items():
        options = settings_of(provider)
        saved = config.get(provider) or {}
        with _lock:
            count, error, kind = len(_models.get(provider, [])), _errors.get(provider, ""), _kinds.get(provider, "")
        rows.append({"id": provider, "title": info["title"], "local": bool(info.get("local")), "needsKey": bool(info["key"]),
                     "enabled": options["enabled"], "url": options["url"], "defaultUrl": info["url"],
                     "hasKey": bool(options["key"]), "models": count, "error": error, "errorKind": kind,
                     "keyEnd": options["key"][-4:] if len(options["key"]) >= 12 else "", "keyBroken": bool(saved.get("key")) and not options["key"],
                     "keyPage": KEY_PAGES.get(provider, ""),
                     "installed": installed(provider), "site": SITES.get(provider, "")})
    return rows


def _anthropic_messages(messages):
    system = "\n\n".join(str(item.get("content", "")) for item in messages if item.get("role") == "system")
    converted = []
    for message in messages:
        if message.get("role") == "system":
            continue
        blocks = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image}}
                  for image in message.get("images") or []]
        blocks.append({"type": "text", "text": str(message.get("content", "")) or " "})
        role = "assistant" if message.get("role") == "assistant" else "user"
        if converted and converted[-1]["role"] == role:
            converted[-1]["content"] += blocks
        else:
            converted.append({"role": role, "content": blocks})
    return system, converted


EFFORTS = ["low", "medium", "high", "xhigh", "max"]
EFFORT_ORDER = ["minimal", "low", "medium", "high", "xhigh", "max"]
THINKING_FIELDS = ("reasoning_effort", "reasoning", "chat_template_kwargs", "output_config")
LEVEL_WORDS = r"none|minimal|low|medium|high|xhigh|max"
learned = {}
on_learned = None
CLAUDE_BUDGETS = {"low": 2048, "medium": 8192, "high": 24576}
_capabilities = {}


def _openrouter_thinking(item):
    reasoning = item.get("reasoning") if isinstance(item.get("reasoning"), dict) else {}
    efforts = [level for level in EFFORT_ORDER if level in (reasoning.get("supported_efforts") or [])]
    can_stop = not reasoning.get("mandatory")
    if efforts:
        return ([False] if can_stop else []) + efforts, reasoning.get("default_effort") or efforts[len(efforts) // 2]
    return ([True, False], bool(reasoning.get("default_enabled", True))) if can_stop else ([], True)


def _openai_thinking(model):
    if re.match(r"o\d", model) or model.startswith("gpt-oss"):
        return ["low", "medium", "high"], "medium"
    match = re.match(r"gpt-(\d+)", model)
    if not match or int(match.group(1)) < 5:
        return None
    if "-pro" in model:
        return ["medium", "high", "xhigh"], "high"
    if "codex" in model:
        return ["low", "medium", "high", "xhigh"], "medium"
    if model.startswith(("gpt-5-", "gpt-5.0")) or model == "gpt-5":
        return ["minimal", "low", "medium", "high"], "medium"
    if model.startswith("gpt-5.1"):
        return [False, "low", "medium", "high"], False
    return [False, "low", "medium", "high", "xhigh"], False


def _gemini_thinking(model):
    if any(word in model for word in ("tts", "image", "banana", "embedding", "aqa")):
        return None
    match = re.match(r"gemini-(\d+(?:\.\d+)?)", model)
    generation = float(match.group(1)) if match else 0.0
    if not model.startswith("gemini-") or (match and generation < 2.5):
        return None
    if generation == 2.5 and "pro" not in model:
        return [False, "low", "medium", "high"], "medium"
    if generation == 3 and "pro" in model:
        return ["low", "high"], "high"
    return ["low", "medium", "high"], "high" if "pro" in model else "medium"


def _claude_generation(model):
    import re
    match = re.match(r"claude-([a-z]+)-(\d+)(?:-(\d)(?!\d))?", model)
    if match:
        return match.group(1), int(match.group(2)) + int(match.group(3) or 0) / 10
    match = re.match(r"claude-(\d)(?:-(\d)(?!\d))?-(opus|sonnet|haiku)", model)
    if match:
        return match.group(3), int(match.group(1)) + int(match.group(2) or 0) / 10
    return "", 0.0


def _claude_thinking(model):
    family, version = _claude_generation(model)
    if family in ("fable", "mythos") or (family == "opus" and version >= 5.5):
        return EFFORTS, "medium" if family == "opus" else "high", "adaptive"
    if family == "haiku" and version >= 5.5:
        return [False] + EFFORTS, "medium", "adaptive"
    if version >= 5:
        return [False] + EFFORTS, "high", "adaptive"
    if version >= 4.7:
        return [False] + EFFORTS, False, "adaptive"
    if version >= 4.6:
        return [False, "low", "medium", "high", "max"], False, "adaptive"
    if family and version >= 3.7:
        return [False, "low", "medium", "high"], False, "budget"
    return [], None, ""


def _local_thinking(provider, model):
    name = f"{provider}:{model}"
    if name in _capabilities:
        return _capabilities[name]
    base = settings_of(provider)["url"].rsplit("/v1", 1)[0]
    result = [], None
    if provider == "ollama":
        request = urllib.request.Request(base + "/api/show", data=json.dumps({"model": model}).encode("utf-8"),
                                         headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=5) as response:
            capabilities = json.loads(response.read().decode("utf-8")).get("capabilities") or []
        if "thinking" in capabilities:
            result = (["low", "medium", "high"], "medium") if "gpt-oss" in model else ([True, False], True)
    else:
        for item in _get(base + "/api/v1/models", {"User-Agent": USER_AGENT}, timeout=5).get("models") or []:
            reasoning = (item.get("capabilities") or {}).get("reasoning") if item.get("key") == model else None
            if isinstance(reasoning, dict):
                named = {"off": False, "on": True}
                values = [named.get(option, option) for option in reasoning.get("allowed_options") or []]
                result = values, named.get(reasoning.get("default"), reasoning.get("default"))
    _capabilities[name] = result
    return result


def levels_from_error(text, known):
    """What a service's refusal says about a model: the whole list of levels, or one level to drop from what we believed."""
    text = re.sub(r"\([^)]*\)", "", str(text or ""))
    listed = re.search(r"(?i)\b(?:valid|supported|allowed|accepted)[\w\s]*?(?:values?|levels?|options?|efforts?|types?)[\w\s]*?(?:are|is|include|:)\s*:?\s*([^.\n]+)", text)
    if listed:
        words = [word.lower() for word in re.findall(r"[A-Za-z]+", listed.group(1)) if word.lower() not in ("and", "or")]
        if len(words) >= 2 and all(re.fullmatch(LEVEL_WORDS, word) for word in words):
            return ([False] if "none" in words else []) + [level for level in EFFORT_ORDER if level in words]
    single = re.search(rf"(?i)(?:level|effort|value)\s*:?\s*['\"`]?({LEVEL_WORDS})['\"`]?\.?\s+(?:is\s+)?(?:not supported|unsupported|invalid)", text) \
        or re.search(rf"(?i)(?:unsupported|invalid)\s+(?:value|level|effort)\s*:?\s*['\"`]?({LEVEL_WORDS})\b", text)
    if single:
        word = single.group(1).lower()
        rejected = False if word == "none" else word
        if rejected in known:
            return [value for value in known if value != rejected]
    return None


def _learn(name, think, text):
    known = thinking_modes(name)[0]
    values = levels_from_error(text, known) if think not in (None, "__auto__") else None
    if not values or values == known:
        return
    learned[name] = values
    if on_learned:
        on_learned(name, values)


def thinking_modes(name):
    values, default = _known_thinking(name)
    if name not in learned:
        return values, default
    values = learned[name]
    named = [value for value in values if value is not False]
    return values, default if default in values else ("medium" if "medium" in values else named[len(named) // 2] if named else False)


def _known_thinking(name):
    provider, model = split(name)
    lowered = model.lower()
    if provider == "anthropic":
        values, default, _ = _claude_thinking(model)
        return values, default
    if provider == "openai":
        return _openai_thinking(lowered) or ([], None)
    if provider == "gemini":
        return _gemini_thinking(lowered) or ([], None)
    if provider == "openrouter":
        return _reasoning.get(provider, {}).get(model, ([], None))
    if provider in ("ollama", "lmstudio"):
        return _local_thinking(provider, model)
    return _openai_thinking(lowered) or _gemini_thinking(lowered) or ([True, False], True)


def _apply_thinking(provider, model, payload, think):
    if think in (None, "__auto__"):
        return
    try:
        values, _ = thinking_modes(f"{provider}:{model}")
    except Exception:
        return
    if think not in values:
        return
    if provider == "openrouter":
        payload["reasoning"] = {"enabled": think} if isinstance(think, bool) else {"effort": think}
    elif provider == "lmstudio":
        payload["reasoning"] = {True: "on", False: "off"}.get(think, think)
        if isinstance(think, bool):
            payload["chat_template_kwargs"] = {"enable_thinking": think}
        else:
            payload["reasoning_effort"] = think
    elif provider == "ollama":
        if think is False:
            payload["reasoning_effort"] = "none"
        elif think is not True:
            payload["reasoning_effort"] = think
    elif provider == "custom" and isinstance(think, bool):
        payload["chat_template_kwargs"] = {"enable_thinking": think}
        if think is False:
            payload["reasoning_effort"] = "none"
    elif think is False:
        payload["reasoning_effort"] = "none"
    elif isinstance(think, str):
        payload["reasoning_effort"] = think


def _open_stream(url, payload, headers, timeout, name=None, think=None):
    """A level the service turned out not to accept should not cost the user the answer, and is not offered again."""
    def send(body):
        request = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=headers)
        return urllib.request.urlopen(request, timeout=timeout)
    try:
        return send(payload)
    except urllib.error.HTTPError as error:
        plain = {key: value for key, value in payload.items() if key not in THINKING_FIELDS}
        if error.code != 400 or len(plain) == len(payload):
            raise
        if name:
            try:
                _learn(name, think, error.read().decode("utf-8", "replace"))
            except Exception:
                pass
        return send(plain)


def _ask(name, messages, timeout=600, on_status=None, on_thinking=None, cancel_event=None, on_response=None,
         on_text=None, overrides=None, sampling=None, tools=None, tool_calls=None, think="__auto__"):
    provider, model = split(name)
    options = settings_of(provider)
    info = PROVIDERS[provider]
    overrides, sampling = dict(overrides or {}), dict(sampling or {})
    from app.models import llama
    if info["kind"] == "anthropic":
        system, converted = _anthropic_messages(messages)
        payload = {"model": model, "messages": converted, "stream": True,
                   "max_tokens": int(overrides.pop("max_tokens", 0) or sampling.get("max_tokens") or 8192)}
        if system:
            payload["system"] = system
        family, version = _claude_generation(model)
        values, default, style = _claude_thinking(model)
        level = default if think in (None, "__auto__") else think
        thinking = False
        if think is False and False in values:
            payload["thinking"] = {"type": "between_tools" if family == "sonnet" and version >= 5.5 else "disabled"}
        elif style == "budget" and level in CLAUDE_BUDGETS:
            budget = CLAUDE_BUDGETS[level]
            payload["thinking"] = {"type": "enabled", "budget_tokens": budget}
            payload["max_tokens"] = max(payload["max_tokens"], budget + 4096)
            thinking = True
        elif style == "adaptive" and level:
            payload["thinking"] = {"type": "adaptive", "display": "summarized"}
            if think not in (None, "__auto__"):
                payload["output_config"] = {"effort": think}
            thinking = True
        temperature = overrides.pop("temperature", sampling.get("temperature"))
        if temperature is not None and not thinking and family not in ("fable", "mythos") and version < 4.7:
            payload["temperature"] = min(1.0, float(temperature))
        url = options["url"] + "/messages"
    else:
        payload = {"model": model, "messages": llama._to_openai(messages), "stream": True}
        if tools:
            payload["tools"] = tools
        if provider == "openai" and model.lower().startswith(("o1", "o3", "o4", "gpt-5")):
            for key in ("temperature", "top_p", "presence_penalty", "frequency_penalty"):
                sampling.pop(key, None); overrides.pop(key, None)
        for key in ("temperature", "top_p", "presence_penalty", "frequency_penalty", "seed"):
            if key in sampling and not (key.endswith("_penalty") and not sampling[key]):
                payload[key] = sampling[key]
        if provider in ("ollama", "lmstudio", "openrouter", "custom"):
            for key in ("top_k", "min_p", "repeat_penalty"):
                if key in sampling:
                    payload[key] = sampling[key]
        if sampling.get("max_tokens", -1) > 0:
            payload["max_tokens"] = sampling["max_tokens"]
        _apply_thinking(provider, model, payload, think)
        payload.update(overrides)
        url = options["url"] + "/chat/completions"
    if on_status:
        on_status(f"Запрос к {info['title']}")
    parts, thoughts, stage, last, calls = [], [], None, 0.0, {}
    try:
        with _open_stream(url, payload, _headers(provider, options["key"]), timeout, name, think) as response:
            if on_response:
                on_response(response)
            try:
                for raw in response:
                    if cancel_event is not None and cancel_event.is_set():
                        raise InterruptedError("Запрос прерван пользователем")
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    text, thought = "", ""
                    if info["kind"] == "anthropic":
                        delta = chunk.get("delta") or {}
                        text = delta.get("text", "") if delta.get("type") == "text_delta" else ""
                        thought = delta.get("thinking", "") if delta.get("type") == "thinking_delta" else ""
                        if chunk.get("type") == "error":
                            raise RuntimeError(str((chunk.get("error") or {}).get("message") or chunk))
                    else:
                        choices = chunk.get("choices") or []
                        delta = (choices[0].get("delta") or {}) if choices else {}
                        text = delta.get("content") or ""
                        thought = delta.get("reasoning_content") or delta.get("reasoning") or ""
                        llama.collect_tool_calls(delta, calls)
                    if thought:
                        thoughts.append(thought)
                        if on_thinking and time.monotonic() - last >= 0.12:
                            on_thinking("".join(thoughts)); last = time.monotonic()
                        if stage != "thinking" and on_status:
                            on_status("Модель обдумывает ответ"); stage = "thinking"
                    if text:
                        parts.append(text)
                        if on_text:
                            on_text("".join(parts))
                        if stage != "generating" and on_status:
                            on_status("Модель пишет ответ"); stage = "generating"
            finally:
                if on_response:
                    on_response(None)
    except urllib.error.HTTPError as error:
        reason = _http_error(error)
        if error.code == 401:
            with _lock:
                _errors[provider], _kinds[provider] = reason, "key"
        if error.code in RETRY_STATUSES and not (parts or thoughts or calls):
            raise _Lost(f"{info['title']}: {reason}") from error
        raise RuntimeError(f"{info['title']}: {reason}") from error
    except urllib.error.URLError as error:
        if not isinstance(error.reason, TimeoutError) and not (parts or thoughts or calls):
            raise _Lost(f"{info['title']}: нет связи ({error.reason})") from error
        raise RuntimeError(f"{info['title']}: нет связи ({error.reason})") from error
    except (AttributeError, ValueError, OSError) as error:
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Запрос прерван пользователем") from error
        if isinstance(error, OSError) and not isinstance(error, TimeoutError) and not (parts or thoughts or calls):
            raise _Lost(f"{info['title']}: связь оборвалась ({error})") from error
        raise RuntimeError(f"{info['title']}: связь оборвалась ({error})") from error
    if thoughts and on_thinking:
        on_thinking("".join(thoughts))
    if tool_calls is not None and info["kind"] != "anthropic":
        tool_calls.extend(llama.finished_tool_calls(calls))
    return "".join(parts).strip()


def chat(name, messages, timeout=600, on_status=None, on_thinking=None, cancel_event=None, on_response=None,
         on_text=None, overrides=None, sampling=None, tools=None, tool_calls=None, think="__auto__"):
    """A dropped connection costs nothing while the service has not answered yet, so it is tried again."""
    def ask():
        return _ask(name, messages, timeout, on_status, on_thinking, cancel_event, on_response, on_text,
                    overrides, sampling, tools, tool_calls, think)
    for wait in RETRY_WAITS:
        try:
            return ask()
        except _Lost:
            if on_status:
                on_status("Связь оборвалась, подключаюсь снова")
            if cancel_event is None:
                time.sleep(wait)
            elif cancel_event.wait(wait):
                raise InterruptedError("Запрос прерван пользователем")
    return ask()
