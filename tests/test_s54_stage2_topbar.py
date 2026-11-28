"""s54 stage 2: real Qt actions, measured wrapping and live editing (offscreen)."""
import math

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QApplication, QMessageBox, QToolButton

from annotshot import theme
from annotshot.app import make_app
from annotshot.items import CalloutItem, RectItem, TextBoxItem
from annotshot.keywords import key_words
from annotshot.mainwindow import MainWindow
from annotshot.scene import Document
from annotshot.tools import Tool


def settle(w, qapp, width):
    w.resize(width, 720)
    w.layout().activate()
    for _ in range(3):
        qapp.processEvents()


@pytest.fixture
def editor(qapp, white, monkeypatch):
    make_app()
    monkeypatch.setattr(MainWindow, "_screen_area", lambda s: QRect(0, 0, 1920, 1080))
    w = MainWindow()
    w._bind(Document(white))
    w.show()                       # tests/conftest.py owns the offscreen platform
    w.activateWindow()
    settle(w, qapp, 1100)
    yield w
    w._autosave_timer.stop()
    w.doc.undo_stack.mark_exported()
    w.hide()
    w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()


def objects(w):
    return (w.a_dup, w.a_front, w.a_back, w.a_delete)


def box(w, cls=RectItem):
    item = cls()
    item.set_geom((30, 30, 200, 100))
    w.doc.add_items([item])
    return item


def button(w, action):
    bar = w.main_bar if action in w.main_bar.actions() else w.tools_bar
    return bar.widgetForAction(action)


def press(w, action):
    w.view.setFocus()
    QApplication.processEvents()
    QTest.keySequence(w.view, action.shortcut())
    QApplication.processEvents()


def geometry(w):
    return tuple((a.text(), button(w, a).geometry().getRect())
                 for bar in (w.main_bar, w.tools_bar)
                 for a in bar.actions() if a.text())


def switches(w):
    """Label switches and every possible compact contiguous wrap switch."""
    measured = set()
    for bar in (w.main_bar, w.tools_bar):
        measured.update(bar.needs())
        width = bar.width()
        bar.fit(1)
        sizes = [bar.widgetForAction(a).sizeHint().width() for a in bar.actions() if a.text()]
        gap = 4 if bar is w.main_bar else 2
        for start in range(len(sizes)):
            for end in range(start + 1, len(sizes) + 1):
                measured.add(16 + sum(sizes[start:end]) + gap * (end - start - 1))
        bar.fit(width)
    return {n + delta for n in measured for delta in (-1, 0, 1) if n + delta >= 350}


def pixel(image, x, y):
    scale = image.devicePixelRatio()
    return image.pixelColor(int((x + .5) * scale), int((y + .5) * scale))


def visible(w):
    for bar in (w.main_bar, w.tools_bar):
        extension = bar.findChild(QToolButton, "qt_toolbar_ext_button")
        assert extension is None or not extension.isVisibleTo(w)
        last = (-1, -1)
        rects = []
        for a in bar.actions():
            if not a.text():
                continue
            b = bar.widgetForAction(a)
            assert b.isVisibleTo(w), a.text()
            r = QRect(b.mapTo(bar, QPoint()), b.size())
            assert bar.rect().contains(r), (a.text(), r, bar.rect())
            assert w.rect().contains(QRect(b.mapTo(w, QPoint()), b.size()))
            assert (r.center().y(), r.left()) > last
            last = (r.center().y(), r.left())
            assert all(not r.intersects(other) for other in rects)
            rects.append(r)
            assert b.width() >= b.sizeHint().width(), a.text()
        assert bar.sizeHint().width() <= bar.width()
    assert w.tools_bar.y() >= w.main_bar.geometry().bottom()
    assert w.prop_strip.mapTo(w, QPoint()).y() >= w.tools_bar.geometry().bottom()


def wrapped(w, qapp):
    w.setMinimumSize(1, 1)
    settle(w, qapp, 400)
    b = button(w, w.a_copy)
    assert b.toolButtonStyle() == Qt.ToolButtonTextBesideIcon
    assert button(w, w.a_clear).toolButtonStyle() == Qt.ToolButtonTextBesideIcon
    assert len({button(w, a).geometry().center().y() for a in w.main_bar.actions() if a.text()}) > 1
    visible(w)


@pytest.mark.parametrize("name", theme.NAMES)
def test_r33_resting_faces_order_and_selected_mark(editor, qapp, name):
    w = editor
    theme.apply(qapp, name)
    w.tool_actions[Tool.ARROW].trigger()
    settle(w, qapp, 1100)
    assert theme.tokens()["capture-icon"] == theme.tokens()["link"]
    assert [a.text() for a in w.main_bar.actions() if a.text()] == [
        "Capture", "Open…", "Save…", "Copy image", "Close picture", "Undo", "Redo", "Settings…"]
    assert button(w, w.a_copy).objectName() == "outline"
    assert button(w, w.a_clear).objectName() == "closePicture"
    for a in (w.a_capture, w.a_copy):
        assert not a.isCheckable()
    for action, ink, thickness in ((w.a_capture, "link", 2), (w.a_copy, "copy-icon", 2),
                                   (w.a_clear, "icon", 1)):
        b = button(w, action)
        image = b.grab().toImage()
        assert all(pixel(image, x, b.height() // 2) == theme.color(ink) for x in range(thickness))
        face = pixel(image, thickness + 1, b.height() // 2)
        assert face.alpha() == 0 or face == theme.color("bar-main")
    for a in w.tool_actions.values():
        assert a.isChecked() == (a is w.tool_actions[Tool.ARROW])
    # Render the real button, including its icon-only selected underline.
    for width in (1100, 400):
        w.setMinimumSize(1, 1)
        settle(w, qapp, width)
        b = button(w, w.tool_actions[Tool.ARROW])
        img = b.grab().toImage()
        x, y = (b.width() - 12) // 2, b.height() - 5
        assert all(pixel(img, px, py) == theme.color("checked-text")
                   for px in range(x, x + 12) for py in range(y, y + 2))


@pytest.mark.parametrize("name", theme.NAMES)
@pytest.mark.parametrize("ratio", (1.0, 1.5))
def test_r34_measured_switches_wrap_reverse_and_screen_floor(editor, qapp, monkeypatch, name, ratio):
    w = editor
    family, px, small = theme.FONTS[name]
    monkeypatch.setitem(theme.FONTS, name, (family, math.ceil(px * ratio), math.ceil(small * ratio)))
    theme._filled.clear()
    theme.apply(qapp, name)
    w.setMinimumSize(1, 1)
    widths = {400, 640, 819, 900, 1100}
    widths.update(switches(w))
    widths = sorted(n for n in widths if 350 <= n <= 1800)
    seen = {}
    for width in widths + widths[::-1]:
        settle(w, qapp, width)
        assert button(w, w.a_copy).toolButtonStyle() == Qt.ToolButtonTextBesideIcon
        assert button(w, w.a_clear).toolButtonStyle() == Qt.ToolButtonTextBesideIcon
        level = w.main_bar.level()
        for a in (w.a_open, w.a_save):
            assert button(w, a).toolButtonStyle() == (Qt.ToolButtonTextBesideIcon if level == 0 else Qt.ToolButtonIconOnly)
        assert button(w, w.a_capture).toolButtonStyle() == (Qt.ToolButtonIconOnly if level == 2 else Qt.ToolButtonTextBesideIcon)
        visible(w)
        assert geometry(w) == seen.setdefault(width, geometry(w))
    for area in (QRect(0, 0, 500, 400), QRect(0, 0, 800, 800), QRect(0, 0, 1024, 768)):
        w._apply_floor(area)
        assert w.minimumWidth() <= int(area.width() * .8)
        settle(w, qapp, w.minimumWidth())
        visible(w)
    if ratio == 1:
        settle(w, qapp, 1100)
        for bar in (w.main_bar, w.tools_bar):
            assert len({button(w, a).geometry().center().y() for a in bar.actions() if a.text()}) == 1


def contrast(a, b):
    def lum(c):
        rgb = [getattr(QColor(c), k)() / 255 for k in ("red", "green", "blue")]
        return sum(v * weight for v, weight in zip(
            [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb],
            (.2126, .7152, .0722)))
    lo, hi = sorted((lum(a), lum(b)))
    return (hi + .05) / (lo + .05)


@pytest.mark.parametrize("name", theme.NAMES)
def test_r35_focus_inks_names_tips_and_refit(editor, qapp, name):
    w = editor
    theme.apply(qapp, name)
    wrapped(w, qapp)
    w.tool_actions[Tool.ARROW].trigger()
    for a in (w.tool_actions[Tool.ARROW], w.a_copy):
        b = button(w, a)
        assert b.focusPolicy() & Qt.TabFocus
        b.setFocus(Qt.TabFocusReason)
        qapp.processEvents()
        assert b.hasFocus()
        focused = b.grab().toImage()
        b.clearFocus()
        qapp.processEvents()
        assert focused != b.grab().toImage()
        b.setFocus(Qt.TabFocusReason)
        QTest.keyClick(b, Qt.Key_Tab)
        assert not b.hasFocus()
        iface = QAccessible.queryAccessibleInterface(b)
        assert iface.text(QAccessible.Name) == a.text()
        assert key_words(a.shortcut()) in b.toolTip()
        b.clearFocus()
        QTest.mouseMove(b, b.rect().center())
        hover = b.grab().toImage()
        qapp.processEvents()
        assert hover == b.grab().toImage()
        QTest.mousePress(b, Qt.LeftButton)
        assert b.isDown() and b.grab().toImage() != hover
        QTest.mouseRelease(b, Qt.LeftButton, Qt.NoModifier, QPoint(-5, -5))
        assert not b.isDown()
    t = theme.tokens()
    for ink, face, minimum in (("button-text", "bar-main", 4.5), ("tool-text", "bar-tools", 4.5),
                                ("checked-text", "accent-soft", 4.5), ("link", "bar-main", 4.5),
                                ("icon", "bar-main", 3)):
        assert contrast(t[ink], t[face]) >= minimum
    assert "inset" in theme.TEMPLATE  # focus clearance is part of the measured face


def test_r36_wrapped_copy_button_and_key(editor, qapp, monkeypatch):
    w = editor
    wrapped(w, qapp)
    r = box(w)
    monkeypatch.setattr(w, "maybe_discard", lambda: pytest.fail("Copy asked a question"))
    for use_key in (False, True):
        w.doc.set_props([r], {"border_width": 9 if use_key else 7})
        assert w.doc.undo_stack.needs_save()
        expected = w.doc.render_image()
        if use_key:
            press(w, w.a_copy)
        else:
            button(w, w.a_copy).click()
        assert QApplication.clipboard().image() == expected
        assert not w.doc.undo_stack.needs_save()
        assert w.statusBar().currentMessage() == "Copied — paste it anywhere"
        assert not w.a_copy.isChecked()


def test_r37_wrapped_close_guards_and_kept_files(editor, qapp, monkeypatch, tmp_path):
    w = editor
    wrapped(w, qapp)
    kept = tmp_path / "kept.png"
    assert w.doc.base.save(str(kept))
    before = kept.read_bytes()
    r = box(w)
    original = w.doc
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Cancel)
    button(w, w.a_clear).click()
    assert w.doc is original and w.state_name == "editor"
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Save)
    monkeypatch.setattr(w, "save_as", lambda: False)
    press(w, w.a_clear)
    assert w.doc is original and r in w.doc.annotation_items()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Discard)
    press(w, w.a_clear)
    assert w.state_name == "welcome" and not w.main_bar.isVisible()
    assert not w.tools_bar.isVisible() and not w.a_copy.isEnabled()
    assert kept.read_bytes() == before


def test_r58_selection_shared_accessible_state_and_assigned_tips(editor, qapp):
    w = editor
    assert all(not a.isEnabled() for a in objects(w))
    wrapped(w, qapp)
    r = box(w)
    for selected in (True, False, True):
        w.doc.select_only([r] if selected else [])
        assert w.set_shortcut("duplicate", QKeySequence("Ctrl+Alt+D")) is None
        for a in objects(w):
            b = button(w, a)
            assert a.isEnabled() == selected == b.isEnabled()
            iface = QAccessible.queryAccessibleInterface(b)
            assert iface.state().disabled == (not selected)
            assert iface.text(QAccessible.Name) == a.text()
            if selected:
                assert key_words(a.shortcut()) in b.toolTip()
            else:
                assert a.toolTip() == b.toolTip() == "Select an object first"
        assert all(a in w.menu_actions(True) for a in objects(w))
    w._bind(Document(w.doc.base))
    assert all(not a.isEnabled() for a in objects(w))
    for name in theme.NAMES:
        theme.apply(qapp, name)
        settle(w, qapp, 1100)
        for a in objects(w):
            b = button(w, a)
            image = b.grab().toImage()
            colors = {image.pixelColor(x, y).rgb() for x in range(image.width()) for y in range(image.height())}
            assert theme.color("text-disabled").rgb() in colors
            icon = a.icon().pixmap(QSize(20, 20), 1.5, QIcon.Disabled).toImage()
            assert any(icon.pixelColor(x, y) == theme.color("icon-disabled")
                       for x in range(icon.width()) for y in range(icon.height()))


@pytest.mark.parametrize("name", theme.NAMES)
def test_r59_selection_never_changes_fit(editor, qapp, monkeypatch, name):
    w = editor
    assert all(not a.isEnabled() for a in objects(w))
    theme.apply(qapp, name)
    r = box(w)
    w.setMinimumSize(1, 1)
    family, px, small = theme.FONTS[name]
    for ratio in (1, 1.5):
        monkeypatch.setitem(theme.FONTS, name, (family, math.ceil(px * ratio), math.ceil(small * ratio)))
        theme._filled.clear()
        theme.apply(qapp, name)
        widths = {400, 640, 900, 1100}
        widths.update(switches(w))
        for width in sorted(widths):
            settle(w, qapp, width)
            unselected = geometry(w)
            w.doc.select_only([r])
            settle(w, qapp, width)
            assert all(a.isEnabled() for a in objects(w))
            assert geometry(w) == unselected
            w.doc.clearSelection()
            settle(w, qapp, width)
            assert geometry(w) == unselected
            visible(w)


def test_r60_group_commands_one_step_and_crop(editor, qapp):
    w = editor
    assert all(not a.isEnabled() for a in objects(w))
    items = [box(w) for _ in range(5)]
    d, stack = w.doc, w.doc.undo_stack
    picked = [items[1], items[3]]
    for action in objects(w):
        d.select_only(picked)
        index = stack.index()
        action.trigger()
        assert stack.index() == index + 1
        if action is w.a_dup:
            assert len(d.selected()) == 2 and all(i not in items for i in d.selected())
        elif action is w.a_delete:
            assert d.annotation_items() == [items[0], items[2], items[4]]
        elif action is w.a_front:
            assert d.annotation_items()[-2:] == picked
        else:
            assert d.annotation_items()[:2] == picked
        w.undo()
        assert d.annotation_items() == items and stack.index() == index
    d.select_only(picked)
    w.tool_actions[Tool.CROP].trigger()
    assert d.selected() == picked
    vp = w.view.viewport()
    a, b = w.view.mapFromScene(10, 10), w.view.mapFromScene(300, 220)
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, a)
    assert not d.selected() and all(not a.isEnabled() for a in objects(w))
    QTest.mouseMove(vp, b)
    assert all(not a.isEnabled() for a in objects(w))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, b)
    assert all(not a.isEnabled() for a in objects(w))


@pytest.mark.parametrize("cls", (TextBoxItem, CalloutItem))
@pytest.mark.parametrize("selected", (False, True))
@pytest.mark.parametrize("ranged", (False, True))
def test_r61_live_text_keeps_delete_and_duplicate_keys(editor, qapp, cls, selected, ranged):
    w = editor
    assert all(not a.isEnabled() for a in objects(w))
    item = box(w, cls)
    item.apply_props({"text": "abcd"})
    w.doc.select_only([item] if selected else [])
    w.view.setFocus()
    item.start_edit()
    cur = item.editor.textCursor()
    cur.setPosition(1)
    if ranged:
        cur.setPosition(3, QTextCursor.KeepAnchor)
    item.editor.setTextCursor(cur)
    QTest.keyClick(w.view, Qt.Key_Delete)
    assert item.editor.toPlainText() == ("ad" if ranged else "acd")
    assert item.is_editing and item in w.doc.annotation_items()
    assert w.set_shortcut("duplicate", QKeySequence("Ctrl+Alt+D")) is None
    QTest.keySequence(w.view, w.a_dup.shortcut())
    if selected:
        copies = w.doc.selected()
        assert len(copies) == 1 and copies[0] is not item
        assert copies[0].props["text"] == ("ad" if ranged else "acd")
        button(w, w.a_delete).click()
        assert copies[0] not in w.doc.annotation_items()
    else:
        assert w.doc.is_editing() and w.doc.annotation_items() == [item]
        QTest.keyClicks(w.view, "z")
        assert "z" in item.editor.toPlainText()


@pytest.mark.parametrize("selected", (False, True))
@pytest.mark.parametrize("key,seq", (("duplicate", "D"), ("delete", "Backspace"),
                                     ("front", "F")))
def test_r61_plain_object_keys_still_type_in_live_text(editor, qapp, selected, key, seq):
    """The judge's (s55): an object command reassigned to a plain key must
    not swallow that key from a live text edit, selected or caret-only."""
    w = editor
    assert w.set_shortcut(key, QKeySequence(seq)) is None
    item = box(w, TextBoxItem)
    item.apply_props({"text": "abcd"})
    w.doc.select_only([item] if selected else [])
    w.view.setFocus()
    item.start_edit()
    cur = item.editor.textCursor()
    cur.setPosition(4)
    item.editor.setTextCursor(cur)
    if seq == "Backspace":
        QTest.keyClick(w.view, Qt.Key_Backspace)
        assert item.editor.toPlainText() == "abc"
    else:
        QTest.keyClicks(w.view, seq.lower())
        assert item.editor.toPlainText() == "abcd" + seq.lower()
    assert w.doc.is_editing() and w.doc.annotation_items() == [item]


def test_r62_empty_keys_do_not_dispatch_and_assignments_resume(editor, qapp):
    w = editor
    assert all(not a.isEnabled() for a in objects(w))
    counts = [0, 0, 0, 0]
    for i, a in enumerate(objects(w)):
        a.triggered.connect(lambda checked=False, i=i: counts.__setitem__(i, counts[i] + 1))
    for reassigned in (False, True):
        if reassigned:
            for key, seq in zip(("duplicate", "front", "back", "delete"),
                                ("Ctrl+Alt+D", "Ctrl+Alt+F", "Ctrl+Alt+B", "Ctrl+Alt+X")):
                assert w.set_shortcut(key, QKeySequence(seq)) is None
        before = (w.doc.undo_stack.count(), w.doc.undo_stack.index())
        for a in objects(w):
            press(w, a)
        assert counts == [0, 0, 0, 0] and w.doc.annotation_items() == []
        assert (w.doc.undo_stack.count(), w.doc.undo_stack.index()) == before
    r = box(w)
    for a in objects(w):
        w.doc.select_only([r])
        press(w, a)
    assert counts == [1, 1, 1, 1]
