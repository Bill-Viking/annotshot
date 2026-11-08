"""The look: three themes (Light, Dark, Retro) filled into ONE stylesheet
template and ONE palette from named tokens.

A theme names about twenty CORE tokens (the window, the surfaces, the text,
the borders, the accent, the canvas surround, the hint, the tooltip, the
icons, the link). The stylesheet uses finer tokens (a toolbar's line, a
field's hover border, the slider ...): Light names each of them with the
exact values the app had before themes, so Light looks the same to the
pixel; Dark and Retro fill each finer token from a core one (DERIVED).

Only the program's own chrome follows the theme: the picture, the shapes,
their text and colours, and every exported image are never touched.

The choice is saved as look/theme ("light", "dark" or "retro") and read at
start, before the main window is built.
"""
from __future__ import annotations

import re

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QFont, QPalette

SETTING = "look/theme"
DEFAULT = "light"
# (key, the name the Theme pull-down shows), in the pull-down's order
CHOICES = (("light", "Light"), ("dark", "Dark"), ("retro", "Retro"))
NAMES = tuple(k for k, _ in CHOICES)

CORE = ("window", "surface", "surface-2", "text", "text-dim",
        "text-disabled", "border", "border-strong", "accent", "accent-text",
        "accent-hover", "accent-pressed", "accent-soft", "accent-soft-border",
        "canvas", "hint", "tooltip-bg", "tooltip-text", "icon",
        "icon-checked", "link", "error")

# Every finer token, and the core token Dark and Retro take it from.
DERIVED = {
    "tooltip-border": "border-strong",
    "bar-main": "surface", "bar-main-line": "border",
    "bar-tools": "surface-2", "bar-tools-line": "border",
    "separator": "border",
    "button-text": "text", "tool-text": "text",
    "hover": "border", "pressed": "border-strong",
    "checked-text": "icon-checked",
    "accent-border": "accent-pressed",
    "outline-bg": "accent-soft", "outline-border": "accent-soft-border",
    "outline-hover": "accent-soft-border",
    "bar-props": "surface-2", "bar-props-line": "border",
    "field-label": "text-dim", "field-text": "text",
    "heading": "text", "heading-disabled": "text-dim",
    "mark-bg": "accent-soft", "mark-border": "accent-soft-border",
    "divider": "border",
    "field-bg": "surface", "field-border": "border-strong",
    "field-hover": "accent-soft-border", "field-pressed": "surface-2",
    "field-disabled-text": "text-disabled", "field-disabled-bg": "window",
    "field-disabled-border": "border",
    "segment-border": "border-strong", "segment-text": "text",
    "segment-line": "border",
    "segment-checked-text": "icon-checked",
    "segment-checked-bg": "accent-soft",
    "slider-groove": "border-strong", "slider": "accent",
    "slider-disabled": "text-disabled",
    "status-bg": "window", "status-line": "border",
    "status-text": "text-dim", "status-label": "text-dim",
    # outside the stylesheet: the palette, the canvas, the icons, the panes
    "placeholder": "text-dim", "bright-text": "accent-text",
    "select": "accent", "handle-fill": "surface",
    "icon-disabled": "text-disabled",
    "capture-icon": "accent-text", "capture-icon-disabled": "accent-soft-border",
    "copy-icon": "link", "mark-ink": "icon-checked",
    "font-separator": "border",
    "thumb-ground": "canvas", "time-ink": "text-dim",
}

# The fonts: Light and Dark keep the system font at the size it had; Retro
# is the bundled pixel font, which needs the bigger size to be legible.
FONTS = {
    "light": ("Segoe UI", 13, 12),     # (family, ui px, small px)
    "dark": ("Segoe UI", 13, 12),
    "retro": ("VT323", 17, 16),
}

THEMES = {
    # Light: the values the app had before themes, every one of them.
    "light": {
        "window": "#F6F7F9", "surface": "#FFFFFF", "surface-2": "#FBFCFD",
        "text": "#25313D", "text-dim": "#66727E", "text-disabled": "#9AA5B0",
        "border": "#DCE1E6", "border-strong": "#BBC6D1",
        "accent": "#0878D5", "accent-text": "#FFFFFF",
        "accent-hover": "#0A6DC0", "accent-pressed": "#075FA8",
        "accent-soft": "#E8F4FF", "accent-soft-border": "#B5D9F7",
        "canvas": "#E9EDF2", "hint": "#7D8994",
        "tooltip-bg": "#FFFFFF", "tooltip-text": "#25313D",
        "icon": "#334454", "icon-checked": "#086DBE", "link": "#0866AC",
        "error": "#B3261E",
        # the finer tokens, at their exact values
        "tooltip-border": "#C8D0DA",
        "bar-main": "#FFFFFF", "bar-main-line": "#DCE1E6",
        "bar-tools": "#FBFCFD", "bar-tools-line": "#D6DDE4",
        "separator": "#D7DDE4",
        "button-text": "#293846", "tool-text": "#334454",
        "hover": "#F1F5FA", "pressed": "#E4ECF4",
        "checked-text": "#086DBE",
        "accent-border": "#0870C6",
        "outline-bg": "#F6FBFF", "outline-border": "#78B6E8",
        "outline-hover": "#E9F4FE",
        "bar-props": "#FBFCFD", "bar-props-line": "#CDD6DF",
        "field-label": "#4E5D69", "field-text": "#30404D",
        "heading": "#263644", "heading-disabled": "#86909A",
        "mark-bg": "#E7F3FD", "mark-border": "#98BEE1",
        "divider": "#D9E0E6",
        "field-bg": "#FFFFFF", "field-border": "#BBC6D1",
        "field-hover": "#8FA6BB", "field-pressed": "#EEF3F8",
        "field-disabled-text": "#A7B1BB", "field-disabled-bg": "#F4F6F8",
        "field-disabled-border": "#D5DCE3",
        "segment-border": "#BFC9D2", "segment-text": "#31404D",
        "segment-line": "#D7DEE5",
        "segment-checked-text": "#1267A7", "segment-checked-bg": "#E1F0FC",
        "slider-groove": "#D5DDE5", "slider": "#1D75BB",
        "slider-disabled": "#B8C2CC",
        "status-bg": "#F7F8FA", "status-line": "#D4DBE2",
        "status-text": "#66727E", "status-label": "#465461",
        "placeholder": "#86909A", "bright-text": "#FFFFFF",
        "select": "#1E88E5", "handle-fill": "#FFFFFF",
        "icon-disabled": "#A7B1BB",
        "capture-icon": "#FFFFFF", "capture-icon-disabled": "#DCE9F5",
        "copy-icon": "#0866AC", "mark-ink": "#1267A7",
        "font-separator": "#D7DDE4",
        "thumb-ground": "#E9EDF1", "time-ink": "#7A8591",
    },
    "dark": {
        "window": "#1C2228", "surface": "#242B33", "surface-2": "#2A323B",
        "text": "#DDE4EB", "text-dim": "#9AA7B4", "text-disabled": "#5F6B77",
        "border": "#39434E", "border-strong": "#4A5662",
        "accent": "#3B9CF0", "accent-text": "#FFFFFF",
        "accent-hover": "#4EA8F5", "accent-pressed": "#2F86D3",
        "accent-soft": "#1B3350", "accent-soft-border": "#2E5680",
        "canvas": "#12171C", "hint": "#6F7C89",
        "tooltip-bg": "#2A323B", "tooltip-text": "#DDE4EB",
        "icon": "#C9D3DD", "icon-checked": "#6FB8F7", "link": "#7CC0F7",
        "error": "#F28B82",
    },
    "retro": {
        "window": "#0B0B0B", "surface": "#121212", "surface-2": "#161616",
        "text": "#FFB000", "text-dim": "#B37C00", "text-disabled": "#5A4200",
        "border": "#3A2A00", "border-strong": "#6B4F00",
        "accent": "#FFB000", "accent-text": "#0B0B0B",
        "accent-hover": "#FFC133", "accent-pressed": "#E09A00",
        "accent-soft": "#1F1600", "accent-soft-border": "#5C4300",
        "canvas": "#050505", "hint": "#7A5A00",
        "tooltip-bg": "#161616", "tooltip-text": "#FFB000",
        "icon": "#FFB000", "icon-checked": "#FFD24D", "link": "#FFC133",
        "error": "#FF6A3D",
    },
}

# The one stylesheet: @token is a colour, @small-px the small text's size.
# Row 2's labelled tools pad 2 px left of the icon and none after the label
# (Qt already pads a tool button's label with a space each side).
# ASSUMES: the rows are sized for the widest of the three CI fonts (Linux's
# DejaVu Sans); test_nothing_hides_behind_the_overflow_on_a_wide_font lays
# them out at 900 px in a face 1.18 x the Mac's.
TEMPLATE = """
QMainWindow { background: @window; }
QToolTip { color: @tooltip-text; background: @tooltip-bg; border: 1px solid @tooltip-border;
           padding: 4px 6px; }

/* the two toolbar rows */
QToolBar { border: none; spacing: 4px; padding: 0px; }
QToolBar#main { background: @bar-main; border-bottom: 1px solid @bar-main-line; }
QToolBar#tools { background: @bar-tools; border-bottom: 1px solid @bar-tools-line;
                 spacing: 2px; }
QToolBar::separator { background: @separator; width: 1px; margin: 11px 2px; }
QToolBar#main QToolButton, QToolBar#tools QToolButton {
    color: @button-text; background: transparent;
    border: 1px solid transparent; border-radius: 4px; padding: 3px 6px;
    font-size: @small-px; }
QToolBar#tools QToolButton { color: @tool-text; padding: 3px 0px 3px 2px; }
/* row 2's icon-only buttons (Duplicate, Front, Back, Delete): narrower, so
   nine labelled tools and the four fit a 900 px window */
QToolBar#tools QToolButton[iconOnly="true"] { padding: 3px 3px; }
/* the rows' 8 px side insets (a toolbar's padding is one value) */
QToolBar#main QToolButton#primary, QToolBar#tools QToolButton#first {
    margin-left: 8px; }
QToolBar#main QToolButton#last, QToolBar#tools QToolButton#last {
    margin-right: 8px; }
QToolBar#main QToolButton:hover, QToolBar#tools QToolButton:hover {
    background: @hover; }
QToolBar#main QToolButton:pressed, QToolBar#tools QToolButton:pressed {
    background: @pressed; }
QToolBar#main QToolButton:disabled, QToolBar#tools QToolButton:disabled {
    color: @text-disabled; }
QToolBar#tools QToolButton:checked {
    color: @checked-text; background: @accent-soft; border-color: @accent-soft-border; }
QToolBar#main QToolButton#primary {
    color: @accent-text; background: @accent; border-color: @accent-border;
    font-weight: 600; padding: 3px 10px; }
QToolBar#main QToolButton#primary:hover { background: @accent-hover; }
QToolBar#main QToolButton#primary:pressed { background: @accent-pressed; }
QToolBar#main QToolButton#outline {
    color: @link; background: @outline-bg; border-color: @outline-border;
    font-weight: 600; }
QToolBar#main QToolButton#outline:hover { background: @outline-hover; }
/* the overflow chevron a row shows when the window is too narrow */
QToolBar#main QToolButton#qt_toolbar_ext_button,
QToolBar#tools QToolButton#qt_toolbar_ext_button {
    padding: 0px; margin: 0px; border: none; }

/* the property strip */
QToolBar#properties { background: @bar-props; border-bottom: 1px solid @bar-props-line;
                      padding: 0px; }
QScrollArea#stripScroll { background: transparent; border: none; }
QLabel#fieldLabel { color: @field-label; font-size: @small-px; }
QLabel#fieldValue { color: @field-text; }
QLabel#objectHeading { color: @heading; font-weight: 600; }
QLabel#objectHeading:disabled { color: @heading-disabled; }
QLabel#objectMark { background: @mark-bg; border: 1px solid @mark-border;
                    border-radius: 3px; }
QFrame#divider { background: @divider; border: none; }
QToolButton#colorField, QToolButton#field {
    color: @field-text; background: @field-bg; border: 1px solid @field-border;
    border-radius: 4px; padding: 0px 6px; min-height: 28px;
    max-height: 28px; font-size: @small-px; }
QToolButton#field { min-width: 22px; padding: 0px 4px; }
QToolButton#colorField { min-width: 72px; }
QToolButton#colorField:hover, QToolButton#field:hover {
    border-color: @field-hover; }
QToolButton#colorField:pressed, QToolButton#field:pressed {
    background: @field-pressed; }
QToolButton#colorField:disabled, QToolButton#field:disabled {
    color: @field-disabled-text; background: @field-disabled-bg; border-color: @field-disabled-border; }
QFrame#segment { background: @field-bg; border: 1px solid @segment-border;
                 border-radius: 4px; }
QFrame#segment QToolButton {
    color: @segment-text; background: transparent; border: none;
    border-left: 1px solid @segment-line; border-radius: 0px;
    min-width: 19px; min-height: 28px; max-height: 28px;
    padding: 0px 8px; }
QFrame#segment QToolButton#first { border-left: none; }
QFrame#segment QToolButton:hover { background: @hover; }
QFrame#segment QToolButton:checked { color: @segment-checked-text; background: @segment-checked-bg; }
QFrame#segment QToolButton:disabled { color: @field-disabled-text; }
QSlider::groove:horizontal { height: 4px; background: @slider-groove;
                             border-radius: 2px; }
QSlider::sub-page:horizontal { background: @slider; border-radius: 2px; }
QSlider::handle:horizontal { width: 13px; height: 13px; margin: -6px 0px;
                             background: @field-bg; border: 2px solid @slider;
                             border-radius: 8px; }
QSlider::sub-page:horizontal:disabled { background: @slider-disabled; }
QSlider::handle:horizontal:disabled { border-color: @slider-disabled; }

/* the canvas and the status line */
QGraphicsView { border: none; }
QStatusBar { background: @status-bg; border-top: 1px solid @status-line;
             color: @status-text; font-size: @small-px; }
QStatusBar::item { border: none; }
QStatusBar QLabel { color: @status-label; padding: 0px 6px; }
"""

_TOKEN = re.compile(r"@([a-z][a-z0-9-]*)")
_current = DEFAULT
_filled: dict[str, dict] = {}       # theme -> its tokens, filled once


def normalise(name) -> str:
    """A theme key; anything unknown (an old or damaged setting) is Light."""
    name = str(name or "").strip().lower()
    return name if name in THEMES else DEFAULT


def tokens(name: str | None = None) -> dict:
    """Every token of the theme `name` (the current one when None): its own
    values, and each finer token it does not name filled from DERIVED."""
    name = normalise(name or _current)
    if name not in _filled:
        t = dict(THEMES[name])
        for fine, core in DERIVED.items():
            t.setdefault(fine, t[core])
        t["small-px"] = f"{FONTS[name][2]}px"
        _filled[name] = t
    return _filled[name]


def current() -> str:
    return _current


def color(token: str, name: str | None = None) -> QColor:
    return QColor(tokens(name)[token])


def style_sheet(name: str | None = None) -> str:
    t = tokens(name)
    return _TOKEN.sub(lambda m: t[m.group(1)], TEMPLATE)


PALETTE_ROLES = (
    (QPalette.Window, "window"), (QPalette.WindowText, "text"),
    (QPalette.Base, "surface"), (QPalette.AlternateBase, "window"),
    (QPalette.Text, "text"), (QPalette.Button, "surface"),
    (QPalette.ButtonText, "button-text"), (QPalette.BrightText, "bright-text"),
    (QPalette.Highlight, "accent"), (QPalette.HighlightedText, "accent-text"),
    (QPalette.ToolTipBase, "tooltip-bg"), (QPalette.ToolTipText, "tooltip-text"),
    (QPalette.PlaceholderText, "placeholder"), (QPalette.Link, "link"),
)
# Fusion draws frames and bevels from these; Light leaves them at Qt's own
# (as it always did), Dark and Retro set them so no light bevel shows.
BEVEL_ROLES = ((QPalette.Light, "surface-2"), (QPalette.Midlight, "border"),
               (QPalette.Mid, "border-strong"), (QPalette.Dark, "window"),
               (QPalette.Shadow, "window"), (QPalette.LinkVisited, "link"))


def palette(name: str | None = None) -> QPalette:
    name = normalise(name or _current)
    t = tokens(name)
    pal = QPalette()
    for role, token in PALETTE_ROLES:
        pal.setColor(role, QColor(t[token]))
    if name != DEFAULT:
        for role, token in BEVEL_ROLES:
            pal.setColor(role, QColor(t[token]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(t["text-disabled"]))
    return pal


def font(name: str | None = None) -> QFont:
    family, ui_px, _small = FONTS[normalise(name or _current)]
    f = QFont(family)
    f.setPixelSize(ui_px)
    return f


def ui_scale(name: str | None = None) -> float:
    """How much bigger the theme's text is than Light's (the empty hint)."""
    return FONTS[normalise(name or _current)][1] / FONTS[DEFAULT][1]


def saved() -> str:
    """The theme saved in the settings (Light when none or unknown)."""
    return normalise(QSettings("Annotshot", "Annotshot").value(SETTING,
                                                               DEFAULT))


def save(name: str) -> None:
    QSettings("Annotshot", "Annotshot").setValue(SETTING, normalise(name))


def apply(app, name: str | None = None) -> str:
    """Fusion, the theme's font, palette and stylesheet on the whole app;
    then every open window that has a retheme() redraws what it paints
    itself (icons, the canvas, the panes). Returns the theme applied."""
    global _current
    _current = normalise(name)
    app.setStyle("Fusion")
    app.setFont(font())
    app.setPalette(palette())
    app.setStyleSheet(style_sheet())
    for w in app.topLevelWidgets():
        retheme = getattr(w, "retheme", None)
        if callable(retheme):
            retheme()
    return _current
