"""Local previews of pages the model made: one folder served read-only on 127.0.0.1, so the built-in browser
(which opens only web addresses) can show an HTML game or site from disk. Nothing outside that folder is served."""
from __future__ import annotations

import functools
import http.server
import threading
import urllib.parse
from pathlib import Path

_servers = {}   # {folder: (server, port)}
_lock = threading.Lock()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")   # a rewritten file shows up on reload
        super().end_headers()


def url_for(path):
    """The local address of an HTML file, starting a server for its folder the first time."""
    path = Path(path).resolve()
    folder = path.parent
    with _lock:
        if folder not in _servers:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_QuietHandler, directory=str(folder)))
            threading.Thread(target=server.serve_forever, name="preview-server", daemon=True).start()
            _servers[folder] = (server, server.server_address[1])
        port = _servers[folder][1]
    return f"http://127.0.0.1:{port}/{urllib.parse.quote(path.name)}"


def stop_all():
    with _lock:
        for server, _port in _servers.values():
            server.shutdown()
            server.server_close()
        _servers.clear()
