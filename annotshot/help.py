"""About Annotshot and Help.

One function, `about_widget`, builds the About content for both places it
shows: the About Annotshot… window (the right-click menu) and the Settings
window's About tab. `HelpWindow` shows the user manual the app carries, with
the user's own keys at the top, and two buttons to the project's pages.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QKeySequence, QTextCursor
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QTextBrowser,
                               QVBoxLayout, QWidget)

from . import __version__

PUBLISHER = "Viking Software"
PROJECT_URL = "https://github.com/Bill-Viking/annotshot"
ISSUES_URL = PROJECT_URL + "/issues"
MANUAL_URL = PROJECT_URL + "/blob/main/docs/USER-MANUAL.md"
ABOUT_LINE = ("Capture a region or a window, annotate it, copy or save it, "
              "and keep the project editable.")
LICENCE_LINE = "MIT licence"
NO_NOTICES = "No notices are bundled with this copy of Annotshot."
NO_MANUAL = ("The user manual is not in this copy of Annotshot. "
             "Click Open on GitHub to read it there.")
NO_KEY = "no key"
ICON_SIZE = 64


def open_url(url: str) -> bool:
    """Open a page in the browser (the one place the app does)."""
    return QDesktopServices.openUrl(QUrl(url))


def _root() -> Path:
    from .__main__ import app_root
    return app_root()


# -- About ----------------------------------------------------------------------
def about_widget(parent=None, on_help=None) -> QWidget:
    """The About content: the icon, name and version, one line of what it
    does, the publisher, the project page, the licence, and the buttons for
    the third-party notices (and Help, when `on_help` is given)."""
    from .app import app_icon
    w = QWidget(parent)
    w.setObjectName("about")
    box = QVBoxLayout(w)
    box.setSpacing(8)
    icon = QLabel(w)
    icon.setObjectName("aboutIcon")
    icon.setPixmap(app_icon().pixmap(QSize(ICON_SIZE, ICON_SIZE)))
    icon.setFixedSize(ICON_SIZE, ICON_SIZE)
    name = QLabel(f"Annotshot {__version__}", w)
    name.setObjectName("aboutName")
    big = QFont(name.font())
    if big.pointSizeF() > 0:
        big.setPointSizeF(big.pointSizeF() * 1.5)
    else:                           # a font sized in pixels (the style sheet)
        big.setPixelSize(round(max(big.pixelSize(), 12) * 1.5))
    big.setBold(True)
    name.setFont(big)
    head = QHBoxLayout()
    head.addWidget(icon)
    head.addSpacing(10)
    head.addWidget(name, 1)
    box.addLayout(head)
    line = QLabel(ABOUT_LINE, w)
    line.setWordWrap(True)
    box.addWidget(line)
    box.addWidget(QLabel(PUBLISHER, w))
    link = QLabel(f'<a href="{PROJECT_URL}">{PROJECT_URL}</a>', w)
    link.setObjectName("aboutLink")
    link.setTextFormat(Qt.RichText)
    link.setTextInteractionFlags(Qt.TextBrowserInteraction)
    link.setOpenExternalLinks(True)
    box.addWidget(link)
    box.addWidget(QLabel(LICENCE_LINE, w))
    buttons = QHBoxLayout()
    notices = QPushButton("Third-party notices", w)
    notices.setObjectName("noticesButton")
    notices.clicked.connect(lambda: show_notices(w.window()))
    buttons.addWidget(notices)
    if on_help is not None:
        help_button = QPushButton("Help", w)
        help_button.setObjectName("helpButton")
        help_button.clicked.connect(on_help)
        buttons.addWidget(help_button)
    buttons.addStretch(1)
    box.addLayout(buttons)
    box.addStretch(1)
    return w


class AboutDialog(QDialog):
    def __init__(self, parent=None, on_help=None):
        super().__init__(parent)
        self.setWindowTitle("About Annotshot")
        box = QVBoxLayout(self)
        self.about = about_widget(self, on_help)
        box.addWidget(self.about)
        close = QDialogButtonBox(QDialogButtonBox.Close, self)
        close.rejected.connect(self.reject)
        box.addWidget(close)


# -- the third-party notices ------------------------------------------------------
def notice_files(root: Path | None = None) -> list[Path]:
    """The notice and licence texts the app carries: THIRD-PARTY-NOTICES.md
    and LICENSE (in a public build), then every text in the licences
    folder."""
    from .__main__ import licence_folder
    root = _root() if root is None else root
    files = [root / n for n in ("THIRD-PARTY-NOTICES.md", "LICENSE")
             if (root / n).is_file()]
    folder = licence_folder(root)
    if folder.is_dir():
        files += sorted(p for p in folder.iterdir() if p.is_file())
    return files


def notices_text(root: Path | None = None) -> str:
    parts = []
    for path in notice_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            text = f"(could not read it: {e})"
        rule = "=" * 72
        parts.append(f"{rule}\n{path.name}\n{rule}\n\n{text.strip()}\n")
    return "\n\n".join(parts) if parts else NO_NOTICES


class TextWindow(QDialog):
    """A read-only text that scrolls (the notices)."""

    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setPlainText(text)
        self.text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        close = QDialogButtonBox(QDialogButtonBox.Close, self)
        close.rejected.connect(self.reject)
        box = QVBoxLayout(self)
        box.addWidget(self.text)
        box.addWidget(close)
        self.resize(700, 600)


def show_notices(parent=None) -> TextWindow:
    window = TextWindow("Third-party notices", notices_text(), parent)
    window.setAttribute(Qt.WA_DeleteOnClose)
    window.show()
    return window


# -- Help ---------------------------------------------------------------------------
def _cell(text: str) -> str:
    """Text safe inside a Markdown table cell."""
    for ch in "\\|[]*_`":
        text = text.replace(ch, "\\" + ch)
    return text


def keys_text(seqs) -> str:
    keys = [s.toString(QKeySequence.NativeText) for s in seqs if not s.isEmpty()]
    return " or ".join(keys) if keys else NO_KEY


def shortcuts_markdown(rows) -> str:
    """The Keyboard shortcuts section from (what it does, [key sequences])."""
    lines = ["## Keyboard shortcuts", "",
             "Your keys as they are set now (change them in **Settings…**). "
             "The table further down lists the keys Annotshot starts with.",
             "", "| Keys | Does |", "|---|---|"]
    lines += [f"| {_cell(keys_text(seqs))} | {_cell(name)} |"
              for name, seqs in rows]
    return "\n".join(lines) + "\n"


def manual_text(root: Path | None = None) -> str | None:
    from .__main__ import MANUAL
    path = (_root() if root is None else root) / MANUAL
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def help_markdown(rows, manual: str | None) -> str:
    """The manual with the live shortcuts section inserted at its top: after
    its title and date line, before its first section."""
    keys = shortcuts_markdown(rows)
    if manual is None:
        return f"# Annotshot help\n\n{NO_MANUAL}\n\n{keys}"
    lines = manual.splitlines()
    at = next((i for i, l in enumerate(lines) if l.startswith("## ")),
              len(lines))
    return "\n".join(lines[:at]) + "\n\n" + keys + "\n" + "\n".join(lines[at:])


class HelpWindow(QDialog):
    """The manual, the user's own keys at the top, and two buttons to the
    project's pages. It does not block the editor."""

    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Annotshot help")
        self.setModal(False)
        self.browser = QTextBrowser(self)
        self.browser.setOpenExternalLinks(True)
        self.github = QPushButton("Open on GitHub", self)
        self.github.setToolTip(MANUAL_URL)
        self.github.clicked.connect(lambda: open_url(MANUAL_URL))
        self.report = QPushButton("Report a problem", self)
        self.report.setToolTip(ISSUES_URL)
        self.report.clicked.connect(lambda: open_url(ISSUES_URL))
        close = QDialogButtonBox(QDialogButtonBox.Close, self)
        close.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self.github)
        bottom.addWidget(self.report)
        bottom.addStretch(1)
        bottom.addWidget(close)
        box = QVBoxLayout(self)
        box.addWidget(self.browser)
        box.addLayout(bottom)
        self.resize(760, 720)
        self.refresh(rows)

    def refresh(self, rows) -> None:
        """Show the manual again with the keys as they are now. Pictures
        the manual names that are not on this computer are left out."""
        from .__main__ import MANUAL
        self.browser.setSearchPaths([str(_root() / MANUAL.parent)])
        self.browser.setMarkdown(help_markdown(rows, manual_text()))
        self.browser.moveCursor(QTextCursor.Start)
