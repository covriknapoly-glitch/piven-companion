"""The right-hand workspace's backend: running code from the editor and reading presentations for preview.

Code runs in a fresh temporary folder with a time limit, without a console window; Python runs isolated
(-I: no user site-packages, no current-folder imports). It is the user's own code, run on their click.
"""
from __future__ import annotations

import base64
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MAX_OUTPUT = 60000


def runners(app_dir):
    """{language: (title, file name, command list or None when not installed)}."""
    python = Path(app_dir) / "runtime" / "Python311" / "python.exe"
    node = shutil.which("node") or (str(Path(app_dir) / "runtime" / "node" / "node.exe") if (Path(app_dir) / "runtime" / "node" / "node.exe").is_file() else None)
    return {
        "python": ("Python", "main.py", [str(python if python.is_file() else sys.executable), "-I", "-X", "utf8", "main.py"]),
        "powershell": ("PowerShell", "main.ps1", ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "main.ps1"]),
        "javascript": ("JavaScript (Node.js)", "main.js", [node, "main.js"] if node else None),
        "batch": ("Командная строка", "main.cmd", ["cmd", "/c", "main.cmd"]),
    }


def run_code(app_dir, language, code, stdin="", timeout=30):
    """Run code; returns {"ok", "stdout", "stderr", "exitCode", "seconds", "error"}."""
    table = runners(app_dir)
    if language not in table:
        return {"ok": False, "error": "Этот язык не поддерживается."}
    title, file_name, command = table[language]
    if command is None:
        return {"ok": False, "error": f"Для {title} нужно установить его (https://nodejs.org)."}
    folder = Path(tempfile.mkdtemp(prefix="piven-run-"))
    try:
        encoding = "utf-8-sig" if language == "powershell" else ("cp866" if language == "batch" else "utf-8")
        (folder / file_name).write_text(str(code), encoding=encoding)
        started = time.monotonic()
        try:
            result = subprocess.run(command, cwd=str(folder), input=str(stdin), capture_output=True, timeout=timeout,
                                    creationflags=NO_WINDOW, env=_clean_env())
        except subprocess.TimeoutExpired as expired:
            return {"ok": False, "stdout": _decode(expired.stdout), "stderr": _decode(expired.stderr), "exitCode": None,
                    "seconds": timeout, "error": f"Код работал дольше {timeout} с и был остановлен."}
        return {"ok": result.returncode == 0, "stdout": _decode(result.stdout)[:MAX_OUTPUT], "stderr": _decode(result.stderr)[:MAX_OUTPUT],
                "exitCode": result.returncode, "seconds": round(time.monotonic() - started, 2), "error": ""}
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _clean_env():
    import os
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith(("PYTHON", "HF_", "OPENAI", "ANTHROPIC"))}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _decode(data):
    if not data:
        return ""
    for encoding in ("utf-8", "cp866", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def presentation_slides(path):
    """Slides of a .pptx for the in-app viewer: [{"title", "texts": [..], "images": [data URLs], "background"}]."""
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    presentation = Presentation(str(path))
    slides = []
    for slide in presentation.slides:
        title, texts, images = "", [], []
        background = ""
        for shape in slide.shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                try:
                    blob = shape.image.blob
                    if len(blob) < 4 * 2**20:
                        images.append(f"data:{shape.image.content_type};base64,{base64.b64encode(blob).decode('ascii')}")
                except Exception:
                    pass
                continue
            if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                lines = [paragraph.text.strip() for paragraph in shape.text_frame.paragraphs if paragraph.text.strip()]
                if not lines:
                    continue
                if not title and (getattr(shape, "is_placeholder", False) and "title" in str(shape.placeholder_format.type).lower()
                                  or not texts and len(lines) == 1 and len(lines[0]) < 120):
                    title = lines[0]
                else:
                    texts += lines
        try:
            fill = slide.background.fill
            if fill.type is not None and fill.fore_color and fill.fore_color.type is not None:
                background = "#" + str(fill.fore_color.rgb)
        except Exception:
            background = ""
        slides.append({"title": title, "texts": texts[:30], "images": images[:4], "background": background})
    return slides
