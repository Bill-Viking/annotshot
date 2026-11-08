"""MainWindow: the two toolbar rows, the property strip, file and clipboard
actions, and the capture flow."""
from __future__ import annotations

import errno
import json
import ntpath
import os
import re
import shlex
import sys
import warnings
import zipfile
import zlib
from functools import lru_cache
from pathlib import Path

import shiboken6

from PySide6.QtCore import (QByteArray, QDateTime, QEvent, QRect, QSettings,
                            QSize, Qt, QTimer, Signal)
from PySide6.QtGui import (QAction, QActionGroup, QColor, QFont,
                           QFontDatabase, QFontInfo, QFontMetrics,
                           QGuiApplication, QIcon, QImage, QKeySequence,
                           QPainter, QPixmap, QUndoGroup)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractSlider, QApplication, QButtonGroup,
                               QCheckBox, QColorDialog, QComboBox, QFileDialog,
                               QFrame, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QScrollArea,
                               QSizePolicy, QSlider, QSpinBox,
                               QStyledItemDelegate, QToolBar,
                               QToolButton, QVBoxLayout, QWidget)

from . import hotkey, macos
from .capture import CaptureSession
from .items import HighlightItem, TextBoxItem, without_alpha
from .office import OFFICE_FORMATS, export
from . import recent, theme, typefaces
from .scene import Document
from .tools import Tool
from .view import EditorView

PROJECT_FILTER = "Annotshot editable (*.annotshot)"
PROJECT_FORMAT = "ANNOTSHOT"
# Open… also lists the type used before the rename (same zip format).
OPEN_FILTER = "Annotshot editable (*.annotshot *.snagup)"
# Save…'s file types: (filter, extensions, format). The first extension is
# the one a name gets. A picture type saves the rendered picture with every
# edit (JPEG and BMP have no alpha); the last type saves the editable file.
SAVE_TYPES = (
    ("PNG image (*.png)", ("png",), "PNG"),
    ("JPEG image (*.jpg *.jpeg)", ("jpg", "jpeg"), "JPEG"),
    ("BMP image (*.bmp)", ("bmp",), "BMP"),
    ("WebP image (*.webp)", ("webp",), "WEBP"),
    ("Word document (*.docx)", ("docx",), "DOCX"),
    ("PowerPoint slide (*.pptx)", ("pptx",), "PPTX"),
    (PROJECT_FILTER, ("annotshot",), PROJECT_FORMAT),
)
SAVE_FILTERS = ";;".join(t[0] for t in SAVE_TYPES)
NO_ALPHA_FORMATS = ("JPEG", "BMP")
JPEG_QUALITY = 92
DEFAULT_DIR = Path.home() / "Pictures" / "Annotshot"
RECENT_SUBDIR = "Recent"            # the kept captures: DEFAULT_DIR/Recent
CAPTURE_DELAY_MS = 250
AUTOSAVE_MS = 700                   # the autosave's debounce after an edit
CURRENT_KEY = "recent/current"      # the capture on screen, back at launch
AUTOSAVE_FAILED = "Could not keep your changes to this picture: {why}"
# The way back when macOS refuses an app it already lists as switched on (an
# update that is not signed by Apple keeps the old entry, which no longer
# matches): the user manual's Updating -> macOS bullet says the same words.
PERMISSION_WAY_BACK = (
    "If Annotshot is already switched on and macOS still refuses: in that "
    "same list remove Annotshot with − and add it again with + from "
    "Applications, switch it on, then quit and reopen Annotshot.")
PERMISSION_TEXT = (
    "Annotshot needs permission to record the screen. Open System Settings "
    "→ Privacy & Security → Screen & System Audio Recording, switch "
    "Annotshot on, then quit Annotshot and start it again.\n\n"
    + PERMISSION_WAY_BACK)
PERMISSION_STATUS = "Capture needs screen-recording permission"
# The window: it opens centered at a moderate size (never maximized), at
# most SCREEN_SHARE of the screen's free area, never smaller than MIN_SIZE
# (logical px). After a capture it grows to the picture at 100 %.
START_SIZE = QSize(1100, 720)
MIN_SIZE = QSize(900, 600)
SCREEN_SHARE = 0.8
# Buttons that show only their icon (the tooltip names them).
ICON_ONLY = ("Undo", "Redo", "Settings…", "Duplicate", "Front", "Back",
             "Delete")
# The shortcuts the user may set: (settings key, the name the page shows).
# The tools' keys are their names in lower case. Saved as shortcuts/<key>.
SHORTCUT_ROWS = (
    ("capture", "Capture"), ("open", "Open…"), ("save", "Save…"),
    ("copy", "Copy image"), ("clear", "Clear"), ("undo", "Undo"),
    ("redo", "Redo"), *((t.name.lower(), t.value) for t in Tool),
    ("duplicate", "Duplicate"), ("front", "Front"), ("back", "Back"),
    ("delete", "Delete"), ("settings", "Settings…"), ("help", "Help"))
HOTKEY_NAME = "Capture from anywhere"


# -- icons ----------------------------------------------------------------
# The toolbar icons are monochrome line drawings in annotshot/icons/*.svg, drawn
# with the stroke ICON_INK; each state gets its own ink, rendered at several
# scales so they stay sharp at 125 / 150 / 200 %.
ICON_DIR = Path(__file__).resolve().parent / "icons"
# The strip's text controls that, with nothing selected, show and set the
# style the next text box starts in.
NEW_TEXT_KEYS = ("font_family", "font_px", "bold", "italic")
ICON_PX = 20                      # logical px
ICON_INK = "#334454"              # the stroke the SVG files are drawn with
INK_CHECKED = "#086DBE"
INK_DISABLED = "#A7B1BB"
ICON_SCALES = (1, 1.25, 1.5, 1.75, 2, 3)
# Toolbar action text -> icon file (without .svg).
TOOLBAR_ICONS = {
    "Capture": "capture", "Open…": "open", "Save…": "save",
    "Copy image": "copy-image", "Clear": "clear-picture", "Undo": "undo",
    "Redo": "redo", "Settings…": "settings",
    "Select": "select", "Text": "text", "Callout": "callout", "Rect": "rect",
    "Ellipse": "ellipse",
    "Arrow": "arrow", "Highlight": "highlight", "Pen": "pen", "Crop": "crop",
    "Duplicate": "duplicate", "Front": "front", "Back": "back",
    "Delete": "delete"}
ALIGN_ICONS = {"left": "align-left", "center": "align-center",
               "right": "align-right"}
KIND_ICONS = {"text": "text", "callout": "callout", "rect": "rect",
              "ellipse": "ellipse",
              "arrow": "arrow", "highlight": "highlight", "pen": "pen"}
# The arrow's pull-downs: (prop value, the name shown).
ARROW_HEADS = (("filled", "Filled"), ("open", "Open"), ("none", "None"))
HEAD_SIZE_NAMES = (("small", "Small"), ("medium", "Medium"),
                   ("large", "Large"))
LINE_STYLE_NAMES = (("solid", "Solid"), ("dashed", "Dashed"),
                    ("dotted", "Dotted"))
# Friendly names for the colors the controls show; others show as #RRGGBB.
COLOR_NAMES = {
    "#000000": "Black", "#FFFFFF": "White", "#E53935": "Red",
    "#FF0000": "Red", "#FFFF00": "Yellow", "#00FF00": "Green",
    "#008000": "Green", "#0000FF": "Blue", "#1E88E5": "Blue",
    "#808080": "Grey", "#FFA500": "Orange", "#800080": "Purple"}


@lru_cache(maxsize=None)
def _svg_source(name: str) -> str:
    return (ICON_DIR / f"{name}.svg").read_text(encoding="utf-8")


def svg_pixmap(name: str, px: int, ink: str = ICON_INK) -> QPixmap:
    """The icon `name` drawn `px` pixels square in the color `ink`."""
    svg = _svg_source(name).replace(ICON_INK, ink)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p)
    p.end()
    return pm


def svg_icon(name: str, size: int = ICON_PX, ink: str = ICON_INK,
             checked: str = INK_CHECKED, disabled: str = INK_DISABLED) -> QIcon:
    """A QIcon with its normal, checked and disabled inks at each scale."""
    icon = QIcon()
    for scale in ICON_SCALES:
        px = round(size * scale)
        for mode, state, color in ((QIcon.Normal, QIcon.Off, ink),
                                   (QIcon.Normal, QIcon.On, checked),
                                   (QIcon.Disabled, QIcon.Off, disabled),
                                   (QIcon.Disabled, QIcon.On, disabled)):
            icon.addPixmap(svg_pixmap(name, px, color), mode, state)
    return icon


def themed_svg(name: str, ink: str) -> str:
    """The icon file's text with its one stroke ICON_INK replaced by `ink`."""
    return _svg_source(name).replace(ICON_INK, ink)


def themed_icon(name: str, theme_name: str | None = None, size: int = ICON_PX,
                ink: str = "icon", checked: str = "icon-checked",
                disabled: str = "icon-disabled") -> QIcon:
    """The icon `name` in the theme's inks (the current theme when None):
    `ink`, `checked` and `disabled` name the theme's tokens for the normal,
    checked and disabled states. An unknown name is an empty icon."""
    if not (ICON_DIR / f"{name}.svg").is_file():
        return QIcon()
    t = theme.tokens(theme_name)
    return svg_icon(name, size, ink=t[ink], checked=t[checked],
                    disabled=t[disabled])


def color_name(color) -> str:
    """'Black', 'Yellow 45%', 'None' (alpha 0) or '#RRGGBB'."""
    c = QColor(color)
    if c.alpha() == 0:
        return "None"
    rgb = c.name(QColor.HexRgb).upper()
    name = COLOR_NAMES.get(rgb, rgb)
    return name if c.alpha() == 255 else f"{name} {round(c.alpha() * 100 / 255)}%"


def swatch_icon(color, size: int = 17) -> QIcon:
    """A small color square over a checkerboard (so alpha shows), at each
    scale so it stays sharp on a scaled display."""
    icon = QIcon()
    for scale in ICON_SCALES:
        px = round(size * scale)
        cell = max(2, round(px / 3))
        pm = QPixmap(px, px)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        for y in range(0, px, cell):
            for x in range(0, px, cell):
                light = (x // cell + y // cell) % 2 == 0
                p.fillRect(x, y, cell, cell,
                           QColor("#FFFFFF" if light else "#C8C8C8"))
        p.fillRect(0, 0, px, px, QColor(color))
        p.setPen(QColor("#9DA9B5"))
        p.drawRect(0, 0, px - 1, px - 1)
        p.end()
        icon.addPixmap(pm)
    return icon


def flatten_on_white(img: QImage) -> QImage:
    """The picture over a white background, opaque (for JPEG and BMP)."""
    flat = QImage(img.size(), QImage.Format_RGB32)
    flat.fill(QColor("#FFFFFF"))
    p = QPainter(flat)
    p.drawImage(0, 0, img)
    p.end()
    return flat


def typed_path_for(path: str, exts: tuple) -> str:
    """`path` with an extension of the chosen type: kept when it already has
    one, swapped when it names another save type, added when missing."""
    p = Path(path)
    suffix = p.suffix[1:].lower()
    if suffix in exts:
        return path
    if any(suffix in t[1] for t in SAVE_TYPES):
        return str(p.with_suffix("." + exts[0]))
    return f"{path}.{exts[0]}"


def open_warning(path: str, error: Exception) -> str:
    """The plain sentence for a file that could not be opened."""
    name = Path(path).name
    if isinstance(error, FileNotFoundError):
        return f"The file is no longer there:\n{name}"
    if isinstance(error, IsADirectoryError) or os.path.isdir(path):
        # Windows says "permission denied" for a folder
        return f"This is a folder, not a file:\n{name}"
    if isinstance(error, (zipfile.BadZipFile, zlib.error, KeyError,
                          json.JSONDecodeError, UnicodeDecodeError)):
        return f"This is not an Annotshot file, or it is damaged:\n{name}"
    return f"Could not open {name}:\n{error}"


def save_problem(path: str, error: OSError) -> str:
    """The plain sentence for a Word or PowerPoint file that could not be
    written; it names the file the user chose, never a temp file."""
    if isinstance(error, FileNotFoundError):
        reason = "the folder is missing"
    elif isinstance(error, PermissionError):
        reason = "no permission"
    elif error.errno in (errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)):
        reason = "the disk is full"
    else:
        reason = error.strerror or str(error)
    return f"Could not save {Path(path).name}: {reason}"


# What a path may hold and still be typed into PowerShell bare.
_PLAIN_WINDOWS_PATH = re.compile(r"[A-Za-z0-9_.:\\/-]+")
OFFICE_PINS = "python-docx==1.2.0 python-pptx==1.0.2"


def pip_command(executable: str | None = None, platform: str | None = None,
                isfile=os.path.isfile) -> str:
    """The one line that adds the Word / PowerPoint parts to the running
    Python. On Windows pythonw.exe has no console, so python.exe beside it
    is named; a path that needs quotes gets PowerShell's call operator."""
    python = sys.executable if executable is None else executable
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        if python.lower().endswith("pythonw.exe"):
            console = ntpath.join(ntpath.dirname(python), "python.exe")
            if isfile(console):
                python = console
        if not _PLAIN_WINDOWS_PATH.fullmatch(python):
            # inside double quotes PowerShell still reads ` and $
            python = '& "{}"'.format(
                python.replace("`", "``").replace("$", "`$"))
    else:
        python = shlex.quote(python)
    return f"{python} -m pip install {OFFICE_PINS}"


class SaveAction(QAction):
    """The Save… action. It remembers which shortcut triggered it, so a
    plain Ctrl+S can save an editable file again without asking, while the
    button and Ctrl+Shift+S open the dialog."""

    def __init__(self, *args):
        super().__init__(*args)
        self._key: QKeySequence | None = None

    def event(self, e):
        if e.type() == QEvent.Shortcut:
            self._key = QKeySequence(e.key())
        return super().event(e)

    def take_key(self) -> QKeySequence | None:
        """The shortcut behind the current trigger (None for a click)."""
        key, self._key = self._key, None
        return key


def _clear_alpha(item, key):
    return without_alpha(item.props[key])


class ColorButton(QToolButton):
    """A swatch with the color's name that opens QColorDialog (alpha shown).
    `label` is what the field label beside it says (its accessible name)."""

    def __init__(self, label: str, title: str, on_pick, parent=None):
        super().__init__(parent)
        self.setObjectName("colorField")
        self.setAccessibleName(label)
        self.setToolTip(title)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(17, 17))
        self._title, self._on_pick = title, on_pick
        self._color = QColor("#000000")
        self.set_color(self._color)
        self.clicked.connect(self._choose)

    def set_color(self, color) -> None:
        self._color = QColor(color)
        self.setIcon(swatch_icon(self._color))
        self.setText(color_name(self._color))

    def _choose(self) -> None:
        start = QColor(self._color)
        if start.alpha() == 0:      # after "No fill": start opaque, same hue
            start.setAlpha(255)
        c = QColorDialog.getColor(start, self.window(), self._title,
                                  QColorDialog.ShowAlphaChannel)
        if c.isValid():
            self.set_color(c)
            self._on_pick(c)


class _FaceDelegate(QStyledItemDelegate):
    """Draws each family's name in its own face, at paint time only (so a
    system with hundreds of fonts loads only the rows shown); a separator
    row is a thin line."""

    def _separator(self, index) -> bool:
        return index.data(Qt.AccessibleDescriptionRole) == "separator"

    def initStyleOption(self, option, index) -> None:  # noqa: N802
        super().initStyleOption(option, index)
        family = index.data(Qt.DisplayRole)
        if family and not self._separator(index):
            face = QFont(family)
            face.setPixelSize(max(13, option.font.pixelSize()))
            option.font = face

    def paint(self, painter, option, index) -> None:
        if self._separator(index):
            painter.save()
            painter.setPen(theme.color("font-separator"))
            y = option.rect.center().y()
            painter.drawLine(option.rect.left() + 4, y, option.rect.right() - 4, y)
            painter.restore()
            return
        super().paint(painter, option, index)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        if self._separator(index):
            return QSize(option.rect.width(), 7)
        return QSize(super().sizeHint(option, index).width(), 22)


class FontBox(QComboBox):
    """The Font box: the fonts Annotshot carries first (the VT323 pixel
    font, "Pixel font (bundled)"), a separator, then this system's families;
    each name is shown in its own face. Speaks QFontComboBox's words
    (currentFontChanged, setCurrentFont, currentFont)."""

    currentFontChanged = Signal(QFont)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setItemDelegate(_FaceDelegate(self))
        # one row's height for all: no font is loaded to measure the list
        self.view().setUniformItemSizes(True)
        self.bundled: list[str] = []
        self.populate()
        self.currentIndexChanged.connect(self._index_changed)

    def populate(self) -> None:
        self.blockSignals(True)
        try:
            self.clear()
            self.bundled = typefaces.load_bundled()
            for family in self.bundled:
                self.addItem(family)
                i = self.count() - 1
                self.setItemData(i, typefaces.tooltip(family), Qt.ToolTipRole)
            if self.bundled:
                self.insertSeparator(self.count())
            for family in QFontDatabase.families():
                if family in self.bundled or QFontDatabase.isPrivateFamily(family):
                    continue
                self.addItem(family)
        finally:
            self.blockSignals(False)

    def is_separator(self, i: int) -> bool:
        return self.itemData(i, Qt.AccessibleDescriptionRole) == "separator"

    def _index_changed(self, i: int) -> None:
        if i >= 0 and not self.is_separator(i):
            self.currentFontChanged.emit(QFont(self.itemText(i)))

    def setCurrentFont(self, font: QFont) -> None:  # noqa: N802 - Qt's name
        """Select the family, or the one Qt would draw it with; a family this
        system lacks is shown by its name."""
        i = self.findText(font.family(), Qt.MatchFixedString)
        if i < 0:
            i = self.findText(QFontInfo(font).family(), Qt.MatchFixedString)
        if i >= 0:
            self.setCurrentIndex(i)
        else:                   # no row: so picking any row is a change
            self.setCurrentIndex(-1)
            self.setEditText(font.family())

    def currentFont(self) -> QFont:  # noqa: N802 - Qt's name
        return QFont(self.currentText())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("Annotshot", "Annotshot")
        self.undo_group = QUndoGroup(self)
        self.doc = Document()
        self._bound: Document | None = None
        self._capture: CaptureSession | None = None
        # One open at a time: Open…, open_path and macOS's FileOpen events
        # share this flag; a file that arrives meanwhile is kept (the newest
        # wins) and opens when the running open returns.
        self._opening = False
        self._kept: str | None = None
        self._slider_session = 0
        self._refreshing = False
        self._marks: dict = {}          # the heading's kind marks
        self.view = EditorView(self.doc, self)
        self.setCentralWidget(self.view)
        self._build_actions()
        self._apply_saved_shortcuts()
        self.hotkey = hotkey.GlobalHotkey(self)
        self.hotkey.activated.connect(self.capture_from_anywhere)
        self._build_toolbar()
        self._build_props_bar()
        self.zoom_label, self.size_label = QLabel(), QLabel()
        bar = self.statusBar()
        bar.addPermanentWidget(self.size_label)
        bar.addPermanentWidget(self.zoom_label)
        self.view.zoomChanged.connect(
            lambda z: self.zoom_label.setText(f"{round(z * 100)} %"))
        self.view.toolDone.connect(
            lambda: self.tool_actions[Tool.SELECT].setChecked(True))
        self.view.menu_actions = self.menu_actions
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(AUTOSAVE_MS)
        self._autosave_timer.timeout.connect(
            lambda: self.autosave_now(from_timer=True))
        self._saver = recent._Saver(self)
        self._saver.written.connect(self._autosaved)
        self._saver.failed.connect(self._autosave_failed)
        self._remembering = False       # recent/current, from launch on
        self._build_recent()
        self._bind(self.doc)
        area = self._screen_area()
        self.setMinimumSize(MIN_SIZE.boundedTo(self._cap(area)))
        saved = self.settings.value("window/size", START_SIZE, type=QSize)
        self._place(saved if saved.isValid() else START_SIZE, area)
        self.view.setFocus()
        bar.showMessage("Ctrl+N to capture a region or a window", 8000)
        self.restore_last()
        self._remembering = True

    # -- building ---------------------------------------------------------
    def _build_recent(self) -> None:
        """The Recent captures pane: docked on the right the first time,
        then where the user left it (docked left or right, floating, or
        closed), restored from the saved window state."""
        self.recent_store = recent.RecentStore(
            lambda: Path(DEFAULT_DIR) / RECENT_SUBDIR)
        self.recent = recent.RecentPane(self.recent_store, self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.recent)
        self.recent.openRequested.connect(self.open_recent)
        self.recent.filingFailed.connect(self._filing_failed)
        self.recent.deleted.connect(self._recent_deleted)
        self.a_recent = self.recent.toggleViewAction()
        self.a_recent.setText(recent.TITLE)
        self.a_recent.setToolTip("Show or hide the Recent captures pane")
        state = self.settings.value("window/state", QByteArray(),
                                    type=QByteArray)
        if state is not None and not state.isEmpty():
            self.restoreState(state)

    def keep_recent(self) -> bool:
        return self.settings.value(recent.SETTING, True, type=bool)

    def open_recent(self, path: str, quiet: bool = False) -> bool:
        """Open a kept capture as the current picture, with its edits: its
        `.annotshot` when there is one, else the PNG (unedited). The
        current picture's edits are kept first. A capture gone from the
        folder only drops from the pane."""
        if self._capture is not None or self._opening:
            return False
        png, editable = recent.png_for(path), recent.editable_for(path)
        if not png.is_file() and not editable.is_file():
            self.recent.refresh()
            self.statusBar().showMessage(
                "That capture is no longer in the Recent folder", 6000)
            return False
        if not self.maybe_discard():
            return False
        recent.writer().waitForDone()   # its own last edit, on its way
        doc = None
        if editable.is_file():
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    doc = Document.load(editable)
            except Exception:           # noqa: BLE001 - fall back to the PNG
                doc = None
        if doc is None:
            img = QImage(str(png))
            if img.isNull():
                self.recent.refresh()
                self.statusBar().showMessage(
                    "That capture could not be read", 6000)
                return False
            doc = Document(img)
        doc.path = str(editable)
        self._bind(doc)
        if not quiet:
            self.statusBar().showMessage(
                f"Opened the capture from "
                f"{recent.time_label(recent.taken_at(png))}", 5000)
        return True

    # -- the autosave ---------------------------------------------------------
    def _schedule_autosave(self, *_) -> None:
        """An edit: write the editable about AUTOSAVE_MS after the last
        one (a document without a file has nowhere to keep itself)."""
        if self.doc.path:
            self._autosave_timer.start()

    def autosave_now(self, doc: Document | None = None, end_edit: bool = False,
                     from_timer: bool = False) -> bool:
        """Hand the document's edits to the writer thread at once. A text
        box being typed in is left alone when the timer fires (its edit
        writes when it ends); `end_edit` ends it first (switching, closing).
        True when a write was started."""
        doc = doc or self.doc
        if not doc.path:
            return False
        if doc.is_editing():
            if end_edit:
                doc.end_text_edit()     # pushes its edit: one more change
            elif from_timer:
                self._autosave_timer.start()
                return False
        if doc is self.doc:
            self._autosave_timer.stop()
        if not doc.needs_write():
            return False
        meta, base = doc.snapshot()
        gen = doc.written = doc.changes
        recent.writer().start(recent._SaveJob(
            doc, gen, doc.path, meta, base, self._saver))
        return True

    def _autosaved(self, doc, gen: int, path: str) -> None:
        """A write landed: the document is clean if nothing changed since,
        and its thumbnail shows the edit."""
        if shiboken6.isValid(doc) and doc.changes == gen:
            doc.undo_stack.setClean()
        if self.recent_store.owns(path):
            self.recent.refresh_one(path)

    def _autosave_failed(self, doc, gen: int, path: str, why: str) -> None:
        """One sentence; the next change (or switch) tries again."""
        if shiboken6.isValid(doc) and doc.written == gen:
            doc.written = -1
        self.statusBar().showMessage(AUTOSAVE_FAILED.format(why=why), 10000)

    def changeEvent(self, event):       # noqa: N802 - Qt's name
        if event.type() == QEvent.ActivationChange and \
                not self.isActiveWindow():
            self.autosave_now()         # the window lost focus: keep it now
        super().changeEvent(event)

    def restore_last(self) -> bool:
        """Launch: open the capture (or file) that was on screen when the
        app last closed, with its edits; the empty page when it is gone."""
        last = self.settings.value(CURRENT_KEY, "", type=str)
        if not last:
            return False
        if self.recent_store.owns(last):
            if not (Path(last).is_file() or recent.png_for(last).is_file()):
                return False
            return self.open_recent(last, quiet=True)
        if not os.path.isfile(last):
            return False
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                doc = Document.load(last)
        except Exception:               # noqa: BLE001 - a broken file: start empty
            return False
        self._bind(doc)
        return True

    def is_recent_doc(self, doc: Document | None = None) -> bool:
        doc = doc or self.doc
        return bool(doc.path) and self.recent_store.owns(doc.path)

    def _filing_failed(self, text: str) -> None:
        """The capture's PNG could not be filed: say so; a capture whose
        files are nowhere is no Recent capture (it asks before it goes)."""
        self.statusBar().showMessage(text, 10000)
        if self.is_recent_doc():
            if not recent.png_for(self.doc.path).exists() and \
                    not Path(self.doc.path).exists():
                self.doc.path = None
                self.update_title()

    def _recent_deleted(self, pngs: list) -> None:
        """A capture deleted from the pane: when it is the one on screen,
        the window lets go of it (its edits are not written back)."""
        if not self.is_recent_doc():
            return
        mine = os.path.normcase(str(recent.png_for(self.doc.path)))
        if mine in {os.path.normcase(p) for p in pngs}:
            self.doc.path = None
            self._bind(Document())

    def _act(self, text: str, slot, shortcuts=(), tip: str | None = None,
             checkable: bool = False, cls=QAction) -> QAction:
        a = cls(text, self)
        shortcuts = [shortcuts] if isinstance(shortcuts, str) else shortcuts
        if shortcuts:
            a.setShortcuts([QKeySequence(s) for s in shortcuts])
        a.setProperty("tip", tip or text)
        self._retip(a)
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        self.addAction(a)
        return a

    @staticmethod
    def _retip(a: QAction) -> None:
        """The tooltip: what it does, then its first key."""
        keys = a.shortcuts()
        tip = a.property("tip") or a.text()
        a.setToolTip(f"{tip} ({keys[0].toString()})" if keys else tip)

    def _build_actions(self) -> None:
        self.a_capture = self._act("Capture", self.capture, "Ctrl+N",
                                   "Capture a region or a window")
        self.a_open = self._act("Open…", self.open_project, "Ctrl+O",
                                "Open an Annotshot editable file")
        self.a_save = self._act(
            "Save…", self.save, ["Ctrl+S", "Ctrl+Shift+S"],
            "Save a copy of this capture as a picture or an editable file",
            cls=SaveAction)
        self.a_copy = self._act("Copy image", self.copy_image, "Ctrl+C",
                                "Copy the picture to the clipboard")
        self.a_clear = self._act("Clear", self.clear_picture, "Ctrl+W",
                                 "Remove the picture and start empty")
        self.a_undo = self._act("Undo", self.undo, "Ctrl+Z")
        self.a_redo = self._act("Redo", self.redo, ["Ctrl+Y", "Ctrl+Shift+Z"])
        # While a text box is edited, Undo / Redo drive its text's own
        # history; otherwise the undo stack (see _sync_undo).
        self._typing_doc = None
        self.undo_group.canUndoChanged.connect(self._sync_undo)
        self.undo_group.canRedoChanged.connect(self._sync_undo)
        self.undo_group.undoTextChanged.connect(self._sync_undo)
        self.undo_group.redoTextChanged.connect(self._sync_undo)
        group = QActionGroup(self)
        self.tool_actions: dict[Tool, QAction] = {}
        for tool in Tool:
            a = self._act(tool.value, lambda _=False, t=tool: self.view.set_tool(t),
                          checkable=True)
            group.addAction(a)
            self.tool_actions[tool] = a
        self.tool_actions[Tool.SELECT].setChecked(True)
        self.a_dup = self._act("Duplicate", self.duplicate, "Ctrl+D")
        self.a_front = self._act("Front", self.bring_to_front, "Ctrl+]",
                                 "Bring to front")
        self.a_back = self._act("Back", self.send_to_back, "Ctrl+[",
                                "Send to back")
        self.a_delete = self._act("Delete", self.delete_selected, "Delete")
        self.a_escape = self._act("Deselect", self.escape, "Esc")
        self.a_settings = self._act("Settings…", self.open_settings, "Ctrl+,",
                                    "Settings… — shortcuts and quick capture")
        self.a_settings.setMenuRole(QAction.NoRole)
        self.a_help = self._act("Help", self.show_help, "F1",
                                "Help — the user manual and your keys")
        self.a_help.setMenuRole(QAction.NoRole)
        self._help_window = None
        self.a_about = self._act("About Annotshot…", self.show_about,
                                 tip="About Annotshot — version, publisher, "
                                     "licence")
        self.a_about.setMenuRole(QAction.NoRole)
        self.shortcut_actions: dict[str, QAction] = {
            "capture": self.a_capture, "open": self.a_open,
            "save": self.a_save, "copy": self.a_copy, "clear": self.a_clear,
            "undo": self.a_undo, "redo": self.a_redo,
            **{t.name.lower(): self.tool_actions[t] for t in Tool},
            "duplicate": self.a_dup, "front": self.a_front,
            "back": self.a_back, "delete": self.a_delete,
            "settings": self.a_settings, "help": self.a_help}
        self.shortcut_names = dict(SHORTCUT_ROWS)
        self.default_shortcuts = {k: a.shortcuts()
                                  for k, a in self.shortcut_actions.items()}

    def _build_toolbar(self) -> None:
        """Row 1: Capture, Open, Save, Copy image, Clear | Undo, Redo. Row 2: the
        tools | the item actions. (The property strip is row 3.) Capture,
        Open, Save, Copy image and the tools are an icon with its label
        beside it; Undo, Redo and the item actions are icon-only (ICON_ONLY),
        named by their tooltips."""
        def new_bar(title: str, name: str, height: int) -> QToolBar:
            bar = QToolBar(title, self)
            bar.setObjectName(name)
            bar.setMovable(False)
            bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            bar.setIconSize(QSize(ICON_PX, ICON_PX))
            bar.setMinimumHeight(height)
            return bar

        def spacer(bar: QToolBar) -> None:
            w = QWidget(bar)
            w.setObjectName("spacer")
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            bar.addWidget(w)

        for a in (self.a_capture, self.a_open, self.a_save,
                  self.a_copy, self.a_clear, self.a_undo, self.a_redo,
                  self.a_settings,
                  *self.tool_actions.values(), self.a_dup, self.a_front,
                  self.a_back, self.a_delete):
            a.setIconText(a.text())     # a tool button drops the "…" else
        self._apply_icons()
        # its glyph is for the accent button; on a menu it would be blank
        self.a_capture.setIconVisibleInMenu(False)

        bar = new_bar("Main", "main", 40)
        for a in (self.a_capture, self.a_open, self.a_save, self.a_copy,
                  self.a_clear):
            bar.addAction(a)
        spacer(bar)                     # Undo, Redo keep the right edge
        bar.addSeparator()
        for a in (self.a_undo, self.a_redo, self.a_settings):
            bar.addAction(a)
        bar.widgetForAction(self.a_capture).setObjectName("primary")
        bar.widgetForAction(self.a_copy).setObjectName("outline")
        bar.widgetForAction(self.a_settings).setObjectName("last")
        self.addToolBar(bar)
        # ASSUMES: the rows are sized for the widest of the three CI fonts
        # (Linux's DejaVu Sans); the tools' padding in theme.TEMPLATE keeps
        # row 2 inside 900 px there (the wide-font test proves it).
        bar = new_bar("Tools", "tools", 36)
        for a in self.tool_actions.values():
            bar.addAction(a)
        spacer(bar)
        for a in (self.a_dup, self.a_front, self.a_back, self.a_delete):
            bar.addAction(a)
        bar.widgetForAction(self.tool_actions[Tool.SELECT]).setObjectName("first")
        bar.widgetForAction(self.a_delete).setObjectName("last")
        self.addToolBarBreak()
        self.addToolBar(bar)
        for b in (self.findChild(QToolBar, "main"), bar):
            for a in b.actions():
                if a.text() in ICON_ONLY:
                    button = b.widgetForAction(a)
                    button.setToolButtonStyle(Qt.ToolButtonIconOnly)
                    button.setProperty("iconOnly", True)

    def _apply_icons(self) -> None:
        """Every icon the window shows, in the current theme's inks (built
        again when the theme changes)."""
        for a in (self.a_capture, self.a_open, self.a_save,
                  self.a_copy, self.a_clear, self.a_undo, self.a_redo,
                  self.a_settings,
                  *self.tool_actions.values(), self.a_dup, self.a_front,
                  self.a_back, self.a_delete):
            a.setIcon(themed_icon(TOOLBAR_ICONS[a.text()]))
        self.a_capture.setIcon(themed_icon(
            "capture", ink="capture-icon", checked="capture-icon",
            disabled="capture-icon-disabled"))
        self.a_copy.setIcon(themed_icon("copy-image", ink="copy-icon"))
        for b in (getattr(self, "b_nofill", None),
                  getattr(self, "b_noborder", None)):
            if b is not None:
                b.setIcon(themed_icon("clear", size=14))
        for key, b in getattr(self, "align_buttons", {}).items():
            b.setIcon(themed_icon(ALIGN_ICONS[key], size=17,
                                  checked="mark-ink"))
        self._marks.clear()

    def set_theme(self, name: str) -> str:
        """Apply the theme to the whole app at once and remember it."""
        name = theme.apply(QApplication.instance(), name)
        self.settings.setValue(theme.SETTING, name)
        return name

    def retheme(self) -> None:
        """The theme changed (theme.apply calls this): the icons, the
        heading's mark, the Recent pane and the canvas are drawn again."""
        self._apply_icons()
        if hasattr(self, "sel_mark"):
            self._show_selection(self.doc.selected())
        self.recent.retheme()
        self.doc.update()
        self.view.viewport().update()
        if self._help_window is not None:
            self._help_window.update()

    def _button(self, text: str, tip: str, slot, checkable=False) -> QToolButton:
        b = QToolButton(self)
        b.setText(text)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        (b.toggled if checkable else b.clicked).connect(slot)
        return b

    def _spin(self, lo: int, hi: int, tip: str, slot) -> QSpinBox:
        s = QSpinBox(self)
        s.setRange(lo, hi)
        s.setSuffix(" px")
        s.setToolTip(tip)
        s.valueChanged.connect(slot)
        return s

    def _build_props_bar(self) -> None:
        """Row 3, the property strip: two labelled rows under the tools --
        what is selected, the text's font, size, style and alignment; then
        text color, fill, border, width and opacity. A control is enabled
        when the selection has its property (refresh_props)."""
        self._key_widgets: dict[str, list] = {}
        bar = QToolBar("Properties", self)
        bar.setObjectName("properties")
        bar.setMovable(False)
        set_ = self._set
        self.c_text = ColorButton("Text color", "Text color",
                                  lambda c: set_({"text_color": c}, "Text color"))
        self.c_fill = ColorButton("Fill", "Fill color",
                                  lambda c: set_({"fill_color": c}, "Fill"))
        self.b_nofill = self._button("No fill", "No fill",
                                     lambda: set_({"fill_color": _clear_alpha}, "No fill"))
        self.c_border = ColorButton("Border", "Border color",
                                    lambda c: set_({"border_color": c}, "Border"))
        self.b_noborder = self._button("No border", "No border",
                                       lambda: set_({"border_color": _clear_alpha}, "No border"))
        for b, name in ((self.b_nofill, "No fill"), (self.b_noborder, "No border")):
            b.setObjectName("field")
            b.setText("")
            b.setAccessibleName(name)
            b.setIcon(themed_icon("clear", size=14))
            b.setIconSize(QSize(14, 14))
            b.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.s_width = self._spin(0, 40, "Border width",
                                  lambda v: set_({"border_width": v}, "Border width"))
        self.f_font = FontBox(self)
        self.f_font.setToolTip("Font")
        self.f_font.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.f_font.setMinimumContentsLength(8)
        self.f_font.setFixedWidth(150)
        self.f_font.currentFontChanged.connect(
            lambda f: set_({"font_family": f.family()}, "Font"))
        self.s_size = self._spin(6, 400, "Font size (pixels)",
                                 lambda v: set_({"font_px": v}, "Font size"))
        for w in (self.f_font, self.s_size, self.s_width):
            w.setMinimumHeight(28)
        self.b_bold = self._button("B", "Bold", lambda on: set_({"bold": on}, "Bold"), True)
        self.b_italic = self._button("I", "Italic",
                                     lambda on: set_({"italic": on}, "Italic"), True)
        f = self.b_bold.font(); f.setBold(True); self.b_bold.setFont(f)
        f = self.b_italic.font(); f.setItalic(True); self.b_italic.setFont(f)
        self.align_buttons: dict[str, QToolButton] = {}
        group = QButtonGroup(self)
        for key, text in (("left", "Left"), ("center", "Center"),
                          ("right", "Right")):
            b = self._button(text, f"Align {key}",
                             lambda _=False, k=key: set_({"align": k}, "Align"))
            b.setCheckable(True)
            b.setIcon(themed_icon(ALIGN_ICONS[key], size=17,
                                  checked="mark-ink"))
            b.setIconSize(QSize(17, 17))
            b.setToolButtonStyle(Qt.ToolButtonIconOnly)
            group.addButton(b)
            self.align_buttons[key] = b
        # The arrow's head: its kind, its size and both ends (shown only
        # while an arrow is selected).
        self.cb_head = self._choice("Arrow head", ARROW_HEADS,
                                    lambda v: set_({"head": v}, "Arrow head"))
        self.cb_head_size = self._choice(
            "Arrow head size", HEAD_SIZE_NAMES,
            lambda v: set_({"head_size": v}, "Arrow head size"))
        self.cb_line = self._choice("Line style", LINE_STYLE_NAMES,
                                    lambda v: set_({"line_style": v}, "Line style"))
        self.ch_both = QCheckBox("Both ends", self)
        self.ch_both.setToolTip("A head at both ends")
        self.ch_both.toggled.connect(
            lambda on: set_({"both_ends": on}, "Both ends"))
        self.sl_opacity = QSlider(Qt.Horizontal, self)
        self.sl_opacity.setRange(0, 100)
        self.sl_opacity.setFixedWidth(112)
        self.sl_opacity.setToolTip("Opacity")
        self.sl_opacity.sliderPressed.connect(self._new_slider_session)
        self.sl_opacity.actionTriggered.connect(self._slider_action)
        self.sl_opacity.valueChanged.connect(
            lambda v: set_({"opacity": v / 100}, "Opacity",
                           ("opacity", self._slider_session)))
        self.opacity_label = QLabel(self)
        self.opacity_label.setObjectName("fieldValue")
        self.opacity_label.setMinimumWidth(
            self.opacity_label.fontMetrics().horizontalAdvance("100%") + 4)
        self.sl_opacity.valueChanged.connect(
            lambda v: self.opacity_label.setText(f"{v}%"))
        self.opacity_label.setText(f"{self.sl_opacity.value()}%")

        # What is selected: a small kind mark and its name. The name keeps
        # one width so the row never shifts as the selection changes.
        self.sel_mark = QLabel(self)
        self.sel_mark.setObjectName("objectMark")
        self.sel_mark.setFixedSize(21, 21)
        self.sel_mark.setAlignment(Qt.AlignCenter)
        self.sel_heading = QLabel(self)
        self.sel_heading.setObjectName("objectHeading")
        bold = QFont(self.sel_heading.font())
        bold.setBold(True)
        fm = QFontMetrics(bold)
        self.sel_heading.setMinimumWidth(max(
            fm.horizontalAdvance(t) for t in (
                "Nothing selected", "Text box", "Rectangle", "Highlight",
                "Pen stroke", "99 objects")) + 4)

        strip = QWidget(self)
        strip.setObjectName("strip")
        rows = QVBoxLayout(strip)
        rows.setContentsMargins(8, 2, 8, 2)
        rows.setSpacing(0)

        def row(height: int, *parts) -> None:
            w = QWidget(strip)
            w.setMinimumHeight(height)
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)
            for part in parts:
                h.addWidget(part)
            h.addStretch(1)
            rows.addWidget(w)

        row(36,
            self._group(None, self.sel_mark, self.sel_heading, gap=6),
            self._divider(),
            self._group("Font", self.f_font),
            self._group("Size", self.s_size),
            self._divider(),
            self._group("Style", self._segment(self.b_bold, self.b_italic)),
            self._group("Align", self._segment(*self.align_buttons.values())))
        row(36,
            self._group("Text", self.c_text),
            self._divider(),
            self._group("Fill", self.c_fill, self.b_nofill),
            self._divider(),
            self._group("Border", self.c_border, self.b_noborder),
            self._group("Width", self.s_width),
            *self._shown_with("line_style",
                              self._group("Line", self.cb_line)),
            self._divider(),
            self._group("Opacity", self.sl_opacity, self.opacity_label,
                        gap=6),
            *self._shown_with("head", self._divider(),
                              self._group("Head", self.cb_head),
                              self._group("Head size", self.cb_head_size),
                              self.ch_both))

        # In a window narrower than the strip, it scrolls sideways instead
        # of widening the window.
        scroll = QScrollArea(bar)
        scroll.setObjectName("stripScroll")
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        scroll.setWidget(strip)
        scroll.viewport().setAutoFillBackground(False)
        strip.setAutoFillBackground(False)
        sideways = scroll.horizontalScrollBar()

        def fit_height(*_):
            if not shiboken6.isValid(sideways):     # at teardown
                return
            extra = sideways.sizeHint().height() if sideways.maximum() > 0 else 0
            scroll.setFixedHeight(strip.sizeHint().height() + extra)
        sideways.rangeChanged.connect(fit_height)
        fit_height()
        self.prop_strip = strip
        bar.addWidget(scroll)

        self._controls = {
            self.c_text: "text_color", self.c_fill: "fill_color",
            self.b_nofill: "fill_color", self.c_border: "border_color",
            self.b_noborder: "border_color", self.s_width: "border_width",
            self.f_font: "font_family", self.s_size: "font_px",
            self.b_bold: "bold", self.b_italic: "italic",
            **{b: "align" for b in self.align_buttons.values()},
            self.sl_opacity: "opacity", self.cb_line: "line_style",
            self.cb_head: "head",
            self.cb_head_size: "head_size", self.ch_both: "both_ends"}
        self.addToolBarBreak()
        self.addToolBar(bar)

    def _group(self, label: str | None, *widgets, gap: int = 5) -> QWidget:
        """A field label (if any) and its controls, side by side."""
        box = QWidget(self)
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(gap)
        if label:
            lab = QLabel(label, self)
            lab.setObjectName("fieldLabel")
            lab.setBuddy(widgets[0])
            h.addWidget(lab)
        for w in widgets:
            h.addWidget(w)
        return box

    def _choice(self, tip: str, choices, slot) -> QComboBox:
        """A pull-down of (value, name) pairs; `slot` gets the value."""
        box = QComboBox(self)
        box.setToolTip(tip)
        box.setAccessibleName(tip)
        box.setMinimumHeight(28)
        for value, name in choices:
            box.addItem(name, value)
        box.currentIndexChanged.connect(lambda i: slot(box.itemData(i)))
        return box

    def _shown_with(self, key: str, *widgets) -> tuple:
        """Widgets the strip shows only while the selection has `key`."""
        self._key_widgets.setdefault(key, []).extend(widgets)
        return widgets

    def _divider(self) -> QFrame:
        line = QFrame(self)
        line.setObjectName("divider")
        line.setFixedSize(1, 30)
        return line

    def _segment(self, *buttons) -> QFrame:
        """Buttons joined into one bordered pill (B I, the alignments)."""
        frame = QFrame(self)
        frame.setObjectName("segment")
        frame.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        h = QHBoxLayout(frame)
        h.setContentsMargins(1, 1, 1, 1)
        h.setSpacing(0)
        for i, b in enumerate(buttons):
            if i == 0:
                b.setObjectName("first")
            h.addWidget(b)
        return frame

    # -- document binding -------------------------------------------------
    def _bind(self, doc: Document) -> None:
        """Make `doc` the current document; the window owns it, and the
        replaced one is disconnected and deleted."""
        old = self._bound
        if old is not None and old is not doc and old.path:
            self.autosave_now(old, end_edit=True)   # its last edit, kept
        doc.setParent(self)
        self.doc = self._bound = doc
        self.undo_group.addStack(doc.undo_stack)
        self.undo_group.setActiveStack(doc.undo_stack)
        doc.selectionChanged.connect(self.refresh_props)
        doc.undo_stack.indexChanged.connect(self._doc_changed)
        doc.undo_stack.indexChanged.connect(self._schedule_autosave)
        doc.undo_stack.cleanChanged.connect(self.update_title)
        doc.editingChanged.connect(self._editing_changed)
        self.view.set_document(doc)
        if old is not None and old is not doc:
            old.selectionChanged.disconnect(self.refresh_props)
            old.undo_stack.indexChanged.disconnect(self._doc_changed)
            old.undo_stack.indexChanged.disconnect(self._schedule_autosave)
            old.undo_stack.cleanChanged.disconnect(self.update_title)
            old.editingChanged.disconnect(self._editing_changed)
            self.undo_group.removeStack(old.undo_stack)
            old.deleteLater()
        self.tool_actions[Tool.SELECT].setChecked(True)
        self._editing_changed(doc.editing_item)
        self._doc_changed()
        if self._remembering:
            self.settings.setValue(CURRENT_KEY, doc.path or "")

    def _editing_changed(self, item) -> None:
        """Point Undo / Redo at the edited text's history, or back at the
        undo stack when no text box is being edited."""
        if self._typing_doc is not None:
            self._typing_doc.undoAvailable.disconnect(self._sync_undo)
            self._typing_doc.redoAvailable.disconnect(self._sync_undo)
        self._typing_doc = item.editor.document() if item is not None else None
        if self._typing_doc is not None:
            self._typing_doc.undoAvailable.connect(self._sync_undo)
            self._typing_doc.redoAvailable.connect(self._sync_undo)
        self._sync_undo()

    def _sync_undo(self, *_) -> None:
        td = self._typing_doc
        if td is not None:
            can_undo, can_redo = td.isUndoAvailable(), td.isRedoAvailable()
            undo_tip, redo_tip = "Undo typing", "Redo typing"
        else:
            g = self.undo_group
            can_undo, can_redo = g.canUndo(), g.canRedo()
            undo_tip = f"Undo {g.undoText()}" if can_undo else "Undo"
            redo_tip = f"Redo {g.redoText()}" if can_redo else "Redo"
        self.a_undo.setEnabled(can_undo)
        self.a_redo.setEnabled(can_redo)
        self.a_undo.setProperty("tip", undo_tip)
        self.a_redo.setProperty("tip", redo_tip)
        self._retip(self.a_undo)
        self._retip(self.a_redo)

    def _doc_changed(self, *_) -> None:
        self.size_label.setText(f"{self.doc.base.width()} × "
                                f"{self.doc.base.height()} px")
        self.update_title()
        self.refresh_props()

    def update_title(self, *_) -> None:
        if self.is_recent_doc():        # a Recent capture: its stamp
            name = Path(self.doc.path).stem
        else:
            name = Path(self.doc.path).name if self.doc.path else "Untitled"
        self.setWindowTitle(f"Annotshot — {name}[*]")
        # A document with a file keeps itself (the autosave): no * churn.
        self.setWindowModified(not self.doc.path
                               and self.doc.undo_stack.needs_save())

    def refresh_props(self) -> None:
        """Enable the controls the selection has; show the first item's values."""
        items = self.doc.selected()
        self._show_selection(items)

        def first(key):
            if not items and key in NEW_TEXT_KEYS:  # what the next text box gets
                return self.new_text_style()[key]
            for it in items:
                k = it.key_for(key)
                if k is not None:
                    return it.props[k]
            return None

        self._refreshing = True
        try:
            for w, key in self._controls.items():
                w.setEnabled(first(key) is not None)
            # A highlight's fill alpha is fixed: "No fill" does nothing to it.
            self.b_nofill.setEnabled(any(
                it.key_for("fill_color") is not None
                and not isinstance(it, HighlightItem) for it in items))
            for button, key in ((self.c_text, "text_color"),
                                (self.c_fill, "fill_color"),
                                (self.c_border, "border_color")):
                if first(key) is not None:
                    button.set_color(first(key))
            if first("border_width") is not None:
                self.s_width.setValue(first("border_width"))
            if first("font_family") is not None:
                self.f_font.setCurrentFont(QFont(first("font_family")))
            if first("font_px") is not None:
                self.s_size.setValue(first("font_px"))
            self.b_bold.setChecked(bool(first("bold")))
            self.b_italic.setChecked(bool(first("italic")))
            if first("align") in self.align_buttons:
                self.align_buttons[first("align")].setChecked(True)
            if first("opacity") is not None:
                self.sl_opacity.setValue(round(first("opacity") * 100))
            for box, key in ((self.cb_line, "line_style"),
                             (self.cb_head, "head"),
                             (self.cb_head_size, "head_size")):
                if first(key) is not None:
                    box.setCurrentIndex(max(0, box.findData(first(key))))
            self.ch_both.setChecked(bool(first("both_ends")))
            self._show_key_widgets(first)
        finally:
            self._refreshing = False

    def _show_key_widgets(self, first) -> None:
        """Show the strip's per-kind controls the selection has, hide the
        rest. Each changed row is told its size changed: a hidden window
        lays out only on request, and the strip must never keep the width
        of controls it no longer shows."""
        changed = set()
        for key, widgets in self._key_widgets.items():
            show = first(key) is not None
            for w in widgets:
                if w.isHidden() == show:
                    w.setVisible(show)
                    changed.add(w.parentWidget())
        for row in changed:
            row.updateGeometry()

    def _show_selection(self, items) -> None:
        """The strip's heading: what the controls will change."""
        if len(items) == 1:
            item = items[0]
            text = "Text box" if item.KIND == "text" else item.LABEL
            kind = KIND_ICONS.get(item.KIND, "select")
        else:
            text = f"{len(items)} objects" if items else "Nothing selected"
            kind = "select"
        self.sel_heading.setText(text)
        self.sel_heading.setEnabled(bool(items))
        dpr = self.devicePixelRatioF()
        if (kind, dpr) not in self._marks:
            self._marks[kind, dpr] = themed_icon(kind, size=13,
                                                 ink="mark-ink").pixmap(
                QSize(13, 13), dpr)
        self.sel_mark.setPixmap(self._marks[kind, dpr])

    def _new_slider_session(self) -> None:
        self._slider_session += 1

    def _slider_action(self, action: int) -> None:
        # A groove click, an arrow key or a wheel step is its own undo step;
        # the moves of a drag stay in the session sliderPressed opened.
        # (the signal passes a plain int; the PySide6 enum is not an IntEnum)
        if not (int(action) == QAbstractSlider.SliderMove.value
                and self.sl_opacity.isSliderDown()):
            self._new_slider_session()

    def new_text_style(self) -> dict:
        """The font, size, bold and italic the next text box starts in."""
        return {**{k: TextBoxItem.DEFAULTS[k] for k in NEW_TEXT_KEYS},
                **self.view.new_text_props}

    def _set(self, props: dict, text: str, merge_key=None) -> None:
        if not self._refreshing and not self.doc.selected():
            # Nothing selected: a font, size or style picked in the strip is
            # what the next text box starts in, this session.
            picked = {k: v for k, v in props.items() if k in NEW_TEXT_KEYS}
            if picked:
                self.view.new_text_props.update(picked)
                self.refresh_props()
            return
        if not self._refreshing:
            if not self.doc.set_props(self.doc.selected(), props, text,
                                      merge_key):
                self.refresh_props()     # e.g. a highlight's forced alpha

    def menu_actions(self, on_item: bool) -> list:
        """The right-click menu, top to bottom (None = a separator): the
        same actions as the buttons, so the same text, icons and keys."""
        actions = [self.a_copy, self.a_save, None]
        if on_item:
            actions += [self.a_dup, self.a_front, self.a_back, self.a_delete,
                        None]
        return actions + [self.a_clear, self.a_capture, self.a_recent, None,
                          self.a_settings, self.a_help, self.a_about]

    # -- the keys the user sets -------------------------------------------
    def _key_owner(self, seq: QKeySequence, skip: str | None = None,
                   with_hotkey: bool = True) -> str | None:
        """The name of what already uses `seq` (an action, Deselect, or the
        capture key), or None."""
        if seq.isEmpty():
            return None
        for key, a in self.shortcut_actions.items():
            if key != skip and any(k == seq for k in a.shortcuts()):
                return self.shortcut_names[key]
        if any(k == seq for k in self.a_escape.shortcuts()):
            return self.a_escape.text()
        if (with_hotkey and skip != "hotkey" and not self.hotkey_off()
                and self.hotkey_sequence() == seq):
            return HOTKEY_NAME
        return None

    @staticmethod
    def _taken(seq: QKeySequence, owner: str) -> str:
        return (f"{seq.toString(QKeySequence.NativeText)} is already used "
                f"by {owner}.")

    def _use_shortcuts(self, key: str, seqs: list) -> None:
        a = self.shortcut_actions[key]
        a.setShortcuts(seqs)
        if a in (self.a_undo, self.a_redo):
            self._sync_undo()
        else:
            self._retip(a)

    def set_shortcut(self, key: str, seq: QKeySequence) -> str | None:
        """Give an action its own key (an empty one removes its key). The
        one-line reason when the key is already used; nothing changes then."""
        seq = QKeySequence(seq)
        owner = self._key_owner(seq, skip=key)
        if owner:
            return self._taken(seq, owner)
        self._use_shortcuts(key, [] if seq.isEmpty() else [seq])
        self.settings.setValue(f"shortcuts/{key}",
                               seq.toString(QKeySequence.PortableText))
        return None

    def reset_shortcut(self, key: str) -> str | None:
        """Back to the key(s) Annotshot ships with, unless another action
        now uses one of them."""
        for seq in self.default_shortcuts[key]:
            owner = self._key_owner(seq, skip=key)
            if owner:
                return self._taken(seq, owner)
        self._use_shortcuts(key, list(self.default_shortcuts[key]))
        self.settings.remove(f"shortcuts/{key}")
        return None

    def reset_all_shortcuts(self) -> None:
        for key in self.shortcut_actions:
            self._use_shortcuts(key, list(self.default_shortcuts[key]))
        self.settings.remove("shortcuts")
        self.settings.remove("hotkey/sequence")

    def _apply_saved_shortcuts(self) -> None:
        """At start: the keys saved under shortcuts/<key>. One that clashes
        with a key already in use keeps the shipped default."""
        for key in self.shortcut_actions:
            value = self.settings.value(f"shortcuts/{key}", None)
            if value is None:
                continue
            seq = QKeySequence(str(value))
            if not self._key_owner(seq, skip=key, with_hotkey=False):
                self._use_shortcuts(key, [] if seq.isEmpty() else [seq])

    # -- the capture key ------------------------------------------------------
    def hotkey_sequence(self) -> QKeySequence:
        return QKeySequence(self.settings.value("hotkey/sequence",
                                                hotkey.DEFAULT, type=str))

    def hotkey_off(self) -> bool:
        return self.settings.value("hotkey/off", False, type=bool)

    def set_hotkey(self, seq: QKeySequence, off: bool) -> str | None:
        """Save the capture key and whether it is off, then register it.
        A key an action uses is refused (nothing saved); a key the system
        refuses is kept as typed and the reason returned."""
        seq = QKeySequence(seq)
        if not off:
            owner = self._key_owner(seq, skip="hotkey")
            if owner:
                return self._taken(seq, owner)
        self.settings.setValue("hotkey/sequence",
                               seq.toString(QKeySequence.PortableText))
        self.settings.setValue("hotkey/off", bool(off))
        return self.apply_hotkey()

    def apply_hotkey(self) -> str | None:
        """Register the saved capture key (main() calls this once the window
        is up). The reason, also on the status line, when it cannot be."""
        self.hotkey.clear()
        if self.hotkey_off() or not self.hotkey.available:
            return None
        problem = self.hotkey.set_sequence(self.hotkey_sequence())
        if problem:
            self.statusBar().showMessage(f"{HOTKEY_NAME}: {problem}", 10000)
        return problem

    def capture_from_anywhere(self) -> None:
        """The capture key: bring the window back if it is minimized or
        hidden, then Capture."""
        if self._capture is not None:
            return
        if self.isMinimized() or not self.isVisible():
            self.showNormal()
            self.raise_()
            self.activateWindow()
        self.capture()

    def show_about(self) -> None:
        from .help import AboutDialog
        dialog = AboutDialog(self, on_help=lambda: self._help_from(dialog))
        dialog.exec()
        dialog.deleteLater()

    def _help_from(self, dialog) -> None:
        """Help from inside a window that waits for an answer (About,
        Settings): close it first, so the Help window can be used."""
        dialog.accept()
        self.show_help()

    def shortcut_rows(self) -> list:
        """(what it does, its keys now) for every key the user can press:
        the actions with the keys they have now, Deselect, and the capture
        key (no key when it is off or not available here)."""
        rows = [(name, self.shortcut_actions[key].shortcuts())
                for key, name in SHORTCUT_ROWS]
        rows.append(("Stop typing, then clear the selection",
                     self.a_escape.shortcuts()))
        on = self.hotkey.available and not self.hotkey_off()
        rows.append((HOTKEY_NAME, [self.hotkey_sequence()] if on else []))
        return rows

    def show_help(self) -> None:
        """The Help window: the manual with the keys as they are now. It
        does not block the editor; a second F1 brings it to the front."""
        from .help import HelpWindow
        if self._help_window is None:
            self._help_window = HelpWindow(self.shortcut_rows(), self)
            self._help_window.finished.connect(self._help_closed)
        else:
            self._help_window.refresh(self.shortcut_rows())
        self._help_window.show()
        self._help_window.raise_()
        self._help_window.activateWindow()

    def _help_closed(self, *_) -> None:
        if self._help_window is not None:
            self._help_window.deleteLater()
            self._help_window = None

    def open_settings(self) -> None:
        from .settings_dialog import SettingsDialog
        dialog = SettingsDialog(self)
        dialog.exec()
        dialog.deleteLater()

    # -- quick capture ----------------------------------------------------------
    def quick_copy(self) -> bool:
        return self.settings.value("capture/copy", False, type=bool)

    def quick_minimize(self) -> bool:
        """Minimize after the copy: only while the copy is on too."""
        return self.quick_copy() and self.settings.value(
            "capture/minimize", False, type=bool)

    # -- edit actions -----------------------------------------------------
    def _typing(self, redo: bool) -> bool:
        """Undo / redo inside the text box being edited; False if none."""
        item = self.doc.editing_item
        if item is None:
            return False
        ed = item.editor
        cursor = ed.textCursor()
        doc = ed.document()
        (doc.redo if redo else doc.undo)(cursor)
        ed.setTextCursor(cursor)
        return True

    def undo(self) -> None:
        if not self._typing(redo=False):
            self.undo_group.undo()

    def redo(self) -> None:
        if not self._typing(redo=True):
            self.undo_group.redo()

    def duplicate(self) -> None:
        self.doc.duplicate(self.doc.selected())

    def bring_to_front(self) -> None:
        self.doc.bring_to_front(self.doc.selected())

    def send_to_back(self) -> None:
        self.doc.send_to_back(self.doc.selected())

    def delete_selected(self) -> None:
        self.doc.end_text_edit()
        self.doc.remove_items(self.doc.selected())

    def escape(self) -> None:
        if self.doc.is_editing():
            self.doc.end_text_edit()
        else:
            self.doc.clearSelection()

    def _exported(self) -> None:
        """The picture is out: this step counts as saved until the next edit."""
        self.doc.undo_stack.mark_exported()
        self.update_title()

    def clear_picture(self) -> None:
        """Clear: the discard question, then a fresh empty document."""
        if self._capture is not None or not self.maybe_discard():
            return
        self._bind(Document())
        self.statusBar().showMessage("Cleared", 3000)

    def copy_image(self) -> None:
        QApplication.clipboard().setImage(self.doc.render_image())
        self._exported()
        self.statusBar().showMessage("Copied — paste it anywhere", 2000)

    # -- files ------------------------------------------------------------
    def _folder(self, kind: str) -> Path:
        folder = Path(self.settings.value(f"last_dir/{kind}", "", type=str) or DEFAULT_DIR)
        if not folder.is_dir():
            folder = DEFAULT_DIR
            folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _default_path(self, kind: str, ext: str) -> str:
        stamp = QDateTime.currentDateTime().toString("yyyy-MM-dd HH-mm-ss")
        return str(self._folder(kind) / f"Annotshot {stamp}.{ext}")

    def _remember(self, kind: str, path: str,
                  name_filter: str | None = None) -> None:
        self.settings.setValue(f"last_dir/{kind}", str(Path(path).parent))
        if name_filter is not None:
            self.settings.setValue(f"last_filter/{kind}", name_filter)

    def _warn(self, text: str) -> None:
        QMessageBox.warning(self, "Annotshot", text)

    def save(self, *_) -> bool:
        """Save…: a plain Ctrl+S saves an editable file the document already
        has, without asking; otherwise (the button, Ctrl+Shift+S, no file
        yet) the Save dialog."""
        key = self.a_save.take_key()
        self.doc.end_text_edit()
        first = self.a_save.shortcuts()[:1]
        if self.doc.path and key is not None and first and key == first[0]:
            return self._save_editable(self.doc.path)
        return self.save_as()

    def save_as(self) -> bool:
        """The Save dialog. A picture type saves the picture with every edit;
        the .annotshot type saves the editable file. The chosen type wins over a
        typed extension; the last type chosen is preselected next time."""
        self.doc.end_text_edit()
        types = {t[0]: t for t in SAVE_TYPES}
        last = self.settings.value("last_filter/save", "", type=str)
        preset = types.get(last, SAVE_TYPES[0])
        if self.doc.path:
            p = Path(self.doc.path)
            start = str(p.with_suffix("." + preset[1][0]))
        else:
            start = self._default_path("save", preset[1][0])
        path, chosen = QFileDialog.getSaveFileName(
            self, "Save", start, SAVE_FILTERS, preset[0])
        if not path:
            return False
        name_filter, exts, fmt = types.get(chosen, preset)
        typed, path = path, typed_path_for(path, exts)
        if (os.path.normcase(path) != os.path.normcase(typed)
                and os.path.exists(path) and not self._ask_replace(path)):
            return False
        if fmt == PROJECT_FORMAT:
            ok = self._save_editable(path)
        elif fmt in OFFICE_FORMATS:
            ok = self._save_office(path, fmt)
        else:
            ok = self._save_picture(path, fmt)
        if ok:
            self._remember("save", path, name_filter)
        return ok

    def _ask_replace(self, path: str) -> bool:
        """The Save window asked about the name the user typed; when the
        chosen type changed that name to one that is already there, ask
        here. True replaces it; the default answer is No."""
        p = Path(path)
        folder = p.parent.name or str(p.parent)
        answer = QMessageBox.question(
            self, "Annotshot",
            f"Replace {p.name}?\n\nA file with this name is already in {folder}.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes

    def _save_picture(self, path: str, fmt: str) -> bool:
        """The rendered picture with every edit (white under JPEG / BMP)."""
        img = self.doc.render_image()
        if fmt in NO_ALPHA_FORMATS:
            img = flatten_on_white(img)
        quality = JPEG_QUALITY if fmt == "JPEG" else -1
        if not img.save(path, fmt, quality):
            self._warn(f"Could not write {path}")
            return False
        self._exported()
        self.statusBar().showMessage(f"Saved {Path(path).name}", 3000)
        return True

    def _save_office(self, path: str, fmt: str) -> bool:
        """The picture in a Word document or on a PowerPoint slide."""
        try:
            export(fmt, self.doc.render_image(), path)
        except ModuleNotFoundError as e:
            if (e.name or "").split(".")[0] not in ("docx", "pptx"):
                self._warn(f"Could not save {Path(path).name}:\n{e}")
                return False
            # A copy run from source that never installed the two Word /
            # PowerPoint libraries: say how to add them (the versions are
            # the release workflow's pins).
            self._warn(
                "Saving as Word or PowerPoint needs two more parts that this "
                "copy of Annotshot does not have yet.\n"
                "In a terminal, run:\n"
                f"{pip_command()}")
            return False
        except OSError as e:            # the folder, the rights, the disk
            self._warn(save_problem(path, e))
            return False
        except Exception as e:          # noqa: BLE001 - the libraries raise
            # their own kinds (zip, XML) as well as OSError
            self._warn(f"Could not save {Path(path).name}:\n{e}")
            return False
        self._exported()
        self.statusBar().showMessage(f"Saved {Path(path).name}", 3000)
        return True

    def _save_editable(self, path: str) -> bool:
        """The editable .annotshot file. A document that already keeps
        itself (it has a file) writes a second COPY there and stays the
        one that keeps itself; its own file is simply written now. A
        document with no file at all takes this one as its file."""
        self.doc.end_text_edit()
        own = self.doc.path and os.path.normcase(os.path.abspath(path)) == \
            os.path.normcase(os.path.abspath(self.doc.path))
        try:
            if self.doc.path and not own:
                self.doc.write(path)
            else:
                self._autosave_timer.stop()
                recent.writer().waitForDone()   # never two writers of a file
                self.doc.save(path)
        except OSError as e:
            self._warn(f"Could not save the editable file:\n{e}")
            return False
        self._remember("project", path)
        self.update_title()
        self.statusBar().showMessage(f"Saved {Path(path).name}", 3000)
        return True

    def open_project(self) -> None:
        """Open…: the discard question, then the Open window. A file chosen
        in the Open window is the newest choice, so it replaces one that
        arrived from Finder meanwhile."""
        if self._opening:
            return                      # one open at a time

        def run() -> bool:
            if not self.maybe_discard():
                return False
            path, _ = QFileDialog.getOpenFileName(
                self, "Open", str(self._folder("project")), OPEN_FILTER)
            if not path:
                return False
            self._kept = None           # chosen after anything kept
            return self._open_now(path, ask=False)
        self._one_open(run)

    def open_path(self, path: str, ask: bool = True) -> bool:
        """Open the editable file at `path` (a double-click, the command
        line, Finder, or Open…). True when it loaded; a bad file shows the
        plain warning and the current document stays. While another open is
        running (its question on screen) the file is kept instead, and it
        opens when that open returns; False then."""
        path = os.path.abspath(path)    # never a folder relative to the cwd
        if self._opening:
            self._kept = path           # the newest wins
            return False
        return self._one_open(lambda: self._open_now(path, ask))

    def _one_open(self, first) -> bool:
        """Run `first`, then every file kept meanwhile, one at a time. When
        an open raises, the kept file goes too, so it never opens later."""
        self._opening = True
        try:
            ok = first()
            while self._kept is not None:
                path, self._kept = self._kept, None
                self._open_now(path, ask=True)
        except BaseException:
            self._kept = None
            raise
        finally:
            self._opening = False
        return ok

    def _open_now(self, path: str, ask: bool) -> bool:
        path = os.path.abspath(path)
        if ask and not self.maybe_discard():
            return False
        self.autosave_now(end_edit=True)
        recent.writer().waitForDone()   # the file may be the one just written
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                doc = Document.load(path)
        except Exception as e:          # never a bare traceback from Open
            self._warn(open_warning(path, e))
            return False
        self._bind(doc)
        self._remember("project", path)
        if caught:
            self.statusBar().showMessage(
                "; ".join(str(w.message) for w in caught), 8000)
        return True

    def maybe_discard(self) -> bool:
        """True when it is fine to replace the document. A document with a
        file (a Recent capture, a file opened from anywhere) keeps itself:
        its last edits go to the writer and nothing is asked. Only a
        document with no file at all (Keep recent off, or the start-up
        page drawn on) asks, and only when the current step is neither
        saved nor exported."""
        self.doc.end_text_edit()
        if self.doc.path:
            self.autosave_now()
            return True
        if not self.doc.undo_stack.needs_save():
            return True
        answer = QMessageBox.question(
            self, "Annotshot", "Save your changes to this project first?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save)
        if answer == QMessageBox.Save:
            return (self._save_editable(self.doc.path) if self.doc.path
                    else self.save_as())
        return answer == QMessageBox.Discard

    def closeEvent(self, event):
        if self._capture is None and self.maybe_discard():
            recent.writer().waitForDone()   # every edit on disk first
            size = (self.normalGeometry().size() if self.isMaximized()
                    or self.isFullScreen() else self.size())
            self.settings.setValue("window/size", size)
            self.settings.setValue("window/state", self.saveState())
            self.settings.setValue(CURRENT_KEY, self.doc.path or "")
            self.hotkey.clear()
            event.accept()
        else:
            event.ignore()

    # -- window size --------------------------------------------------------
    def _screen_area(self) -> QRect:
        """The free area (without the taskbar or menu bar) of the window's
        screen, else the primary screen's."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry() if screen else QRect(0, 0, 1280, 800)

    @staticmethod
    def _cap(area: QRect) -> QSize:
        return QSize(int(area.width() * SCREEN_SHARE),
                     int(area.height() * SCREEN_SHARE))

    def _place(self, size: QSize, area: QRect) -> None:
        """Resize to `size`, capped at SCREEN_SHARE of `area` and no smaller
        than the minimum, then center the window in `area`."""
        size = size.boundedTo(self._cap(area)).expandedTo(self.minimumSize())
        self.resize(size)
        frame = self.frameGeometry()        # the title bar and borders too
        extra = frame.size() - self.geometry().size()
        box = QRect(0, 0, size.width() + extra.width(),
                    size.height() + extra.height())
        box.moveCenter(area.center())
        self.move(box.topLeft())

    def _chrome(self) -> QSize:
        """The window's size around the picture area: the toolbar rows, the
        property strip, the status line and the view's frame."""
        self.layout().setGeometry(self.rect())  # laid out at today's size
        view = self.view.geometry().size()
        frame = 2 * self.view.frameWidth()
        return QSize(self.width() - view.width() + frame,
                     self.height() - view.height() + frame)

    def fit_to_picture(self, area: QRect | None = None) -> None:
        """After a capture: size the window to show the picture at 100 %
        (capped at SCREEN_SHARE of the screen's free area; a larger picture
        is then zoomed to fit), centered."""
        area = area or self._screen_area()
        img = self.doc.base.size()
        dpr = max(1.0, self.devicePixelRatioF())
        chrome = self._chrome()
        want = QSize(round(img.width() / dpr) + chrome.width() + 4,
                     round(img.height() / dpr) + chrome.height() + 4)
        self._place(want, area)
        self.view.fit_after_resize()

    # -- capture ----------------------------------------------------------
    def capture(self) -> None:
        if self._capture is not None or not self.maybe_discard():
            return
        if not self._may_record_screen():
            return
        self.hide()
        QTimer.singleShot(CAPTURE_DELAY_MS, self._start_capture)

    def _start_capture(self) -> None:
        self._capture = CaptureSession(self)
        self._capture.finished.connect(self._capture_done)
        try:
            self._capture.start()
        except Exception as e:          # never leave the window hidden
            self._capture = None
            self._show_again()
            self._warn(f"Capture failed: {e}")

    def _capture_done(self, result) -> None:
        session, self._capture = self._capture, None
        if session is not None:
            session.deleteLater()
        self._show_again()
        if result is None:
            return
        doc, png = Document(result.image), None
        if self.keep_recent():          # its record: the PNG and, from the
            png = self.recent_store.reserve()   # first edit, the editable
            doc.path = str(recent.editable_for(png))
        self._bind(doc)
        self.fit_to_picture()
        if png is not None:             # never waits on the disk
            self.recent.file_capture(result.image, path=png)
        size = f"{result.image.width()} × {result.image.height()}"
        if self.quick_copy():           # quick capture: straight out
            QApplication.clipboard().setImage(self.doc.render_image())
            self._exported()
            self.statusBar().showMessage(f"Copied {size} — Ctrl+V to paste")
            if self.quick_minimize():
                self.showMinimized()
            return
        self.statusBar().showMessage(
            f"Captured {size}" + (f" — {result.title}" if result.title else ""),
            5000)

    def _may_record_screen(self) -> bool:
        """macOS: without the screen-recording permission macOS hands over
        only the wallpaper, so no capture is made; macOS's own prompt is
        asked for and the window says what to switch on. True elsewhere."""
        if not macos.IS_MAC or macos.screen_capture_allowed():
            return True
        macos.request_screen_capture()
        self._show_again()
        self.statusBar().showMessage(PERMISSION_STATUS)
        self._permission_message()
        return False

    def _permission_message(self) -> None:
        box = QMessageBox(QMessageBox.Information, "Annotshot",
                          PERMISSION_TEXT, QMessageBox.NoButton, self)
        settings = box.addButton("Open System Settings",
                                 QMessageBox.AcceptRole)
        box.addButton("Not now", QMessageBox.RejectRole)
        box.setDefaultButton(settings)
        box.exec()
        if box.clickedButton() is settings:
            macos.open_privacy_settings()

    def _show_again(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
