from __future__ import annotations

import functools
import http.server
import threading
import urllib.parse
from pathlib import Path

_servers = {}
_lock = threading.Lock()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def url_for(path):
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
