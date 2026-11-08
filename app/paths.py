"""The folder with chats, settings and models. Older versions called it OllamaCompanion; main.pyw moves it on launch."""
from __future__ import annotations

import os
from pathlib import Path

NAME = "PIVEN"
OLD_NAME = "OllamaCompanion"


def _local():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home())))


def _has_files(folder):
    try:
        return any(folder.iterdir())
    except OSError:
        return False


def current(local=None):
    local = local or _local()
    new, old = local / NAME, local / OLD_NAME
    return old if _has_files(old) and not _has_files(new) else new


def _fix_saved_paths(folder):
    """Pictures in old chats are stored by full path."""
    saved = folder / "conversation.json"
    if not saved.is_file():
        return
    text = saved.read_text(encoding="utf-8")
    fixed = text.replace(f"\\\\{OLD_NAME}\\\\", f"\\\\{NAME}\\\\").replace(f"/{OLD_NAME}/", f"/{NAME}/")
    if fixed != text:
        temporary = saved.with_suffix(".moving")
        temporary.write_text(fixed, encoding="utf-8")
        os.replace(temporary, saved)


def migrate(local=None):
    """Renames the old folder. If a file is busy, stays on the old folder until the next launch."""
    global DATA_DIR
    local = local or _local()
    new, old = local / NAME, local / OLD_NAME
    if _has_files(old) and not _has_files(new):
        try:
            if new.exists():
                new.rmdir()
            old.rename(new)
        except OSError:
            DATA_DIR = old
            return old
        try:
            _fix_saved_paths(new)
        except (OSError, ValueError):
            pass
    DATA_DIR = new
    return new


DATA_DIR = current()
