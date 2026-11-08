from __future__ import annotations

import ast
import difflib
import fnmatch
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from app.tools.toolbox import _tool
from app.window.workspace import NO_WINDOW, _clean_env, _decode

IGNORED_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".vs", "dist", "build", ".next", ".cache", "target"}
SECRET_FILE = re.compile(r"(^|[\\/])(\.env(\..+)?|id_rsa|id_ed25519|.*\.pem|.*\.pfx|.*\.key|credentials(\.json)?|secrets?\.(json|ya?ml|toml))$", re.I)
MAX_FILE_BYTES = 2_000_000
READ_LINES = 250
READ_CHARS = 14_000
OUTPUT_CHARS = 6_000
CARD_CHARS = 5_000
LIST_LIMIT = 200
SEARCH_LIMIT = 60
COMMAND_SECONDS = 60
MODES = ("ask", "edits", "plan", "free")
CHANGING_TOOLS = ("write_file", "edit_file", "move_file", "delete_file")
CHANGE_DIR = re.compile(r"(?:^|[&|;]\s*)\s*(?:cd|chdir|pushd|set-location|sl)(?:\s+/d)?\s+(\"[^\"]+\"|'[^']+'|[^\s&|;]+)", re.I)
WRITING_COMMAND = re.compile(r"^\s*(mkdir|md|copy|xcopy|robocopy|move|ren|rename|del|erase|rd|rmdir|new-item|copy-item|move-item|remove-item|set-content|out-file)\b", re.I)
COPYING_COMMANDS = ("copy", "xcopy", "robocopy", "move", "copy-item", "move-item")
ABSOLUTE_PATH = re.compile(r"\"([A-Za-z]:[\\/][^\"]*)\"|([A-Za-z]:[\\/][^\s\"&|;<>]*)")
REDIRECT_TO_PATH = re.compile(r">>?\s*(?:\"([A-Za-z]:[\\/][^\"]*)\"|([A-Za-z]:[\\/][^\s\"&|;<>]*))")
COMMAND_MAX_SECONDS = 900
BACKGROUND_START_SECONDS = 3
OUTLINE_LIMIT = 150
OUTLINE_LINE = re.compile(r"^(?: {0,4}|\t?)(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\*?\s+[\w$]+|class\s+[\w$]+|def\s+\w+|(?:const|let|var)\s+[\w$]+(?:\s*,\s*[\w$]+)*|struct\s+\w+|fn\s+\w+)")
JUST_LOOKING = re.compile(r"^\s*(?:cd\s[^&]*&&\s*)?(?:findstr|grep|dir|ls|type|cat|more|where|echo|node\s+(?:-e|--eval|--check|--version)|python3?\s+(?:-c|--version)|git\s+(?:status|diff|log|show)|powershell\s+.*select-string|select-string|get-content)\b", re.I)
NOT_ALLOWED = "The user did not allow this change. Do not try it again; find another way or finish and explain what is needed."
SEARCHING = re.compile(r"^\s*(?:cd\s[^&]*&&\s*)?(?:findstr|grep|dir|ls|type|cat|more|where|select-string|get-content)\b", re.I)
LOOK_LIMIT = 4
ALIASES = {"file_path": "path", "filepath": "path", "filename": "path", "file": "path", "old_string": "old_text", "oldText": "old_text", "old_str": "old_text", "old": "old_text", "search": "old_text",
           "new_string": "new_text", "newText": "new_text", "new_str": "new_text", "new": "new_text", "replace": "new_text", "text": "content", "contents": "content", "cmd": "command"}

NEVER = re.compile(
    r"\bformat(?:\.com)?\s+(?:/\S+\s+)*[a-z]:|\bformat-volume\b|\bclear-disk\b|\binitialize-disk\b"
    r"|\b(?:diskpart|bcdedit|shutdown|vssadmin|takeown|schtasks|netsh|mkfs|set-executionpolicy|reg(?:\.exe)?\s+(?:add|delete|import)|sc(?:\.exe)?\s+(?:delete|create|config)|cipher\s+/w)\b"
    r"|\brm\s+-[a-z]*r[a-z]*\s+[/~]|\b(?:rd|rmdir)\s+/s\s+(?:/q\s+)?[a-z]:\\?\s*(?:$|[&|])|\bdel\s+(?:/[a-z]\s+)*[a-z]:\\\*?\s*(?:$|[&|])|\bremove-item\s+.*[a-z]:\\\*?\s+-recurse|\bremove-item\s+-recurse\s+.*[a-z]:\\\*?\s*(?:$|[&|;])"
    r"|ollamacompanion|\.ssh\b|login data|\bcredentials\b", re.I)
ALWAYS_ASK = re.compile(
    r"\b(?:pip3?\s+(?:install|uninstall)|-m\s+pip\s+(?:install|uninstall)|npm\s+(?:i|install|add|uninstall|publish|update)\b|npx\s|yarn\s+add|pnpm\s+(?:add|install)|cargo\s+install|"
    r"go\s+install|winget|choco|scoop|git\s+(?:push|reset\s+--hard|clean|remote|rebase|checkout\s+--)|curl|wget|invoke-webrequest|invoke-restmethod|iwr|irm|start-bitstransfer|"
    r"del|erase|rd|rmdir|rm|remove-item|ri|format-volume|clear-content|taskkill|stop-process)\b", re.I)
SAFE = re.compile(
    r"^\s*(?:python3?\s+(?:--version|-m\s+(?:py_compile|compileall|unittest|pytest)\b.*)|py\s+-m\s+(?:py_compile|compileall|unittest|pytest)\b.*|pytest\b.*|node\s+(?:--version|--check\s.*)|"
    r"npm\s+(?:--version|test|run\s+(?:test|build|lint|typecheck)\b.*)|tsc\b.*|git\s+(?:status|diff|log|show|branch(?:\s+--list)?)\b.*|"
    r"dir\b[^|&;<>]*|ls\b[^|&;<>]*|type\s[^|&;<>]*|where\s[^|&;<>]*|findstr\s[^|&;<>]*|grep\s[^|&;<>]*|cargo\s+(?:check|test|build)\b.*|go\s+(?:test|vet|build)\b.*|dotnet\s+(?:test|build)\b.*)\s*$", re.I)


def outline(text, limit=OUTLINE_LIMIT):
    """Declarations of a source file with line numbers."""
    rows = []
    for number, line in enumerate(str(text).splitlines(), 1):
        found = OUTLINE_LINE.match(line)
        if found:
            rows.append(f"{number}: {found.group(0).strip().rstrip('({=: ')}")
    return rows[:limit]


def command_policy(command, root):
    """Returns (verdict, reason): refuse, ask (even in a trusted project, but not in free mode), safe or normal."""
    text = str(command or "")
    if NEVER.search(text):
        return "refuse", "This command can damage the computer or touches private data, so it is not allowed."
    root_text = str(root).replace("/", "\\").rstrip("\\").lower()
    outside = text.replace("/", "\\").lower().replace(root_text, "")
    if re.search(r"(?<![a-z0-9])[a-z]:\\", outside):
        return "ask", "Команда обращается к файлу вне папки проекта"
    if re.search(r"(?:^|[\s\"'\\/])\.\.[\\/]", text):
        return "ask", "Команда обращается к файлу вне папки проекта"
    if ALWAYS_ASK.search(text):
        return "ask", "Команда скачивает, устанавливает или удаляет что-то либо меняет репозиторий"
    parts = re.split(r"\s*&&\s*", text.strip())
    if all(SAFE.match(part) or re.fullmatch(r"echo\s+[\w .-]*", part) for part in parts) and not re.search(r"[&|;<>`]|\$\(", " ".join(parts)):
        return "safe", ""
    return "normal", ""


def _inside(target, root):
    """True if the path is the project folder, something in it, or the temporary folder."""
    expanded = os.path.expandvars(str(target).strip().strip("\"'"))
    if "%" in expanded or "$" in expanded or not expanded:
        return True
    candidate = Path(expanded)
    full = os.path.normcase(os.path.abspath(candidate if candidate.is_absolute() else Path(root) / candidate))
    for folder in (str(root), tempfile.gettempdir()):
        base = os.path.normcase(os.path.abspath(folder))
        if full == base or full.startswith(base.rstrip("\\/") + os.sep):
            return True
    return False


def leaves_project(command, root):
    """The folder outside the project that a command goes to or writes to, or an empty string."""
    text = str(command or "")
    for match in CHANGE_DIR.finditer(text):
        if not _inside(match.group(1), root):
            return match.group(1).strip("\"'")
    for match in REDIRECT_TO_PATH.finditer(text):
        target = match.group(1) or match.group(2)
        if not _inside(target, root):
            return target
    for part in re.split(r"&&|\|\||[&|;]", text):
        verb = WRITING_COMMAND.match(part)
        if not verb:
            continue
        targets = [first or second for first, second in ABSOLUTE_PATH.findall(part)]
        if verb.group(1).lower() in COPYING_COMMANDS:
            targets = targets[-1:] if targets and part.rstrip().rstrip('"').endswith(targets[-1]) else []
        for target in targets:
            if not _inside(target, root):
                return target
    return ""


def syntax_problem(path, text, app_dir=None):
    """Syntax check for a file that was just written."""
    suffix = path.suffix.lower()
    try:
        if suffix in (".py", ".pyw"):
            ast.parse(text)
        elif suffix == ".json":
            json.loads(text)
    except SyntaxError as error:
        return f"Syntax error at line {error.lineno}: {error.msg}"
    except ValueError as error:
        return f"JSON error: {error}"
    if suffix in (".js", ".mjs", ".cjs"):
        node = shutil.which("node") or (str(Path(app_dir) / "runtime" / "node" / "node.exe") if app_dir and (Path(app_dir) / "runtime" / "node" / "node.exe").is_file() else "")
        if node:
            try:
                done = subprocess.run([node, "--check", str(path)], capture_output=True, timeout=15, creationflags=NO_WINDOW)
            except (OSError, subprocess.SubprocessError):
                return ""
            if done.returncode:
                lines = [line for line in _decode(done.stderr).splitlines() if line.strip()]
                where = next((line for line in lines if re.search(r":\d+\s*$", line)), "")
                what = next((line for line in lines if "Error" in line), "")
                number = where.rsplit(":", 1)[-1].strip() if where else "?"
                return f"Syntax error at line {number}: {what}"
    return ""


def _short_diff(before, after, name):
    lines = list(difflib.unified_diff(before.splitlines(), after.splitlines(), fromfile=name, tofile=name, lineterm="", n=2))[2:]
    text = "\n".join(lines)
    return text[:CARD_CHARS] + ("\n…" if len(text) > CARD_CHARS else "")


def _count_changes(diff):
    lines = diff.splitlines()
    return sum(line.startswith("+") for line in lines), sum(line.startswith("-") for line in lines)


class Job:
    def __init__(self, command, process):
        self.id = uuid.uuid4().hex[:6]
        self.command, self.process = command, process
        self.head, self.tail = bytearray(), bytearray()
        self.started = time.monotonic()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            while True:
                chunk = self.process.stdout.read1(65536) if hasattr(self.process.stdout, "read1") else self.process.stdout.read(4096)
                if not chunk:
                    return
                room = 40_000 - len(self.head)
                if room > 0:
                    self.head += chunk[:room]
                    chunk = chunk[room:]
                if chunk:
                    self.tail += chunk
                    del self.tail[:-40_000]
        except (OSError, ValueError):
            return

    def output(self, limit=OUTPUT_CHARS):
        text = _decode(bytes(self.head)) + (_decode(bytes(self.tail)) if self.tail else "")
        text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text).replace("\r\n", "\n")
        if len(text) <= limit:
            return text
        keep = limit // 3
        return f"{text[:keep]}\n… [{len(text) - limit} characters skipped] …\n{text[-(limit - keep):]}"

    def stop(self):
        if self.process.poll() is None:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.process.pid)], capture_output=True, creationflags=NO_WINDOW)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()


_jobs = {}


def stop_jobs():
    for job in list(_jobs.values()):
        job.stop()
    _jobs.clear()


def restore_checkpoint(folder):
    """Puts back what a turn changed. Files the user changed afterwards are left alone."""
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    restored, kept = [], []
    for entry in reversed(manifest["files"]):
        path = Path(entry["path"])
        final = entry.get("final")
        try:
            info = path.stat()
            current = {"size": info.st_size, "mtime": info.st_mtime_ns}
        except OSError:
            current = None
        if final is not None and current != final:
            kept.append(str(path))
            continue
        if final is None and current is not None:
            kept.append(str(path))
            continue
        if entry.get("backup"):
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(folder / entry["backup"], path)
        elif current is not None:
            path.unlink()
        restored.append(str(path))
    for name in sorted(manifest.get("folders", []), key=len, reverse=True):
        try:
            Path(name).rmdir()
        except OSError:
            pass
    return restored, kept


class CodeTools:

    def __init__(self, root, app_dir, data_dir, ask=None, trusted=False, mode=None, browser=None, web=None, vision=False, cancel=None, on_card=None, on_status=None, on_trust=None, on_edits=None):
        self.root = Path(root).resolve()
        self.app_dir, self.data_dir = Path(app_dir), Path(data_dir)
        self.ask = ask
        self.mode = mode if mode is not None else "edits"
        self.trusted = trusted
        self.browser, self.web, self.vision = browser, web, vision
        self.cancel = cancel or threading.Event()
        self.on_card = on_card or (lambda card: None)
        self.on_status = on_status or (lambda text: None)
        self.on_trust = on_trust or (lambda: None)
        self.on_edits = on_edits or (lambda: None)
        self.changes = {}
        self.plan = []
        self.pending_image = None
        self.verified = True
        self.progress = False
        self.edits = 0
        self.picture = None
        self.picture_edits = -1
        self.window_command = ""
        self.looks = 0
        self.looks_at = 0
        self.refused_looks = 0
        self.read_limit = READ_LINES
        self.checkpoint = self.data_dir / "code_checkpoints" / uuid.uuid4().hex
        self._saved = {}
        self._folders = []

    def specs(self):
        path = {"type": "string", "description": "path relative to the project folder"}
        specs = [
            _tool("list_files", "List files and folders of the project as a tree.",
                  {"path": {"type": "string", "description": "folder, default the project folder"}, "pattern": {"type": "string", "description": "optional name filter such as *.js"}}),
            _tool("read_file", f"Read a text file with line numbers, up to {self.read_limit} lines at a time.",
                  {"path": path, "offset": {"type": "integer", "description": "first line, from 1"}, "limit": {"type": "integer"}}, ["path"]),
            _tool("outline", "List the functions, classes and variables of a source file with their line numbers. The cheap way to find your way around a file before reading parts of it.", {"path": path}, ["path"]),
            _tool("write_file", "Create a file or replace its whole content; missing folders are created. Set append to add the content to the end, which is how a long file is written in several parts.",
                  {"path": path, "content": {"type": "string"}, "append": {"type": "boolean"}}, ["path", "content"]),
            _tool("edit_file", "Replace an exact piece of text in a file. old_text must match the file and be unique, so include enough surrounding lines. Prefer this over rewriting a file.",
                  {"path": path, "old_text": {"type": "string"}, "new_text": {"type": "string"}, "replace_all": {"type": "boolean"}}, ["path", "old_text", "new_text"]),
            _tool("search", "Search the project's text files with a regular expression. Returns file:line: text.",
                  {"pattern": {"type": "string"}, "path": {"type": "string"}, "glob": {"type": "string", "description": "optional file filter such as *.py"}}, ["pattern"]),
            _tool("run_command", "Run a command on Windows. It already runs in the project folder, so do not cd there, and folders for files are created by write_file. The shell is cmd unless shell is powershell. Output and exit code come back. "
                  "A program that keeps running (a game window, a server) needs background: true, otherwise it is stopped at the timeout.",
                  {"command": {"type": "string"}, "timeout": {"type": "integer", "description": f"seconds, default {COMMAND_SECONDS}, at most {COMMAND_MAX_SECONDS}"},
                   "background": {"type": "boolean"}, "shell": {"type": "string", "enum": ["cmd", "powershell"]}}, ["command"]),
            _tool("command_status", "Read the output of a background command, or stop it.",
                  {"id": {"type": "string"}, "stop": {"type": "boolean"}}, ["id"]),
            _tool("inspect_api", "Show what a Python library really offers: its functions, classes, attributes and signatures, from the installed package. Use it instead of guessing a name: before you use a library you do not know well, and whenever an AttributeError, NameError, ImportError or TypeError names something from a library. name is dotted, for example ursina.mouse or pygame.Rect; match narrows the list to names containing that text.",
                  {"name": {"type": "string"}, "match": {"type": "string"}}, ["name"]),
            _tool("move_file", "Move or rename a file or folder inside the project.", {"source": path, "destination": path}, ["source", "destination"]),
            _tool("delete_file", "Delete a file from the project. It can be restored with the undo button.", {"path": path}, ["path"]),
            _tool("update_plan", "Set the task list the user sees. Call it first on a task with several steps and again as steps finish.",
                  {"items": {"type": "array", "items": {"type": "object", "properties": {"text": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "done"]}}, "required": ["text", "status"]}}}, ["items"]),
        ]
        if self.browser is not None:
            specs.append(_tool("check_page", "Open an HTML file of the project in a hidden browser and report JavaScript errors, failed files, the page text and whether each canvas draws anything. "
                               + ("Set screenshot to look at the page. " if self.vision else "") + "Every call loads the page anew, so nothing carries over between calls: do all steps of a test in one call. "
                               "script is the body of a JavaScript function run after loading; press('ArrowUp'), click('#start') and the mouse are available in it: clickAt(x, y, button) clicks a point in pixels, or as 0-1 shares of the window, and says what it hit; button is 'left', 'right' or 'middle'. moveMouse(dx, dy) moves it, which also turns the camera of a 3D game; drag(x1, y1, x2, y2) drags. Pointer lock always succeeds here. It cannot wait, so read the result of those actions in after_script, which runs after_seconds later. Both can return a value. Variables inside the page's own functions cannot be reached, only what is global or on the page.",
                               {"path": path, "wait_seconds": {"type": "number", "description": "how long the page runs before script, default 2"}, "script": {"type": "string"}, "after_seconds": {"type": "number", "description": "default 1"}, "after_script": {"type": "string"},
                                "explore": {"type": "boolean", "description": "default true: after your scripts every button and control is pressed once and reported; set false to skip"},
                                **({"screenshot": {"type": "boolean"}} if self.vision else {})}, ["path"]))
        specs.append(_tool("check_window", "Start a program with a window (pygame, Ursina, tkinter and so on), press things in it and look at it, then close it. It reports whether the program stayed alive, its window size and what it printed. "
                           + ("Set screenshot to see the window. " if self.vision else "") + "steps run in order, for example: \"click 0.5 0.5\" (pixels, or 0-1 shares of the window), \"click 100 200 right\", \"drag 10 10 90 90\", \"key w 0.5\" (hold for seconds), \"key space\", \"wait 2\". "
                           "The camera of a game that captures the mouse cannot be turned this way. Use run_command for programs without a window.",
                           {"command": {"type": "string", "description": "for example python game.py"}, "steps": {"type": "array", "items": {"type": "string"}}, "wait_seconds": {"type": "number", "description": "how long the program runs before the steps, default 3"},
                            **({"screenshot": {"type": "boolean"}} if self.vision else {})}, ["command"]))
        if self.web is not None:
            specs.append(_tool("web_search", "Search the internet for documentation or current facts.", {"query": {"type": "string"}}, ["query"]))
        if self._current_mode() == "plan":
            specs = [spec for spec in specs if spec["function"]["name"] not in (*CHANGING_TOOLS, "check_window")]
        return specs

    def _path(self, raw, must_exist=False):
        raw = str(raw or ".").strip().strip('"')
        candidate = Path(os.path.expandvars(raw)).expanduser()
        path = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError(f"{raw} is outside the project folder {self.root}. Work only inside it; to work elsewhere the user must change the project folder.")
        if must_exist and not path.exists():
            hint = self._similar(path)
            raise ValueError(f"{self._show(path)} does not exist.{hint}")
        return path

    def _similar(self, path):
        names = [str(item.relative_to(self.root)).replace("\\", "/") for item in self._walk() if item.is_file()]
        close = difflib.get_close_matches(str(path.name), [Path(name).name for name in names], n=3, cutoff=0.5)
        found = [name for name in names if Path(name).name in close][:3]
        return f" Similar files: {', '.join(found)}." if found else ""

    def _show(self, path):
        try:
            return str(path.relative_to(self.root)).replace("\\", "/") or "."
        except ValueError:
            return str(path)

    def _walk(self, folder=None):
        for current, dirs, files in os.walk(folder or self.root):
            dirs[:] = sorted(name for name in dirs if name not in IGNORED_DIRS)
            base = Path(current)
            for name in dirs:
                yield base / name
            for name in sorted(files):
                yield base / name

    def _secret(self, path):
        if SECRET_FILE.search(str(path)):
            raise ValueError(f"{self._show(path)} looks like a file with secrets, so the agent may not touch it.")

    def _remember(self, path):
        """Keeps the state before the first change of a file, for the undo button."""
        key = str(path)
        if key in self._saved:
            return
        self.checkpoint.mkdir(parents=True, exist_ok=True)
        backup = ""
        if path.is_file():
            backup = f"{len(self._saved)}.bak"
            shutil.copy2(path, self.checkpoint / backup)
        self._saved[key] = backup
        missing, parent = [], path.parent
        while parent != self.root and self.root in parent.parents and not parent.exists():
            missing.append(str(parent))
            parent = parent.parent
        self._folders += missing
        self._write_manifest()

    def _write_manifest(self):
        files = []
        for key, backup in self._saved.items():
            try:
                info = Path(key).stat()
                final = {"size": info.st_size, "mtime": info.st_mtime_ns}
            except OSError:
                final = None
            files.append({"path": key, "backup": backup, "final": final})
        self.checkpoint.mkdir(parents=True, exist_ok=True)
        (self.checkpoint / "manifest.json").write_text(json.dumps({"root": str(self.root), "files": files, "folders": self._folders}, ensure_ascii=False), encoding="utf-8")

    def finish(self):
        """Fixes the final state of the files, so undo can tell later whether the user changed them. Returns the changed files."""
        if self._saved:
            self._write_manifest()
        return [{"path": path, "state": state} for path, state in self.changes.items()]

    def run(self, name, arguments):
        arguments = arguments if isinstance(arguments, dict) else {}
        arguments = {ALIASES.get(key, key): value for key, value in arguments.items()}
        if "_raw" in arguments:
            if name != "write_file":
                return "Error: the arguments of this call were cut off or are not valid JSON, so nothing was done. Make the call again, shorter."
            return ("Error: the arguments of this call were cut off or are not valid JSON, so nothing was done. The content was probably too long for one call: "
                    "write the file in smaller parts, first write_file with the beginning, then write_file with append: true for each next part.")
        method = getattr(self, f"_tool_{name}", None)
        if method is None or (name == "check_page" and self.browser is None) or (name == "web_search" and self.web is None):
            return f"Error: there is no tool named {name}."
        try:
            return method(arguments)
        except InterruptedError:
            raise
        except (ValueError, OSError, RuntimeError, TimeoutError) as error:
            return f"Error: {error}"

    def _python(self):
        for candidate in (self.root / ".venv" / "Scripts" / "python.exe", self.root / "venv" / "Scripts" / "python.exe"):
            if candidate.is_file():
                return str(candidate)
        return shutil.which("python") or shutil.which("py")

    def _probe(self, *arguments, timeout=40):
        """Runs api_probe.py under the project's Python."""
        python = self._python()
        if not python:
            return None
        env = _clean_env()
        env.update(SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy", PYTHONIOENCODING="utf-8")
        try:
            done = subprocess.run([python, "-X", "utf8", str(Path(__file__).with_name("api_probe.py")), arguments[0], str(self.root), *arguments[1:]],
                                  capture_output=True, timeout=timeout, cwd=str(self.root), env=env, creationflags=NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            return None
        marker = done.stdout.rfind(b"@@RESULT@@")
        if marker < 0:
            return None
        try:
            return json.loads(done.stdout[marker + 10:].decode("utf-8", "replace"))
        except ValueError:
            return None

    def _api_problem(self, path, text):
        """Library names used by the file that do not exist."""
        if path.suffix.lower() not in (".py", ".pyw") or not re.search(r"^\s*(?:import|from)\s", text, re.M):
            return ""
        found = self._probe("check", str(path))
        if not found or not isinstance(found, list):
            return ""
        return " API check, these names do not exist in the installed libraries (fix all of them; inspect_api shows the real ones):\n" + "\n".join("- " + item for item in found[:8])

    def _tool_inspect_api(self, arguments):
        name = str(arguments.get("name") or "").strip()
        if not re.fullmatch(r"[A-Za-z_][\w.]*", name):
            raise ValueError("name must be dotted, for example ursina.mouse.")
        self.progress = True
        report = self._probe("inspect", name, str(arguments.get("match") or ""))
        if report is None:
            raise RuntimeError("Python is not available to look this up. Use web_search or read the library's documentation instead.")
        return str(report)[:5000]

    def _tool_list_files(self, arguments):
        folder = self._path(arguments.get("path", "."), must_exist=True)
        if not folder.is_dir():
            raise ValueError(f"{self._show(folder)} is a file, not a folder.")
        pattern = str(arguments.get("pattern") or "")
        rows = []
        total = 0
        for item in self._walk(folder):
            if pattern and not fnmatch.fnmatch(item.name, pattern):
                continue
            total += 1
            if len(rows) >= LIST_LIMIT:
                continue
            shown = self._show(item)
            if item.is_dir():
                rows.append(shown + "/")
            else:
                try:
                    rows.append(f"{shown} ({item.stat().st_size} bytes)")
                except OSError:
                    rows.append(shown)
        self.on_card({"kind": "read", "title": f"Смотрит файлы: {self._show(folder)}"})
        if not rows:
            return "No files match." if pattern else "The folder is empty."
        return "\n".join(rows) + (f"\n… and {total - LIST_LIMIT} more" if total > LIST_LIMIT else "")

    def _text(self, path):
        self._secret(path)
        if not path.is_file():
            raise ValueError(f"{self._show(path)} is not a file.{self._similar(path)}")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError(f"{self._show(path)} is larger than 2 MB. Use search to find the needed part.")
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            raise ValueError(f"{self._show(path)} is a binary file.")
        for encoding in ("utf-8-sig", "cp1251"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", "replace")

    def _tool_read_file(self, arguments):
        path = self._path(arguments.get("path"), must_exist=True)
        lines = self._text(path).splitlines()
        start = max(1, int(arguments.get("offset") or 1))
        count = max(1, min(self.read_limit, int(arguments.get("limit") or self.read_limit)))
        chosen, size = [], 0
        for number, line in enumerate(lines[start - 1:start - 1 + count], start):
            row = f"{number}|{line[:400]}"
            size += len(row) + 1
            if size > READ_CHARS and chosen:
                break
            chosen.append(row)
        self.on_card({"kind": "read", "title": f"Читает {self._show(path)}"})
        if not lines:
            return "The file is empty."
        last = start + len(chosen) - 1
        more = f"\n[lines {start}-{last} of {len(lines)}; read further with offset {last + 1}]" if last < len(lines) else ""
        return "\n".join(chosen) + more

    def _tool_outline(self, arguments):
        path = self._path(arguments.get("path"), must_exist=True)
        text = self._text(path)
        rows = outline(text)
        self.on_card({"kind": "read", "title": f"Смотрит оглавление {self._show(path)}"})
        return f"{self._show(path)}, {text.count(chr(10)) + 1} lines:\n" + ("\n".join(rows) if rows else "No declarations found.")

    def _store(self, path, text):
        temporary = path.with_name(path.name + ".piven-tmp")
        with temporary.open("w", encoding="utf-8", newline="") as file:
            file.write(text)
        temporary.replace(path)
        self.verified = False
        self.progress = True
        self.edits += 1

    def _tool_write_file(self, arguments):
        path = self._path(arguments.get("path"))
        self._secret(path)
        if path.is_dir():
            raise ValueError(f"{self._show(path)} is a folder.")
        content = str(arguments.get("content", ""))
        append = bool(arguments.get("append"))
        before = self._text(path) if path.exists() else None
        if not self._allow_change(path, content[:1500]):
            return NOT_ALLOWED
        self._remember(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = (before or "") + content if append else content
        self._store(path, text)
        state = "created" if self.changes.get(str(path)) == "created" or (before is None and self._saved[str(path)] == "") else "edited"
        self.changes[str(path)] = state
        shown = self._show(path)
        lines = text.count("\n") + 1
        diff = _short_diff(before or "", text, shown) if before is not None else "\n".join("+" + line for line in content.splitlines())[:CARD_CHARS]
        self.on_card({"kind": "write", "title": ("Дописывает " if append else "Создаёт " if before is None else "Перезаписывает ") + shown, "path": str(path), "diff": diff,
                      "added": content.count("\n") + 1 if before is None or append else _count_changes(diff)[0], "removed": 0 if before is None or append else _count_changes(diff)[1]})
        problem = syntax_problem(path, text, self.app_dir)
        note = f" {problem}. It can also just be an unfinished file: ignore this if you are going to append more." if problem and (append or not text.rstrip().endswith(("}", ")", ">", ";"))) else (f" {problem}. Fix it." if problem else "")
        if not problem and not append:
            note += self._api_problem(path, text)
        return f"{'Appended to' if append else 'Wrote'} {shown}, now {lines} lines.{note}"

    def _tool_edit_file(self, arguments):
        path = self._path(arguments.get("path"), must_exist=True)
        before = self._text(path)
        old, new = str(arguments.get("old_text", "")), str(arguments.get("new_text", ""))
        if old.lstrip().startswith("[removed to save memory") or new.lstrip().startswith("[removed to save memory"):
            raise ValueError("old_text or new_text is a placeholder from the memory cleanup, not real text. Read the part of the file with read_file and copy the real lines.")
        if not old:
            raise ValueError("old_text is empty. To add to a file, use a nearby line as old_text, or write_file with append.")
        if old == new:
            raise ValueError("old_text and new_text are the same.")
        newline = "\r\n" if "\r\n" in before else "\n"
        text = before.replace("\r\n", "\n")
        old, new = old.replace("\r\n", "\n"), new.replace("\r\n", "\n")
        count = text.count(old)
        if count == 0:
            matched = self._loose_match(text, old)
            if matched is None:
                raise ValueError(f"old_text was not found in {self._show(path)}. {self._closest(text, old)} Read the file again and copy the text exactly.")
            old, count = matched, 1
        if count > 1 and not arguments.get("replace_all"):
            places = [text[:match.start()].count("\n") + 1 for match in re.finditer(re.escape(old), text)][:8]
            raise ValueError(f"old_text occurs {count} times, at lines {places}. Add surrounding lines to make it unique, or set replace_all.")
        if not self._allow_change(path, f"- {old[:700]}\n+ {new[:700]}"):
            return NOT_ALLOWED
        self._remember(path)
        after = text.replace(old, new) if arguments.get("replace_all") else text.replace(old, new, 1)
        self._store(path, after.replace("\n", newline) if newline != "\n" else after)
        self.changes.setdefault(str(path), "edited")
        shown = self._show(path)
        diff = _short_diff(text, after, shown)
        added, removed = _count_changes(diff)
        self.on_card({"kind": "edit", "title": f"Правит {shown}", "path": str(path), "diff": diff, "added": added, "removed": removed})
        line = text[:text.find(old)].count("\n") + 1
        problem = syntax_problem(path, after, self.app_dir)
        return f"Edited {shown} at line {line}" + (f", {count} places." if count > 1 else ".") + (f" {problem}. Fix it." if problem else self._api_problem(path, after))

    @staticmethod
    def _loose_match(text, old):
        """Matches ignoring indentation when the match is unique."""
        wanted = [line.strip() for line in old.strip("\n").split("\n")]
        lines = text.split("\n")
        hits = [start for start in range(len(lines) - len(wanted) + 1)
                if all(lines[start + offset].strip() == wanted[offset] for offset in range(len(wanted)))]
        return "\n".join(lines[hits[0]:hits[0] + len(wanted)]) if len(hits) == 1 else None

    @staticmethod
    def _closest(text, old):
        first = next((line for line in old.split("\n") if line.strip()), "")
        lines = text.split("\n")
        close = difflib.get_close_matches(first, lines, n=1, cutoff=0.6)
        if not close:
            return ""
        number = lines.index(close[0])
        around = "\n".join(f"{index + 1}|{lines[index][:200]}" for index in range(max(0, number - 1), min(len(lines), number + 4)))
        return f"The closest place:\n{around}\n"

    def _tool_search(self, arguments):
        pattern = str(arguments.get("pattern") or arguments.get("query") or "")
        if not pattern:
            raise ValueError("pattern is empty.")
        try:
            regex = re.compile(pattern, re.I)
        except re.error:
            regex = re.compile(re.escape(pattern), re.I)
        folder = self._path(arguments.get("path", "."), must_exist=True)
        wanted = str(arguments.get("glob") or "")
        rows, total = [], 0
        for item in (self._walk(folder) if folder.is_dir() else [folder]):
            if not item.is_file() or (wanted and not fnmatch.fnmatch(item.name, wanted)) or SECRET_FILE.search(str(item)):
                continue
            try:
                if item.stat().st_size > 500_000:
                    continue
                data = item.read_bytes()
                if b"\0" in data[:4096]:
                    continue
                text = data.decode("utf-8-sig", "replace")
            except OSError:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    total += 1
                    if len(rows) < SEARCH_LIMIT:
                        rows.append(f"{self._show(item)}:{number}: {line.strip()[:200]}")
        self.on_card({"kind": "read", "title": f"Ищет: {pattern}"[:120]})
        if not rows:
            return "No matches."
        return "\n".join(rows) + (f"\n… {total} matches in all; narrow the search" if total > SEARCH_LIMIT else "")

    def _environment(self):
        env = {key: value for key, value in _clean_env().items() if not re.search(r"TOKEN|SECRET|API_?KEY|PASSWORD", key, re.I)}
        extra = [self.app_dir / "runtime" / "Python311", self.app_dir / "runtime" / "Python311" / "Scripts", self.app_dir / "runtime" / "node"]
        env["PATH"] = os.pathsep.join([env.get("PATH", "")] + [str(folder) for folder in extra if folder.is_dir()])
        env.update({"PYTHONUTF8": "1", "PIP_REQUIRE_VIRTUALENV": "1", "PYTHONDONTWRITEBYTECODE": "1", "NO_COLOR": "1", "FORCE_COLOR": "0", "CI": "1", "npm_config_yes": "false"})
        return env

    def _allow_change(self, path, preview):
        mode = self._current_mode()
        if mode == "plan":
            raise ValueError("Plan mode: nothing may be changed yet. Finish with your plan as the final message.")
        if mode != "ask":
            return True
        if self.ask is None:
            raise ValueError("Changes that need the user's permission cannot be made here.")
        answer = self.ask(f"{self._show(path)}\n\n{preview}", "Агент хочет изменить файл", True, "edit")
        if answer == "project":
            if not callable(self.mode):
                self.mode = "edits"
            self.on_edits()
        if not answer:
            self.on_card({"kind": "command", "title": f"Изменение {self._show(path)}", "output": "Пользователь не разрешил это изменение.", "exit": None, "denied": True})
        return bool(answer)

    def _is_trusted(self):
        return bool(self.trusted() if callable(self.trusted) else self.trusted)

    def _current_mode(self):
        mode = self.mode() if callable(self.mode) else self.mode
        return mode if mode in MODES else "ask"

    def _permitted(self, command):
        verdict, reason = command_policy(command, self.root)
        if verdict == "refuse":
            raise ValueError(reason)
        outside = leaves_project(command, self.root)
        if outside:
            raise ValueError(f"{outside} is outside the project folder {self.root}. Work only inside it and do not look for or continue other projects; to work elsewhere the user must change the project folder.")
        mode = self._current_mode()
        if mode == "plan" and verdict != "safe":
            raise ValueError("Plan mode: only read-only commands run. Finish with your plan as the final message.")
        if verdict == "safe" or mode == "free" or (verdict == "normal" and self._is_trusted()):
            return True
        if self.ask is None:
            raise ValueError("Commands that need the user's permission cannot be run here.")
        answer = self.ask(command, reason, verdict == "normal")
        if answer == "project":
            self.trusted = True if not callable(self.trusted) else self.trusted
            self.on_trust()
        return bool(answer)

    def _start(self, command, shell):
        if shell == "powershell":
            import base64
            encoded = base64.b64encode(("[Console]::OutputEncoding=[Text.Encoding]::UTF8\n" + command).encode("utf-16-le")).decode("ascii")
            line = f"powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand {encoded}"
        else:
            line = f'cmd /d /s /c "chcp 65001>nul & {command}"'
        process = subprocess.Popen(line, cwd=str(self.root), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   creationflags=NO_WINDOW, env=self._environment())
        job = Job(command, process)
        _jobs[job.id] = job
        return job

    def _tool_run_command(self, arguments):
        command = str(arguments.get("command", "")).strip()
        if not command:
            raise ValueError("command is empty.")
        if SEARCHING.match(command):
            if self.looks_at != self.edits:
                self.looks, self.looks_at, self.refused_looks = 0, self.edits, 0
            self.looks += 1
            if self.looks > LOOK_LIMIT:
                self.refused_looks += 1
                self.on_card({"kind": "read", "title": "Пропускает повторный поиск по файлам"})
                return (f"Not run: you have searched {LOOK_LIMIT} times since the last change and searching again will not help. Use what you already found: "
                        "change the file with edit_file, read one part with read_file (offset, limit), or finish with your message to the user.")
        if not self._permitted(command):
            self.on_card({"kind": "command", "title": command, "output": "Пользователь не разрешил эту команду.", "exit": None, "denied": True})
            return "The user did not allow this command. Do not try it again; find another way or finish and explain what is needed."
        timeout = max(1, min(COMMAND_MAX_SECONDS, int(arguments.get("timeout") or COMMAND_SECONDS)))
        background = bool(arguments.get("background"))
        self.on_status(f"Запускает: {command[:80]}")
        job = self._start(command, "powershell" if arguments.get("shell") == "powershell" else "cmd")
        deadline = time.monotonic() + (BACKGROUND_START_SECONDS if background else timeout)
        while job.process.poll() is None and time.monotonic() < deadline:
            if self.cancel.is_set():
                job.stop()
                _jobs.pop(job.id, None)
                raise InterruptedError("Запрос прерван пользователем")
            time.sleep(0.1)
        seconds = round(time.monotonic() - job.started, 1)
        if job.process.poll() is None and background:
            self.on_card({"kind": "command", "title": command, "output": job.output(CARD_CHARS), "exit": None, "seconds": seconds, "background": True})
            return f"Started in the background with id {job.id} and still running. Output so far:\n{job.output()}\nUse command_status to read more or stop it."
        if job.process.poll() is None:
            job.stop()
            _jobs.pop(job.id, None)
            self.on_card({"kind": "command", "title": command, "output": job.output(CARD_CHARS), "exit": None, "seconds": seconds, "stopped": True})
            return (f"Still running after {timeout} s, so it was stopped. A program that keeps running needs background: true; a slow one needs a larger timeout. "
                    f"Output so far:\n{job.output()}")
        job.reader.join(timeout=2)
        _jobs.pop(job.id, None)
        code = job.process.returncode
        output = job.output()
        if not JUST_LOOKING.match(command):
            self.progress = True
            if code == 0:
                self.verified = True
        self.on_card({"kind": "command", "title": command, "output": job.output(CARD_CHARS), "exit": code, "seconds": seconds})
        return f"Exit code {code}, {seconds} s.\n{output}" if output.strip() else f"Exit code {code}, {seconds} s, no output."

    def _tool_command_status(self, arguments):
        job = _jobs.get(str(arguments.get("id", "")))
        if job is None:
            raise ValueError("There is no running command with this id.")
        if arguments.get("stop"):
            job.stop()
            _jobs.pop(job.id, None)
            return f"Stopped. Last output:\n{job.output()}"
        running = job.process.poll() is None
        if not running:
            _jobs.pop(job.id, None)
        return f"{'Still running' if running else f'Finished with exit code {job.process.returncode}'}.\n{job.output()}"

    def _tool_move_file(self, arguments):
        source = self._path(arguments.get("source"), must_exist=True)
        destination = self._path(arguments.get("destination"))
        self._secret(source)
        self._secret(destination)
        if destination.exists():
            raise ValueError(f"{self._show(destination)} already exists.")
        if source.is_dir():
            raise ValueError("Move files one at a time, this tool does not move whole folders.")
        if not self._allow_change(source, f"-> {self._show(destination)}"):
            return NOT_ALLOWED
        self._remember(source)
        self._remember(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.replace(destination)
        self.changes[str(source)] = "deleted"
        self.changes[str(destination)] = "created"
        self.progress = True
        self.edits += 1
        self.on_card({"kind": "edit", "title": f"Переносит {self._show(source)} → {self._show(destination)}", "path": str(destination)})
        return f"Moved to {self._show(destination)}."

    def _tool_delete_file(self, arguments):
        path = self._path(arguments.get("path"), must_exist=True)
        self._secret(path)
        if path.is_dir():
            raise ValueError("Only files can be deleted with this tool, one at a time.")
        if not self._allow_change(path, "(delete)"):
            return NOT_ALLOWED
        self._remember(path)
        path.unlink()
        self.changes[str(path)] = "deleted"
        self.progress = True
        self.edits += 1
        self.on_card({"kind": "edit", "title": f"Удаляет {self._show(path)}"})
        return f"Deleted {self._show(path)}."

    def _tool_update_plan(self, arguments):
        items = []
        for item in arguments.get("items") or []:
            if isinstance(item, dict) and str(item.get("text", "")).strip():
                status = str(item.get("status", "pending"))
                items.append({"text": str(item["text"]).strip()[:160], "status": status if status in ("pending", "in_progress", "done") else "pending"})
        if not items:
            raise ValueError("The plan has no items.")
        self.plan = items[:20]
        self.on_card({"kind": "plan", "items": self.plan})
        return "Plan updated. Keep working."

    def _tool_check_page(self, arguments):
        from app.tools import preview
        path = self._path(arguments.get("path"), must_exist=True)
        if not path.is_file() or path.suffix.lower() not in (".html", ".htm"):
            raise ValueError("check_page needs an .html file.")
        self.on_status(f"Проверяет страницу {self._show(path)}")
        wait = max(0.5, min(30.0, float(arguments.get("wait_seconds") or 2)))
        report = self.browser.check_page(preview.url_for(path, self.root), wait, str(arguments.get("script") or ""), bool(arguments.get("screenshot")) and self.vision,
                                         max(0.5, min(30.0, float(arguments.get("after_seconds") or 1))), str(arguments.get("after_script") or ""), arguments.get("explore") is not False)
        errors = report.get("errors") or []
        page = report.get("page") or {}
        canvases = page.get("canvases") or []
        rows = [f"JavaScript errors and failed files ({len(errors)}):" + "".join(f"\n- {error}" for error in errors[:12])]
        rows.append(f"Title: {page.get('title', '')}. Elements: {page.get('elements', 0)}. Page size: {page.get('size')}.")
        for canvas in canvases[:4]:
            state = "unknown (WebGL or not readable)" if canvas.get("blank") is None else "a single colour, nothing drawn yet" if canvas.get("blank") else "has a picture"
            rows.append(f"Canvas {canvas.get('width')}x{canvas.get('height')}: {state}.")
        if "moving" in report:
            rows.append("The canvas changed while watching, so it is animating." if report["moving"] else "The canvas did not change while watching: it is waiting for input or stuck.")
        clicks = report.get("clicks")
        if clicks and clicks.get("rows"):
            rows.append(f"Every control was pressed once ({len(clicks['rows'])}): {clicks.get('dead', 0)} did nothing, {clicks.get('broken', 0)} raised errors. "
                        "Each one that did nothing or failed is a bug to fix now (look at the errors above, a missing handler, an element on top):\n" + "\n".join("- " + row for row in clicks["rows"]))
        elif clicks is not None:
            rows.append("No buttons or other controls were found to press.")
        rows.append("Visible text: " + (" ".join(str(page.get("text", "")).split())[:800] or "(none)"))
        if report.get("script") is not None:
            rows.append(f"Script result: {str(report['script'])[:1500]}")
        if report.get("after") is not None:
            rows.append(f"After script result: {str(report['after'])[:1500]}")
        ok = not errors and not (clicks or {}).get("dead") and not (clicks or {}).get("broken")
        self.progress = True
        if ok:
            self.verified = True
        if report.get("image"):
            self.pending_image = report["image"]
        if report.get("picture"):
            self.picture, self.picture_edits = report["picture"], self.edits
        self.on_card({"kind": "page", "title": f"Проверяет страницу {self._show(path)}", "output": "\n".join(rows)[:CARD_CHARS], "exit": 0 if ok else 1, "path": str(path)})
        return "\n".join(rows)[:OUTPUT_CHARS]

    def _tool_check_window(self, arguments):
        from app.tools import desktop
        command = str(arguments.get("command", "")).strip()
        if not command:
            raise ValueError("command is empty.")
        if not self._permitted(command):
            self.on_card({"kind": "command", "title": command, "output": "Пользователь не разрешил эту команду.", "exit": None, "denied": True})
            return "The user did not allow this command. Do not try it again; find another way or finish and explain what is needed."
        self.window_command = command
        self.on_status(f"Проверяет окно: {command[:80]}")
        job = self._start(command, "cmd")
        rows, window, image, blank = [], None, None, True
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline and job.process.poll() is None and not self.cancel.is_set():
                window = desktop.find_window(job.process.pid)
                if window:
                    break
                time.sleep(0.2)
            if window:
                pause = time.monotonic() + max(0.5, min(30.0, float(arguments.get("wait_seconds") or 3)))
                while time.monotonic() < pause and not self.cancel.is_set():
                    time.sleep(0.05)
                for step in list(arguments.get("steps") or [])[:40]:
                    if self.cancel.is_set() or job.process.poll() is not None:
                        break
                    rows.append(desktop.run_step(window, step, self.cancel.is_set))
                time.sleep(0.5)
                if job.process.poll() is None:
                    image, blank = desktop.picture(window)
                    width, height = desktop.client_size(window)
                    rows.insert(0, f"Window «{desktop.title(window)}», {width}x{height}.")
            alive = job.process.poll() is None
            code = job.process.poll()
        finally:
            job.stop()
        if self.cancel.is_set():
            raise InterruptedError("Запрос прерван пользователем")
        output = job.output()
        failed = not window or not alive or "Traceback (most recent call last)" in output
        rows.insert(0, ("The program is still running." if alive else f"The program exited with code {code}." ) + ("" if window else " It never opened a window."))
        if image and blank:
            rows.append("The window picture is a single colour: it may draw nothing, or its 3D view could not be captured while it was behind other windows.")
        rows.append("Printed:\n" + (output.strip() or "(nothing)"))
        report = "\n".join(rows)
        self.progress = True
        if not failed:
            self.verified = True
        if image:
            self.picture, self.picture_edits = image, self.edits
            if arguments.get("screenshot") and self.vision:
                self.pending_image = image
        self.on_card({"kind": "page", "title": f"Проверяет окно: {command}"[:120], "output": report[:CARD_CHARS], "exit": 1 if failed else 0})
        return report[:OUTPUT_CHARS]

    def _tool_web_search(self, arguments):
        query = str(arguments.get("query", "")).strip()
        self.on_card({"kind": "read", "title": f"Ищет в интернете: {query}"[:120]})
        return self.web(query)
