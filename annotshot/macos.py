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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtGui import QImage

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


def screen_capture_state() -> str:
    """The current process's grant; an unavailable check is unknown."""
    if not IS_MAC:
        return "unknown"
    try:
        # ASSUMES: the preflight function exists. Missing or failing is unknown.
        fn = _cg().CGPreflightScreenCaptureAccess
        fn.restype = ctypes.c_bool
        fn.argtypes = []
        return "allowed" if fn() else "denied"
    except Exception:
        return "unknown"


def screen_capture_allowed() -> bool:
    """Unknown never stops a capture by mistake."""
    return screen_capture_state() != "denied"


def permission_check_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--screen-permission"]
    return [sys.executable, "-m", "annotshot", "--screen-permission"]


def permission_relaunch_command() -> list[str]:
    from pathlib import Path
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable)
        if len(executable.parents) > 2:
            bundle = executable.parents[2]
            if bundle.suffix == ".app":
                return ["/usr/bin/open", "-n", str(bundle), "--args",
                        "--permission-restart"]
    return [sys.executable, "-m", "annotshot", "--permission-restart"]


# Constant script; paths are positional arguments, never shell source.
# ASSUMES: the old process exits before the elapsed-seconds deadline.
# Otherwise give up, including a deadline check immediately before launch.
RELAUNCH_SECONDS = 30
RELAUNCH_WAIT = ('started=$(/bin/date +%s) || exit 1; '
                 'while /bin/kill -0 "$1" 2>/dev/null; do '
                 'now=$(/bin/date +%s) || exit 1; '
                 '[ "$((now-started))" -lt "$2" ] || exit 1; '
                 '/bin/sleep 0.1; done; '
                 'now=$(/bin/date +%s) || exit 1; '
                 '[ "$((now-started))" -lt "$2" ] || exit 1; '
                 'shift 2; exec "$@"')


def window_picture(number: int) -> QImage | None:
    """The window's own pixels, without raising it; no temporary data survives."""
    if not IS_MAC or type(number) is not int:
        return None
    import tempfile
    from pathlib import Path
    from PySide6.QtGui import QImage
    try:
        with tempfile.TemporaryDirectory(prefix="annotshot-window-") as folder:
            path = Path(folder) / "window.png"
            result = subprocess.run(
                ["/usr/sbin/screencapture", "-x", "-o", f"-l{number}",
                 "-t", "png", str(path)], timeout=3, check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode != 0 or not path.is_file() or path.stat().st_size == 0:
                return None
            image = QImage(str(path))
            return None if image.isNull() else image
    except Exception:
        return None


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


# CoreGraphics window coordinates use global, top-left logical points. They
# are converted by the overlay's existing to_device mapping on each display.
CORE_FOUNDATION = ("/System/Library/Frameworks/CoreFoundation.framework/"
                   "CoreFoundation")


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


def _window_info() -> list[dict]:
    """Copy and release the native list; convert only typed, borrowed values."""
    from PySide6.QtCore import QRectF
    cg, cf = _cg(), _lib(CORE_FOUNDATION)
    vp, index = ctypes.c_void_p, ctypes.c_long

    def signature(lib, name, result, args):
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = result, args
        return fn

    copy = signature(cg, "CGWindowListCopyWindowInfo", vp,
                     [ctypes.c_uint32, ctypes.c_uint32])
    bounds = signature(cg, "CGRectMakeWithDictionaryRepresentation", ctypes.c_bool,
                       [vp, ctypes.POINTER(_CGRect)])
    release = signature(cf, "CFRelease", None, [vp])
    type_id = signature(cf, "CFGetTypeID", ctypes.c_ulong, [vp])
    types = {kind: signature(cf, f"CF{kind}GetTypeID", ctypes.c_ulong, [])()
             for kind in ("Array", "Dictionary", "Number", "String")}
    count = signature(cf, "CFArrayGetCount", index, [vp])
    at = signature(cf, "CFArrayGetValueAtIndex", vp, [vp, index])
    get = signature(cf, "CFDictionaryGetValue", vp, [vp, vp])
    number = signature(cf, "CFNumberGetValue", ctypes.c_bool,
                       [vp, ctypes.c_int, vp])
    length = signature(cf, "CFStringGetLength", index, [vp])
    string = signature(cf, "CFStringGetCString", ctypes.c_bool,
                       [vp, ctypes.c_char_p, index, ctypes.c_uint32])
    keys = {key: vp.in_dll(cg, key).value for key in (
        "kCGWindowLayer", "kCGWindowOwnerPID", "kCGWindowNumber",
        "kCGWindowBounds", "kCGWindowOwnerName", "kCGWindowName")}

    def typed(value, kind):
        if not value or type_id(value) != types[kind]:
            raise ValueError(f"Expected CF{kind}")
        return value

    def integer(value):
        out = ctypes.c_int64()
        if not number(typed(value, "Number"), 4, ctypes.byref(out)):  # kCFNumberSInt64Type
            raise ValueError("Bad window number")
        return out.value

    def text(value, optional=False):
        if not value and optional:
            return ""
        typed(value, "String")
        buf = ctypes.create_string_buffer(length(value) * 4 + 1)
        if not string(value, buf, len(buf), 0x08000100):  # kCFStringEncodingUTF8
            raise ValueError("Bad window title")
        return buf.value.decode("utf-8")

    # kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements
    array = copy((1 << 0) | (1 << 4), 0)
    if not array:
        return []
    try:
        typed(array, "Array")
        rows = []
        for i in range(count(array)):
            row = typed(at(array, i), "Dictionary")
            value = lambda key: get(row, keys[key])
            layer = integer(value("kCGWindowLayer"))
            pid = integer(value("kCGWindowOwnerPID"))
            # Filter before reading optional properties of non-app windows.
            import os
            if layer != 0 or pid == os.getpid():
                continue
            rect = _CGRect()
            if not bounds(typed(value("kCGWindowBounds"), "Dictionary"), ctypes.byref(rect)):
                raise ValueError("Bad window bounds")
            rows.append({
                "kCGWindowLayer": layer, "kCGWindowOwnerPID": pid,
                "kCGWindowNumber": integer(value("kCGWindowNumber")),
                "kCGWindowBounds": QRectF(rect.origin.x, rect.origin.y,
                                           rect.size.width, rect.size.height),
                "kCGWindowOwnerName": text(value("kCGWindowOwnerName")),
                "kCGWindowName": text(value("kCGWindowName"), optional=True)})
        return rows
    finally:
        release(array)


def _parse_windows(rows):
    import math
    import os
    from typing import NamedTuple
    from PySide6.QtCore import QRectF

    class Window(NamedTuple):
        hwnd: int
        title: str
        rect: QRectF

    # ASSUMES: CoreGraphics gives a well-formed dictionary list. Reject a
    # malformed list as a whole; enumeration failure never blocks capture.
    if not isinstance(rows, list):
        raise ValueError("Expected a window dictionary list")
    windows = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Expected a window dictionary")
        layer, pid = row["kCGWindowLayer"], row["kCGWindowOwnerPID"]
        if not isinstance(layer, int) or not isinstance(pid, int):
            raise ValueError("Bad window owner or layer")
        if layer != 0 or pid == os.getpid():
            continue
        number = row["kCGWindowNumber"]
        rect = row["kCGWindowBounds"]
        owner, name = row["kCGWindowOwnerName"], row.get("kCGWindowName", "")
        if (not isinstance(number, int) or not isinstance(rect, QRectF)
                or not isinstance(owner, str) or not isinstance(name, str)
                or not all(math.isfinite(v) for v in (rect.x(), rect.y(), rect.width(), rect.height()))):
            raise ValueError("Bad window dictionary")
        if rect.isEmpty():
            continue
        title = owner + (f" — {name}" if name else "")
        windows.append(Window(number, title, QRectF(rect)))
    return windows


def list_windows() -> list:
    """On-screen, layer-zero windows, front to back; never our own process.

    Any framework, permission or parsing failure returns an empty list.
    """
    if not IS_MAC:
        return []
    try:
        return _parse_windows(_window_info())
    except Exception:                    # noqa: BLE001 - never block a capture
        return []
