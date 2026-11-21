"""Serves the PIVEN site from this computer, for the router to publish under its KeenDNS name.

What it can give out is decided when it starts: the files of this folder at /, the phone page (ui/dist) at /phone/.
They are read into memory, and a request can only pick one of them by its exact address, so no address reaches
any other file on the disk. It listens on the home network address only and answers GET and HEAD; the router
talks to the internet and does HTTPS.

    runtime\\Python311\\pythonw.exe site\\serve.py              (finds the home network address itself)
    runtime\\Python311\\pythonw.exe site\\serve.py --host 192.168.1.100 --port 8090
"""
from __future__ import annotations

import argparse
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ((ROOT / "site", "/"), (ROOT / "ui" / "dist", "/phone/"))
SKIP = {"publish.py", "serve.py", "__pycache__"}
TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".json": "application/json", ".webmanifest": "application/manifest+json", ".txt": "text/plain; charset=utf-8",
    ".png": "image/png", ".webp": "image/webp", ".svg": "image/svg+xml", ".ico": "image/x-icon",
    ".ttf": "font/ttf", ".otf": "font/otf", ".woff2": "font/woff2",
}
# The site needs nothing but its own files, the GitHub API (release size) and ntfy.sh (the phone finding the computer).
SECURITY = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                               "img-src 'self' data: blob: https:; media-src 'self' data: blob:; font-src 'self'; "
                               "connect-src 'self' https://ntfy.sh https://api.github.com; object-src 'none'; base-uri 'none'; "
                               "form-action 'self'; frame-ancestors 'none'",
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
LOG = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PIVEN" / "site-server.log"
LOG_LIMIT = 1_000_000
BUSY_LIMIT = 64


def collect():
    """Address -> (bytes, type). Hidden files, this script and unknown file types are never included."""
    files = {}
    for folder, prefix in FOLDERS:
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            parts = path.relative_to(folder).parts
            if not path.is_file() or any(part in SKIP or part.startswith(".") for part in parts):
                continue
            kind = TYPES.get(path.suffix.lower())
            if kind:
                files[prefix + "/".join(parts)] = (path.read_bytes(), kind)
    for address in list(files):
        if address.endswith("/index.html"):
            files[address[:-len("index.html")]] = files[address]
    return files


def stamp():
    newest = 0.0
    for folder, _ in FOLDERS:
        for path in folder.rglob("*") if folder.is_dir() else []:
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:
                pass
    return newest


class Site:
    """The files in memory, refreshed when something in the folders changes (checked at most every 10 seconds)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.files, self.seen, self.checked = collect(), stamp(), time.monotonic()

    def get(self, address):
        with self.lock:
            if time.monotonic() - self.checked > 10:
                self.checked = time.monotonic()
                newest = stamp()
                if newest != self.seen:
                    self.files, self.seen = collect(), newest
            return self.files.get(address)


def log(line):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > LOG_LIMIT:
            LOG.replace(LOG.with_suffix(".old.log"))
        with LOG.open("a", encoding="utf-8") as stream:
            stream.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except OSError:
        pass


class Handler(BaseHTTPRequestHandler):
    server_version = "PIVEN"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = 15
    site: Site
    busy = threading.BoundedSemaphore(BUSY_LIMIT)

    def log_message(self, format, *args):
        log(f"{self.client_address[0]} {format % args}")

    def _plain(self, code, text, extra=None):
        body = text.encode("utf-8")
        self.send_response(code)
        for key, value in {**SECURITY, **(extra or {})}.items():
            self.send_header(key, value)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _serve(self):
        if not self.busy.acquire(blocking=False):
            self.close_connection = True
            return self._plain(503, "busy, try again in a moment")
        try:
            address = self.path.split("?", 1)[0].split("#", 1)[0]
            if len(self.path) > 1024 or not address.startswith("/"):
                return self._plain(400, "bad request")
            if address == "/phone":
                return self._plain(301, "moved", {"Location": "/phone/"})
            found = self.site.get(address)
            if found is None:
                return self._plain(404, "not found")
            body, kind = found
            self.send_response(200)
            for key, value in SECURITY.items():
                self.send_header(key, value)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache" if kind.startswith("text/html") or kind.endswith("manifest+json") else "public, max-age=3600")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        finally:
            self.busy.release()

    def do_GET(self):
        self._serve()

    def do_HEAD(self):
        self._serve()

    def _refuse(self):
        self.close_connection = True
        self._plain(405, "only GET and HEAD", {"Allow": "GET, HEAD"})

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = do_CONNECT = _refuse


def home_address():
    """The address of this computer in the home network (the route to the router, not to a VPN)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.168.1.1", 9))
        return probe.getsockname()[0]
    finally:
        probe.close()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    host = args.host or home_address()
    Handler.site = Site()
    server = Server((host, args.port), Handler)
    log(f"serving {len(Handler.site.files)} files on {host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
