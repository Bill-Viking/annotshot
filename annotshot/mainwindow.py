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
import time
import warnings
import zipfile
import zlib
from functools import lru_cache
from pathlib import Path

import shiboken6

from PySide6.QtCore import (QBuffer, QByteArray, QDateTime, QEvent, QIODevice, QProcess, QRect, QRectF,
                            QSettings, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import (QAction, QActionGroup, QColor, QFont, QPen,
                           QFontInfo, QFontMetrics,
                           QGuiApplication, QIcon, QImage, QKeySequence, QPalette,
                           QPainter, QPixmap, QShortcut, QUndoGroup)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractSlider, QApplication, QButtonGroup,
                               QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog,
                               QFrame, QHBoxLayout, QLabel,
                               QMainWindow, QMenu, QMessageBox, QScrollArea,
                               QSizePolicy, QSlider, QSpinBox,
                               QStackedWidget, QStyle, QStyledItemDelegate,
                               QStyleOptionComboBox, QStyleOptionSpinBox, QStyleOptionViewItem,
                               QStyleOptionToolButton, QStylePainter, QToolBar,
                               QToolButton, QVBoxLayout, QWidget)

from . import feedback, hotkey, macos
from .capture import CaptureSession
from .items import HighlightItem, arrow_ink, without_alpha
from .keywords import key_words
from .office import OFFICE_FORMATS, _write_safely, export
from . import recent, theme, typefaces
from .scene import Document
from .packaged import app_data_directory, is_packaged
from .tools import Tool
from .view import EditorView, ZOOM_STEP

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
CURRENT_KEY = "recent/current"      # retained record, ignored at launch
AUTOSAVE_FAILED = "Could not keep your changes to this picture: {why}"
CLOSE_SAVE_FAILED = (
    "Your last changes to this picture could not be kept ({why}).\n\n"
    "Save a copy somewhere else, or discard those changes.")
CLOSE_SAVE_COPY = "Save a copy…"
CLOSE_DISCARD = "Discard changes"
RESTART_SAVE_FAILED = (
    "Annotshot did not restart: your changes to this picture could not be kept ({why})")
# The way back when macOS refuses an app it already lists as switched on (an
# update that is not signed by Apple keeps the old entry, which no longer
# matches): the user manual's Updating -> macOS bullet says the same words.
PERMISSION_WAY_BACK = (
    "If Annotshot is already switched on there and macOS still refuses: "
    "remove it with −, add it again with + from "
    "Applications, and switch it on.")
PERMISSION_TEXT = (
    "macOS has not yet allowed Annotshot to take pictures of your screen.\n\n"
    "This is normal the first time, and it can come back after an update. "
    "Nothing is broken.\n\n"
    "Open System Settings and switch Annotshot on. macOS lists it under "
    '"Screen & System Audio Recording": that is macOS\'s own name for the setting. '
    "Annotshot takes still pictures only, never video or sound. "
    "Annotshot then restarts by itself.\n\n"
    + PERMISSION_WAY_BACK)
PERMISSION_STATUS = "Capture is waiting for macOS to allow it"
PERMISSION_ON = "macOS now allows capture"
PERMISSION_RESTART = "macOS now allows capture. Annotshot needs to restart to use it."
PERMISSION_FIX = (
    'To fix it: open System Settings, find Annotshot under "Screen & System Audio Recording", '
    "remove it with −, add it again with + from Applications, and switch it on.")
RESTART_STILL_REFUSED = (
    "macOS shows Annotshot switched on but still refuses it. "
    "This can happen after an update. Nothing is broken.\n\n"
    + PERMISSION_FIX)
# The window: it opens centered at a moderate size (never maximized), at
# most SCREEN_SHARE of the screen's free area, never smaller than MIN_SIZE
# (logical px). After a capture it grows to the picture at 100 %.
START_SIZE = QSize(1100, 720)
MIN_SIZE = QSize(900, 600)
SCREEN_SHARE = 0.8
# Buttons that show only their icon (the tooltip names them).
ICON_ONLY = ("Undo", "Redo", "Settings…")
# The shortcuts the user may set: (settings key, the name the page shows).
# The tools' keys are their names in lower case. Saved as shortcuts/<key>.
SHORTCUT_ROWS = (
    ("capture", "Capture"), ("open", "Open…"), ("save", "Save…"),
    ("copy", "Copy image"), ("clear", "Close picture"), ("undo", "Undo"),
    ("redo", "Redo"), *((t.name.lower(), t.value) for t in Tool),
    ("duplicate", "Duplicate"), ("front", "Front"), ("back", "Back"),
    ("delete", "Delete"), ("fit", "Fit"), ("zoom100", "100 %"),
    ("zoom200", "200 %"), ("zoom_in", "Zoom in"), ("zoom_out", "Zoom out"),
    ("settings", "Settings…"), ("help", "Help"))
TOOL_KEYS = dict(zip(Tool, ("V", "T", "B", "R", "E", "A", "H", "P", "C")))
KIND_WORDS = {
    "text": ("text", "text objects"), "callout": ("callout", "callouts"),
    "rect": ("rectangle", "rectangles"), "ellipse": ("ellipse", "ellipses"),
    "arrow": ("arrow", "arrows"), "highlight": ("highlight", "highlights"),
    "pen": ("pen stroke", "pen strokes")}
TOOL_HINTS = {
    Tool.SELECT: "Click an object to change it, or pick a tool to draw.",
    Tool.CROP: "Drag a box to crop the picture; objects outside it stay editable."}
HOTKEY_NAME = "Capture from anywhere"


def default_directory() -> Path:
    """Store captures stay in the user's app data. Other builds keep Pictures."""
    if is_packaged():
        return app_data_directory() / "Captures"
    return DEFAULT_DIR


# -- icons ----------------------------------------------------------------
# The toolbar icons are monochrome line drawings in annotshot/icons/*.svg, drawn
# with the stroke ICON_INK; each state gets its own ink, rendered at several
# scales so they stay sharp at 125 / 150 / 200 %.
ICON_DIR = Path(__file__).resolve().parent / "icons"
ICON_PX = 20                      # logical px
ICON_INK = "#334454"              # the stroke the SVG files are drawn with
INK_CHECKED = "#086DBE"
INK_DISABLED = "#A7B1BB"
ICON_SCALES = (1, 1.25, 1.5, 1.75, 2, 3)
# Toolbar action text -> icon file (without .svg).
TOOLBAR_ICONS = {
    "Capture": "capture", "Open…": "open", "Save…": "save",
    "Copy image": "copy-image", "Close picture": "clear-picture", "Undo": "undo",
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
ARROW_HEADS = (("filled", "Filled"), ("open", "Open"), ("none", "None"),
               ("bar", "Bar"))
HEAD_SIZE_NAMES = (("small", "Small"), ("medium", "Medium"),
                   ("large", "Large"))
LINE_STYLE_NAMES = (("solid", "Solid"), ("dashed", "Dashed"),
                    ("long_dash", "Long dash"), ("dotted", "Dotted"),
                    ("dash_dot", "Dash-dot"))


def _paint_choice_sample(p, rect, color, kind, value):
    """A 56 × 16 logical-pixel sample using production ink at w = 2."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(rect.left() + 2, rect.top() + 8)
    p.fillPath(arrow_ink(52, 2, value if kind == "line" else "solid",
                         value if kind == "head" else "none"), color)
    p.restore()


class _MarkChoiceDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width() + 56 + 8, max(size.height(), 16 + 4))

    def paint(self, p, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, p, opt.widget)
        role = QPalette.HighlightedText if opt.state & QStyle.State_Selected \
            else QPalette.Text
        color = opt.palette.color(role)
        sample = QRectF(opt.rect.left() + 6, opt.rect.center().y() - 8, 56, 16)
        _paint_choice_sample(p, sample, color, self.parent().sample_kind,
                             index.data(Qt.UserRole))
        p.save()
        p.setFont(opt.font)
        p.setPen(color)
        name_rect = opt.rect.adjusted(6 + 56 + 8, 0, -6, 0)
        p.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, text)
        p.restore()


class PropertyChoice(QComboBox):
    """Qt owns search; a real activation completes its focus transfer now."""
    mouseCommitted = Signal()
    popupOpened = Signal()
    popupFinished = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mouse_release_row = None
        self._popup_open = False
        self._key_accept = False
        self._escape_cancel = False
        self._popup_origin = None
        self.view().installEventFilter(self)
        self.view().viewport().installEventFilter(self)
        self.activated.connect(self._choice_activated)

    def showPopup(self):
        self._mouse_release_row = None
        self._key_accept = self._escape_cancel = False
        self._popup_origin = QApplication.focusWidget()
        self._popup_open = True
        self.popupOpened.emit()
        super().showPopup()
        # Escape can close this container without calling hidePopup().
        self.view().window().installEventFilter(self)

    def hidePopup(self):
        super().hidePopup()
        self._popup_hidden()

    def _popup_hidden(self):
        accepting = self._mouse_release_row is not None or self._key_accept
        if self._popup_open and not accepting:
            origin, resume = self._popup_origin, self._escape_cancel
            self._popup_origin = self._mouse_release_row = None
            self._popup_open = self._key_accept = self._escape_cancel = False
            # Escape returns to its origin in this delivery. A different
            # destination or an outside dismissal never earns a hand-back.
            if (resume and origin is not None and shiboken6.isValid(origin)
                    and QApplication.focusWidget() in (None, self, self.view())):
                origin.setFocus(Qt.PopupFocusReason)
            self.popupFinished.emit(resume)

    def event(self, event):
        if event.type() == QEvent.KeyPress:
            self._mouse_release_row = None
        if (event.type() == QEvent.ShortcutOverride and not self.isEditable()
                and not event.modifiers() & (Qt.ControlModifier
                                             | Qt.AltModifier | Qt.MetaModifier)
                and event.text() and event.text().isprintable()):
            event.accept()
            return True  # ordinary KeyPress still runs Qt's search once
        return super().event(event)

    def eventFilter(self, watched, event):
        # Escape may hide Qt's popup container directly rather than call
        # hidePopup(). HideToParent runs after its native focus restoration.
        if watched is self.view().window() and event.type() == QEvent.HideToParent:
            self._popup_hidden()
        if watched in (self.view(), self.view().viewport()):
            if event.type() in (QEvent.ShortcutOverride, QEvent.KeyPress,
                                QEvent.MouseButtonPress):
                # Qt may complete Return inside its own KeyPress filter.
                # ShortcutOverride identifies that command; the ordinary
                # key still goes through Qt once, with no replay/search here.
                self._mouse_release_row = None
                self._key_accept = (event.type() in (QEvent.ShortcutOverride, QEvent.KeyPress)
                                    and event.key() in (Qt.Key_Return, Qt.Key_Enter))
                self._escape_cancel = (event.type() in (QEvent.ShortcutOverride, QEvent.KeyPress)
                                       and event.key() == Qt.Key_Escape)
            if (event.type() == QEvent.MouseButtonRelease
                    and event.button() == Qt.LeftButton):
                index = self.view().indexAt(event.position().toPoint())
                if (index.isValid() and index.flags() & Qt.ItemIsEnabled
                        and index.flags() & Qt.ItemIsSelectable):
                    self._mouse_release_row = index.row()
        return super().eventFilter(watched, event)

    def _choice_activated(self, row):
        # ASSUMES: only Qt's activation of the released row confirms a
        # mouse choice, including a re-pick. Transfer synchronously: any
        # later focus destination wins, even inside the next activated slot.
        mouse = row == self._mouse_release_row
        was_open = self._popup_open
        self._mouse_release_row = self._popup_origin = None
        self._popup_open = self._key_accept = self._escape_cancel = False
        if mouse:
            self.mouseCommitted.emit()
        elif was_open and not self.isEditable():
            self.setFocus(Qt.PopupFocusReason)
        if was_open:
            self.popupFinished.emit(True)


class MarkChoice(PropertyChoice):
    """Stock choice data/navigation; roomy popup, original closed width."""
    def __init__(self, kind, original, parent=None):
        super().__init__(parent)
        self.sample_kind = kind
        self._original = original
        self._closed_width = 0
        self.setItemDelegate(_MarkChoiceDelegate(self))
        self.currentIndexChanged.connect(self._describe_choice)

    def _describe_choice(self, *_):
        text = self.currentText()
        title = "Line style" if self.sample_kind == "line" else "Arrow head"
        self.setToolTip(f"{title}: {text}")
        self.setAccessibleDescription(text)

    def remeasure(self):
        # Stock QComboBox measures the text bounds, then asks the active
        # style for its frame/arrow allowance. Measure only the original
        # entries; popup samples and new names get no strip space.
        fm = self.fontMetrics()
        contents = QSize(max(fm.boundingRect(name).width()
                             for _, name in self._original), fm.height() + 2)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        self._closed_width = self.style().sizeFromContents(
            QStyle.CT_ComboBox, opt, contents, self).width()
        self.setFixedWidth(self._closed_width)
        self.updateGeometry()

    def sizeHint(self):
        size = super().sizeHint()
        if self._closed_width:
            size.setWidth(self._closed_width)
        return size

    def minimumSizeHint(self):
        return self.sizeHint()

    def changeEvent(self, event):
        super().changeEvent(event)
        if (event.type() in (QEvent.FontChange, QEvent.StyleChange)
                and hasattr(self, "_original")):
            self.remeasure()

    def showPopup(self):
        opt = QStyleOptionViewItem()
        opt.initFrom(self)
        opt.font = self.font()
        width = max(self.itemDelegate().sizeHint(opt, self.model().index(i, 0)).width()
                    for i in range(self.count()))
        self.view().setMinimumWidth(width + 12)
        super().showPopup()

    def paintEvent(self, event):
        if self.sample_kind != "line":
            return super().paintEvent(event)
        p = QStylePainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        opt.currentText = ""
        p.drawComplexControl(QStyle.CC_ComboBox, opt)
        p.drawControl(QStyle.CE_ComboBoxLabel, opt)
        edit = self.style().subControlRect(QStyle.CC_ComboBox, opt,
                                          QStyle.SC_ComboBoxEditField, self)
        p.setClipRect(edit)
        _paint_choice_sample(p, QRectF(edit.center().x() - 28,
                                      edit.center().y() - 8, 56, 16),
                             opt.palette.color(QPalette.ButtonText),
                             "line", self.currentData())
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


class FontBox(PropertyChoice):
    """The Font box: the fonts Annotshot carries first (the VT323 pixel
    font, "Pixel font (bundled)"), a separator, then this system's families;
    each name is shown in its own face. Speaks QFontComboBox's words
    (currentFontChanged, setCurrentFont, currentFont)."""

    currentFontChanged = Signal(QFont)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        # The arrow is a choice, while the entry remains a click/Tab target.
        self.setFocusPolicy(Qt.TabFocus)
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
            self.bundled = [f for f in typefaces.load_bundled()
                            if not f.startswith(".")]
            for family in self.bundled:
                self.addItem(family)
                i = self.count() - 1
                self.setItemData(i, typefaces.tooltip(family), Qt.ToolTipRole)
            if self.bundled:
                self.insertSeparator(self.count())
            for family in typefaces.public_families():
                if family in self.bundled:
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
        if font.family().strip().startswith("."):
            font = QFont(typefaces.text_family())
        i = self.findText(font.family(), Qt.MatchFixedString)
        if i < 0:
            i = self.findText(QFontInfo(font).family(), Qt.MatchFixedString)
        if i >= 0:
            self.setCurrentIndex(i)
        else:                   # no row: so picking any row is a change
            self.setCurrentIndex(-1)
            self.setEditText(font.family())

    def currentFont(self) -> QFont:  # noqa: N802 - Qt's name
        family = self.currentText()
        return QFont(typefaces.text_family() if family.strip().startswith(".") else family)


class _ReadableRecentStore(recent.RecentStore):
    def files(self):
        # ASSUMES: Recent is readable. An unavailable store still permits launch.
        try:
            return super().files()
        except Exception:
            return []


class _BarButton(QToolButton):
    """A tool's persistent mark and keyboard focus are separate cues."""

    def paintEvent(self, event):
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.state &= ~QStyle.State_HasFocus
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.CC_ToolButton, option)
        if self.isChecked():
            painter.fillRect((self.width() - 12) // 2, self.height() - 5,
                             12, 2, theme.color("checked-text"))
        if self.hasFocus():
            # Separate inset dotted focus, inside every measured button.
            ink = "checked-text" if self.isChecked() else "button-text"
            painter.setPen(QPen(theme.color(ink), 1, Qt.DotLine))
            painter.drawRect(self.rect().adjusted(3, 3, -4, -4))


class _BarContents(QWidget):
    def __init__(self, bar):
        super().__init__(bar)
        self.bar = bar
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def sizeHint(self):
        # QMainWindow must allocate the screen's width, never a single-line
        # action sum as a minimum. FitBar owns the measured height instead.
        return QSize(1, 1)

    def minimumSizeHint(self):
        return QSize(1, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.bar.fit(event.size().width())


class FitBar(QToolBar):
    """Ordered action buttons: shed labels, collapse the gap, then wrap.

    A single toolbar widget owns the complete flow. Qt's native toolbar
    layout therefore never moves an action into an overflow menu. Actions
    remain shared with the window, shortcuts and menus.
    """

    def __init__(self, *args, **kwargs):
        self._levels = []
        self._level = 0
        self._icon_only = frozenset()
        self._needs = None
        self._fit_width = None
        self._fitting = False
        self._entries = {}
        self._line_height = 1
        self._bar_height = 1
        super().__init__(*args, **kwargs)
        self._contents = _BarContents(self)
        super().addWidget(self._contents)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def addAction(self, action):  # noqa: N802 - QToolBar's public surface
        button = _BarButton(self._contents)
        button.setDefaultAction(action)
        button.setIconSize(self.iconSize())
        button.setToolButtonStyle(self.toolButtonStyle())
        button.setFocusPolicy(Qt.StrongFocus)
        button.setAccessibleName(action.text())
        # Toolbar clicks keep a live caret until the chosen action handles it.
        # Tab still takes keyboard focus (and draws its own dotted perimeter).
        button.setFocusPolicy(Qt.TabFocus)
        self._entries[action] = button
        button.show()

    def addWidget(self, widget):  # noqa: N802
        action = QAction(self)
        widget.setParent(self._contents)
        self._entries[action] = widget
        return action

    def addSeparator(self):  # noqa: N802
        action = QAction(self)
        action.setSeparator(True)
        line = QFrame(self._contents)
        line.setObjectName("barDivider")
        self._entries[action] = line
        return action

    def actions(self):
        return list(self._entries)

    def widgetForAction(self, action):  # noqa: N802
        return self._entries.get(action)

    def sizeHint(self):  # noqa: N802
        if not self._levels:
            return super().sizeHint()
        width = min(self.needs()[self._level], self._fit_width or self.needs()[0])
        return QSize(width, self._bar_height)

    def minimumSizeHint(self):  # noqa: N802
        return QSize(1, self._bar_height)

    def set_levels(self, levels: list[frozenset[QAction]]) -> None:
        self._levels = levels
        self._needs = None
        self._apply_level(0)

    def _apply_level(self, level: int) -> None:
        icon_only = self._levels[level]
        for action in self._icon_only ^ icon_only:
            button = self.widgetForAction(action)
            compact = action in icon_only
            button.setProperty("iconOnly", compact)
            button.style().unpolish(button)
            button.style().polish(button)
            button.setToolButtonStyle(
                Qt.ToolButtonIconOnly if compact else Qt.ToolButtonTextBesideIcon)
            button.updateGeometry()
        self._icon_only = icon_only
        self._level = level

    def needs(self) -> tuple[int, ...]:
        if self._needs is None:
            current = self._level
            updates = self.updatesEnabled()
            self.setUpdatesEnabled(False)
            try:
                measured = []
                for level in range(len(self._levels)):
                    self._apply_level(level)
                    sizes = self._sizes()
                    measured.append(self._single_need(sizes))
                self._needs = tuple(measured)
            finally:
                self._apply_level(current)
                self.layout().invalidate()
                self.setUpdatesEnabled(updates)
        return self._needs

    def compact_need(self) -> int:
        return self.needs()[-1]

    def level(self) -> int:
        return self._level

    def _spacing(self):
        return 4 if self.objectName() == "main" else 2

    def _single_need(self, sizes):
        return (16 + sum(s.width() for s in sizes.values())
                + self._spacing() * max(0, len(sizes) - 1)
                + (9 if any(a.isSeparator() for a in self._entries) else 0))

    def _sizes(self):
        # ASSUMES: disabled controls have the same geometry as enabled ones.
        # Reserve the enabled style option without changing action state,
        # emitting signals or temporarily authorizing a shortcut.
        sizes = {}
        for action, widget in self._entries.items():
            if not action.text():
                continue
            option = QStyleOptionToolButton()
            widget.initStyleOption(option)
            option.state |= QStyle.State_Enabled
            size = widget.sizeHint()
            enabled = widget.style().sizeFromContents(QStyle.CT_ToolButton,
                                                       option, QSize(), widget)
            sizes[action] = size.expandedTo(enabled)
        return sizes

    def _flow(self, width):
        sizes = self._sizes()
        gap = self._spacing()
        available = max(1, width - 16)
        lines, line, used = [], [], 0
        for action, size in sizes.items():
            need = size.width() + (gap if line else 0)
            if line and used + need > available:
                lines.append(line)
                line, used = [], 0
            line.append(action)
            used += size.width() + (gap if len(line) > 1 else 0)
        if line:
            lines.append(line)
        row_height = max(self._line_height, max(s.height() for s in sizes.values()) + 8)
        # Stretch only on a single line. On wrapped bars the spacer and
        # divider collapse together, preserving strict action reading order.
        single = len(lines) == 1
        spread = single and self._single_need(sizes) <= width
        spacer = next((a for a, w in self._entries.items()
                       if w.objectName() == "spacer"), None)
        before_gap = list(self._entries).index(spacer) if spacer is not None else -1
        stretch = max(0, width - self._single_need(sizes)) if spread else 0
        divider = next((w for a, w in self._entries.items() if a.isSeparator()), None)
        if divider is not None:
            divider.hide()
        passed_gap = False
        for row, actions in enumerate(lines):
            x = 8
            for action in actions:
                if spread and not passed_gap and list(self._entries).index(action) > before_gap:
                    passed_gap = True
                    x += stretch
                    stretch = 0
                    if divider is not None:
                        divider.setGeometry(x + 4, 11, 1, max(1, row_height - 22))
                        divider.show()
                        x += 9
                widget, size = self._entries[action], sizes[action]
                widget.setGeometry(x, row * row_height + (row_height - size.height()) // 2,
                                   size.width(), size.height())
                widget.setVisible(action.isVisible())
                x += size.width() + gap
        for action, widget in self._entries.items():
            if not action.text() and not action.isSeparator():
                # Retain the toolbar's named spacer as a visible, empty
                # widget for callers inspecting the action list. Its gap
                # is laid out above and collapses entirely on wrapped rows.
                widget.setGeometry(8, 0, 1, 1)
                widget.show()
        height = max(1, len(lines)) * row_height + 1
        self._bar_height = height
        if self.height() != height:
            self.setFixedHeight(height)
            self.updateGeometry()

    def fit(self, width: int) -> None:
        if self._fitting or not self._levels:
            return
        self._fitting = True
        try:
            self._fit_width = width
            needs = self.needs()
            level = next((i for i, need in enumerate(needs) if need <= width),
                         len(needs) - 1)
            if level != self._level:
                self._apply_level(level)
            # Polishing a newly shown control can settle its font after
            # the first measure. Never use an earlier sum to place it.
            if self._single_need(self._sizes()) != needs[level]:
                self._needs = None
                needs = self.needs()
                level = next((i for i, need in enumerate(needs) if need <= width),
                             len(needs) - 1)
                self._apply_level(level)
            self._flow(width)
        finally:
            self._fitting = False

    def resizeEvent(self, event):  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        self.fit(event.size().width())

    def remeasure(self) -> None:
        self._needs = None
        if self._fit_width is not None:
            self.fit(self._fit_width)

    def changeEvent(self, event):  # noqa: N802 - Qt's name
        if event.type() in (QEvent.StyleChange, QEvent.FontChange):
            self._needs = None
            if hasattr(self, "_contents"):
                QTimer.singleShot(0, self.remeasure)
        super().changeEvent(event)


class MainWindow(QMainWindow):
    keyStateChanged = Signal()
    captureCountChanged = Signal()
    def __init__(self, *, permission_restart=False):
        super().__init__()
        self.settings = QSettings("Annotshot", "Annotshot")
        # Read before _bind/configure_background and the controls write any
        # defaults. Existing settings or entries mean ordinary Welcome.
        self._first_welcome_eligible = recent.fresh_profile(
            self.settings, default_directory() / RECENT_SUBDIR)
        self._first_welcome_visible = False
        self._pending_edits = {}
        self._edit_jobs = {}
        self.undo_group = QUndoGroup(self)
        self.doc = Document()
        self._bound: Document | None = None
        self._capture: CaptureSession | None = None
        self._capture_pending = False
        self._capture_was_visible = True
        self._quitting = False
        self.tray = None
        self._permission_restarted = permission_restart
        self._permission_process = None
        self._permission_callback = None
        self._permission_expired = False
        self._permission_deadline = 0.0
        self._permission_stale = False
        self._restart_pending = False
        self._restart_save = None
        self._save_jobs = set()         # document, change count, path awaiting an outcome
        self._restart_dialog = False
        self._permission_box = None
        self._permission_watch = QTimer(self)
        self._permission_watch.setInterval(3000)
        self._permission_watch.timeout.connect(self._permission_tick)
        self._permission_timeout = QTimer(self)
        self._permission_timeout.setSingleShot(True)
        self._permission_timeout.setInterval(5000)
        self._permission_timeout.timeout.connect(self._permission_check_timeout)
        QApplication.instance().aboutToQuit.connect(self._permission_quitting)
        QApplication.instance().applicationStateChanged.connect(self._permission_active)
        self.state_name = "welcome"
        # One open at a time: Open…, open_path and macOS's FileOpen events
        # share this flag; a file that arrives meanwhile is kept (the newest
        # wins) and opens when the running open returns.
        self._opening = False
        self._kept: str | None = None
        self._slider_session = 0
        self._refreshing = False
        self._marks: dict = {}          # the heading's kind marks
        self.view = EditorView(self.doc, self, settings=self.settings)
        self.pages = QStackedWidget(self)
        self.pages.addWidget(self.view)
        self.setCentralWidget(self.pages)
        self._build_actions()
        self._apply_saved_shortcuts()
        self.hotkey = hotkey.GlobalHotkey(self)
        self._key_ready = False
        self._key_feedback = ""
        self._key_edit_error = ""
        self._key_edit_qualified = False
        self._key_line = ""
        self._key_green = False
        self._key_epoch = 0
        self._key_try = None
        self._key_restoring = False
        self.key_clock = hotkey.KeyClock()
        self.hotkey.event_epoch = lambda: self._key_epoch
        self.hotkey.native_event.connect(self._native_capture_key)
        self._build_toolbar()
        self._build_props_bar()
        self.view.toolChanged.connect(self.refresh_props)
        self.view.toolChanged.connect(
            lambda: self.tool_actions[self.view.tool].setChecked(True))
        self.zoom_label, self.size_label = QToolButton(), QLabel()
        self.zoom_label.setObjectName("zoomButton")
        self.zoom_label.setToolTip("Zoom")
        self.zoom_label.setPopupMode(QToolButton.InstantPopup)
        zoom_menu = QMenu(self.zoom_label)
        for action in (self.a_fit, self.a_zoom100, self.a_zoom200,
                       self.a_zoom_in, self.a_zoom_out):
            zoom_menu.addAction(action)
        self.zoom_label.setMenu(zoom_menu)
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
        from .welcome import WelcomeWidget
        self.welcome = WelcomeWidget(self)
        self.pages.addWidget(self.welcome)
        self._welcome_keys = []
        for key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(lambda: self.capture())
            self._welcome_keys.append(shortcut)
        self._editor_state = self.saveState()
        self._bind(self.doc)
        self.show_welcome()
        bar.showMessage(self.capture_status(), 8000)
        self._remembering = True
        self.configure_background()
        if permission_restart and macos.IS_MAC and macos.screen_capture_state() == "allowed":
            bar.showMessage(PERMISSION_ON)

    def _save_editor_geometry(self):
        if self.state_name == "editor":
            size = (self.normalGeometry().size() if self.isMaximized()
                    or self.isFullScreen() else self.size())
            self._editor_state = self.saveState()
            try:
                self.settings.setValue("window/size", size)
                self.settings.setValue("window/state", self._editor_state)
                self.settings.setValue('recent/edge-v1', recent.EDGE_NAMES.get(
                    self.recent.last_edge, 'right'))
                self.settings.setValue('recent/direction-v1', self.recent.direction)
                self.settings.sync()
                if self.settings.status() != self.settings.Status.NoError:
                    raise OSError('settings could not be saved')
            except (OSError, RuntimeError) as error:
                self.statusBar().showMessage(f'Could not remember Recent placement: {error}', 6000)

    def _picture_actions(self, enabled):
        for shortcut in self._welcome_keys:
            shortcut.setEnabled(not enabled)
        for action in (self.a_save, self.a_copy, self.a_clear, self.a_dup,
                       self.a_front, self.a_back, self.a_delete, self.a_fit,
                       self.a_zoom100, self.a_zoom200, self.a_zoom_in,
                       self.a_zoom_out, *self.tool_actions.values()):
            action.setEnabled(enabled)
        self._selection_actions()
        if not enabled:
            self.a_undo.setEnabled(False)
            self.a_redo.setEnabled(False)

    def show_welcome(self):
        self._save_editor_geometry()
        self.state_name = "welcome"
        self.recent.set_document_path(None)
        self.pages.setCurrentWidget(self.welcome)
        for toolbar in self.findChildren(QToolBar):
            toolbar.hide()
        self.recent.hide()
        self.statusBar().hide()
        self._picture_actions(False)
        self.welcome.refresh()
        area = self._screen_area()
        if self.isMaximized() or self.isFullScreen():
            was_visible = self.isVisible()
            self.showNormal()
            if not was_visible:
                self.hide()
        self.setFixedSize(640, 430)
        frame = self.frameGeometry()
        frame.moveCenter(area.center())
        self.move(frame.topLeft())
        # Account for native frame margins and integer rounding on screens
        # whose logical origin is negative.
        self.move(self.pos() + area.center() - self.frameGeometry().center())
        self.welcome.setFocus()

    def show_editor(self):
        if self.state_name == "editor":
            return
        self._leave_first_welcome()
        self.state_name = "editor"
        area = self._screen_area()
        self.setMaximumSize(QSize(16777215, 16777215))
        self._apply_floor(area)
        self.pages.setCurrentWidget(self.view)
        self.restoreState(self._editor_state)
        for toolbar in self.findChildren(QToolBar):
            toolbar.show()
        self.statusBar().show()
        saved = self.settings.value("window/size", START_SIZE, type=QSize)
        self._place(saved if saved.isValid() else START_SIZE, area)
        self._restore_recent_layout()
        self._picture_actions(True)
        self._sync_undo()
        self.view.setFocus()

    def _apply_floor(self, area: QRect) -> None:
        floor = MIN_SIZE.boundedTo(self._cap(area))
        self.setMinimumSize(floor)

    # -- building ---------------------------------------------------------
    def _build_recent(self) -> None:
        """The Recent captures pane: docked on the right the first time,
        then where the user left it (docked left or right, floating, or
        closed), restored from the saved window state."""
        self.recent_store = _ReadableRecentStore(
            lambda: default_directory() / RECENT_SUBDIR,
            keep=self.capture_count() or 0)
        self.recent = recent.RecentPane(self.recent_store, self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.recent)
        self.recent.openRequested.connect(self._open_recent_request)
        self.recent.saveRequested.connect(self.save_recent)
        self.recent.filingFailed.connect(self._filing_failed)
        self.recent.deleted.connect(self._recent_deleted)
        self.recent._filer.filed.connect(self._refresh_welcome_recent)
        self.recent.list.canvasRequested.connect(self._focus_canvas)
        self.recent.redockRequested.connect(self._redock_recent)
        self.recent.filingFinished.connect(self._recent_filed)
        self.a_recent = self._act(recent.TITLE, self._reveal_recent,
                                  tip="Show Recent captures")
        edge = self.settings.value('recent/edge-v1', 'right')
        self.recent.last_edge = next((e for e, n in recent.EDGE_NAMES.items()
                                     if n == edge), Qt.RightDockWidgetArea)
        direction = self.settings.value('recent/direction-v1', 'vertical')
        state = self.settings.value("window/state", QByteArray(),
                                    type=QByteArray)
        restored = state is not None and not state.isEmpty() and self.restoreState(state)
        if not restored:
            self.recent.setFloating(False)
            self.addDockWidget(Qt.RightDockWidgetArea, self.recent)
            self.recent.show()
        if self.recent.isFloating():
            self.recent.set_direction(direction)
            self.recent._float_direction(self.recent.size())
        else:
            self.recent._dock_location(self.dockWidgetArea(self.recent))

    def _restore_recent_layout(self):
        if self.recent.isFloating():
            direction = self.settings.value('recent/direction-v1', self.recent.direction)
            self.recent.set_direction(direction)
            self.recent._float_direction(self.recent.size())
            if not self._recent_placement_valid():
                self._redock_recent()
        else:
            self.recent._dock_location(self.dockWidgetArea(self.recent))
        self.recent.set_document_path(self.doc.path)

    def _redock_recent(self):
        """Recover the existing dock, visibly, and remember the recovery."""
        pane = self.recent
        edge = pane.last_edge if pane.last_edge in recent.DOCK_EDGES else Qt.RightDockWidgetArea
        pane.setFloating(False)
        self.addDockWidget(edge, pane)
        pane.show()
        pane._dock_location(edge)
        self._save_editor_geometry()

    def _recent_screen_areas(self):
        return [screen.availableGeometry() for screen in QGuiApplication.screens()]

    def _recent_visible_rects(self):
        """Visible title and client, in logical desktop coordinates.

        Native frame margins include invisible resize borders. Their lower
        inset is excluded from the title's top inset; shadows never enter
        either rectangle. A platform without a provable title fails closed
        to the visible dock (including restricted Wayland placement).
        """
        if QGuiApplication.platformName().lower().startswith('wayland'):
            return None
        pane = self.recent
        handle = pane.windowHandle()
        if handle is None:
            return None
        margins = handle.frameMargins()
        title_height = margins.top() - margins.bottom()
        if title_height <= 0:
            return None
        client = QRect(pane.mapToGlobal(pane.rect().topLeft()), pane.size())
        title = QRect(client.left(), client.top() - title_height,
                      client.width(), title_height)
        return title, client

    def _recent_placement_valid(self):
        rects = self._recent_visible_rects()
        if rects is None or any(not r.isValid() for r in rects):
            return False
        return any(all(area.contains(r) for r in rects)
                   for area in self._recent_screen_areas())

    def _raise_recent(self):
        """Request native activation; verify its asynchronous result next."""
        self.recent.showNormal()
        self.recent.raise_()
        self.recent.activateWindow()
        return None

    def _reveal_recent(self):
        if self.state_name != 'editor':
            return
        pane = self.recent
        if pane.isFloating():
            if not self._recent_placement_valid():
                self._redock_recent()
            else:
                raised = self._raise_recent()
                if raised is None:
                    QTimer.singleShot(100, self, self._recent_raise_finished)
                    return
                if not raised:
                    self._redock_recent()
        pane.show()
        if not pane.isFloating():
            self.activateWindow()
        pane.list.setFocus(Qt.ShortcutFocusReason)

    def _recent_raise_finished(self):
        if self.state_name != 'editor' or self._quitting:
            return
        if self.recent.isFloating() and (not self._recent_placement_valid()
                                        or not self.recent.isActiveWindow()):
            self._redock_recent()
        self.recent.show()
        if not self.recent.isFloating():
            self.activateWindow()
        self.recent.list.setFocus(Qt.ShortcutFocusReason)

    def _focus_canvas(self):
        if self.state_name == 'editor':
            self.raise_()
            self.activateWindow()
            self.view.setFocus(Qt.ShortcutFocusReason)

    def _recent_filed(self, *_):
        # A successful stage-3 rotation can expire an unedited open picture.
        # Detach only actual absence; filtered membership says nothing about
        # ownership, and an accepted capture may still be awaiting its filer.
        source = getattr(self.doc, '_recent_source', None)
        if self.is_recent_doc() and getattr(source, 'capture', None) is None:
            try:
                png, editable = self.recent_store.companions(self.doc.path)
                if not png.is_file() and not editable.is_file():
                    self.doc.path = None
                    self.update_title()
            except OSError:
                pass  # Unprovable absence never detaches a pending edit.

    def _refresh_welcome_recent(self, *_):
        if hasattr(self, "welcome") and self.state_name == "welcome":
            self.welcome.refresh_recent()

    def keep_recent(self) -> bool:
        return bool(self.capture_count())

    def capture_count(self):
        return recent.read_count(self.settings)

    def set_capture_count(self, number):
        recent.write_count(self.settings, number)
        for window in QApplication.topLevelWidgets():
            if (isinstance(window, MainWindow)
                    and window.settings.fileName() == self.settings.fileName()):
                window.recent_store.keep = number
                window.captureCountChanged.emit()

    def _commit_capture_counts(self):
        for control in self.findChildren(recent.CaptureCountControl):
            control.commit()

    def _leave_first_welcome(self):
        if self._first_welcome_eligible and self._first_welcome_visible:
            self.settings.setValue(recent.FIRST_WELCOME, True)
            self.settings.sync()
            self._first_welcome_eligible = False
            self.welcome.count_control.hide()

    def _open_recent_request(self, path: str) -> None:
        # The pane scopes this to the actual thumbnail request. A failed
        # open, list search or programmatic refresh cannot hand off focus.
        thumbnail = self.recent.opening_thumbnail
        if self.open_recent(path) and thumbnail:
            self._focus_canvas()

    def open_recent(self, path: str, quiet: bool = False) -> bool:
        """Open a kept capture as the current picture, with its edits: its
        `.annotshot` when there is one, else the PNG (unedited). The
        current picture's edits are kept first. A capture gone from the
        folder only drops from the pane."""
        if self.state_name == 'editor' and self.recent.is_document_path(path):
            return True  # continue the live scene, including its caret and undo
        self.end_key_interaction()
        if self._capture is not None or self._opening:
            return False
        try:
            png, editable = self.recent_store.companions(path)
            if not png.is_file() and not editable.is_file():
                raise FileNotFoundError('That capture is no longer in the Recent folder')
        except OSError as error:
            message = ('That capture is no longer in the Recent folder'
                       if isinstance(error, FileNotFoundError) else str(error))
            self.statusBar().showMessage(message, 6000)
            self.recent.refresh()
            return False
        if not self.maybe_discard():
            return False
        recent.writer().waitForDone()   # its own last edit, on its way
        try:
            doc = recent.load_edit(path)
        except OSError as error:
            self.statusBar().showMessage(str(error), 6000)
            self.recent.refresh()
            return False
        png = recent.png_for(path)
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
        if not self.doc.path and getattr(self.doc, '_recent_retry_path', None):
            # A failed initial claim detached the scene. A later edit may
            # retry only against the exact surviving source, under a claim.
            self._protect_recent_edit(self.doc)
        if self.doc.path:
            if self.is_recent_doc() and not self._protect_recent_edit(self.doc):
                return
            self._autosave_timer.start()

    def _protect_recent_edit(self, doc):
        if doc in self._pending_edits:
            return True
        path = doc.path or getattr(doc, '_recent_retry_path', None)
        try:
            if not hasattr(doc, '_recent_source'):
                doc._recent_source = recent.edit_source(path)
            hold = recent.pending_edit(path, doc._recent_source)
        except OSError as error:
            if isinstance(error, recent.RecentConflict):
                self._detach_recent_conflict(doc, path, str(error))
                return False
            # Keep the scene and its undo history. It cannot safely autosave
            # against a path expiry owns, removed, or could not protect.
            doc._recent_retry_path = path
            doc.path = None
            self._autosave_timer.stop()
            self.statusBar().showMessage(AUTOSAVE_FAILED.format(why=str(error)), 10000)
            self.update_title()
            return False
        doc.path = str(path)
        doc._recent_retry_path = None
        self._pending_edits[doc] = [hold]
        if hold.marker is None:
            self.statusBar().showMessage(AUTOSAVE_FAILED.format(
                why="the pending marker could not be written; the original remains protected"), 10000)
        return True

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
        if self.is_recent_doc(doc) and not self._protect_recent_edit(doc):
            return False
        markers = self._pending_edits.pop(doc, [])
        meta, base = doc.snapshot()
        gen = doc.written = doc.changes
        outcome = doc.last_write = recent.WriteOutcome(markers=tuple(markers))
        self._edit_jobs[(doc, gen, doc.path)] = markers
        self._save_jobs.add((doc, gen, doc.path))
        recent.writer().start(recent._SaveJob(
            doc, gen, doc.path, meta, base, self._saver, outcome))
        return True

    def _autosaved(self, doc, gen: int, path: str) -> None:
        """A write landed: the document is clean if nothing changed since,
        and its thumbnail shows the edit."""
        key = (doc, gen, path)
        self._save_jobs.discard(key)
        self._edit_jobs.pop(key, None)
        if (shiboken6.isValid(doc) and doc.path == path and doc.changes == gen
                and not getattr(getattr(doc, '_recent_source', None), 'conflicted', False)):
            doc.undo_stack.setClean()
        if self.recent_store.owns(path):
            self.recent.refresh_one(path)
        if self._restart_pending and self._restart_save == key:
            self._restart_save = None
            self._save_before_permission_restart()

    def _autosave_failed(self, doc, gen: int, path: str, why: str) -> None:
        """One sentence; the next change (or switch) tries again."""
        key = (doc, gen, path)
        self._save_jobs.discard(key)
        markers = self._edit_jobs.pop(key, [])
        if shiboken6.isValid(doc) and doc.path is not None and doc.path != path:
            # A separate Save As superseded this queued outcome. It must not
            # detach or dirty the newly saved document or reuse Recent holds.
            try:
                recent.finish_edits(path, markers, abandon=True)
            except OSError:
                pass
            return
        conflict = (any(h.state.conflicted for h in markers)
                    or getattr(getattr(doc, '_recent_source', None), 'conflicted', False))
        if conflict and shiboken6.isValid(doc):
            self._detach_recent_conflict(doc, path, why)
        elif markers:
            self._pending_edits.setdefault(doc, []).extend(markers)
        if shiboken6.isValid(doc) and doc.written == gen:
            doc.written = -1
        self.statusBar().showMessage(AUTOSAVE_FAILED.format(why=why), 10000)
        if self._restart_pending and self._restart_save == key:
            self._restart_pending = False
            self._restart_save = None
            self.statusBar().showMessage(RESTART_SAVE_FAILED.format(why=why))

    def _detach_recent_conflict(self, doc, path, why):
        state = getattr(doc, '_recent_source', None)
        if state is not None:
            state.conflicted = True
        holds = self._pending_edits.pop(doc, [])
        if state is not None and state.hold is not None:
            holds.append(state.hold)
        try:
            recent.finish_edits(path, holds, abandon=True)
        except OSError:
            pass  # keep another entry's protection; never clean through a link
        doc._recent_retry_path = None
        doc.path = None
        doc.written = -1
        doc.undo_stack.resetClean()
        if doc is self.doc:
            self._autosave_timer.stop()
            self.update_title()
        self.statusBar().showMessage(AUTOSAVE_FAILED.format(why=why), 10000)

    def changeEvent(self, event):       # noqa: N802 - Qt's name
        if event.type() == QEvent.ActivationChange and \
                not self.isActiveWindow():
            self.autosave_now()         # the window lost focus: keep it now
        if event.type() == QEvent.WindowStateChange and getattr(self, "_key_try", None):
            if self.isMinimized():
                self._arm_key_try()
            elif self._key_try["phase"] == "armed" and not self._key_restoring:
                self.end_key_try("Try cancelled")
        super().changeEvent(event)

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
        if a.property("selectionAction") and not a.isEnabled():
            a.setToolTip("Select an object first")
            return
        keys = a.shortcuts()
        tip = a.property("tip") or a.text()
        key = key_words(keys[0]) if keys else ""
        a.setToolTip(f"{tip} ({key})" if key else tip)

    def _build_actions(self) -> None:
        self.a_capture = self._act("Capture", lambda: self.capture(), "Ctrl+N",
                                   "Capture a region or a window")
        self.a_open = self._act("Open…", self.open_project, "Ctrl+O",
                                "Open an Annotshot editable file")
        self.a_save = self._act(
            "Save…", self.save, ["Ctrl+S", "Ctrl+Shift+S"],
            "Save a copy of this capture as a picture or an editable file",
            cls=SaveAction)
        self.a_copy = self._act("Copy image", self.copy_image, "Ctrl+C",
                                "Copy the picture to the clipboard")
        self.a_clear = self._act("Close picture", self.clear_picture, "Ctrl+W",
                                 "Close this picture; kept captures stay in Recent captures")
        self.a_undo = self._act("Undo", self.undo, "Ctrl+Z")
        self.a_redo = self._act("Redo", self.redo,
                               ["Ctrl+Shift+Z", "Ctrl+Y"] if macos.IS_MAC
                               else ["Ctrl+Y", "Ctrl+Shift+Z"])
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
            a = self._act(tool.value, lambda _=False, t=tool: self.view.pick_tool(t),
                          TOOL_KEYS[tool], checkable=True)
            # Tool picks also work from non-text Properties controls. Keep
            # the window shortcut scope; native text fields and the view's
            # live text caret claim ordinary typing via ShortcutOverride.
            group.addAction(a)
            self.tool_actions[tool] = a
        self.tool_actions[Tool.SELECT].setChecked(True)
        self.a_dup = self._act("Duplicate", self.duplicate, "Ctrl+D")
        self.a_front = self._act("Front", self.bring_to_front, "Ctrl+]",
                                 "Bring to front")
        self.a_back = self._act("Back", self.send_to_back, "Ctrl+[",
                                "Send to back")
        self.a_delete = self._act("Delete", self.delete_selected, "Delete")
        for action in (self.a_dup, self.a_front, self.a_back, self.a_delete):
            action.setProperty("selectionAction", True)
        self.view.object_actions = (self.a_dup, self.a_front, self.a_back, self.a_delete)
        self.a_escape = self._act("Deselect", self.escape, "Esc")
        self.a_fit = self._act("Fit", self.view.zoom_to_fit_or_100, "Ctrl+0")
        self.a_zoom100 = self._act("100 %", lambda: self.view.set_zoom(1), "Ctrl+1")
        self.a_zoom200 = self._act("200 %", lambda: self.view.set_zoom(2))
        self.a_zoom_in = self._act("Zoom in", lambda: self.view.set_zoom(
            self.view.zoom * ZOOM_STEP), "Ctrl+=")
        self.a_zoom_out = self._act("Zoom out", lambda: self.view.set_zoom(
            self.view.zoom / ZOOM_STEP), "Ctrl+-")
        self.a_settings = self._act("Settings…", self.open_settings, "Ctrl+,",
                                    "Settings… — shortcuts and quick capture")
        self.a_settings.setMenuRole(QAction.NoRole)
        self.a_help = self._act("Help", self.show_help, "F1",
                                "Help — the user manual and your keys")
        self.a_help.setMenuRole(QAction.NoRole)
        self._help_window = None
        self._privacy_window = None
        self._privacy_focus = None
        self.a_feedback = self._act(
            "Send feedback…", self.send_feedback,
            tip="Report a bug or suggest an improvement — opens the feedback "
                "page in your browser")
        self.a_feedback.setMenuRole(QAction.NoRole)
        self.a_about = self._act("About Annotshot…", self.show_about,
                                 tip="About Annotshot — version, publisher, "
                                     "licence")
        self.a_about.setMenuRole(QAction.NoRole)
        self.a_quit = self._act("Quit Annotshot", self.quit_app,
                                [QKeySequence(QKeySequence.Quit)])
        self.a_quit.setMenuRole(QAction.QuitRole)
        self.shortcut_actions: dict[str, QAction] = {
            "capture": self.a_capture, "open": self.a_open,
            "save": self.a_save, "copy": self.a_copy, "clear": self.a_clear,
            "undo": self.a_undo, "redo": self.a_redo,
            **{t.name.lower(): self.tool_actions[t] for t in Tool},
            "duplicate": self.a_dup, "front": self.a_front,
            "back": self.a_back, "delete": self.a_delete,
            "fit": self.a_fit, "zoom100": self.a_zoom100,
            "zoom200": self.a_zoom200, "zoom_in": self.a_zoom_in,
            "zoom_out": self.a_zoom_out,
            "settings": self.a_settings, "help": self.a_help}
        self.shortcut_names = dict(SHORTCUT_ROWS)
        self.default_shortcuts = {k: a.shortcuts()
                                  for k, a in self.shortcut_actions.items()}
        self._update_capture_hint()

    def capture_status(self) -> str:
        key = key_words(self.a_capture.shortcut())
        return f"{key} to take a screenshot" if key else "Click Capture to take a screenshot"

    def _update_capture_hint(self) -> None:
        # ASSUMES: Capture has a key. A cleared key removes the whole bracket.
        key = key_words(self.a_capture.shortcut())
        capture = f"Capture ({key})" if key else "Capture"
        self.view.empty_hint = ("No picture yet", f"Click {capture} to take a screenshot, or Open… a saved file")
        self.view.viewport().update()

    def _build_toolbar(self) -> None:
        """Capture and file actions on the left; Close picture and history
        on the right. Each row drops labels by group as it narrows, keeping
        every action visible and named by its tooltip."""
        def new_bar(title: str, name: str, height: int) -> FitBar:
            bar = FitBar(title, self)
            bar.setObjectName(name)
            bar.setMovable(False)
            bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            bar.setIconSize(QSize(ICON_PX, ICON_PX))
            bar.setMinimumHeight(height)
            bar._line_height = height
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
        for a in (self.a_capture, self.a_open, self.a_save, self.a_copy):
            bar.addAction(a)
        spacer(bar)                     # Undo, Redo keep the right edge
        bar.addSeparator()
        for a in (self.a_clear, self.a_undo, self.a_redo, self.a_settings):
            bar.addAction(a)
        bar.widgetForAction(self.a_capture).setObjectName("primary")
        bar.widgetForAction(self.a_copy).setObjectName("outline")
        bar.widgetForAction(self.a_clear).setObjectName("closePicture")
        bar.widgetForAction(self.a_settings).setObjectName("last")
        self.main_bar = bar
        base = frozenset(a for a in bar.actions() if a.text() in ICON_ONLY)
        bar.set_levels([base, base | {self.a_open, self.a_save},
                        base | {self.a_open, self.a_save, self.a_capture}])
        self.addToolBar(bar)
        bar = new_bar("Tools", "tools", 36)
        for a in self.tool_actions.values():
            bar.addAction(a)
        spacer(bar)
        for a in (self.a_dup, self.a_front, self.a_back, self.a_delete):
            bar.addAction(a)
        bar.widgetForAction(self.tool_actions[Tool.SELECT]).setObjectName("first")
        bar.widgetForAction(self.a_delete).setObjectName("last")
        self.tools_bar = bar
        objects = frozenset((self.a_dup, self.a_front, self.a_back, self.a_delete))
        bar.set_levels([frozenset(), objects,
                        objects | frozenset(self.tool_actions.values())])
        self.addToolBarBreak()
        self.addToolBar(bar)

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
                b.setIcon(themed_icon("no-color", size=14))
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
        for bar in (self.main_bar, self.tools_bar):
            bar.remeasure()
        for box in (self.cb_line, self.cb_head):
            box.remeasure()
        if self.state_name == "editor":
            self._apply_floor(self._screen_area())
        if hasattr(self, "sel_mark"):
            self._show_selection(self.doc.selected())
            self._props_reflow.start()
        self.recent.retheme()
        self.doc.update()
        self.view.viewport().update()
        if hasattr(self, "welcome"):
            self.welcome.retheme()
        if self._help_window is not None:
            self._help_window.update()
        if self._privacy_window is not None:
            self._privacy_window.update()

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
        """Two balanced rows where they fit; whole ordered rows below."""
        self._key_widgets: dict[str, list] = {}
        self._live_format = None
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
            b.setIcon(themed_icon("no-color", size=14))
            b.setIconSize(QSize(14, 14))
            b.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.s_width = self._spin(0, 40, "Border width",
                                  lambda v: set_({"border_width": v}, "Border width"))
        self.f_font = FontBox(self)
        self.f_font.setToolTip("Font")
        self.f_font.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.f_font.setMinimumContentsLength(8)
        self.f_font.setFixedWidth(180)
        self.f_font.currentFontChanged.connect(
            lambda f: set_({"font_family": f.family()}, "Font"))
        self.s_size = self._spin(6, 400, "Font size (pixels)",
                                 lambda v: set_({"font_px": v}, "Font size"))
        self.s_size.setFocusPolicy(Qt.TabFocus)
        self.s_size.lineEdit().installEventFilter(self)
        self.f_font.lineEdit().installEventFilter(self)
        self.s_size.installEventFilter(self)
        self.f_font.popupOpened.connect(lambda: self._begin_live_format(self.f_font))
        self.f_font.popupFinished.connect(
            lambda resume: self._finish_live_format(self.f_font, resume))
        QApplication.instance().focusChanged.connect(self._live_format_focus_changed)
        self.view.installEventFilter(self)
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
                                    lambda v: set_({"head": v}, "Arrow head"),
                                    sample="head", original=ARROW_HEADS[:3])
        self.cb_head_size = self._choice(
            "Arrow head size", HEAD_SIZE_NAMES,
            lambda v: set_({"head_size": v}, "Arrow head size"))
        self.cb_line = self._choice("Line style", LINE_STYLE_NAMES,
                                    lambda v: set_({"line_style": v}, "Line style"),
                                    sample="line", original=tuple(
                                        pair for pair in LINE_STYLE_NAMES
                                        if pair[0] in ("solid", "dashed", "dotted")))
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

        self.sel_mark = QLabel(self)
        self.sel_mark.setObjectName("objectMark")
        self.sel_mark.setFixedSize(21, 21)
        self.sel_mark.setAlignment(Qt.AlignCenter)
        self.sel_heading = QLabel(self)
        self.sel_heading.setObjectName("objectHeading")

        strip = QWidget(self)
        strip.setObjectName("strip")
        rows = QVBoxLayout(strip)
        rows.setContentsMargins(8, 2, 8, 2)
        rows.setSpacing(0)

        def row() -> QWidget:
            w = QWidget(strip)
            w.setFixedHeight(36)
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            h.addStretch(1)
            rows.addWidget(w)
            return w

        self.prop_row1, self.prop_row2 = row(), row()
        self._prop_rows = [self.prop_row1, self.prop_row2]
        self._prop_partition = None
        heading = self._group(None, self.sel_mark, self.sel_heading, gap=6)
        self.border_group = self._group("Border", self.c_border, self.b_noborder)
        self.border_label = self.border_group.findChild(QLabel, "fieldLabel")
        self.fill_group = self._group("Fill", self.c_fill, self.b_nofill)
        self.fill_label = self.fill_group.findChild(QLabel, "fieldLabel")
        self.line_group = self._group("Line style", self.cb_line)
        self._prop_groups = [
            (None, heading),
            ("font_family", self._group("Font", self.f_font)),
            ("font_px", self._group("Size", self.s_size)),
            ("bold", self._group(None, self._segment(self.b_bold, self.b_italic))),
            ("align", self._group("Align", self._segment(*self.align_buttons.values()))),
            ("text_color", self._group("Text colour", self.c_text)),
            ("fill_color", self.fill_group),
            ("border_color", self.border_group),
            ("border_width", self._group("Width", self.s_width)),
            ("line_style", self.line_group),
            ("head", self._group("Head", self.cb_head)),
            ("head_size", self._group("Head size", self.cb_head_size)),
            ("both_ends", self.ch_both),
            ("opacity", self._group("Opacity", self.sl_opacity, self.opacity_label, gap=6))]
        for key, group in self._prop_groups:
            self.prop_row1.layout().insertWidget(self.prop_row1.layout().count() - 1, group)
            if key:
                self._shown_with(key, group)

        scroll = QScrollArea(bar)
        scroll.setObjectName("stripScroll")
        # A scroll container is not the owner of a child's non-focus click.
        # In particular, TabFocus choices and neutral buttons keep the
        # picture's focus instead of walking up to this StrongFocus parent.
        scroll.setFocusPolicy(Qt.NoFocus)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        scroll.setWidget(strip)
        scroll.viewport().setAutoFillBackground(False)
        strip.setAutoFillBackground(False)
        # Fixed even when Select/Crop have only one instruction line.
        scroll.setFixedHeight(76)
        self.prop_strip = strip
        self.prop_scroll = scroll
        self._props_reflow = QTimer(self)
        self._props_reflow.setSingleShot(True)
        self._props_reflow.setInterval(0)
        self._props_reflow.timeout.connect(self._arrange_props)
        scroll.viewport().installEventFilter(self)
        strip.installEventFilter(self)
        for _key, group in self._prop_groups:
            group.installEventFilter(self)
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

    def _choice(self, tip: str, choices, slot, *, sample=None, original=()) -> QComboBox:
        """A pull-down of (value, name) pairs; `slot` gets the value."""
        box = MarkChoice(sample, original, self) if sample else PropertyChoice(self)
        box.setToolTip(tip)
        box.setAccessibleName(tip)
        box.setMinimumHeight(28)
        for value, name in choices:
            box.addItem(name, value)
        if sample:
            box.remeasure()
            box._describe_choice()
        box.currentIndexChanged.connect(lambda i: slot(box.itemData(i)))
        box.mouseCommitted.connect(self.view.setFocus)
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
        if hasattr(self, "welcome"):
            if doc.is_placeholder and not doc.path:
                self.show_welcome()
            else:
                self.show_editor()
        if old is not None and old is not doc:
            old.selectionChanged.disconnect(self.refresh_props)
            old.undo_stack.indexChanged.disconnect(self._doc_changed)
            old.undo_stack.indexChanged.disconnect(self._schedule_autosave)
            old.undo_stack.cleanChanged.disconnect(self.update_title)
            old.editingChanged.disconnect(self._editing_changed)
            self.undo_group.removeStack(old.undo_stack)
            old.deleteLater()
        self.tool_actions[self.view.tool].setChecked(True)
        self._editing_changed(doc.editing_item)
        self._doc_changed()
        if self._remembering:
            self.settings.setValue(CURRENT_KEY, doc.path or "")

    def _editing_changed(self, item) -> None:
        """Point Undo / Redo at the edited text's history, or back at the
        undo stack when no text box is being edited."""
        context = getattr(self, "_live_format", None)
        if context is not None and context[2] is not item:
            self._live_format = None
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
        self.recent.set_document_path(self.doc.path if self.state_name == 'editor' else None)
        if self.is_recent_doc():        # a Recent capture: its stamp
            name = Path(self.doc.path).stem
        else:
            name = Path(self.doc.path).name if self.doc.path else "Untitled"
        self.setWindowTitle(f"Annotshot — {name}[*]")
        # A document with a file keeps itself (the autosave): no * churn.
        self.setWindowModified(not self.doc.path
                               and self.doc.undo_stack.needs_save())

    def refresh_props(self) -> None:
        """Show the selection's style, or the active tool's starting style."""
        self._selection_actions()
        items = self.doc.selected()
        self._show_selection(items)
        default = self.view.defaults_item()
        targets = items or ([default] if default is not None else [])

        def first(key):
            for it in targets:
                k = it.key_for(key)
                if k is not None:
                    return it.props[k]
            return None

        self._refreshing = True
        try:
            for w, key in self._controls.items():
                w.setEnabled(first(key) is not None)
                w.setVisible(first(key) is not None)
            # A highlight's fill alpha is fixed: "No fill" does nothing to it.
            self.b_nofill.setEnabled(any(
                it.key_for("fill_color") is not None
                and not isinstance(it, HighlightItem) for it in targets))
            line = any(it.KIND in ("arrow", "pen") for it in targets)
            self.border_label.setText("Line colour" if line else "Border")
            highlight = bool(targets) and all(isinstance(it, HighlightItem) for it in targets)
            self.fill_label.setText("Fill colour" if highlight else "Fill")
            self.b_nofill.setVisible(self.b_nofill.isEnabled())
            self.c_border.setAccessibleName("Line" if line else "Border")
            self.c_border._title = "Line color" if line else "Border color"
            self.c_border.setToolTip(self.c_border._title)
            self.s_width.setToolTip("Line width" if line else "Border width")
            self.b_noborder.setVisible(not line and first("border_color") is not None)
            for button, key in ((self.c_text, "text_color"),
                                (self.c_fill, "fill_color"),
                                (self.c_border, "border_color")):
                if first(key) is not None:
                    button.set_color(first(key))
            if first("border_width") is not None:
                self.s_width.setValue(first("border_width"))
            if (first("font_family") is not None
                    and QApplication.focusWidget() not in
                    (self.f_font, self.f_font.lineEdit())):
                # A focused entry owns its draft, including an unfinished
                # family name. Refreshing the strip must not replace it.
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
            self._arrange_props()
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

    def _arrange_props(self) -> None:
        """Keep the balanced pair, otherwise use the fewest ordered rows.

        ASSUMES: an individual field fits the viewport. An oversized field
        falsifies this: it can pan, with a separate scrollbar band below
        all full-height controls, rather than clipping the second row.
        """
        groups = [g for _key, g in self._prop_groups if not g.isHidden()]
        if not groups:
            return
        before = (self._prop_partition, self.prop_strip.minimumSize(),
                  self.prop_scroll.minimumHeight(), self.prop_scroll.maximumHeight())
        for group in groups:
            group.ensurePolished()
            if group.layout() is not None:
                group.layout().activate()
        widths = [g.sizeHint().width() for g in groups]
        margins = self.prop_strip.layout().contentsMargins()
        available = max(1, self.prop_scroll.viewport().width()
                        - margins.left() - margins.right())

        def width(a, b):
            return sum(widths[a:b]) + max(0, b - a - 1) * 8

        cut = min(range(1, len(groups) + 1),
                  key=lambda i: max(width(0, i), width(i, len(groups))))
        # Hidden toolbars have no laid-out viewport yet. Keep their
        # balanced pair until the real viewport's show/resize event.
        if not self.isVisible() or not self.prop_scroll.isVisibleTo(self):
            available = max(available, width(0, cut), width(cut, len(groups)))
        parts = [groups[:cut], groups[cut:]]
        if max(width(0, cut), width(cut, len(groups))) > available:
            parts, start = [], 0
            for index in range(len(groups)):
                if index > start and width(start, index + 1) > available:
                    parts.append(groups[start:index])
                    start = index
            parts.append(groups[start:])
            if len(parts) == 1:
                parts.append([])
        signature = tuple(tuple(part) for part in parts)
        if signature != self._prop_partition:
            for row in self._prop_rows:
                layout = row.layout()
                while layout.count() > 1:
                    layout.takeAt(0)
            while len(self._prop_rows) < len(parts):
                row = QWidget(self.prop_strip)
                row.setFixedHeight(36)
                layout = QHBoxLayout(row)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(8)
                layout.addStretch(1)
                self.prop_strip.layout().addWidget(row)
                self._prop_rows.append(row)
            for index, part in enumerate(parts):
                row = self._prop_rows[index]
                row.show()
                for group in part:
                    row.layout().insertWidget(row.layout().count() - 1, group)
                    group.show()
                row.layout().invalidate()
            # Remove spare rows from the layout, preserving the original
            # two row objects for the balanced-pair geometry contract.
            while len(self._prop_rows) > len(parts):
                row = self._prop_rows.pop()
                for _key, group in self._prop_groups:
                    if group.parentWidget() is row:
                        group.setParent(self.prop_strip)
                        group.hide()
                self.prop_strip.layout().removeWidget(row)
                row.deleteLater()
            self._prop_partition = signature
        minimum = max((sum(g.sizeHint().width() for g in part)
                       + max(0, len(part) - 1) * 8 for part in parts), default=0)
        self.prop_strip.setMinimumWidth(minimum + margins.left() + margins.right())
        height = 4 + 36 * len(parts)
        self.prop_strip.setMinimumHeight(height)
        band = max(self.prop_scroll.style().pixelMetric(QStyle.PM_ScrollBarExtent),
                   self.prop_scroll.horizontalScrollBar().sizeHint().height()) \
            if minimum > available else 0
        self.prop_scroll.setFixedHeight(height + band)
        self.prop_strip.layout().activate()
        after = (self._prop_partition, self.prop_strip.minimumSize(),
                 self.prop_scroll.minimumHeight(), self.prop_scroll.maximumHeight())
        # The viewport's LayoutRequest rearms our zero timer. Notify its
        # parent only for a changed partition or size, so idle reflow ends.
        if after != before:
            self.prop_strip.updateGeometry()

    def _begin_live_format(self, control):
        """Capture the actual caret at gesture start, never a last-input mode."""
        self._live_format = None
        item = self.doc.editing_item
        if (item is not None and QApplication.focusWidget() is self.view
                and item.editor.hasFocus()):
            self._live_format = (control, self.doc, item, item.editor.textCursor())

    def _live_format_focus_changed(self, old, now):
        context = self._live_format
        if context is None or now is None:
            return
        control = context[0]
        expected = (self.view, self.f_font.view()) if control is self.f_font else (self.view,)
        if now not in expected:
            self._live_format = None  # a newer destination owns its typing

    def _finish_live_format(self, control, resume=True):
        context, self._live_format = self._live_format, None
        if context is None or context[0] is not control or not resume:
            return
        _, doc, item, cursor = context
        if self.doc is doc and doc.editing_item is item:
            # ASSUMES: this still-live gesture has not been superseded by
            # another focus owner. Consume it before restoring, so no later
            # event, refresh, or window return can repeat the hand-back.
            self.view.setFocus(Qt.PopupFocusReason)
            item.editor.setFocus(Qt.PopupFocusReason)
            item.editor.setTextCursor(cursor)

    def eventFilter(self, watched, event):  # noqa: N802 - Qt's name
        if (hasattr(self, "f_font") and hasattr(self, "s_size")
                and watched in (self.f_font.lineEdit(), self.s_size.lineEdit())
                and event.type() == QEvent.MouseButtonPress
                and event.button() == Qt.LeftButton):
            # Editable combos/spins share their entry's focus policy. Keep
            # the arrow TabFocus, and give a deliberate text-area click its
            # focus here, in the same press, before normal text handling.
            self._live_format = None
            watched.setFocus(Qt.MouseFocusReason)
        if watched is getattr(self, "s_size", None):
            if (event.type() == QEvent.MouseButtonPress
                    and event.button() == Qt.LeftButton):
                option = QStyleOptionSpinBox()
                self.s_size.initStyleOption(option)
                hit = self.s_size.style().hitTestComplexControl(
                    QStyle.CC_SpinBox, option, event.position().toPoint(), self.s_size)
                if hit in (QStyle.SC_SpinBoxUp, QStyle.SC_SpinBoxDown):
                    self._begin_live_format(self.s_size)
            elif (event.type() == QEvent.MouseButtonRelease
                  and event.button() == Qt.LeftButton):
                self._finish_live_format(self.s_size)
        if (watched is getattr(self, "view", None)
                and event.type() == QEvent.KeyPress
                and event.key() in (Qt.Key_Tab, Qt.Key_Backtab)
                and not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)
                and self.doc.is_editing()):
            self.doc.end_text_edit()
            self.focusNextPrevChild(event.key() != Qt.Key_Backtab
                                    and not event.modifiers() & Qt.ShiftModifier)
            return True
        timer = getattr(self, "_props_reflow", None)
        if timer is not None and event.type() in (
                QEvent.Resize, QEvent.FontChange, QEvent.StyleChange,
                QEvent.LayoutRequest):
            timer.start()
        return super().eventFilter(watched, event)

    def _show_selection(self, items) -> None:
        """Plain words for the objects or new drawing the controls affect."""
        target = items[0] if items else self.view.defaults_item()
        hint = not items and target is None
        if hint:
            text, kind = TOOL_HINTS[self.view.tool], "select"
        else:
            same = all(item.KIND == target.KIND for item in items)
            singular, plural = KIND_WORDS[target.KIND]
            kind = KIND_ICONS[target.KIND] if same else "select"
            if not items:
                text = "New " + ("text" if target.KIND == "text" else plural)
            elif len(items) == 1:
                text = "This " + singular
            else:
                text = f"{len(items)} {plural if same else 'objects'}"
        self.sel_heading.setText(text)
        self.sel_heading.setObjectName("stripHint" if hint else "objectHeading")
        self.sel_heading.style().unpolish(self.sel_heading)
        self.sel_heading.style().polish(self.sel_heading)
        self.sel_mark.setVisible(not hint)
        dpr = self.devicePixelRatioF()
        if (kind, dpr) not in self._marks:
            self._marks[kind, dpr] = themed_icon(kind, size=13,
                                                ink="mark-ink").pixmap(QSize(13, 13), dpr)
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
        """The text kind's own starting style (kept separate from callouts)."""
        return self.view.starting_style("text")

    def set_remember_props(self, on: bool) -> None:
        self.view.set_remember_props(on)
        self.refresh_props()

    def reset_tool_defaults(self) -> None:
        self.view.reset_tool_defaults()
        self.refresh_props()

    def _set(self, props: dict, text: str, merge_key=None) -> None:
        if self._refreshing:
            return
        items = self.doc.selected()
        if items:
            self.doc.set_props(items, props, text, merge_key)
        else:
            item = self.view.defaults_item()
            if item is None:
                return
            items = [item]
            picked = {}
            for control_key, value in props.items():
                key = item.key_for(control_key)
                if key is not None:
                    picked[key] = value(item, key) if callable(value) else value
            item.apply_props(picked)
            self.view.new_style_choice(item, props)
        for item in items:
            self.view.remember_style(item, props)
        self.refresh_props()

    def _selection_actions(self):
        enabled = self.state_name == "editor" and bool(self.doc.selected())
        for action in (self.a_dup, self.a_front, self.a_back, self.a_delete):
            action.setEnabled(enabled)
            self._retip(action)

    def menu_actions(self, on_item: bool) -> list:
        """The right-click menu, top to bottom (None = a separator): the
        same actions as the buttons, so the same text, icons and keys."""
        actions = [self.a_copy, self.a_save, None]
        if on_item:
            actions += [self.a_dup, self.a_front, self.a_back, self.a_delete,
                        None]
        return actions + [self.a_clear, self.a_capture, self.a_recent, None,
                          self.a_settings, self.a_help, self.a_feedback,
                          self.a_about, None, self.a_quit]

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
        return (f"{key_words(seq)} is already used "
                f"by {owner}.")

    def _use_shortcuts(self, key: str, seqs: list) -> bool:
        a = self.shortcut_actions[key]
        changed = a.shortcuts() != seqs
        a.setShortcuts(seqs)
        if a in (self.a_undo, self.a_redo):
            self._sync_undo()
        else:
            self._retip(a)
        if key == "capture":
            previous = self.statusBar().currentMessage()
            self._update_capture_hint()
            if changed and (not previous or previous.endswith("to take a screenshot")):
                self.statusBar().showMessage(self.capture_status(), 8000)
        return changed

    def _reapply_hotkey_after_shortcut_change(self, changed: bool) -> None:
        if (changed and not self.hotkey_off() and self.hotkey.available
                and not self.hotkey.registered):
            problem = self.apply_hotkey()
            if not problem and self.statusBar().currentMessage().startswith(HOTKEY_NAME):
                self.statusBar().clearMessage()

    def set_shortcut(self, key: str, seq: QKeySequence) -> str | None:
        """Give an action its own key (an empty one removes its key). The
        one-line reason when the key is already used; nothing changes then."""
        seq = QKeySequence(seq)
        owner = self._key_owner(seq, skip=key)
        if owner:
            return self._taken(seq, owner)
        if not seq.isEmpty() and seq == self.shortcut_actions[key].shortcut():
            return None
        changed = self._use_shortcuts(key, [] if seq.isEmpty() else [seq])
        self.settings.setValue(f"shortcuts/{key}",
                               seq.toString(QKeySequence.PortableText))
        self._reapply_hotkey_after_shortcut_change(changed)
        return None

    def reset_shortcut(self, key: str) -> str | None:
        """Back to the key(s) Annotshot ships with, unless another action
        now uses one of them."""
        for seq in self.default_shortcuts[key]:
            owner = self._key_owner(seq, skip=key)
            if owner:
                return self._taken(seq, owner)
        changed = self._use_shortcuts(key, list(self.default_shortcuts[key]))
        self.settings.remove(f"shortcuts/{key}")
        self._reapply_hotkey_after_shortcut_change(changed)
        return None

    def reset_all_shortcuts(self) -> str | None:
        for key in self.shortcut_actions:
            self._use_shortcuts(key, list(self.default_shortcuts[key]))
        self.settings.remove("shortcuts")
        self._reset_key = True
        try:
            return self.apply_hotkey()
        finally:
            self._reset_key = False

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

    def key_state(self):
        """The single published result read by every capture-key surface."""
        if not hasattr(self, "_key_snapshot"):
            self._key_snapshot = self._make_key_state()
        return self._key_snapshot

    def _make_key_state(self):
        requested = self.hotkey_sequence()
        held = self.hotkey.sequence if self.hotkey.registered else QKeySequence()
        off = self.hotkey_off()
        trying = self._key_try is not None
        confirmed = self._key_ready and not off and not held.isEmpty()
        key = key_words(held) if confirmed else ""
        if not self._key_ready:
            button, line, face = "Capture key", "Setting up the capture key…", "plain"
        elif off and not self.hotkey.registered:
            button, line, face = "Key off", "Capture key is off.", "plain"
        elif off:
            button, line, face = "Choose another key", self._key_feedback, "amber"
        elif key:
            button, line, face = key, f"Capture from anywhere with {key}", "green" if self._key_green else "plain"
        else:
            button, face = "Choose another key", "amber"
            line = (self._key_feedback if self._key_feedback and
                    not self._key_feedback.startswith(key_words(requested) + " is taken")
                    else f"{key_words(requested)} is unavailable.")
        if self._key_line:
            line = self._key_line
        live = key if not trying else ""
        menu = (["Retry turn off"] if off and self.hotkey.registered else
                ["Turn on"] if off else ["Try this key", "Change key", "Turn off"])
        outcome = self._key_feedback
        if self._key_edit_error:
            reasons = [self._key_edit_error]
            if self._key_edit_qualified and (self.hotkey._retained or (off and self.hotkey.registered)):
                failed = (self.hotkey._retained[0][1] if self.hotkey._retained else held)
                reasons.append(hotkey.RELEASE.format(key=key_words(failed)))
            elif self._key_edit_qualified and not off and held.isEmpty():
                reasons.append(f"{key_words(requested)} is unavailable.")
            outcome = "\n".join(dict.fromkeys(reasons))
        return dict(requested=QKeySequence(requested), off=off,
                    held=QKeySequence(held), outcome=outcome,
                    button=button, line=line, face=face, menu=menu,
                    live=live, notice_key=key)

    def _publish_key(self):
        self._key_snapshot = self._make_key_state()
        self.keyStateChanged.emit()
        if hasattr(self, "welcome"):
            self.welcome.refresh_key()
        if self.tray is not None:
            self.tray.refresh()
        if self._help_window is not None:
            self._help_window.refresh(self.shortcut_rows())

    def _key_status(self, text="", error=False):
        if text:
            message = f"{HOTKEY_NAME}: {text}" if error else text
            self._last_key_status = message
            self.statusBar().showMessage(message, 10000)
        elif (self.statusBar().currentMessage() == getattr(self, "_last_key_status", None)
              or self.statusBar().currentMessage().startswith(HOTKEY_NAME + ":")):
            self.statusBar().clearMessage()

    def validate_capture_key(self, seq):
        problem = hotkey.check(seq)
        if not problem:
            owner = self._key_owner(seq, skip="hotkey")
            problem = self._taken(seq, owner) if owner else None
        if not problem and ((sys.platform == "darwin" and hotkey.mac_combo(seq) is None)
                            or (sys.platform == "win32" and hotkey.win_combo(seq) is None)):
            problem = hotkey.UNKNOWN_KEY
        return problem

    def end_key_interaction(self):
        self.end_key_try()
        self.welcome.cancel_recording()

    def set_hotkey(self, seq: QKeySequence, off: bool, settings_edit=False) -> str | None:
        return self._apply_key(QKeySequence(seq), off, save=True, settings_edit=settings_edit)

    def _apply_key(self, seq, off, save=False, reset=False, settings_edit=False):
        self.end_key_try()
        was_off = self.hotkey_off()
        # Disabling an existing choice must work even for legacy invalid keys.
        new_choice = seq != self.hotkey_sequence()
        problem = None
        if not off or new_choice or reset:
            problem = self.validate_capture_key(seq)
        if problem and (save or reset):
            self._key_edit_error = problem
            self._key_edit_qualified = settings_edit or reset
            if self._key_line != "Annotshot received your key":
                self._key_line = ""
            self._key_status(problem, error=True)
            self._publish_key()
            return problem
        self.welcome.cancel_recording()
        self._key_edit_error = ""
        before = QKeySequence(self.hotkey.sequence)
        previously_held = self.hotkey.registered
        previous_feedback = self._key_feedback
        self._key_line = ""
        if not self.hotkey.available:
            problem = self.hotkey.clear()
        elif off:
            problem = self.hotkey.clear()
        elif not problem:
            problem = self.hotkey.set_sequence(seq)
        accepted = self.hotkey.registered and self.hotkey.sequence == seq
        refused_swap = previously_held and not off and not accepted
        if (refused_swap and problem and not self.hotkey.cleanup_blocked
                and " is taken by the system or another app" in problem):
            problem = hotkey.STILL_USING.format(new=key_words(seq), old=key_words(before))
            if not was_off:
                self._key_line = problem
        if refused_swap and was_off and not self.hotkey.cleanup_blocked:
            problem = previous_feedback
        # Save only a successful replacement, or a requested choice when
        # nothing was held. Off is an explicit preference even on release error.
        can_save = not self.hotkey.cleanup_blocked and (accepted or not previously_held)
        if off:
            can_save = not problem
        if (save or reset) and can_save:
            if reset:
                self.settings.remove("hotkey/sequence")
            elif new_choice:
                self.settings.setValue("hotkey/sequence", seq.toString(QKeySequence.PortableText))
        if save and off:
            self.settings.setValue("hotkey/off", True)
        elif save and was_off and can_save:
            self.settings.setValue("hotkey/off", False)
        if before != self.hotkey.sequence:
            self._key_green = False
        self._key_ready = True
        self._key_feedback = problem or ""
        self._hotkey_problem = problem
        self._key_status(problem or "", error=bool(problem))
        self._publish_key()
        return problem

    def apply_hotkey(self) -> str | None:
        reset = getattr(self, "_reset_key", False)
        seq = QKeySequence(hotkey.DEFAULT) if reset else self.hotkey_sequence()
        return self._apply_key(seq, self.hotkey_off(), reset=reset)

    def try_capture_key(self):
        self.end_key_interaction()
        if self.hotkey_off():
            return
        state = self.key_state()
        if not state["live"] or self.hotkey._retained:
            if self.apply_hotkey():
                return
        self._key_feedback = ""
        self._hotkey_problem = None
        self._key_edit_error = ""
        self._key_status()
        self._key_epoch += 1
        epoch = self._key_epoch
        self._key_try = dict(epoch=epoch, phase="beat", sequence=QKeySequence(self.hotkey.sequence), timers=[])
        self._key_green = False
        self._key_line = f"Press {key_words(self.hotkey.sequence)} now."
        self._key_status()
        self._publish_key()
        def minimize():
            if not self._current_key_try(epoch):
                return
            self._key_try["phase"] = "minimizing"
            self.showMinimized()
            self._arm_key_try()
            self._schedule_key_try(2000, lambda: self._key_minimize_failed(epoch))
        self._schedule_key_try(1000, minimize)

    def _schedule_key_try(self, milliseconds, callback):
        self._key_try["timers"].append(self.key_clock.call_later(milliseconds, callback))

    def _current_key_try(self, epoch):
        return self._key_try is not None and self._key_try["epoch"] == epoch

    def _arm_key_try(self):
        if (not self._key_try or self._key_try["phase"] != "minimizing"
                or not self.isMinimized()):
            return
        self._key_try["phase"] = "armed"
        self._key_try["native_start"] = self.hotkey.try_boundary()
        epoch = self._key_try["epoch"]
        self._schedule_key_try(10000, lambda: self._key_try_timeout(epoch))

    def _key_minimize_failed(self, epoch):
        if self._current_key_try(epoch) and self._key_try["phase"] != "armed":
            self.end_key_try("Annotshot could not minimize for the try.")
            self._key_line = "Annotshot could not minimize for the try."
            self._publish_key()

    def _key_try_timeout(self, epoch):
        if self._current_key_try(epoch):
            self.end_key_try("No press received", restore=True)

    def end_key_try(self, result="", restore=False):
        if self._key_try is None:
            return
        self.hotkey.finish_try()
        for cancel in self._key_try["timers"]:
            if cancel is not None:
                cancel()
        self._key_try = None
        self._key_epoch += 1
        self._key_line = result if result in ("No press received", "Annotshot received your key") else ""
        self._key_green = result == "Annotshot received your key"
        self._key_status(result)
        self._publish_key()
        if restore:
            self._key_restoring = True
            try:
                self.show_welcome()
                self.showNormal()
                self._show_again()
                self.welcome.capture_bar.key_button.setFocus(Qt.OtherFocusReason)
            finally:
                self._key_restoring = False

    def _native_capture_key(self, event):
        seq, pressed, repeat, epoch = event[:4]
        native_time = event[4] if len(event) > 4 else None
        if (not pressed or repeat or epoch != self._key_epoch
                or not self.hotkey.after_latest_try(native_time)):
            return
        if any(getattr(child, "capture_key_has_focus", lambda: False)()
               for child in self.findChildren(QDialog)):
            return
        if self._key_try:
            if (self._key_try["phase"] == "armed" and self.isMinimized()
                    and seq == self._key_try["sequence"]
                    and self.hotkey.after_boundary(native_time, self._key_try["native_start"])):
                self.end_key_try("Annotshot received your key", restore=True)
            return
        if (getattr(self.welcome, "recording", False)
                or any(getattr(child, "capture_key_has_focus", lambda: False)()
                       for child in self.findChildren(QDialog))):
            return
        self.capture_from_anywhere()

    def capture_from_anywhere(self) -> None:
        """Ordinary capture, including a tray click; never a try receipt."""
        self.end_key_interaction()
        if self._capture is None and not self._capture_pending:
            if self.isMinimized():
                self.showNormal()
            self.capture()

    def capture_key_text(self):
        return self.key_state()["live"]

    def keep_running(self):
        # ASSUMES: keep-running is on. Turning it off restores quit on close.
        return self.settings.value("app/keep_running", True, type=bool)

    def set_keep_running(self, enabled):
        self.settings.setValue("app/keep_running", bool(enabled))
        self.configure_background()

    def _ensure_tray(self):
        if (self._quitting or sys.platform == "darwin" or not self.keep_running()
                or self.tray is not None):
            return
        from .tray import QSystemTrayIcon, TrayController
        if QSystemTrayIcon.isSystemTrayAvailable():
            from .app import app_icon
            self.tray = TrayController(self, app_icon())

    def hideEvent(self, event):
        self._ensure_tray()
        super().hideEvent(event)

    def configure_background(self):
        QApplication.instance().setQuitOnLastWindowClosed(not self.can_hide_on_close())
        self.welcome.refresh()

    def can_hide_on_close(self):
        from .tray import QSystemTrayIcon
        return (sys.platform != "linux" and self.keep_running() and
                (sys.platform == "darwin" or
                 QSystemTrayIcon.isSystemTrayAvailable()))

    def reopen(self):
        self.end_key_try("Try cancelled")
        if self._capture is not None or self._capture_pending:
            return
        if not self.isVisible():
            self.show_welcome()
        if self.isMinimized():
            self.showNormal()
        self._show_again()

    def quit_app(self):
        """Use the close guard once, including when the window is hidden."""
        if self._restart_save is not None:
            # A person's quit while the restart waits is an ordinary quit.
            self._restart_save = None
            self._restart_pending = False
        self._quitting = True
        if self.close():
            QApplication.instance().quit()
        else:
            self._quitting = False

    def send_feedback(self) -> None:
        from .help import open_url
        open_url(feedback.CHOOSER_URL)

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
        state = self.key_state()
        rows.append((HOTKEY_NAME, [state["held"]] if state["live"] else []))
        return rows

    def show_help(self) -> None:
        """The Help window: the manual with the keys as they are now. It
        does not block the editor; a second F1 brings it to the front."""
        from .help import HelpWindow
        if self._help_window is None:
            self._help_window = HelpWindow(self.shortcut_rows(), self)
            self._help_window.privacyRequested.connect(self.show_privacy)
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

    def show_privacy(self) -> None:
        from .help import PrivacyWindow
        from PySide6.QtWidgets import QApplication
        focus = QApplication.focusWidget()
        if focus is not None and (self._privacy_window is None or
                                  focus.window() is not self._privacy_window):
            self._privacy_focus = focus
        if self._privacy_window is None:
            if self._privacy_focus is None:
                self._privacy_focus = self.welcome.privacy_row
            self._privacy_window = PrivacyWindow(self)
            self._privacy_window.finished.connect(self._privacy_closed)
        self._privacy_window.show()
        self._privacy_window.raise_()
        self._privacy_window.activateWindow()

    def _privacy_closed(self, *_):
        if self._privacy_window is not None:
            self._privacy_window.deleteLater()
            self._privacy_window = None
        import shiboken6
        target = self._privacy_focus
        if target is not None and shiboken6.isValid(target) and target.isVisible():
            target.window().activateWindow()
            target.setFocus(Qt.OtherFocusReason)
        else:
            self.activateWindow()
            self.pages.currentWidget().setFocus(Qt.OtherFocusReason)
        self._privacy_focus = None

    def open_shortcut_settings(self) -> None:
        self.open_settings(tab="Shortcuts")

    def open_settings(self, tab=None) -> None:
        self.end_key_try("Try cancelled")
        from .settings_dialog import SettingsDialog
        dialog = SettingsDialog(self)
        if tab == "Shortcuts":
            dialog.tabs.setCurrentIndex(0)
        dialog.exec()
        dialog.deleteLater()
        self.welcome.refresh()

    # -- quick capture ----------------------------------------------------------
    def quick_copy(self) -> bool:
        # On to begin with: a capture is on the clipboard at once, so a
        # paste works without a click on Copy image. Off is the user's pick.
        return self.settings.value("capture/copy", True, type=bool)

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
        elif self.view._press is None and self.view._handle_drag is None and self.view._before is None:
            self.view.set_tool(Tool.SELECT)
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
        self.statusBar().showMessage("Picture closed", 3000)

    def copy_image(self) -> None:
        QApplication.clipboard().setImage(self.doc.render_image())
        self._exported()
        self.statusBar().showMessage("Copied — paste it anywhere", 2000)

    # -- files ------------------------------------------------------------
    def _folder(self, kind: str) -> Path:
        if kind == "save":
            # ASSUMES: a remembered directory remains accessible. Never
            # recreate it: only the built-in default may be created here.
            remembered = self.settings.value("last_dir/save", "", type=str)
            usable = lambda p: p.is_dir() and os.access(
                p, os.R_OK | os.W_OK | os.X_OK)
            if remembered and usable(Path(remembered)):
                return Path(remembered)
            folder = default_directory()
            try:
                folder.mkdir(parents=True, exist_ok=True)
                if usable(folder):
                    return folder
            except OSError:
                pass
            home = Path.home()
            # Home is a browsing fallback: the person can choose a writable
            # child from it even when home itself permits no new files.
            if home.is_dir() and os.access(home, os.R_OK | os.X_OK):
                return home
            raise OSError("Neither the default save folder nor your home "
                          "folder can be opened")
        folder = Path(self.settings.value(f"last_dir/{kind}", "", type=str)
                      or default_directory())
        if not folder.is_dir():
            folder = default_directory()
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
        return self._save_dialog(self.doc)

    @staticmethod
    def _same_file(first, second) -> bool:
        """Resolve directory/file symlinks, case and existing hard links."""
        try:
            if os.path.samefile(first, second):
                return True
        except OSError:
            pass
        return os.path.normcase(os.path.realpath(first)) == \
            os.path.normcase(os.path.realpath(second))

    def _kept_destination(self, path: str) -> bool:
        # ASSUMES: spelling a path differently does not grant ownership of
        # a kept source. Read actual entries, including their suffix case.
        candidates = self.recent_store.source_entries()
        for reserved in recent._RESERVED:
            candidates.extend((recent.png_for(reserved), recent.editable_for(reserved)))
        if self.doc.path:
            # The shown document may live outside Recent. Protect its own
            # spelling, resolved identity, and both PNG/editable companions.
            for bound in (self.doc.path, os.path.realpath(self.doc.path)):
                candidates.extend((Path(bound), recent.png_for(bound),
                                   recent.editable_for(bound)))
        return any(self._same_file(path, candidate) for candidate in candidates)

    def save_recent(self, path: str) -> bool:
        """Export a detached full-size revision, without binding/opening it.

        The shown capture is snapshotted immediately after finishing typing.
        Another capture's serial writes must settle before its file is read.
        Thumbnail's raw-PNG fallback is deliberately not used here.
        """
        png, editable = recent.png_for(path), recent.editable_for(path)
        doc = None
        try:
            try:
                self.recent_store.source_entries()  # refuse a linked/unreadable root
            except (OSError, RuntimeError) as error:
                # Do not read this source. Let the picker name the refused
                # destination in R22's warning and re-offer the same proposal.
                return self._save_dialog(self.doc, source=Path(path),
                                         source_error=error)
            if not png.exists() and not editable.exists() and \
                    str(png) not in recent._RESERVED:
                raise OSError(f"{png.name}: the capture is no longer in Recent")
            if self.doc.path and self._same_file(self.doc.path, editable):
                self.doc.end_text_edit()
                doc = Document(QImage(self.doc.base))
                for item in self.doc.annotation_items():
                    doc.addItem(item.clone())
                doc.path = str(editable)
            else:
                pending = [d for d, _g, p in self._save_jobs
                           if self._same_file(p, editable)]
                if not recent.writer().waitForDone(5000):
                    raise OSError(f"{editable.name}: the pending write "
                                  "has not finished")
                for waiting in pending:
                    outcome = waiting.last_write
                    if outcome is not None and outcome.error:
                        raise OSError(f"{editable.name}: {outcome.error}")
                if editable.exists():
                    try:
                        # A skipped object/newer format is also a lossy
                        # read. An export promising edits must refuse it.
                        with warnings.catch_warnings():
                            warnings.simplefilter("error")
                            doc = Document.load(editable)
                    except Exception as e:
                        raise OSError(
                            f"{editable.name}: Could not read this capture’s "
                            f"edits. {e}") from e
                else:
                    reader = QImage(str(png))
                    if reader.isNull():
                        raise OSError(f"{png.name}: the capture is missing "
                                      "or its picture cannot be read")
                    doc = Document(reader)
                    doc.path = str(editable)
            return self._save_dialog(doc, source=Path(path))
        except OSError as e:
            self._warn(str(e))
            return False
        finally:
            if doc is not None:
                doc.deleteLater()

    def _save_dialog(self, doc: Document, source: Path | None = None,
                     source_error: Exception | None = None) -> bool:
        """Both Save entry points use the same filters, folder and writers."""
        types = {t[0]: t for t in SAVE_TYPES}
        last = self.settings.value("last_filter/save", "", type=str)
        preset = types.get(last, SAVE_TYPES[0])
        try:
            name = source or (Path(doc.path) if doc.path else None)
            start = (str(self._folder("save") /
                         name.with_suffix("." + preset[1][0]).name)
                     if name else self._default_path("save", preset[1][0]))
        except OSError as e:
            self._warn(f"Could not open a Save folder: {e}")
            return False
        while True:
            if source is None:
                path, chosen = QFileDialog.getSaveFileName(
                    self, "Save", start, SAVE_FILTERS, preset[0])
            else:
                # Only the FINAL name may ask to replace. In particular a
                # mismatched typed suffix must not prompt for two files.
                path, chosen = QFileDialog.getSaveFileName(
                    self, "Save", start, SAVE_FILTERS, preset[0],
                    options=QFileDialog.DontConfirmOverwrite)
            if not path:
                return False
            name_filter, exts, fmt = types.get(chosen, preset)
            typed, path = path, typed_path_for(path, exts)
            problem = None
            try:
                if source_error is not None:
                    raise source_error
                self.recent_store.source_entries()  # also guard editor Save As
                if self.recent_store.contains_destination(path):
                    problem = ("Recent is where Annotshot keeps captures, and it "
                               "removes older ones. Choose another folder for this copy.")
                elif source is not None and self._kept_destination(path):
                    problem = "That file belongs to Recent. Choose another name or folder."
            except (OSError, RuntimeError) as e:
                problem = f"Could not write {path}: {e}"
            if problem is None:
                break
            self._warn(problem)
            # Keep the rejected proposal for correction in the native Save
            # picker; no export or settings write has happened.
            start, preset = typed, types.get(chosen, preset)
        if ((source is not None or os.path.normcase(path) != os.path.normcase(typed)
             or (os.path.islink(path) and not os.path.exists(path)))
                and os.path.lexists(path) and not self._ask_replace(path)):
            return False
        if fmt == PROJECT_FORMAT:
            ok = self._save_editable(path, doc)
        elif fmt in OFFICE_FORMATS:
            ok = self._save_office(path, fmt, doc)
        else:
            ok = self._save_picture(path, fmt, doc)
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

    def _save_picture(self, path: str, fmt: str,
                      doc: Document | None = None) -> bool:
        """The rendered picture with every edit (white under JPEG / BMP)."""
        doc = self.doc if doc is None else doc
        img = doc.render_image()
        if fmt in NO_ALPHA_FORMATS:
            img = flatten_on_white(img)
        quality = JPEG_QUALITY if fmt == "JPEG" else -1
        try:
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            if not img.save(buffer, fmt, quality):
                raise OSError("the picture could not be encoded")
            data = bytes(buffer.data())
            buffer.close()
            _write_safely(lambda stream: stream.write(data), path)
        except OSError as e:
            self._warn(f"Could not write {path}: {e}")
            return False
        if doc is self.doc:
            self._exported()
        self.statusBar().showMessage(f"Saved {Path(path).name}", 3000)
        return True

    def _save_office(self, path: str, fmt: str,
                     doc: Document | None = None) -> bool:
        """The picture in a Word document or on a PowerPoint slide."""
        doc = self.doc if doc is None else doc
        try:
            export(fmt, doc.render_image(), path)
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
        if doc is self.doc:
            self._exported()
        self.statusBar().showMessage(f"Saved {Path(path).name}", 3000)
        return True

    def _save_editable(self, path: str,
                       doc: Document | None = None) -> bool:
        """The editable .annotshot file. A document that already keeps
        itself (it has a file) writes a second COPY there and stays the
        one that keeps itself; its own file is simply written now. A
        document with no file at all takes this one as its file."""
        doc = self.doc if doc is None else doc
        if doc is not self.doc:
            try:
                doc.write(path)
            except OSError as e:
                self._warn(f"Could not save {Path(path).name}: {e}")
                return False
            self.statusBar().showMessage(f"Saved {Path(path).name}", 3000)
            return True
        doc.end_text_edit()
        own = self.doc.path and os.path.normcase(os.path.abspath(path)) == \
            os.path.normcase(os.path.abspath(self.doc.path))
        try:
            if self.doc.path and not own:
                self.doc.write(path)
            else:
                self._autosave_timer.stop()
                recent.writer().waitForDone()   # never two writers of a file
                if self.is_recent_doc():
                    if not self._protect_recent_edit(self.doc):
                        return False
                    holds = self._pending_edits[self.doc]
                    recent._write_editable(path, *self.doc.snapshot(), holds)
                    self._pending_edits.pop(self.doc, None)
                    self.doc.written = self.doc.changes
                    self.doc.last_write = None
                    self.doc.undo_stack.setClean()
                else:
                    self.doc.save(path)
                    if hasattr(self.doc, '_recent_source'):
                        del self.doc._recent_source
                    self.doc._recent_retry_path = None
        except OSError as e:
            if isinstance(e, recent.RecentConflict):
                self._detach_recent_conflict(self.doc, path, str(e))
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
        self.end_key_interaction()
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
        self.end_key_interaction()
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
                if (Path(path).suffix.lower() == recent.EDITABLE
                        and self.recent_store.owns(path)):
                    doc = recent.load_edit(path, fallback=False)
                else:
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

    def _failed_write_box(self, why: str) -> QMessageBox:
        box = QMessageBox(QMessageBox.Warning, "Annotshot", "",
                          QMessageBox.NoButton, self)
        box.setText(CLOSE_SAVE_FAILED.format(why=why))
        save = box.addButton(CLOSE_SAVE_COPY, QMessageBox.AcceptRole)
        box.addButton(CLOSE_DISCARD, QMessageBox.DestructiveRole)
        cancel = box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(save)
        box.setEscapeButton(cancel)
        return box

    def _ask_failed_write(self, why: str) -> str:
        """Show the box; "save", "discard" or "cancel" by the ROLE of the
        button pressed (Escape and the box's own close button: "cancel")."""
        box = self._failed_write_box(why)
        box.exec()
        clicked = box.clickedButton()
        role = box.buttonRole(clicked) if clicked is not None else None
        box.deleteLater()
        if role == QMessageBox.AcceptRole:
            return "save"
        if role == QMessageBox.DestructiveRole:
            return "discard"
        return "cancel"

    def closeEvent(self, event):
        self.end_key_interaction()
        if self._restart_save is not None:
            self._restart_save = None
            self._restart_pending = False
        if self._capture is not None or self._capture_pending or not self.maybe_discard():
            event.ignore()
            return
        recent.writer().waitForDone()   # every edit on disk first
        # ASSUMES: waitForDone() has returned, so this document's last write
        # has ended and its outcome is set; its queued signal may not have
        # been delivered yet.
        outcome = self.doc.last_write
        if outcome is not None and outcome.error is not None:
            answer = self._ask_failed_write(outcome.error)
            if answer == "cancel" or (answer == "save" and not self.save_as()):
                event.ignore()
                return
        self._save_editor_geometry()
        self._leave_first_welcome()
        if not self._quitting and self.can_hide_on_close():
            self.hide()
            self._bind(Document())
            if self.tray is not None:
                self.tray.notify_hidden()
            event.ignore()
            return
        self.settings.setValue(CURRENT_KEY, self.doc.path or "")
        self.hotkey.clear()
        if self.tray is not None:
            self.tray.shutdown()
        QApplication.instance().setQuitOnLastWindowClosed(True)
        self._quitting = True
        event.accept()

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
        self.pages.layout().setGeometry(self.pages.rect())
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
        self.layout().setGeometry(self.rect())
        self.pages.layout().setGeometry(self.pages.rect())
        self.view.fit_after_resize()

    # -- capture ----------------------------------------------------------
    def capture(self, mode=None) -> None:
        self._commit_capture_counts()
        self.end_key_interaction()
        if self._capture is not None or self._capture_pending:
            return
        if not self._may_record_screen() or not self.maybe_discard():
            return
        self._capture_was_visible = self.isVisible()
        self._capture_pending = True
        self.hide()
        QTimer.singleShot(CAPTURE_DELAY_MS, lambda: self._start_capture(mode))

    def _start_capture(self, mode=None) -> None:
        self._capture_pending = False
        self._capture = CaptureSession(self)
        self._capture.finished.connect(self._capture_done)
        try:
            self._capture.start(mode)
        except Exception as e:          # never leave the window hidden
            self._capture = None
            if self._capture_was_visible:
                self._show_again()
            self._warn(f"Capture failed: {e}")

    def _capture_done(self, result) -> None:
        session, self._capture = self._capture, None
        if session is not None:
            session.deleteLater()
        self._capture_pending = False
        if result is None:
            if self._capture_was_visible:
                self._show_again()
            if session is not None and session.error:
                self.statusBar().showMessage(f"Capture failed: {session.error}", 8000)
            return
        self._commit_capture_counts()
        count = self.capture_count() if self.keep_recent() else 0
        doc, png, filing_error = Document(result.image), None, None
        if count:
            try:
                png = self.recent_store.reserve()
                doc.path = str(recent.editable_for(png))
                doc._recent_source = recent.capture_source(png)
            except OSError as error:
                filing_error = str(error)
        self._bind(doc)
        self._show_again()
        self.fit_to_picture()
        if png is not None:             # never waits on the disk
            self.recent.file_capture(result.image, path=png, keep=count)
        size = f"{result.image.width()} × {result.image.height()}"
        if self.quick_copy():           # quick capture: straight out
            QApplication.clipboard().setImage(self.doc.render_image())
            self._exported()
            self.statusBar().showMessage(f"Copied {size} — {key_words(QKeySequence(QKeySequence.Paste))} to paste")
            if self.quick_minimize() and self._capture_was_visible:
                self.showMinimized()
            if filing_error:
                self._filing_failed("Could not keep the capture in Recent captures: " + filing_error)
            return
        self.statusBar().showMessage(
            f"Captured {size}" + (f" — {result.title}" if result.title else ""),
            5000)
        if filing_error:
            self._filing_failed("Could not keep the capture in Recent captures: " + filing_error)

    def _may_record_screen(self) -> bool:
        if not macos.IS_MAC or macos.screen_capture_allowed():
            return True
        if self._permission_stale:
            self._offer_permission_restart()
        else:
            self._fresh_permission(self._permission_for_capture)
        return False

    def _fresh_permission(self, callback):
        if not macos.IS_MAC or self._quitting or self._permission_process is not None:
            return
        process = QProcess(self)
        self._permission_process = process
        self._permission_callback = callback
        self._permission_expired = False
        process.finished.connect(lambda code, status: self._permission_checked(process, code, status))
        process.errorOccurred.connect(lambda error: self._permission_process_error(process, error))
        command = macos.permission_check_command()
        self._permission_timeout.start()
        process.start(command[0], command[1:])

    def _permission_process_error(self, process, error):
        if error == QProcess.FailedToStart:
            self._permission_checked(process, -1, QProcess.CrashExit)

    def _permission_check_timeout(self):
        if self._permission_process is not None:
            self._permission_expired = True
            self._permission_process.kill()

    def _permission_checked(self, process, code, status):
        if self._permission_process is not process:
            return
        self._permission_timeout.stop()
        output = bytes(process.readAllStandardOutput()).strip()
        state = "unknown"
        if not self._permission_expired and code == 0 and status == QProcess.NormalExit:
            if output in (b"allowed", b"denied", b"unknown"):
                state = output.decode("ascii")
        callback = self._permission_callback
        self._permission_process = self._permission_callback = None
        process.deleteLater()
        if callback is not None and not self._quitting:
            callback(state)

    def _permission_for_capture(self, state):
        # ASSUMES: a fresh process sees the current grant. Denied/unknown asks.
        if state == "allowed" and not macos.screen_capture_allowed():
            self._permission_granted()
            return
        macos.request_screen_capture()
        self._show_again()
        self.statusBar().showMessage(PERMISSION_STATUS)
        self._permission_message()

    def _permission_message(self) -> None:
        if self._permission_box is not None:
            return
        box = QMessageBox(QMessageBox.Information, "Annotshot",
                          PERMISSION_TEXT, QMessageBox.NoButton, self)
        settings = box.addButton("Open System Settings", QMessageBox.AcceptRole)
        restart = box.addButton("Restart Annotshot", QMessageBox.ActionRole)
        box.addButton("Not now", QMessageBox.RejectRole)
        box.setDefaultButton(settings)
        self._permission_box = box
        self._permission_deadline = time.monotonic() + 600
        self._permission_watch.start()
        box.exec()
        self._permission_box = None
        if box.clickedButton() is settings:
            macos.open_privacy_settings()
        elif box.clickedButton() is restart:
            self._request_permission_restart()
        box.deleteLater()

    def _permission_active(self, state):
        if macos.IS_MAC and state == Qt.ApplicationActive:
            self._permission_tick()

    def _permission_tick(self):
        if not self._permission_watch.isActive():
            return
        # ASSUMES: the watch ends. Expiry and quit never start another check.
        if self._quitting or time.monotonic() >= self._permission_deadline:
            self._permission_watch.stop()
            return
        self._fresh_permission(self._permission_watched)

    def _permission_watched(self, state):
        if (self._permission_watch.isActive() and
                time.monotonic() < self._permission_deadline and state == "allowed"
                and not macos.screen_capture_allowed()):
            self._permission_granted()

    def _permission_granted(self):
        if self._restart_dialog or self._restart_pending:
            return
        self._permission_watch.stop()
        self._permission_stale = not self._permission_restarted
        if self._permission_box is not None:
            self._permission_box.reject()
            self._permission_box = None
        # ASSUMES: the restarted process agrees. A denied restarted run never loops.
        self.statusBar().showMessage("Restart Annotshot to capture")
        if self._permission_restarted:
            self._restart_refused_message()
        else:
            self._offer_permission_restart()

    def _restart_refused_message(self):
        if self._permission_box is not None or self._restart_dialog or self._quitting:
            return
        self._restart_dialog = True
        box = QMessageBox(QMessageBox.Information, "Annotshot",
                          RESTART_STILL_REFUSED, QMessageBox.NoButton, self)
        restart = box.addButton("Restart Annotshot", QMessageBox.ActionRole)
        settings = box.addButton("Open System Settings", QMessageBox.AcceptRole)
        box.addButton("Not now", QMessageBox.RejectRole)
        box.setDefaultButton(restart)
        self._permission_box = box
        box.exec()
        self._permission_box = None
        self._restart_dialog = False
        if not self._quitting:
            if box.clickedButton() is restart:
                self._request_permission_restart()
            elif box.clickedButton() is settings:
                macos.open_privacy_settings()
        box.deleteLater()

    def _offer_permission_restart(self):
        if self._restart_pending or self._restart_dialog:
            return
        self.doc.end_text_edit()
        # ASSUMES: nothing is unsaved. The opposite case asks once before quit.
        # Same predicate as maybe_discard, without asking or saving here.
        if self.doc.path or not self.doc.undo_stack.needs_save():
            self._request_permission_restart()
            return
        self._restart_dialog = True
        box = QMessageBox(QMessageBox.Information, "Annotshot",
                          PERMISSION_RESTART,
                          QMessageBox.NoButton, self)
        restart = box.addButton("Restart now", QMessageBox.AcceptRole)
        box.addButton("Later", QMessageBox.RejectRole)
        box.setDefaultButton(restart)
        box.exec()
        self._restart_dialog = False
        if box.clickedButton() is restart:
            self._request_permission_restart()
        else:
            self.statusBar().showMessage("Restart Annotshot to capture")
        box.deleteLater()

    def _request_permission_restart(self):
        if self._restart_pending:
            return
        self._restart_pending = True
        self._save_before_permission_restart()

    def _save_before_permission_restart(self):
        self.doc.end_text_edit()
        if self.doc.path:
            key = (self.doc, self.doc.changes, self.doc.path)
            # ASSUMES: the write lands. A failed result cancels the restart;
            # a queued change count is not a successful write. Wait for its
            # own outcome, then recheck the current document and change count.
            if self.doc.needs_write():
                self._restart_save = key
                self.autosave_now()
                return
            if key in self._save_jobs:
                self._restart_save = key
                return
        # No write is needed, or its successful outcome has been delivered.
        self._restart_save = None
        self.quit_app()
        if not self._quitting:
            self._restart_pending = False

    def _permission_quitting(self):
        self._permission_watch.stop()
        self._permission_timeout.stop()
        self._permission_callback = None
        if self._permission_process is not None:
            self._permission_process.kill()
        if self._permission_box is not None:
            self._permission_box.reject()
        if self._restart_save is not None:
            self._restart_save = None
            self._restart_pending = False
        if self._restart_pending and macos.IS_MAC:
            self._restart_pending = False
            QProcess.startDetached("/bin/sh", ["-c", macos.RELAUNCH_WAIT,
                                   "annotshot-relaunch", str(os.getpid()),
                                   str(macos.RELAUNCH_SECONDS),
                                   *macos.permission_relaunch_command()])

    def _show_again(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
