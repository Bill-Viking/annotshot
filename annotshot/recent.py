"""Recent captures: every capture is kept in the Recent folder
(Pictures/Annotshot/Recent) as a pair — `<stamp>.png`, the original pixels,
never rewritten, and `<stamp>.annotshot`, the editable record beside it,
written by the autosave from the first edit on — and shown in a dock pane on
the right of the window as a column of thumbnails WITH their edits, newest at
the top. The last KEEP unedited captures are kept; an edited one is never
pruned.

A click opens a capture as the current picture; the right-click menu opens,
deletes both files (no question), shows the folder, or clears it all (asked
once). A file removed outside the app simply drops from the list at the next
refresh. Filing and every autosave write run on worker threads, so the
window never waits for the disk; a write that fails is one sentence on the
status line.
"""
from __future__ import annotations

import os
import ctypes
import hashlib
import io
import json
import time
from contextlib import contextmanager, ExitStack
import re
import stat
import sys
import threading
import uuid
import unicodedata
import warnings
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from types import SimpleNamespace

from PySide6.QtCore import (QDateTime, QEvent, QObject, QRect, QRunnable, QSize, Qt,
                            QThreadPool, QTimer, QUrl, Signal)
from PySide6.QtGui import (QDesktopServices, QFont, QIcon, QImage,
                           QImageReader, QPainter, QPen, QPixmap)
from PySide6.QtWidgets import (QAbstractItemView, QAbstractSpinBox, QApplication, QDockWidget,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
                               QMessageBox, QStyle, QStyledItemDelegate, QVBoxLayout,
                               QWidget)

from . import theme

KEEP = 12
TITLE = "Recent captures"
SETTING = "recent/keep"                 # QSettings key: file each capture
KEEP_TEXT = f"Keep the last {KEEP} captures in the Recent pane"
COUNT_SETTING = "recent/count-v1"
FIRST_WELCOME = "recent/first-welcome-v1"
COUNT_ERROR = "Enter a whole number from 0 to 100."
PAUSED_TEXT = "Recent keeping is paused. Choose a count to start again."
THUMB = QSize(160, 90)                  # 16:9, letterboxed
CURRENT_ROLE = Qt.UserRole + 1
DOCK_EDGES = (Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea, Qt.BottomDockWidgetArea)
EDGE_NAMES = dict(zip(DOCK_EDGES, ('left', 'right', 'bottom')))
THUMB_GROUND = "#E9EDF1"                # Light's; the theme's "thumb-ground"
TIME_INK = "#7A8591"                    # Light's; the theme's "time-ink"
EMPTY_TEXT = "Your captures appear here."
CLEAR_QUESTION = ("Remove all {count} captures from Recent captures, including captures outside the results? The pictures "
                  "in the Recent folder are deleted; files you saved "
                  "yourself are not touched.")
FIND_SCOPE = "Search words you typed in Text or Callout."
NO_MATCH_TEXT = "No annotations match. Find looks at words you typed with Text or Callout."
MAX_FIND_META = 4 * 1024 * 1024
MAX_FIND_DIRECTORY = 1024 * 1024
# The file names: an ISO date and time with '-' for ':' (Windows refuses a
# colon in a file name) and milliseconds, so names sort by time.
# ASSUMES: the files in the folder are named by stamp_name(); a file with any
# other .png name still shows, timed by its modification time.
NAME_FORMAT = "yyyy-MM-ddTHH-mm-ss-zzz"
NAME_RE = re.compile(
    r"^(\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d-\d{3})(?:-\d+)?\.(?:png|annotshot)$", re.IGNORECASE)
EDITABLE = ".annotshot"
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
          "Oct", "Nov", "Dec")


def _count(value) -> int | None:
    if type(value) is int:
        return value if 0 <= value <= 100 else None
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,3}", value.strip()):
        number = int(value)
        return number if number <= 100 else None
    return None


def write_count(settings, number: int) -> None:
    if type(number) is not int or _count(number) is None:
        raise ValueError(COUNT_ERROR)
    settings.setValue(COUNT_SETTING, number)
    settings.setValue(SETTING, number == KEEP)  # real Boolean for 0.4.4
    settings.sync()


def read_count(settings) -> int | None:
    """A malformed numeric key wins over the old Boolean: pause, don't guess."""
    if not callable(getattr(settings, 'sync', None)):
        # Read-only preference views (the build check) expose reads only.
        # Migration belongs to a writable profile, not that inspection.
        if settings.contains(COUNT_SETTING):
            return _count(settings.value(COUNT_SETTING))
        return KEEP if settings.value(SETTING, True, type=bool) else 0
    settings.sync()
    if not settings.contains(COUNT_SETTING):
        number = KEEP if settings.value(SETTING, True, type=bool) else 0
        write_count(settings, number)
        return number
    stored_count = settings.value(COUNT_SETTING)
    number = _count(stored_count)
    if number is None:
        settings.setValue(SETTING, False)
        settings.sync()
        return None
    stored_legacy = settings.value(SETTING, number == KEEP)
    legacy = settings.value(SETTING, number == KEEP, type=bool)
    if legacy != (number == KEEP):
        number = KEEP if legacy else 0
        write_count(settings, number)
    elif (not settings.contains(SETTING) or type(stored_legacy) is not bool
          or type(stored_count) is not int):
        # INI settings lose scalar types across processes. Normalize the
        # valid loaded choice with typed writes; never coerce a bad count.
        write_count(settings, number)
    return number


def fresh_profile(settings, folder: Path) -> bool:
    # ASSUMES: startup has not yet written defaults. An uncertain inventory
    # is an established profile, never permission to offer setup or expire.
    if not callable(getattr(settings, 'allKeys', None)) or settings.allKeys():
        return False
    try:
        _root_identity(folder)
        return not any(folder.iterdir())
    except FileNotFoundError:
        return not os.path.lexists(folder)
    except OSError:
        return False


class CountSpinBox(QAbstractSpinBox):
    """Keep the typed draft separate from the committed whole number.

    QSpinBox's built-in fixup silently rounds/restores invalid drafts before
    editingFinished. Here Return and blur validate the actual text first.
    """
    committed = Signal(int)
    invalid = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = KEEP
        self._draft_edited = False
        self.setAccessibleName("Captures to keep")
        self.lineEdit().installEventFilter(self)
        self.lineEdit().textEdited.connect(self._edited)
        self.display(KEEP)

    def _edited(self, _text):
        self._draft_edited = True

    def value(self):
        return self._value

    def display(self, number):
        self._value = number or 0
        self.lineEdit().setText(str(number) if number else "Off")
        self._draft_edited = False

    def setValue(self, number):
        if _count(number) is None or type(number) is not int:
            raise ValueError(COUNT_ERROR)
        self.display(number)
        self.committed.emit(number)

    def commit(self):
        text = self.lineEdit().text().strip()
        number = 0 if text.casefold() == "off" else _count(text)
        if number is None:
            self.display(self._value)
            self.invalid.emit()
        else:
            self.setValue(number)

    def stepBy(self, steps):
        text = self.lineEdit().text().strip()
        number = 0 if text.casefold() == 'off' else _count(text)
        if number is None:
            self.commit()           # restore the last choice and name the error
            return
        self.setValue(max(0, min(100, number + steps)))

    def stepEnabled(self):
        flags = QAbstractSpinBox.StepNone
        if self._value < 100:
            flags |= QAbstractSpinBox.StepUpEnabled
        if self._value > 0:
            flags |= QAbstractSpinBox.StepDownEnabled
        return flags

    def eventFilter(self, obj, event):
        if obj is self.lineEdit() and event.type() == QEvent.FocusOut:
            self._commit_on_blur()
        return super().eventFilter(obj, event)

    def _commit_on_blur(self):
        expected = str(self._value) if self._value else 'Off'
        if self._draft_edited or self.lineEdit().text() != expected:
            self.commit()

    def focusOutEvent(self, event):
        # QAbstractSpinBox itself owns focus on the shipped Qt platforms;
        # its line edit alone does not receive every real focus transfer.
        self._commit_on_blur()
        super().focusOutEvent(event)

    def event(self, event):
        if event.type() == QEvent.ShortcutOverride and event.key() in (
                Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.commit()
            event.accept()
            return
        super().keyPressEvent(event)


class CaptureCountControl(QWidget):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window_ = window
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        self.caption = QLabel("Captures to keep", self)
        self.caption.setWordWrap(True)
        self.spin = CountSpinBox(self)
        self.spin.setObjectName("captureCount")
        self.caption.setBuddy(self.spin)
        self.note = QLabel(self)
        self.error = QLabel(self)
        for label in (self.note, self.error):
            label.setWordWrap(True)
            label.setTextFormat(Qt.PlainText)
        for widget in (self.caption, self.spin, self.note, self.error):
            box.addWidget(widget)
        self.spin.committed.connect(window.set_capture_count)
        self.spin.invalid.connect(self._invalid)
        window.captureCountChanged.connect(self.refresh)
        self.refresh()

    def _invalid(self):
        self.error.setText(COUNT_ERROR)
        self.error.show()

    def refresh(self):
        number = self.window_.capture_count()
        self.spin.display(number)
        self.error.clear()
        self.error.hide()
        self.note.setText(PAUSED_TEXT if number is None else
                          "New captures won’t be kept." if number == 0 else
                          f"Recent keeps the newest {number} captures. When the next "
                          "capture is saved to Recent, older ones without edits are removed.")
        self.spin.setAccessibleDescription(self.note.text())

    def commit(self):
        # Do not turn a paused or untouched field into an explicit Off pick.
        expected = str(self.spin.value()) if self.spin.value() else "Off"
        if self.spin.lineEdit().text() != expected:
            self.spin.commit()


def stamp_name(when: QDateTime) -> str:
    return when.toString(NAME_FORMAT) + ".png"


def editable_for(path) -> Path:
    """The editable record beside a capture's PNG (existing or to be
    written)."""
    return Path(path).with_suffix(EDITABLE)


def png_for(path) -> Path:
    return Path(path).with_suffix(".png")


def _without_extended_prefix(path: str) -> str:
    """Remove Windows' extended path prefix by text, on any system."""
    if path[:8].upper() == "\\\\?\\UNC\\":
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def taken_at(path: Path) -> QDateTime:
    """When the capture was taken: from its name, else the file's time."""
    m = NAME_RE.match(path.name)
    if m:
        when = QDateTime.fromString(m.group(1), NAME_FORMAT)
        if when.isValid():
            return when
    try:
        return QDateTime.fromSecsSinceEpoch(int(path.stat().st_mtime))
    except OSError:
        return QDateTime.currentDateTime()


def time_label(when: QDateTime, now: QDateTime | None = None) -> str:
    """"12:34" today, "Tue 12:34" within the week, the date beyond it. Fixed
    English names, so the label never depends on the system's language."""
    now = now or QDateTime.currentDateTime()
    hm = when.toString("HH:mm")
    days = when.date().daysTo(now.date())
    if days == 0:
        return hm
    if 0 < days < 7:
        return f"{DAYS[when.date().dayOfWeek() - 1]} {hm}"
    d = when.date()
    text = f"{d.day()} {MONTHS[d.month() - 1]}"
    return text if d.year() == now.date().year() else f"{text} {d.year()}"


def _version(info):
    return (_identity(info), info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _identity(info):
    return (info.st_dev, info.st_ino)


def _root_identity(folder, *, create=False):
    """Never follow a linked Recent root, including Windows reparse points."""
    if _HOST_WINDOWS:
        with _WindowsRoot(folder, create=create) as root:
            return root.identity
    try:
        info = folder.lstat()
    except FileNotFoundError:
        if not create:
            raise
        folder.mkdir(parents=True, exist_ok=True)
        info = folder.lstat()
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or getattr(info, 'st_file_attributes', 0) & 0x400):
        raise OSError("Recent must be an ordinary folder, not a link or junction")
    return _identity(info)


_DIR_FUNCTIONS = (os.open, os.stat, os.unlink, os.link, os.rename, os.mkdir, os.rmdir)
# The backend belongs to the real host, not sys.platform (also used for UI tests).
_HOST_WINDOWS = os.name == 'nt'


def _require_handles():
    # Check capabilities, not a platform guess. There is no pathname fallback
    # after admission: checks alone cannot close a root-exchange race.
    if _HOST_WINDOWS:
        _windows_native()           # missing APIs fail before any mutation
        return
    if (not all(fn in os.supports_dir_fd for fn in _DIR_FUNCTIONS)
            or not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_DIRECTORY')
            or _native_rename is None):
        raise OSError('Safe Recent directory handles are unavailable; edits remain unsaved')


def _load_rename():
    if os.name != 'posix':
        return None
    library = ctypes.CDLL(None, use_errno=True)
    name = 'renameatx_np' if sys.platform == 'darwin' else 'renameat2'
    function = getattr(library, name, None)
    if function is not None:
        function.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                             ctypes.c_char_p, ctypes.c_uint)
        function.restype = ctypes.c_int
    return function


_native_rename = _load_rename()
_RENAME_EXCLUSIVE = 4 if sys.platform == 'darwin' else 1


def _rename_noreplace(source, src, destination, dst):
    """Move one entry, including a symlink itself, without replacing anything."""
    _require_handles()
    source._name(src)
    destination._name(dst)
    if isinstance(source, _WindowsRoot):
        source.rename(src, destination, dst)
        return
    # Native flags belong to the host selected at import, even in tests that
    # simulate another platform's UI by changing sys.platform.
    if _native_rename(source.fd, os.fsencode(src), destination.fd, os.fsencode(dst), _RENAME_EXCLUSIVE):
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number), str(destination.folder / dst))


class _Root:
    """Pin a validated directory for metadata/publication/unlink operations.

    ASSUMES: a root may be exchanged after reservation. Identity checks
    refuse the exchange; POSIX dir_fd operations cannot follow its new link.
    A platform without these handles refuses before mutation.
    """
    def __new__(cls, *args, **kwargs):
        if cls is _Root and _HOST_WINDOWS:
            return object.__new__(_WindowsRoot)
        return object.__new__(cls)

    def __init__(self, folder, expected=None, *, create=False):
        self.folder, self.fd = Path(folder), None
        _require_handles()
        self.identity = _root_identity(self.folder, create=create)
        if expected is not None and self.identity != expected:
            raise OSError("Recent folder changed since reservation")
        self.fd = os.open(self.folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            if _identity(os.fstat(self.fd)) != self.identity:
                raise OSError("Recent folder changed while opening it")
            self.check()
        except BaseException:
            self.close()
            raise

    def check(self):
        if _root_identity(self.folder) != self.identity:
            raise OSError("Recent folder changed")

    @classmethod
    def held(cls, hold):
        """Duplicate the directory admitted by this editor, never its pathname."""
        if isinstance(hold.fd, _WindowsHandle):
            return _WindowsRoot.held(hold)
        _require_handles()
        root = cls.__new__(cls)
        root.folder = hold.folder
        root.fd = os.dup(hold.fd)
        root.identity = _identity(os.fstat(root.fd))
        if root.identity != hold.directory:
            root.close()
            raise OSError('Recent directory hold changed')
        return root

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @staticmethod
    def _name(name):
        if Path(name).name != str(name):
            raise OSError("Recent entry must be a single name")

    def _args(self, name):
        self._name(name)
        return name, {'dir_fd': self.fd}

    def names(self):
        return os.listdir(self.fd)

    def stat(self, name):
        path, kw = self._args(name)
        return os.stat(path, follow_symlinks=False, **kw)

    @contextmanager
    def pin(self, name):
        path, kw = self._args(name)
        before = self.stat(name)
        if not stat.S_ISREG(before.st_mode):
            raise OSError("Recent record is not a regular file")
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0), **kw)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if _version(info) != _version(before):
                raise OSError("Recent record changed while opening it")
            data = source.read()
            if _version(os.fstat(source.fileno())) != _version(info):
                raise OSError("Recent entry changed while reading")
            if _version(self.stat(name)) != _version(info):
                raise OSError("Recent entry changed while reading")
            yield data, info, source.fileno()

    def read(self, name):
        with self.pin(name) as (data, info, _):
            return data, info

    @contextmanager
    def stream(self, name):
        """Seek through one admitted regular file, without loading its pixels."""
        path, kw = self._args(name)
        before = self.stat(name)
        if not stat.S_ISREG(before.st_mode):
            raise OSError('Recent record is not a regular file')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW, **kw)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if _version(info) != _version(before):
                raise OSError('Recent record changed while opening it')
            yield source
            if (_version(os.fstat(source.fileno())) != _version(info)
                    or _version(self.stat(name)) != _version(info)):
                raise OSError('Recent record changed while reading it')
            self.check()

    @contextmanager
    def temporary(self, name, data, mode=0o600):
        path, kw = self._args(name)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600, **kw)
        try:
            with os.fdopen(fd, 'wb', closefd=False) as output:
                if output.write(data) != len(data):
                    raise OSError('Recent record write was incomplete')
                output.flush()
                os.fsync(fd)
            os.fchmod(fd, mode)
            yield fd
        finally:
            os.close(fd)

    def create(self, name, data=b''):
        path, kw = self._args(name)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, **kw)
        with os.fdopen(fd, 'wb') as output:
            if output.write(data) != len(data):
                raise OSError("Recent record write was incomplete")
            output.flush()
            os.fsync(output.fileno())
            return _identity(os.fstat(output.fileno()))

    def unlink(self, name, identity=None):
        path, kw = self._args(name)
        if identity is not None and _identity(self.stat(name)) != identity:
            raise OSError("Recent entry changed before cleanup")
        os.unlink(path, **kw)

    def publish(self, temporary, name, source=None):
        source = source or self
        source._name(temporary)
        self._name(name)
        os.link(temporary, name, src_dir_fd=source.fd, dst_dir_fd=self.fd,
                follow_symlinks=False)

class _PosixStage(_Root):
    """Private operation directory; only explicitly owned work is cleaned.

    Unknown or recovered entries are never swept. A failed restoration stays
    here, with its path in the notice, rather than risking another file.
    """
    def __init__(self, root):
        self.parent = root
        self.name = '.annotshot-stage-' + uuid.uuid4().hex
        self.folder = root.folder / self.name
        self.fd = None
        os.mkdir(self.name, 0o700, dir_fd=root.fd)
        self.fd = os.open(self.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                          dir_fd=root.fd)
        self.identity = _identity(os.fstat(self.fd))

    def __exit__(self, *_):
        self.close()
        try:
            if _identity(self.parent.stat(self.name)) == self.identity:
                os.rmdir(self.name, dir_fd=self.parent.fd)  # empty only
        except OSError:
            pass


class _WindowsReadStream(io.RawIOBase):
    """Seekable ZIP reader over the Windows road's held, serialized handle."""
    def __init__(self, api, handle, size):
        super().__init__()
        self.api, self.handle, self.size, self.position = api, handle, size, 0

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        target = offset + (self.position if whence == 1 else self.size if whence == 2 else 0)
        if target < 0 or whence not in (0, 1, 2):
            raise OSError('Invalid archive seek')
        self.position = target
        return target

    def read(self, size=-1):
        size = max(0, min(self.size - self.position, size if size >= 0 else self.size))
        if size > MAX_FIND_META + 65536:
            raise OSError('Archive read is too large')
        data = self.api.read_at(self.handle, self.position, size) if size else b''
        self.position += len(data)
        return data


class _WindowsNative:
    """The native call boundary. Every child name is relative to an open folder.

    NtCreateFile's OPEN_REPARSE_POINT applies to the final entry, including
    junctions. NtSetInformationFile takes the verified *source handle* and a
    pinned destination directory, with ReplaceIfExists FALSE. No pathname
    delete/replace fallback is permitted. Unsupported filesystems refuse.
    """
    def __init__(self):
        from ctypes import wintypes as w
        self.w = w
        self.nt = ctypes.WinDLL('ntdll', use_last_error=True)
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)

        class Unicode(ctypes.Structure):
            _fields_ = [('length', w.USHORT), ('maximum', w.USHORT), ('buffer', w.LPWSTR)]
        class Attributes(ctypes.Structure):
            _fields_ = [('length', w.ULONG), ('root', w.HANDLE),
                        ('name', ctypes.POINTER(Unicode)), ('attributes', w.ULONG),
                        ('security', w.LPVOID), ('quality', w.LPVOID)]
        class IO(ctypes.Structure):
            _fields_ = [('status', ctypes.c_void_p), ('information', ctypes.c_size_t)]
        class Info(ctypes.Structure):
            _fields_ = [('attributes', w.DWORD), ('created', w.FILETIME),
                        ('accessed', w.FILETIME), ('written', w.FILETIME),
                        ('volume', w.DWORD), ('size_high', w.DWORD), ('size_low', w.DWORD),
                        ('links', w.DWORD), ('index_high', w.DWORD), ('index_low', w.DWORD)]
        class Rename(ctypes.Structure):
            _fields_ = [('replace', w.ULONG), ('root', w.HANDLE),
                        ('length', w.ULONG), ('name', w.WCHAR * 1)]
        class FileID(ctypes.Structure):
            _fields_ = [('volume', ctypes.c_ulonglong), ('file', ctypes.c_ubyte * 16)]
        self.Unicode, self.Attributes, self.IO = Unicode, Attributes, IO
        self.Info, self.Rename, self.FileID = Info, Rename, FileID
        signatures = [
            (self.nt.NtCreateFile, [ctypes.POINTER(w.HANDLE), w.DWORD,
                ctypes.POINTER(Attributes), ctypes.POINTER(IO), w.LPVOID,
                w.ULONG, w.ULONG, w.ULONG, w.ULONG, w.LPVOID, w.ULONG], ctypes.c_long),
            (self.nt.NtSetInformationFile, [w.HANDLE, ctypes.POINTER(IO),
                w.LPVOID, w.ULONG, w.ULONG], ctypes.c_long),
            (self.nt.NtQueryInformationFile, [w.HANDLE, ctypes.POINTER(IO),
                w.LPVOID, w.ULONG, w.ULONG], ctypes.c_long),
            (self.nt.RtlNtStatusToDosError, [ctypes.c_long], w.ULONG),
            (self.k.GetFileInformationByHandle, [w.HANDLE, ctypes.POINTER(Info)], w.BOOL),
            (self.k.GetFileInformationByHandleEx, [w.HANDLE, ctypes.c_int,
                w.LPVOID, w.DWORD], w.BOOL),
            (self.k.ReadFile, [w.HANDLE, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID], w.BOOL),
            (self.k.WriteFile, [w.HANDLE, w.LPCVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID], w.BOOL),
            (self.k.SetFilePointerEx, [w.HANDLE, ctypes.c_longlong, w.LPVOID, w.DWORD], w.BOOL),
            (self.k.FlushFileBuffers, [w.HANDLE], w.BOOL),
            (self.k.SetFileTime, [w.HANDLE, ctypes.POINTER(w.FILETIME),
                ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME)], w.BOOL),
            (self.k.CloseHandle, [w.HANDLE], w.BOOL),
            (self.k.GetCurrentProcess, [], w.HANDLE),
            (self.k.DuplicateHandle, [w.HANDLE, w.HANDLE, w.HANDLE,
                ctypes.POINTER(w.HANDLE), w.DWORD, w.BOOL, w.DWORD], w.BOOL),
            (self.k.GetDriveTypeW, [w.LPCWSTR], w.UINT),
        ]
        for function, args, result in signatures:
            function.argtypes, function.restype = args, result

    def _ok(self, ok):
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    def _status(self, status):
        if status < 0:
            raise ctypes.WinError(self.nt.RtlNtStatusToDosError(status))

    def open(self, parent, name, *, directory=False, create=False,
             mutable=False, write=False, metadata=False, listing=False, hidden=False):
        if parent is None:
            # ASSUMES: Recent is on a local volume. Network/device paths do
            # not inherit this proof. Open only the volume root by full name.
            if self.k.GetDriveTypeW(str(name)) not in (2, 3, 6):
                raise OSError('Recent needs an ordinary local volume')
            name = '\\??\\' + str(name)
        buffer = ctypes.create_unicode_buffer(str(name))
        length = len(str(name).encode('utf-16-le'))
        unicode = self.Unicode(length, length + 2, ctypes.cast(buffer, self.w.LPWSTR))
        attributes = self.Attributes(ctypes.sizeof(self.Attributes), parent,
                                     ctypes.pointer(unicode), 0x40, None, None)
        handle, io = self.w.HANDLE(), self.IO()
        access = 0x100000 | 0x80  # SYNCHRONIZE | FILE_READ_ATTRIBUTES
        if directory:
            # IopOpenLinkOrRenameTarget opens the destination directory
            # internally. A persistent LIST_DIRECTORY/DELETE handle can
            # conflict with that open. Admission needs TRAVERSE/ATTRIBUTES;
            # enumeration gets its own short-lived LIST_DIRECTORY handle.
            access |= 0x20 | (1 if listing else 0)
        elif not metadata:
            access |= 0x80000000
        if mutable:
            access |= 0x10000   # DELETE, held before verification
        if write:
            access |= 0x40000000
        if create:
            access |= 0x100     # FILE_WRITE_ATTRIBUTES, on our new entry only
        options = 0x200000 | 0x20 | (1 if directory else 0x40)
        # Directory handles disallow renaming/removal of the admitted path.
        # File handles deny competing writes AND deletes, not just root swaps.
        share = 3 if directory else (7 if metadata else 1)
        self._status(self.nt.NtCreateFile(ctypes.byref(handle), access,
            ctypes.byref(attributes), ctypes.byref(io), None, 2 if hidden else 0,
            share, 2 if create else 1, options, None, 0))
        if directory and create and hidden:
            try:
                # Directory creation may ignore FileAttributes. Set HIDDEN
                # immediately through the handle of the directory we created.
                self.set_hidden(handle.value, True)
            except BaseException:
                self.close(handle.value)
                raise
        return handle.value

    def info(self, handle):
        info = self.Info()
        self._ok(self.k.GetFileInformationByHandle(handle, ctypes.byref(info)))
        file_id = self.FileID()
        self._ok(self.k.GetFileInformationByHandleEx(handle, 18,
            ctypes.byref(file_id), ctypes.sizeof(file_id)))  # FileIdInfo
        inode = int.from_bytes(bytes(file_id.file), 'little')
        if not inode:
            raise OSError('Recent cannot prove a stable Windows file ID')
        def ns(value):
            return (((value.dwHighDateTime << 32) | value.dwLowDateTime)
                    - 116444736000000000) * 100
        mode = stat.S_IFDIR if info.attributes & 0x10 else stat.S_IFREG
        if info.attributes & 0x400:
            mode = stat.S_IFLNK
        mode |= 0o444 if info.attributes & 1 else 0o666
        return SimpleNamespace(st_dev=file_id.volume, st_ino=inode, st_mode=mode,
            st_size=(info.size_high << 32) | info.size_low,
            st_mtime_ns=ns(info.written), st_ctime_ns=ns(info.created),
            st_file_attributes=info.attributes)

    def close(self, handle):
        self._ok(self.k.CloseHandle(handle))

    def duplicate(self, handle):
        process, duplicate = self.k.GetCurrentProcess(), self.w.HANDLE()
        self._ok(self.k.DuplicateHandle(process, handle, process,
            ctypes.byref(duplicate), 0, False, 2))
        return duplicate.value

    def names(self, handle):
        # ASSUMES: an empty relative UNICODE_STRING reopens RootDirectory
        # itself. NT does not accept the Win32 path components '.' or '..'.
        listing = self.open(handle, '', directory=True, listing=True)
        try:
            return self._names(listing)
        finally:
            self.close(listing)

    def _names(self, handle):
        # FILE_ID_BOTH_DIR_INFO: the WCHAR name starts at byte 104.
        # Restart once per inventory; subsequent batches continue this handle.
        result, kind = [], 11  # FileIdBothDirectoryRestartInfo
        while True:
            buffer = ctypes.create_string_buffer(65536)
            if not self.k.GetFileInformationByHandleEx(handle, kind, buffer, len(buffer)):
                error = ctypes.get_last_error()
                if error == 18:  # ERROR_NO_MORE_FILES
                    return result
                raise ctypes.WinError(error)
            kind, offset = 10, 0
            while True:
                following = int.from_bytes(buffer[offset:offset + 4], 'little')
                length = int.from_bytes(buffer[offset + 60:offset + 64], 'little')
                if length % 2 or offset + 104 + length > len(buffer):
                    raise OSError('Incomplete Windows Recent inventory')
                name = buffer[offset + 104:offset + 104 + length].decode('utf-16-le')
                if name not in ('.', '..'):
                    result.append(name)
                if following == 0:
                    break
                if following < 104 or offset + following >= len(buffer):
                    raise OSError('Incomplete Windows Recent inventory')
                offset += following

    def case_sensitive(self, handle):
        flags, io = self.w.ULONG(), self.IO()
        status = self.nt.NtQueryInformationFile(handle, ctypes.byref(io),
            ctypes.byref(flags), ctypes.sizeof(flags), 71)  # FileCaseSensitiveInformation
        # Before Win10 1803 (or on a filesystem without this class), ordinary
        # Windows names are case-insensitive. Access/I/O failures prove nothing.
        if (status & 0xffffffff) in (0xc0000003, 0xc000000d, 0xc00000bb):
            return False  # INVALID_INFO_CLASS, INVALID_PARAMETER, NOT_SUPPORTED
        self._status(status)
        return bool(flags.value & 1)

    def set_hidden(self, handle, hidden):
        class Basic(ctypes.Structure):
            _fields_ = [('created', ctypes.c_longlong), ('accessed', ctypes.c_longlong),
                        ('written', ctypes.c_longlong), ('changed', ctypes.c_longlong),
                        ('attributes', self.w.ULONG)]
        # Zero timestamps preserve them. NORMAL must stand alone and zero
        # attributes would mean "do not change", rather than "clear HIDDEN".
        attributes = self.info(handle).st_file_attributes & ~0x80
        attributes = (attributes | 2) if hidden else (attributes & ~2)
        basic, io = Basic(), self.IO()
        basic.attributes = attributes or 0x80
        self._status(self.nt.NtSetInformationFile(handle, ctypes.byref(io),
            ctypes.byref(basic), ctypes.sizeof(basic), 4))  # FileBasicInformation

    def read(self, handle):
        self._ok(self.k.SetFilePointerEx(handle, 0, None, 0))
        chunks = []
        while True:
            data, read = ctypes.create_string_buffer(1024 * 1024), self.w.DWORD()
            self._ok(self.k.ReadFile(handle, data, len(data), ctypes.byref(read), None))
            if not read.value:
                return b''.join(chunks)
            chunks.append(data.raw[:read.value])

    def read_at(self, handle, offset, size):
        self._ok(self.k.SetFilePointerEx(handle, offset, None, 0))
        data, read = ctypes.create_string_buffer(size), self.w.DWORD()
        self._ok(self.k.ReadFile(handle, data, size, ctypes.byref(read), None))
        return data.raw[:read.value]

    def write(self, handle, data):
        for offset in range(0, len(data), 1024 * 1024):
            chunk, written = data[offset:offset + 1024 * 1024], self.w.DWORD()
            self._ok(self.k.WriteFile(handle, chunk, len(chunk), ctypes.byref(written), None))
            if written.value != len(chunk):
                raise OSError('Recent record write was incomplete')
        self._ok(self.k.FlushFileBuffers(handle))

    def seal(self, handle, mode):
        # Explicit last-write time, then suppress deferred close-time updates
        # on this writing handle. Receipts can be bound before it closes.
        ticks = time.time_ns() // 100 + 116444736000000000
        stamp = self.w.FILETIME(ticks & 0xffffffff, ticks >> 32)
        frozen = self.w.FILETIME(0xffffffff, 0xffffffff)
        self._ok(self.k.SetFileTime(handle, None, None, ctypes.byref(stamp)))
        self._ok(self.k.SetFileTime(handle, None, ctypes.byref(frozen), ctypes.byref(frozen)))

    def _move_info(self, handle, parent, name, kind):
        # Native FILE_RENAME_INFORMATION / FILE_LINK_INFORMATION share this
        # prefix. ReplaceIfExists stays FALSE, even on recovery collisions.
        encoded = name.encode('utf-16-le')
        size = ctypes.sizeof(self.Rename) + len(encoded)
        buffer = ctypes.create_string_buffer(size)
        info = self.Rename.from_buffer(buffer)
        info.replace, info.root, info.length = False, parent, len(encoded)
        ctypes.memmove(ctypes.addressof(buffer) + self.Rename.name.offset, encoded, len(encoded))
        io = self.IO()
        self._status(self.nt.NtSetInformationFile(handle, ctypes.byref(io), buffer, size, kind))

    def link(self, handle, parent, name):
        self._move_info(handle, parent, name, 11)  # FileLinkInformation

    def rename(self, handle, parent, name):
        self._move_info(handle, parent, name, 10)  # FileRenameInformation

    def delete(self, handle):
        if self.info(handle).st_file_attributes & 1:
            raise PermissionError('Recent file is read-only')
        io, delete = self.IO(), self.w.BOOLEAN(True)
        self._status(self.nt.NtSetInformationFile(handle, ctypes.byref(io),
            ctypes.byref(delete), ctypes.sizeof(delete), 13))  # FileDispositionInformation


_WINDOWS_NATIVE = None


def _windows_native():
    global _WINDOWS_NATIVE
    if _WINDOWS_NATIVE is None:
        try:
            _WINDOWS_NATIVE = _WindowsNative()
        except (AttributeError, OSError) as error:
            raise OSError('Safe Windows Recent primitives are unavailable; edits remain unsaved') from error
    return _WINDOWS_NATIVE


_WINDOWS_LEASES = {}
_WINDOWS_LEASE_LOCK = threading.RLock()


class _WindowsHandle:
    def __init__(self, api, raw):
        self.api, self.raw, self.closed = api, raw, False
        self.references = 1
        self.owner = threading.get_ident()
        self.io_lock = threading.RLock()
        self.after_close = []


def _fd_info(fd):
    return fd.api.info(fd.raw) if isinstance(fd, _WindowsHandle) else os.fstat(fd)


def _dup_handle(fd):
    return (_WindowsHandle(fd.api, fd.api.duplicate(fd.raw))
            if isinstance(fd, _WindowsHandle) else os.dup(fd))


def _close_handle(fd):
    if not isinstance(fd, _WindowsHandle):
        os.close(fd)
        return
    with _WINDOWS_LEASE_LOCK:
        if not fd.closed:
            fd.references -= 1
            if fd.references:
                return
            fd.api.close(fd.raw)
            fd.closed = True
            for key, value in list(_WINDOWS_LEASES.items()):
                if value is fd:
                    del _WINDOWS_LEASES[key]
            for callback in fd.after_close:
                callback()


class _WindowsRoot(_Root):
    """Pin every component on admission; all later child use is handle-relative."""
    def __init__(self, folder, expected=None, *, create=False):
        self.folder, self.fd, self.chain = Path(folder), None, []
        self.api = _windows_native()
        absolute = Path(_without_extended_prefix(os.path.abspath(folder)))
        try:
            parent = None
            for index, name in enumerate(absolute.parts):
                if index:
                    self._name(name)
                try:
                    raw = self.api.open(parent, name, directory=True)
                except FileNotFoundError:
                    if not create or index == 0:
                        raise
                    try:
                        raw = self.api.open(parent, name, directory=True, create=True)
                    except FileExistsError:
                        raw = self.api.open(parent, name, directory=True)
                handle = _WindowsHandle(self.api, raw)
                self.chain.append(handle)
                self._directory(_fd_info(handle))
                parent = raw
            self.fd = self.chain[-1]
            self.identity = _identity(_fd_info(self.fd))
            if expected is not None and expected != self.identity:
                raise OSError('Recent folder changed since reservation')
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _directory(info):
        if not stat.S_ISDIR(info.st_mode) or info.st_file_attributes & 0x400:
            raise OSError('Recent must be an ordinary folder, not a link or junction')

    @staticmethod
    def _name(name):
        name = str(name)
        if (not name or name in ('.', '..') or any(c in name for c in '/\\:')
                or name[-1] in '. ' or '\x00' in name):
            raise OSError('Recent entry must be a single ordinary name')

    def check(self):
        self._directory(_fd_info(self.fd))
        with _WindowsRoot(self.folder, self.identity):
            pass

    @classmethod
    def held(cls, hold):
        root = object.__new__(cls)
        root.folder, root.fd, root.chain = hold.folder, None, []
        root.api = hold.fd.api
        try:
            for handle in hold.fd.chain:
                root.chain.append(_dup_handle(handle))
            root.fd = root.chain[-1]
            root.identity = _identity(_fd_info(root.fd))
            if root.identity != hold.directory:
                raise OSError('Recent directory hold changed')
            return root
        except BaseException:
            root.close()
            raise

    def duplicate(self):
        handle = _dup_handle(self.fd)
        handle.chain = []
        try:
            for ancestor in self.chain[:-1]:
                handle.chain.append(_dup_handle(ancestor))
            handle.chain.append(handle)
            return handle
        except BaseException:
            for h in handle.chain:
                _close_handle(h)
            _close_handle(handle)
            raise

    def close(self):
        for handle in reversed(self.chain):
            _close_handle(handle)
        self.chain, self.fd = [], None

    def names(self):
        self._directory(_fd_info(self.fd))
        names = self.api.names(self.fd.raw)
        for name in names:
            self._name(name)
        return names

    def _key(self, name):
        self._name(name)
        return id(self.api), self.identity, str(name).casefold()

    @contextmanager
    def _lease(self, name, *, metadata=False, create=False, write=False):
        key = self._key(name)
        deadline = time.monotonic() + 0.25
        while True:
            try:
                with _WINDOWS_LEASE_LOCK:
                    handle = _WINDOWS_LEASES.get(key)
                    if handle is not None:
                        if create:
                            raise FileExistsError(str(self.folder / name))
                        if not metadata and handle.owner != threading.get_ident():
                            # Never borrow a peer's DELETE-capable handle.
                            error = PermissionError('Recent capture is busy; work remains protected')
                            error.winerror = 32
                            raise error
                        handle.references += 1
                    else:
                        handle = _WindowsHandle(self.api, self.api.open(self.fd.raw, name,
                            metadata=metadata, mutable=not metadata, create=create,
                            write=write, hidden=create))
                        if not metadata:
                            _WINDOWS_LEASES[key] = handle
                break
            except OSError as error:
                remaining = deadline - time.monotonic()
                if (metadata or create or write or getattr(error, 'winerror', None) != 32
                        or remaining <= 0):
                    raise
                # ASSUMES: thumbnail/AV read handles can briefly deny DELETE
                # sharing. Retry only that refusal, outside the lease lock.
                time.sleep(min(0.025, remaining))
        try:
            yield handle
        finally:
            _close_handle(handle)

    def stat(self, name):
        with self._lease(name, metadata=True) as handle:
            return _fd_info(handle)

    @contextmanager
    def pin(self, name):
        with self._lease(name) as handle:
            # A borrowed native handle has one file pointer. Retain the
            # handle and serialize that pointer through the entire pin.
            with handle.io_lock:
                info = _fd_info(handle)
                if not stat.S_ISREG(info.st_mode) or info.st_file_attributes & 0x400:
                    raise OSError('Recent record is not a regular file')
                data = self.api.read(handle.raw)
                if _version(_fd_info(handle)) != _version(info):
                    raise OSError('Recent entry changed while reading')
                yield data, info, handle

    @contextmanager
    def stream(self, name):
        with self._lease(name) as handle, handle.io_lock:
            info = _fd_info(handle)
            if not stat.S_ISREG(info.st_mode) or info.st_file_attributes & 0x400:
                raise OSError('Recent record is not a regular file')
            with _WindowsReadStream(self.api, handle.raw, info.st_size) as source:
                yield source
            if _version(_fd_info(handle)) != _version(info):
                raise OSError('Recent record changed while reading it')
            self.check()

    @contextmanager
    def temporary(self, name, data, mode=0o600):
        with self._lease(name, create=True, write=True) as handle:
            with handle.io_lock:
                self.api.write(handle.raw, data)
                self.api.seal(handle.raw, mode)
                yield handle

    def create(self, name, data=b''):
        with self.temporary(name, data) as handle:
            return _identity(_fd_info(handle))

    def expiry_entries(self, entries, *, claimed=False):
        """An idle empty companion cannot be an archive or prove a filing.

        Only expiry uses this view. Keep the actual entry on disk, including
        when its PNG expires; ambiguity, links, busy handles and claims keep
        their usual protection. The candidate check owns its stem claim.
        """
        pngs = [p for p in entries if p.suffix.lower() == '.png']
        edits = [p for p in entries if p.suffix.lower() == EDITABLE]
        if len(pngs) != 1 or len(edits) != 1:
            return entries
        if not claimed and _claim_name(pngs[0]) in self.names():
            return entries
        info = self.stat(edits[0].name)
        if (info.st_size or not stat.S_ISREG(info.st_mode)
                or info.st_file_attributes & 0x400):
            return entries
        with self.pin(edits[0].name) as (data, _, _):
            return entries if data else [p for p in entries if p != edits[0]]

    @contextmanager
    def expiry_companion(self, name):
        """Pin an empty companion; delete only the one this attempt creates."""
        with ExitStack() as stack:
            try:
                handle = stack.enter_context(self._lease(name, create=True, write=True))
                created = True
            except FileExistsError:
                data, _, handle = stack.enter_context(self.pin(name))
                if data:
                    raise FileExistsError(str(self.folder / name))
                created = False
            identity, marked = None, False
            try:
                identity = _identity(_fd_info(handle))
                if created:
                    self.api.seal(handle.raw, 0o600)
                    info = _fd_info(handle)
                    if (_identity(info) != identity or info.st_size
                            or not stat.S_ISREG(info.st_mode)
                            or info.st_file_attributes & 0x400):
                        raise OSError('Recent expiry placeholder changed')
                    # Mark while exclusive, so even process death retires our
                    # placeholder. The creating handle is the deletion target.
                    self.api.delete(handle.raw)
                    marked = True
                yield
            finally:
                if created and not marked:
                    # Setup/marking may have raised before the usual mark.
                    # Never reopen by path or remove an entry with any bytes.
                    info = _fd_info(handle)
                    if identity is None:
                        # The first metadata query failed. FILE_CREATE's still
                        # exclusive handle remains our ownership proof; obtain
                        # its ID here, without opening the pathname again.
                        identity = _identity(info)
                    if (_identity(info) == identity and info.st_size == 0
                            and stat.S_ISREG(info.st_mode)
                            and not info.st_file_attributes & 0x400):
                        self.api.delete(handle.raw)

    def unlink(self, name, identity=None):
        with self._lease(name) as handle:
            info = _fd_info(handle)
            if identity is not None and _identity(info) != identity:
                raise OSError('Recent entry changed before cleanup')
            self.api.delete(handle.raw)
            if isinstance(self, _WindowsStage):
                self.pending.append(handle)
            with _WINDOWS_LEASE_LOCK:
                _WINDOWS_LEASES.pop(self._key(name), None)

    def publish(self, temporary, name, source=None):
        source = source or self
        with source._lease(temporary) as handle:
            self._name(name)
            # HIDDEN belongs to the inode, including every hard link. Clear
            # it on our temp before publication so the person's PNG/editable
            # is visible from its first instant. Failed temps stay in a hidden
            # operation directory; no existing picture's attributes are set.
            self.api.set_hidden(handle.raw, False)
            try:
                self.api.link(handle.raw, self.fd.raw, name)
            except OSError:
                self.api.set_hidden(handle.raw, True)
                raise
            with _WINDOWS_LEASE_LOCK:
                _WINDOWS_LEASES[self._key(name)] = handle

    def rename(self, name, destination, target):
        with self._lease(name) as handle:
            info = _fd_info(handle)
            if info.st_file_attributes & 1 or not info.st_mode & 0o222:
                raise PermissionError('Recent file is read-only')
            destination._name(target)
            self.api.rename(handle.raw, destination.fd.raw, target)
            with _WINDOWS_LEASE_LOCK:
                _WINDOWS_LEASES.pop(self._key(name), None)
                _WINDOWS_LEASES[destination._key(target)] = handle


class _WindowsStage(_WindowsRoot):
    def __init__(self, root):
        self.parent, self.api = root, root.api
        self.name = '.annotshot-stage-' + uuid.uuid4().hex
        self.folder, self.chain, self.pending = root.folder / self.name, [], []
        self.parent_handle = None
        self.fd = _WindowsHandle(self.api, self.api.open(root.fd.raw, self.name,
            directory=True, create=True, hidden=True))
        self.chain = [self.fd]
        try:
            self._directory(_fd_info(self.fd))
            self.identity = _identity(_fd_info(self.fd))
            self.parent_handle = _dup_handle(root.fd)
        except BaseException:
            self.close()
            raise

    def __exit__(self, *_):
        # Windows removes a marked link at last handle close. A proven inode
        # may still be pinned by the caller. Keep this directory handle until
        # those closes; remove only the same, now-empty directory, by handle.
        def finish():
            if self.fd is not None and all(h.closed for h in self.pending):
                try:
                    empty = not self.api.names(self.fd.raw)
                except OSError:
                    empty = False
                if not empty:
                    # A retained file is already at the reported location.
                    # Do not drop its directory pin to attempt any cleanup.
                    self.close()
                    _close_handle(self.parent_handle)
                    self.parent_handle = None
                    return
                # Drop the non-delete admission handle before opening our
                # empty directory for deletion. Reopen relative to the held
                # parent and verify its ID; an exchanged entry stays intact.
                # Deletion itself still uses that verified exclusive handle.
                self.close()
                cleanup = None
                try:
                    cleanup = _WindowsHandle(self.api, self.api.open(
                        self.parent_handle.raw, self.name, directory=True, mutable=True))
                    info = _fd_info(cleanup)
                    self._directory(info)
                    if _identity(info) == self.identity:
                        self.api.delete(cleanup.raw)
                except OSError:
                    pass           # retained recovery work is never swept
                finally:
                    if cleanup is not None:
                        _close_handle(cleanup)
                    _close_handle(self.parent_handle)
                    self.parent_handle = None
        for handle in self.pending:
            if not handle.closed:
                handle.after_close.append(finish)
        finish()


def _Stage(root):
    return _WindowsStage(root) if isinstance(root, _WindowsRoot) else _PosixStage(root)


@contextmanager
def _expiry_guard(root, path):
    """Hold companion absence through Windows expiry, not just its scan.

    ASSUMES: a peer can create an editable after the inventory. FILE_CREATE
    either observes it (pin only if empty) or owns an empty, delete-pending
    entry that denies competing writes/deletes until expiry finishes. The
    handle removes only its own placeholder on close, including process death.
    A pre-existing empty companion is pinned but never removed here.
    Case-sensitive directories cannot exclude every companion spelling this
    way, so they keep the original. Only explicitly unsupported case queries
    imply ordinary Windows names; other query failures keep the original.
    """
    if not isinstance(root, _WindowsRoot):
        yield
        return
    if root.api.case_sensitive(root.fd.raw):
        raise OSError(f'Recent cannot prove companion absence in this case-sensitive folder; file kept at {path}')
    name = editable_for(path).name
    try:
        with root.expiry_companion(name):
            names = root.names()
            companions = [n for n in names if Path(n).stem.casefold() == path.stem.casefold()
                          and Path(n).suffix.lower() in ('.png', EDITABLE)
                          and n.casefold() != name.casefold()]
            if (companions != [path.name]
                    or any(n.split('.pending-', 1)[0].casefold() == path.stem.casefold()
                           for n in names if '.pending-' in n)):
                raise OSError(f'Recent companions changed; file kept at {path}')
            yield
    except FileExistsError as error:
        raise OSError(f'Recent companion appeared; file kept at {path}') from error


def _moved_matches(name, data, info, expected):
    actual = _fingerprint(name, data, info)
    return (stat.S_ISREG(info.st_mode) and
            all(actual[key] == value for key, value in expected.items() if key != 'ctime_ns'))


def _restore(stage, staged, root, name):
    """No check-then-replace: a competing occupant always keeps its entry."""
    try:
        _rename_noreplace(stage, staged, root, name)
        return name
    except FileExistsError:
        for _ in range(8):
            recovery = Path(name).stem + '-recovered-' + uuid.uuid4().hex + Path(name).suffix
            try:
                _rename_noreplace(stage, staged, root, recovery)
                return recovery
            except FileExistsError:
                continue
            except OSError as error:
                raise OSError(f'{error}; retained file: {stage.folder / staged}') from error
    except OSError as error:
        raise OSError(f'{error}; retained file: {stage.folder / staged}') from error
    raise OSError(f'Could not restore; retained file: {stage.folder / staged}')


def _receipt_name(path):
    return '.' + Path(path).name + '.filed-v1'


def _fingerprint(name, data, info):
    return {'name': name, 'device': info.st_dev, 'inode': info.st_ino,
            'size': info.st_size, 'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns,
            'sha256': hashlib.sha256(data).hexdigest()}


def _claim_name(path):
    # All spellings of a stem use the same bounded portable filename.
    key = hashlib.sha256(Path(path).stem.casefold().encode('utf-8')).hexdigest()
    return '.' + key + '.claim-v1'


@dataclass
class _Claim:
    name: str
    identity: tuple

    def release(self, root):
        root.unlink(self.name, self.identity)


def _claim(root, path):
    name = _claim_name(path)
    return _Claim(name, root.create(name))


@dataclass(frozen=True)
class _CaptureFiles:
    path: Path
    entries: tuple                 # actual names and their admitted versions
    receipts: tuple = ()


@dataclass(frozen=True)
class _LibrarySnapshot:
    folder: Path
    directory: tuple | None
    captures: tuple[_CaptureFiles, ...]


def _find_text(text):
    return unicodedata.normalize('NFC', unicodedata.normalize('NFC', text).casefold())


def _annotation_metadata(source):
    # ASSUMES: an archive can be malformed or enormous. Bound the ZIP central
    # directory BEFORE ZipFile allocates it, then bound decoded metadata too.
    # _EndRecData reads only the bounded EOCD/ZIP64 tail from a seekable file.
    end = zipfile._EndRecData(source)
    if end is None or end[5] > MAX_FIND_DIRECTORY or end[4] > 4096:
        raise ValueError('Unsearchable archive directory')
    with zipfile.ZipFile(source) as archive:
        member = archive.getinfo('project.json')
        if member.file_size > MAX_FIND_META:
            raise ValueError('Annotation metadata is too large')
        with archive.open(member) as data:
            raw = data.read(MAX_FIND_META + 1)
        if len(raw) > MAX_FIND_META:
            raise ValueError('Annotation metadata is too large')
    from .scene import FORMAT, FORMAT_VERSION, LEGACY_FORMATS
    meta = json.loads(raw.decode('utf-8'))
    if not isinstance(meta, dict) or meta.get('format') not in (FORMAT, *LEGACY_FORMATS):
        raise ValueError('Unsupported annotation format')
    version = meta.get('version', 1)
    if type(version) is not int or not 1 <= version <= FORMAT_VERSION:
        raise ValueError('Unsupported annotation version')
    items = meta.get('items')
    if not isinstance(items, list):
        raise ValueError('Invalid annotation items')
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('Invalid annotation item')
        if item.get('type') in ('text', 'callout') and not isinstance(item.get('text'), str):
            raise ValueError('Invalid typed annotation')
    return items


class RecentStore:
    """The Recent folder on disk. `folder` is read at every call, so a test
    (or a changed setting) can point it elsewhere."""

    def __init__(self, folder: Callable[[], Path], keep: int = KEEP):
        self._folder = folder
        self.keep = keep

    @property
    def folder(self) -> Path:
        return Path(self._folder())

    def files(self) -> list[Path]:
        """The kept captures, newest first, one path each: the PNG, or the
        `.annotshot` alone when its PNG is gone (the editable carries the
        base). None when the folder is not there."""
        try:
            groups = self._inventory()
            found = [next((p for p in entries if p.suffix.lower() == '.png'
                           and p.is_file()),
                          next((p for p in entries if p.is_file()), None))
                     for entries in groups.values()]
        except OSError:
            return []
        return sorted((p for p in found if p is not None),
                      key=lambda p: (taken_at(p).toMSecsSinceEpoch(), p.stem),
                      reverse=True)

    def _inventory(self) -> dict[str, list[Path]]:
        """Actual names, including links: errors propagate to expiry."""
        groups: dict[str, list[Path]] = {}
        with ExitStack() as stack:
            root = stack.enter_context(_Root(self.folder)) if _HOST_WINDOWS else None
            entries = ([root.folder / name for name in root.names()
                        if Path(name).suffix.lower() in ('.png', EDITABLE)]
                       if root else self.source_entries())
            for path in sorted(entries):
                mode = root.stat(path.name).st_mode if root else path.lstat().st_mode
                if not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
                    raise OSError(f"uncertain Recent entry: {path.name}")
                groups.setdefault(path.stem.casefold(), []).append(path)
        return groups

    def companions(self, path) -> tuple[Path, Path]:
        """Use actual names on case-sensitive volumes too."""
        entries = self._inventory().get(Path(path).stem.casefold(), [])
        png = next((p for p in entries if p.suffix.lower() == '.png'), png_for(path))
        editable = next((p for p in entries if p.suffix.lower() == EDITABLE), editable_for(path))
        return png, editable

    def source_entries(self) -> list[Path]:
        """Actual source names for the Save guard; listing errors propagate.

        Do not use the thumbnail inventory: it merges companions and treats
        an unreadable directory as empty. Missing Recent has no sources yet.
        """
        folder = self.folder
        try:
            if _HOST_WINDOWS:
                with _Root(folder) as root:
                    return [folder / name for name in root.names()
                            if Path(name).suffix.lower() in ('.png', EDITABLE)]
            _root_identity(folder)
            return [p for p in folder.iterdir()
                    if p.suffix.lower() in (".png", EDITABLE)]
        except FileNotFoundError:
            if os.path.lexists(folder):
                raise
            return []

    def library_snapshot(self) -> _LibrarySnapshot:
        """Count on-disk stems, including unreadable captures; never guess empty.

        Names, no-follow metadata and directory identity use the existing
        platform road. A denied/inconsistent listing grants no Clear authority.
        """
        folder = self.folder
        entries = self.source_entries()
        try:
            with _Root(folder) as root:
                names = root.names()
                actual = {n for n in names if Path(n).suffix.lower() in ('.png', EDITABLE)}
                if actual != {p.name for p in entries}:
                    raise OSError('Recent changed while counting captures')
                groups = {}
                for path in sorted(entries):
                    info = root.stat(path.name)
                    if not (stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)):
                        raise OSError('Recent membership is uncertain')
                    groups.setdefault(path.stem.casefold(), []).append((path, _version(info)))
                captures = []
                for group in groups.values():
                    path = next((p for p, v in group if p.suffix.lower() == '.png'), group[0][0])
                    receipts = []
                    for p, _ in group:
                        name = _receipt_name(p)
                        if p.suffix.lower() == '.png' and name in names:
                            receipts.append((name, _version(root.stat(name))))
                    captures.append(_CaptureFiles(path, tuple((p.name, v) for p, v in group), tuple(receipts)))
                captures.sort(key=lambda c: (taken_at(c.path).toMSecsSinceEpoch(), c.path.stem), reverse=True)
                root.check()
                return _LibrarySnapshot(folder, root.identity, tuple(captures))
        except FileNotFoundError:
            if entries or os.path.lexists(folder):
                raise
            return _LibrarySnapshot(folder, None, ())

    def annotation_match(self, snapshot, capture, query):
        edits = [(name, version) for name, version in capture.entries
                 if Path(name).suffix.lower() == EDITABLE]
        if not edits:
            return False             # PNG-only is an ordinary nonmatch
        matched = False
        with _Root(snapshot.folder, snapshot.directory) as root:
            for name, version in edits:
                if _version(root.stat(name)) != version:
                    raise OSError('Editable changed during Find')
                with root.stream(name) as source:
                    items = _annotation_metadata(source)
                matched |= any(query in _find_text(i['text']) for i in items
                               if i.get('type') in ('text', 'callout'))
        return matched

    def find_annotations(self, query, cancelled):
        snapshot = self.library_snapshot()
        matches, skipped = [], 0
        for capture in snapshot.captures:
            if cancelled.is_set():
                return [], 0
            try:
                if self.annotation_match(snapshot, capture, query):
                    matches.append(capture.path)
            except Exception:         # one malformed capture cannot abort the library
                skipped += 1
        return matches, skipped

    def contains_destination(self, path) -> bool:
        """Save-dialog copies must live outside Recent and its descendants."""
        # ASSUMES: spelling a folder through a link does not make a copy safe
        # from Recent's cleanup. Resolve the destination before containment.
        resolved_folder = self.folder.resolve()
        folder = os.path.normcase(str(resolved_folder))
        # ASSUMES: the destination may itself be a link. The writer replaces
        # the link, not its target, so the folder that HOLDS the entry counts
        # as much as the folder its target is in.
        for resolved_parent in (Path(path).resolve().parent,
                                Path(path).parent.resolve()):
            # normcase alone does not fold case on a case-insensitive Mac volume.
            for ancestor in (resolved_parent, *resolved_parent.parents):
                try:
                    if os.path.samefile(ancestor, resolved_folder):
                        return True
                except FileNotFoundError:
                    pass               # a new folder, or Recent not made yet
            parent = os.path.normcase(str(resolved_parent))
            try:
                if os.path.commonpath((parent, folder)) == folder:
                    return True
            except ValueError:         # different Windows drives
                pass
        return False

    def owns(self, path) -> bool:
        """True when `path` is a capture's file in the Recent folder."""
        # ASSUMES: a path the app made from the folder's name carries that name.
        try:
            parent, folder = Path(path).parent, self.folder
            if os.path.normcase(os.path.abspath(parent)) == \
                    os.path.normcase(os.path.abspath(folder)):
                return True
            resolved_parent = _without_extended_prefix(str(parent.resolve()))
            resolved_folder = _without_extended_prefix(str(folder.resolve()))
            return os.path.normcase(resolved_parent) == os.path.normcase(resolved_folder)
        except OSError:
            return False

    def reserve(self, when: QDateTime | None = None) -> Path:
        """Reserve a fresh path in a validated ordinary Recent directory."""
        with _IO_LOCK, _Root(self.folder, create=True) as root:
            name = stamp_name(when or QDateTime.currentDateTime())
            path, n = self.folder / name, 1
            while True:
                try:
                    self._reserve_path(path, root)
                    return path
                except FileExistsError:
                    path = self.folder / f"{name[:-4]}-{n}.png"
                    n += 1

    def _reserve_path(self, path, root):
        if not self.owns(path) or Path(path).suffix != '.png':
            raise OSError("capture destination is outside Recent")
        if path.stem.casefold() in self._inventory() or str(path) in _RESERVED:
            raise FileExistsError(str(path))
        marker = '.' + path.name + '.reserve'
        identity = root.create(marker)
        _RESERVED.add(str(path))
        _RESERVATIONS[str(path)] = (self, marker, identity, root.identity)

    def release(self, path):
        with _IO_LOCK:
            record = _RESERVATIONS.get(str(path))
            if record is None or record[0] is not self:
                return
            _, marker, identity, directory = _RESERVATIONS.pop(str(path))[:4]
            _RESERVED.discard(str(path))
            try:
                with _Root(self.folder, directory) as root:
                    root.unlink(marker, identity)
            except OSError:
                pass  # Never clean through an exchanged root.

    def file(self, image: QImage, when: QDateTime | None = None,
             path: Path | None = None, *, keep: int | None = None) -> Path:
        """Publish PNG then its exact receipt; only complete filing rotates."""
        count = self.keep if keep is None else keep
        if type(count) is not int or not 1 <= count <= 100:
            raise OSError("Recent keeping is paused or off")
        path = Path(path) if path is not None else self.reserve(when)
        try:
            with _IO_LOCK, _Root(self.folder, create=True) as root:
                record = _RESERVATIONS.get(str(path))
                if record is None:
                    self._reserve_path(path, root)
                    record = _RESERVATIONS[str(path)]
                if record[0] is not self:
                    raise OSError("capture belongs to another reservation")
                if record[3] != root.identity:
                    raise OSError("Recent folder changed since reservation")
                # Validate records even on a write with nothing to expire.
                self._expiry_order()
                from .scene import png_bytes
                pixels = png_bytes(image)
                with _Stage(root) as stage:
                    try:
                        with stage.temporary('capture.tmp', pixels) as fd:
                            if path.stem.casefold() in self._inventory():
                                raise OSError(f"capture destination is occupied: {path.name}")
                            root.check()
                            root.publish('capture.tmp', path.name, stage)
                            stage.unlink('capture.tmp', _identity(_fd_info(fd)))
                            # Link removal changes ctime. Fingerprint our encoded
                            # bytes and the still-open fd after that last change.
                            info = _fd_info(fd)
                            if _version(root.stat(path.name)) != _version(info):
                                raise OSError('published PNG was substituted')
                            receipt = _fingerprint(path.name, pixels, info)
                            root.create(_receipt_name(path), json.dumps(receipt).encode('utf-8'))
                            if _version(root.stat(path.name)) != _version(_fd_info(fd)):
                                raise OSError('published PNG changed during receipt creation')
                            if len(record) > 4:
                                state = record[4]
                                state.original = (path.name, receipt)
                                state.capture = None
                    except OSError as error:
                        raise OSError(f'incomplete filing: {error}; retained work, if any: {stage.folder}') from error
                root.check()
                self.prune(keep=count, arrival=path, strict=True,
                           directory_identity=root.identity)
            return path
        finally:
            self.release(path)

    def _proven(self, root, path):
        """Missing/stale records grant nothing; unreadable records fail closed."""
        try:
            data, _ = root.read(_receipt_name(path))
        except FileNotFoundError:
            return False
        try:
            receipt = json.loads(data)
        except (ValueError, UnicodeError) as error:
            raise OSError("unreadable Recent filing record") from error
        try:
            pixels, info = root.read(path.name)
        except PermissionError:
            return False           # a busy picture grants no expiry authority
        return receipt == _fingerprint(path.name, pixels, info)

    def _expiry_order(self):
        """Usual discovery order, restricted to stems with proof on disk."""
        with _Root(self.folder) as root:
            groups = self._inventory()
            # A damaged record anywhere makes the inventory uncertain, even
            # if its PNG has gone. Never silently turn a bad record into proof.
            for entry in ([root.folder / n for n in root.names()] if _HOST_WINDOWS
                          else self.folder.iterdir()):
                if entry.name.startswith('.') and entry.name.endswith('.filed-v1'):
                    data, _ = root.read(entry.name)
                    try:
                        record = json.loads(data)
                        if not isinstance(record, dict) or set(record) != {
                                'name', 'device', 'inode', 'size', 'mtime_ns', 'ctime_ns', 'sha256'}:
                            raise ValueError('bad fields')
                    except (ValueError, UnicodeError) as error:
                        raise OSError("unreadable Recent filing record") from error
            ordered = []
            for entries in groups.values():
                if _HOST_WINDOWS:
                    entries = root.expiry_entries(entries)
                modes = [root.stat(p.name).st_mode for p in entries]
                regular = [p for p, mode in zip(entries, modes) if stat.S_ISREG(mode)]
                pngs = [p for p in regular if p.suffix.lower() == '.png']
                edits = [p for p in regular if p.suffix.lower() == EDITABLE]
                if edits:
                    ordered.append(pngs[0] if pngs else edits[0])
                elif pngs and any(self._proven(root, p) for p in pngs):
                    ordered.append(pngs[0])
            return sorted(ordered, key=lambda p: (
                taken_at(p).toMSecsSinceEpoch(), p.stem), reverse=True)

    def _expiry_candidate(self, root, old, expected):
        """Final check under the stem claim. Caller holds it through unlink."""
        entries = self._inventory().get(old.stem.casefold(), [])
        if _HOST_WINDOWS:
            entries = root.expiry_entries(entries, claimed=True)
        if entries != [old] or not stat.S_ISREG(root.stat(old.name).st_mode):
            return False
        if _version(root.stat(old.name)) != _version(expected) or not self._proven(root, old):
            return False
        names = root.names() if _HOST_WINDOWS else [p.name for p in self.folder.iterdir()]
        return not any(n.split('.pending-', 1)[0].casefold() == old.stem.casefold()
                       for n in names if '.pending-' in n)

    def prune(self, *, keep: int | None = None, arrival: Path | None = None,
              strict=False, directory_identity=None) -> list[Path]:
        count = self.keep if keep is None else keep
        if type(count) is not int or not 1 <= count <= 100:
            return []
        gone = []
        notices = []
        try:
            with _IO_LOCK, _Root(self.folder, directory_identity) as root:
                ordered = self._expiry_order()
                if arrival is not None:
                    # Only this filing promotes the actual arrival, never its
                    # clock or suffix. Discovery itself is left unchanged.
                    ordered = [arrival] + [p for p in ordered if p != arrival]
                selected = [(p, root.stat(p.name)) for p in ordered[count:]]
                for old, expected in selected:
                    claim = None
                    try:
                        claim = _claim(root, old)  # exclusive across processes
                        if self._expiry_candidate(root, old, expected):
                            # Hold the proven inode open until the moved entry
                            # has been verified and erased in private staging.
                            with root.pin(old.name) as (data, info, _):
                                with root.pin(_receipt_name(old)) as (proof, receipt_info, _), _expiry_guard(root, old):
                                    receipt = json.loads(proof)
                                    if receipt != _fingerprint(old.name, data, info):
                                        continue
                                    with _Stage(root) as stage:
                                        _rename_noreplace(root, old.name, stage, 'expired')
                                        try:
                                            moved, moved_info = stage.read('expired')
                                            match = _moved_matches(old.name, moved, moved_info, receipt)
                                        except OSError:
                                            match = False
                                        if match:
                                            try:
                                                stage.unlink('expired', _identity(info))
                                            except OSError:
                                                restored = _restore(stage, 'expired', root, old.name)
                                                raise OSError(f'Expiry incomplete; file kept at {root.folder / restored}')
                                            gone.append(old)
                                            root.unlink(_receipt_name(old), _identity(receipt_info))
                                        else:
                                            restored = _restore(stage, 'expired', root, old.name)
                                            raise OSError(f'Recent entry changed; file kept at {root.folder / restored}')
                    except FileExistsError:
                        continue  # busy stem, never steal its claim
                    except OSError as error:
                        notices.append(str(error))
                    finally:
                        if claim is not None:
                            try:
                                claim.release(root)
                            except OSError:
                                pass
        except OSError:
            if strict:
                raise
        for notice in notices:
            warnings.warn(notice, RuntimeWarning)
        if notices and strict:
            raise OSError('; '.join(notices))
        return gone

    def delete(self, path: Path, *, snapshot=None, capture=None) -> None:
        """Explicit deletion, including this entry's private receipt."""
        writer().waitForDone()
        if not self.owns(path):
            raise OSError('capture destination is outside Recent')
        snapshot = snapshot or self.library_snapshot()
        capture = capture or next((c for c in snapshot.captures
                                   if c.path.stem.casefold() == Path(path).stem.casefold()), None)
        if capture is None:
            return
        with _IO_LOCK, _Root(snapshot.folder, snapshot.directory) as root:
            if snapshot.folder != self.folder:
                raise OSError('Recent folder changed since confirmation')
            claim = _claim(root, path)
            try:
                current = {n for n in root.names() if Path(n).stem.casefold() == capture.path.stem.casefold()
                           and Path(n).suffix.lower() in ('.png', EDITABLE)}
                if current != {n for n, _ in capture.entries}:
                    raise OSError('Capture changed since confirmation; kept it')
                for name, version in capture.entries:
                    if _version(root.stat(name)) != version or not stat.S_ISREG(version[1]):
                        raise OSError('Capture changed or is a link; kept it')
                # ASSUMES: another process may exchange a name even after the
                # check. Move without replacement, verify the actual moved
                # entry, and restore on mismatch/failure, as expiry already does.
                with _Stage(root) as stage:
                    staged = []
                    try:
                        for index, (name, version) in enumerate(capture.entries):
                            data, info = root.read(name)
                            if _version(info) != version:
                                raise OSError('Capture changed since confirmation; kept it')
                            expected = _fingerprint(name, data, info)
                            del data
                            target = f'removed-{index}'
                            _rename_noreplace(root, name, stage, target)
                            staged.append((name, target))
                            data, info = stage.read(target)
                            matches = (_version(info)[:4] == version[:4]
                                       and _moved_matches(name, data, info, expected))
                            del data
                            if not matches:
                                raise OSError('Capture changed during removal; kept it')
                        for name, target in list(staged):
                            stage.unlink(target)
                            staged.remove((name, target))
                    finally:
                        for name, target in staged:
                            _restore(stage, target, root, name)
                for name, version in capture.receipts:
                    try:
                        if _version(root.stat(name)) == version:
                            root.unlink(name, version[0])
                    except FileNotFoundError:
                        pass
            finally:
                claim.release(root)

    def clear(self, snapshot=None) -> list[Path]:
        snapshot = snapshot or self.library_snapshot()
        gone, failures = [], []
        for capture in snapshot.captures:
            try:
                self.delete(capture.path, snapshot=snapshot, capture=capture)
            except OSError as error:
                failures.append(str(error))
            # Only proven absence of the ENTIRE stem can release its scene.
            try:
                with _Root(snapshot.folder, snapshot.directory) as root:
                    survives = any(Path(n).stem.casefold() == capture.path.stem.casefold()
                                   and Path(n).suffix.lower() in ('.png', EDITABLE) for n in root.names())
                if not survives:
                    gone.append(capture.path)
            except OSError:
                pass
        if failures:
            error = OSError('Could not remove all Recent captures: ' + '; '.join(failures))
            error.removed = gone
            raise error
        return gone


_RESERVED: set[str] = set()
_RESERVATIONS: dict[str, tuple] = {}
_IO_LOCK = threading.RLock()
_WRITER: QThreadPool | None = None


class RecentConflict(OSError):
    """The editor's loaded revision no longer owns in-place publication."""


@dataclass
class _EditState:
    directory: tuple
    original: tuple | None
    companion: tuple | None
    capture: str | None = None
    hold: object = None
    conflicted: bool = False
    lock: object = field(default_factory=threading.RLock, repr=False, compare=False)


@dataclass
class _EditHold:
    folder: Path
    directory: tuple
    state: _EditState
    marker: str | None
    marker_identity: tuple | None
    claim: _Claim | None
    fd: int | _WindowsHandle | None
    users: int = 1

    def __del__(self):
        if self.fd is not None:
            _close_hold_handle(self.fd)
            self.fd = None


def _close_hold_handle(fd):
    if isinstance(fd, _WindowsHandle):
        for handle in reversed(fd.chain):
            _close_handle(handle)
    else:
        os.close(fd)


def _edit_entries(root, path):
    names = sorted(n for n in root.names()
                   if Path(n).stem.casefold() == Path(path).stem.casefold()
                   and Path(n).suffix.lower() in ('.png', EDITABLE))
    pngs = [n for n in names if Path(n).suffix.lower() == '.png']
    edits = [n for n in names if Path(n).suffix.lower() == EDITABLE]
    if len(pngs) > 1 or len(edits) > 1:
        raise RecentConflict('Save conflict: Recent has ambiguous companions; use Save As')
    if any(not stat.S_ISREG(root.stat(n).st_mode) for n in names):
        raise RecentConflict('Save conflict: Recent entry is not a regular file; use Save As')
    return (pngs or [None])[0], (edits or [None])[0]


def _read_revision(root, name):
    if name is None:
        return None, None
    data, info = root.read(name)
    return (name, _fingerprint(name, data, info)), data


def _read_edit(root, path):
    png, edit = _edit_entries(root, path)
    original, pixels = _read_revision(root, png)
    companion, archive = _read_revision(root, edit)
    return _EditState(root.identity, original, companion), pixels, archive


def edit_source(path):
    """Read both actual companions under the stem claim, never just the PNG."""
    path = Path(path)
    with _IO_LOCK, _Root(path.parent) as root:
        claim = _claim(root, path)
        try:
            state, _, _ = _read_edit(root, path)
            if state.original is None and state.companion is None:
                raise FileNotFoundError('That capture is no longer in Recent')
            return state
        finally:
            claim.release(root)


def load_edit(path, *, fallback=True):
    """Bind the baseline to the exact bytes the editor loads, under one claim."""
    from .scene import Document
    path = Path(path)
    with _IO_LOCK, _Root(path.parent) as root:
        claim = _claim(root, path)
        try:
            state, pixels, archive = _read_edit(root, path)
            if pixels is None and archive is None:
                raise FileNotFoundError('That capture is no longer in the Recent folder')
            doc = None
            if archive is not None:
                try:
                    with warnings.catch_warnings():
                        if fallback:
                            warnings.simplefilter('ignore')
                        doc = Document.load_bytes(archive, root.folder / state.companion[0])
                except Exception:
                    if not fallback:
                        raise
                    pass  # raw fallback still binds the actual companion revision
            if doc is None:
                if not fallback:
                    raise FileNotFoundError(str(path))
                img = QImage.fromData(pixels or b'', 'PNG')
                if img.isNull():
                    raise OSError('That capture could not be read')
                doc = Document(img)
            name = state.companion[0] if state.companion else editable_for(path).name
            doc.path = str(root.folder / name)
            doc._recent_source = state
            root.check()
            return doc
        finally:
            claim.release(root)


def capture_source(path):
    """A reserved capture starts with explicit companion absence.

    The filer supplies its own final fd revision to this same lineage. An
    editor never discovers a different writer's revision by a later read.
    """
    path = Path(path)
    with _IO_LOCK, _Root(path.parent) as root:
        record = _RESERVATIONS[str(path)]
        state = _EditState(record[3], None, None, capture=path.name)
        _RESERVATIONS[str(path)] = (*record[:4], state)
        return state


def _compare_edit(root, path, state, *, admission=False):
    if state.conflicted:
        raise RecentConflict('Save conflict: another editor saved this capture; use Save As')
    if root.identity != state.directory:
        raise RecentConflict('Save conflict: Recent folder changed; use Save As')
    actual, _, _ = _read_edit(root, path)
    if state.capture is not None:
        # Admission may precede the asynchronous filer. Publication cannot.
        if not admission or actual.original is not None:
            raise OSError('The capture has not finished filing; edits remain unsaved')
    elif actual.original != state.original:
        raise RecentConflict('Save conflict: the original changed; use Save As')
    if actual.companion != state.companion:
        raise RecentConflict('Save conflict: another editor saved this capture; use Save As')
    if state.capture is None and state.original is None and state.companion is None:
        raise RecentConflict('Save conflict: that capture is no longer in Recent; use Save As')


def pending_edit(path, expected=None) -> _EditHold:
    """Admission precedes debounce. One editor's queued snapshots share lineage."""
    path = Path(path)
    with _IO_LOCK, _Root(path.parent) as root:
        state = expected
        if state is not None and state.conflicted:
            raise RecentConflict('Save conflict: another editor saved this capture; use Save As')
        if state is not None:
            with state.lock:
                if state.hold is not None:
                    hold = state.hold
                    if root.identity != hold.directory:
                        raise RecentConflict('Save conflict: Recent folder changed; use Save As')
                    # One editor's marker protects all its queued generations.
                    name, identity = ((hold.marker, hold.marker_identity) if hold.marker is not None
                                      else (hold.claim.name, hold.claim.identity))
                    if _identity(root.stat(name)) != identity:
                        raise RecentConflict('Save conflict: this editor lost its protection; use Save As')
                    hold.users += 1
                    return hold
        claim = _claim(root, path)
        try:
            if state is None:
                state, _, _ = _read_edit(root, path)
            _compare_edit(root, path, state, admission=True)
        except BaseException:
            claim.release(root)
            raise
        try:
            hold = _EditHold(path.parent, root.identity, state, None, None, claim,
                root.duplicate() if isinstance(root, _WindowsRoot) else os.dup(root.fd))
        except BaseException:
            claim.release(root)
            raise
        state.hold = hold
        marker = path.stem + '.pending-' + uuid.uuid4().hex
        try:
            hold.marker_identity = root.create(marker)
            hold.marker = marker
        except OSError:
            return hold  # durable claim intentionally survives failure/crash
        claim.release(root)
        hold.claim = None
        return hold


@contextmanager
def _editing(path, holds):
    """Compare the loaded revision under the claim held through publication."""
    holds = tuple(holds)
    if not holds:
        yield None
        return
    first = holds[0]
    if first.state.conflicted:
        raise RecentConflict('Save conflict: another editor saved this capture; use Save As')
    with _Root.held(first) as root:
        _check_edit_root(root)
        claim = next((h.claim for h in holds if h.claim is not None), None)
        owned = claim is not None
        if owned:
            if _identity(root.stat(claim.name)) != claim.identity:
                raise OSError('Recent edit claim changed')
        else:
            deadline = time.monotonic() + 0.5
            while True:
                try:
                    claim = _claim(root, Path(path))
                    break
                except FileExistsError:
                    if time.monotonic() >= deadline:
                        raise OSError('Recent capture is busy; edits remain unsaved')
                    time.sleep(0.01)
        try:
            with ExitStack() as pins:
                if isinstance(root, _WindowsRoot):
                    # Keep both loaded revisions locked through install and
                    # rollback. A folder lock cannot protect either child.
                    for expected in (first.state.original, first.state.companion):
                        if expected is not None:
                            pins.enter_context(_optional_pin(root, expected))
                _compare_edit(root, path, first.state)
                yield root
        finally:
            if not owned:
                claim.release(root)


def finish_edits(path, markers, root=None, *, abandon=False):
    if not markers:
        return
    if root is None:
        active = [hold for hold in markers if hold.users and hold.fd is not None]
        if not active:
            return
        with _Root.held(active[0]) as held_root:
            finish_edits(path, active, held_root, abandon=abandon)
        return
    for hold in markers:
        with hold.state.lock:
            _finish_hold(root, hold, abandon)


def _finish_hold(root, hold, abandon):
    if hold.users == 0:
        return
    if not abandon and hold.users > 1:
        hold.users -= 1
        return
    if hold.marker is not None:
        try:
            root.unlink(hold.marker, hold.marker_identity)
        except FileNotFoundError:
            pass
    if hold.claim is not None:
        hold.claim.release(root)
        hold.claim = None
    hold.users = 0
    hold.state.hold = None
    if hold.fd is not None:
        _close_hold_handle(hold.fd)
        hold.fd = None


def _check_edit_root(root):
    try:
        root.check()
    except OSError as error:
        raise RecentConflict('Save conflict: Recent folder changed; use Save As') from error


class _EditableTarget(str):
    """A path-shaped pinned sink keeps ordinary writer call seams intact."""
    def __new__(cls, path, root, state):
        self = super().__new__(cls, str(path))
        self.root, self.state = root, state
        return self

    def write_encoded(self, data):
        from .scene import _NEW_FILE_MODE
        root, state = self.root, self.state
        name = Path(self).name
        expected = state.companion
        with _Stage(root) as stage:
            staged_old = False
            old_data = old_info = old_fd = None
            # Keep the old inode pinned even through rollback. Its ctime can
            # change on moves; a restored baseline comes from this fd only.
            with _optional_pin(root, expected) as pinned:
                if pinned is not None:
                    old_data, old_info, old_fd = pinned
                mode = stat.S_IMODE(old_info.st_mode) if old_info else _NEW_FILE_MODE
                try:
                    with stage.temporary('editable.tmp', data, mode) as fd:
                        _check_edit_root(root)
                        if expected is not None:
                            _rename_noreplace(root, name, stage, 'previous')
                            staged_old = True
                            moved, info = stage.read('previous')
                            if not _moved_matches(name, moved, info, expected[1]):
                                raise RecentConflict('Save conflict: companion changed at publication; use Save As')
                        try:
                            root.publish('editable.tmp', name, stage)
                        except FileExistsError as error:
                            raise RecentConflict('Save conflict: companion appeared at publication; use Save As') from error
                        stage.unlink('editable.tmp', _identity(_fd_info(fd)))
                        info = _fd_info(fd)
                        if _version(root.stat(name)) != _version(info):
                            raise RecentConflict('Save conflict: published companion changed; use Save As')
                        # Commit from our own encoded bytes and final fd, never
                        # from whatever a later UI callback sees by pathname.
                        revision = (name, _fingerprint(name, data, info))
                        state.companion = revision
                        if staged_old:
                            stage.unlink('previous', _identity(old_info))
                            staged_old = False
                        _check_edit_root(root)
                        return revision
                except BaseException as error:
                    if staged_old:
                        restored = _restore(stage, 'previous', root, name)
                        if restored != name:
                            raise RecentConflict(f'Save conflict; previous file kept at {root.folder / restored}; use Save As') from error
                        if old_fd is not None and _moved_matches(name, old_data, _fd_info(old_fd), expected[1]):
                            state.companion = (name, _fingerprint(name, old_data, _fd_info(old_fd)))
                        elif not isinstance(error, RecentConflict):
                            error = RecentConflict('Save conflict: companion changed; use Save As')
                    raise error
                finally:
                    # Only this private temp may be removed. Failed recovery
                    # work is retained, never swept by later operations.
                    try:
                        stage.unlink('editable.tmp')
                    except FileNotFoundError:
                        pass
                    except OSError as error:
                        warnings.warn(f'Unfinished editable retained at {stage.folder / "editable.tmp"}: {error}', RuntimeWarning)


@contextmanager
def _optional_pin(root, expected):
    if expected is None:
        yield None
    else:
        with root.pin(expected[0]) as pinned:
            data, info, _ = pinned
            if _fingerprint(expected[0], data, info) != expected[1]:
                raise RecentConflict('Save conflict: companion changed before publication; use Save As')
            yield pinned


def _write_editable(path, meta, base, holds):
    from .scene import write_project
    try:
        with _editing(path, holds) as root:
            if root is None:
                return write_project(path, meta, base)
            target = _EditableTarget(path, root, holds[0].state)
            revision = write_project(target, meta, base)
            finish_edits(path, holds, root)
            return revision
    except RecentConflict:
        for hold in holds:
            hold.state.conflicted = True
        try:
            finish_edits(path, holds, abandon=True)
        except OSError as error:
            warnings.warn(f'Could not release this editor protection in {Path(path).parent}: {error}', RuntimeWarning)
        raise


def writer() -> QThreadPool:
    """The one thread every autosave write runs on, in order (two writes of
    one file never overlap)."""
    global _WRITER
    if _WRITER is None:
        _WRITER = QThreadPool()
        _WRITER.setMaxThreadCount(1)
    return _WRITER


class _Filer(QObject):
    filed = Signal(str)
    failed = Signal(str)


class _FileJob(QRunnable):
    def __init__(self, store: RecentStore, image: QImage, signals: _Filer,
                 path: Path | None = None, keep: int | None = None):
        super().__init__()
        self.store, self.image, self.signals = store, image, signals
        self.path = path
        self.keep = store.keep if keep is None else keep

    def run(self) -> None:
        try:
            try:
                path = self.store.file(self.image, path=self.path, keep=self.keep)
            except Exception as e:      # noqa: BLE001 - never fail a capture
                self.signals.failed.emit(str(e))
                return
            self.signals.filed.emit(str(path))
        except RuntimeError:            # the pane closed meanwhile
            pass


def rendered(path: Path) -> QImage:
    """The capture WITH its edits: the editable loaded offscreen and drawn
    by the same road as Copy image and Save… as a picture
    (Document.render_image). A null image when it cannot be read."""
    from .scene import Document         # the scene imports the theme only
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            doc = Document.load(path)
    except Exception:                   # noqa: BLE001 - a broken file: no thumb
        return QImage()
    try:
        return doc.render_image()
    finally:
        doc.setParent(None)
        del doc


class _Saver(QObject):
    written = Signal(object, int, str)          # doc, change count, path
    failed = Signal(object, int, str, str)      # doc, change count, path, why


@dataclass
class WriteOutcome:
    error: str | None = None
    markers: tuple = ()


class _SaveJob(QRunnable):
    """One autosave write on the writer thread."""

    def __init__(self, doc, gen: int, path: str, meta: str, base: QImage,
                 signals: _Saver, outcome: WriteOutcome):
        super().__init__()
        self.doc, self.gen, self.path = doc, gen, path
        self.meta, self.base, self.signals = meta, base, signals
        self.outcome = outcome

    def run(self) -> None:
        from .scene import write_project
        try:
            try:
                _write_editable(self.path, self.meta, self.base, self.outcome.markers)
            except Exception as e:      # noqa: BLE001 - never raise on a thread
                self.outcome.error = _one_line(e)
                self.signals.failed.emit(self.doc, self.gen, self.path,
                                         self.outcome.error)
                return
            self.signals.written.emit(self.doc, self.gen, self.path)
        except RuntimeError:            # the window closed meanwhile
            pass


def _one_line(e: Exception) -> str:
    text = getattr(e, "strerror", None) or str(e) or type(e).__name__
    return " ".join(str(text).split())


def thumbnail(path: Path, size: QSize = THUMB, dpr: float = 1.0) -> QPixmap:
    """The capture scaled into a 16:9 box on a light ground (letterboxed):
    from its `.annotshot` (with the edits) when there is one, else the PNG;
    an empty pixmap when neither can be read."""
    box = QSize(round(size.width() * dpr), round(size.height() * dpr))
    try:
        _, editable = RecentStore(lambda: Path(path).parent).companions(path)
    except OSError:
        return QPixmap()
    img = rendered(editable) if editable.is_file() else QImage()
    if not img.isNull():
        img = img.scaled(box, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    elif Path(path).suffix.lower() == ".png":
        reader = QImageReader(str(path))
        full = reader.size()
        if not full.isValid() or full.isEmpty():
            return QPixmap()
        fit = full.scaled(box, Qt.KeepAspectRatio)
        reader.setScaledSize(fit.expandedTo(QSize(1, 1)))
        img = reader.read()
    if img.isNull():
        return QPixmap()
    pm = QPixmap(box)
    pm.fill(theme.color("thumb-ground"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    target = QRect(0, 0, img.width(), img.height())
    target.moveCenter(QRect(0, 0, box.width(), box.height()).center())
    p.drawImage(target, img)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


class _ThumbDelegate(QStyledItemDelegate):
    """The picture's frame and keyboard focus have independent perimeters.

    Gutters belong to every cell; neither cue paints on the thumbnail,
    including the letterbox pixels already present in its icon.
    """

    @staticmethod
    def image_rect(cell: QRect) -> QRect:
        return QRect(cell.left() + (cell.width() - THUMB.width()) // 2,
                     cell.top() + 4, THUMB.width(), THUMB.height())

    def paint(self, painter, option, index):
        painter.save()
        cell = option.rect
        painter.setClipRect(cell)
        painter.fillRect(cell, theme.color('surface'))
        image = self.image_rect(cell)
        icon = index.data(Qt.DecorationRole)
        if icon:
            icon.paint(painter, image)
        if index.data(CURRENT_ROLE):
            # Filled strips give exactly two logical pixels, outside the image.
            ink = theme.color('accent')
            painter.fillRect(QRect(image.left() - 2, image.top() - 2,
                                   image.width() + 4, 2), ink)
            painter.fillRect(QRect(image.left() - 2, image.bottom() + 1,
                                   image.width() + 4, 2), ink)
            painter.fillRect(QRect(image.left() - 2, image.top(), 2, image.height()), ink)
            painter.fillRect(QRect(image.right() + 1, image.top(), 2, image.height()), ink)
        caption = QRect(cell.left() + 3, image.bottom() + 4,
                        cell.width() - 6, cell.bottom() - image.bottom() - 5)
        painter.setFont(index.data(Qt.FontRole) or option.font)
        selected = bool(option.state & QStyle.State_Selected)
        if selected:
            painter.fillRect(caption, theme.color('accent-soft'))
        painter.setPen(theme.color('time-ink'))
        painter.drawText(caption, Qt.AlignHCenter | Qt.AlignVCenter, index.data(Qt.DisplayRole))
        if option.state & QStyle.State_HasFocus:
            painter.setPen(QPen(theme.color('text'), 1, Qt.DotLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(cell.adjusted(1, 1, -2, -2))
        painter.restore()


_FIND_POOL = None


def find_pool():
    global _FIND_POOL
    if _FIND_POOL is None:
        _FIND_POOL = QThreadPool()
        _FIND_POOL.setMaxThreadCount(2)
    return _FIND_POOL


class _Finder(QObject):
    finished = Signal(int, object, int, str)


class _FindJob(QRunnable):
    def __init__(self, store, query, epoch, cancel, signals):
        super().__init__()
        self.store, self.query, self.epoch = store, query, epoch
        self.cancel, self.signals = cancel, signals

    def run(self):
        paths, skipped, error = [], 0, ''
        try:
            paths, skipped = self.store.find_annotations(self.query, self.cancel)
        except Exception:  # no source text, titles or query in messages/logs
            error = 'Recent captures could not be searched.'
        try:
            self.signals.finished.emit(self.epoch, paths if not self.cancel.is_set() else [], skipped, error)
        except RuntimeError:
            pass                # pane destroyed: neither delivery nor UI access


class _FindField(QLineEdit):
    canvasRequested = Signal()

    def event(self, event):
        if event.type() == QEvent.ShortcutOverride and event.key() == Qt.Key_Escape:
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.clear()
            self.canvasRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _ThumbList(QListWidget):
    """The column of thumbnails: as wide as one thumbnail and its scroll
    bar, so the docked pane takes no more of the canvas than it needs."""

    canvasRequested = Signal()

    def event(self, event):
        if event.type() == QEvent.ShortcutOverride and event.key() == Qt.Key_Escape:
            event.accept()
            return True
        if (event.type() == QEvent.ShortcutOverride
                and not event.modifiers() & (Qt.ControlModifier
                                             | Qt.AltModifier | Qt.MetaModifier)
                and event.text() and event.text().isprintable()):
            event.accept()
            return True  # QListWidget receives the ordinary search KeyPress
        return super().event(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            event.accept()
            self.canvasRequested.emit()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        if self.flow() != QListWidget.LeftToRight:
            return super().wheelEvent(event)
        # Both a horizontal trackpad gesture and an ordinary wheel travel the row.
        pixels, angle = event.pixelDelta(), event.angleDelta()
        delta = pixels.x() or pixels.y()
        if not delta:
            delta = (angle.x() or angle.y()) / 120 * self.horizontalScrollBar().singleStep() * 3
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - round(delta))
        event.accept()

    def sizeHint(self) -> QSize:
        bar = self.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        if self.flow() == QListWidget.LeftToRight:
            return QSize(super().sizeHint().width(), self.row_height())
        return QSize(self.gridSize().width() + 2 * self.frameWidth() + bar + 4,
                     super().sizeHint().height())

    def row_height(self):
        return (self.gridSize().height() + 2 * self.frameWidth()
                + 2 * self.spacing() + self.style().pixelMetric(QStyle.PM_ScrollBarExtent))


class RecentPane(QDockWidget):
    """The dock pane. `openRequested(path)` asks the window to open a
    capture; the window decides (the discard question first)."""

    openRequested = Signal(str)
    saveRequested = Signal(str)
    filingFailed = Signal(str)
    filingFinished = Signal(str)
    redockRequested = Signal()
    # The captures deleted from the pane (their PNG paths), so the window
    # can let go of the one it is showing.
    deleted = Signal(list)

    def __init__(self, store: RecentStore, parent=None):
        super().__init__(TITLE, parent)
        self.setObjectName("recentPane")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea
                             | Qt.BottomDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetClosable
                         | QDockWidget.DockWidgetMovable
                         | QDockWidget.DockWidgetFloatable)
        self.store = store
        self.last_edge = Qt.RightDockWidgetArea
        self.direction = 'vertical'
        self._bound_stem = None
        self._layout_epoch = 0
        self._thumbs: dict[tuple[str, int], QPixmap] = {}
        self._last_click: tuple[str, int] | None = None
        self.opening_thumbnail = False
        body = QWidget(self)
        box = QVBoxLayout(body)
        box.setContentsMargins(6, 6, 6, 6)
        box.setSpacing(4)
        self.find = _FindField(body)
        self.find.setObjectName('recentFind')
        self.find.setPlaceholderText('Find annotations')
        self.find.setAccessibleName('Find annotations')
        self.find.setToolTip(FIND_SCOPE)
        self.find.setAccessibleDescription(FIND_SCOPE)
        self.find.setClearButtonEnabled(True)
        self.skipped = QLabel(body)
        self.skipped.setWordWrap(True)
        self.skipped.hide()
        self._find_epoch = 0
        self._find_query = ''
        self._find_state = None
        self._find_tasks = {}
        self._find_requested = None
        self._find_pool = find_pool()
        self._finder = _Finder(self)
        self._finder.finished.connect(self._find_finished)
        self._find_timer = QTimer(self)
        self._find_timer.setSingleShot(True)
        self._find_timer.timeout.connect(self._start_find)
        tasks = self._find_tasks
        self.destroyed.connect(lambda: [cancel.set() for cancel in tasks.values()])
        self.empty = QLabel(EMPTY_TEXT, body)
        self.empty.setObjectName("recentEmpty")
        self.empty.setWordWrap(True)
        self.empty.setStyleSheet(f"color: {theme.color('time-ink').name()};")
        self.list = _ThumbList(body)
        self.list.setObjectName("recentList")
        self.list.setItemDelegate(_ThumbDelegate(self.list))
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setFlow(QListWidget.TopToBottom)
        self.list.setWrapping(False)
        self.list.setMovement(QListWidget.Static)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setIconSize(THUMB)
        self.list.setGridSize(QSize(THUMB.width() + 12, THUMB.height() + 26))
        self.list.setSpacing(2)
        self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu_at)
        self.list.itemClicked.connect(self._clicked)
        self.list.itemDoubleClicked.connect(self._double_clicked)
        box.addWidget(self.find)
        box.addWidget(self.empty)
        box.addWidget(self.skipped)
        box.addWidget(self.list, 1)
        self.setWidget(body)
        self.setMinimumWidth(THUMB.width() + 36)
        self._filer = _Filer(self)
        self._filer.filed.connect(self._filed)
        self._filer.failed.connect(self._failed)
        self.visibilityChanged.connect(
            lambda shown: self.refresh() if shown else None)
        self.dockLocationChanged.connect(self._dock_location)
        self.topLevelChanged.connect(self._floating_changed)
        self.find.textChanged.connect(self.refresh)
        self.refresh()

    def _dock_location(self, area):
        if area in DOCK_EDGES:
            self.last_edge = area
            if not self.isFloating():
                self.set_direction('horizontal' if area == Qt.BottomDockWidgetArea else 'vertical')

    def _floating_changed(self, floating):
        self.setMaximumHeight(16777215)
        if floating:
            self._float_direction(self.size())
        else:
            self._dock_location(self.last_edge)

    def _float_direction(self, size):
        # ASSUMES: these are the CLIENT dimensions, before list/scrollbar layout.
        w, h = size.width(), size.height()
        if w * 5 >= h * 6:
            self.set_direction('horizontal')
        elif h * 5 >= w * 6:
            self.set_direction('vertical')

    def resizeEvent(self, event):
        if hasattr(self, 'list') and self.isFloating():
            self._float_direction(event.size())
        super().resizeEvent(event)

    def closeEvent(self, event):
        self.cancel_find()
        parent = self.parentWidget()
        if (self.isFloating() and getattr(parent, 'state_name', None) == 'editor'
                and not getattr(parent, '_quitting', False)):
            event.ignore()
            self.redockRequested.emit()
            return
        super().closeEvent(event)

    def _view_state(self):
        items = [self.list.item(i) for i in range(self.list.count())]
        stems = [Path(i.data(Qt.UserRole)).stem.casefold() for i in items]
        visible = [n for n, i in enumerate(items)
                   if self.list.visualItemRect(i).intersects(self.list.viewport().rect())]
        start = visible[0] if visible else 0
        current = self.list.currentItem()
        return (stems[start:] + stems[:start],
                Path(current.data(Qt.UserRole)).stem.casefold() if current else None,
                bool(current and current.isSelected()))

    def _restore_view(self, state):
        order, current, selected = state
        items = {Path(self.list.item(i).data(Qt.UserRole)).stem.casefold(): self.list.item(i)
                 for i in range(self.list.count())}
        if current in items:
            self.list.setCurrentItem(items[current])
            items[current].setSelected(selected)
        anchor = next((items[s] for s in order if s in items), None)
        self.list.doItemsLayout()
        if anchor is not None:
            self.list.scrollToItem(anchor, QAbstractItemView.PositionAtTop)

    def _settle_view(self, state):
        self._layout_epoch += 1
        epoch = self._layout_epoch
        self._restore_view(state)
        # QMainWindow assigns dock space after the flow changes. Restore once
        # more on that layout, without allowing an old resize to win a later one.
        QTimer.singleShot(0, self, lambda: self._restore_view(state)
                          if epoch == self._layout_epoch else None)

    def set_direction(self, direction):
        direction = direction if direction in ('horizontal', 'vertical') else 'vertical'
        state = self._view_state()
        changed = direction != self.direction
        self.direction = direction
        horizontal = direction == 'horizontal'
        self.list.setFlow(QListWidget.LeftToRight if horizontal else QListWidget.TopToBottom)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded if horizontal else Qt.ScrollBarAlwaysOff)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff if horizontal else Qt.ScrollBarAsNeeded)
        self.list.setMinimumHeight(self.list.row_height() if horizontal and not self.isFloating() else 0)
        self.setMaximumHeight(16777215)
        self.list.updateGeometry()
        self.widget().layout().invalidate()
        if horizontal and not self.isFloating():
            self.setMaximumHeight(self.sizeHint().height())
        self.updateGeometry()
        if changed:
            self._settle_view(state)

    def set_document_path(self, path):
        """The bound scene owns this identity; list selection never does.

        Folder membership uses the store's existing per-platform road. This
        stage adds no file operation to the store or its safety machinery.
        """
        stem = Path(path).stem.casefold() if path and self.store.owns(path) else None
        self._bound_stem = stem
        for i in range(self.list.count()):
            self._mark(self.list.item(i))

    def _mark(self, item):
        current = self._bound_stem is not None and (
            Path(item.data(Qt.UserRole)).stem.casefold()) == self._bound_stem
        item.setData(CURRENT_ROLE, current)
        item.setData(Qt.AccessibleTextRole, ('Current, ' if current else '') + item.text())

    def is_document_path(self, path):
        return bool(path and self._bound_stem is not None and self.store.owns(path)
                    and Path(path).stem.casefold() == self._bound_stem)

    def _filed(self, path):
        self.refresh()
        self.filingFinished.emit(path)

    # -- filing ---------------------------------------------------------------
    def file_capture(self, image: QImage, wait: bool = False,
                     path: Path | None = None, *, keep: int | None = None) -> None:
        """Keep `image` in the Recent folder (at `path`, from reserve()) on a
        worker thread (at once with wait=True, for tests); the pane
        refreshes when it lands."""
        if wait:
            try:
                self.store.file(image, path=path, keep=keep)
            except Exception as e:      # noqa: BLE001
                self._failed(str(e))
                return
            self._filed(str(path or ''))
            return
        QThreadPool.globalInstance().start(
            _FileJob(self.store, image.copy(), self._filer, path, keep))

    def _failed(self, why: str) -> None:
        self.filingFailed.emit(f"Could not keep the capture in Recent "
                               f"captures: {why}")

    # -- the list -------------------------------------------------------------
    def paths(self) -> list[str]:
        return [self.list.item(i).data(Qt.UserRole)
                for i in range(self.list.count())]

    def retheme(self) -> None:
        """The theme changed: the empty line's ink, and the thumbnails drawn
        again on the new ground."""
        self.empty.setStyleSheet(f"color: {theme.color('time-ink').name()};")
        self._thumbs = {}
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the list from the folder; a file gone from the folder is
        simply not shown."""
        was_searching = bool(self._find_query)
        state = self._view_state()
        if was_searching and self._find_state is not None:
            old_order, old_current, old_selected = self._find_state
            order, current, selected = state
            seen = set(order)
            state = (order + [s for s in old_order if s not in seen],
                     current or old_current, selected if current else old_selected)
        self.cancel_find()
        self._find_query = _find_text(self.find.text().strip())
        self.skipped.hide()
        if self._find_query:
            # Do not render/load a project here: matching is metadata-only.
            self._find_state = state
            self.list.clear()
            self.empty.setText('Finding annotations…')
            self.empty.show()
            self._find_requested = self._find_epoch
            self._find_timer.start(0)       # coalesce changes in this event turn
            return
        files = self.store.files()
        message = 'Captures could not be previewed.'
        if not files:
            try:
                if not self.store.library_snapshot().captures:
                    message = EMPTY_TEXT
            except OSError:
                message = 'Recent captures could not be read.'
        self.empty.setText(message)
        self._display_files(files, state=state)
        self._find_state = None

    def _display_files(self, files, *, searching=False, state=None):
        dpr = max(1.0, self.devicePixelRatioF())
        now = QDateTime.currentDateTime()
        state = self._view_state() if state is None else state
        self.list.clear()
        keep = dict(self._thumbs) if searching else {}
        cached = {key[0]: pm for key, pm in self._thumbs.items()} if searching else {}
        small = QFont(self.list.font())
        small.setPixelSize(round(11 * theme.ui_scale()))
        for path in files:
            if searching:
                # Search never reads a picture, including a matched project's
                # base. An uncached/unreadable thumbnail gets an empty icon.
                pm = cached.get(str(path), QPixmap())
            else:
                key = _thumb_key(path)
                if key is None:
                    continue
                pm = self._thumbs.get(key) or thumbnail(path, THUMB, dpr)
                if pm.isNull():
                    continue
                keep[key] = pm
            item = QListWidgetItem(pm, time_label(taken_at(path), now))
            item.setData(Qt.UserRole, str(path))
            item.setToolTip(path.name)
            item.setForeground(theme.color("time-ink"))
            item.setFont(small)
            item.setTextAlignment(Qt.AlignHCenter)
            self.list.addItem(item)
            self._mark(item)
        self._thumbs = keep
        self.empty.setVisible(self.list.count() == 0)
        self._settle_view(state)

    def cancel_find(self):
        self._find_epoch += 1
        self._find_timer.stop()
        self._find_requested = None
        for cancel in self._find_tasks.values():
            cancel.set()

    def find_pending(self):
        return (self._find_timer.isActive() or self._find_requested is not None
                or any(not c.is_set() for c in self._find_tasks.values()))

    def _start_find(self):
        epoch = self._find_requested
        if epoch is None or len(self._find_tasks) >= 2:
            return
        self._find_requested = None
        cancel = self._find_tasks[epoch] = threading.Event()
        self._find_pool.start(_FindJob(self.store, self._find_query, epoch, cancel, self._finder))

    def _find_finished(self, epoch, paths, skipped, error):
        self._find_tasks.pop(epoch, None)
        if epoch == self._find_epoch and self._find_query:
            self.empty.setText(error or NO_MATCH_TEXT)
            self._display_files(paths, searching=True, state=self._find_state)
            self.skipped.setText(f'{skipped} capture' + ('s' if skipped != 1 else '') + ' could not be searched.')
            self.skipped.setVisible(skipped > 0)
        self._start_find()              # only the latest pending request survives

    def refresh_one(self, path) -> None:
        """Draw one capture's thumbnail again (after an autosave of it),
        not the whole list; a capture not listed yet refreshes the list."""
        if self._find_query:
            stem = Path(path).stem.casefold()
            self._thumbs = {k: pm for k, pm in self._thumbs.items()
                            if Path(k[0]).stem.casefold() != stem}
            self.refresh()
            return
        mine = {os.path.normcase(str(png_for(path))),
                os.path.normcase(str(editable_for(path)))}
        dpr = max(1.0, self.devicePixelRatioF())
        for i in range(self.list.count()):
            item = self.list.item(i)
            shown = Path(item.data(Qt.UserRole))
            if os.path.normcase(str(shown)) not in mine:
                continue
            key = _thumb_key(shown)
            pm = thumbnail(shown, THUMB, dpr) if key else QPixmap()
            if pm.isNull():
                break
            for old in [k for k in self._thumbs if k[0] == str(shown)]:
                del self._thumbs[old]
            self._thumbs[key] = pm
            item.setIcon(QIcon(pm))
            return
        self.refresh()

    def _clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        self._last_click = (path, _now_ms())
        self._request_thumbnail(path)

    def _request_thumbnail(self, path: str) -> None:
        self.opening_thumbnail = True
        try:
            self.openRequested.emit(path)
        finally:
            self.opening_thumbnail = False

    def _double_clicked(self, item: QListWidgetItem) -> None:
        """A double-click opens too; the click just before it already asked,
        so the same capture is not asked for twice in one double-click."""
        path = item.data(Qt.UserRole)
        last = self._last_click
        self._last_click = None
        if last and last[0] == path and \
                _now_ms() - last[1] <= QApplication.doubleClickInterval():
            return
        self._request_thumbnail(path)

    # -- the right-click menu -----------------------------------------------------
    def menu_for(self, item: QListWidgetItem | None) -> QMenu:
        menu = QMenu(self)
        path = item.data(Qt.UserRole) if item is not None else None
        a_open = menu.addAction("Open")
        a_save = menu.addAction("Save…")
        a_show = menu.addAction("Show in folder")
        menu.addSeparator()
        a_delete = menu.addAction("Delete")
        menu.addSeparator()
        a_clear = menu.addAction("Clear recent captures")
        a_open.setEnabled(path is not None)
        a_save.setEnabled(path is not None)
        a_delete.setEnabled(path is not None)
        try:
            a_clear.setEnabled(bool(self.store.library_snapshot().captures))
        except OSError:
            a_clear.setEnabled(False)
        a_open.triggered.connect(lambda: self.openRequested.emit(path))
        a_save.triggered.connect(lambda: self.saveRequested.emit(path))
        a_delete.triggered.connect(lambda: self.delete(path))
        a_show.triggered.connect(self.show_folder)
        a_clear.triggered.connect(self.clear)
        return menu

    def _menu_at(self, pos) -> None:
        menu = self.menu_for(self.list.itemAt(pos))
        menu.exec(self.list.viewport().mapToGlobal(pos))
        menu.deleteLater()

    def delete(self, path: str | None) -> None:
        """Remove the capture (its PNG and its editable) and its thumbnail;
        no question."""
        if path:
            try:
                self.store.delete(Path(path))
            except OSError as e:
                self._failed(str(e))
            else:
                self.deleted.emit([str(png_for(path))])
        self.refresh()

    def show_folder(self) -> bool:
        folder = self.store.folder
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def clear(self) -> bool:
        """Every kept capture goes, after one question."""
        try:
            snapshot = self.store.library_snapshot()
        except OSError as error:
            self._failed(str(error))
            return False
        if not snapshot.captures:
            return False
        answer = QMessageBox.question(
            self, "Annotshot", CLEAR_QUESTION.format(count=len(snapshot.captures)),
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer != QMessageBox.Yes:
            return False
        success = True
        try:
            gone = self.store.clear(snapshot)
        except OSError as error:
            gone = getattr(error, 'removed', [])
            self._failed(str(error))
            success = False
        self.deleted.emit([str(png_for(p)) for p in gone])
        self.refresh()
        return success


def _mtime(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _thumb_key(path: Path) -> tuple | None:
    """A thumbnail is drawn again only when one of the capture's two files
    changed (the editable's mtime moves with every autosave)."""
    try:
        source, companion = RecentStore(lambda: Path(path).parent).companions(path)
    except OSError:
        return None
    png, editable = _mtime(source), _mtime(companion)
    if not png and not editable:
        return None
    return (str(path), png, editable)


def _now_ms() -> int:
    return QDateTime.currentMSecsSinceEpoch()
