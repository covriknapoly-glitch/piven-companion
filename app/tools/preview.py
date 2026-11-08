from __future__ import annotations

import functools
import http.server
import threading
import urllib.parse
from pathlib import Path

_servers = {}
_lock = threading.Lock()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8",
                      ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                      ".json": "application/json; charset=utf-8", ".txt": "text/plain; charset=utf-8", ".wasm": "application/wasm"}

    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def url_for(path, root=None):
    path = Path(path).resolve()
    folder = Path(root).resolve() if root else path.parent
    with _lock:
        if folder not in _servers:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_QuietHandler, directory=str(folder)))
            threading.Thread(target=server.serve_forever, name="preview-server", daemon=True).start()
            _servers[folder] = (server, server.server_address[1])
        port = _servers[folder][1]
    return f"http://127.0.0.1:{port}/{urllib.parse.quote(path.relative_to(folder).as_posix())}"


def stop_all():
    with _lock:
        for server, _port in _servers.values():
            server.shutdown()
            server.server_close()
        _servers.clear()
