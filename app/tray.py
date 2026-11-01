"""The program's icon in the Windows notification area: brings the window back, quits, and shows notifications.

Plain Win32 through ctypes (Shell_NotifyIcon), so no extra packages are needed. The icon lives in its own
thread with its own hidden window and message loop; callbacks run on that thread.
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WM_DESTROY, WM_CLOSE, WM_COMMAND, WM_NULL, WM_USER = 0x0002, 0x0010, 0x0111, 0x0000, 0x0400
WM_LBUTTONUP, WM_RBUTTONUP, WM_LBUTTONDBLCLK = 0x0202, 0x0205, 0x0203
NIN_BALLOONUSERCLICK = WM_USER + 5
CALLBACK = WM_USER + 20
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
NIIF_USER, NIIF_LARGE_ICON = 0x04, 0x20
MENU_OPEN, MENU_QUIT = 1, 2


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.LoadImageW.restype = wintypes.HANDLE
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.LPVOID]
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]


def foreground_title():
    """The title of the window the user is working in now."""
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(user32.GetForegroundWindow(), buffer, 256)
    return buffer.value


class Tray:
    def __init__(self, icon_path, tooltip, on_open, on_quit):
        self.icon_path, self.tooltip = str(icon_path), tooltip
        self.on_open, self.on_quit = on_open, on_quit
        self.hwnd = None
        self.hicon = None
        self._ready = threading.Event()
        self._proc = WNDPROC(self._window_proc)  # kept alive for as long as the window exists
        threading.Thread(target=self._run, name="tray", daemon=True).start()
        self._ready.wait(5)

    # ---------- public ----------
    def notify(self, title, text):
        """A Windows notification from the tray icon; clicking it opens the window."""
        if not self.hwnd:
            return
        data = self._data(NIF_INFO)
        data.szInfoTitle = str(title)[:63]
        data.szInfo = str(text)[:255] or " "
        data.dwInfoFlags = NIIF_USER | NIIF_LARGE_ICON
        data.hBalloonIcon = self.hicon
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))

    def close(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    # ---------- window thread ----------
    def _data(self, flags):
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd, data.uID, data.uFlags = self.hwnd, 1, flags
        return data

    def _add(self):
        data = self._data(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        data.uCallbackMessage, data.hIcon, data.szTip = CALLBACK, self.hicon, self.tooltip[:127]
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data))

    def _run(self):
        instance = kernel32.GetModuleHandleW(None)
        window_class = WNDCLASSW(lpfnWndProc=self._proc, hInstance=instance, lpszClassName="PivenCompanionTray")
        user32.RegisterClassW(ctypes.byref(window_class))
        self.hwnd = user32.CreateWindowExW(0, "PivenCompanionTray", "PIVEN tray", 0, 0, 0, 0, 0, None, None, instance, None)
        self.hicon = user32.LoadImageW(None, self.icon_path, 1, 0, 0, 0x10 | 0x40)  # IMAGE_ICON, LR_LOADFROMFILE | LR_DEFAULTSIZE
        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        self._add()
        self._ready.set()
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))

    def _menu(self):
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, 0, MENU_OPEN, "Открыть PIVEN")
        user32.AppendMenuW(menu, 0x800, 0, None)  # separator
        user32.AppendMenuW(menu, 0, MENU_QUIT, "Выйти")
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        user32.SetForegroundWindow(self.hwnd)
        choice = user32.TrackPopupMenu(menu, 0x0100 | 0x0080 | 0x0002, point.x, point.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        if choice == MENU_OPEN:
            self.on_open()
        elif choice == MENU_QUIT:
            self.on_quit()

    def _window_proc(self, hwnd, message, wparam, lparam):
        if message == CALLBACK:
            event = lparam & 0xFFFF
            if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK, NIN_BALLOONUSERCLICK):
                self.on_open()
            elif event == WM_RBUTTONUP:
                self._menu()
            return 0
        if message == getattr(self, "_taskbar_created", -1):  # Explorer restarted: put the icon back
            self._add()
            return 0
        if message == WM_CLOSE:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._data(0)))
            user32.DestroyWindow(hwnd)
            return 0
        if message == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)
