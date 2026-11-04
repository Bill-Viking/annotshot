"""Application setup (name, icon, Fusion style, the look) and main()."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import QApplication

from . import __version__, filetype
from .mainwindow import MainWindow

if sys.platform == "win32":
    from . import win32
else:                                    # macOS, Linux: no Win32 helpers
    win32 = None

ROOT = Path(__file__).resolve().parent.parent

# The look (layout study 2, "the property strip under the tools"): a light
# Fusion palette, Segoe UI 13 px, and a stylesheet for the toolbar rows and
# the strip. Sizes are logical px, so Qt scales them with the display.
FONT_FAMILY, FONT_PX = "Segoe UI", 13
PALETTE = {
    QPalette.Window: "#F6F7F9", QPalette.WindowText: "#25313D",
    QPalette.Base: "#FFFFFF", QPalette.AlternateBase: "#F6F7F9",
    QPalette.Text: "#25313D", QPalette.Button: "#FFFFFF",
    QPalette.ButtonText: "#293846", QPalette.BrightText: "#FFFFFF",
    QPalette.Highlight: "#0878D5", QPalette.HighlightedText: "#FFFFFF",
    QPalette.ToolTipBase: "#FFFFFF", QPalette.ToolTipText: "#25313D",
    QPalette.PlaceholderText: "#86909A", QPalette.Link: "#0866AC",
}
DISABLED_TEXT = "#9AA5B0"

STYLE_SHEET = """
QMainWindow { background: #F6F7F9; }
QToolTip { color: #25313D; background: #FFFFFF; border: 1px solid #C8D0DA;
           padding: 4px 6px; }

/* the two toolbar rows */
QToolBar { border: none; spacing: 4px; padding: 0px; }
QToolBar#main { background: #FFFFFF; border-bottom: 1px solid #DCE1E6; }
QToolBar#tools { background: #FBFCFD; border-bottom: 1px solid #D6DDE4;
                 spacing: 2px; }
QToolBar::separator { background: #D7DDE4; width: 1px; margin: 11px 2px; }
QToolBar#main QToolButton, QToolBar#tools QToolButton {
    color: #293846; background: transparent;
    border: 1px solid transparent; border-radius: 4px; padding: 3px 6px;
    font-size: 12px; }
QToolBar#tools QToolButton { color: #334454; padding: 3px 6px; }
/* the rows' 8 px side insets (a toolbar's padding is one value) */
QToolBar#main QToolButton#primary, QToolBar#tools QToolButton#first {
    margin-left: 8px; }
QToolBar#main QToolButton#last, QToolBar#tools QToolButton#last {
    margin-right: 8px; }
QToolBar#main QToolButton:hover, QToolBar#tools QToolButton:hover {
    background: #F1F5FA; }
QToolBar#main QToolButton:pressed, QToolBar#tools QToolButton:pressed {
    background: #E4ECF4; }
QToolBar#main QToolButton:disabled, QToolBar#tools QToolButton:disabled {
    color: #9AA5B0; }
QToolBar#tools QToolButton:checked {
    color: #086DBE; background: #E8F4FF; border-color: #B5D9F7; }
QToolBar#main QToolButton#primary {
    color: #FFFFFF; background: #0878D5; border-color: #0870C6;
    font-weight: 600; padding: 3px 10px; }
QToolBar#main QToolButton#primary:hover { background: #0A6DC0; }
QToolBar#main QToolButton#primary:pressed { background: #075FA8; }
QToolBar#main QToolButton#outline {
    color: #0866AC; background: #F6FBFF; border-color: #78B6E8;
    font-weight: 600; }
QToolBar#main QToolButton#outline:hover { background: #E9F4FE; }
/* the overflow chevron a row shows when the window is too narrow */
QToolBar#main QToolButton#qt_toolbar_ext_button,
QToolBar#tools QToolButton#qt_toolbar_ext_button {
    padding: 0px; margin: 0px; border: none; }

/* the property strip */
QToolBar#properties { background: #FBFCFD; border-bottom: 1px solid #CDD6DF;
                      padding: 0px; }
QScrollArea#stripScroll { background: transparent; border: none; }
QLabel#fieldLabel { color: #4E5D69; font-size: 12px; }
QLabel#fieldValue { color: #30404D; }
QLabel#objectHeading { color: #263644; font-weight: 600; }
QLabel#objectHeading:disabled { color: #86909A; }
QLabel#objectMark { background: #E7F3FD; border: 1px solid #98BEE1;
                    border-radius: 3px; }
QFrame#divider { background: #D9E0E6; border: none; }
QToolButton#colorField, QToolButton#field {
    color: #30404D; background: #FFFFFF; border: 1px solid #BBC6D1;
    border-radius: 4px; padding: 0px 6px; min-height: 28px;
    max-height: 28px; font-size: 12px; }
QToolButton#field { min-width: 22px; padding: 0px 4px; }
QToolButton#colorField { min-width: 72px; }
QToolButton#colorField:hover, QToolButton#field:hover {
    border-color: #8FA6BB; }
QToolButton#colorField:pressed, QToolButton#field:pressed {
    background: #EEF3F8; }
QToolButton#colorField:disabled, QToolButton#field:disabled {
    color: #A7B1BB; background: #F4F6F8; border-color: #D5DCE3; }
QFrame#segment { background: #FFFFFF; border: 1px solid #BFC9D2;
                 border-radius: 4px; }
QFrame#segment QToolButton {
    color: #31404D; background: transparent; border: none;
    border-left: 1px solid #D7DEE5; border-radius: 0px;
    min-width: 19px; min-height: 28px; max-height: 28px;
    padding: 0px 8px; }
QFrame#segment QToolButton#first { border-left: none; }
QFrame#segment QToolButton:hover { background: #F1F5FA; }
QFrame#segment QToolButton:checked { color: #1267A7; background: #E1F0FC; }
QFrame#segment QToolButton:disabled { color: #A7B1BB; }
QSlider::groove:horizontal { height: 4px; background: #D5DDE5;
                             border-radius: 2px; }
QSlider::sub-page:horizontal { background: #1D75BB; border-radius: 2px; }
QSlider::handle:horizontal { width: 13px; height: 13px; margin: -6px 0px;
                             background: #FFFFFF; border: 2px solid #1D75BB;
                             border-radius: 8px; }
QSlider::sub-page:horizontal:disabled { background: #B8C2CC; }
QSlider::handle:horizontal:disabled { border-color: #B8C2CC; }

/* the canvas and the status line */
QGraphicsView { border: none; }
QStatusBar { background: #F7F8FA; border-top: 1px solid #D4DBE2;
             color: #66727E; font-size: 12px; }
QStatusBar::item { border: none; }
QStatusBar QLabel { color: #465461; padding: 0px 6px; }
"""


def app_icon() -> QIcon:
    for name in ("annotshot.ico", "icon.png"):
        if (ROOT / name).is_file():
            return QIcon(str(ROOT / name))
    return QIcon()


def look_palette() -> QPalette:
    pal = QPalette()
    for role, color in PALETTE.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(DISABLED_TEXT))
    return pal


def apply_look(app: QApplication) -> None:
    """Fusion, the light palette, the font and the stylesheet."""
    app.setStyle("Fusion")
    font = QFont(FONT_FAMILY)
    font.setPixelSize(FONT_PX)
    app.setFont(font)
    app.setPalette(look_palette())
    app.setStyleSheet(STYLE_SHEET)


def set_app_id(app_id: str) -> None:
    """The taskbar grouping id on Windows; a no-op elsewhere."""
    if win32 is not None:
        win32.set_app_id(app_id)


def make_app(argv=None) -> QApplication:
    """The QApplication (reused if one exists), set up for Annotshot."""
    app = QApplication.instance()
    if app is None:
        set_app_id("Annotshot.Annotshot")
        app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("Annotshot")
    app.setOrganizationName("Annotshot")
    app.setApplicationVersion(__version__)
    apply_look(app)
    app.setWindowIcon(app_icon())
    return app


OTHER_PROGRAM = ("Windows opens .annotshot files with another program — "
                 "right-click one, Open with, Choose another app, Annotshot, "
                 "Always use this app")


class FileOpenFilter(QObject):
    """macOS: Finder's double-click and a drop on the Dock icon arrive as a
    FileOpen event on the application; the window opens the file.

    The window's own open guard does the rest: a file that arrives while
    an open is still running (Open…'s or another file's "Save your
    changes?" question is on screen) is kept, not opened inside that
    question; only the newest such file is kept, and it opens when the
    running open returns. So one question at a time, and the last file
    chosen is the one left open."""

    def __init__(self, window: MainWindow):
        super().__init__(window)
        self._window = window

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.FileOpen:
            path = event.file()
            if path:
                self._open(path)
            return True
        return False

    def _open(self, path: str) -> None:
        self._window.open_path(path)    # kept by the window while it is busy


def file_argument(argv) -> str | None:
    """The first argument after the program that is not an option and names
    an existing editable file."""
    for arg in list(argv)[1:]:
        if not arg.startswith("-") and filetype.is_editable_file(arg):
            return arg
    return None


def argument_problem(argv) -> str | None:
    """The status line for an argument that names an editable file which is
    not there, or a folder with an editable name; None when there is none.
    Options and arguments with other names stay silent."""
    for arg in list(argv)[1:]:
        if arg.startswith("-"):
            continue
        plain = os.path.normpath(arg)   # x.annotshot/ is the folder x.annotshot
        if not plain.lower().endswith(filetype.EXTENSIONS):
            continue
        name = os.path.basename(plain)
        if os.path.isdir(arg):
            return f"{name} is a folder, not a file"
        if not os.path.exists(arg):
            return f"Could not find {name}"
    return None


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = make_app(argv)
    window = MainWindow()           # centered at a moderate size
    filetype.register()             # Windows: the double-click, repaired
    choice = filetype.user_choice()
    if choice and not filetype.is_ours(choice):
        window.statusBar().showMessage(OTHER_PROGRAM, 10000)
    app._annotshot_file_filter = FileOpenFilter(window)
    app.installEventFilter(app._annotshot_file_filter)
    window.show()
    path = file_argument(argv)
    if path:
        window.open_path(path)
    else:
        problem = argument_problem(argv)
        if problem:
            window.statusBar().showMessage(problem, 10000)
    return app.exec()
