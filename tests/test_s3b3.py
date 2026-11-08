"""Round 2 (C): themes -- Light, Dark, Retro. Offscreen; every setting a test
writes is in its own tmp ini (conftest), and the app is back in Light after
each test (conftest's light_theme_after)."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# -- the baseline: the look exactly as it was before themes (copied from
#    annotshot/app.py at a78a96b, never generated) ---------------------------
BASELINE_FONT = ("Segoe UI", 13)
BASELINE_PALETTE = {        # QPalette role name -> colour
    "Window": "#F6F7F9", "WindowText": "#25313D",
    "Base": "#FFFFFF", "AlternateBase": "#F6F7F9",
    "Text": "#25313D", "Button": "#FFFFFF",
    "ButtonText": "#293846", "BrightText": "#FFFFFF",
    "Highlight": "#0878D5", "HighlightedText": "#FFFFFF",
    "ToolTipBase": "#FFFFFF", "ToolTipText": "#25313D",
    "PlaceholderText": "#86909A", "Link": "#0866AC",
}
BASELINE_DISABLED_TEXT = "#9AA5B0"
BASELINE_OTHER = {          # the chrome colours outside the stylesheet
    "canvas": "#E9EDF2", "hint": "#7D8994", "select": "#1E88E5",
    "handle-fill": "#FFFFFF", "icon": "#334454", "icon-checked": "#086DBE",
    "icon-disabled": "#A7B1BB", "capture-icon": "#FFFFFF",
    "capture-icon-disabled": "#DCE9F5", "copy-icon": "#0866AC",
    "mark-ink": "#1267A7", "font-separator": "#D7DDE4",
    "thumb-ground": "#E9EDF1", "time-ink": "#7A8591", "error": "#B3261E",
}
# One ruled change since: row 2's tools pad 3px 0px 3px 2px (was 3px 4px),
# fix round s5a, so the row fits 900 px on Linux's DejaVu Sans.
BASELINE_STYLE_SHEET = '''
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
QToolBar#tools QToolButton { color: #334454; padding: 3px 0px 3px 2px; }
/* row 2's icon-only buttons (Duplicate, Front, Back, Delete): narrower, so
   nine labelled tools and the four fit a 900 px window */
QToolBar#tools QToolButton[iconOnly="true"] { padding: 3px 3px; }
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
'''

DARK = {
    "window": "#1C2228", "surface": "#242B33", "surface-2": "#2A323B",
    "text": "#DDE4EB", "text-dim": "#9AA7B4", "text-disabled": "#5F6B77",
    "border": "#39434E", "border-strong": "#4A5662", "accent": "#3B9CF0",
    "accent-text": "#FFFFFF", "accent-hover": "#4EA8F5",
    "accent-pressed": "#2F86D3", "accent-soft": "#1B3350",
    "accent-soft-border": "#2E5680", "canvas": "#12171C", "hint": "#6F7C89",
    "icon": "#C9D3DD", "icon-checked": "#6FB8F7", "link": "#7CC0F7"}
RETRO = {
    "window": "#0B0B0B", "surface": "#121212", "surface-2": "#161616",
    "text": "#FFB000", "text-dim": "#B37C00", "text-disabled": "#5A4200",
    "border": "#3A2A00", "border-strong": "#6B4F00", "accent": "#FFB000",
    "accent-text": "#0B0B0B", "accent-hover": "#FFC133",
    "accent-pressed": "#E09A00", "accent-soft": "#1F1600",
    "accent-soft-border": "#5C4300", "canvas": "#050505", "hint": "#7A5A00",
    "icon": "#FFB000", "icon-checked": "#FFD24D", "link": "#FFC133"}


@pytest.fixture
def window(qapp):
    from annotshot.app import make_app
    from annotshot.mainwindow import MainWindow
    make_app()
    w = MainWindow()
    w.resize(1100, 720)
    yield w
    w.deleteLater()


def _hex(c) -> str:
    return c.name().upper()


# -- 1. one look, three themes ------------------------------------------------
def test_light_is_the_look_before_themes_exactly(qapp):
    from PySide6.QtGui import QPalette
    from annotshot import app, theme
    assert theme.style_sheet("light") == BASELINE_STYLE_SHEET
    assert app.STYLE_SHEET == BASELINE_STYLE_SHEET
    pal = theme.palette("light")
    for role, value in BASELINE_PALETTE.items():
        assert _hex(pal.color(getattr(QPalette, role))) == value, role
    for role in ("WindowText", "Text", "ButtonText"):
        assert _hex(pal.color(QPalette.Disabled, getattr(QPalette, role))) \
            == BASELINE_DISABLED_TEXT
    t = theme.tokens("light")
    for token, value in BASELINE_OTHER.items():
        assert t[token] == value, token
    f = theme.font("light")
    assert (f.family(), f.pixelSize()) == BASELINE_FONT


@pytest.mark.parametrize("name, ruled", [("dark", DARK), ("retro", RETRO)])
def test_dark_and_retro_carry_the_ruled_values(name, ruled):
    from annotshot import theme
    t = theme.tokens(name)
    for token, value in ruled.items():
        assert t[token] == value, (name, token)


@pytest.mark.parametrize("name", ["light", "dark", "retro"])
def test_every_token_is_filled(name):
    from annotshot import theme
    qss = theme.style_sheet(name)
    assert "@" not in qss
    t = theme.tokens(name)
    for token in (*theme.CORE, *theme.DERIVED):
        assert t[token].startswith("#") and len(t[token]) == 7, token


def test_the_three_themes_and_their_fonts(qapp):
    from annotshot import theme, typefaces
    typefaces.load_bundled()
    assert [k for k, _ in theme.CHOICES] == ["light", "dark", "retro"]
    assert [n for _, n in theme.CHOICES] == ["Light", "Dark", "Retro"]
    theme.apply(qapp, "retro")
    assert qapp.font().family() == "VT323"
    assert qapp.font().pixelSize() == 17
    theme.apply(qapp, "dark")
    assert (qapp.font().family(), qapp.font().pixelSize()) == BASELINE_FONT


def test_an_unknown_setting_is_light():
    from annotshot import theme
    assert theme.normalise("Neon") == "light"
    assert theme.normalise(None) == "light"
    assert theme.normalise("DARK") == "dark"


def test_the_document_is_byte_identical_under_every_theme(window, qapp):
    """The picture, the shapes and their text are the document's own: the
    exported image does not change with the theme."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QImage
    from annotshot import scene, theme
    from annotshot.tools import Tool, drag_geom, make_item
    img = QImage(400, 240, QImage.Format_RGB32)
    img.fill(QColor("#C0D0E0"))
    doc = window.doc
    doc.set_base(img)
    items = []
    for tool, a, b in ((Tool.RECT, (20, 20), (120, 90)),
                       (Tool.ARROW, (150, 30), (300, 150)),
                       (Tool.TEXT, (40, 140), (220, 200)),
                       (Tool.HIGHLIGHT, (250, 160), (380, 220))):
        it = make_item(tool)
        it.set_geom(drag_geom(tool, QPointF(*a), QPointF(*b), True))
        if tool is Tool.TEXT:
            it.apply_props({"text": "Theme-proof"})
        items.append(it)
    doc.add_items(items)
    doc.select_only(items[:2])          # handles are never in the export
    shots = {}
    for name in ("light", "dark", "retro"):
        theme.apply(qapp, name)
        shots[name] = scene.png_bytes(doc.render_image())
    assert shots["light"] == shots["dark"] == shots["retro"]


def test_the_canvas_surround_and_hint_follow_the_theme(window, qapp):
    from annotshot import theme
    window.show()                       # offscreen: nothing on the screen
    for name in ("light", "dark", "retro"):
        window.set_theme(name)
        qapp.processEvents()
        shot = window.view.viewport().grab().toImage()
        corner = shot.pixelColor(2, 2)
        assert _hex(corner) == theme.tokens(name)["canvas"], name
    window.hide()


def test_the_selection_handles_read_their_token(qapp):
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtCore import QPointF
    from annotshot import theme
    from annotshot.scene import Document
    from annotshot.tools import Tool, drag_geom, make_item
    doc = Document()
    it = make_item(Tool.RECT)
    it.set_geom(drag_geom(Tool.RECT, QPointF(20, 20), QPointF(120, 90), True))
    doc.add_items([it])
    doc.select_only([it])
    theme.apply(qapp, "retro")
    img = QImage(200, 140, QImage.Format_ARGB32)
    img.fill(QColor("#000000"))
    p = QPainter(img)
    it.paint_selection(p)
    p.end()
    seen = {img.pixelColor(x, y).name().upper()
            for x in range(img.width()) for y in range(img.height())}
    assert theme.tokens("retro")["select"] in seen
    assert "#1E88E5" not in seen


# -- 2. icons follow the theme --------------------------------------------------
def test_themed_svg_carries_no_light_ink():
    from annotshot import mainwindow, theme
    for svg in mainwindow.ICON_DIR.glob("*.svg"):
        for name in ("dark", "retro"):
            text = mainwindow.themed_svg(svg.stem, theme.tokens(name)["icon"])
            assert "#334454" not in text, (svg.name, name)
            assert theme.tokens(name)["icon"] in text


def test_an_unknown_icon_is_empty(qapp):
    from annotshot.mainwindow import themed_icon
    assert themed_icon("no-such-icon", "dark").isNull()
    assert not themed_icon("open", "dark").isNull()


def _ink(icon, on=False):
    """The darkest-alpha colours an icon is drawn in."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QIcon
    img = icon.pixmap(QSize(40, 40), 1.0, QIcon.Normal,
                      QIcon.On if on else QIcon.Off).toImage()
    return {img.pixelColor(x, y).name().upper()
            for x in range(img.width()) for y in range(img.height())
            if img.pixelColor(x, y).alpha() == 255}


def test_the_icons_take_the_theme_inks(qapp):
    from annotshot.mainwindow import themed_icon
    from annotshot import theme
    for name in ("light", "dark", "retro"):
        t = theme.tokens(name)
        assert _ink(themed_icon("rect", name)) == {t["icon"]}
        assert _ink(themed_icon("rect", name), on=True) == {t["icon-checked"]}


def test_changing_the_theme_rebuilds_every_icon(window, qapp):
    from annotshot import theme
    actions = [window.a_open, window.a_capture, window.a_copy,
               *window.tool_actions.values(), window.a_delete]
    before = [a.icon().cacheKey() for a in actions]
    window.set_theme("dark")
    after = [a.icon().cacheKey() for a in actions]
    assert all(b != a for b, a in zip(before, after))
    assert _ink(window.a_open.icon()) == {theme.tokens("dark")["icon"]}
    for b in window.align_buttons.values():
        assert _ink(b.icon()) == {theme.tokens("dark")["icon"]}


# -- 3. Settings -> Look ----------------------------------------------------------
def test_the_look_tab_sits_before_about(window):
    from annotshot.settings_dialog import SettingsDialog
    d = SettingsDialog(window)
    tabs = [d.tabs.tabText(i) for i in range(d.tabs.count())]
    assert tabs == ["Shortcuts", "Capture", "Look", "About"]
    assert [d.theme_box.itemText(i) for i in range(d.theme_box.count())] \
        == ["Light", "Dark", "Retro"]
    d.deleteLater()


def test_picking_a_theme_applies_and_is_saved(window, qapp, private_settings):
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QPalette
    from annotshot import theme
    from annotshot.settings_dialog import SettingsDialog
    d = SettingsDialog(window)
    for i, name in ((1, "dark"), (2, "retro"), (0, "light")):
        d.theme_box.setCurrentIndex(i)
        assert theme.current() == name
        want = theme.tokens(name)["window"]
        assert _hex(qapp.palette().color(QPalette.Window)) == want
        assert _hex(window.palette().color(QPalette.Window)) == want
        assert _hex(d.palette().color(QPalette.Window)) == want
        assert QSettings(private_settings, QSettings.IniFormat).value(
            theme.SETTING) == name
        assert theme.saved() == name
        red = theme.tokens(name)["error"]
        assert red in d.message.styleSheet().upper()
    d.deleteLater()


def test_the_saved_theme_is_read_at_start(qapp, private_settings):
    from PySide6.QtCore import QSettings
    from annotshot import theme
    from annotshot.app import make_app
    QSettings(private_settings, QSettings.IniFormat).setValue(
        theme.SETTING, "retro")
    make_app()
    assert theme.current() == "retro"
    assert qapp.font().family() == "VT323"


def test_the_recent_pane_follows_the_theme(window, qapp):
    from annotshot import theme
    window.set_theme("dark")
    assert theme.tokens("dark")["time-ink"] in \
        window.recent.empty.styleSheet().upper()


# -- 4. the manual ----------------------------------------------------------------
def test_the_manual_has_a_themes_paragraph():
    text = (ROOT / "docs" / "USER-MANUAL.md").read_text(encoding="utf-8")
    settings = text[text.index("## Settings"):]
    settings = settings[:settings.index("\n## ", 5)]
    assert "Themes" in settings
    for word in ("Light", "Dark", "Retro", "VT323", "Open Font License"):
        assert word in settings, word
