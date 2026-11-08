from __future__ import annotations

import html
import io
import json
import re
import urllib.parse
import urllib.request

HEADERS = {"User-Agent": "PivenCompanion/1.0 (https://github.com/covriknapoly-glitch/piven-companion)"}
SPANISH = re.compile(r"[¿¡ñáéíóú]|\b(?:haz|hazme|crea|sobre|una|los|las|del|presentaci[oó]n|diapositivas?)\b", re.I)
SOURCE_CHARS = 10000
WIDE_SOURCE_CHARS = 5000
IMAGE_BYTES = 8 * 2**20
IMAGE_WIDTH = 1280
MIN_IMAGE_WIDTH = 600
FREE_LICENSE = re.compile(r"\b(?:cc|public domain|pd|gfdl|mit|fal)\b|cc0|attribution", re.I)
NOT_FREE_LICENSE = re.compile(r"\bnc\b|\bnd\b|non-?commercial|no-?deriv|fair use", re.I)


def language_of(text):
    if re.search(r"[А-Яа-яЁё]", text):
        return "ru"
    if re.search(r"[㐀-鿿]", text):
        return "zh"
    return "es" if SPANISH.search(text) else "en"


def _json(url, params=None, timeout=15):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _wiki(host, **params):
    return _json(f"https://{host}/w/api.php", {"action": "query", "format": "json", "formatversion": 2, **params})


def _plain(value, limit=70):
    text = re.sub(r"<[^>]+>", " ", html.unescape(str(value or "")))
    return " ".join(text.split())[:limit].rstrip()


def _articles(host, queries, limit):
    titles = []
    for query in queries:
        exact = (_wiki(host, titles=query, redirects=1).get("query", {}).get("pages") or [{}])[0]
        if exact.get("title") and not exact.get("missing") and not exact.get("invalid"):
            titles.append(exact["title"])
    for query in queries:
        for hit in _wiki(host, list="search", srsearch=query, srlimit=2).get("query", {}).get("search", []):
            if hit["title"] not in titles:
                titles.append(hit["title"])
    found = []
    share = limit // max(1, min(3, len(titles)))
    for title in titles[:3]:
        pages = _wiki(host, prop="extracts|info", explaintext=1, exsectionformat="plain", inprop="url", titles=title, redirects=1)
        page = (pages.get("query", {}).get("pages") or [{}])[0]
        text = str(page.get("extract", "")).strip()
        if text:
            found.append({"title": page.get("title", title), "url": page.get("fullurl", ""), "text": text[:share]})
    return found


def wikipedia_articles(queries, language):
    limit = WIDE_SOURCE_CHARS if language == "zh" else SOURCE_CHARS
    found = _articles(f"{language}.wikipedia.org", queries, limit)
    if not found and language != "en":
        found = _articles("en.wikipedia.org", queries, limit)
    return found


def _commons_candidates(query):
    pages = _wiki("commons.wikimedia.org", generator="search", gsrsearch="filetype:bitmap " + query, gsrnamespace=6, gsrlimit=10,
                  prop="imageinfo", iiprop="url|size|mime|extmetadata", iiurlwidth=IMAGE_WIDTH,
                  iiextmetadatafilter="LicenseShortName|Artist").get("query", {}).get("pages", [])
    candidates = []
    for page in sorted(pages, key=lambda item: item.get("index", 0)):
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        candidates.append({"url": info.get("thumburl") or info.get("url", ""), "page": info.get("descriptionurl", ""),
                           "width": info.get("width", 0), "height": info.get("height", 0), "mime": info.get("mime", ""),
                           "author": _plain(meta.get("Artist", {}).get("value")),
                           "license": _plain(meta.get("LicenseShortName", {}).get("value")), "source": "Wikimedia Commons"})
    return candidates


def _openverse_candidates(query):
    results = _json("https://api.openverse.org/v1/images/", {"q": query, "license_type": "commercial,modification", "page_size": 10}).get("results", [])
    return [{"url": item.get("url", ""), "page": item.get("foreign_landing_url", ""), "width": item.get("width") or 0, "height": item.get("height") or 0,
             "mime": "image/" + str(item.get("filetype") or "jpeg").replace("jpg", "jpeg"), "author": _plain(item.get("creator")),
             "license": f"{str(item.get('license', '')).upper()} {item.get('license_version') or ''}".strip(), "source": _plain(item.get("source"))}
            for item in results]


def usable_candidate(candidate, used=()):
    url, ratio = candidate["url"], candidate["width"] / max(1, candidate["height"])
    return (url.startswith("https://") and url not in used and candidate["mime"] in ("image/jpeg", "image/png", "image/tiff")
            and candidate["width"] >= MIN_IMAGE_WIDTH and 0.55 <= ratio <= 2.4
            and bool(FREE_LICENSE.search(candidate["license"])) and not NOT_FREE_LICENSE.search(candidate["license"]))


def _download(url):
    from PIL import Image
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=25) as response:
        data = response.read(IMAGE_BYTES + 1)
    if len(data) > IMAGE_BYTES:
        raise ValueError("image is too large")
    with Image.open(io.BytesIO(data)) as image:
        image.thumbnail((IMAGE_WIDTH, IMAGE_WIDTH))
        output = io.BytesIO()
        image.convert("RGB").save(output, "JPEG", quality=86)
        return output.getvalue(), image.size


def find_image(query, used):
    for search in (_commons_candidates, _openverse_candidates):
        try:
            candidates = search(query)
        except Exception:
            continue
        for candidate in candidates:
            if not usable_candidate(candidate, used):
                continue
            try:
                data, size = _download(candidate["url"])
            except Exception:
                continue
            used.add(candidate["url"])
            credit = " · ".join(part for part in (candidate["author"], candidate["license"], candidate["source"]) if part)
            return {"data": data, "size": size, "credit": credit, "page": candidate["page"]}
    return None
