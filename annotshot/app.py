"""Application setup (name, icon, Fusion style, the look) and main()."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import QApplication

from . import __version__, filetype, theme, typefaces
from .mainwindow import MainWindow

if sys.platform == "win32":
    from . import win32
else:                                    # macOS, Linux: no Win32 helpers
    win32 = None

ROOT = Path(__file__).resolve().parent.parent

# The look lives in theme.py: three themes (Light, Dark, Retro) filled into
# one stylesheet and one palette. Light is the look of layout study 2 ("the
# property strip under the tools"), value for value. Sizes are logical px.
FONT_FAMILY, FONT_PX = theme.FONTS[theme.DEFAULT][:2]
STYLE_SHEET = theme.style_sheet(theme.DEFAULT)      # Light, as it was


def app_icon() -> QIcon:
    for name in ("annotshot.ico", "icon.png"):
        if (ROOT / name).is_file():
            return QIcon(str(ROOT / name))
    return QIcon()


def look_palette(name: str | None = None) -> QPalette:
    return theme.palette(name)


def apply_look(app: QApplication, name: str | None = None) -> str:
    """Fusion, the theme's palette, font and stylesheet (the current theme
    when `name` is None); open windows redraw their own parts."""
    return theme.apply(app, name or theme.current())


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
    typefaces.load_bundled()        # the pixel font, on every system
    apply_look(app, theme.saved())  # Retro's UI font is that pixel font
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
    window.apply_hotkey()           # the capture key, from anywhere
    path = file_argument(argv)
    if path:
        window.open_path(path)
    else:
        problem = argument_problem(argv)
        if problem:
            window.statusBar().showMessage(problem, 10000)
    return app.exec()
