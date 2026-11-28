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
    assert window.sel_heading.text() == "This callout"
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
    # Enter editor before changing its restored dock state. The test screen
    # is 800 px wide, so hide Recent to leave these points a 420 px canvas.
    view, doc = at_100(window, picture(640, 360, "#FFFFFF"))
    window.recent.hide()
    window.layout().setGeometry(window.rect())
    window.pages.layout().setGeometry(window.pages.rect())
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


def test_about_shows_when_this_build_was_made(window, monkeypatch):
    """Two builds of one version number are told apart by the build line:
    the newest file of the package from source, the program file when
    packaged; with unreadable dates the line is left out, never guessed."""
    import os
    import re
    import sys
    import time
    from pathlib import Path
    from annotshot import help as about
    from PySide6.QtWidgets import QLabel
    newest = max(f.stat().st_mtime
                 for f in Path(about.__file__).resolve().parent.glob("*.py"))
    stamp = about.build_stamp()
    assert stamp == time.strftime("%a %d %b %Y, %H:%M", time.localtime(newest))
    assert re.fullmatch(r"\w{3} \d{2} \w{3} \d{4}, \d{2}:\d{2}", stamp)
    line = about.about_widget().findChild(QLabel, "aboutBuild")
    assert line is not None and line.text() == f"Build: {stamp}"
    # packaged: the program file's own date
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", about.__file__)
    assert about.build_stamp() == time.strftime(
        "%a %d %b %Y, %H:%M", time.localtime(os.stat(about.__file__).st_mtime))
    # the opposite case: dates that cannot be read
    monkeypatch.setattr(sys, "executable", str(Path(about.__file__).parent / "no-such-file"))
    assert about.build_stamp() == ""
    assert about.about_widget().findChild(QLabel, "aboutBuild") is None


def test_about_says_what_who_where_and_the_licence(window):
    from annotshot import __version__
    from annotshot.help import (ABOUT_LINE, PROJECT_URL, PUBLISHER,
                                about_widget)
    from PySide6.QtWidgets import QLabel, QPushButton
    w = about_widget()
    texts = labels_of(w)
    assert f"Annotshot {__version__}" in texts and __version__ == "0.4.4"
    assert ABOUT_LINE in texts and PUBLISHER == "Bill Moldestad"
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
    assert menu.actions()[-3] is window.a_about
    assert menu.actions()[-1] is window.a_quit
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
    from annotshot.help import _cell, shortcuts_markdown
    from annotshot.keywords import key_words
    k = key_words(QKeySequence("Ctrl+K"))
    md = shortcuts_markdown(window.shortcut_rows())
    assert f"| {_cell(k)} | Copy image |" in md      # the user's key now
    assert k in yours and "Copy image" in yours
    assert "Callout" in yours and "no key" in yours    # a tool without one
    assert "Capture from anywhere" in yours
    # a second F1 shows the same window with the keys as they are now
    window.set_shortcut("copy", QKeySequence("Ctrl+J"))
    window.show_help()
    assert window._help_window is h
    j = key_words(QKeySequence("Ctrl+J"))
    assert j in h.browser.toPlainText()


def test_help_is_in_the_menu_and_its_buttons_open_the_pages(window, no_show):
    from annotshot.help import ISSUES_URL, MANUAL_URL
    view, doc = at_100(window)
    menu = view.context_menu_at(view.mapFromScene(QPointF(600, 340)))
    assert [a.text() for a in menu.actions() if not a.isSeparator()][-4:] == [
        "Help", "Send feedback…", "About Annotshot…", "Quit Annotshot"]
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
    yml = (root / ".github" / "workflows" / "build-windows.yml").read_text(
        encoding="utf-8")
    assert "docs/USER-MANUAL.md" in yml
    release = (root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "docs/USER-MANUAL.md" in release
    ps1 = (root / "packaging" / "build-win.ps1").read_text(encoding="utf-8")
    assert "USER-MANUAL.md" in ps1


# -- 7. the permission message names the way back ------------------------------
def test_the_permission_message_names_the_way_back(window, monkeypatch):
    from pathlib import Path
    from PySide6.QtWidgets import QMessageBox
    from annotshot import mainwindow
    way_back = ("If Annotshot is already switched on there and macOS still "
                "refuses: remove it with −, add "
                "it again with + from Applications, and switch it on.")
    assert mainwindow.PERMISSION_WAY_BACK == way_back
    assert mainwindow.PERMISSION_TEXT.endswith(way_back)
    assert "Screen & System Audio Recording" in mainwindow.PERMISSION_TEXT
    seen, opened = [], []
    class RecordingBox(QMessageBox):
        def exec(self):
            seen.append((self.text(), [b.text() for b in self.buttons()]))
            return 0
    monkeypatch.setattr(mainwindow, "QMessageBox", RecordingBox)
    monkeypatch.setattr(mainwindow.macos, "open_privacy_settings",
                        lambda: opened.append(1))
    window._permission_message()
    text, buttons = seen[0]
    assert text == mainwindow.PERMISSION_TEXT
    assert sorted(buttons) == ["Not now", "Open System Settings", "Restart Annotshot"]
    manual = (Path(__file__).resolve().parent.parent / "docs" /
              "USER-MANUAL.md").read_text(encoding="utf-8")
    updating = manual[manual.index("### Updating to a new version"):
                      manual.index("## Capture options")]
    mac = [l for l in updating.splitlines() if l.startswith("- **macOS:**")][0]
    assert "After an update of the unsigned app, capture may need permission again." in mac
    assert "If Annotshot is already enabled in the screen recording list, remove it, add it again from **Applications**, and switch it on." in mac
    install = manual[manual.index("### macOS"):
                     manual.index("### Linux")]
    assert "If Annotshot is already on the list and capture is still blocked, remove it from the list, add **Annotshot** again from **Applications**, and switch it on." in install


# -- s50: independent local privacy reader ---------------------------------------
def click_browser_link(browser, href, qapp):
    """Click an anchor in the laid-out document, rather than emitting a signal."""
    from PySide6.QtGui import QTextCursor
    block = browser.document().begin()
    while block.isValid():
        fragment = block.begin()
        while not fragment.atEnd():
            part = fragment.fragment()
            if part.charFormat().anchorHref() == href:
                cursor = QTextCursor(browser.document())
                cursor.setPosition(part.position() + 1)
                browser.setTextCursor(cursor)
                browser.ensureCursorVisible()
                qapp.processEvents()
                point = browser.cursorRect(cursor).center()
                assert browser.anchorAt(point) == href
                QTest.mouseClick(browser.viewport(), Qt.LeftButton, pos=point)
                return
            fragment += 1
        block = block.next()
    pytest.fail(f"No anchor {href}")


def test_privacy_manual_routes_buttons_and_independent_reading(window, monkeypatch, qapp):
    from annotshot import help
    opened = []
    monkeypatch.setattr(help, "open_url", lambda url: opened.append(url) or True)
    window.show()
    window.a_help.trigger()
    h = window._help_window
    qapp.processEvents()
    assert h.browser.verticalScrollBar().value() == 0
    click_browser_link(h.browser, help.PRIVACY_URL, qapp)
    p = window._privacy_window
    qapp.processEvents()
    saved = h.browser.verticalScrollBar().value()
    assert saved > 0 and not opened
    assert p is not h and p.windowTitle() == "How it stays private"
    p.browser.verticalScrollBar().setValue(130)
    pos = p.browser.verticalScrollBar().value()
    window.show_privacy()
    window.show_help()
    assert p.browser.verticalScrollBar().value() == pos
    assert h.browser.verticalScrollBar().value() == saved
    h.github.click()
    p.github.click()
    h.report.click()
    assert opened == [help.MANUAL_URL, help.PRIVACY_URL, help.ISSUES_URL]
    p.close()
    qapp.processEvents()
    assert window._privacy_window is None and window._help_window is h
    assert h.browser.hasFocus()
    assert h.browser.verticalScrollBar().value() == saved
    window.show_privacy()
    replacement = window._privacy_window
    assert replacement is not p
    h.close()
    assert window._help_window is None and window._privacy_window is replacement
    replacement.close()


def test_help_links_exact_policy_route_fragment_and_near_match(qapp, tmp_path, monkeypatch):
    from annotshot import help
    hrefs = [help.PRIVACY_URL, help.PRIVACY_URL + "?near=1",
             "https://example.test/manual", "#privacy"]
    manual = "# Manual\n\n## Privacy\n\n" + "\n\n".join(
        f"[Link {i}]({href})" for i, href in enumerate(hrefs))
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/USER-MANUAL.md").write_text(manual)
    monkeypatch.setattr(help, "_root", lambda: tmp_path)
    opened, internal = [], []
    monkeypatch.setattr(help, "open_url", lambda url: opened.append(url) or True)
    h = help.HelpWindow([])
    h.privacyRequested.connect(lambda: internal.append(True))
    h.show()
    qapp.processEvents()
    for href in hrefs:
        click_browser_link(h.browser, href, qapp)
    assert internal == [True]
    assert opened == hrefs[1:3]
    h.close()


@pytest.mark.parametrize("damage", ["missing", "empty", "unreadable", "utf8"])
@pytest.mark.parametrize("frozen", [False, True])
def test_privacy_missing_page_local_recovery_and_retry(qapp, tmp_path, monkeypatch, damage, frozen):
    import sys
    from pathlib import Path
    from annotshot import help
    from annotshot.__main__ import PRIVACY, app_root
    root = app_root()
    policy = (root / PRIVACY).read_text()
    (tmp_path / "docs").mkdir()
    target = tmp_path / PRIVACY
    if damage == "empty":
        target.write_text(" \n")
    elif damage == "utf8":
        target.write_bytes(b"\xff\xfe")
    elif damage == "unreadable":
        target.mkdir()  # read_text raises OSError even when running as root
    if frozen:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    else:
        monkeypatch.setattr(help, "_root", lambda: tmp_path)
    opened = []
    monkeypatch.setattr(help, "open_url", lambda url: opened.append(url) or False)
    p = help.PrivacyWindow()
    h = help.HelpWindow([])
    assert help.PRIVACY_SUMMARY in p.browser.toPlainText()
    assert help.NO_PRIVACY in p.browser.toPlainText()
    assert p.browser.toPlainText().startswith("How it stays private")
    assert help.PRIVACY_SUMMARY in h.browser.toPlainText()
    assert not opened
    p.show()
    qapp.processEvents()
    p.browser.verticalScrollBar().setValue(15)
    position = p.browser.verticalScrollBar().value()
    text = p.browser.toPlainText()
    p.github.click()
    assert opened == [help.PRIVACY_URL]
    assert p.browser.toPlainText() == text
    assert p.browser.verticalScrollBar().value() == position
    assert "Could not open the privacy page in your browser." in p.failure.text()
    assert help.PRIVACY_URL in p.failure.text()
    assert p.github.isEnabled() and p.close_buttons.isEnabled()
    if target.is_dir():
        target.rmdir()
    target.write_text(policy)
    p.close()
    p = help.PrivacyWindow()
    assert "Where pictures are kept" in p.browser.toPlainText()
    assert help.NO_PRIVACY not in p.browser.toPlainText()
    assert help.NO_MANUAL in h.browser.toPlainText()
    p.close()
    h.close()


@pytest.mark.parametrize("asset", ["docs/privacy/recent-menu-macos.png",
                                   "docs/privacy/capture-settings-windows.png"])
@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_privacy_missing_image_keeps_instructions_and_caption(qapp, tmp_path, monkeypatch, asset, damage):
    import shutil
    from annotshot import help
    from annotshot.__main__ import PRIVACY, app_root
    (tmp_path / "docs/privacy").mkdir(parents=True)
    shutil.copyfile(app_root() / PRIVACY, tmp_path / PRIVACY)
    if damage == "corrupt":
        (tmp_path / asset).write_bytes(b"not a PNG")
    monkeypatch.setattr(help, "_root", lambda: tmp_path)
    monkeypatch.setattr(help, "open_url", lambda _: pytest.fail("unsolicited URL"))
    p = help.PrivacyWindow()
    text = p.browser.toPlainText()
    assert "Show in folder opens the folder containing the capture." in text
    assert "these two checkboxes control the clipboard copy" in text
    assert "Keep the last 12 captures in the Recent pane" in text
    assert help.NO_PRIVACY not in text
    p.close()


def test_privacy_release_gate_requires_each_asset(tmp_path, qapp):
    import shutil
    from annotshot.__main__ import PRIVACY, PRIVACY_IMAGES, _check_privacy, app_root
    root = app_root()
    (tmp_path / "docs/privacy").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="PRIVACY.md is missing"):
        _check_privacy(tmp_path)
    policy = (root / PRIVACY).read_bytes()
    for broken, message in [(b"", "empty"), (b"\xff", "unreadable")]:
        (tmp_path / PRIVACY).write_bytes(broken)
        with pytest.raises(RuntimeError, match=message):
            _check_privacy(tmp_path)
    (tmp_path / PRIVACY).write_bytes(policy)
    # A pre-existing icon is a decoder fixture only; no policy render is made.
    for asset in PRIVACY_IMAGES:
        shutil.copyfile(root / "icon.png", tmp_path / asset)
    assert _check_privacy(tmp_path) == 2
    for asset in PRIVACY_IMAGES:
        saved = (tmp_path / asset).read_bytes()
        (tmp_path / asset).unlink()
        with pytest.raises(RuntimeError, match=asset.as_posix()):
            _check_privacy(tmp_path)
        (tmp_path / asset).write_bytes(b"corrupt")
        with pytest.raises(RuntimeError, match=asset.as_posix()):
            _check_privacy(tmp_path)
        (tmp_path / asset).write_bytes(saved)


def test_privacy_image_fit_uses_local_resources_only(qapp, tmp_path, monkeypatch):
    import shutil
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QTextDocument
    from annotshot import help
    from annotshot.__main__ import app_root
    # Reuse a real repository PNG solely to exercise Qt decoding and sizing.
    (tmp_path / "docs").mkdir()
    shutil.copyfile(app_root() / "icon.png", tmp_path / "docs/local.png")
    (tmp_path / "docs/PRIVACY.md").write_text("# How it stays private\n\n![local](local.png)")
    monkeypatch.setattr(help, "_root", lambda: tmp_path)
    monkeypatch.setattr(help, "open_url", lambda _: pytest.fail("unsolicited URL"))
    p = help.PrivacyWindow()
    p.resize(400, 450)
    p.show()
    qapp.processEvents()
    p._fit_images()
    image = p.browser.document().begin().next().begin().fragment().charFormat().toImageFormat()
    assert 0 < image.width() <= p.browser.viewport().width()
    resource = p.browser.document().resource(QTextDocument.ImageResource, QUrl("local.png"))
    assert resource is not None
    assert p.browser.loadResource(QTextDocument.ImageResource, QUrl("https://example.test/picture.png")) is None
    p.close()


def test_privacy_survives_theme_help_close_and_editor_state(window, white, monkeypatch, qapp):
    from annotshot import help, recent, theme
    monkeypatch.setattr(help, "open_url", lambda _: pytest.fail("URL"))
    at_100(window, white)
    # Preserve an unsaved edit, its selection, the clipboard, settings and Recent.
    item = make_callout(window.doc)
    item.setSelected(True)
    qapp.clipboard().setText("private clipboard sentinel")
    window.settings.setValue("capture/copy", False)
    window.settings.setValue(recent.SETTING, False)
    before = (window.doc, list(window.doc.selected()), window.doc.undo_stack.index(),
              window.doc.undo_stack.isClean(), window.recent_store.files(),
              dict((k, window.settings.value(k)) for k in window.settings.allKeys()))
    window.show()
    window.activateWindow()
    qapp.processEvents()
    QTest.keyClick(window, Qt.Key_F1)
    qapp.processEvents()
    h = window._help_window
    assert h is not None
    window.show_privacy()
    p = window._privacy_window
    qapp.processEvents()
    h.browser.verticalScrollBar().setValue(100)
    p.browser.verticalScrollBar().setValue(100)
    positions = (h.browser.verticalScrollBar().value(), p.browser.verticalScrollBar().value())
    for name in ("Light", "Dark", "Retro"):
        theme.apply(qapp, name)
        qapp.processEvents()
        assert (h.browser.verticalScrollBar().value(), p.browser.verticalScrollBar().value()) == positions
    h.close()
    assert window._privacy_window is p
    window.show_help()
    assert window._help_window is not h and window._privacy_window is p
    after = (window.doc, list(window.doc.selected()), window.doc.undo_stack.index(),
             window.doc.undo_stack.isClean(), window.recent_store.files(),
             dict((k, window.settings.value(k)) for k in window.settings.allKeys()
                  if k != theme.SETTING))
    assert before[:-1] == after[:-1]
    assert {k: v for k, v in before[-1].items() if k != theme.SETTING} == after[-1]
    assert qapp.clipboard().text() == "private clipboard sentinel"
    window._help_window.close()
    p.close()
    window.doc.undo_stack.mark_exported()


def test_privacy_caller_images_decode_and_render(qapp):
    from annotshot import help
    from annotshot.__main__ import PRIVACY_IMAGES, app_root, _check_privacy
    missing = [p.as_posix() for p in PRIVACY_IMAGES if not (app_root() / p).is_file()]
    if missing:
        pytest.skip("WAITS ON PICTURES: " + ", ".join(missing))
    assert _check_privacy(app_root()) == 2
    p = help.PrivacyWindow()
    p.show()
    qapp.processEvents()
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QImage, QTextDocument
    formats = {}
    block = p.browser.document().begin()
    while block.isValid():
        fragment = block.begin()
        while not fragment.atEnd():
            fmt = fragment.fragment().charFormat()
            if fmt.isImageFormat():
                fmt = fmt.toImageFormat()
                formats[fmt.name()] = fmt
            fragment += 1
        block = block.next()
    for asset in PRIVACY_IMAGES:
        fmt = formats["privacy/" + asset.name]
        assert 0 < fmt.width() <= p.browser.viewport().width()
        assert fmt.height() > 0
        url = QUrl.fromLocalFile(str(app_root() / asset))
        resource = p.browser.document().resource(QTextDocument.ImageResource, url)
        assert resource is not None
        assert not QImage(str(app_root() / asset)).isNull()
    p.close()


def test_privacy_real_images_fit_viewport_after_show_and_resize(qapp):
    from annotshot.help import PrivacyWindow
    from annotshot.__main__ import PRIVACY_IMAGES, app_root

    originals = {"privacy/" + asset.name: QImage(str(app_root() / asset))
                 for asset in PRIVACY_IMAGES}
    assert len(originals) == 2
    assert all(not image.isNull() for image in originals.values())
    p = PrivacyWindow()
    try:
        p.resize(760, 900)
        p.show()
        previous = None
        for width in (760, 480):
            p.resize(width, 900)
            for _ in range(5):
                qapp.processEvents()
            document = p.browser.document()
            available = p.browser.viewport().width() - 2 * document.documentMargin()
            formats = {}
            block = document.begin()
            while block.isValid():
                fragment = block.begin()
                while not fragment.atEnd():
                    fmt = fragment.fragment().charFormat()
                    if fmt.isImageFormat():
                        fmt = fmt.toImageFormat()
                        formats[fmt.name()] = fmt
                    fragment += 1
                block = block.next()
            assert formats.keys() == originals.keys()
            for name, image in originals.items():
                fitted = min(available, image.width())
                assert formats[name].width() == pytest.approx(fitted, abs=1)
                assert formats[name].height() == pytest.approx(
                    image.height() * fitted / image.width(), abs=1)
                if previous is not None:
                    assert formats[name].width() < previous[name]
            previous = {name: fmt.width() for name, fmt in formats.items()}
    finally:
        p.close()


def test_privacy_rejected_github_preserves_full_document_and_position(qapp, monkeypatch):
    from annotshot import help
    calls = []
    monkeypatch.setattr(help, "open_url", lambda url: calls.append(url) or False)
    p = help.PrivacyWindow()
    p.resize(500, 300)
    p.show()
    qapp.processEvents()
    p.browser.verticalScrollBar().setValue(100)
    position = p.browser.verticalScrollBar().value()
    assert position > 0
    text = p.browser.toPlainText()
    QTest.mouseClick(p.github, Qt.LeftButton)
    qapp.processEvents()
    assert calls == [help.PRIVACY_URL]
    assert p.browser.toPlainText() == text
    assert p.browser.verticalScrollBar().value() == position
    assert p.failure.isVisible() and help.PRIVACY_URL in p.failure.text()
    p.close()
