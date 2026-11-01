"""Model Context Protocol servers: tools from other programs the model may call.

A server is either a command started by the program (stdio: one JSON-RPC message per line) or an address
(Streamable HTTP: JSON-RPC over POST, the answer as JSON or as server-sent events). Servers are started on
first use and stopped with the program (the Job Object kills stdio servers with it).
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request

import process_job

PROTOCOL = "2025-06-18"
CLIENT = {"name": "PIVEN Companion", "version": "1.0"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class McpError(RuntimeError):
    pass


class Server:
    """One configured server: {"name", "command" (a command line) or "url", "env": {..}, "enabled"}."""

    def __init__(self, config):
        self.config = config
        self.name = str(config.get("name") or "server")
        self._process = None
        self._next_id = 0
        self._lock = threading.Lock()
        self._session = ""      # HTTP: the Mcp-Session-Id the server gave
        self._tools = None
        self.error = ""

    # ---------- transport ----------
    def _start(self):
        command = str(self.config.get("command") or "").strip()
        if not command:
            raise McpError("не указана команда запуска")
        env = {**os.environ, **{str(k): str(v) for k, v in (self.config.get("env") or {}).items()}}
        self._replies, self._arrived = {}, threading.Condition()
        program = shlex.split(command, posix=False)[0].strip('"')
        found = shutil.which(program) or program
        if found.lower().endswith((".cmd", ".bat")):  # npx, uvx and the like are batch files on Windows
            command = f"cmd /c {command}"
        self._process = process_job.own(subprocess.Popen(command, stdin=subprocess.PIPE,
                                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
                                                         creationflags=NO_WINDOW, text=True, encoding="utf-8", bufsize=1))
        threading.Thread(target=self._read_loop, args=(self._process,), daemon=True).start()
        self._request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": CLIENT}, timeout=60)
        self._notify("notifications/initialized")

    def _read_loop(self, process):
        """The one reader of a stdio server: answers are filed by request id."""
        for line in process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue  # a log line some servers print on stdout
            if isinstance(message, dict) and "id" in message and ("result" in message or "error" in message):
                with self._arrived:
                    self._replies[message["id"]] = message
                    self._arrived.notify_all()
        with self._arrived:
            self._arrived.notify_all()

    def _wait_reply(self, wanted_id, timeout):
        deadline = time.monotonic() + timeout
        with self._arrived:
            while wanted_id not in self._replies:
                left = deadline - time.monotonic()
                if left <= 0 or self._process.poll() is not None:
                    raise McpError("сервер не ответил" if left <= 0 else "сервер закрылся")
                self._arrived.wait(min(left, 1.0))
            return self._replies.pop(wanted_id)

    def _post(self, message, timeout):
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": PROTOCOL}
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        headers.update({str(k): str(v) for k, v in (self.config.get("headers") or {}).items()})
        request = urllib.request.Request(str(self.config["url"]), data=json.dumps(message).encode("utf-8"), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                self._session = response.headers.get("Mcp-Session-Id") or self._session
                body = response.read().decode("utf-8", "replace")
                kind = response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as error:
            raise McpError(f"HTTP {error.code}") from error
        except urllib.error.URLError as error:
            raise McpError(f"нет связи: {error.reason}") from error
        if "id" not in message:
            return None
        if "text/event-stream" in kind:
            for line in body.splitlines():
                if line.startswith("data:"):
                    try:
                        data = json.loads(line[5:].strip())
                    except ValueError:
                        continue
                    if data.get("id") == message["id"]:
                        return data
            raise McpError("сервер не прислал ответ")
        return json.loads(body) if body.strip() else None

    def _request(self, method, params=None, timeout=60):
        stdio = not self.config.get("url")
        if stdio and method != "initialize" and (self._process is None or self._process.poll() is not None):
            self._start()
        with self._lock:
            self._next_id += 1
            message = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params or {}}
            if stdio:
                self._process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
                self._process.stdin.flush()
        reply = self._wait_reply(message["id"], timeout) if stdio else self._post(message, timeout)
        if not reply:
            raise McpError("пустой ответ")
        if "error" in reply:
            raise McpError(str((reply["error"] or {}).get("message") or reply["error"]))
        return reply.get("result") or {}

    def _notify(self, method):
        message = {"jsonrpc": "2.0", "method": method}
        if self.config.get("url"):
            self._post(message, 30)
        else:
            self._process.stdin.write(json.dumps(message) + "\n")
            self._process.stdin.flush()

    # ---------- protocol ----------
    def connect(self):
        if self.config.get("url") and not self._session:
            self._request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": CLIENT}, timeout=30)
            self._notify("notifications/initialized")
        elif not self.config.get("url") and (self._process is None or self._process.poll() is not None):
            self._start()

    def tools(self):
        """[{"name", "description", "inputSchema"}] of this server (asked once)."""
        if self._tools is None:
            self.connect()
            found, cursor = [], None
            while True:
                result = self._request("tools/list", {"cursor": cursor} if cursor else {})
                found += result.get("tools") or []
                cursor = result.get("nextCursor")
                if not cursor:
                    break
            self._tools = found
        return self._tools

    def call(self, tool, arguments):
        """Run a tool; returns its text output (images and other content are described in words)."""
        self.connect()
        result = self._request("tools/call", {"name": tool, "arguments": arguments or {}}, timeout=300)
        texts = []
        for item in result.get("content") or []:
            if item.get("type") == "text":
                texts.append(str(item.get("text", "")))
            elif item.get("type") == "resource":
                texts.append(str((item.get("resource") or {}).get("text", "")))
            else:
                texts.append(f"[{item.get('type', 'данные')}]")
        if result.get("structuredContent") and not texts:
            texts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
        text = "\n".join(texts).strip() or "(пустой результат)"
        return ("Ошибка инструмента: " + text) if result.get("isError") else text

    def stop(self):
        if self._process is not None and self._process.poll() is None:
            self._process.kill()
        self._process, self._session, self._tools = None, "", None


servers = {}   # {name: Server} for the enabled entries of settings["mcp_servers"]


def configure(entries):
    """Apply the settings list; servers whose configuration changed are restarted on next use."""
    wanted = {str(entry.get("name")): entry for entry in entries or [] if entry.get("enabled", True) and entry.get("name")}
    for name in list(servers):
        if name not in wanted or servers[name].config != wanted[name]:
            servers.pop(name).stop()
    for name, entry in wanted.items():
        servers.setdefault(name, Server(entry))


def stop_all():
    for server in servers.values():
        server.stop()
