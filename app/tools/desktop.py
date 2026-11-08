"""Reads the window of a program the agent started and sends it input."""
from __future__ import annotations

import base64
import ctypes
import io
import re
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ENUM_WINDOWS = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
LRESULT = ctypes.c_ssize_t
user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.EnumWindows.argtypes = (ENUM_WINDOWS, wintypes.LPARAM)
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.IsWindowVisible.argtypes = (wintypes.HWND,)
user32.IsWindow.argtypes = (wintypes.HWND,)
user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetWindowDC.argtypes = (wintypes.HWND,)
user32.GetWindowDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
user32.PrintWindow.argtypes = (wintypes.HWND, wintypes.HDC, wintypes.UINT)
user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
user32.GetForegroundWindow.restype = wintypes.HWND
user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int)
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
gdi32.DeleteDC.argtypes = (wintypes.HDC,)
gdi32.GetDIBits.argtypes = (wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT)
kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

SNAP_PROCESS = 0x2
PW_CLIENT_FULL = 3
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_RBUTTONDOWN, WM_RBUTTONUP, WM_MBUTTONDOWN, WM_MBUTTONUP = 0x200, 0x201, 0x202, 0x204, 0x205, 0x207, 0x208
WM_KEYDOWN, WM_KEYUP = 0x100, 0x101
BUTTONS = {"left": (WM_LBUTTONDOWN, WM_LBUTTONUP, 0x1), "right": (WM_RBUTTONDOWN, WM_RBUTTONUP, 0x2), "middle": (WM_MBUTTONDOWN, WM_MBUTTONUP, 0x10)}
KEYS = {"space": 0x20, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "backspace": 0x08, "shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12,
        "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "arrowleft": 0x25, "arrowup": 0x26, "arrowright": 0x27, "arrowdown": 0x28, "delete": 0x2E,
        **{f"f{number}": 0x6F + number for number in range(1, 13)}}
EXTENDED = {0x25, 0x26, 0x27, 0x28, 0x2E}


class _Process(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


def process_tree(pid):
    """The process and its children."""
    snapshot = kernel32.CreateToolhelp32Snapshot(SNAP_PROCESS, 0)
    children = {}
    try:
        entry = _Process()
        entry.dwSize = ctypes.sizeof(_Process)
        found = kernel32.Process32FirstW(wintypes.HANDLE(snapshot), ctypes.byref(entry))
        while found:
            children.setdefault(entry.th32ParentProcessID, []).append(entry.th32ProcessID)
            found = kernel32.Process32NextW(wintypes.HANDLE(snapshot), ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    tree, waiting = set(), [int(pid)]
    while waiting:
        current = waiting.pop()
        if current not in tree:
            tree.add(current)
            waiting += children.get(current, [])
    return tree


def client_size(window):
    rect = wintypes.RECT()
    user32.GetClientRect(window, ctypes.byref(rect))
    return rect.right - rect.left, rect.bottom - rect.top


def title(window):
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(window, buffer, 256)
    return buffer.value


def find_window(pid):
    """The biggest visible window of the program, or None while it has not opened one."""
    tree = process_tree(pid)
    windows = []

    def visit(window, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if owner.value in tree and user32.IsWindowVisible(window):
            width, height = client_size(window)
            if width > 50 and height > 50:
                windows.append((width * height, window))
        return True
    user32.EnumWindows(ENUM_WINDOWS(visit), 0)
    return max(windows, key=lambda row: row[0])[1] if windows else None


def _grab(window, width, height):
    screen = user32.GetWindowDC(window)
    memory = gdi32.CreateCompatibleDC(screen)
    bitmap = gdi32.CreateCompatibleBitmap(screen, width, height)
    previous = gdi32.SelectObject(memory, bitmap)
    try:
        user32.PrintWindow(window, memory, PW_CLIENT_FULL)
        info = _BitmapInfo(ctypes.sizeof(_BitmapInfo), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        pixels = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(memory, bitmap, 0, height, pixels, ctypes.byref(info), 0)
        return pixels.raw
    finally:
        gdi32.SelectObject(memory, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory)
        user32.ReleaseDC(window, screen)


def picture(window, longest=(900, 700)):
    """Returns (JPEG as base64, blank): 3D windows can draw past PrintWindow. Only a window in front may be read from the screen, or the picture could show the user's other windows."""
    from PIL import Image, ImageGrab
    width, height = client_size(window)
    if width <= 0 or height <= 0:
        return None, True
    image = Image.frombuffer("RGB", (width, height), _grab(window, width, height), "raw", "BGRX", 0, 1)
    blank = image.convert("L").getextrema()[0] == image.convert("L").getextrema()[1]
    if blank and user32.GetForegroundWindow() == window:
        corner = wintypes.POINT(0, 0)
        user32.ClientToScreen(window, ctypes.byref(corner))
        image = ImageGrab.grab(bbox=(corner.x, corner.y, corner.x + width, corner.y + height), all_screens=True).convert("RGB")
        blank = image.convert("L").getextrema()[0] == image.convert("L").getextrema()[1]
    image.thumbnail(longest)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=75)
    return base64.b64encode(buffer.getvalue()).decode("ascii"), blank


def _point(x, y):
    return (int(y) & 0xFFFF) << 16 | (int(x) & 0xFFFF)


def _place(window, x, y):
    width, height = client_size(window)
    return (x * width if 0 < x <= 1 else x), (y * height if 0 < y <= 1 else y)


def _post(window, message, flags, x, y):
    user32.PostMessageW(window, message, flags, _point(x, y))


def click(window, x, y, button="left"):
    down, up, flag = BUTTONS[button]
    x, y = _place(window, x, y)
    # SDL goes back to the real cursor as soon as it has handled a move, so each press has to follow its move at once.
    _post(window, WM_MOUSEMOVE, 0, x, y)
    _post(window, down, flag, x, y)
    time.sleep(0.08)
    _post(window, WM_MOUSEMOVE, flag, x, y)
    _post(window, up, 0, x, y)


def drag(window, x1, y1, x2, y2, button="left"):
    down, up, flag = BUTTONS[button]
    x1, y1 = _place(window, x1, y1)
    x2, y2 = _place(window, x2, y2)
    _post(window, WM_MOUSEMOVE, 0, x1, y1)
    _post(window, down, flag, x1, y1)
    for step in range(1, 9):
        time.sleep(0.03)
        _post(window, WM_MOUSEMOVE, flag, x1 + (x2 - x1) * step / 8, y1 + (y2 - y1) * step / 8)
    _post(window, WM_MOUSEMOVE, flag, x2, y2)
    _post(window, up, 0, x2, y2)


def key(window, name, seconds=0.1):
    lowered = str(name).strip().lower()
    code = KEYS.get(lowered) or (ord(lowered.upper()) if len(lowered) == 1 and lowered.isascii() and lowered.isalnum() else None)
    if code is None:
        raise ValueError(f"unknown key {name}")
    scan = user32.MapVirtualKeyW(code, 0) << 16 | (1 << 24 if code in EXTENDED else 0)
    user32.PostMessageW(window, WM_KEYDOWN, code, 1 | scan)
    time.sleep(seconds)
    user32.PostMessageW(window, WM_KEYUP, code, 1 | scan | 0xC0000000)


def run_step(window, step, cancelled=lambda: False):
    """One test step in plain words: «click 0.5 0.5», «click 100 200 right», «drag 10 10 90 90», «key w 0.5», «wait 2». Returns what happened, for the model."""
    words = re.split(r"\s+", str(step).strip())
    action, rest = words[0].lower(), words[1:]
    try:
        if action == "click":
            click(window, float(rest[0]), float(rest[1]), rest[2].lower() if len(rest) > 2 else "left")
        elif action == "drag":
            drag(window, *[float(value) for value in rest[:4]], rest[4].lower() if len(rest) > 4 else "left")
        elif action == "key":
            key(window, rest[0], min(10.0, float(rest[1])) if len(rest) > 1 else 0.1)
        elif action == "wait":
            deadline = time.monotonic() + min(30.0, float(rest[0]))
            while time.monotonic() < deadline and not cancelled():
                time.sleep(0.05)
        else:
            return f"{step}: unknown step"
    except (IndexError, KeyError, TypeError, ValueError) as error:
        return f"{step}: not understood ({error})"
    return f"{step}: done"
