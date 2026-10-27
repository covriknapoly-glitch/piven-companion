"""A real browser panel inside the PIVEN web window.

The page draws an empty box on the right; this module lays a second, separate WebView2 control
over that box. Sites load as in Edge (no iframe restrictions), but the control is cut off from the
companion: it has its own profile folder, no JS bridge, no web messages, no host objects, no
downloads, and only http(s) navigation. Links that want a new window open in the same panel.
"""
from __future__ import annotations

import os
import threading

import clr  # noqa: F401 - pythonnet, already loaded by pywebview
from System import Func, Type, Uri
import System.Windows.Forms as WinForms
from webview.util import interop_dll_path

clr.AddReference(interop_dll_path("Microsoft.Web.WebView2.Core.dll"))
clr.AddReference(interop_dll_path("Microsoft.Web.WebView2.WinForms.dll"))
from Microsoft.Web.WebView2.WinForms import CoreWebView2CreationProperties, WebView2  # noqa: E402


def _is_web(url):
    lowered = str(url or "").lower()
    return lowered.startswith("http://") or lowered.startswith("https://") or lowered == "about:blank"


class NativeBrowser:
    def __init__(self, window, profile_dir):
        self._window = window
        self._profile_dir = profile_dir
        self._control = None
        self._ready = False
        self._pending_url = ""
        self._lock = threading.Lock()
        self._state = {"url": "", "title": "", "loading": False, "canBack": False, "canForward": False, "notice": ""}

    # ---------- plumbing ----------
    def _form(self):
        from webview.platforms.winforms import BrowserView
        return BrowserView.instances.get(self._window.uid)

    def _on_ui(self, action):
        form = self._form()
        if form is None:
            return
        def run():
            action()
        form.Invoke(Func[Type](run))

    def _update(self, **values):
        with self._lock:
            self._state.update(values)

    def _sync_history(self):
        core = self._control.CoreWebView2 if self._control else None
        if core is not None:
            self._update(url=str(core.Source), title=str(core.DocumentTitle), canBack=bool(core.CanGoBack), canForward=bool(core.CanGoForward))

    def _create(self):
        """Runs on the UI thread."""
        control = WebView2()
        props = CoreWebView2CreationProperties()
        props.UserDataFolder = self._profile_dir
        control.CreationProperties = props
        control.Visible = False
        control.CoreWebView2InitializationCompleted += self._on_ready
        form = self._form()
        form.Controls.Add(control)
        control.BringToFront()
        self._control = control
        control.EnsureCoreWebView2Async(None)

    def _on_ready(self, sender, args):
        if not args.IsSuccess:
            self._update(notice=f"Браузер не запустился: {args.InitializationException}")
            return
        core = sender.CoreWebView2
        settings = core.Settings
        settings.IsWebMessageEnabled = False
        settings.AreHostObjectsAllowed = False
        settings.AreDevToolsEnabled = False
        settings.IsStatusBarEnabled = False
        settings.AreDefaultContextMenusEnabled = True
        core.NavigationStarting += self._on_navigation_starting
        core.NavigationCompleted += self._on_navigation_completed
        core.SourceChanged += lambda *_: self._sync_history()
        core.HistoryChanged += lambda *_: self._sync_history()
        core.DocumentTitleChanged += lambda *_: self._sync_history()
        core.NewWindowRequested += self._on_new_window
        core.DownloadStarting += self._on_download
        self._ready = True
        if self._pending_url:
            core.Navigate(self._pending_url)
            self._pending_url = ""

    def _on_navigation_starting(self, _sender, args):
        if not _is_web(args.Uri):
            args.Cancel = True
            self._update(notice="Во встроенном браузере открываются только сайты (http и https).")
            return
        self._update(loading=True, url=str(args.Uri), notice="")

    def _on_navigation_completed(self, _sender, _args):
        self._update(loading=False)
        self._sync_history()

    def _on_new_window(self, _sender, args):
        args.Handled = True
        if _is_web(args.Uri):
            self._control.CoreWebView2.Navigate(args.Uri)

    def _on_download(self, _sender, args):
        args.Cancel = True
        self._update(notice="Скачивание из встроенного браузера отключено. Открой сайт в обычном браузере, если нужен файл.")

    # ---------- called from the page through WebApi (any thread) ----------
    def place(self, x, y, width, height, visible):
        def action():
            if self._control is None:
                if not visible:
                    return
                self._create()
            self._control.SetBounds(int(x), int(y), max(0, int(width)), max(0, int(height)))
            self._control.Visible = bool(visible) and width > 0 and height > 0
            if self._control.Visible:
                self._control.BringToFront()
        self._on_ui(action)

    def navigate(self, url):
        if not _is_web(url):
            return False
        def action():
            if self._ready:
                self._control.CoreWebView2.Navigate(url)
            else:
                self._pending_url = url
        self._on_ui(action)
        return True

    def command(self, name):
        def action():
            core = self._control.CoreWebView2 if self._control and self._ready else None
            if core is None:
                return
            if name == "back" and core.CanGoBack:
                core.GoBack()
            elif name == "forward" and core.CanGoForward:
                core.GoForward()
            elif name == "reload":
                core.Reload()
            elif name == "stop":
                core.Stop()
        self._on_ui(action)

    def state(self):
        with self._lock:
            return dict(self._state)

    def clear_notice(self):
        self._update(notice="")
