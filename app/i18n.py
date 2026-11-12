"""The window translates itself; Windows notifications, the tray menu and file dialogs are drawn outside it, so they use the same dictionary here."""
from __future__ import annotations

import json
import re
from pathlib import Path

DICTIONARY = Path(__file__).resolve().parents[1] / "ui" / "src" / "i18n" / "strings.json"
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
_words: dict[str, str] | None = None
_patterns: list[tuple[re.Pattern, str]] = []


def _load():
    global _words
    if _words is None:
        try:
            _words = json.loads(DICTIONARY.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _words = {}
        for key, value in _words.items():
            pieces = re.split(r"\{(\d)\}", key)
            if len(pieces) == 1:
                continue
            regex = "".join(re.escape(piece) if index % 2 == 0 else f"(?P<p{piece}>.+?)" for index, piece in enumerate(pieces))
            _patterns.append((re.compile(f"^{regex}$", re.S), value))
        _patterns.sort(key=lambda item: -len(item[0].pattern))
    return _words


def translate(text, language):
    text = str(text or "")
    if language != "en" or not CYRILLIC.search(text):
        return text
    words = _load()
    clean = " ".join(text.split())
    if clean in words:
        return words[clean]
    for regex, value in _patterns:
        found = regex.match(clean)
        if found:
            result = value
            for name, part in found.groupdict().items():
                result = result.replace("{" + name[1:] + "}", translate(part.strip(), language))
            return result
    return text
