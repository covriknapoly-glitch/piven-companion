"""Image, video, speech and transcription endpoints."""
from __future__ import annotations

import base64
import hashlib
import io
import wave
import json
import urllib.error
import urllib.request
import uuid
import mimetypes
import re
import time
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.models import integrations


VISUAL_MODELS = {
    "openrouter": {
        "image": {"bytedance-seed/seedream-4.5": "Seedream 4.5"},
        "video": {"google/veo-3.1": "Veo 3.1", "bytedance/seedance-2.0": "Seedance 2.0"},
    },
    "gemini": {
        "image": {"gemini-3.1-flash-image": "Nano Banana 2", "gemini-3-pro-image-preview": "Nano Banana Pro",
                  "gemini-2.5-flash-image": "Nano Banana"},
        "video": {"gemini-omni-1.2-flash": "Gemini Omni 1.2 Flash"},
    },
    "openai": {"image": {"gpt-image-2": "GPT Image 2", "gpt-image-2.6-flare": "GPT Image 2.6 Flare",
                         "gpt-image-2.6-sunburst": "GPT Image 2.6 Sunburst"}},
    "custom": {},
    "runway": {
        "image": {"gen4_image": "Gen-4 Image", "gen4_image_turbo": "Gen-4 Image Turbo",
                  "ideogram_4_5": "Ideogram 4.5", "gemini_image3.1_flash": "Nano Banana 2"},
        "video": {"gen4.5": "Gen-4.5", "gen4_turbo": "Gen-4 Turbo (Image-to-Video)"},
    },
    "higgsfield": {
        "image": {"higgsfield-ai/soul/v2/standard": "Soul 2", "alibaba/qwen-image-3/text-to-image": "Qwen Image 3",
                  "recraft/v4.1/text-to-image": "Recraft V4.1",
                  "bytedance/seedream/v5.0/pro/text-to-image": "Seedream 5.0 Pro"},
        "video": {"bytedance/seedance-2.0": "Seedance 2.0"},
    },
    "fal": {
        "image": {"fal-ai/flux/schnell": "FLUX.1 Schnell", "fal-ai/flux/dev": "FLUX.1 Dev"},
        "video": {"fal-ai/kling-video/v2.5-turbo/pro": "Kling 2.5 Turbo Pro"},
    },
}


_RUNWAY_SPEC = "https://raw.githubusercontent.com/runwayml/openapi/main/openapi.json"
_RUNWAY_OPERATIONS = ("text_to_image", "text_to_video", "image_to_video")
_LIVE_VISUAL = ("runway", "openrouter", "openai", "gemini", "fal", "higgsfield")
_FAL_CATALOG = "https://api.fal.ai/v1/models"
_HIGGSFIELD_SPEC = "https://docs.higgsfield.ai/docs/openapi.json"
_ENDPOINT_ID = re.compile(r"[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_.-]+)+\Z")
_visual_cache = {}
_visual_lock = threading.Lock()
_CATALOG_TTL = 600


def _schema_types(schema):
    yield schema
    for child in (*schema.get("oneOf", ()), *schema.get("anyOf", ())):
        yield from _schema_types(child)


def _runway_required(field, schema, *, image):
    preference = {
        "ratio": ("1024:1024", "auto", "auto_1k") if image else ("1280:720", "16:9", "auto_720p"),
        "duration": (5, 4, 6),
    }[field]
    for choice in _schema_types(schema):
        values = choice.get("enum")
        if values:
            return next((value for value in preference if value in values), values[0])
        if "const" in choice:
            return choice["const"]
        if "default" in choice:
            return choice["default"]
        if field == "duration" and choice.get("type") in ("integer", "number"):
            duration = max(5, choice.get("minimum", 5))
            return min(duration, choice.get("maximum", duration))
    raise ValueError(f"Unsupported Runway field: {field}")


def _runway_schema(spec):
    operations = {}
    for operation in _RUNWAY_OPERATIONS:
        schema = spec["paths"]["/v1/" + operation]["post"]["requestBody"]["content"]["application/json"]["schema"]
        models = {}
        for variant in schema.get("oneOf", ()):
            fields = variant.get("properties", {})
            model = fields.get("model", {}).get("const")
            required = set(variant.get("required", ()))
            if not model or "promptText" not in fields or model.endswith("_vector"):
                continue
            image_input = operation == "image_to_video"
            expected = {"model", "promptText", "ratio", "duration"}
            if image_input:
                expected.add("promptImage")
            if required - expected or (image_input and "promptImage" not in fields):
                continue
            try:
                defaults = {field: _runway_required(field, fields[field], image=operation == "text_to_image")
                            for field in sorted(required & {"ratio", "duration"})}
            except ValueError:
                continue
            image_array = False
            if image_input:
                types = tuple(_schema_types(fields["promptImage"]))
                if not any(item.get("type") == "string" and (not item.get("pattern") or "data:image" in item["pattern"])
                           for item in types):
                    if not any(item.get("type") == "array" and item.get("minItems", 1) <= 1
                               and set(item.get("items", {}).get("properties", {})) >= {"uri", "position"}
                               for item in types):
                        continue
                    image_array = True
            models[model] = (defaults, fields["promptText"].get("maxLength"), image_array)
        operations[operation] = models
    if not operations["text_to_image"] or not operations["text_to_video"]:
        raise ValueError("Runway specification has no compatible models.")
    return operations


def _model_pages(fetch, query, cursor_key, next_key, rows_key):
    seen = set()
    while True:
        page = fetch(urllib.parse.urlencode(query))
        yield from page[rows_key]
        cursor = page.get(next_key)
        if not cursor or cursor in seen:
            return
        seen.add(cursor)
        query[cursor_key] = cursor


def _fal_catalog(query):
    request = urllib.request.Request(_FAL_CATALOG + "?" + query, headers={"User-Agent": integrations.USER_AGENT})
    options = integrations.settings_of("fal")
    if options["enabled"] and options["key"] and options["url"] == integrations.PROVIDERS["fal"]["url"]:
        request.add_unredirected_header("Authorization", "Key " + options["key"])
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code != 429:
            raise
        with error:
            delay = integrations.retry_delay(error, "") or 1
        if delay > 3:
            raise
        time.sleep(max(0, delay))
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.load(response)


def _fal_models():
    models = {"image": {}, "video": {}}
    routes = {}
    for category in ("text-to-image", "text-to-video", "image-to-video"):
        kind = "image" if category == "text-to-image" else "video"
        for row in _model_pages(_fal_catalog, {"category": category, "status": "active", "limit": 100},
                                "cursor", "next_cursor", "models"):
            model = row["endpoint_id"]
            if not _ENDPOINT_ID.fullmatch(model):
                continue
            routes[model] = category
            models[kind][model] = row.get("metadata", {}).get("display_name") or model
    return models, routes


def _higgsfield_models():
    spec = integrations._get(_HIGGSFIELD_SPEC, {"User-Agent": integrations.USER_AGENT}, timeout=8)
    models = {kind: dict(choices) for kind, choices in VISUAL_MODELS["higgsfield"].items()}
    routes = {}
    for path, methods in spec["paths"].items():
        endpoint = path.lstrip("/")
        category = endpoint.rsplit("/", 1)[-1]
        if category not in ("text-to-image", "text-to-video", "image-to-video") or not _ENDPOINT_ID.fullmatch(endpoint):
            continue
        operation = methods.get("post", {})
        schema = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
        expected = {"prompt", "image_url"} if category == "image-to-video" else {"prompt"}
        if not expected <= schema.get("properties", {}).keys() or set(schema.get("required", ())) - expected:
            continue
        routes[endpoint] = category
        models["image" if category == "text-to-image" else "video"][endpoint] = endpoint
    return models, routes


def _gemini_models():
    def fetch(query):
        with _response({"provider": "gemini"}, "/models?" + query, None, timeout=8) as response:
            return json.load(response)

    models = {"image": {}, "video": {}}
    for row in _model_pages(fetch, {"pageSize": 100}, "pageToken", "nextPageToken", "models"):
        name = row["name"].removeprefix("models/")
        title = row.get("displayName") or name
        methods = row.get("supportedGenerationMethods", ())
        if name.startswith("gemini-omni-") or (name.startswith("veo-") and "predictLongRunning" in methods):
            models["video"][name] = title
        elif name.startswith("gemini-") and "image" in name.split("-") and "generateContent" in methods:
            models["image"][name] = title
    return models, {}


def _load_visual_catalog(provider):
    target = {"provider": provider}
    if provider == "gemini":
        return _gemini_models()
    if provider == "fal":
        return _fal_models()
    if provider == "higgsfield":
        return _higgsfield_models()
    if provider == "runway":
        spec = integrations._get(_RUNWAY_SPEC, {"User-Agent": integrations.USER_AGENT}, timeout=8)
        operations = _runway_schema(spec)
        known = VISUAL_MODELS[provider]
        image = {model: known["image"].get(model, model) for model in operations["text_to_image"]}
        video = {model: known["video"].get(model, model) for model in
                 dict.fromkeys((*operations["text_to_video"], *operations["image_to_video"]))}
        return {"image": image, "video": video}, operations

    with _response(target, "/models" if provider == "openai" else "/images/models", None, timeout=8) as response:
        image = {row["id"]: row.get("name") or row["id"] for row in json.load(response)["data"]
                 if row.get("id") and (provider != "openai" or row["id"].startswith("gpt-image-"))}
    if provider == "openai":
        return {"image": image}, {}
    with _response(target, "/videos/models", None, timeout=8) as response:
        video = {row["id"]: row.get("name") or row["id"] for row in json.load(response)["data"] if row.get("id")}
    return {"image": image, "video": video}, {}


def _visual_snapshot(provider, refresh=False):
    options = connection({"provider": provider})
    account = hashlib.sha256(options["key"].encode()).digest()
    key = (provider, options["url"], account) if provider != "runway" else ("runway",)
    with _visual_lock:
        entry = _visual_cache.get(key)
    if not refresh or (entry and entry[0] > time.monotonic()):
        return entry[1] if entry else None
    try:
        found = _load_visual_catalog(provider)
        lifetime = _CATALOG_TTL
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        found = entry[1] if entry else None
        lifetime = 45
    with _visual_lock:
        _visual_cache[key] = (time.monotonic() + lifetime, found)
    return found


def visual_catalog(settings, *, refresh=False):
    rows = []
    account_error = ""
    account_rejected = False
    if refresh:
        connected = []
        for provider in _LIVE_VISUAL:
            try:
                connection({"provider": provider})
            except ValueError:
                continue
            if integrations.provider_error(provider) != "key":
                connected.append(provider)
        if connected:
            with ThreadPoolExecutor(max_workers=len(connected) + 1) as pool:
                catalogs = [pool.submit(_visual_snapshot, provider, True) for provider in connected]
                if "runway" in connected:
                    try:
                        integrations.runway_account(connection({"provider": "runway"}), refresh=True)
                    except integrations.KeyRejected as error:
                        account_error, account_rejected = str(error), True
                    except (OSError, ValueError, RuntimeError) as error:
                        account_error = str(error)
                for catalog in catalogs:
                    catalog.result()
    for provider, catalog in VISUAL_MODELS.items():
        try:
            options = connection({"provider": provider})
        except ValueError:
            continue
        error = integrations.provider_error(provider)
        if error == "key" or (provider == "custom" and error):
            continue
        live = _visual_snapshot(provider) if provider in _LIVE_VISUAL else None
        source = live[0] if live else catalog
        models = {kind: dict(source.get(kind, {})) for kind in ("image", "video")}
        details = {"catalogFallback": live is None} if provider in _LIVE_VISUAL else {}
        if provider == "runway":
            account = integrations.runway_account(options)
            if account_rejected:
                models = {"image": {}, "video": {}}
            elif account:
                limits = account["tier"]["models"]
                for kind, choices in models.items():
                    models[kind] = {model: title for model, title in choices.items()
                                    if model in limits and limits[model].get("maxConcurrentGenerations") != 0
                                    and limits[model].get("maxDailyGenerations") != 0}
                if not account_error:
                    details["credits"] = account["creditBalance"]
            details["accountError"] = account_error
        if provider == "custom":
            models["image"].update(integrations.custom_image_models())
        for kind in models:
            saved = settings.get(kind + "_media")
            if saved and saved["provider"] == provider and not live and not account_rejected and not (provider == "runway" and account):
                models[kind].setdefault(saved["model"], saved["model"])
        if any(models.values()) or details:
            rows.append({"id": provider, "title": integrations.PROVIDERS[provider]["title"],
                         **details,
                         **{kind: [{"id": model, "title": title} for model, title in choices.items()]
                            for kind, choices in models.items()}})
    return rows


TASKS = {"videoMedia": "video_media", "imageMedia": "image_media", "ttsMedia": "tts_media", "asrMedia": "asr_media"}


AUDIO_MODELS = {
    "openai": {
        "tts": {"gpt-4o-mini-tts": "GPT-4o mini TTS", "tts-1": "TTS-1", "tts-1-hd": "TTS-1 HD"},
        "asr": {"gpt-transcribe": "GPT Transcribe", "gpt-4o-mini-transcribe": "GPT-4o mini Transcribe",
                "whisper-1": "Whisper"},
    },
    "openrouter": {
        "tts": {"elevenlabs/eleven-v4-turbo": "Eleven v4 Turbo", "elevenlabs/eleven-v4": "Eleven v4",
                "elevenlabs/eleven-flash-v2.5": "Eleven Flash v2.5",
                "elevenlabs/eleven-multilingual-v2": "Eleven Multilingual v2"},
        "asr": {"elevenlabs/scribe-v2": "Scribe v2", "elevenlabs/scribe-v2-medical": "Scribe v2 Medical"},
    },
    "elevenlabs": {
        "tts": {"eleven_flash_v2_5": "Eleven Flash v2.5", "eleven_multilingual_v2": "Eleven Multilingual v2",
                "eleven_v3": "Eleven v3"},
        "asr": {"scribe_v2": "Scribe v2"},
    },
    "deepgram": {"tts": {"aura-2": "Aura 2 (EN / ES)"}, "asr": {"nova-3": "Nova-3 Multilingual"}},
    "cartesia": {"tts": {"sonic-3.6": "Sonic 3.6"}},
    "groq": {
        "tts": {"canopylabs/orpheus-v1-english": "Orpheus (EN)", "canopylabs/orpheus-arabic-saudi": "Orpheus (AR)"},
        "asr": {"whisper-large-v3-turbo": "Whisper Large v3 Turbo", "whisper-large-v3": "Whisper Large v3"},
    },
    "assemblyai": {"asr": {"universal-2": "Universal-2", "universal-3-pro": "Universal-3 Pro"}},
    "custom": {"tts": {}, "asr": {}},
}


def audio_catalog(settings):
    rows = []
    for provider, catalog in AUDIO_MODELS.items():
        try:
            connection({"provider": provider})
        except ValueError:
            continue
        if integrations.provider_error(provider) == "key":
            continue
        row = {"id": provider, "title": integrations.PROVIDERS[provider]["title"]}
        for kind, models in catalog.items():
            choices = dict(models)
            saved = settings.get(kind + "_media")
            if saved and saved["provider"] == provider:
                choices.setdefault(saved["model"], saved["model"])
            row[kind] = [{"id": model, "title": title} for model, title in choices.items()]
        rows.append(row)
    return rows


def audio_voices(provider, model):
    if provider not in AUDIO_MODELS or "tts" not in AUDIO_MODELS[provider]:
        raise ValueError("Выбери сервис в списке.")
    connection({"provider": provider})
    static = {
        "openai": ("alloy", "echo", "fable", "onyx", "nova", "shimmer") if model in ("tts-1", "tts-1-hd")
                  else ("alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer"),
        "openrouter": ("george",),
        "deepgram": ("aura-2-thalia-en", "aura-2-asteria-en", "aura-2-andromeda-en", "aura-2-selena-es"),
        "groq": ("abdullah", "fahad", "sultan", "lulwa", "noura", "aisha") if model.endswith("-arabic-saudi")
                else ("autumn", "diana", "hannah", "austin", "daniel", "troy"),
    }
    if provider not in ("elevenlabs", "cartesia"):
        return [{"id": voice, "title": voice} for voice in static.get(provider, ())]

    target = {"provider": provider}
    eleven = provider == "elevenlabs"
    voices_path = "/v2/voices" if eleven else "/voices"
    path = voices_path + ("?page_size=100" if eleven else "?limit=100")
    rows = {}
    seen = set()
    while path and path not in seen:
        seen.add(path)
        with _response(target, path, None, timeout=15) as response:
            page = json.load(response)
        entries = page.get("voices" if eleven else "data", [])
        for entry in entries:
            voice_id = entry.get("voice_id" if eleven else "id")
            if voice_id:
                rows[voice_id] = entry.get("name") or voice_id
        cursor = page.get("next_page_token" if eleven else "next_page")
        path = None
        if page.get("has_more") and cursor:
            key = "next_page_token" if eleven else "starting_after"
            size = "page_size" if eleven else "limit"
            path = voices_path + "?" + urllib.parse.urlencode({size: 100, key: cursor})
    return [{"id": voice, "title": title} for voice, title in rows.items()]


def selection(value, *, task):
    providers = {"openai", "custom"}
    if task == "image_media":
        providers.update(VISUAL_MODELS)
    elif task == "video_media":
        providers = {provider for provider, models in VISUAL_MODELS.items() if models.get("video")}
    elif task in ("tts_media", "asr_media"):
        kind = task.split("_")[0]
        providers = {provider for provider, catalog in AUDIO_MODELS.items() if kind in catalog}
    speech = task == "tts_media"
    if value is None:
        return None
    if not isinstance(value, dict) or value.get("provider") not in providers:
        raise ValueError("Выбери сервис в списке.")
    result = {"provider": value["provider"]}
    for field in (("model", "voice") if speech else ("model",)):
        item = value.get(field)
        if not isinstance(item, str) or not item.strip() or len(item) > 256 or not item.strip().isprintable():
            raise ValueError("Укажи идентификатор модели и голос." if speech else "Укажи идентификатор модели.")
        result[field] = item.strip()
    return result


def connection(target):
    provider = target["provider"]
    options = integrations.settings_of(provider)
    name = integrations.PROVIDERS[provider]["title"]
    if not options["enabled"] or not options["url"] or (provider != "custom" and not options["key"]):
        raise ValueError(f"Настрой подключение «{name}» в разделе «Интеграции».")
    return options


def _response(target, path, data, content_type="application/json", timeout=90):
    options = connection(target)
    base = options["url"].removesuffix("/openai") if target["provider"] == "gemini" else options["url"]
    if target["provider"] == "elevenlabs" and path.startswith("/v2/"):
        base = base.removesuffix("/v1")
    request = urllib.request.Request(base + path, data=data,
                                     headers={"Content-Type": content_type, "User-Agent": integrations.USER_AGENT})
    if target["provider"] == "cartesia":
        request.add_header("Cartesia-Version", "2026-08-14")
    if target["provider"] == "runway":
        request.add_header("X-Runway-Version", "2024-11-06")
    if target["provider"] == "gemini":
        request.add_unredirected_header("x-goog-api-key", options["key"])
    elif target["provider"] == "elevenlabs":
        request.add_unredirected_header("xi-api-key", options["key"])
    elif options["key"]:
        scheme = {"higgsfield": "Key", "fal": "Key", "deepgram": "Token", "assemblyai": ""}.get(target["provider"], "Bearer")
        request.add_unredirected_header("Authorization", (scheme + " " + options["key"]).strip())
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        with error:
            detail = integrations._http_error(error)
        raise RuntimeError(detail) from error


def _json(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def image(target, prompt, cancel=None):
    if target["provider"] in ("runway", "higgsfield", "fal"):
        return _image_format(_queued_media(target, prompt, "", cancel, video=False))
    body = {"model": target["model"], "prompt": prompt, "n": 1}
    if target["provider"] == "custom" and not target["model"].startswith("gpt-image"):
        body["response_format"] = "b64_json"
    endpoint = "/images/generations"
    if target["provider"] == "openrouter":
        endpoint = "/images"
        del body["n"]
    if target["provider"] == "gemini":
        endpoint = "/models/" + urllib.parse.quote(target["model"], safe="") + ":generateContent"
        body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}
    with _response(target, endpoint, _json(body), timeout=300) as response:
        result = json.load(response)
    rows = result.get("data")
    if target["provider"] == "gemini":
        rows = [{"b64_json": part["inlineData"].get("data")} for candidate in result.get("candidates", [])
                for part in candidate.get("content", {}).get("parts", []) if part.get("inlineData")]
    if not rows or not isinstance(rows[0], dict) or not rows[0].get("b64_json"):
        raise ValueError("Сервис должен возвращать изображение в формате b64_json.")
    return _image_format(base64.b64decode(rows[0]["b64_json"], validate=True))


def _image_format(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data, ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return data, ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return data, ".webp"
    raise ValueError("Сервис вернул изображение в неизвестном формате.")


def _download(url, data=None, headers=None):
    uri = urllib.parse.urlsplit(url)
    if uri.scheme != "https" or not uri.hostname or uri.username or uri.password:
        raise ValueError("Неизвестный адрес файла.")
    request = urllib.request.Request(url, data=data, headers=headers or {}, method="PUT" if data is not None else "GET")
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.read()


def _runway_request(target, prompt, image_path, video):
    model = target["model"]
    operation = "image_to_video" if image_path else "text_to_video" if video else "text_to_image"
    snapshot = _visual_snapshot("runway") or _visual_snapshot("runway", refresh=True)
    image_array = False
    if snapshot:
        schema = snapshot[1][operation].get(model)
        if not schema:
            other = "text_to_video" if image_path else "image_to_video"
            if video and model in snapshot[1][other]:
                raise ValueError("Эта модель Runway принимает только текст." if image_path
                                 else "Для этой модели Runway нужна исходная картинка.")
            raise ValueError("Модель Runway недоступна для этого запроса. Выбери другую в разделе «Картинки и видео».")
        defaults, max_prompt, image_array = schema
        # Runway counts UTF-16 code units for some models.
        if max_prompt and len(prompt.encode("utf-16-le")) // 2 > max_prompt:
            raise ValueError(f"Описание слишком длинное для этой модели Runway. Максимум {max_prompt} символов.")
        body = {"model": model, "promptText": prompt, **defaults}
    else:
        if video and model == "gen4_turbo" and not image_path:
            raise ValueError("Для Gen-4 Turbo приложи картинку.")
        body = {"model": model, "promptText": prompt}
        if model != "ideogram_4_5":
            body["ratio"] = "1280:720" if video else "1024:1024"
        if video:
            body["duration"] = 5
    if image_path:
        mime = mimetypes.guess_type(image_path)[0] or "image/png"
        encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        uri = f"data:{mime};base64,{encoded}"
        body["promptImage"] = [{"uri": uri, "position": "first"}] if image_array else uri
    return "/" + operation, body


def _fal_schema(endpoint):
    query = urllib.parse.urlencode({"endpoint_id": endpoint, "expand": "openapi-3.0"})
    result = _fal_catalog(query)
    row = next((row for row in result["models"] if row["endpoint_id"] == endpoint), None)
    if row is None:
        raise ValueError("Модель больше не найдена в каталоге fal.ai.")
    try:
        spec = row["openapi"]
        paths = spec["paths"]
        operation = paths.get("/" + endpoint, {}).get("post")
        if operation is None:
            # Aliases can publish the schema under the canonical inference path.
            posts = [methods["post"] for path, methods in paths.items() if "{" not in path and "post" in methods]
            if len(posts) != 1:
                raise ValueError("В каталоге fal.ai отсутствует схема этой модели.")
            operation = posts[0]
        schema = operation["requestBody"]["content"]["application/json"]["schema"]
        ref = schema.get("$ref", "")
        if ref.startswith("#/components/schemas/"):
            schema = spec["components"]["schemas"][ref.rsplit("/", 1)[1]]
    except (KeyError, TypeError) as error:
        raise ValueError("В каталоге fal.ai отсутствует схема этой модели.") from error
    return row["metadata"]["category"], schema


def _queued_endpoint(target, video, image_path):
    provider, model = target["provider"], target["model"]
    if not _ENDPOINT_ID.fullmatch(model):
        raise ValueError("Идентификатор модели не подходит для генерации.")
    if not video:
        endpoint = model
    else:
        desired = "image-to-video" if image_path else "text-to-video"
        prefix, _, suffix = model.rpartition("/")
        if suffix in ("image-to-video", "text-to-video"):
            endpoint = prefix + "/" + desired
        elif model in VISUAL_MODELS[provider]["video"]:
            endpoint = model + "/" + desired
        else:
            endpoint = model
    if provider == "fal":
        legacy = model in VISUAL_MODELS["fal"]["video"] or model in VISUAL_MODELS["fal"]["image"]
        if not legacy:
            category, schema = _fal_schema(endpoint)
            desired = ("image-to-video" if image_path else "text-to-video") if video else "text-to-image"
            expected = {"prompt", "image_url"} if image_path else {"prompt"}
            if category != desired or not expected <= schema.get("properties", {}).keys() or set(schema.get("required", ())) - expected:
                raise ValueError("Модель fal.ai требует входные данные, которых нет в этом запросе.")
    elif video and model not in VISUAL_MODELS["higgsfield"]["video"]:
        snapshot = _visual_snapshot("higgsfield") or _visual_snapshot("higgsfield", True)
        if not snapshot or endpoint not in snapshot[1]:
            raise ValueError("Модель Higgsfield не поддерживает этот тип запроса.")
    return "/" + endpoint


def _fal_queue_path(target, url, fallback):
    if not url:
        return fallback
    configured = urllib.parse.urlsplit(connection(target)["url"])
    remote = urllib.parse.urlsplit(url)
    if (remote.scheme, remote.netloc) != (configured.scheme, configured.netloc):
        raise ValueError("Неизвестный адрес задания fal.ai.")
    prefix = configured.path.rstrip("/")
    if prefix and not remote.path.startswith(prefix + "/"):
        raise ValueError("Неизвестный адрес задания fal.ai.")
    return remote.path[len(prefix):] + ("?" + remote.query if remote.query else "")


def _queued_media(target, prompt, image_path, cancel, *, video):
    provider, model = target["provider"], target["model"]
    cancel = cancel if cancel is not None else threading.Event()
    if cancel.is_set():
        raise InterruptedError()
    body = {"prompt": prompt}
    if provider == "runway":
        endpoint, body = _runway_request(target, prompt, image_path, video)
    else:
        endpoint = _queued_endpoint(target, video, image_path)
    if provider != "runway" and image_path:
        mime = mimetypes.guess_type(image_path)[0] or "image/png"
        data = Path(image_path).read_bytes()
        if provider == "higgsfield":
            with _response(target, "/files/generate-upload-url", _json({"content_type": mime})) as response:
                upload = json.load(response)
            _download(upload["upload_url"], data, upload["upload_headers"])
            body["image_url"] = upload["public_url"]
        else:
            encoded = base64.b64encode(data).decode("ascii")
            body["image_url"] = f"data:{mime};base64,{encoded}"
    if cancel.is_set():
        raise InterruptedError()
    with _response(target, endpoint, _json(body)) as response:
        job = json.load(response)
    request_id = urllib.parse.quote(job["id"] if provider == "runway" else job["request_id"], safe="")
    if provider == "runway":
        path = "/tasks/" + request_id
    elif provider == "higgsfield":
        path = "/requests/" + request_id + "/status"
    else:
        application = "/".join(model.split("/")[:2])
        result_path = f"/{application}/requests/{request_id}"
        path = _fal_queue_path(target, job.get("status_url"), result_path + "/status")
        result_path = _fal_queue_path(target, job.get("response_url"), result_path)
    deadline = time.monotonic() + 3600
    while time.monotonic() < deadline:
        if cancel.wait(5):
            raise InterruptedError()
        with _response(target, path, None) as response:
            result = json.load(response)
        status = str(result.get("status", "")).lower()
        if status in ("succeeded", "completed"):
            if provider == "runway":
                return _download(result["output"][0])
            if provider == "fal":
                with _response(target, result_path, None) as response:
                    result = json.load(response)
            output = result["video"] if video else result["images"][0]
            return _download(output["url"])
        if status in ("failed", "canceled", "cancelled", "nsfw", "expired"):
            raise RuntimeError(result.get("failure") or result.get("error") or status)
    raise RuntimeError("Истекло время ожидания генерации.")


def _gemini_omni_video(target, prompt, image_path, cancel):
    if cancel.is_set():
        raise InterruptedError()
    contents = [{"type": "text", "text": prompt}]
    if image_path:
        mime = mimetypes.guess_type(image_path)[0] or "image/png"
        encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        contents.insert(0, {"type": "image", "data": encoded, "mime_type": mime})
    body = {"model": target["model"], "input": contents, "response_format": {"type": "video", "delivery": "inline"}}
    with _response(target, "/interactions", _json(body), timeout=300) as response:
        result = json.load(response)
    if cancel.is_set():
        raise InterruptedError()
    for step in result.get("steps", []):
        if step.get("type") == "model_output":
            for content in step.get("content", []):
                if content.get("type") == "video" and content.get("data"):
                    return base64.b64decode(content["data"], validate=True)
    raise RuntimeError(result.get("error") or "Сервис не вернул видео.")


def video(target, prompt, image_path, cancel):
    if target["provider"] in ("runway", "higgsfield", "fal"):
        return _queued_media(target, prompt, image_path, cancel, video=True)
    if target["provider"] == "gemini" and target["model"].startswith("gemini-omni-"):
        return _gemini_omni_video(target, prompt, image_path, cancel)
    body = {"model": target["model"], "prompt": prompt}
    gemini = target["provider"] == "gemini"
    instance = {"prompt": prompt}
    if image_path:
        mime = mimetypes.guess_type(image_path)[0] or "image/png"
        encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        instance["image"] = {"mimeType": mime, "bytesBase64Encoded": encoded}
        body["frame_images"] = [{"frame_type": "first_frame", "type": "image_url",
                                 "image_url": {"url": f"data:{mime};base64,{encoded}"}}]
    if cancel.is_set():
        raise InterruptedError()
    endpoint = "/videos"
    if gemini:
        endpoint = "/models/" + urllib.parse.quote(target["model"], safe="") + ":predictLongRunning"
        body = {"instances": [instance]}
    with _response(target, endpoint, _json(body)) as response:
        job = json.load(response)
    path = "/" + urllib.parse.quote(job["name"], safe="/") if gemini else "/videos/" + urllib.parse.quote(job["id"], safe="")
    deadline = time.monotonic() + 3600
    while time.monotonic() < deadline:
        if cancel.is_set():
            raise InterruptedError()
        if gemini and job.get("done"):
            samples = job.get("response", {}).get("generateVideoResponse", {}).get("generatedSamples", [])
            if not samples:
                raise RuntimeError(job.get("error") or "Сервис не вернул видео.")
            url = samples[0]["video"]["uri"]
            base = connection(target)["url"].removesuffix("/openai")
            origin = urllib.parse.urlsplit(base)
            uri = urllib.parse.urlsplit(url)
            if (uri.scheme, uri.netloc) != (origin.scheme, origin.netloc):
                raise ValueError("Неизвестный адрес загрузки видео.")
            request = urllib.request.Request(url)
            request.add_unredirected_header("x-goog-api-key", connection(target)["key"])
            with urllib.request.urlopen(request, timeout=300) as response:
                return response.read()
        if job.get("status") == "completed":
            with _response(target, path + "/content", None, timeout=300) as response:
                return response.read()
        if job.get("status") in ("failed", "cancelled", "expired"):
            raise RuntimeError(job.get("error") or job["status"])
        if cancel.wait(5):
            raise InterruptedError()
        with _response(target, path, None) as response:
            job = json.load(response)
    raise RuntimeError("Истекло время ожидания видео.")


def speech(target, text):
    provider = target["provider"]
    if provider == "elevenlabs":
        voice = urllib.parse.quote(target["voice"], safe="")
        return _response(target, f"/text-to-speech/{voice}?output_format=pcm_24000",
                         _json({"model_id": target["model"], "text": text}))
    if provider == "cartesia":
        body = {"model_id": target["model"], "transcript": text, "voice": target["voice"],
                "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 24000}}
        return _response(target, "/tts/bytes", _json(body))
    if provider == "deepgram":
        query = urllib.parse.urlencode({"model": target["voice"], "encoding": "linear16", "container": "wav"})
        return _response(target, "/speak?" + query, _json({"text": text}))
    if provider == "openrouter":
        body = {"model": target["model"], "voice": target["voice"], "input": text, "response_format": "pcm"}
        return _response(target, "/audio/speech", _json(body))
    body = {"model": target["model"], "voice": target["voice"], "input": text, "response_format": "wav"}
    return _response(target, "/audio/speech", _json(body))


def transcription_body(audio, model, language=None):
    fields = {"model": model, "response_format": "json"}
    if language:
        fields["language"] = language
    return _audio_form(audio, fields)


def _audio_form(audio, fields):
    boundary = uuid.uuid4().hex
    form = "".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
                   for key, value in fields.items())
    form += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.wav"\r\n'
             'Content-Type: audio/wav\r\n\r\n')
    return form.encode() + audio + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def speech_wav(target, audio):
    if target["provider"] not in ("elevenlabs", "openrouter") or audio.startswith(b"RIFF"):
        return audio
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        wav.writeframes(audio)
    return output.getvalue()


def _assembly_transcript(target, audio):
    with _response(target, "/upload", audio, "application/octet-stream", timeout=20) as response:
        upload_url = json.load(response)["upload_url"]
    body = {"audio_url": upload_url, "speech_models": [target["model"]], "language_detection": True}
    with _response(target, "/transcript", _json(body), timeout=20) as response:
        result = json.load(response)
    path = "/transcript/" + urllib.parse.quote(result["id"], safe="")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if result["status"] == "completed":
            return result
        if result["status"] == "error":
            raise RuntimeError(result.get("error") or "Сервис не вернул текст распознавания.")
        time.sleep(0.75)
        with _response(target, path, None, timeout=10) as response:
            result = json.load(response)
    raise RuntimeError("Истекло время ожидания распознавания речи.")


def transcribe(target, audio):
    provider = target["provider"]
    if provider == "assemblyai":
        return (_assembly_transcript(target, audio).get("text") or "").strip()
    if provider == "deepgram":
        query = urllib.parse.urlencode({"model": target["model"], "language": "multi", "smart_format": "true"})
        with _response(target, "/listen?" + query, audio, "audio/wav") as response:
            results = json.load(response)["results"]["channels"]
        return results[0]["alternatives"][0]["transcript"].strip()
    path = "/audio/transcriptions"
    if provider == "elevenlabs":
        path = "/speech-to-text"
        data, content_type = _audio_form(audio, {"model_id": target["model"]})
    else:
        data, content_type = transcription_body(audio, target["model"])
    with _response(target, path, data, content_type) as response:
        result = json.load(response)
    if not isinstance(result.get("text"), str):
        raise ValueError("Сервис не вернул текст распознавания.")
    return result["text"].strip()
