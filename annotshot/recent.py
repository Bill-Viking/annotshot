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
import re
import warnings
from pathlib import Path
from typing import Callable

from PySide6.QtCore import (QDateTime, QObject, QRect, QRunnable, QSize, Qt,
                            QThreadPool, QUrl, Signal)
from PySide6.QtGui import (QDesktopServices, QFont, QIcon, QImage,
                           QImageReader, QPainter, QPixmap)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDockWidget,
                               QLabel, QListWidget, QListWidgetItem, QMenu,
                               QMessageBox, QStyle, QVBoxLayout,
                               QWidget)

from . import theme

KEEP = 12
TITLE = "Recent captures"
SETTING = "recent/keep"                 # QSettings key: file each capture
KEEP_TEXT = f"Keep the last {KEEP} captures in the Recent pane"
THUMB = QSize(160, 90)                  # 16:9, letterboxed
THUMB_GROUND = "#E9EDF1"                # Light's; the theme's "thumb-ground"
TIME_INK = "#7A8591"                    # Light's; the theme's "time-ink"
EMPTY_TEXT = "Your captures appear here."
CLEAR_QUESTION = ("Remove every capture from Recent captures? The pictures "
                  "in the Recent folder are deleted; files you saved "
                  "yourself are not touched.")
# The file names: an ISO date and time with '-' for ':' (Windows refuses a
# colon in a file name) and milliseconds, so names sort by time.
# ASSUMES: the files in the folder are named by stamp_name(); a file with any
# other .png name still shows, timed by its modification time.
NAME_FORMAT = "yyyy-MM-ddTHH-mm-ss-zzz"
NAME_RE = re.compile(
    r"^(\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d-\d{3})(?:-\d+)?\.(?:png|annotshot)$")
EDITABLE = ".annotshot"
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
          "Oct", "Nov", "Dec")


def stamp_name(when: QDateTime) -> str:
    return when.toString(NAME_FORMAT) + ".png"


def editable_for(path) -> Path:
    """The editable record beside a capture's PNG (existing or to be
    written)."""
    return Path(path).with_suffix(EDITABLE)


def png_for(path) -> Path:
    return Path(path).with_suffix(".png")


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
            found = [p for p in self.folder.iterdir()
                     if p.suffix.lower() in (".png", EDITABLE) and p.is_file()]
        except OSError:
            return []
        by_stem: dict[str, Path] = {}
        for p in found:
            if p.suffix.lower() == ".png" or p.stem not in by_stem:
                by_stem[p.stem] = p
        return sorted(by_stem.values(),
                      key=lambda p: (taken_at(p).toMSecsSinceEpoch(), p.stem),
                      reverse=True)

    def owns(self, path) -> bool:
        """True when `path` is a capture's file in the Recent folder."""
        try:
            return Path(path).parent.resolve() == self.folder.resolve()
        except OSError:
            return False

    def reserve(self, when: QDateTime | None = None) -> Path:
        """A new capture's PNG path, unused (two in one millisecond get
        -1, -2 …); nothing is written yet, so the window knows the path
        before the filer lands the picture."""
        folder = self.folder
        name = stamp_name(when or QDateTime.currentDateTime())
        path, n = folder / name, 1
        while path.exists() or editable_for(path).exists() or \
                str(path) in _RESERVED:
            path = folder / f"{name[:-4]}-{n}.png"
            n += 1
        _RESERVED.add(str(path))
        return path

    def file(self, image: QImage, when: QDateTime | None = None,
             path: Path | None = None) -> Path:
        """Write `image` as a full PNG (at `path`, else a new stamp) and drop
        the oldest unedited captures beyond `keep`. Raises OSError naming
        what went wrong."""
        folder = self.folder
        path = Path(path) if path is not None else self.reserve(when)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if not image.save(str(path), "PNG"):
                path.unlink(missing_ok=True)
                raise OSError(f"could not write {path.name} in {folder}")
        finally:
            _RESERVED.discard(str(path))
        self.prune()
        return path

    def prune(self) -> list[Path]:
        """Drop the unedited captures beyond the last `keep`; a capture with
        an `.annotshot` beside it is work, and is never thrown away."""
        gone = []
        for old in self.files()[self.keep:]:
            if editable_for(old).exists():
                continue
            try:
                old.unlink()
                gone.append(old)
            except OSError:
                pass
        return gone

    def delete(self, path: Path) -> None:
        """Both files of a capture: the PNG and its editable."""
        writer().waitForDone()          # an autosave still on its way
        png_for(path).unlink(missing_ok=True)
        editable_for(path).unlink(missing_ok=True)

    def clear(self) -> None:
        for p in self.files():
            self.delete(p)


# Paths handed out by reserve() whose PNG is not on disk yet.
_RESERVED: set[str] = set()
_WRITER: QThreadPool | None = None


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
                 path: Path | None = None):
        super().__init__()
        self.store, self.image, self.signals = store, image, signals
        self.path = path

    def run(self) -> None:
        try:
            try:
                path = self.store.file(self.image, path=self.path)
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


class _SaveJob(QRunnable):
    """One autosave write on the writer thread."""

    def __init__(self, doc, gen: int, path: str, meta: str, base: QImage,
                 signals: _Saver):
        super().__init__()
        self.doc, self.gen, self.path = doc, gen, path
        self.meta, self.base, self.signals = meta, base, signals

    def run(self) -> None:
        from .scene import write_project
        try:
            try:
                write_project(self.path, self.meta, self.base)
            except Exception as e:      # noqa: BLE001 - never raise on a thread
                self.signals.failed.emit(self.doc, self.gen, self.path,
                                         _one_line(e))
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
    editable = editable_for(path)
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


class _ThumbList(QListWidget):
    """The column of thumbnails: as wide as one thumbnail and its scroll
    bar, so the docked pane takes no more of the canvas than it needs."""

    def sizeHint(self) -> QSize:
        bar = self.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        return QSize(self.gridSize().width() + 2 * self.frameWidth() + bar + 4,
                     super().sizeHint().height())


class RecentPane(QDockWidget):
    """The dock pane. `openRequested(path)` asks the window to open a
    capture; the window decides (the discard question first)."""

    openRequested = Signal(str)
    filingFailed = Signal(str)
    # The captures deleted from the pane (their PNG paths), so the window
    # can let go of the one it is showing.
    deleted = Signal(list)

    def __init__(self, store: RecentStore, parent=None):
        super().__init__(TITLE, parent)
        self.setObjectName("recentPane")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetClosable
                         | QDockWidget.DockWidgetMovable
                         | QDockWidget.DockWidgetFloatable)
        self.store = store
        self._thumbs: dict[tuple[str, int], QPixmap] = {}
        self._last_click: tuple[str, int] | None = None
        body = QWidget(self)
        box = QVBoxLayout(body)
        box.setContentsMargins(6, 6, 6, 6)
        box.setSpacing(4)
        self.empty = QLabel(EMPTY_TEXT, body)
        self.empty.setObjectName("recentEmpty")
        self.empty.setWordWrap(True)
        self.empty.setStyleSheet(f"color: {theme.color('time-ink').name()};")
        self.list = _ThumbList(body)
        self.list.setObjectName("recentList")
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
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu_at)
        self.list.itemClicked.connect(self._clicked)
        self.list.itemDoubleClicked.connect(self._double_clicked)
        box.addWidget(self.empty)
        box.addWidget(self.list, 1)
        self.setWidget(body)
        self.setMinimumWidth(THUMB.width() + 36)
        self._filer = _Filer(self)
        self._filer.filed.connect(lambda _p: self.refresh())
        self._filer.failed.connect(self._failed)
        self.visibilityChanged.connect(
            lambda shown: self.refresh() if shown else None)
        self.refresh()

    # -- filing ---------------------------------------------------------------
    def file_capture(self, image: QImage, wait: bool = False,
                     path: Path | None = None) -> None:
        """Keep `image` in the Recent folder (at `path`, from reserve()) on a
        worker thread (at once with wait=True, for tests); the pane
        refreshes when it lands."""
        if wait:
            try:
                self.store.file(image, path=path)
            except Exception as e:      # noqa: BLE001
                self._failed(str(e))
                return
            self.refresh()
            return
        QThreadPool.globalInstance().start(
            _FileJob(self.store, image.copy(), self._filer, path))

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
        files = self.store.files()
        dpr = max(1.0, self.devicePixelRatioF())
        now = QDateTime.currentDateTime()
        self.list.clear()
        keep = {}
        small = QFont(self.list.font())
        small.setPixelSize(round(11 * theme.ui_scale()))
        for path in files:
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
        self._thumbs = keep
        self.empty.setVisible(self.list.count() == 0)

    def refresh_one(self, path) -> None:
        """Draw one capture's thumbnail again (after an autosave of it),
        not the whole list; a capture not listed yet refreshes the list."""
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
        self.openRequested.emit(path)

    def _double_clicked(self, item: QListWidgetItem) -> None:
        """A double-click opens too; the click just before it already asked,
        so the same capture is not asked for twice in one double-click."""
        path = item.data(Qt.UserRole)
        last = self._last_click
        self._last_click = None
        if last and last[0] == path and \
                _now_ms() - last[1] <= QApplication.doubleClickInterval():
            return
        self.openRequested.emit(path)

    # -- the right-click menu -----------------------------------------------------
    def menu_for(self, item: QListWidgetItem | None) -> QMenu:
        menu = QMenu(self)
        path = item.data(Qt.UserRole) if item is not None else None
        a_open = menu.addAction("Open")
        a_delete = menu.addAction("Delete")
        a_show = menu.addAction("Show in folder")
        menu.addSeparator()
        a_clear = menu.addAction("Clear recent captures")
        a_open.setEnabled(path is not None)
        a_delete.setEnabled(path is not None)
        a_clear.setEnabled(self.list.count() > 0)
        a_open.triggered.connect(lambda: self.openRequested.emit(path))
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
        answer = QMessageBox.question(
            self, "Annotshot", CLEAR_QUESTION,
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer != QMessageBox.Yes:
            return False
        gone = [str(png_for(p)) for p in self.store.files()]
        self.store.clear()
        self.deleted.emit(gone)
        self.refresh()
        return True


def _mtime(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _thumb_key(path: Path) -> tuple | None:
    """A thumbnail is drawn again only when one of the capture's two files
    changed (the editable's mtime moves with every autosave)."""
    png, editable = _mtime(png_for(path)), _mtime(editable_for(path))
    if not png and not editable:
        return None
    return (str(path), png, editable)


def _now_ms() -> int:
    return QDateTime.currentMSecsSinceEpoch()
