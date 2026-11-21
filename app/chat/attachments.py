"""Files attached to a message. Their text goes to the model inside the message; the chat shows only a card with the name.

Plain text and code of any kind are read as they are, Word documents (.docx) from their XML, PDF through pypdf when it is
installed. A file is refused when nothing readable comes out of it (a picture, an archive, a scanned PDF).
"""
from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path

MAX_FILE_BYTES = 20_000_000
# Suffixes that are binary whatever their first bytes look like.
BINARY_SUFFIXES = {".exe", ".dll", ".zip", ".7z", ".rar", ".gz", ".tar", ".iso", ".msi", ".bin", ".gguf", ".safetensors",
                   ".mp3", ".wav", ".flac", ".ogg", ".mp4", ".mkv", ".webm", ".avi", ".mov", ".doc", ".xls", ".ppt",
                   ".xlsx", ".pptx", ".odt", ".ods", ".sqlite", ".db", ".pyc", ".class", ".jar", ".woff", ".woff2", ".ttf", ".otf"}
FILE_ONLY_PROMPTS = {False: "Посмотри этот файл и коротко расскажи, что в нём.",
                     True: "Посмотри эти файлы и коротко расскажи, что в них."}


class Unreadable(ValueError):
    """The file has no text the model could read; the message says why, in words for the user."""


def read_text(path, *, preserve_lines=False) -> str:
    path = Path(path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise Unreadable("файл больше 20 МБ")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = _pdf(path)
    elif suffix == ".docx":
        text = _docx(path)
    elif suffix in BINARY_SUFFIXES:
        raise Unreadable("такие файлы читать не умею: подходят текст, код, PDF и документы Word (.docx)")
    else:
        text = _plain(path.read_bytes())
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise Unreadable("в файле нет текста" + (": похоже, это скан" if suffix == ".pdf" else ""))
    return text if preserve_lines else text.strip()


def _plain(data: bytes) -> str:
    head = data[:8192]
    controls = sum(1 for byte in head if byte < 32 and byte not in (9, 10, 12, 13, 27))
    if b"\x00" in head or (head and controls / len(head) > 0.02):
        raise Unreadable("это не текстовый файл: подходят текст, код, PDF и документы Word (.docx)")
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError) as error:
        raise Unreadable("документ Word повреждён") from error
    parts = []
    for match in _DOCX_TOKEN.finditer(xml):
        token = match.group(0)
        parts.append(html.unescape(match.group(1)) if match.group(1) is not None else "\t" if token.startswith("<w:tab") else "\n")
    return "".join(parts)


# Text runs, tabs, line breaks and paragraph ends of word/document.xml, in their order.
_DOCX_TOKEN = re.compile(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>|<w:tab/>|<w:br[^>]*/>|</w:p>", re.S)


def pdf_pages(path: Path) -> list[str]:
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise Unreadable("для PDF в программе пока нет модуля pypdf") from error
    try:
        reader = PdfReader(str(path))
        return [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as error:
        raise Unreadable("PDF не открывается: возможно, он защищён паролем или повреждён") from error


def _pdf(path: Path) -> str:
    return "\n\n".join(pdf_pages(path))


def prompt_block(paths, budget: int) -> str:
    """The files as they go to the model after the user's words. All of them together take at most `budget` characters:
    short files go whole, long ones share what is left equally and say how much of them was cut."""
    read = []
    for path in paths:
        name = Path(path).name.replace('"', "'")
        try:
            read.append([name, read_text(path), ""])
        except (Unreadable, OSError) as error:
            read.append([name, "", f"[не удалось прочитать: {error}]"])
    left, waiting = max(0, budget), [entry for entry in read if entry[1]]
    for entry in sorted(waiting, key=lambda item: len(item[1])):
        share = left // len(waiting)
        waiting.remove(entry)
        text = entry[1]
        if len(text) > share:
            entry[1], entry[2] = text[:share], f"[файл обрезан: здесь первые {share} из {len(text)} символов]"
        left -= len(entry[1])
    blocks = [f'<file name="{name}">\n' + "\n".join(part for part in (text, note) if part) + "\n</file>" for name, text, note in read]
    return "\n\nПриложенные файлы:\n\n" + "\n\n".join(blocks)


def check(path) -> str:
    """Empty when the file can be attached, otherwise why it cannot."""
    try:
        read_text(path)
        return ""
    except Unreadable as error:
        return str(error)
    except OSError:
        return "файл не открывается"
