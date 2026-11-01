"""Downloads that survive a lost connection: the partial file is kept, and when the network comes back
the download continues from where it stopped (HTTP Range). Only cancelling or a broken file deletes it."""
from __future__ import annotations

import http.client
import socket
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

NETWORK_ERRORS = (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, http.client.IncompleteRead,
                  http.client.RemoteDisconnected, ssl.SSLError, OSError)
WAIT_MESSAGE = "Нет связи с интернетом — загрузка продолжится сама, как только связь появится"


def is_network_error(error):
    """True for a lost connection or a server hiccup (worth waiting for), False for a real refusal."""
    if isinstance(error, urllib.error.HTTPError):
        return error.code in (408, 425, 429, 500, 502, 503, 504)
    return isinstance(error, NETWORK_ERRORS)


def fetch(url, partial: Path, headers=None, cancel_event=None, on_bytes=lambda received: None,
          on_wait=lambda message: None, chunk=4 * 1024 * 1024, timeout=60):
    """Download url into `partial`, continuing a file left by an earlier attempt. Returns the bytes on disk.
    Waits through network errors with growing pauses (up to 30 s) until it finishes or is cancelled."""
    partial.parent.mkdir(parents=True, exist_ok=True)
    pause = 2.0
    while True:
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Загрузка отменена.")
        have = partial.stat().st_size if partial.exists() else 0
        request_headers = dict(headers or {})
        if have:
            request_headers["Range"] = f"bytes={have}-"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=request_headers), timeout=timeout) as response:
                resumed = have and response.status == 206
                mode = "ab" if resumed else "wb"
                received = have if resumed else 0
                with partial.open(mode) as output:
                    on_bytes(received)
                    while True:
                        if cancel_event is not None and cancel_event.is_set():
                            raise InterruptedError("Загрузка отменена.")
                        data = response.read(chunk)
                        if not data:
                            break
                        output.write(data)
                        received += len(data)
                        on_bytes(received)
                        pause = 2.0
            return received
        except urllib.error.HTTPError as error:
            if error.code == 416 and have:  # asked past the end: the file was already complete
                return have
            if not is_network_error(error):
                raise
            wait_error = error
        except InterruptedError:
            raise
        except NETWORK_ERRORS as error:
            wait_error = error
        on_wait(WAIT_MESSAGE)
        deadline = time.monotonic() + pause
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("Загрузка отменена.")
            time.sleep(0.25)
        pause = min(pause * 2, 30.0)
        del wait_error
