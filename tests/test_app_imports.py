"""Smoke test: every module imports, MainWindow builds offscreen (never
shown), and the view, the properties bar and the capture overlay wire up."""
import importlib
import sys

import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, QSettings, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

# annotshot.__main__ is left out on purpose: importing it starts the app.
MODULES = ["annotshot", "annotshot.app", "annotshot.items", "annotshot.commands", "annotshot.scene", "annotshot.view",
           "annotshot.tools", "annotshot.capture", "annotshot.mainwindow",
           "annotshot.macos", "annotshot.hotkey",
           "annotshot.settings_dialog", "annotshot.help"]
if sys.platform == "win32":                 # the Win32 helpers: Windows only
    MODULES.append("annotshot.win32")


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(name)


@pytest.fixture
def window(qapp):
    from annotshot.app import make_app
    from annotshot.mainwindow import MainWindow
    make_app()
    w = MainWindow()
    w.view.resize(900, 600)
    yield w
    w.deleteLater()


def test_main_window_builds_without_showing(window):
    assert not window.isVisible()
    texts = [a.text() for a in window.findChildren(type(window.a_copy))]
    for t in ("Capture", "Open…", "Save…", "Copy image", "Clear", "Undo",
              "Redo",
              "Select", "Text", "Callout", "Rect", "Ellipse", "Arrow",
              "Highlight", "Pen", "Crop", "Duplicate", "Front", "Back", "Delete"):
        assert t in texts
    assert window.a_copy.shortcut().toString() == "Ctrl+C"
    assert window.windowTitle() == "Annotshot — Untitled[*]"


def drag_on(widget, a: QPoint, b: QPoint):
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, a)
    QTest.mouseMove(widget, (a + b) / 2)
    QTest.mouseMove(widget, b)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, b)


def drag(view, a: QPoint, b: QPoint):
    drag_on(view.viewport(), a, b)


def test_tool_drag_creates_one_item_then_move_is_one_step(window):
    from annotshot.items import RectItem
    from annotshot.tools import Tool
    view, doc = window.view, window.doc
    window.tool_actions[Tool.RECT].trigger()
    assert view.tool is Tool.RECT
    a, b = QPoint(100, 100), QPoint(260, 200)
    drag(view, a, b)
    (rect,) = doc.annotation_items()
    p0, p1 = view.mapToScene(a), view.mapToScene(b)
    assert isinstance(rect, RectItem)
    assert rect.geom() == (round(p0.x()), round(p0.y()),
                           round(p1.x()) - round(p0.x()), round(p1.y()) - round(p0.y()))
    assert doc.undo_stack.count() == 1 and rect.isSelected()
    assert view.tool is Tool.SELECT and window.tool_actions[Tool.SELECT].isChecked()
    g = rect.geom()
    drag(view, QPoint(180, 150), QPoint(230, 170))         # move it
    assert doc.undo_stack.count() == 2
    assert rect.geom()[:2] == (g[0] + 50, g[1] + 20)
    window.undo()
    assert rect.geom() == g


def test_properties_bar_follows_the_selection(window):
    from annotshot.items import RectItem, TextBoxItem
    doc = window.doc
    t, r = TextBoxItem(), RectItem()
    t.set_geom((10, 10, 200, 50))
    r.set_geom((300, 10, 80, 80))
    doc.add_items([t, r])
    assert window.sel_heading.text() == "Text defaults"
    doc.select_only([r])
    assert window.c_border.isEnabled() and not window.f_font.isEnabled()
    assert not window.c_text.isEnabled()
    assert window.sel_heading.text() == "Rectangle"
    assert window.c_border.text() == "Red"            # swatch + color name
    doc.select_only([t])
    assert window.f_font.isEnabled() and window.c_text.isEnabled()
    assert window.sel_heading.text() == "Text box"
    assert (window.c_text.text(), window.c_fill.text()) == ("Black", "White")
    assert window.s_size.value() == 24
    window.s_size.setValue(40)
    assert t.props["font_px"] == 40
    window.b_nofill.click()
    assert QColor(t.props["fill_color"]).alpha() == 0
    assert window.c_fill.text() == "None"
    window.sl_opacity.setValue(50)
    window.sl_opacity.setValue(40)
    assert t.props["opacity"] == 0.4 and window.opacity_label.text() == "40%"
    count = doc.undo_stack.count()
    window.undo()
    assert t.props["opacity"] == 1.0 and doc.undo_stack.index() == count - 1


def test_the_property_strip_has_two_rows_and_a_hidden_line_row(window):
    """The strip under the tools: row 1 what is selected, Font, Size, Style,
    Align; row 2 Text (its color), Fill + No fill, Border + No border, Width,
    Opacity. Each label names the control beside it."""
    from PySide6.QtWidgets import QLabel, QVBoxLayout
    strip = window.prop_strip
    rows = strip.layout()
    assert isinstance(rows, QVBoxLayout) and rows.count() == 3
    assert window.prop_row3.isHidden()
    labels = {lab.text(): lab.buddy() for lab in strip.findChildren(QLabel)
              if lab.objectName() == "fieldLabel"}
    assert labels == {
        "Font": window.f_font, "Size": window.s_size,
        "Style": window.b_bold.parentWidget(),
        "Align": window.align_buttons["left"].parentWidget(),
        "Text": window.c_text, "Fill": window.c_fill,
        "Border": window.c_border, "Width": window.s_width,
        "Opacity": window.sl_opacity, "Line": window.cb_line,
        "Head": window.cb_head,
        "Head size": window.cb_head_size}
    assert window.b_nofill.toolTip() == "No fill"
    assert window.b_noborder.toolTip() == "No border"
    assert window.b_nofill.text() == "" and not window.b_nofill.icon().isNull()

    def row_of(w):
        while w.parentWidget() is not strip:
            w = w.parentWidget()
        return rows.indexOf(w)
    assert {row_of(w) for w in (window.sel_heading, window.f_font,
                                window.s_size, window.b_bold,
                                window.align_buttons["right"])} == {0}
    assert {row_of(w) for w in (window.c_text, window.c_fill,
                                window.b_nofill, window.c_border,
                                window.b_noborder, window.s_width,
                                window.sl_opacity)} == {1}
    assert 75 <= strip.sizeHint().height() <= 85      # the ~80 px strip
    assert window.f_font.width() == 150 and window.sl_opacity.width() == 112
    assert window.c_text.accessibleName() == "Text color"


@pytest.mark.skipif(sys.platform != "win32",
                    reason="the window pick uses the Win32 window list")
def test_capture_overlay_maps_logical_to_device_pixels(qapp):
    from annotshot.capture import CaptureOverlay, ScreenGrab
    from annotshot.win32 import Window
    from PySide6.QtGui import QGuiApplication
    img = QImage(1920, 1200, QImage.Format_RGB32)
    img.fill(QColor("#336699"))
    grab = ScreenGrab(QGuiApplication.primaryScreen(), img,
                      QRect(0, 0, 1280, 800), 1.5, QRect(0, 0, 1920, 1200))
    win = Window(1, "Notepad", QRect(300, 150, 600, 450))
    ov = CaptureOverlay(grab, [win])
    results = []
    ov.picked.connect(results.append)
    assert ov.to_device(QPointF(100, 100)) == QPoint(150, 150)
    drag_on(ov, QPoint(100, 100), QPoint(300, 200))
    region = results.pop()
    assert region.image.size().toTuple() == (300, 150) and region.title is None
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(400, 300))
    clicked = results.pop()
    assert clicked.title == "Notepad"
    assert clicked.image.size().toTuple() == (600, 450)
    QTest.keyClick(ov, Qt.Key_Escape)
    assert results == [None]
    assert not ov.testAttribute(Qt.WA_QuitOnClose)    # closing it never quits
    ov.deleteLater()


def test_text_tool_click_makes_a_box_and_edits_it(window):
    from annotshot.items import TextBoxItem
    from annotshot.tools import TEXT_CLICK_SIZE, Tool
    view, doc = window.view, window.doc
    window.tool_actions[Tool.TEXT].trigger()
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(120, 90))
    (box,) = doc.annotation_items()
    assert isinstance(box, TextBoxItem) and box.geom()[2] == TEXT_CLICK_SIZE[0]
    assert box.is_editing and doc.is_editing()
    box.editor.textCursor().insertText("Typed")
    window.escape()                                   # Esc ends the edit
    assert not doc.is_editing() and box.props["text"] == "Typed"
    assert [doc.undo_stack.text(i) for i in range(doc.undo_stack.count())] == \
        ["Add Text", "Edit text"]


def test_new_document_replaces_the_old_one(window):
    from annotshot.scene import Document
    old = window.doc
    img = QImage(320, 200, QImage.Format_RGB32)
    img.fill(QColor("#FFFFFF"))
    window._bind(Document(img))
    assert window.doc is not old and window.view.scene() is window.doc
    assert window.size_label.text() == "320 × 200 px"
    assert window.undo_group.activeStack() is window.doc.undo_stack


def test_an_exported_picture_counts_as_saved(window, monkeypatch, tmp_path):
    """After Copy image or Save… as a picture, Ctrl+N / Close do not ask and the
    title has no *; the next edit makes them ask again. The clipboard, the file
    dialog, the settings and the question box are stubbed: nothing real."""
    from PySide6.QtWidgets import QMessageBox
    from annotshot import mainwindow
    from annotshot.items import RectItem
    copied, asked = [], []

    class Clipboard:
        def setImage(self, img):
            copied.append(img)

    class App:
        @staticmethod
        def clipboard():
            return Clipboard()

    class Ask(QMessageBox):
        @staticmethod
        def question(*args, **kwargs):
            asked.append(args)
            return QMessageBox.Cancel

    png = tmp_path / "out.png"
    monkeypatch.setattr(mainwindow, "QApplication", App)
    monkeypatch.setattr(mainwindow, "QMessageBox", Ask)
    monkeypatch.setattr(mainwindow.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(png), "PNG image (*.png)")))
    monkeypatch.setattr(window, "_default_path", lambda *a: str(png))
    monkeypatch.setattr(window, "_remember", lambda *a: None)
    doc, stack = window.doc, window.doc.undo_stack
    r = RectItem()
    r.set_geom((10, 10, 80, 60))
    doc.add_items([r])
    assert stack.needs_save() and window.isWindowModified()

    window.copy_image()
    assert len(copied) == 1 and not copied[0].isNull()
    assert not stack.needs_save() and not window.isWindowModified()
    assert window.maybe_discard() and asked == []     # Ctrl+N / Close: no question

    doc.set_props([r], {"border_width": 9})            # one more edit
    assert stack.needs_save() and window.isWindowModified()
    assert not window.maybe_discard() and len(asked) == 1

    assert window.save_as() and png.stat().st_size > 0
    assert not stack.needs_save() and not window.isWindowModified()
    assert window.maybe_discard() and len(asked) == 1

    window.undo()                                      # back past the export ...
    doc.set_props([r], {"border_width": 4})            # ... and a different edit
    assert stack.index() == 2 and stack.needs_save()   # same index, new state
    assert window.isWindowModified()


def test_typing_keys_go_to_the_text_box_not_the_actions(window):
    """While a text box is edited, Delete / Ctrl+C / Ctrl+Z / Ctrl+Y are the
    text's (ShortcutOverride accepted); Esc and Ctrl+D stay the window's."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication
    from annotshot.items import TextBoxItem
    doc = window.doc
    t = TextBoxItem()
    t.set_geom((10, 10, 200, 50))
    doc.add_items([t])
    QApplication.sendEvent(doc, QEvent(QEvent.WindowActivate))
    t.start_edit()
    assert doc.focusItem() is t.editor

    def claimed(key, mod=Qt.NoModifier):
        ev = QKeyEvent(QEvent.ShortcutOverride, key, mod)
        ev.ignore()
        QApplication.sendEvent(window.view, ev)
        return ev.isAccepted()
    assert claimed(Qt.Key_Delete) and claimed(Qt.Key_C, Qt.ControlModifier)
    assert claimed(Qt.Key_Z, Qt.ControlModifier) and claimed(Qt.Key_Y, Qt.ControlModifier)
    assert not claimed(Qt.Key_Escape) and not claimed(Qt.Key_D, Qt.ControlModifier)


def test_undo_while_typing_drives_the_text_then_the_stack(window):
    """(1a) While a text box is edited, Undo / Redo stay enabled and drive
    the text's own history; the undo stack is untouched. After the edit
    ends they drive the stack again."""
    from annotshot.items import TextBoxItem
    doc, stack = window.doc, window.doc.undo_stack
    t = TextBoxItem()
    t.set_geom((10, 10, 200, 50))
    doc.add_items([t])
    assert window.a_undo.isEnabled()                  # the stack's "Add"
    t.start_edit()
    assert not window.a_undo.isEnabled()              # nothing typed yet
    assert not window.a_redo.isEnabled()
    t.editor.textCursor().insertText("Typed")
    assert window.a_undo.isEnabled() and not window.a_redo.isEnabled()
    count, index = stack.count(), stack.index()
    window.a_undo.trigger()
    assert t.editor.toPlainText() == "" and t.is_editing
    assert (stack.count(), stack.index()) == (count, index)
    assert window.a_redo.isEnabled() and not window.a_undo.isEnabled()
    window.a_redo.trigger()
    assert t.editor.toPlainText() == "Typed"
    assert (stack.count(), stack.index()) == (count, index)
    window.escape()                                   # the edit ends
    assert not doc.is_editing() and t.props["text"] == "Typed"
    assert stack.undoText() == "Edit text" and window.a_undo.isEnabled()
    window.a_undo.trigger()                           # now the stack's undo
    assert t.props["text"] == "" and stack.index() == index


def toolbar_texts(bar):
    """A toolbar's actions in order: "|" a separator, "<>" a stretch."""
    out = []
    for a in bar.actions():
        if a.isSeparator():
            out.append("|")
        elif a.text():
            out.append(a.text())
        elif bar.widgetForAction(a).objectName() == "spacer":
            out.append("<>")
        else:
            out.append(bar.widgetForAction(a).objectName())
    return out


def test_the_toolbars_are_two_rows_then_the_properties(window):
    """(1b) Row 1 Capture, Open, Save, Copy image <> | Undo, Redo; row 2
    tools <> item actions; row 3 the property strip; each row starts after a
    toolbar break (look pass: layout study 2)."""
    from PySide6.QtWidgets import QScrollArea, QToolBar
    bars = {b.objectName(): b for b in window.findChildren(QToolBar)}
    assert set(bars) == {"main", "tools", "properties"}
    assert toolbar_texts(bars["main"]) == [
        "Capture", "Open…", "Save…", "Copy image", "Clear", "<>", "|",
        "Undo", "Redo", "Settings…"]
    assert toolbar_texts(bars["tools"]) == [
        "Select", "Text", "Callout", "Rect", "Ellipse", "Arrow", "Highlight",
        "Pen", "Crop", "<>", "Duplicate", "Front", "Back", "Delete"]
    (strip_action,) = bars["properties"].actions()  # the strip, one widget
    assert isinstance(bars["properties"].widgetForAction(strip_action),
                      QScrollArea)
    assert not window.toolBarBreak(bars["main"])
    assert window.toolBarBreak(bars["tools"])
    assert window.toolBarBreak(bars["properties"])
    assert all(window.toolBarArea(b) == Qt.TopToolBarArea
               for b in bars.values())
    kids = window.children()                          # added in row order
    assert kids.index(bars["main"]) < kids.index(bars["tools"]) <         kids.index(bars["properties"])
    main = bars["main"]
    assert main.widgetForAction(window.a_capture).objectName() == "primary"
    assert main.widgetForAction(window.a_copy).objectName() == "outline"
    # The buttons show the whole label, "…" included, beside the icon;
    # Undo, Redo and the item actions show only the icon, named by the
    # tooltip, and keep their shortcuts.
    assert main.toolButtonStyle() == Qt.ToolButtonTextBesideIcon
    assert window.a_open.iconText() == "Open…"
    icon_only = {"Undo", "Redo", "Settings…", "Duplicate", "Front", "Back",
                 "Delete"}
    for name in ("main", "tools"):
        bar = bars[name]
        for a in bar.actions():
            if a.isSeparator() or not a.text():
                continue
            style = bar.widgetForAction(a).toolButtonStyle()
            if a.text() in icon_only:
                assert style == Qt.ToolButtonIconOnly, a.text()
                assert a.toolTip().startswith(
                    {"Front": "Bring to front", "Back": "Send to back"}.get(
                        a.text(), a.text())), a.toolTip()
                assert "(Ctrl+" in a.toolTip() or a.text() == "Delete"
            else:
                assert style == Qt.ToolButtonTextBesideIcon, a.text()
    assert window.a_dup.shortcut().toString() == "Ctrl+D"
    assert window.a_delete.shortcut().toString() == "Del"
    assert window.a_undo.shortcut().toString() == "Ctrl+Z"


def laid_out(window, width, height):
    """Lay the hidden window out at width x height (it is never shown):
    the main window's layout, then each toolbar's own layout, which places
    or hides the toolbar's overflow (») button."""
    from PySide6.QtWidgets import QToolBar
    window.setMinimumSize(1, 1)
    window.resize(width, height)
    QApplication.processEvents()
    window.layout().setGeometry(window.rect())
    for bar in window.findChildren(QToolBar):
        bar.layout().activate()
    QApplication.processEvents()


def assert_rows_fit(window, width=900):
    """Rows 1 and 2 show every button at `width` logical px: no » button,
    every action's widget visible, each row's size hint within the row."""
    from PySide6.QtWidgets import QToolBar, QToolButton
    laid_out(window, width, 600)
    for name in ("main", "tools"):
        bar = window.findChild(QToolBar, name)
        assert bar.width() == width
        ext = bar.findChild(QToolButton, "qt_toolbar_ext_button")
        assert ext is not None and not ext.isVisibleTo(window), name
        for a in bar.actions():
            w = bar.widgetForAction(a)
            if w is not None and not a.isSeparator():
                assert w.isVisibleTo(window), (name, a.text())
        assert bar.sizeHint().width() <= width, (name, bar.sizeHint())


# The CI's widest font is Linux's DejaVu Sans. Measured on the Mac (DejaVu
# loaded from a file, 12 px): the tool labels draw 1.014 x the Mac face's
# width and the tools row grew 888 -> 907 px. A machine without DejaVu
# stands in for it with the app's own face 1.18 x bigger (12 -> 14 px,
# 13 -> 15 px), about three times DejaVu's extra width: a 1.014 scale
# rounds back to the same whole pixel size and would test nothing.
WIDE_FONT_RATIO = 1.18


def test_nothing_hides_behind_the_overflow_at_900_px(window):
    """At 900 x 600 logical, rows 1 and 2 show every button: no » button,
    and the buttons' widths add up to less than the row. The strip's rows
    fit too, so it needs no sideways scroll bar. On the Mac the tools row
    leaves 60 px spare, so a Mac-green run means a Linux-green run."""
    from PySide6.QtWidgets import QToolBar
    assert_rows_fit(window, 900)
    if sys.platform == "darwin":
        tools = window.findChild(QToolBar, "tools")
        assert tools.sizeHint().width() <= 900 - 60, tools.sizeHint()
    strip = window.prop_strip
    assert strip.sizeHint().width() <= 900


def test_nothing_hides_behind_the_overflow_on_a_wide_font(qapp, monkeypatch):
    """The opposite case: the rows are sized for the widest CI font. With
    DejaVu Sans (Linux's face) when the machine has it, else the app's face
    scaled by WIDE_FONT_RATIO, rows 1 and 2 still fit 900 px."""
    from PySide6.QtGui import QFontDatabase
    from annotshot import theme
    from annotshot.app import make_app
    from annotshot.mainwindow import MainWindow
    app = make_app()
    family, ui_px, small_px = theme.FONTS[theme.DEFAULT]
    if "DejaVu Sans" in QFontDatabase.families():
        wide = ("DejaVu Sans", ui_px, small_px)
    else:
        wide = (family, round(ui_px * WIDE_FONT_RATIO),
                round(small_px * WIDE_FONT_RATIO))
    monkeypatch.setitem(theme.FONTS, theme.DEFAULT, wide)
    theme._filled.clear()
    theme.apply(app, theme.DEFAULT)
    w = None
    try:
        w = MainWindow()
        w.view.resize(900, 600)
        assert_rows_fit(w, 900)
    finally:
        if w is not None:
            w.deleteLater()
        monkeypatch.undo()
        theme._filled.clear()
        theme.apply(app, theme.DEFAULT)


def test_the_window_is_moderate_not_maximized(window):
    """It opens centered at a moderate size, never maximized; after a
    capture it fits the picture at 100 % plus the chrome, capped at 80 % of
    the screen's free area, and stays centered."""
    from PySide6.QtGui import QGuiApplication
    from annotshot.mainwindow import SCREEN_SHARE
    from annotshot.scene import Document
    assert not window.isMaximized() and not window.isFullScreen()
    area = QGuiApplication.primaryScreen().availableGeometry()
    assert window.width() <= area.width() * SCREEN_SHARE
    assert window.height() <= area.height() * SCREEN_SHARE
    assert window.minimumWidth() <= 900 and window.minimumHeight() <= 600
    big = QImage(1920, 1200, QImage.Format_RGB32)
    big.fill(QColor("#FFFFFF"))
    window._bind(Document(big))
    window.fit_to_picture()                       # the offscreen screen
    assert not window.isMaximized()
    assert window.width() <= area.width() * SCREEN_SHARE
    assert window.height() <= area.height() * SCREEN_SHARE
    # On a 1920 x 1200 screen: capped at 80 %, centered.
    screen = QRect(0, 0, 1920, 1200)
    window.fit_to_picture(screen)
    assert (window.width(), window.height()) == (1536, 960)
    assert window.frameGeometry().center() == screen.center()
    # A small picture: the window shows it at 100 % plus the chrome.
    small = QImage(1000, 500, QImage.Format_RGB32)
    small.fill(QColor("#FFFFFF"))
    window._bind(Document(small))
    window.fit_to_picture(screen)
    window.layout().setGeometry(window.rect())
    view = window.view.geometry()
    assert view.width() >= 1000 and view.height() >= 500
    assert window.width() < 1536 and window.height() < 960
    assert window.frameGeometry().center() == screen.center()


def test_the_window_size_is_remembered(window, private_settings):
    from PySide6.QtCore import QSize
    from annotshot.mainwindow import MainWindow
    window.resize(640, 620)
    window.close()                                # nothing to save: accepted
    window.settings.sync()
    assert QSettings(private_settings, QSettings.IniFormat).value(
        "window/size", type=QSize) == QSize(640, 620)
    again = MainWindow()                          # the same private file
    assert again.size() == QSize(640, 620)
    again.deleteLater()


def test_toolbar_actions_have_icons_and_labels(window):
    """Every toolbar button has a label (shown, or the tooltip of an
    icon-only button) and an icon drawn from an SVG file
    that exists in annotshot/icons (and draws something)."""
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QToolBar
    from annotshot.mainwindow import ALIGN_ICONS, ICON_DIR, TOOLBAR_ICONS
    seen = []
    for name in ("main", "tools"):
        bar = window.findChild(QToolBar, name)
        for a in bar.actions():
            if a.isSeparator() or not a.text():
                continue
            seen.append(a.text())
            assert a.text() in TOOLBAR_ICONS, a.text()
            assert (ICON_DIR / f"{TOOLBAR_ICONS[a.text()]}.svg").is_file()
            assert not a.icon().isNull(), a.text()
            img = a.icon().pixmap(QSize(20, 20), 1.5).toImage()
            assert img.width() == 30                  # sharp at 150 %
            assert any(img.pixelColor(x, y).alpha() > 0
                       for x in range(img.width())
                       for y in range(img.height())), a.text()
    assert len(seen) == 21 and set(seen) == set(TOOLBAR_ICONS)
    for key, b in window.align_buttons.items():
        assert (ICON_DIR / f"{ALIGN_ICONS[key]}.svg").is_file()
        assert not b.icon().isNull()


def test_save_follows_the_chosen_file_type(window, monkeypatch, tmp_path):
    """(2) One Save…: the chosen type decides the format: JPEG is opaque with
    white where the picture was transparent, PNG keeps alpha; a missing
    extension is added; the type wins a typed extension; the last type is
    remembered and preselected next time, and the default name follows it."""
    from annotshot import mainwindow
    img = QImage(40, 20, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    for x in range(20):                               # left half: opaque red
        for y in range(20):
            img.setPixelColor(x, y, QColor("#FF0000"))
    monkeypatch.setattr(window.doc, "render_image", lambda: QImage(img))
    monkeypatch.setattr(mainwindow, "DEFAULT_DIR", tmp_path)
    calls, answers = [], []

    def dialog(parent, caption, folder, filters, selected):
        calls.append((caption, folder, filters, selected))
        return answers.pop(0)
    monkeypatch.setattr(mainwindow.QFileDialog, "getSaveFileName",
                        staticmethod(dialog))
    jpeg_filter = "JPEG image (*.jpg *.jpeg)"
    answers.append((str(tmp_path / "shot"), jpeg_filter))
    window.a_save.trigger()                           # the button: the dialog
    caption, folder, filters, selected = calls[0]
    assert caption == "Save" and selected == "PNG image (*.png)"
    assert folder.endswith(".png")
    assert filters == ("PNG image (*.png);;JPEG image (*.jpg *.jpeg);;"
                       "BMP image (*.bmp);;WebP image (*.webp);;"
                       "Word document (*.docx);;PowerPoint slide (*.pptx);;"
                       "Annotshot editable (*.annotshot)")
    jpg = QImage(str(tmp_path / "shot.jpg"))
    assert not jpg.isNull() and not jpg.hasAlphaChannel()
    right, left = jpg.pixelColor(30, 10), jpg.pixelColor(5, 10)
    assert min(right.red(), right.green(), right.blue()) > 245   # white
    assert left.red() > 200 and left.green() < 60                # red
    assert window.statusBar().currentMessage() == "Saved shot.jpg"
    assert window.doc.path is None                    # a picture is no project

    answers.append((str(tmp_path / "keep.png"), "PNG image (*.png)"))
    assert window.save_as()
    assert calls[1][3] == jpeg_filter and calls[1][1].endswith(".jpg")
    png = QImage(str(tmp_path / "keep.png"))
    assert png.hasAlphaChannel() and png.pixelColor(30, 10).alpha() == 0
    assert png.pixelColor(5, 10).alpha() == 255

    answers.append((str(tmp_path / "pic.png"), "BMP image (*.bmp)"))
    assert window.save_as()                           # the type wins the name
    assert calls[2][3] == "PNG image (*.png)"
    assert QImage(str(tmp_path / "pic.bmp")).pixelColor(30, 10) == \
        QColor("#FFFFFF")
    assert not (tmp_path / "pic.png").exists()


def test_save_as_editable_then_ctrl_s_saves_again(window, monkeypatch,
                                                  tmp_path):
    """(2) The .annotshot type saves the editable file (the type wins a typed
    .png); the document then has its path, a plain Ctrl+S saves to it with
    no dialog, and the next dialog preselects the editable type."""
    from PySide6.QtGui import QKeySequence, QShortcutEvent
    from annotshot import mainwindow
    from annotshot.items import RectItem
    from annotshot.scene import Document
    monkeypatch.setattr(mainwindow, "DEFAULT_DIR", tmp_path)
    calls, answers = [], []

    def dialog(parent, caption, folder, filters, selected):
        calls.append((caption, folder, filters, selected))
        return answers.pop(0)
    monkeypatch.setattr(mainwindow.QFileDialog, "getSaveFileName",
                        staticmethod(dialog))
    doc = window.doc
    r = RectItem()
    r.set_geom((10, 10, 80, 60))
    doc.add_items([r])
    answers.append((str(tmp_path / "proj.png"), mainwindow.PROJECT_FILTER))
    assert window.save_as()
    path = tmp_path / "proj.annotshot"
    assert path.is_file() and not (tmp_path / "proj.png").exists()
    assert doc.path == str(path) and doc.undo_stack.isClean()
    assert window.windowTitle() == "Annotshot — proj.annotshot[*]"
    assert len(Document.load(path).annotation_items()) == 1

    doc.set_props([r], {"border_width": 9})
    assert doc.undo_stack.needs_save()

    def press(keys):
        """What a shortcut press does: the shortcut event, then the trigger."""
        QApplication.sendEvent(window.a_save,
                               QShortcutEvent(QKeySequence(keys), 0))
    press("Ctrl+S")                                   # a plain Ctrl+S
    assert len(calls) == 1                            # no dialog
    assert doc.undo_stack.isClean()
    (saved,) = Document.load(path).annotation_items()
    assert saved.props["stroke_width"] == 9

    answers.append(("", ""))                          # cancelled
    press("Ctrl+Shift+S")                             # Ctrl+Shift+S: the dialog
    assert len(calls) == 2
    assert calls[1][3] == mainwindow.PROJECT_FILTER   # the last type chosen
    assert calls[1][1] == str(path)                   # its name, its type


def test_the_save_actions_say_what_they_keep(window):
    """(3) One Save… (Ctrl+S, Ctrl+Shift+S) saves the picture or the editable
    file; Open… opens an Annotshot editable file."""
    assert window.a_save.text() == "Save…"
    assert [k.toString() for k in window.a_save.shortcuts()] == \
        ["Ctrl+S", "Ctrl+Shift+S"]
    assert window.a_save.toolTip().startswith(
        "Save a copy of this capture as a picture or an editable file")
    assert not hasattr(window, "a_png")
    assert not hasattr(window, "save_screenshot")
    assert not hasattr(window, "save_project")
    assert window.a_open.toolTip().startswith("Open an Annotshot editable file")
    from annotshot import mainwindow
    assert mainwindow.OPEN_FILTER == "Annotshot editable (*.annotshot *.snagup)"


def test_pen_tool_drag_draws_one_stroke_then_select(window):
    """A drag with the Pen tool makes ONE pen stroke through the drag's
    points; the tool returns to Select; a drag under 4 px makes nothing."""
    from annotshot.items import PenItem
    from annotshot.tools import Tool
    view, doc = window.view, window.doc
    window.tool_actions[Tool.PEN].trigger()
    assert view.tool is Tool.PEN
    vp = view.viewport()
    pts = [QPoint(100, 100), QPoint(140, 130), QPoint(180, 110),
           QPoint(220, 160)]
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, pts[0])
    for p in pts[1:]:
        QTest.mouseMove(vp, p)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, pts[-1])
    (pen,) = doc.annotation_items()
    assert isinstance(pen, PenItem) and len(pen.points) >= 3
    first, last = pen.scene_points()[0], pen.scene_points()[-1]
    s0, s1 = view.mapToScene(pts[0]), view.mapToScene(pts[-1])
    assert (round(first.x()), round(first.y())) == (round(s0.x()), round(s0.y()))
    assert (round(last.x()), round(last.y())) == (round(s1.x()), round(s1.y()))
    assert doc.undo_stack.count() == 1 and pen.isSelected()
    assert doc.undo_stack.undoText() == "Add Pen stroke"
    assert view.tool is Tool.SELECT and window.tool_actions[Tool.SELECT].isChecked()
    assert window.sel_heading.text() == "Pen stroke"
    assert window.c_border.isEnabled() and window.s_width.isEnabled()
    assert window.sl_opacity.isEnabled()
    assert not window.c_fill.isEnabled() and not window.c_text.isEnabled()
    assert not window.f_font.isEnabled() and not window.b_nofill.isEnabled()
    assert window.c_border.text() == "Red" and window.s_width.value() == 4
    window.s_width.setValue(9)
    assert pen.props["stroke_width"] == 9

    window.tool_actions[Tool.PEN].trigger()           # a 3 px nudge
    drag(view, QPoint(400, 300), QPoint(402, 301))
    assert doc.annotation_items() == [pen]
    assert view.tool is Tool.SELECT


def test_the_fill_picker_starts_opaque_after_no_fill(window, monkeypatch):
    """After "No fill" (alpha 0) the color dialog must start opaque, else
    every hue picked comes back transparent and the fill never shows."""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QColorDialog
    from annotshot.items import TextBoxItem
    doc = window.doc
    t = TextBoxItem()
    t.set_geom((10, 10, 200, 50))
    doc.add_items([t])
    doc.select_only([t])
    window.b_nofill.click()
    assert QColor(t.props["fill_color"]).alpha() == 0
    seen = []

    def fake(initial, *a, **k):
        seen.append(QColor(initial))
        return QColor(0, 128, 255)
    monkeypatch.setattr(QColorDialog, "getColor", fake)
    window.c_fill.click()
    assert seen and seen[0].alpha() == 255
    assert QColor(t.props["fill_color"]).alpha() == 255
    assert QColor(t.props["fill_color"]).name() == "#0080ff"
    assert window.c_fill.text() != "None"


def _default_family_shown(window):
    """The name the Font box gives the default family: Qt's resolution of
    it on this machine when that family is in the list, else its own name."""
    from PySide6.QtGui import QFont, QFontInfo
    from annotshot.items import TextBoxItem
    family = TextBoxItem.DEFAULTS["font_family"]
    resolved = QFontInfo(QFont(family)).family()
    box = window.f_font
    if box.findText(family, Qt.MatchFixedString) >= 0:
        return family
    if box.findText(resolved, Qt.MatchFixedString) >= 0:
        return resolved
    return family


def test_the_font_box_shows_the_selection_or_the_default(window):
    """Nothing selected: the box names the family the next text box gets,
    never VT323 unless picked. A selection: its own family. Size, bold and
    italic follow the same rule."""
    from annotshot.items import TextBoxItem
    doc = window.doc
    default = _default_family_shown(window)
    window.refresh_props()
    assert window.f_font.currentText() == default != "VT323"
    assert window.f_font.isEnabled() and window.s_size.isEnabled()
    assert window.s_size.value() == TextBoxItem.DEFAULTS["font_px"]
    assert not window.b_bold.isChecked() and not window.b_italic.isChecked()
    pixel, plain = TextBoxItem(), TextBoxItem()
    pixel.set_geom((10, 10, 200, 50))
    plain.set_geom((10, 100, 200, 50))
    pixel.apply_props({"font_family": "VT323", "font_px": 40, "bold": True})
    doc.add_items([pixel, plain])
    doc.select_only([pixel])
    assert window.f_font.currentText() == "VT323"
    assert window.s_size.value() == 40 and window.b_bold.isChecked()
    doc.select_only([plain])
    assert window.f_font.currentText() == default
    assert window.s_size.value() == 24 and not window.b_bold.isChecked()
    doc.select_only([])
    assert window.f_font.currentText() == default


def test_a_font_picked_with_nothing_selected_is_the_next_text_boxs(window):
    """Picking VT323 (and a size, bold) with nothing selected changes no item
    and no undo step; the next text box starts in them, across launches."""
    from annotshot.items import TextBoxItem
    from annotshot.tools import Tool
    doc = window.doc
    doc.select_only([])
    window.f_font.setCurrentIndex(0)                # VT323, nothing selected
    window.s_size.setValue(36)
    window.b_bold.setChecked(True)
    assert doc.undo_stack.count() == 0
    assert window.f_font.currentText() == "VT323"
    view = window.view
    window.tool_actions[Tool.TEXT].trigger()
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier,
                     QPoint(100, 100))
    new = doc.annotation_items()
    assert len(new) == 1 and isinstance(new[0], TextBoxItem)
    assert new[0].props["font_family"] == "VT323"
    assert new[0].props["font_px"] == 36 and new[0].props["bold"] is True
    assert window.f_font.currentText() == "VT323"   # it is selected now
