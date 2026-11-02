from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path


_user32 = ctypes.windll.user32 if os.name == "nt" else None
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010
_MOUSEEVENTF_WHEEL = 0x0800
_PROJECT_IGNORED_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", ".next", ".tox", "архив"}


def _is_sensitive_project_file(path: Path) -> bool:
    name = path.name.casefold()
    if name in {".env", ".env.local", ".env.development", ".env.production", "id_rsa", "id_ed25519", "credentials", "secrets.json"}:
        return True
    if name.startswith(".env.") and name not in {".env.example", ".env.sample", ".env.template"}:
        return True
    return path.suffix.casefold() in {".pem", ".key", ".p12", ".pfx"}

_KEYS = {
    "ENTER": 0x0D, "TAB": 0x09, "ESC": 0x1B, "ESCAPE": 0x1B,
    "BACKSPACE": 0x08, "DELETE": 0x2E, "SPACE": 0x20,
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
    "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "CTRL": 0x11, "CONTROL": 0x11, "ALT": 0x12, "SHIFT": 0x10,
    "WIN": 0x5B, "LWIN": 0x5B,
}
_KEYS.update({chr(code): code for code in range(ord("A"), ord("Z") + 1)})
_KEYS.update({str(code - 0x60): code for code in range(0x60, 0x6A)})
_KEYS.update({f"F{number}": 0x70 + number - 1 for number in range(1, 25)})
_KEYS.update({"CAPSLOCK": 0x14, "PRINTSCREEN": 0x2C, "INSERT": 0x2D,
              "BACK": 0xA6, "FORWARD": 0xA7, "WINDOWS": 0x5B})


def _send_key(vk: int, key_up: bool = False) -> None:
    flags = _KEYEVENTF_KEYUP if key_up else 0
    _user32.keybd_event(vk, 0, flags, 0)


def _type_text(text: str) -> None:
    if len(text) > 2000:
        raise ValueError("За один раз можно ввести не более 2000 символов.")
    for char in text:
        encoded = char.encode("utf-16-le", errors="surrogatepass")
        for offset in range(0, len(encoded), 2):
            scan = int.from_bytes(encoded[offset:offset + 2], "little")
            _user32.keybd_event(0, scan, _KEYEVENTF_UNICODE, 0)
            _user32.keybd_event(0, scan, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP, 0)


def _key_combo(value: str) -> None:
    keys = [part.strip().upper() for part in value.split("+") if part.strip()]
    if not keys or len(keys) > 4 or any(key not in _KEYS for key in keys):
        raise ValueError("Сочетание клавиш не поддерживается.")
    pressed = []
    try:
        for key in keys:
            vk = _KEYS[key]
            _send_key(vk)
            pressed.append(vk)
        _send_key(pressed[-1], True)
        pressed.pop()
    finally:
        for vk in reversed(pressed):
            _send_key(vk, True)


def _activate_window(title_hint: str) -> str:
    hint = title_hint.strip().casefold()
    if not hint or len(hint) > 100:
        raise ValueError("Укажи короткую часть заголовка окна.")
    matches = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def collect(hwnd, _):
        if not _user32.IsWindowVisible(hwnd):
            return True
        length = _user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, title, length + 1)
        if hint in title.value.casefold():
            matches.append((hwnd, title.value))
        return True

    _user32.EnumWindows(callback_type(collect), 0)
    if not matches:
        raise ValueError(f"Открытое окно с названием «{title_hint}» не найдено.")
    hwnd, title = matches[0]
    _user32.ShowWindow(hwnd, 9)
    _user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)
    return f"Переключился на окно «{title}»."


def _safe_path(raw: str) -> Path:
    if not raw:
        raise ValueError("Не указан путь к файлу или папке.")
    path = Path(os.path.expandvars(raw)).expanduser()
    if not path.is_absolute():
        raise ValueError("Для работы с компьютером укажи полный путь, например C:/Users/Имя/Documents/file.txt.")
    return path.resolve()


def _file_action(name: str, action: dict, created=None) -> str:
    created = created if created is not None else []
    if name == "open_path":
        path = _safe_path(str(action.get("path", "")))
        if not path.exists():
            raise ValueError("Файл или папка не найдены.")
        os.startfile(str(path))
        return f"Открыто: «{path.name}»."
    if name == "search_files":
        query = str(action.get("query", "")).strip().casefold()
        if not query or len(query) > 120:
            raise ValueError("Укажи имя или часть имени файла для поиска.")
        folder = _safe_path(str(action.get("path", "")))
        if not folder.is_dir():
            raise ValueError("Папка для поиска не найдена.")
        results = []
        ignored = {"$recycle.bin", "system volume information"}
        for current, dirs, files in os.walk(folder):
            dirs[:] = [entry for entry in dirs if entry.casefold() not in ignored]
            for entry in files:
                if query in entry.casefold():
                    results.append(str(Path(current) / entry))
                    if len(results) >= 50:
                        break
            if len(results) >= 50:
                break
        return "Найдены файлы:\n" + ("\n".join(results) if results else "Совпадений нет.")
    if name == "copy_file":
        source = _safe_path(str(action.get("source", "")))
        destination = _safe_path(str(action.get("destination", "")))
        if not source.is_file():
            raise ValueError("Исходный файл не найден.")
        if not destination.parent.is_dir():
            raise ValueError("Папка назначения не найдена.")
        if destination.exists():
            raise ValueError("Файл назначения уже существует; ничего не перезаписал.")
        shutil.copy2(source, destination)
        return f"«{source.name}» скопирован в «{destination}»."
    if name == "list_files":
        folder = _safe_path(str(action.get("path", "")))
        if not folder.is_dir():
            raise ValueError("Папка не найдена.")
        entries = sorted(folder.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))[:60]
        return "Содержимое папки:\n" + ("\n".join(("[Папка] " if p.is_dir() else "[Файл] ") + p.name for p in entries) or "Папка пуста.")
    if name == "read_file":
        path = _safe_path(str(action.get("path", "")))
        if not path.is_file():
            raise ValueError("Файл не найден.")
        if _is_sensitive_project_file(path):
            raise ValueError("Чтение файлов с ключами и секретами заблокировано.")
        if path.suffix.lower() not in (".txt", ".md", ".json", ".csv", ".tsv", ".log", ".ini", ".yaml", ".yml", ".xml", ".html", ".htm"):
            raise ValueError("Навык читает только распространённые текстовые файлы.")
        if path.stat().st_size > 100_000:
            raise ValueError("Для чтения доступны текстовые файлы размером до 100 КБ.")
        data = path.read_bytes()
        try:
            content = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            content = data.decode("cp1251", errors="replace")
        return f"Содержимое файла «{path.name}»:\n{content[:20000]}"
    if name == "create_file":
        path = _safe_path(str(action.get("path", "")))
        content = str(action.get("content", ""))
        if len(content.encode("utf-8")) > 100_000:
            raise ValueError("Новый файл ограничен размером 100 КБ.")
        if not path.parent.is_dir():
            raise ValueError("Папка для нового файла не найдена.")
        with path.open("x", encoding="utf-8", newline="") as file:
            file.write(content)
        created.append(str(path))
        return f"Файл «{path.name}» создан."
    if name == "write_file":
        path = _safe_path(str(action.get("path", "")))
        content = str(action.get("content", ""))
        if len(content.encode("utf-8")) > 100_000:
            raise ValueError("Файл ограничен размером 100 КБ: раздели код на несколько файлов.")
        if not path.parent.is_dir():
            raise ValueError("Папка для файла не найдена.")
        if path.exists() and str(path) not in created:
            raise ValueError("Этот файл создан не в этой просьбе, его нельзя перезаписать: выбери новое имя.")
        new = not path.exists()
        path.write_text(content, encoding="utf-8", newline="")
        if new:
            created.append(str(path))
        return f"Файл «{path.name}» {'создан' if new else 'перезаписан'} ({len(content)} символов)."
    if name == "create_folder":
        path = _safe_path(str(action.get("path", "")))
        path.mkdir(parents=False, exist_ok=False)
        created.append(str(path))
        return f"Папка «{path.name}» создана."
    if name in ("rename_file", "move_file"):
        source = _safe_path(str(action.get("source", "")))
        destination = _safe_path(str(action.get("destination", "")))
        if not source.exists():
            raise ValueError("Исходный файл или папка не найдены.")
        if not destination.parent.is_dir():
            raise ValueError("Папка назначения не найдена.")
        if destination.exists():
            raise ValueError("В месте назначения уже есть файл или папка; ничего не перезаписал.")
        source.rename(destination)
        return f"{('Переименовано' if name == 'rename_file' else 'Перемещено')}: «{source.name}» → «{destination.name}»."
    raise ValueError("Неизвестная файловая команда.")


def _download_file(action: dict) -> str:
    url = str(action.get("url", "")).strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Для скачивания нужен полный HTTP или HTTPS адрес.")
    destination = _safe_path(str(action.get("destination", "")))
    if not destination.parent.is_dir():
        raise ValueError("Папка для скачивания не найдена.")
    if destination.exists():
        raise ValueError("Файл с таким именем уже существует; ничего не перезаписал.")
    partial = destination.with_name(destination.name + ".download-part")
    if partial.exists():
        raise ValueError("Уже есть незавершённая загрузка с таким именем; сначала проверь её.")
    request = urllib.request.Request(url, headers={"User-Agent": "PivenCompanion/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response, partial.open("xb") as output:
            final_url = urllib.parse.urlparse(response.geturl())
            if final_url.scheme not in ("http", "https"):
                raise ValueError("Сайт перенаправил на неподдерживаемый адрес.")
            while True:
                cancel_event = action.get("_cancel_event")
                if cancel_event is not None and cancel_event.is_set():
                    raise InterruptedError("Скачивание отменено пользователем.")
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
        partial.replace(destination)
    except Exception:
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return f"Файл «{destination.name}» ({destination.stat().st_size:,} байт) скачан в «{destination.parent}»."


def execute_project_action(project_root: str | os.PathLike, action: dict) -> str:
    if not isinstance(action, dict):
        raise ValueError("Действие проекта должно быть объектом.")
    root = Path(project_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Выбранная папка проекта недоступна.")

    def resolve_project_path(raw: str) -> Path:
        raw = str(raw or ".").strip()
        candidate = Path(os.path.expandvars(raw)).expanduser()
        return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()

    def display_path(path: Path) -> str:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return str(path)

    name = str(action.get("project_action", "")).strip().lower()
    if name == "roots":
        if os.name == "nt":
            mask = ctypes.windll.kernel32.GetLogicalDrives()
            drives = [f"{chr(65 + index)}:/" for index in range(26) if mask & (1 << index)]
        else:
            drives = ["/"]
        return "Доступные диски компьютера:\n" + ("\n".join(drives) or "Не удалось определить диски.")
    if name == "list":
        folder = resolve_project_path(action.get("path", "."))
        if not folder.is_dir():
            raise ValueError("Папка проекта не найдена.")
        results = []
        base_depth = len(folder.parts)
        for current, dirs, files in os.walk(folder):
            current_path = Path(current)
            depth = len(current_path.parts) - base_depth
            dirs[:] = sorted(d for d in dirs if d.lower() not in _PROJECT_IGNORED_DIRS) if depth < 2 else []
            for entry in sorted(dirs) + sorted(files):
                full_path = current_path / entry
                label = "[папка] " if full_path.is_dir() else ""
                results.append(label + display_path(full_path))
                if len(results) >= 240:
                    break
            if len(results) >= 240:
                break
        return "Файлы проекта:\n" + ("\n".join(results) if results else "Папка пуста.")

    if name == "read":
        path = resolve_project_path(action.get("path", ""))
        if not path.is_file():
            raise ValueError("Файл проекта не найден.")
        if _is_sensitive_project_file(path):
            raise ValueError("Файл похож на хранилище секретов; чтение через агента заблокировано.")
        if path.stat().st_size > 2_000_000:
            raise ValueError("Для чтения через агента доступны файлы размером до 2 МБ.")
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            raise ValueError("Похоже, это бинарный файл; читать его как код нельзя.")
        lines = data.decode("utf-8-sig", errors="replace").splitlines()
        start_line = max(1, min(len(lines) or 1, int(action.get("start_line", 1))))
        line_count = max(1, min(500, int(action.get("max_lines", 300))))
        selected = lines[start_line - 1:start_line - 1 + line_count]
        end_line = start_line + len(selected) - 1
        return (f"Файл {display_path(path)} · строки {start_line}-{end_line} из {len(lines)}:\n"
                + "\n".join(selected)[:32_000])

    if name == "write":
        path = resolve_project_path(action.get("path", ""))
        if _is_sensitive_project_file(path):
            raise ValueError("Изменение файла с секретами через агента заблокировано.")
        content = str(action.get("content", ""))
        if len(content.encode("utf-8")) > 240_000:
            raise ValueError("Изменяемый файл ограничен размером 240 КБ.")
        if not path.parent.is_dir():
            raise ValueError("Родительская папка должна уже существовать.")
        if path.exists() and not path.is_file():
            raise ValueError("Можно изменять только обычные файлы.")
        temporary = path.with_name(path.name + ".companion-tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="") as file:
                file.write(content)
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return f"Сохранено: {display_path(path)} ({len(content)} символов)."

    if name == "search":
        query = str(action.get("query", ""))
        if not query or len(query) > 200:
            raise ValueError("Поисковая фраза должна содержать от 1 до 200 символов.")
        search_root = resolve_project_path(action.get("path", "."))
        if not search_root.is_dir():
            raise ValueError("Папка для поиска не найдена.")
        results = []
        for current, dirs, files in os.walk(search_root):
            dirs[:] = [directory for directory in dirs if directory.lower() not in _PROJECT_IGNORED_DIRS]
            for filename in files:
                file_path = Path(current) / filename
                try:
                    if _is_sensitive_project_file(file_path):
                        continue
                    if file_path.stat().st_size > 500_000:
                        continue
                    content = file_path.read_text(encoding="utf-8-sig")
                except (OSError, UnicodeError):
                    continue
                for line_no, line in enumerate(content.splitlines(), 1):
                    if query.casefold() in line.casefold():
                        results.append(f"{display_path(file_path)}:{line_no}: {line[:240]}")
                        if len(results) >= 80:
                            break
                if len(results) >= 80:
                    break
            if len(results) >= 80:
                break
        return "Совпадения:\n" + ("\n".join(results) if results else "Совпадений нет.")

    if name == "run":
        argv = action.get("argv")
        if not isinstance(argv, list) or not argv or len(argv) > 24 or any(not isinstance(part, str) for part in argv):
            raise ValueError("Команда должна быть списком аргументов, без shell-строки.")
        executable = Path(argv[0]).name.lower()
        allowed = {
            "python", "python.exe", "py", "py.exe", "pytest", "pytest.exe",
            "node", "node.exe", "git", "git.exe", "ruff", "ruff.exe",
            "go", "go.exe", "cargo", "cargo.exe", "dotnet", "dotnet.exe", "cmake", "cmake.exe",
        }
        if executable not in allowed:
            raise ValueError("Разрешены только Python, pytest, Node, Git, Ruff, Go, Cargo, .NET и CMake.")
        command_text = " ".join(argv[1:]).lower()
        if executable.startswith(("git",)) and not any(command_text.startswith(prefix) for prefix in ("status", "diff", "log", "show", "branch --list", "branch -l", "branch --show-current")):
            raise ValueError("Для Git разрешены только status, diff, log, show и branch.")
        if executable.startswith(("python", "py")) and not any(
                command_text.startswith(prefix) for prefix in (
                    "-m pytest", "-m unittest", "-m compileall", "-m ruff", "-m mypy", "-m py_compile")):
            raise ValueError("Python-команда ограничена тестами, проверкой синтаксиса и анализаторами.")
        if executable.startswith(("go",)) and not any(command_text.startswith(prefix) for prefix in ("test", "vet", "build")):
            raise ValueError("Для Go разрешены только test, vet и build.")
        if executable.startswith(("cargo",)) and not any(command_text.startswith(prefix) for prefix in ("test", "check", "build")):
            raise ValueError("Для Cargo разрешены только test, check и build.")
        if executable.startswith(("dotnet",)) and not any(command_text.startswith(prefix) for prefix in ("test", "build")):
            raise ValueError("Для .NET разрешены только test и build.")
        if executable.startswith(("cmake",)) and not command_text.startswith("--build"):
            raise ValueError("Для CMake разрешена только команда --build.")
        cwd = resolve_project_path(action.get("cwd", "."))
        if not cwd.is_dir():
            raise ValueError("Рабочая папка команды не найдена.")
        try:
            completed = subprocess.run(argv, cwd=str(cwd), shell=False, capture_output=True,
                                       text=True, encoding="utf-8", errors="replace", timeout=120,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as error:
            output = (error.stdout or "") + "\nКоманда остановлена: превышен лимит 120 секунд."
            return output[-12_000:]
        output = (completed.stdout or "") + (completed.stderr or "")
        return f"Код завершения: {completed.returncode}\n" + (output[-12_000:] or "Команда выполнена без вывода.")

    raise ValueError("Неизвестное действие проекта.")


COMPUTER_ACTIONS = ("list_files", "read_file", "create_file", "write_file", "create_folder", "rename_file", "move_file", "copy_file",
                    "open_path", "search_files", "download_file", "web_search", "open_url", "open_app", "activate_window",
                    "get_active_window", "minimize_window", "maximize_window", "restore_window", "wait", "click",
                    "type_text", "press_key", "scroll")
_ACTION_ALIASES = {"save_file": "write_file", "update_file": "write_file", "make_file": "create_file",
                   "create_text_file": "create_file", "new_file": "create_file", "mkdir": "create_folder",
                   "make_folder": "create_folder", "create_directory": "create_folder", "open_file": "open_path",
                   "open_folder": "open_path", "list_folder": "list_files", "list_directory": "list_files"}


def execute_computer_action(action: dict, screenshot_size=None, display_size=None, created=None) -> str:
    if _user32 is None:
        raise RuntimeError("Управление компьютером доступно только в Windows.")
    if not isinstance(action, dict):
        raise ValueError("Команда компьютера должна быть объектом.")
    name = str(action.get("computer_action", "")).strip().lower()
    name = _ACTION_ALIASES.get(name, name)
    if name in ("list_files", "read_file", "create_file", "write_file", "create_folder", "rename_file", "move_file",
                "copy_file", "open_path", "search_files"):
        return _file_action(name, action, created)
    if name == "download_file":
        if action.get("approved") is not True:
            raise PermissionError("Загрузка не началась: требуется отдельное подтверждение пользователя.")
        return _download_file(action)
    if name == "web_search":
        query = " ".join(str(action.get("query", "")).split())
        if not query or len(query) > 300:
            raise ValueError("Поисковый запрос должен содержать от 1 до 300 символов.")
        url = "https://search.brave.com/search?" + urllib.parse.urlencode({"q": query})
        webbrowser.open(url)
        return f"Открыты результаты Brave Search по запросу «{query}»."
    if name == "open_url":
        url = str(action.get("url", "")).strip()
        if "://" not in url:
            url = "https://" + url
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or any(char.isspace() for char in parsed.netloc):
            raise ValueError("Не удалось распознать адрес сайта.")
        webbrowser.open(url)
        return f"Открыт сайт {parsed.netloc}."
    if name == "open_app":
        app_name = str(action.get("app", "")).strip()
        if not app_name or len(app_name) > 100:
            raise ValueError("Укажи короткое название приложения.")
        normalized_app = " ".join(app_name.casefold().replace("ё", "е").split())
        if normalized_app in {"проводник", "файловый проводник", "file explorer", "explorer", "explorer.exe"}:
            os.startfile("explorer.exe")
            return "Проводник открыт."
        if normalized_app in {"терминал", "windows terminal", "командная строка", "cmd", "cmd.exe"}:
            try:
                subprocess.Popen(["wt.exe"], shell=False)
            except OSError:
                subprocess.Popen([os.environ.get("COMSPEC", "cmd.exe")], shell=False)
            return "Терминал Windows открыт."
        if normalized_app in {"powershell", "windows powershell", "powershell 7", "pwsh"}:
            executable = shutil.which("pwsh") or shutil.which("powershell") or "powershell.exe"
            subprocess.Popen([executable, "-NoLogo"], shell=False)
            return "PowerShell открыт."
        _send_key(_KEYS["WIN"])
        _send_key(_KEYS["WIN"], True)
        time.sleep(0.35)
        _type_text(app_name)
        time.sleep(0.35)
        _send_key(_KEYS["ENTER"])
        _send_key(_KEYS["ENTER"], True)
        time.sleep(1.0)
        return f"Поиск приложения «{app_name}» через меню Пуск."
    if name == "activate_window":
        return _activate_window(str(action.get("title", "")))
    if name == "get_active_window":
        hwnd = _user32.GetForegroundWindow()
        length = _user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, title, length + 1)
        return "Активное окно: " + (title.value or "без заголовка")
    if name in ("minimize_window", "maximize_window", "restore_window"):
        hwnd = _user32.GetForegroundWindow()
        command = {"minimize_window": 6, "maximize_window": 3, "restore_window": 9}[name]
        _user32.ShowWindow(hwnd, command)
        return {"minimize_window": "Активное окно свёрнуто.",
                "maximize_window": "Активное окно развёрнуто.",
                "restore_window": "Восстановил размер активного окна."}[name]
    if name == "wait":
        seconds = max(0.0, min(5.0, float(action.get("seconds", 1))))
        time.sleep(seconds)
        return f"Подождал {seconds:g} с."
    if name == "click":
        if not screenshot_size or not display_size:
            raise ValueError("Для клика нужен свежий снимок экрана.")
        image_w, image_h = screenshot_size
        screen_w, screen_h = display_size
        x = round(float(action.get("x", -1)) * screen_w / image_w)
        y = round(float(action.get("y", -1)) * screen_h / image_h)
        if x < 0 or y < 0 or x >= screen_w or y >= screen_h:
            raise ValueError("Координаты клика за пределами экрана.")
        _user32.SetCursorPos(x, y)
        button = str(action.get("button", "left")).lower()
        if button not in ("left", "right", "double"):
            raise ValueError("Поддерживаются левая кнопка, правая кнопка и двойной щелчок.")
        down, up = (_MOUSEEVENTF_RIGHTDOWN, _MOUSEEVENTF_RIGHTUP) if button == "right" else (_MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP)
        count = 2 if button == "double" else 1
        for _ in range(count):
            _user32.mouse_event(down, 0, 0, 0, 0)
            _user32.mouse_event(up, 0, 0, 0, 0)
            if count == 2:
                time.sleep(0.08)
        return f"Клик в точке {x}, {y}."
    if name == "type_text":
        _type_text(str(action.get("text", "")))
        return "Текст введён в активное поле."
    if name == "press_key":
        _key_combo(str(action.get("keys", "")))
        return f"Нажато: {action.get('keys', '')}."
    if name == "scroll":
        if action.get("x") is not None and action.get("y") is not None and screenshot_size and display_size:
            image_w, image_h = screenshot_size
            screen_w, screen_h = display_size
            image_x, image_y = float(action["x"]), float(action["y"])
            if not (0 <= image_x < image_w and 0 <= image_y < image_h):
                raise ValueError("Точка прокрутки находится за пределами снимка экрана.")
            _user32.SetCursorPos(round(image_x * screen_w / image_w), round(image_y * screen_h / image_h))
        amount = max(-1200, min(1200, int(action.get("amount", -480))))
        _user32.mouse_event(_MOUSEEVENTF_WHEEL, 0, 0, ctypes.c_ulong(amount).value, 0)
        return "Страница прокручена."
    raise ValueError(f"Команды «{name}» нет. Доступны: " + ", ".join(COMPUTER_ACTIONS) + ".")
