"""New versions come from the GitHub releases of the project. The installer is downloaded, checked and run only when the user asks."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from app.models import download
from app.version import VERSION

REPO = "covriknapoly-glitch/piven-companion"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
USER_AGENT = f"PIVEN-Companion/{VERSION}"
TRUSTED_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")


def version_key(text):
    numbers = re.findall(r"\d+", str(text or ""))[:4]
    return tuple(int(number) for number in numbers) + (0,) * (4 - len(numbers))


def is_newer(candidate, current=VERSION):
    return bool(re.search(r"\d", str(candidate or ""))) and version_key(candidate) > version_key(current)


def _installer(assets):
    for asset in assets or []:
        name = str(asset.get("name") or "")
        if name.lower().endswith("-setup.exe"):
            digest = str(asset.get("digest") or "")
            return {"name": name, "size": int(asset.get("size") or 0), "url": str(asset.get("browser_download_url") or ""),
                    "sha256": digest.split(":", 1)[1].lower() if digest.lower().startswith("sha256:") else ""}
    return None


def latest_release(timeout=15):
    request = urllib.request.Request(LATEST, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.load(response)
    if data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    return {"version": tag.lstrip("vV"), "tag": tag, "name": str(data.get("name") or tag), "notes": str(data.get("body") or "")[:4000],
            "page": str(data.get("html_url") or ""), "installer": _installer(data.get("assets"))}


def installed_copy(app_dir):
    """Only a copy put there by the installer can be updated by it; a copy run from the sources is left alone."""
    return (Path(app_dir) / "unins000.exe").is_file()


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class Updater:
    def __init__(self, app_dir, data_dir, on_change=lambda: None):
        self.app_dir, self.folder, self.on_change = Path(app_dir), Path(data_dir) / "updates", on_change
        self.latest = None
        self.checked = 0.0
        self.error = ""
        self.job = {"state": "idle", "percent": 0, "message": ""}
        self.ready = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    def status(self, skipped=""):
        latest = self.latest or {}
        available = is_newer(latest.get("version"))
        return {"current": VERSION, "latest": latest.get("version", ""), "available": available, "notes": latest.get("notes", ""),
                "page": latest.get("page", ""), "size": (latest.get("installer") or {}).get("size", 0),
                "canInstall": installed_copy(self.app_dir) and bool(latest.get("installer")), "skipped": available and latest.get("version") == skipped,
                "checked": self.checked, "error": self.error, "job": dict(self.job), "ready": bool(self.ready)}

    def check(self):
        try:
            self.latest = latest_release()
            self.error = ""
        except Exception as error:
            self.error = f"Не удалось проверить обновления: {error}"
        self.checked = time.time()
        self.on_change()
        return self.latest

    def _set(self, **values):
        self.job.update(values)
        self.on_change()

    def download(self):
        installer = (self.latest or {}).get("installer")
        if not installer or not is_newer((self.latest or {}).get("version")):
            return {"ok": False, "error": "Новой версии нет."}
        if not installed_copy(self.app_dir):
            return {"ok": False, "error": "Эта копия запущена из исходников, обновлять её нужно через git."}
        if urlparse(installer["url"]).scheme != "https" or urlparse(installer["url"]).hostname not in TRUSTED_HOSTS:
            return {"ok": False, "error": "Ссылка на установщик ведёт не на GitHub."}
        with self._lock:
            if self.job["state"] == "running":
                return {"ok": True}
            self._cancel.clear()
            self.ready = None
            self._set(state="running", percent=0, message="Скачивается обновление")
        threading.Thread(target=self._download, args=(installer,), daemon=True).start()
        return {"ok": True}

    def _download(self, installer):
        target = self.folder / re.sub(r"[^A-Za-z0-9._-]", "_", installer["name"])
        partial = target.with_suffix(".part")
        size = installer["size"]
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            for old in self.folder.glob("*.exe"):
                if old != target:
                    old.unlink(missing_ok=True)
            if not (target.is_file() and target.stat().st_size == size):
                download.fetch(installer["url"], partial, headers={"User-Agent": USER_AGENT}, cancel_event=self._cancel,
                               on_bytes=lambda received: self._set(percent=int(received * 100 / size) if size else 0),
                               on_wait=lambda message: self._set(message=message))
                partial.replace(target)
            if size and target.stat().st_size != size:
                raise ValueError("Файл скачался не полностью.")
            if installer["sha256"]:
                self._set(message="Проверяется файл")
                if _sha256(target) != installer["sha256"]:
                    target.unlink(missing_ok=True)
                    raise ValueError("Файл не совпал с тем, что выложен на GitHub. Скачай обновление ещё раз.")
            self.ready = target
            self._set(state="done", percent=100, message="Обновление скачано")
        except InterruptedError:
            partial.unlink(missing_ok=True)
            self._set(state="idle", percent=0, message="")
        except Exception as error:
            self._set(state="error", message=str(error))

    def cancel(self):
        self._cancel.set()
        return {"ok": True}

    def launch(self):
        """Starts the installer on its own; the caller closes the program so its files can be replaced."""
        if not self.ready or not Path(self.ready).is_file():
            return {"ok": False, "error": "Обновление ещё не скачано."}
        flags = 0x00000008 | 0x00000200
        subprocess.Popen([str(self.ready), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/update=1"],
                         cwd=str(self.folder), creationflags=flags, close_fds=True)
        return {"ok": True}

    def clean(self):
        """After an update the downloaded installer is no longer needed; a newer one waiting to be installed is kept."""
        for item in self.folder.glob("*"):
            if item.is_file() and item.suffix.lower() in (".exe", ".part") and not is_newer(item.stem):
                try:
                    item.unlink()
                except OSError:
                    pass
