"""Win32 helpers through ctypes (no pywin32): the visible top-level windows
in z-order with their visible bounds, the monitors with their physical
rects, and the window under a point.

Every coordinate is in physical pixels. Call these after the Qt application
exists: Qt makes the process per-monitor DPI aware, and without that Windows
would hand back scaled (virtualised) coordinates.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import NamedTuple

from PySide6.QtCore import QRect

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32")
dwmapi = ctypes.WinDLL("dwmapi")
shell32 = ctypes.WinDLL("shell32")

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR,
                                     wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                     wintypes.LPARAM)


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                ("szDevice", wintypes.WCHAR * 32)]


user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = wintypes.LONG
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p,
                                       MONITORENUMPROC, wintypes.LPARAM]
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR,
                                   ctypes.POINTER(MONITORINFOEXW)]
dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                         ctypes.c_void_p, wintypes.DWORD]
dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
kernel32.GetConsoleWindow.restype = wintypes.HWND
shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long


class Window(NamedTuple):
    hwnd: int
    title: str
    rect: QRect      # visible bounds, physical pixels


def _qrect(r: wintypes.RECT) -> QRect:
    return QRect(r.left, r.top, r.right - r.left, r.bottom - r.top)


def _cloaked(hwnd) -> bool:
    value = ctypes.c_int(0)
    hr = dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(value),
                                      ctypes.sizeof(value))
    return hr == 0 and value.value != 0


def window_bounds(hwnd) -> QRect:
    """The visible frame (DWM extended frame bounds), else GetWindowRect."""
    r = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS,
                                    ctypes.byref(r), ctypes.sizeof(r)) != 0:
        if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return QRect()
    return _qrect(r)


def _window(hwnd) -> Window | None:
    if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
        return None
    if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
        return None
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0 or _cloaked(hwnd):
        return None
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    rect = window_bounds(hwnd)
    if not buf.value.strip() or rect.isEmpty():
        return None
    return Window(int(hwnd), buf.value, rect)


def list_windows() -> list[Window]:
    """Visible, titled, uncloaked top-level windows, topmost first."""
    found: list[Window] = []

    def visit(hwnd, _):
        try:
            w = _window(hwnd)
            if w is not None:
                found.append(w)
        except OSError:
            pass
        return True

    user32.EnumWindows(WNDENUMPROC(visit), 0)
    return found


def monitors() -> dict[str, QRect]:
    """{device name (e.g. \\\\.\\DISPLAY1): physical monitor rect}."""
    found: dict[str, QRect] = {}

    def visit(hmon, _hdc, _rect, _data):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            found[info.szDevice] = _qrect(info.rcMonitor)
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(visit), 0)
    return found


def window_under_point(x: int, y: int, exclude=(),
                       windows: list[Window] | None = None) -> Window | None:
    """The topmost listed window containing the physical point (x, y)."""
    exclude = {int(h) for h in exclude}
    for w in (list_windows() if windows is None else windows):
        if w.hwnd not in exclude and w.rect.contains(x, y):
            return w
    return None


def console_window() -> int:
    """This process's console window handle, or 0."""
    return int(kernel32.GetConsoleWindow() or 0)


def set_app_id(app_id: str) -> None:
    """Group the taskbar button under Annotshot's own icon, not python's."""
    try:
        shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except OSError:
        pass
