"""macOS helpers through ctypes (no extra package): the screen-recording
permission, and an overlay window that floats above the menu bar on every
Space without entering native full screen.

Importing this module is safe on every system and does nothing: the
frameworks load on first use, only on macOS. Every call is wrapped, so a
failure here never blocks a capture -- the permission reads as granted and
the overlay simply stays an ordinary window.
"""
from __future__ import annotations

import ctypes
import subprocess
import sys

IS_MAC = sys.platform == "darwin"

PRIVACY_URL = ("x-apple.systempreferences:com.apple.preference.security"
               "?Privacy_ScreenCapture")
SCREEN_SAVER_LEVEL = 1000            # NSScreenSaverWindowLevel: above the menu bar
CAN_JOIN_ALL_SPACES = 1 << 0         # NSWindowCollectionBehavior...
STATIONARY = 1 << 4
IGNORES_CYCLE = 1 << 6
FULL_SCREEN_AUXILIARY = 1 << 8
OVERLAY_BEHAVIOR = (CAN_JOIN_ALL_SPACES | STATIONARY | FULL_SCREEN_AUXILIARY
                    | IGNORES_CYCLE)

CORE_GRAPHICS = ("/System/Library/Frameworks/CoreGraphics.framework/"
                 "CoreGraphics")
LIBOBJC = "/usr/lib/libobjc.A.dylib"

_libs: dict[str, ctypes.CDLL] = {}


def _lib(path: str) -> ctypes.CDLL:
    if path not in _libs:
        _libs[path] = ctypes.CDLL(path)
    return _libs[path]


def _cg() -> ctypes.CDLL:
    return _lib(CORE_GRAPHICS)


def screen_capture_allowed() -> bool:
    """True when this app may record the screen. Off macOS, or when the
    check itself fails, True: the check never stops a capture by mistake."""
    if not IS_MAC:
        return True
    try:
        # ASSUMES: macOS 10.15 or newer, where CoreGraphics has
        # CGPreflightScreenCaptureAccess (the app's minimum is Apple silicon,
        # macOS 11+). Tested false: a missing function reads as allowed.
        fn = _cg().CGPreflightScreenCaptureAccess
        fn.restype = ctypes.c_bool
        fn.argtypes = []
        return bool(fn())
    except (OSError, AttributeError):
        return True


def request_screen_capture() -> None:
    """Ask macOS to show its own permission prompt (it does so only the
    first time; later it adds the app to the Settings list, switched off)."""
    if not IS_MAC:
        return
    try:
        fn = _cg().CGRequestScreenCaptureAccess
        fn.restype = ctypes.c_bool
        fn.argtypes = []
        fn()
    except (OSError, AttributeError):
        pass


def open_privacy_settings() -> bool:
    """Open System Settings at Screen & System Audio Recording."""
    if not IS_MAC:
        return False
    try:
        subprocess.Popen(["open", PRIVACY_URL])
        return True
    except OSError:
        return False


def _msg(restype, *argtypes):
    """objc_msgSend cast to one exact signature (arm64 needs the exact
    argument types; objc_msgSend is not a true variadic function)."""
    objc = _lib(LIBOBJC)
    addr = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
    return ctypes.CFUNCTYPE(restype, *argtypes)(addr)


def _sel(name: str) -> int:
    objc = _lib(LIBOBJC)
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    return objc.sel_registerName(name.encode("ascii"))


def float_above_menu_bar(widget) -> bool:
    """Put the widget's NSWindow at the screen-saver level (above the menu
    bar and the Dock) and let it sit on every Space, never in native full
    screen. True when it was done; False off macOS, on a platform plugin
    other than cocoa (offscreen tests), or on any failure."""
    if not IS_MAC:
        return False
    try:
        from PySide6.QtGui import QGuiApplication
        # ASSUMES: on the cocoa platform plugin a widget's winId() is its
        # NSView* and the view already has an NSWindow once the widget is
        # shown. Tested false: offscreen, and a view with no window.
        if QGuiApplication.platformName() != "cocoa":
            return False
        view = int(widget.winId())
        if not view:
            return False
        vp, sel = ctypes.c_void_p, ctypes.c_void_p
        window = _msg(vp, vp, sel)(view, _sel("window"))
        if not window:
            return False
        _msg(None, vp, sel, ctypes.c_long)(window, _sel("setLevel:"),
                                           SCREEN_SAVER_LEVEL)
        _msg(None, vp, sel, ctypes.c_ulong)(
            window, _sel("setCollectionBehavior:"), OVERLAY_BEHAVIOR)
        return True
    except Exception:                    # noqa: BLE001 - never block a capture
        return False
