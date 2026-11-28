"""One capture key that works while Annotshot is not in front.

Windows: RegisterHotKey for the thread (no window) and a native event
filter that catches WM_HOTKEY as Qt's event loop takes it from the queue.
macOS: Carbon's RegisterEventHotKey with an event handler on the
application target (no permission needed; Qt's loop runs the run loop that
delivers it). Linux: not built yet -- `available` is False.

Importing this module loads nothing: each system's library is opened when
its backend is made. A replacement is registered before the previous handle is released.
"""
from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence

from .keywords import key_words


def default_for_platform(platform: str) -> str:
    """The capture key requested when no preference is saved."""
    if platform == "win32":
        return "Ctrl+Alt+Space"
    if platform == "darwin":
        return "Meta+Ctrl+Space"
    return "Shift+Alt+Space"


DEFAULT = default_for_platform(sys.platform)
NOT_ON_LINUX = "not available on Linux yet"
NEED_MODIFIER = (
    "Use Control, Option, Shift or Command with the key (or an F key alone)"
    if sys.platform == "darwin" else
    "Use Ctrl, Alt or Shift with the key (or an F key alone)"
)
ONE_KEY = "Use one key with its modifiers"
UNKNOWN_KEY = "This key cannot be used from anywhere; try a letter, a digit or an F key"
MAC_KEYPAD = "Keypad keys cannot be used for capture on this Mac. Choose another key."
WIN_KEYPAD = "Choose a digit above the letters. Annotshot reads keypad digits as top-row digits for capture."
RELEASE = "Could not release {key}. Try again."
STILL_USING = "{new} is taken by the system or another app. Still using {old}."
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
    if sys.platform == "darwin" and mods & Qt.KeypadModifier:
        return MAC_KEYPAD
    if (sys.platform == "win32" and mods & Qt.KeypadModifier
            and Qt.Key_0.value <= key.value <= Qt.Key_9.value):
        return WIN_KEYPAD
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
    if mods & Qt.KeypadModifier and Qt.Key_0.value <= k <= Qt.Key_9.value:
        return None
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


def native_callback(fire, *args, native_time=None):
    """Stamp on native receipt, before a backend queues its callback."""
    return fire.stamp(*args, native_time=native_time) if hasattr(fire, "stamp") else lambda: fire(*args)


class WinHotkeyFilter(QAbstractNativeEventFilter):
    """Calls `fire` for our WM_HOTKEY. A thread hotkey (no window) reaches
    Qt's event dispatcher as "windows_dispatcher_MSG"; a window's message
    is "windows_generic_MSG". Both are read."""

    TYPES = (b"windows_dispatcher_MSG", b"windows_generic_MSG")

    def __init__(self, fire, identity=HOTKEY_ID):
        super().__init__()
        self._fire = fire
        self.identity = identity

    def nativeEventFilter(self, event_type, message):
        try:
            if bytes(event_type) in self.TYPES and \
                    hotkey_id(int(message)) == self.identity:
                native_callback(self._fire, native_time=MSG.from_address(int(message)).time)()
                return True, 0
        except Exception:                # noqa: BLE001 - never break the loop
            pass
        return False, 0


class WinBackend:
    available = True
    _next_id = HOTKEY_ID

    def __init__(self, fire):
        from ctypes import wintypes
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int,
                                                wintypes.UINT, wintypes.UINT]
        self._user32.RegisterHotKey.restype = wintypes.BOOL
        self._user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.UnregisterHotKey.restype = wintypes.BOOL
        self._id = WinBackend._next_id
        WinBackend._next_id += 1
        self._filter = WinHotkeyFilter(fire, self._id)
        self._installed = False
        self._on = False

    def event_time_now(self):
        # ASSUMES: MSG.time and GetTickCount share the 32-bit millisecond
        # clock; queued hotkeys are delivered within half its wrap period.
        tick = ctypes.WinDLL("kernel32", use_last_error=True).GetTickCount
        tick.argtypes = []
        tick.restype = ctypes.c_uint32
        return int(tick())

    @staticmethod
    def time_after(press, end):
        return 0 < ((press - end) & 0xffffffff) < 0x80000000

    def register(self, seq: QKeySequence) -> str | None:
        c = win_combo(seq)
        if c is None:
            pair = combo(seq)
            return WIN_KEYPAD if pair and pair[1] & Qt.KeypadModifier and Qt.Key_0.value <= pair[0].value <= Qt.Key_9.value else UNKNOWN_KEY
        if not self._installed:
            app = QCoreApplication.instance()
            if app is not None:
                app.installNativeEventFilter(self._filter)
                self._installed = True
        # ASSUMES: RegisterHotKey succeeds for a free key. Tested false: a
        # refused key comes back as the TAKEN sentence (the fake backend).
        if not self._user32.RegisterHotKey(None, getattr(self, "_id", HOTKEY_ID), *c):
            if getattr(self, "_filter", None) is not None and self._installed:
                QCoreApplication.instance().removeNativeEventFilter(self._filter)
                self._installed = False
            return TAKEN.format(key=key_words(seq))
        self._on = True
        return None

    def unregister(self) -> None:
        if self._on:
            if not self._user32.UnregisterHotKey(None, getattr(self, "_id", HOTKEY_ID)):
                raise RuntimeError("UnregisterHotKey failed (returned zero)")
            self._on = False
        if getattr(self, "_installed", False):
            QCoreApplication.instance().removeNativeEventFilter(self._filter)
            self._installed = False


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
    if mods & Qt.KeypadModifier:
        return None
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
K_EVENT_HOTKEY_RELEASED = 6


class MacBackend:
    available = True
    _next_id = 1

    def __init__(self, fire):
        self._fire = fire
        self._id = MacBackend._next_id
        MacBackend._next_id += 1
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

    def event_time_now(self):
        # ASSUMES: Carbon GetEventTime and GetCurrentEventTime share the
        # monotonic seconds clock, including while Qt queues an event.
        now = self._carbon.GetCurrentEventTime
        now.argtypes = []
        now.restype = ctypes.c_double
        return now()

    @staticmethod
    def time_after(press, end):
        return press > end

    def _on_event(self, _call, event, _data) -> int:
        c = self._carbon
        c.GetEventTime.argtypes = [ctypes.c_void_p]
        c.GetEventTime.restype = ctypes.c_double
        c.GetEventKind.argtypes = [ctypes.c_void_p]
        c.GetEventKind.restype = ctypes.c_uint32
        c.GetEventParameter.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
            ctypes.c_uint32, ctypes.c_void_p, ctypes.c_ulong,
            ctypes.c_void_p, ctypes.c_void_p]
        c.GetEventParameter.restype = ctypes.c_int32
        identity = EventHotKeyID()
        status = self._carbon.GetEventParameter(event, fourcc("----"),
            fourcc("hkid"), None, ctypes.sizeof(identity), None,
            ctypes.byref(identity))
        if status or identity.id != self._id or identity.signature != fourcc("ANSH"):
            return -9874  # eventNotHandledErr: another registration owns it
        try:
            native_callback(self._fire, self._carbon.GetEventKind(event) == K_EVENT_HOTKEY_PRESSED,
                            native_time=c.GetEventTime(event))()
        except Exception:                # never unwind into Carbon
            pass
        return 0

    def _install(self) -> int:
        if self._handler_ref:
            return 0
        specs = (EventTypeSpec * 2)(
            EventTypeSpec(fourcc("keyb"), K_EVENT_HOTKEY_PRESSED),
            EventTypeSpec(fourcc("keyb"), K_EVENT_HOTKEY_RELEASED))
        return self._carbon.InstallEventHandler(
            self._carbon.GetApplicationEventTarget(), self._handler, 2,
            specs, None, ctypes.byref(self._handler_ref))

    def _remove_handler(self):
        remove = self._carbon.RemoveEventHandler
        remove.argtypes = [ctypes.c_void_p]
        remove.restype = ctypes.c_int32
        remove(self._handler_ref)

    def register_code(self, code: int, mods: int) -> int:
        """The OSStatus of installing the handler and registering the key."""
        status = self._install()
        self._setup_problem = status
        if status:
            return status
        status = self._carbon.RegisterEventHotKey(
            code, mods, EventHotKeyID(fourcc("ANSH"), self._id),
            self._carbon.GetApplicationEventTarget(), 0,
            ctypes.byref(self._key_ref))
        if status and self._handler_ref:
            self._remove_handler()
            self._handler_ref = ctypes.c_void_p()
        return status

    def register(self, seq: QKeySequence) -> str | None:
        c = mac_combo(seq)
        if c is None:
            pair = combo(seq)
            return MAC_KEYPAD if pair and pair[1] & Qt.KeypadModifier else UNKNOWN_KEY
        if self.register_code(*c) != 0:
            self._key_ref = ctypes.c_void_p()
            if getattr(self, "_setup_problem", 0):
                return f"The capture key could not be set: could not install its handler ({self._setup_problem})"
            return TAKEN.format(key=key_words(seq))
        return None

    def unregister(self) -> int:
        if not self._key_ref:
            return 0
        status = self._carbon.UnregisterEventHotKey(self._key_ref)
        if status:
            raise RuntimeError(f"UnregisterEventHotKey failed ({status})")
        self._key_ref = ctypes.c_void_p()
        if getattr(self, "_handler_ref", None):
            self._remove_handler()
            self._handler_ref = ctypes.c_void_p()
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
    """Own the confirmed registration and any old handles awaiting release.

    Each backend owns one independent native handle. During a swap two
    backends coexist; the old one is never touched after a refused register.
    """
    activated = Signal()
    native_event = Signal(object)

    def __init__(self, parent=None, backend=None):
        super().__init__(parent)
        self._backend_cls = backend or backend_class()
        self._backend = None
        self._registered = False
        self.sequence = QKeySequence()
        self._retained = []
        self.event_epoch = lambda: 0
        self._down = set()
        self._try_end = None
        self.cleanup_blocked = False

    def try_boundary(self):
        backend = self._backend
        if backend is not None and hasattr(backend, "event_time_now"):
            # ASSUMES: the adapter's event clock is the clock on its raw
            # native presses. Never substitute Qt time or dispatch time.
            return backend.event_time_now(), backend.time_after
        return None

    @staticmethod
    def after_boundary(native_time, boundary):
        return native_time is None or boundary is None or boundary[1](native_time, boundary[0])

    def finish_try(self):
        backend = self._backend
        if backend is not None and hasattr(backend, "event_time_now"):
            self._try_end = (backend.event_time_now(), backend.time_after)

    def after_latest_try(self, native_time):
        # ASSUMES: a delivery without native time represents a press now;
        # direct callers and backends without a native clock use this road.
        return (native_time is None or self._try_end is None
                or self._try_end[1](native_time, self._try_end[0]))

    @property
    def available(self):
        return self._backend_cls.available

    @property
    def registered(self):
        return self._registered

    def stamp(self, seq=None, pressed=True, repeat=False, native_time=None):
        """Freeze native delivery metadata before any queued dispatch."""
        seq = QKeySequence(self.sequence if seq is None else seq)
        identity = seq.toString(QKeySequence.PortableText)
        repeated = repeat or (pressed and identity in self._down)
        if pressed:
            self._down.add(identity)
        else:
            self._down.discard(identity)
        event = (seq, pressed, repeated, self.event_epoch(), native_time)
        def dispatch():
            self.native_event.emit(event)
            if pressed and not repeated:
                self.activated.emit()
        return dispatch

    def deliver(self, seq=None, pressed=True, repeat=False):
        self.stamp(seq, pressed, repeat)()

    def _get(self):
        if self._backend is None:
            self._backend = self._backend_cls(lambda: self.deliver())
        return self._backend

    def _release(self, backend, seq):
        try:
            backend.unregister()
            return None
        except Exception:
            return RELEASE.format(key=key_words(seq))

    def _release_retained(self):
        for backend, seq in list(self._retained):
            problem = self._release(backend, seq)
            if problem:
                return problem
            self._retained.remove((backend, seq))
        return None

    def set_sequence(self, seq):
        self.cleanup_blocked = False
        seq = QKeySequence(seq)
        # Preflight must precede even cleanup of a failed previous release.
        problem = check(seq)
        if problem:
            return problem
        if not self.available:
            return NOT_ON_LINUX
        problem = self._release_retained()
        if problem:
            self.cleanup_blocked = True
            return problem
        if self.registered and self.sequence == seq:
            return None
        try:
            def stamp(pressed=True, repeat=False, native_time=None):
                if (candidate is not self._backend or not self.registered) and not any(
                        candidate is retained for retained, _ in self._retained):
                    return lambda: None
                # Windows supplies distinct presses; Carbon supplies both edges.
                if isinstance(candidate, WinBackend):
                    self._down.discard(seq.toString(QKeySequence.PortableText))
                return self.stamp(seq, pressed, repeat, native_time=native_time)
            def fire(pressed=True, repeat=False):
                stamp(pressed, repeat)()
            fire.stamp = stamp
            candidate = self._backend_cls(fire)
            problem = candidate.register(seq)
        except Exception as e:
            return f"The capture key could not be set: {e}"
        if problem:
            return problem
        old, old_seq = self._backend, QKeySequence(self.sequence)
        old_registered = self.registered
        self._backend, self.sequence, self._registered = candidate, seq, True
        if old is not None and old_registered:
            problem = self._release(old, old_seq)
            if problem:
                self._retained.append((old, old_seq))
        return problem

    def clear(self):
        self.cleanup_blocked = False
        problem = self._release_retained()
        if problem:
            self.cleanup_blocked = True
            return problem
        if self._backend is not None and self.registered:
            problem = self._release(self._backend, self.sequence)
            if problem:
                return problem
        self._registered = False
        self.sequence = QKeySequence()
        self._down.clear()
        return None


class KeyClock:
    """One scheduler for the beat, minimize check and try deadline."""
    def call_later(self, milliseconds, callback):
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(callback)
        timer.start(milliseconds)
        # The cancel closure also keeps the timer alive until it fires/ends.
        return timer.stop
