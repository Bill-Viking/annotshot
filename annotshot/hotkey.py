"""One capture key that works while Annotshot is not in front.

Windows: RegisterHotKey for the thread (no window) and a native event
filter that catches WM_HOTKEY as Qt's event loop takes it from the queue.
macOS: Carbon's RegisterEventHotKey with an event handler on the
application target (no permission needed; Qt's loop runs the run loop that
delivers it). Linux: not built yet -- `available` is False.

Importing this module loads nothing: each system's library is opened when
its backend is made. Only one key is registered at a time.
"""
from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, Qt, Signal
from PySide6.QtGui import QKeySequence

DEFAULT = "Ctrl+Shift+2"
NOT_ON_LINUX = "not available on Linux yet"
NEED_MODIFIER = "Use Ctrl, Alt or Shift with the key (or an F key alone)"
ONE_KEY = "Use one key with its modifiers"
UNKNOWN_KEY = "This key cannot be used from anywhere; try a letter, a digit or an F key"
TAKEN = "{key} is taken by the system or another app; pick another key"

HOTKEY_ID = 0xA57                    # our id for the one Windows hotkey
WM_HOTKEY = 0x0312


def combo(seq: QKeySequence):
    """(Qt key, Qt modifiers) of a one-chord sequence; None otherwise."""
    if seq.isEmpty() or seq.count() != 1:
        return None
    kc = seq[0]
    return kc.key(), kc.keyboardModifiers()


def is_function_key(key) -> bool:
    return Qt.Key_F1.value <= key.value <= Qt.Key_F24.value


def check(seq: QKeySequence) -> str | None:
    """Why the sequence cannot be the capture key, or None."""
    c = combo(seq)
    if c is None:
        return ONE_KEY
    key, mods = c
    plain = mods & ~Qt.KeypadModifier
    if plain == Qt.NoModifier and not is_function_key(key):
        return NEED_MODIFIER
    return None


# -- Windows ----------------------------------------------------------------
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 1, 2, 4, 8, 0x4000
_WIN_NAMED = {Qt.Key_Space: 0x20, Qt.Key_PageUp: 0x21, Qt.Key_PageDown: 0x22,
              Qt.Key_End: 0x23, Qt.Key_Home: 0x24, Qt.Key_Print: 0x2C,
              Qt.Key_Insert: 0x2D}


def win_combo(seq: QKeySequence):
    """(modifiers, virtual-key code) for RegisterHotKey, or None."""
    c = combo(seq)
    if c is None:
        return None
    key, mods = c
    k = key.value
    if Qt.Key_A.value <= k <= Qt.Key_Z.value or Qt.Key_0.value <= k <= Qt.Key_9.value:
        vk = k                                   # same codes as ASCII
    elif is_function_key(key):
        vk = 0x70 + k - Qt.Key_F1.value
    elif key in _WIN_NAMED:
        vk = _WIN_NAMED[key]
    else:
        return None
    m = MOD_NOREPEAT
    if mods & Qt.ControlModifier:
        m |= MOD_CONTROL
    if mods & Qt.ShiftModifier:
        m |= MOD_SHIFT
    if mods & Qt.AltModifier:
        m |= MOD_ALT
    if mods & Qt.MetaModifier:
        m |= MOD_WIN
    return m, vk


class MSG(ctypes.Structure):
    """The Win32 MSG with fixed-width fields, so it can be built and read
    on any system (the 64-bit layout)."""
    _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint32),
                ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                ("time", ctypes.c_uint32), ("pt_x", ctypes.c_int32),
                ("pt_y", ctypes.c_int32), ("lPrivate", ctypes.c_uint32)]


def hotkey_id(address: int) -> int | None:
    """The hotkey id when the MSG at `address` is a WM_HOTKEY, else None."""
    if not address:
        return None
    msg = MSG.from_address(address)
    return int(msg.wParam) if msg.message == WM_HOTKEY else None


class WinHotkeyFilter(QAbstractNativeEventFilter):
    """Calls `fire` for our WM_HOTKEY. A thread hotkey (no window) reaches
    Qt's event dispatcher as "windows_dispatcher_MSG"; a window's message
    is "windows_generic_MSG". Both are read."""

    TYPES = (b"windows_dispatcher_MSG", b"windows_generic_MSG")

    def __init__(self, fire):
        super().__init__()
        self._fire = fire

    def nativeEventFilter(self, event_type, message):
        try:
            if bytes(event_type) in self.TYPES and \
                    hotkey_id(int(message)) == HOTKEY_ID:
                self._fire()
                return True, 0
        except Exception:                # noqa: BLE001 - never break the loop
            pass
        return False, 0


class WinBackend:
    available = True

    def __init__(self, fire):
        from ctypes import wintypes
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int,
                                                wintypes.UINT, wintypes.UINT]
        self._user32.RegisterHotKey.restype = wintypes.BOOL
        self._user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.UnregisterHotKey.restype = wintypes.BOOL
        self._filter = WinHotkeyFilter(fire)
        self._installed = False
        self._on = False

    def register(self, seq: QKeySequence) -> str | None:
        c = win_combo(seq)
        if c is None:
            return UNKNOWN_KEY
        if not self._installed:
            app = QCoreApplication.instance()
            if app is not None:
                app.installNativeEventFilter(self._filter)
                self._installed = True
        # ASSUMES: RegisterHotKey succeeds for a free key. Tested false: a
        # refused key comes back as the TAKEN sentence (the fake backend).
        if not self._user32.RegisterHotKey(None, HOTKEY_ID, *c):
            return TAKEN.format(key=seq.toString(QKeySequence.NativeText))
        self._on = True
        return None

    def unregister(self) -> None:
        if self._on:
            self._user32.UnregisterHotKey(None, HOTKEY_ID)
            self._on = False


# -- macOS --------------------------------------------------------------------
CARBON = "/System/Library/Frameworks/Carbon.framework/Carbon"
CMD_KEY, SHIFT_KEY, OPTION_KEY, CONTROL_KEY = 0x100, 0x200, 0x800, 0x1000
_MAC_CODES = {
    "A": 0, "S": 1, "D": 2, "F": 3, "H": 4, "G": 5, "Z": 6, "X": 7, "C": 8,
    "V": 9, "B": 11, "Q": 12, "W": 13, "E": 14, "R": 15, "Y": 16, "T": 17,
    "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "9": 25, "7": 26,
    "8": 28, "0": 29, "O": 31, "U": 32, "I": 34, "P": 35, "L": 37, "J": 38,
    "K": 40, "N": 45, "M": 46}
_MAC_F = (122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111)
_MAC_NAMED = {Qt.Key_Space: 49}


def fourcc(code: str) -> int:
    return int.from_bytes(code.encode("ascii"), "big")


def mac_combo(seq: QKeySequence):
    """(virtual key code, Carbon modifiers), or None. Qt's Ctrl is the
    Command key on the Mac and Qt's Meta the Control key."""
    c = combo(seq)
    if c is None:
        return None
    key, mods = c
    k = key.value
    if Qt.Key_A.value <= k <= Qt.Key_Z.value or Qt.Key_0.value <= k <= Qt.Key_9.value:
        code = _MAC_CODES.get(chr(k))
    elif Qt.Key_F1.value <= k <= Qt.Key_F12.value:
        code = _MAC_F[k - Qt.Key_F1.value]
    else:
        code = _MAC_NAMED.get(key)
    if code is None:
        return None
    # ASSUMES: Qt's default Ctrl/Meta swap on the Mac (the app never sets
    # AA_MacDontSwapCtrlAndMeta), so Ctrl here is the Command key.
    m = 0
    if mods & Qt.ControlModifier:
        m |= CMD_KEY
    if mods & Qt.ShiftModifier:
        m |= SHIFT_KEY
    if mods & Qt.AltModifier:
        m |= OPTION_KEY
    if mods & Qt.MetaModifier:
        m |= CONTROL_KEY
    return code, m


class EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p,
                           ctypes.c_void_p)
K_EVENT_HOTKEY_PRESSED = 5


class MacBackend:
    available = True

    def __init__(self, fire):
        self._fire = fire
        c = ctypes.CDLL(CARBON)
        c.GetApplicationEventTarget.restype = ctypes.c_void_p
        c.GetApplicationEventTarget.argtypes = []
        c.InstallEventHandler.restype = ctypes.c_int32
        c.InstallEventHandler.argtypes = [
            ctypes.c_void_p, HANDLER, ctypes.c_ulong,
            ctypes.POINTER(EventTypeSpec), ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p)]
        c.RegisterEventHotKey.restype = ctypes.c_int32
        c.RegisterEventHotKey.argtypes = [
            ctypes.c_uint32, ctypes.c_uint32, EventHotKeyID, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
        c.UnregisterEventHotKey.restype = ctypes.c_int32
        c.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
        self._carbon = c
        # kept on the object: Carbon calls it for as long as the app runs
        self._handler = HANDLER(self._on_event)
        self._handler_ref = ctypes.c_void_p()
        self._key_ref = ctypes.c_void_p()

    def _on_event(self, _call, _event, _data) -> int:
        try:
            self._fire()
        except Exception:                # noqa: BLE001 - never into Carbon
            pass
        return 0

    def _install(self) -> int:
        if self._handler_ref:
            return 0
        spec = EventTypeSpec(fourcc("keyb"), K_EVENT_HOTKEY_PRESSED)
        return self._carbon.InstallEventHandler(
            self._carbon.GetApplicationEventTarget(), self._handler, 1,
            ctypes.byref(spec), None, ctypes.byref(self._handler_ref))

    def register_code(self, code: int, mods: int) -> int:
        """The OSStatus of installing the handler and registering the key."""
        status = self._install()
        if status:
            return status
        self.unregister()
        return self._carbon.RegisterEventHotKey(
            code, mods, EventHotKeyID(fourcc("ANSH"), 1),
            self._carbon.GetApplicationEventTarget(), 0,
            ctypes.byref(self._key_ref))

    def register(self, seq: QKeySequence) -> str | None:
        c = mac_combo(seq)
        if c is None:
            return UNKNOWN_KEY
        if self.register_code(*c) != 0:
            self._key_ref = ctypes.c_void_p()
            return TAKEN.format(key=seq.toString(QKeySequence.NativeText))
        return None

    def unregister(self) -> int:
        if not self._key_ref:
            return 0
        status = self._carbon.UnregisterEventHotKey(self._key_ref)
        self._key_ref = ctypes.c_void_p()
        return status


# -- Linux and anything else ----------------------------------------------------
class NoBackend:
    available = False

    def __init__(self, fire):
        pass

    def register(self, seq: QKeySequence) -> str | None:
        return NOT_ON_LINUX

    def unregister(self) -> None:
        pass


def backend_class():
    if sys.platform == "win32":
        return WinBackend
    if sys.platform == "darwin":
        return MacBackend
    return NoBackend


class GlobalHotkey(QObject):
    """The capture key. `activated` fires when it is pressed anywhere.
    Nothing is registered until set_sequence is called."""

    activated = Signal()

    def __init__(self, parent=None, backend=None):
        super().__init__(parent)
        self._backend_cls = backend or backend_class()
        self._backend = None

    @property
    def available(self) -> bool:
        return self._backend_cls.available

    def _fire(self) -> None:
        self.activated.emit()

    def _get(self):
        if self._backend is None:
            self._backend = self._backend_cls(self._fire)
        return self._backend

    def set_sequence(self, seq: QKeySequence) -> str | None:
        """Register `seq` (the old key goes); the reason when it cannot."""
        if not self.available:
            return NOT_ON_LINUX
        problem = check(seq)
        if problem:
            self.clear()
            return problem
        try:
            backend = self._get()
            backend.unregister()
            return backend.register(seq)
        except Exception as e:           # noqa: BLE001 - a missing library
            return f"The capture key could not be set: {e}"

    def clear(self) -> None:
        if self._backend is not None:
            try:
                self._backend.unregister()
            except Exception:            # noqa: BLE001
                pass
