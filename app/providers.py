"""Chat models outside the built-in llama.cpp: other local programs (Ollama, LM Studio) and cloud services by
the user's own API key (OpenAI, Anthropic, Google Gemini, OpenRouter, any OpenAI-compatible server).

Their models appear in the model list as "<provider>:<model id>", e.g. "ollama:qwen3:8b" or
"anthropic:claude-sonnet-4-5". Keys are kept encrypted with Windows DPAPI (only this Windows user can read
them) and are sent only to the provider they belong to.
"""
from __future__ import annotations

import base64
import ctypes
import json
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
config = {}            # settings["providers"]: {id: {"enabled": bool, "url": str, "key": encrypted str}}
_models = {}           # {provider: [model ids]} from the last refresh
_errors = {}           # {provider: error text} from the last refresh
_reasoning = {}        # {provider: {model ids that accept a reasoning setting}} where the model list says so (OpenRouter)
_lock = threading.Lock()


# ---------- keys at rest: Windows DPAPI ----------
class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data, protect):
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    source = _Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
    result = _Blob()
    call = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not call(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(result)):  # CRYPTPROTECT_UI_FORBIDDEN
        raise OSError("DPAPI не смог обработать ключ")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)


def seal(key):
    """An API key as stored in settings (empty stays empty)."""
    key = str(key or "").strip()
    return base64.b64encode(_dpapi(key.encode("utf-8"), True)).decode("ascii") if key else ""


def unseal(stored):
    try:
        return _dpapi(base64.b64decode(stored), False).decode("utf-8") if stored else ""
    except Exception:
        return ""


# ---------- configuration ----------
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
            body = body[0] if isinstance(body, list) and body else body  # Gemini wraps the error in a list
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


_server_start_tried = {}   # {provider: time of the last attempt to start its server}


def _lms_path():
    """LM Studio's command-line tool, which can start its local server without opening the window."""
    import shutil
    from pathlib import Path
    candidate = Path.home() / ".lmstudio" / "bin" / "lms.exe"
    return str(candidate) if candidate.is_file() else shutil.which("lms")


def _start_lmstudio_server(url):
    """Start LM Studio's local server with `lms server start` on the port of the configured address.
    Returns "" when it is running afterwards, otherwise a readable reason. Tried at most once a minute."""
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


def fetch_models(provider):
    """Model ids the provider offers now (raises with a readable reason)."""
    options = settings_of(provider)
    info = PROVIDERS[provider]
    if not options["url"]:
        raise RuntimeError("не указан адрес сервера")
    if info["key"] and not info.get("optional_key") and not options["key"]:
        raise RuntimeError("нужен API-ключ")
    local_timeout = 5 if info.get("local") else 15
    try:
        try:
            data = _get(options["url"] + "/models", _headers(provider, options["key"]), timeout=local_timeout)
        except (urllib.error.URLError, OSError) as error:
            if provider != "lmstudio" or isinstance(error, urllib.error.HTTPError):
                raise
            # LM Studio is installed but its server is off: start it, as the user switched this integration on.
            problem = _start_lmstudio_server(options["url"])
            if problem:
                raise RuntimeError(problem) from error
            data = _get(options["url"] + "/models", _headers(provider, options["key"]), timeout=local_timeout)
    except urllib.error.HTTPError as error:
        raise RuntimeError(_http_error(error)) from error
    except (urllib.error.URLError, OSError) as error:
        raise RuntimeError("программа не запущена" if info.get("local") else f"нет связи: {getattr(error, 'reason', error)}") from error
    items = data.get("data") if isinstance(data, dict) else data
    ids = [str(item.get("id") or "") for item in items or [] if isinstance(item, dict)]
    if provider == "openrouter":
        _reasoning[provider] = {str(item.get("id")) for item in items or [] if isinstance(item, dict)
                                and "reasoning" in (item.get("supported_parameters") or [])}
    if info.get("local"):  # embedding models cannot chat; they only clutter the list
        ids = [i for i in ids if "embed" not in i.lower()]
    if provider == "openai":  # only chat models, not embeddings, images, audio or moderation
        ids = [i for i in ids if i.startswith(("gpt-", "o1", "o3", "o4", "chatgpt")) and not any(
            word in i for word in ("audio", "realtime", "transcribe", "tts", "image", "search", "embedding"))]
    if provider == "gemini":
        ids = [i.split("/", 1)[1] if i.startswith("models/") else i for i in ids]
        ids = [i for i in ids if i.startswith("gemini") and "embedding" not in i and "image" not in i]
    return sorted({i for i in ids if i})


def refresh():
    """Ask every enabled provider for its models; returns the "<provider>:<model>" names."""
    names = []
    for provider in PROVIDERS:
        if not settings_of(provider)["enabled"]:
            with _lock:
                _models.pop(provider, None); _errors.pop(provider, None)
            continue
        try:
            found = fetch_models(provider)
            with _lock:
                _models[provider] = found; _errors.pop(provider, None)
        except Exception as error:
            with _lock:
                _models[provider] = []; _errors[provider] = str(error)
    with _lock:
        for provider, ids in _models.items():
            names += [f"{provider}:{model}" for model in ids]
    return names


def model_names():
    with _lock:
        return [f"{provider}:{model}" for provider, ids in _models.items() for model in ids]


SITES = {"ollama": "https://ollama.com/download", "lmstudio": "https://lmstudio.ai/download"}


def installed(provider):
    """Whether a local program is on this computer (its usual install folders or PATH); cloud services: True."""
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
    """For the settings page: every provider with its options (the key only as "set or not") and last result."""
    rows = []
    for provider, info in PROVIDERS.items():
        options = settings_of(provider)
        with _lock:
            count, error = len(_models.get(provider, [])), _errors.get(provider, "")
        rows.append({"id": provider, "title": info["title"], "local": bool(info.get("local")), "needsKey": bool(info["key"]),
                     "enabled": options["enabled"], "url": options["url"], "defaultUrl": info["url"],
                     "hasKey": bool(options["key"]), "models": count, "error": error,
                     "installed": installed(provider), "site": SITES.get(provider, "")})
    return rows


# ---------- answers ----------
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
        if converted and converted[-1]["role"] == role:  # the API wants user and assistant turns to alternate
            converted[-1]["content"] += blocks
        else:
            converted.append({"role": role, "content": blocks})
    return system, converted


# ---------- thinking levels ----------
EFFORTS = ["low", "medium", "high", "xhigh", "max"]
CLAUDE_BUDGETS = {"low": 2048, "medium": 8192, "high": 24576}   # thinking tokens for Claude models before 4.6
_capabilities = {}     # {"provider:model": (values, default)} asked from Ollama and LM Studio


def _claude_generation(model):
    """("opus" | "sonnet" | "haiku" | "fable" | "mythos", version) from a Claude model id, ("", 0) when unknown."""
    import re
    match = re.match(r"claude-(opus|sonnet|haiku|fable|mythos)-(\d+)(?:-(\d)(?!\d))?", model)
    if match:
        return match.group(1), int(match.group(2)) + int(match.group(3) or 0) / 10
    match = re.match(r"claude-(\d)(?:-(\d)(?!\d))?-(opus|sonnet|haiku)", model)
    if match:
        return match.group(3), int(match.group(1)) + int(match.group(2) or 0) / 10
    return "", 0.0


def _claude_thinking(model):
    """(values, default, style) of a Claude model: style "adaptive" (effort levels), "budget" (budget_tokens)
    or "" when it does not think. False in values means it can be switched off."""
    family, version = _claude_generation(model)
    if family in ("fable", "mythos") or (family == "opus" and version >= 5.5):   # thinking is always on
        return EFFORTS, "medium" if family == "opus" else "high", "adaptive"
    if family == "haiku" and version >= 5.5:
        return [False] + EFFORTS, "medium", "adaptive"
    if version >= 5:
        return [False] + EFFORTS, "high", "adaptive"
    if version >= 4.7:   # adaptive thinking only when asked for
        return [False] + EFFORTS, False, "adaptive"
    if version >= 4.6:
        return [False, "low", "medium", "high", "max"], False, "adaptive"
    if family and version >= 3.7:
        return [False, "low", "medium", "high"], False, "budget"
    return [], None, ""


def _local_thinking(provider, model):
    """What Ollama or LM Studio report about a model's reasoning, cached; raises when the program is off."""
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
    else:   # LM Studio: capabilities.reasoning.allowed_options, e.g. ["off", "on"] or ["low", "medium", "high"]
        for item in _get(base + "/api/v1/models", {"User-Agent": USER_AGENT}, timeout=5).get("models") or []:
            reasoning = (item.get("capabilities") or {}).get("reasoning") if item.get("key") == model else None
            if isinstance(reasoning, dict):
                named = {"off": False, "on": True}
                values = [named.get(option, option) for option in reasoning.get("allowed_options") or []]
                result = values, named.get(reasoning.get("default"), reasoning.get("default"))
    _capabilities[name] = result
    return result


def thinking_modes(name):
    """(values, default) for an integration model's thinking switch, like llama_backend.thinking_modes."""
    provider, model = split(name)
    lowered = model.lower()
    if provider == "anthropic":
        values, default, _ = _claude_thinking(model)
        return values, default
    if provider == "openai" and lowered.startswith(("o1", "o3", "o4", "gpt-5", "gpt-oss")):
        return ["low", "medium", "high"], "medium"
    if provider == "gemini" and lowered.startswith(("gemini-2.5", "gemini-3")):
        return ["low", "medium", "high"], "high"
    if provider == "openrouter" and model in _reasoning.get(provider, ()):
        return [False, "low", "medium", "high"], "medium"
    if provider in ("ollama", "lmstudio"):
        return _local_thinking(provider, model)
    return [], None


def _apply_thinking(provider, model, payload, think):
    """Put the chosen thinking level into an OpenAI-style request, in the form this provider reads. A level the
    model does not offer (a quick service request asks every model for no thinking) is not sent."""
    if think in (None, "__auto__"):
        return
    try:
        values, _ = thinking_modes(f"{provider}:{model}")
    except Exception:
        return
    if think not in values:
        return
    if provider == "openrouter":
        payload["reasoning"] = {"enabled": False} if think is False else {"effort": think}
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
    elif isinstance(think, str):   # OpenAI, Gemini
        payload["reasoning_effort"] = think


def chat(name, messages, timeout=600, on_status=None, on_thinking=None, cancel_event=None, on_response=None,
         on_text=None, overrides=None, sampling=None, tools=None, tool_calls=None, think="__auto__"):
    """Stream one answer from a provider's model; returns the final text (same contract as llama_backend.chat)."""
    provider, model = split(name)
    options = settings_of(provider)
    info = PROVIDERS[provider]
    overrides, sampling = dict(overrides or {}), dict(sampling or {})
    import llama_backend
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
            # Claude Sonnet 5.5 turns thinking off with "between_tools"; "disabled" is refused there
            payload["thinking"] = {"type": "between_tools" if family == "sonnet" and version >= 5.5 else "disabled"}
        elif style == "budget" and level in CLAUDE_BUDGETS:
            budget = CLAUDE_BUDGETS[level]
            payload["thinking"] = {"type": "enabled", "budget_tokens": budget}
            payload["max_tokens"] = max(payload["max_tokens"], budget + 4096)
            thinking = True
        elif style == "adaptive" and level:
            payload["thinking"] = {"type": "adaptive", "display": "summarized"}   # readable reasoning in the panel
            if think not in (None, "__auto__"):
                payload["output_config"] = {"effort": think}
            thinking = True
        # Claude 4.7 and later accept only the default sampling; with thinking on no model takes a temperature
        temperature = overrides.pop("temperature", sampling.get("temperature"))
        if temperature is not None and not thinking and family not in ("fable", "mythos") and version < 4.7:
            payload["temperature"] = min(1.0, float(temperature))
        url = options["url"] + "/messages"
    else:
        payload = {"model": model, "messages": llama_backend._to_openai(messages), "stream": True}
        if tools:
            payload["tools"] = tools
        if provider == "openai" and model.lower().startswith(("o1", "o3", "o4", "gpt-5")):
            # OpenAI's reasoning models accept only the default sampling
            for key in ("temperature", "top_p", "presence_penalty", "frequency_penalty"):
                sampling.pop(key, None); overrides.pop(key, None)
        for key in ("temperature", "top_p", "presence_penalty", "frequency_penalty", "seed"):
            # zero penalties are the default anyway, and Gemini refuses the field outright on its newer models
            if key in sampling and not (key.endswith("_penalty") and not sampling[key]):
                payload[key] = sampling[key]
        if provider in ("ollama", "lmstudio", "openrouter", "custom"):  # these accept llama.cpp-style sampling too
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
    request = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                     headers=_headers(provider, options["key"]))
    parts, thoughts, stage, last, calls = [], [], None, 0.0, {}
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
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
                        llama_backend.collect_tool_calls(delta, calls)
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
        raise RuntimeError(f"{info['title']}: {_http_error(error)}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"{info['title']}: нет связи ({error.reason})") from error
    except (AttributeError, ValueError, OSError) as error:  # the stop button closed the connection
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Запрос прерван пользователем") from error
        raise RuntimeError(f"{info['title']}: связь оборвалась ({error})") from error
    if thoughts and on_thinking:
        on_thinking("".join(thoughts))
    if tool_calls is not None and info["kind"] != "anthropic":
        tool_calls.extend(llama_backend.finished_tool_calls(calls))
    return "".join(parts).strip()
