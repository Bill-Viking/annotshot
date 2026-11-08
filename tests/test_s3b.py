"""0.3.0 round 2: the Callout tool, the crop fade, About and Help, and the
permission message that names the way back. (The arrow heads and the line
style are proved in test_items.py.) Everything runs offscreen; no real
dialog or menu is ever shown."""
import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest


@pytest.fixture
def window(qapp):
    from annotshot.app import make_app
    from annotshot.mainwindow import MainWindow
    make_app()
    w = MainWindow()
    w.view.resize(900, 600)
    yield w
    w.deleteLater()


def picture(w=640, h=360, color="#FFFFFF"):
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(color))
    return img


def px(img, x, y) -> tuple:
    c = img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue())


def drag(view, a: QPoint, b: QPoint):
    vp = view.viewport()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, a)
    QTest.mouseMove(vp, (a + b) / 2)
    QTest.mouseMove(vp, b)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, b)


def at_100(window, img=None):
    from annotshot.scene import Document
    window._bind(Document(img or picture()))
    window.view.set_zoom(1.0)
    window.view.centerOn(320, 180)
    return window.view, window.doc


# -- 3. the Callout tool ------------------------------------------------------
def make_callout(doc, geom=(200, 60, 200, 60), **props):
    from annotshot.items import CalloutItem
    c = CalloutItem()
    c.apply_props(props)
    c.set_geom(geom)
    doc.add_items([c])
    return c


def test_a_callout_is_drawn_by_drag_and_starts_typing(window):
    from annotshot.items import CalloutItem
    from annotshot.tools import Tool
    view, doc = at_100(window)
    window.tool_actions[Tool.CALLOUT].trigger()
    assert view.tool is Tool.CALLOUT
    a = view.mapFromScene(QPointF(200, 60))
    b = view.mapFromScene(QPointF(420, 130))
    drag(view, a, b)
    (c,) = doc.annotation_items()
    assert isinstance(c, CalloutItem) and c.is_editing and c.isSelected()
    assert c.geom()[:4] == (200, 60, 220, 70)
    assert window.sel_heading.text() == "Callout"
    assert window.f_font.isEnabled() and window.c_fill.isEnabled()
    c.editor.textCursor().insertText("Look here")
    window.escape()
    assert c.props["text"] == "Look here" and not c.is_editing
    assert view.tool is Tool.SELECT


def test_a_plain_click_places_a_ready_sized_callout(window):
    from annotshot.tools import CALLOUT_CLICK_SIZE, Tool
    view, doc = at_100(window)
    window.tool_actions[Tool.CALLOUT].trigger()
    p = view.mapFromScene(QPointF(100, 50))
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, p)
    (c,) = doc.annotation_items()
    assert c.geom()[2:4] == CALLOUT_CLICK_SIZE


def test_the_callout_is_one_filled_outline_with_its_pointer(window):
    view, doc = at_100(window)
    c = make_callout(doc, fill_color="#0000FF", border_color="#FF0000",
                     border_width=2)
    tip = c.tip_local()
    assert tip.y() > c.rect.height() and tip.x() < c.rect.width() / 2
    path = c.bubble_path()
    assert len(path.toSubpathPolygons()) == 1          # no seam
    img = doc.render_image()
    tx, ty = c.geom()[4:]
    # the pointer, filled: four fifths of the way from the box's middle to
    # the tip, below the box
    mx, my = 300 + 0.8 * (tx - 300), 90 + 0.8 * (ty - 90)
    assert my > 120 and px(img, round(mx), round(my)) == (0, 0, 255)
    assert px(img, 300, 90) == (0, 0, 255)             # the box's inside
    assert px(img, 399, 140) == (255, 255, 255)        # outside, right
    assert c.body_shape().contains(c.mapFromScene(QPointF(mx, my)))


def test_the_tip_is_a_handle_and_its_drag_is_one_undo_step(window):
    view, doc = at_100(window)
    c = make_callout(doc)
    doc.select_only([c])
    assert len(c.handle_points()) == 9
    tx, ty = c.geom()[4:]
    a = view.mapFromScene(QPointF(tx, ty))
    b = view.mapFromScene(QPointF(500, 300))
    before = doc.undo_stack.count()
    drag(view, a, b)
    assert c.geom()[4:] == (500, 300) and c.geom()[:4] == (200, 60, 200, 60)
    assert doc.undo_stack.count() == before + 1
    assert doc.undo_stack.undoText() == "Resize"
    doc.undo_stack.undo()
    assert c.geom()[4:] == (tx, ty)
    doc.undo_stack.redo()
    assert c.geom()[4:] == (500, 300)


def test_moving_a_callout_moves_its_tip_and_resizing_keeps_it(window):
    view, doc = at_100(window)
    c = make_callout(doc)
    c.set_geom((*c.geom()[:4], 120, 300))
    doc.select_only([c])
    drag(view, view.mapFromScene(QPointF(300, 90)),
         view.mapFromScene(QPointF(340, 110)))
    assert c.geom() == (240, 80, 200, 60, 160, 320)
    assert doc.undo_stack.undoText() == "Move"
    c.drag_handle(4, QPointF(500, 200))                # bottom-right corner
    assert c.geom()[:4] == (240, 80, 260, 120)
    assert c.geom()[4:] == (160, 320)                  # the tip stays put


def test_a_callout_saves_reopens_and_duplicates(window, tmp_path):
    from annotshot.items import CalloutItem, item_from_dict
    from annotshot.scene import Document
    view, doc = at_100(window)
    c = make_callout(doc, text="Hi", fill_color="#FFFF00", font_px=30)
    c.set_geom((*c.geom()[:4], 50, 330))
    d = c.to_dict()
    assert d["type"] == "callout" and d["tip"] == [50, 330]
    assert d["rect"] == [200, 60, 200, 60]
    path = tmp_path / "c.annotshot"
    doc.save(path)
    loaded = Document.load(path)
    (back,) = loaded.annotation_items()
    assert isinstance(back, CalloutItem) and back.geom() == c.geom()
    assert (back.props["text"], back.props["fill_color"],
            back.props["font_px"]) == ("Hi", "#FFFF00", 30)
    (dup,) = doc.duplicate([c])
    assert dup.geom() == tuple(v + 12 for v in (200, 60)) + (200, 60) + \
        (62, 342)
    old = {"type": "callout", "rect": [0, 0, 100, 40], "text": "x"}
    legacy = item_from_dict(old)              # no tip yet: the default spot
    assert legacy.tip_local() == QPointF(15 - 16, legacy.rect.height() + 40)


def test_a_callouts_menu_has_the_item_actions(window):
    view, doc = at_100(window)
    make_callout(doc)
    menu = view.context_menu_at(view.mapFromScene(QPointF(300, 90)))
    texts = [a.text() for a in menu.actions()]
    assert "Duplicate" in texts and "Delete" in texts
    menu.deleteLater()


def test_the_callout_tool_has_its_icon_and_a_shortcut_row(window):
    from annotshot.mainwindow import ICON_DIR, SHORTCUT_ROWS
    from annotshot.tools import Tool
    assert (ICON_DIR / "callout.svg").is_file()
    assert ("callout", "Callout") in SHORTCUT_ROWS
    assert window.shortcut_actions["callout"] is window.tool_actions[Tool.CALLOUT]
    from PySide6.QtGui import QKeySequence
    assert window.set_shortcut("callout", QKeySequence("Ctrl+Shift+L")) is None
    assert window.tool_actions[Tool.CALLOUT].shortcut() == \
        QKeySequence("Ctrl+Shift+L")


# -- 4. the crop fade ---------------------------------------------------------
def crop_with_an_arrow_half_out(window):
    from annotshot.items import ArrowItem
    # The test screen is 800 px wide, so the window is 640: the Recent pane
    # is put away to leave the canvas the 420 px these points need.
    window.recent.hide()
    view, doc = at_100(window, picture(640, 360, "#FFFFFF"))
    a = ArrowItem()
    a.apply_props({"stroke_color": "#E53935", "stroke_width": 6})
    a.set_geom((100, 200, 400, 200))
    doc.add_items([a])
    assert doc.crop(QRect(250, 100, 300, 200))
    view.set_zoom(1.0)
    view.centerOn(150, 100)
    return view, doc, a


def test_a_crop_keeps_shapes_beyond_the_picture(window):
    view, doc, a = crop_with_an_arrow_half_out(window)
    assert doc.base.size().toTuple() == (300, 200)
    assert a.scene() is doc and a.geom() == (-150, 100, 150, 100)
    outside = QPointF(-60, 100)                     # left of the picture
    assert a in doc.items(outside)                  # still hit-tests
    vp = view.mapFromScene(outside)
    assert view.item_at(vp) is a
    doc.select_only([a])
    drag(view, vp, vp + QPoint(0, 30))             # still draggable
    assert a.geom() == (-150, 130, 150, 130)
    doc.undo_stack.undo()
    assert a.geom() == (-150, 100, 150, 100)


def test_the_saved_picture_is_the_picture_rect_only(window):
    view, doc, a = crop_with_an_arrow_half_out(window)
    img = doc.render_image()
    assert img.size().toTuple() == (300, 200)
    assert px(img, 0, 100)[1] < 120                 # the arrow, full strength
    assert px(img, 60, 100)[1] < 120
    assert px(img, 200, 100) == (255, 255, 255)     # past its end: picture


def test_beyond_the_picture_the_editor_draws_it_faded(window):
    view, doc, a = crop_with_an_arrow_half_out(window)
    shot = view.viewport().grab().toImage()
    inside = view.mapFromScene(QPointF(60, 100))
    out = view.mapFromScene(QPointF(-60, 100))
    canvas = view.mapFromScene(QPointF(-60, 160))
    red, faded, grey = (px(shot, p.x(), p.y()) for p in (inside, out, canvas))
    assert red[1] < 120                             # full strength inside
    assert grey == (233, 237, 242)                  # the canvas
    assert 140 < faded[1] < 215 and faded != grey   # faded, still there
    doc.select_only([a])
    shot = view.viewport().grab().toImage()
    p1 = view.mapFromScene(QPointF(-150, 100))      # the tail's handle
    assert px(shot, p1.x(), p1.y()) == (255, 255, 255)   # not faded


# -- 5. About Annotshot… ------------------------------------------------------
def labels_of(widget):
    from PySide6.QtWidgets import QLabel
    return [lab.text() for lab in widget.findChildren(QLabel) if lab.text()]


def test_about_says_what_who_where_and_the_licence(window):
    from annotshot import __version__
    from annotshot.help import (ABOUT_LINE, PROJECT_URL, PUBLISHER,
                                about_widget)
    from PySide6.QtWidgets import QLabel, QPushButton
    w = about_widget()
    texts = labels_of(w)
    assert f"Annotshot {__version__}" in texts and __version__ == "0.3.0"
    assert ABOUT_LINE in texts and PUBLISHER == "Viking Software"
    assert PUBLISHER in texts and "MIT licence" in texts
    assert PROJECT_URL == "https://github.com/Bill-Viking/annotshot"
    link = w.findChild(QLabel, "aboutLink")
    assert PROJECT_URL in link.text() and link.openExternalLinks()
    icon = w.findChild(QLabel, "aboutIcon")
    assert not icon.pixmap().isNull() and icon.width() == 64
    assert w.findChild(QPushButton, "noticesButton").text() == \
        "Third-party notices"
    w.deleteLater()


def test_about_is_last_in_the_menu_and_a_settings_tab(window, monkeypatch):
    from annotshot.help import AboutDialog
    from annotshot.settings_dialog import SettingsDialog
    view, doc = at_100(window)
    menu = view.context_menu_at(view.mapFromScene(QPointF(600, 340)))
    assert menu.actions()[-1] is window.a_about
    assert window.a_about.text() == "About Annotshot…"
    menu.deleteLater()
    shown = []
    monkeypatch.setattr(AboutDialog, "exec",
                        lambda self: shown.append(labels_of(self)) or 0)
    window.a_about.trigger()
    d = SettingsDialog(window)
    tab = d.tabs.widget(d.tabs.count() - 1)
    assert d.tabs.tabText(d.tabs.count() - 1) == "About"
    assert shown and labels_of(tab) == shown[0]       # the same content
    d.deleteLater()


def test_the_notices_window_shows_the_texts_the_app_carries(qapp, tmp_path,
                                                          monkeypatch):
    from annotshot import help
    lic = tmp_path / "licenses"
    lic.mkdir()
    (lic / "LGPL-3.0.txt").write_text("GNU LESSER GENERAL PUBLIC LICENSE")
    (tmp_path / "THIRD-PARTY-NOTICES.md").write_text("# Notices\nQt for Python")
    names = [p.name for p in help.notice_files(tmp_path)]
    assert names == ["THIRD-PARTY-NOTICES.md", "LGPL-3.0.txt"]
    text = help.notices_text(tmp_path)
    assert "Qt for Python" in text and "LESSER" in text
    # the source tree: the GNU texts under packaging/licenses
    names = [p.name for p in help.notice_files()]
    assert "LGPL-3.0.txt" in names and "GPL-3.0.txt" in names
    # ASSUMES the app carries notices; where it carries none, one line says so
    assert help.notices_text(tmp_path / "nothing") == help.NO_NOTICES
    shown = []
    monkeypatch.setattr(help.TextWindow, "show",
                        lambda self: shown.append(self.text.toPlainText()))
    win = help.show_notices()
    assert win.text.isReadOnly() and "GPL-3.0.txt" in shown[0]
    win.deleteLater()


# -- 6. Help --------------------------------------------------------------------
@pytest.fixture
def no_show(monkeypatch):
    """Help windows are built but never put on a screen."""
    from annotshot import help
    monkeypatch.setattr(help.HelpWindow, "show", lambda self: None)
    opened = []
    monkeypatch.setattr(help, "open_url", lambda url: opened.append(url))
    return opened


def test_help_shows_the_manual_with_the_live_keys_at_the_top(window, no_show):
    from PySide6.QtGui import QKeySequence
    from annotshot.help import HelpWindow
    assert window.a_help.shortcut() == QKeySequence("F1")
    assert window.set_shortcut("copy", QKeySequence("Ctrl+K")) is None
    window.a_help.trigger()
    h = window._help_window
    assert isinstance(h, HelpWindow) and not h.isModal()
    text = h.browser.toPlainText()
    keys = text.index("Keyboard shortcuts")
    assert keys < text.index("What Annotshot is")      # at the top
    assert text.index("Annotshot user manual") < keys
    yours = text[keys:text.index("What Annotshot is")]
    k = QKeySequence("Ctrl+K").toString(QKeySequence.NativeText)
    from annotshot.help import _cell, shortcuts_markdown
    md = shortcuts_markdown(window.shortcut_rows())
    assert f"| {_cell(k)} | Copy image |" in md      # the user's key now
    assert k in yours and "Copy image" in yours
    assert "Callout" in yours and "no key" in yours    # a tool without one
    assert "Capture from anywhere" in yours
    # a second F1 shows the same window with the keys as they are now
    window.set_shortcut("copy", QKeySequence("Ctrl+J"))
    window.show_help()
    assert window._help_window is h
    j = QKeySequence("Ctrl+J").toString(QKeySequence.NativeText)
    assert j in h.browser.toPlainText()


def test_help_is_in_the_menu_and_its_buttons_open_the_pages(window, no_show):
    from annotshot.help import ISSUES_URL, MANUAL_URL
    view, doc = at_100(window)
    menu = view.context_menu_at(view.mapFromScene(QPointF(600, 340)))
    assert [a.text() for a in menu.actions()][-2:] == ["Help",
                                                        "About Annotshot…"]
    menu.deleteLater()
    window.show_help()
    h = window._help_window
    assert (h.github.text(), h.report.text()) == ("Open on GitHub",
                                                   "Report a problem")
    h.github.click()
    h.report.click()
    assert no_show == [MANUAL_URL, ISSUES_URL]
    assert MANUAL_URL.endswith("/docs/USER-MANUAL.md")
    assert ISSUES_URL == "https://github.com/Bill-Viking/annotshot/issues"


def test_help_from_the_about_tab_closes_settings_first(window, no_show,
                                                       monkeypatch):
    from PySide6.QtWidgets import QPushButton
    from annotshot.settings_dialog import SettingsDialog
    d = SettingsDialog(window)
    about = d.tabs.widget(d.tabs.count() - 1)
    about.findChild(QPushButton, "helpButton").click()
    from PySide6.QtWidgets import QDialog
    assert d.result() == QDialog.Accepted and window._help_window is not None
    d.deleteLater()


def test_help_without_the_manual_or_its_pictures(qapp, tmp_path):
    """ASSUMES the manual rides with the app; where it does not, Help says
    so in one line and still lists the keys. A picture the manual names
    that is not on this computer is simply not drawn."""
    from PySide6.QtGui import QKeySequence
    from annotshot import help
    rows = [("Capture", [QKeySequence("Ctrl+N")])]
    assert help.manual_text(tmp_path) is None
    md = help.help_markdown(rows, None)
    assert help.NO_MANUAL in md and "| Capture |" in md
    md = help.help_markdown(rows, "# T\n\nline\n\n![shot](nowhere.png)\n\n## A\n")
    from PySide6.QtWidgets import QTextBrowser
    b = QTextBrowser()
    b.setMarkdown(md)                                # no error, no picture
    assert "Keyboard shortcuts" in b.toPlainText()
    assert md.index("## Keyboard shortcuts") < md.index("## A")
    assert help._cell("Ctrl+|") == "Ctrl+\\|"


def test_the_check_needs_the_manual(tmp_path):
    """ASSUMES the build lays the manual at docs/USER-MANUAL.md; a build
    without it fails --check."""
    from annotshot.__main__ import MANUAL, _check_manual, app_root
    assert _check_manual(app_root()) > 100
    with pytest.raises(RuntimeError, match="USER-MANUAL.md is missing"):
        _check_manual(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / MANUAL).write_text("")
    with pytest.raises(RuntimeError, match="empty"):
        _check_manual(tmp_path)


def test_both_build_roads_carry_the_manual():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    spec = (root / "packaging" / "annotshot.spec").read_text(encoding="utf-8")
    assert 'at("docs", "USER-MANUAL.md"), "docs"' in spec
    yml = (root / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8")
    assert "docs/USER-MANUAL.md" in yml
    ps1 = (root / "packaging" / "build-win.ps1").read_text(encoding="utf-8")
    assert "USER-MANUAL.md" in ps1


# -- 7. the permission message names the way back ------------------------------
def test_the_permission_message_names_the_way_back(window, monkeypatch):
    from pathlib import Path
    from PySide6.QtWidgets import QMessageBox
    from annotshot import mainwindow
    way_back = ("If Annotshot is already switched on and macOS still "
                "refuses: in that same list remove Annotshot with − and add "
                "it again with + from Applications, switch it on, then quit "
                "and reopen Annotshot.")
    assert mainwindow.PERMISSION_WAY_BACK == way_back
    assert mainwindow.PERMISSION_TEXT.endswith(way_back)
    assert "Screen & System Audio Recording" in mainwindow.PERMISSION_TEXT
    seen, opened = [], []
    monkeypatch.setattr(QMessageBox, "exec",
                        lambda self: seen.append(
                            (self.text(), [b.text() for b in self.buttons()]))
                        or 0)
    monkeypatch.setattr(mainwindow.macos, "open_privacy_settings",
                        lambda: opened.append(1))
    window._permission_message()
    text, buttons = seen[0]
    assert text == mainwindow.PERMISSION_TEXT
    assert sorted(buttons) == ["Not now", "Open System Settings"]
    manual = (Path(__file__).resolve().parent.parent / "docs" /
              "USER-MANUAL.md").read_text(encoding="utf-8")
    updating = manual[manual.index("### Updating to a new version"):
                      manual.index("## The first ten seconds")]
    mac = [l for l in updating.splitlines() if l.startswith("- **macOS:**")][0]
    assert way_back in mac and "every update asks for screen recording" in mac
    install = manual[manual.index("### macOS — four steps"):
                     manual.index("### Linux — three steps")]
    assert way_back in install
