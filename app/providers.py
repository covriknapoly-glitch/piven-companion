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
        body = json.loads(error.read().decode("utf-8", "replace"))
        detail = body.get("error")
        detail = detail.get("message") if isinstance(detail, dict) else detail
    except Exception:
        detail = ""
    if error.code in (401, 403):
        return f"ключ не подошёл ({error.code}){': ' + str(detail) if detail else ''}"
    if error.code == 429:
        return "превышен лимит запросов или закончились деньги на счёте"
    return f"HTTP {error.code}{': ' + str(detail) if detail else ''}"


def fetch_models(provider):
    """Model ids the provider offers now (raises with a readable reason)."""
    options = settings_of(provider)
    info = PROVIDERS[provider]
    if not options["url"]:
        raise RuntimeError("не указан адрес сервера")
    if info["key"] and not info.get("optional_key") and not options["key"]:
        raise RuntimeError("нужен API-ключ")
    try:
        data = _get(options["url"] + "/models", _headers(provider, options["key"]), timeout=5 if info.get("local") else 15)
    except urllib.error.HTTPError as error:
        raise RuntimeError(_http_error(error)) from error
    except (urllib.error.URLError, OSError) as error:
        raise RuntimeError("программа не запущена" if info.get("local") else f"нет связи: {getattr(error, 'reason', error)}") from error
    items = data.get("data") if isinstance(data, dict) else data
    ids = [str(item.get("id") or "") for item in items or [] if isinstance(item, dict)]
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


def chat(name, messages, timeout=600, on_status=None, on_thinking=None, cancel_event=None, on_response=None,
         on_text=None, overrides=None, sampling=None, tools=None, tool_calls=None):
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
        if "temperature" in sampling or "temperature" in overrides:
            payload["temperature"] = min(1.0, float(overrides.pop("temperature", sampling.get("temperature", 0.7))))
        url = options["url"] + "/messages"
    else:
        payload = {"model": model, "messages": llama_backend._to_openai(messages), "stream": True}
        if tools:
            payload["tools"] = tools
        for key in ("temperature", "top_p", "presence_penalty", "frequency_penalty", "seed"):
            if key in sampling:
                payload[key] = sampling[key]
        if provider in ("ollama", "lmstudio", "openrouter", "custom"):  # these accept llama.cpp-style sampling too
            for key in ("top_k", "min_p", "repeat_penalty"):
                if key in sampling:
                    payload[key] = sampling[key]
        if sampling.get("max_tokens", -1) > 0:
            payload["max_tokens"] = sampling["max_tokens"]
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
