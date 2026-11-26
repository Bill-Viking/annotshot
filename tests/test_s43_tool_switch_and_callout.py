"""s43b: toolbar/canvas transitions, one-placement options and Callout A.

Offscreen only. Run each file in its own bounded process at DPR 1 and 2.
The helpers deliberately do not clear selection or finish typing on a pick.
"""
import json
import zipfile

import pytest
from PySide6.QtCore import QDateTime, QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QKeySequence, QMouseEvent, QPainter, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QColorDialog, QDialog, QLineEdit, QMessageBox,
                               QStyle, QStyleOptionComboBox, QStyleOptionSlider,
                               QStyleOptionSpinBox, QVBoxLayout)

from annotshot.items import (ArrowItem, CalloutItem, RectItem, TextBoxItem,
                            item_from_dict)
from annotshot.mainwindow import MainWindow
from annotshot.scene import Document
from annotshot.tools import ITEM_FOR_TOOL, Tool


def settle():
    for _ in range(8):
        QApplication.processEvents()


@pytest.fixture
def window(qapp, white, monkeypatch):
    from annotshot.app import make_app
    make_app()
    assert qapp.platformName() == 'offscreen'
    monkeypatch.setattr(MainWindow, '_screen_area', lambda self: QRect(0, 0, 1280, 900))
    w = MainWindow()
    w._bind(Document(white))
    w.resize(1100, 720)
    w.show()  # the offscreen platform was asserted above
    settle()
    w.view.set_zoom(w.view.devicePixelRatioF())
    yield w
    w.doc.end_text_edit()
    w.doc.undo_stack.mark_exported()
    w.hide()
    w.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def pick(w, tool):
    button = w.tools_bar.widgetForAction(w.tool_actions[tool])
    assert button.isVisible() and button.isEnabled()
    QTest.mouseClick(button, Qt.LeftButton)
    settle()


def drag(w, start=(40, 40), end=(220, 130), cancel=False):
    v = w.view
    a = v.mapFromScene(QPointF(*start))
    b = a if end is None else v.mapFromScene(QPointF(*end))
    QTest.mousePress(v.viewport(), Qt.LeftButton, pos=a)
    QTest.mouseMove(v.viewport(), (a + b) / 2)
    QTest.mouseMove(v.viewport(), b)
    if cancel:
        QTest.mousePress(v.viewport(), Qt.RightButton, pos=b)
        QTest.mouseRelease(v.viewport(), Qt.RightButton, pos=b)
    QTest.mouseRelease(v.viewport(), Qt.LeftButton, pos=b)
    settle()


def hover(w, point):
    v = w.view
    p = v.mapFromScene(QPointF(*point))
    QApplication.sendEvent(v.viewport(), QMouseEvent(
        QEvent.MouseMove, QPointF(p), v.viewport().mapToGlobal(p),
        Qt.NoButton, Qt.NoButton, Qt.NoModifier))


def prefs(w):
    w.settings.sync()
    return {k: w.settings.value(k) for k in w.settings.allKeys()}


def style_prefs(w):
    return {k: v for k, v in prefs(w).items() if k.startswith('props/') and k != 'props/remember'}


def colour(w, monkeypatch, value):
    monkeypatch.setattr(QColorDialog, 'getColor', lambda *a, **k: QColor(value))
    QTest.mouseClick(w.c_border, Qt.LeftButton)
    settle()


def only_new(w, old):
    return next(i for i in w.doc.annotation_items() if i not in old)


@pytest.mark.parametrize('via', ['toolbar', 'shortcut', 'opacity', 'opacity_drag', 'no_fill'])
def test_switch_rectangle_to_arrow(window, monkeypatch, tmp_path, via):
    w = window
    # Saved Arrow differs from both the rectangle and the later New picks.
    w.settings.setValue('props/arrow/stroke_color', '#008000')
    w.settings.setValue('props/arrow/stroke_width', 6)
    w.view.load_tool_defaults()
    pick(w, Tool.RECT)
    drag(w)
    rect = w.doc.annotation_items()[0]
    if via == 'no_fill':
        w._set({'fill_color': '#E53935'}, 'Fill')
        assert QColor(rect.props['fill_color']).alpha() == 255
        w.view.setFocus()
        settle()
        assert QApplication.focusWidget() is w.view
        QTest.mouseClick(w.b_nofill, Qt.LeftButton)
        settle()
        assert QColor(rect.props['fill_color']).alpha() == 0
    if via == 'opacity_drag':
        w.view.setFocus()
        settle()
        slider = w.sl_opacity
        opt = QStyleOptionSlider()
        slider.initStyleOption(opt)
        a = slider.style().subControlRect(QStyle.CC_Slider, opt,
                                         QStyle.SC_SliderHandle, slider).center()
        b = QPoint(slider.width() // 2, a.y())
        QTest.mousePress(slider, Qt.LeftButton, pos=a)
        QTest.mouseMove(slider, b)
        QTest.mouseRelease(slider, Qt.LeftButton, pos=b)
        settle()
        assert 0 < slider.value() < 100
        assert rect.props['opacity'] == slider.value() / 100
    original, saved_rect = rect.to_dict(), dict(w.view.tool_defaults['rect'])
    assert w.doc.selected() == [rect]
    assert w.view.tool is Tool.SELECT and w.tool_actions[Tool.SELECT].isChecked()
    assert w.sel_heading.text() == 'This rectangle'
    assert w.view.selected_handle_at(QPointF(220, 130))[0] is rect
    assert w.grab().save(str(tmp_path / 'rectangle-selected.png'))
    before = w.doc.undo_stack.count()
    if via == 'toolbar':
        pick(w, Tool.ARROW)
    elif via == 'shortcut':
        w.view.setFocus()
        focused_key(w.view, Qt.Key_A)
        settle()
    elif via in ('opacity_drag', 'no_fill'):
        owner = QApplication.focusWidget()
        assert owner in (w.view, w.sl_opacity, w.b_nofill)
        QTest.keyClick(owner, Qt.Key_A)
        settle()
    else:
        control = {'opacity': w.sl_opacity,
                   'no_fill': w.b_nofill}[via]
        assert control.isVisible() and control.isEnabled()
        control.setFocus(Qt.TabFocusReason)
        settle()
        assert QApplication.focusWidget() is control
        QTest.keyClick(control, Qt.Key_A)
        settle()
    assert [t for t, a in w.tool_actions.items() if a.isChecked()] == [Tool.ARROW]
    assert w.doc.selected() == []
    assert w.view.selected_handle_at(QPointF(220, 130)) is None
    assert w.sel_heading.text() == 'New arrows'
    assert w.cb_head.isEnabled() and w.cb_head_size.isEnabled() and w.ch_both.isEnabled()
    assert w.c_border._color == QColor('#008000') and w.s_width.value() == 6
    assert w.grab().save(str(tmp_path / 'arrow-armed.png'))
    colour(w, monkeypatch, '#0000FF')
    w.s_width.setValue(8)
    colour(w, monkeypatch, '')  # a cancelled second colour picker
    assert w.c_border._color == QColor('#0000FF') and w.s_width.value() == 8
    assert w.doc.undo_stack.count() == before
    assert rect.to_dict() == original and w.view.tool_defaults['rect'] == saved_rect
    hover(w, (220, 130))
    assert w.view.viewport().cursor().shape() == Qt.CrossCursor
    drag(w, (220, 130), (400, 130))
    arrow = only_new(w, [rect])
    assert len(w.doc.annotation_items()) == 2
    assert arrow.geom() == (220, 130, 400, 130)
    assert rect.to_dict() == original
    assert (arrow.props['stroke_color'], arrow.props['stroke_width']) == ('#0000FF', 8)
    assert w.view.tool is Tool.SELECT and w.tool_actions[Tool.SELECT].isChecked()
    assert w.sel_heading.text() == 'This arrow' and w.doc.selected() == [arrow]
    exported = w.doc.render_image()
    expected_red = QColor('#E53935')
    if via == 'opacity_drag':
        alpha = rect.props['opacity']
        expected_red = QColor(*[round(c * alpha + 255 * (1 - alpha))
                               for c in (229, 57, 53)])
        assert all(abs(a - b) <= 1 for a, b in zip(
            exported.pixelColor(130, 40).getRgb(), expected_red.getRgb()))
    else:
        assert exported.pixelColor(130, 40) == expected_red
    assert exported.pixelColor(300, 130) == QColor('#0000FF')
    assert exported.save(str(tmp_path / 'post-switch-export.png'))
    assert w.doc.undo_stack.count() == before + 1
    w.undo()
    assert w.doc.annotation_items() == [rect] and rect.to_dict() == original
    after_undo = w.doc.render_image().pixelColor(130, 40)
    if via == 'opacity_drag':
        assert all(abs(a - b) <= 1 for a, b in zip(after_undo.getRgb(), expected_red.getRgb()))
    else:
        assert after_undo == expected_red
    w.redo()
    assert arrow in w.doc.annotation_items() and arrow.geom() == (220, 130, 400, 130)


@pytest.mark.parametrize('tool', list(ITEM_FOR_TOOL))
@pytest.mark.parametrize('selection', ['same', 'mixed'])
def test_neighbours_explicit_pick_and_completion(window, tool, selection):
    w = window
    old = ITEM_FOR_TOOL[tool]()
    if tool is Tool.PEN:
        old.set_points([(40, 40), (220, 130)])
    else:
        old.set_geom((40, 40, 220, 130))
    items = [old]
    if selection == 'mixed':
        extra = RectItem() if tool is not Tool.RECT else ArrowItem()
        extra.set_geom((300, 200, 100, 80))
        items.append(extra)
    w.doc.add_items(items)
    w.doc.select_only(items)
    saved = [i.to_dict() for i in items]
    count = w.doc.undo_stack.count()
    pick(w, tool)
    assert w.doc.selected() == []
    assert w.sel_heading.text().startswith('New ')
    assert w.view.tool is tool
    target = w.view.defaults_item()
    for control, key in w._controls.items():
        expected = target.key_for(key) is not None and not (
            control is w.b_nofill and tool is Tool.HIGHLIGHT)
        assert control.isEnabled() == expected
    drag(w, (400, 60), (550, 150))
    new = only_new(w, items)
    assert [i.to_dict() for i in items] == saved
    assert w.doc.undo_stack.count() == count + 1
    assert w.view.tool is Tool.SELECT
    assert w.doc.selected() == ([] if tool is Tool.PEN else [new])
    assert w.doc.is_editing() == (tool in (Tool.TEXT, Tool.CALLOUT))
    if tool in (Tool.TEXT, Tool.CALLOUT):
        assert new.editor.hasFocus()


@pytest.mark.parametrize('via', ['toolbar', 'shortcut', 'escape'])
def test_neighbours_select_move_resize_and_escape(window, via):
    w = window
    pick(w, Tool.RECT)
    drag(w)
    rect = w.doc.selected()[0]
    if via == 'toolbar':
        pick(w, Tool.SELECT)
    elif via == 'shortcut':
        w.view.setFocus()
        focused_key(w.view, Qt.Key_V)
    else:
        w.view.setFocus()
        focused_key(w.view, Qt.Key_Escape)
        assert w.doc.selected() == []
    drag(w, (100, 40), None)  # click the selected object's visible border
    assert w.doc.selected() == [rect]
    count = w.doc.undo_stack.count()
    drag(w, (100, 40), (120, 55))
    assert rect.geom() == (60, 55, 180, 90)
    drag(w, (240, 145), (260, 165))
    assert rect.geom() == (60, 55, 200, 110)
    assert w.doc.undo_stack.count() == count + 2


def test_neighbours_crop_and_deliberate_context_target(window):
    w = window
    pick(w, Tool.RECT)
    drag(w)
    rect = w.doc.selected()[0]
    pick(w, Tool.ARROW)
    assert w.doc.selected() == []
    menu = w.view.context_menu_at(w.view.mapFromScene(QPointF(100, 40)))
    assert menu is not None and w.doc.selected() == [rect]
    assert w.a_dup in menu.actions() and w.a_delete in menu.actions()
    w.a_dup.trigger()
    assert len(w.doc.annotation_items()) == 2
    menu.deleteLater()
    pick(w, Tool.CROP)
    drag(w, (10, 10), (600, 320))
    assert (w.doc.base.width(), w.doc.base.height()) == (590, 310)
    assert w.view.tool is Tool.SELECT and w.doc.selected() == []


@pytest.mark.parametrize('tool', [Tool.TEXT, Tool.CALLOUT])
def test_neighbours_typing_letter_and_toolbar_commit_once(window, tool):
    w = window
    pick(w, tool)
    drag(w, (50, 50), None)
    item = w.doc.selected()[0]
    count = w.doc.undo_stack.count()
    assert item.editor.hasFocus()
    focused_text(w, 'a brave callout')
    assert item.editor.toPlainText() == 'a brave callout'
    assert w.doc.is_editing() and w.view.tool is Tool.SELECT
    assert w.doc.selected() == [item]
    assert [t for t, a in w.tool_actions.items() if a.isChecked()] == [Tool.SELECT]
    pick(w, Tool.ARROW)
    assert not w.doc.is_editing() and item.props['text'] == 'a brave callout'
    assert w.doc.undo_stack.count() == count + 1
    assert w.doc.selected() == [] and w.sel_heading.text() == 'New arrows'
    pick(w, Tool.ARROW)
    assert w.doc.undo_stack.count() == count + 1
    drag(w, (500, 250), None)
    assert w.view.tool is Tool.ARROW and len(w.doc.annotation_items()) == 1
    w.undo()
    assert item.props['text'] == ''


@pytest.mark.parametrize('entry', ['idle', 'mouse', 'tab'])
@pytest.mark.parametrize('field', ['font', 'size', 'width'])
def test_tool_shortcut_keeps_properties_text_input(window, field, entry):
    w = window
    item = TextBoxItem()
    w.doc.add_items([item])
    w.doc.select_only([item])
    if entry != 'idle':
        item.start_edit()
        w.view.setFocus()
        focused_text(w, 'red blue')
        cursor = item.editor.textCursor()
        cursor.setPosition(4)
        item.editor.setTextCursor(cursor)
    # A numeric tool key must still type in a numeric editor. Checking only
    # A in a spin box would prove rejection of invalid text, not typing.
    if field != 'font':
        assert w.set_shortcut('arrow', QKeySequence('7')) is None
    control = {'font': w.f_font, 'size': w.s_size, 'width': w.s_width}[field]
    editor = control.lineEdit()
    if entry == 'mouse':
        QTest.mouseClick(editor, Qt.LeftButton, pos=editor.rect().center())
    elif entry == 'tab':
        tab_to(w, control)
    else:
        control.setFocus(Qt.TabFocusReason)
    settle()
    assert QApplication.focusWidget() in (control, editor)
    w.refresh_props()
    settle()
    assert QApplication.focusWidget() in (control, editor)
    if field == 'font' and entry == 'mouse':
        open_font(w)
        family = different_family(w, item)
        click_font(w, family)
        assert QApplication.focusWidget() in (control, editor)
        assert item.props['font_family'] == family
    editor.selectAll()
    typed = 'azqv' if field == 'font' else '17'
    QTest.keyClicks(QApplication.focusWidget(), typed)
    expected = typed if field == 'font' else typed + control.suffix()
    assert editor.text() == expected
    w.refresh_props()
    settle()
    assert QApplication.focusWidget() in (control, editor)
    assert editor.text() == expected
    assert w.view.tool is Tool.SELECT and w.doc.selected() == [item]
    assert [t for t, a in w.tool_actions.items() if a.isChecked()] == [Tool.SELECT]
    if field != 'font':
        assert control.value() == 17
        # Invalid letters retain ordinary spin-box rejection, never a tool
        # switch, including when the default Arrow key is restored.
        assert w.reset_shortcut('arrow') is None
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_A)
        assert editor.text() == expected
        assert w.view.tool is Tool.SELECT and w.doc.selected() == [item]


@pytest.mark.parametrize('remember', [False, True])
@pytest.mark.parametrize('failed', ['miss', 'cancel'])
def test_new_options_survive_failed_drag_and_repick(window, monkeypatch, remember, failed):
    w = window
    w.set_remember_props(remember)
    saved = style_prefs(w)
    pick(w, Tool.ARROW)
    colour(w, monkeypatch, '#0000FF')
    w.s_width.setValue(8)
    assert w.c_border._color == QColor('#0000FF') and w.s_width.value() == 8
    count = w.doc.undo_stack.count()
    drag(w, (40, 40), None if failed == 'miss' else (160, 40), cancel=failed == 'cancel')
    assert w.doc.annotation_items() == [] and w.view.tool is Tool.ARROW
    pick(w, Tool.ARROW)
    assert w.c_border._color == QColor('#0000FF') and w.s_width.value() == 8
    assert w.doc.undo_stack.count() == count
    drag(w, (40, 40), (220, 40))
    first = w.doc.annotation_items()[0]
    assert (first.props['stroke_color'], first.props['stroke_width']) == ('#0000FF', 8)
    pick(w, Tool.ARROW)
    drag(w, (40, 180), (220, 180))
    second = only_new(w, [first])
    expected = ('#0000FF', 8) if remember else ('#E53935', 4)
    assert (second.props['stroke_color'], second.props['stroke_width']) == expected
    if not remember:
        assert style_prefs(w) == saved
    fresh = MainWindow()
    try:
        assert (fresh.view.starting_style('arrow')['stroke_color'],
                fresh.view.starting_style('arrow')['stroke_width']) == expected
        fresh._bind(Document(w.doc.base))
        fresh.resize(1100, 720)
        fresh.show()
        settle()
        fresh.view.set_zoom(fresh.view.devicePixelRatioF())
        pick(fresh, Tool.ARROW)
        drag(fresh, (40, 40), (220, 40))
        reopened_arrow = fresh.doc.annotation_items()[0]
        assert (reopened_arrow.props['stroke_color'], reopened_arrow.props['stroke_width']) == expected
    finally:
        fresh.hide()
        fresh.deleteLater()


@pytest.mark.parametrize('clear', ['different', 'reset', 'remember'])
def test_new_options_clear_and_saved_styles_restore(window, monkeypatch, clear):
    w = window
    w.settings.setValue('props/arrow/stroke_color', '#008000')
    w.settings.setValue('props/arrow/stroke_width', 6)
    w.view.load_tool_defaults()
    w.set_remember_props(False)
    saved = style_prefs(w)
    pick(w, Tool.ARROW)
    colour(w, monkeypatch, '#0000FF')
    w.s_width.setValue(8)
    if clear == 'different':
        pick(w, Tool.RECT)
        pick(w, Tool.ARROW)
    elif clear == 'reset':
        w.reset_tool_defaults()
    else:
        w.set_remember_props(False)
    assert w.c_border._color == QColor('#E53935') and w.s_width.value() == 4
    if clear != 'reset':
        assert style_prefs(w) == saved
    w.set_remember_props(True)
    expected = ('#E53935', 4) if clear == 'reset' else ('#008000', 6)
    assert (w.c_border._color.name().upper(), w.s_width.value()) == expected


@pytest.mark.parametrize('tool', list(ITEM_FOR_TOOL))
def test_new_options_only_new_target(window, tool):
    w = window
    w.set_remember_props(False)
    pick(w, tool)
    # Opacity is available to every drawing tool; selected edits never stage it.
    w.sl_opacity.setValue(63)
    assert w.sl_opacity.value() == 63
    drag(w)
    item = w.doc.annotation_items()[0]
    assert item.props['opacity'] == .63
    w.doc.end_text_edit()
    w.doc.select_only([item])  # Pen deliberately completes with no selection.
    w.sl_opacity.setValue(42)
    assert item.props['opacity'] == .42
    pick(w, tool)
    assert w.sl_opacity.value() == 100
    assert style_prefs(w) == {}


def specimen(item, size, width):
    other = item_from_dict(item.to_dict())
    other.apply_props({'font_px': size, 'border_width': width})
    return other


def isolated_image(base, item):
    doc = Document(base)
    doc.add_items([item_from_dict(item.to_dict())])
    return doc.render_image()


@pytest.mark.parametrize('click', [False, True])
def test_callout_approved_a_caret_geometry_and_export(window, tmp_path, click):
    w = window
    base = QImage(1280, 720, QImage.Format_RGB32)
    base.fill(Qt.white)
    base.setDevicePixelRatio(2)
    w._bind(Document(base))
    w.view.set_zoom(.54)
    pick(w, Tool.CALLOUT)
    saved = style_prefs(w)
    assert w.sel_heading.text() == 'New callouts'
    assert (w.s_size.value(), w.s_width.value(), w.c_border._color.name().upper()) == (32, 4, '#E53935')
    # Change zoom only for precise event coordinates; export remains full resolution.
    w.view.set_zoom(w.view.devicePixelRatioF())
    drag(w, (80, 70), None if click else (360, 170))
    item = w.doc.selected()[0]
    assert item.geom()[:4] == ((80, 70, 220, 60) if click else (80, 70, 280, 100))
    assert w.sel_heading.text() == 'This callout'
    assert w.doc.is_editing() and item.editor.hasFocus()
    focused_text(w, 'callout')
    assert item.editor.toPlainText() == 'callout'
    assert item.editor.font().pixelSize() == 32 and item.props['padding'] == 6
    assert item.props['fill_color'] == '#FFFFFF' and item.props['text_color'] == '#000000'
    pick(w, Tool.TEXT)  # commits once and gives the next text its own factory
    assert item.props['text'] == 'callout'
    assert (w.s_size.value(), w.s_width.value(), w.c_border.text()) == (32, 2, 'None')
    drag(w, (450, 70), None)
    text = only_new(w, [item])
    focused_text(w, 'test')
    assert text.editor.font().pixelSize() == 32
    w.doc.end_text_edit()
    w.doc.clearSelection()
    image = isolated_image(base, item)
    assert image.size() == base.size()
    assert image == isolated_image(base, specimen(item, 32, 4))
    assert image != isolated_image(base, specimen(item, 24, 2))
    assert image != isolated_image(base, specimen(item, 28, 3))
    assert image != isolated_image(base, specimen(item, 32, 2))
    assert image != isolated_image(base, specimen(item, 24, 4))
    # Exact red ink on the box and on both pointer sides, away from handles.
    x, y, width, height, tx, ty = item.geom()
    assert image.pixelColor(round(x + width / 2), round(y)) == QColor('#E53935')
    # Both edges of the default pointer must have red ink. Its two triangle
    # roots are independently derived from the specified box and tip.
    import math
    cx, cy = width / 2, height / 2
    local_tx, local_ty = tx - x, ty - y
    length = math.hypot(local_tx - cx, local_ty - cy)
    ux, uy = (local_tx - cx) / length, (local_ty - cy) / length
    half = max(6, min(18, min(width, height) * .25))
    for sign in (-1, 1):
        root_x, root_y = cx + sign * uy * half, cy - sign * ux * half
        px, py = x + .8 * local_tx + .2 * root_x, y + .8 * local_ty + .2 * root_y
        assert any(image.pixelColor(round(px) + dx, round(py) + dy) == QColor('#E53935')
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1))
    red = [(xx, yy) for yy in range(round(y + height + 4), round(ty - 2))
           for xx in range(round(tx - 35), round(tx + 60))
           if 0 <= xx < image.width() and image.pixelColor(xx, yy) == QColor('#E53935')]
    assert len(red) >= 12
    rows = {}
    for xx, yy in red:
        rows.setdefault(yy, []).append(xx)
    assert any(max(xs) - min(xs) > 8 for xs in rows.values())
    w.view.set_zoom(.54)
    settle()
    # Render the actual view at the requested fit, and retain a useful image.
    fitted = w.view.grab().toImage()
    assert not fitted.isNull() and w.view.zoom == .54
    assert fitted.save(str(tmp_path / 'callout-fit54.png'))
    assert w.doc.render_image().save(str(tmp_path / 'callout-and-text-export.png'))
    assert image.save(str(tmp_path / 'callout-isolated-export.png'))
    assert style_prefs(w) == saved


@pytest.mark.parametrize('end', [(86, 76), (300, 100), (360, 170)])
def test_callout_minimum_and_text_autofit(window, end):
    w = window
    pick(w, Tool.CALLOUT)
    drag(w, (80, 70), end)
    item = w.doc.selected()[0]
    # Drawn widths keep the existing minimum; a short box grows for one
    # line of 32 px text plus its existing 6 px padding.
    assert item.geom()[0:2] == (80, 70)
    assert item.geom()[2] == max(8, end[0] - 80)
    assert item.geom()[3] >= max(8, end[1] - 70)
    assert item.props['padding'] == 6 and item.editor.font().pixelSize() == 32
    before = item.geom()
    focused_text(w, 'callout')
    w.doc.end_text_edit()
    assert item.geom()[0:3] == before[0:3]
    assert item.geom()[3] >= before[3]
    assert item.props['text'] == 'callout'


def test_callout_tip_undo_save_reopen(window, tmp_path):
    w = window
    pick(w, Tool.CALLOUT)
    drag(w, (80, 70), (360, 170))
    item = w.doc.selected()[0]
    focused_text(w, 'callout')
    w.doc.end_text_edit()
    before = item.geom()
    drag(w, before[4:], (400, 250))
    assert item.geom() == (*before[:4], 400, 250)
    w.undo()
    assert item.geom() == before
    w.redo()
    path = tmp_path / 'a.annotshot'
    w.doc.save(path)
    reopened = Document.load(path)
    copy = reopened.annotation_items()[0]
    assert copy.to_dict() == item.to_dict()
    assert reopened.render_image() == w.doc.render_image()
    assert copy.props['padding'] == 6


@pytest.mark.parametrize('seed,expected', [
    ({}, (32, 4, '#E53935')),
    ({'font_px': 48}, (48, 4, '#E53935')),
    ({'border_width': 8}, (32, 8, '#E53935')),
    ({'font_px': 24, 'border_width': 2}, (24, 2, '#E53935')),
    ({'border_color': '#001267A2'}, (32, 4, '#001267A2')),
    ({'font_px': 'bad', 'border_width': 7}, (32, 7, '#E53935')),
    ({'font_px': 40, 'border_width': 'nan'}, (40, 4, '#E53935')),
])
def test_compatibility_saved_keys_independent(window, seed, expected):
    w = window
    for key, value in seed.items():
        w.settings.setValue('props/callout/' + key, value)
    saved = style_prefs(w)
    fresh = MainWindow()
    try:
        style = fresh.view.starting_style('callout')
        assert (style['font_px'], style['border_width'], style['border_color']) == expected
        assert style_prefs(fresh) == saved
    finally:
        fresh.deleteLater()
    w.view.load_tool_defaults()
    pick(w, Tool.CALLOUT)
    drag(w)
    item = w.doc.selected()[0]
    assert (item.props['font_px'], item.props['border_width'], item.props['border_color']) == expected
    assert style_prefs(w) == saved
    w.set_remember_props(False)
    assert (w.view.starting_style('callout')['font_px'], w.view.starting_style('callout')['border_width']) == (32, 4)
    w.set_remember_props(True)
    assert (w.view.starting_style('callout')['font_px'], w.view.starting_style('callout')['border_width']) == expected[:2]
    w.reset_tool_defaults()
    assert (w.view.starting_style('callout')['font_px'], w.view.starting_style('callout')['border_width']) == (32, 4)


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('explicit', [False, True])
def test_compatibility_historical_document_ink(window, tmp_path, legacy, explicit):
    w = window
    # These are historical constructor defaults, not the new factory branch.
    raw = {'type': 'callout', 'rect': [80, 70, 220, 60], 'text': 'old'}
    if explicit:
        raw.update(font_px=24, border_width=2, border_color='#E53935', tip=[120, 190])
    historical = CalloutItem.from_dict(raw)
    assert (historical.props['font_px'], historical.props['border_width']) == (24, 2)
    expected = isolated_image(w.doc.base, historical)
    path = tmp_path / ('old.snagup' if legacy else 'old.annotshot')
    # An editable pre-change specimen with omitted properties really omitted.
    w.doc.save(path)
    with zipfile.ZipFile(path) as z:
        meta, png = json.loads(z.read('project.json')), z.read('base.png')
    meta['items'] = [raw]
    if legacy:
        meta['format'] = 'snagup'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('project.json', json.dumps(meta))
        z.writestr('base.png', png)
    doc = Document.load(path)
    old = doc.annotation_items()[0]
    assert old.to_dict() == historical.to_dict()
    assert doc.render_image() == expected
    w._bind(doc)
    w.view.set_zoom(w.view.devicePixelRatioF())
    pick(w, Tool.CALLOUT)
    drag(w, (360, 200), (600, 290))
    new = only_new(w, [old])
    assert (new.props['font_px'], new.props['border_width']) == (32, 4)
    assert old.to_dict() == historical.to_dict()
    assert isolated_image(doc.base, old) == expected


# s43g: deliver every letter to the settled, asserted focus owner.
def focused_text(w, text):
    settle()
    assert QApplication.focusWidget() is w.view
    assert w.doc.is_editing()
    QTest.keyClicks(QApplication.focusWidget(), text)
    settle()


def focused_key(owner, key, modifiers=Qt.NoModifier):
    settle()
    assert QApplication.focusWidget() is owner
    QTest.keyClick(QApplication.focusWidget(), key, modifiers)
    settle()


def tab_to(w, target):
    # Starting on the picture is deliberate; no direct focus on the target.
    w.view.setFocus()
    settle()
    for _ in range(160):
        if QApplication.focusWidget() is target:
            return
        owner = QApplication.focusWidget()
        assert owner is not None
        QTest.keyClick(owner, Qt.Key_Tab)
        settle()
    pytest.fail(f'Tab never reached {target.accessibleName() or target.objectName()}')


def selected_shape(w, tool):
    pick(w, tool)
    drag(w)
    return w.doc.selected()[0]


def open_choice(w, box, via):
    if via == 'picture_mouse':
        box.setFocusPolicy(Qt.TabFocus)
        w.view.setFocus()
        settle()
        assert QApplication.focusWidget() is w.view
    else:
        tab_to(w, box)
    if via in ('mouse', 'picture_mouse'):
        QTest.mouseClick(box, Qt.LeftButton)
        settle()
    else:
        focused_key(box, Qt.Key_Down, Qt.AltModifier)
    assert box.view().isVisible()
    # Qt briefly ignores the opening mouse release. This is a separate
    # row click, after that native guard, not the release that opened it.
    QTest.qWait(QApplication.doubleClickInterval() + 10)
    assert QApplication.focusWidget() is box.view()


def click_choice(box, data, *, finish=True):
    view = box.view()
    index = box.model().index(box.findData(data), 0)
    view.scrollTo(index)
    settle()
    rect = view.visualRect(index)
    assert rect.isValid() and view.viewport().rect().contains(rect.center())
    # Move first: the actual popup row gesture, including a current-row re-pick.
    QTest.mouseMove(view.viewport(), rect.center() + QPoint(5, 0))
    QTest.mouseMove(view.viewport(), rect.center())
    QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=rect.center())
    assert not view.isVisible()
    if finish:
        finish_choice(box)


def finish_choice(box):
    settle()
    box.window().activateWindow()  # offscreen has no WM to restore activation
    settle()


def test_tab_arrow_head_search_and_undo(window):
    w = window
    arrow = selected_shape(w, Tool.ARROW)
    assert arrow.props['head'] == 'filled'
    before = w.doc.undo_stack.index()
    tab_to(w, w.cb_head)
    focused_key(w.cb_head, Qt.Key_B)
    assert arrow.props['head'] == 'bar'
    assert w.cb_head.currentData() == 'bar'
    assert w.doc.selected() == [arrow] and w.view.tool is Tool.SELECT
    assert [t for t, a in w.tool_actions.items() if a.isChecked()] == [Tool.SELECT]
    assert QApplication.focusWidget() is w.cb_head
    assert w.doc.undo_stack.index() == before + 1
    w.undo()
    assert arrow.props['head'] == 'filled'


def test_tab_line_style_miss_and_programmatic_refresh(window):
    w = window
    rect = selected_shape(w, Tool.RECT)
    tab_to(w, w.cb_line)
    before = rect.to_dict(), w.doc.undo_stack.index()
    focused_key(w.cb_line, Qt.Key_A)
    assert (rect.to_dict(), w.doc.undo_stack.index()) == before
    assert w.doc.selected() == [rect] and w.view.tool is Tool.SELECT
    assert QApplication.focusWidget() is w.cb_line
    w.cb_line.setCurrentIndex(w.cb_line.findData('dotted'))
    w.refresh_props()
    settle()
    assert QApplication.focusWidget() is w.cb_line
    assert rect.props['line_style'] == 'dotted'


@pytest.mark.parametrize('interrupt', ['none', 'width', 'dialog', 'return_field'])
@pytest.mark.parametrize('opening', ['picture_mouse', 'mouse', 'keyboard'])
@pytest.mark.parametrize('repick', [False, True])
@pytest.mark.parametrize('binding', ['R', 'D'])
def test_line_style_mouse_commit_hands_picture_next_tool(window, opening, repick, binding, interrupt):
    w = window
    rect = selected_shape(w, Tool.RECT)
    assert w.set_shortcut('rect', QKeySequence(binding)) is None
    if repick:
        w.cb_line.setCurrentIndex(w.cb_line.findData('dashed'))
    open_choice(w, w.cb_line, opening)
    acquired = []
    dialog = None
    if interrupt in ('dialog', 'return_field'):
        dialog = QDialog(w)
        layout = QVBoxLayout(dialog)
        field = QLineEdit(dialog)
        layout.addWidget(field)
    if interrupt != 'none':
        if interrupt in ('width', 'return_field'):
            assert w.set_shortcut('arrow', QKeySequence('7')) is None
        def destination(row):
            # A direct observer AFTER the product's real Qt activated slot.
            if interrupt == 'width':
                QApplication.setActiveWindow(w)
                w.s_width.setFocus(Qt.MouseFocusReason)
                acquired.append(QApplication.focusWidget() is w.s_width)
            else:
                if interrupt == 'return_field':
                    QApplication.setActiveWindow(w)
                    w.s_width.setFocus(Qt.MouseFocusReason)
                    acquired.append(QApplication.focusWidget() is w.s_width)
                dialog.show()
                QApplication.setActiveWindow(dialog)
                field.setFocus()
                acquired.append(QApplication.focusWidget() is field)
        w.cb_line.activated.connect(destination)
    click_choice(w.cb_line, 'dashed', finish=interrupt == 'none')
    if interrupt != 'none':
        try:
            assert acquired and all(acquired), 'destination did not acquire focus during activation'
            settle()
            if dialog is not None:
                assert QApplication.activeWindow() is dialog
                assert QApplication.focusWidget() is field
                focused_key(field, Qt.Key_A)
                assert field.text() == 'a'
                assert w.view.tool is Tool.SELECT and w.doc.selected() == [rect]
                dialog.hide()
                w.activateWindow()
                settle()
            if interrupt in ('width', 'return_field'):
                assert QApplication.focusWidget() is w.s_width
                w.s_width.lineEdit().selectAll()
                QTest.keyClicks(QApplication.focusWidget(), '17')
                settle()
                assert w.s_width.lineEdit().text() == '17 px'
            else:
                assert QApplication.focusWidget() is w.view
            assert rect.props['line_style'] == 'dashed'
            assert w.doc.selected() == [rect] and w.view.tool is Tool.SELECT
            assert w.tool_actions[Tool.SELECT].isChecked()
            return
        finally:
            if dialog is not None:
                dialog.hide()
                dialog.deleteLater()
    assert rect.props['line_style'] == 'dashed'
    assert w.doc.selected() == [rect]
    focused_key(w.view, Qt.Key_R if binding == 'R' else Qt.Key_D)
    assert w.view.tool is Tool.RECT and w.doc.selected() == []
    assert [t for t, a in w.tool_actions.items() if a.isChecked()] == [Tool.RECT]
    assert rect.props['line_style'] == 'dashed'


@pytest.mark.parametrize('opening', ['closed', 'picture_mouse', 'mouse', 'keyboard'])
def test_line_style_keyboard_search_user_path_keeps_control(window, opening):
    w = window
    rect = selected_shape(w, Tool.RECT)
    assert w.set_shortcut('rect', QKeySequence('D')) is None
    if opening == 'closed':
        tab_to(w, w.cb_line)
    if opening != 'closed':
        open_choice(w, w.cb_line, opening)
    owner = w.cb_line if opening == 'closed' else w.cb_line.view()
    focused_key(owner, Qt.Key_D)
    if opening != 'closed':
        focused_key(owner, Qt.Key_Return)
        w.activateWindow()
        settle()
    assert w.cb_line.currentText() == 'Dashed'
    assert rect.props['line_style'] == w.cb_line.currentData()
    assert w.view.tool is Tool.SELECT and w.doc.selected() == [rect]
    assert QApplication.focusWidget() is w.cb_line
    # A miss still belongs to this closed control.
    focused_key(w.cb_line, Qt.Key_A)
    assert w.view.tool is Tool.SELECT and w.doc.selected() == [rect]


@pytest.mark.parametrize('opening', ['picture_mouse', 'mouse', 'keyboard'])
def test_arrow_popup_search_escape_or_accept(window, opening):
    w = window
    arrow = selected_shape(w, Tool.ARROW)
    before = w.doc.undo_stack.index()
    open_choice(w, w.cb_head, opening)
    focused_key(w.cb_head.view(), Qt.Key_B)
    assert w.cb_head.view().currentIndex().data() == 'Bar'
    focused_key(w.cb_head.view(), Qt.Key_Escape)
    w.activateWindow()
    settle()
    assert arrow.props['head'] == 'filled' and w.cb_head.currentData() == 'filled'
    assert w.doc.undo_stack.index() == before
    if opening == 'picture_mouse':
        focused_key(w.view, Qt.Key_R)
        assert w.view.tool is Tool.RECT
        w.doc.select_only([arrow])
        pick(w, Tool.SELECT)
    else:
        assert QApplication.focusWidget() is w.cb_head
    open_choice(w, w.cb_head, opening)
    focused_key(w.cb_head.view(), Qt.Key_B)
    focused_key(w.cb_head.view(), Qt.Key_Return)
    w.activateWindow()
    settle()
    assert arrow.props['head'] == 'bar'
    assert w.doc.undo_stack.index() == before + 1
    assert w.view.tool is Tool.SELECT and w.doc.selected() == [arrow]
    assert QApplication.focusWidget() is w.cb_head


def recent_rows(w, monkeypatch):
    from annotshot import recent
    monkeypatch.setattr(recent, 'time_label', lambda when, *a:
                        {16: 'Mon capture', 17: 'Tue capture', 19: 'Thu capture'}[when.date().day()])
    for day in (16, 17, 19):
        path = w.recent_store.reserve(QDateTime(2026, 11, day, 10, 0, 0))
        w.recent.file_capture(w.doc.base, wait=True, path=path)
    w.recent.show()
    settle()
    assert [w.recent.list.item(i).text() for i in range(3)] == ['Thu capture', 'Tue capture', 'Mon capture']
    return w.recent.list


def test_recent_typeahead_then_successful_thumbnail_open(window, monkeypatch):
    w = window
    rect = selected_shape(w, Tool.RECT)
    listing = recent_rows(w, monkeypatch)
    listing.setCurrentRow(2)
    tab_to(w, listing)
    requests = []
    w.recent.openRequested.connect(requests.append)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.Discard)
    old = w.doc
    before = old.undo_stack.index(), rect.to_dict()
    focused_key(listing, Qt.Key_T)
    assert listing.currentRow() == 0  # one Qt search: two T rows expose double delivery
    assert requests == []
    assert w.doc is old and w.doc.selected() == [rect] and w.view.tool is Tool.SELECT
    assert (old.undo_stack.index(), rect.to_dict()) == before
    QTest.mouseClick(listing.viewport(), Qt.LeftButton,
                     pos=listing.visualItemRect(listing.item(0)).center())
    settle()
    assert len(requests) == 1 and w.doc is not old
    focused_key(w.view, Qt.Key_T)
    assert w.view.tool is Tool.TEXT


@pytest.mark.parametrize('failure', ['refused', 'unreadable'])
def test_recent_unsuccessful_click_keeps_document_and_list_focus(window, monkeypatch, failure):
    w = window
    rect = selected_shape(w, Tool.RECT)
    listing = recent_rows(w, monkeypatch)
    if failure == 'refused':
        monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.Cancel)
    else:
        monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.Discard)
        from pathlib import Path
        Path(listing.item(0).data(Qt.UserRole)).write_bytes(b'not an image')
    requests = []
    w.recent.openRequested.connect(requests.append)
    old = w.doc
    before = old.undo_stack.index(), rect.to_dict()
    QTest.mouseClick(listing.viewport(), Qt.LeftButton,
                     pos=listing.visualItemRect(listing.item(0)).center())
    settle()
    assert len(requests) == 1 and w.doc is old
    assert w.doc.selected() == [rect] and w.view.tool is Tool.SELECT
    assert (old.undo_stack.index(), rect.to_dict()) == before
    focused_key(listing, Qt.Key_T)
    assert w.doc is old and w.view.tool is Tool.SELECT


def test_both_ends_mouse_and_keyboard_neutral_controls(window):
    w = window
    arrow = selected_shape(w, Tool.ARROW)
    w.view.setFocus()
    QTest.mouseClick(w.ch_both, Qt.LeftButton)
    settle()
    assert arrow.props['both_ends']
    owner = QApplication.focusWidget()
    assert owner in (w.view, w.ch_both)
    focused_key(owner, Qt.Key_R)
    assert w.view.tool is Tool.RECT and arrow.props['both_ends']
    w.doc.select_only([arrow])
    pick(w, Tool.SELECT)
    tab_to(w, w.ch_both)
    focused_key(w.ch_both, Qt.Key_Space)
    assert not arrow.props['both_ends']
    focused_key(w.ch_both, Qt.Key_R)
    assert w.view.tool is Tool.RECT


def test_neutral_keyboard_navigation_and_welcome_guard(window, tmp_path, monkeypatch):
    w = window
    rect = selected_shape(w, Tool.RECT)
    tab_to(w, w.sl_opacity)
    before = w.sl_opacity.value()
    focused_key(w.sl_opacity, Qt.Key_Left)
    assert w.sl_opacity.value() < before
    assert rect.props['opacity'] == w.sl_opacity.value() / 100
    tab_to(w, w.b_nofill)
    focused_key(w.b_nofill, Qt.Key_Space)
    assert QColor(rect.props['fill_color']).alpha() == 0
    focused_key(w.b_nofill, Qt.Key_A)
    assert w.view.tool is Tool.ARROW
    w.show_welcome()
    settle()
    owner = QApplication.focusWidget()
    assert owner is not None and owner is not w.view
    focused_key(owner, Qt.Key_R)
    assert w.state_name == 'welcome'
    assert all(not a.isEnabled() for a in w.tool_actions.values())
    # Existing inline recorder remains the owner of a drawing letter.
    w.welcome.start_recording()
    settle()
    field = w.welcome.recorder
    focused_key(field, Qt.Key_A)
    assert w.state_name == 'welcome'
    assert field.draft.text() == 'A'
    w.welcome.cancel_recording()
    path = tmp_path / 'reopened.annotshot'
    w.doc.save(str(path))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.Discard)
    assert w.open_path(str(path))
    settle()
    assert QApplication.focusWidget() is w.view
    assert all(a.isEnabled() for a in w.tool_actions.values())
    focused_key(w.view, Qt.Key_R)
    assert w.view.tool is Tool.RECT


@pytest.mark.parametrize('box_name, data', [('cb_head', 'bar'), ('cb_head_size', 'large')])
def test_other_properties_mouse_pick_finishes_choice(window, box_name, data):
    w = window
    arrow = selected_shape(w, Tool.ARROW)
    box = getattr(w, box_name)
    open_choice(w, box, 'keyboard')
    click_choice(box, data)
    assert box.currentData() == data
    focused_key(w.view, Qt.Key_R)
    assert w.view.tool is Tool.RECT and w.doc.selected() == []
    assert arrow.props['head' if box_name == 'cb_head' else 'head_size'] == data


def test_stock_head_size_combo_claims_collision(window):
    w = window
    arrow = selected_shape(w, Tool.ARROW)
    assert w.set_shortcut('rect', QKeySequence('L')) is None
    tab_to(w, w.cb_head_size)
    focused_key(w.cb_head_size, Qt.Key_L)
    assert w.cb_head_size.currentData() == 'large'
    assert arrow.props['head_size'] == 'large' and w.doc.selected() == [arrow]
    assert w.view.tool is Tool.SELECT
    assert QApplication.focusWidget() is w.cb_head_size


def test_recent_successful_click_handoff_without_prior_search(window, monkeypatch):
    w = window
    selected_shape(w, Tool.RECT)
    listing = recent_rows(w, monkeypatch)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.Discard)
    requests = []
    w.recent.openRequested.connect(requests.append)
    old = w.doc
    QTest.mouseClick(listing.viewport(), Qt.LeftButton,
                     pos=listing.visualItemRect(listing.item(0)).center())
    settle()
    assert len(requests) == 1 and w.doc is not old
    focused_key(w.view, Qt.Key_T)
    assert w.view.tool is Tool.TEXT


def test_recent_miss_blank_click_and_refresh_keep_list(window, monkeypatch):
    w = window
    rect = selected_shape(w, Tool.RECT)
    listing = recent_rows(w, monkeypatch)
    tab_to(w, listing)
    requests = []
    w.recent.openRequested.connect(requests.append)
    before = w.doc, w.doc.undo_stack.index(), rect.to_dict()
    focused_key(listing, Qt.Key_A)  # no row starts A; still list input
    assert (w.doc, w.doc.undo_stack.index(), rect.to_dict()) == before
    assert w.view.tool is Tool.SELECT and w.doc.selected() == [rect]
    w.recent.refresh()
    settle()
    assert QApplication.focusWidget() is listing
    blank = QPoint(listing.viewport().width() // 2, listing.viewport().height() - 2)
    assert not listing.indexAt(blank).isValid()
    QTest.mouseClick(listing.viewport(), Qt.LeftButton, pos=blank)
    settle()
    assert QApplication.focusWidget() is listing and requests == []
    focused_key(listing, Qt.Key_T)
    assert requests == [] and w.doc is before[0] and w.view.tool is Tool.SELECT


@pytest.mark.parametrize('backwards', [False, True])
def test_closed_choice_tab_can_leave(window, backwards):
    w = window
    selected_shape(w, Tool.ARROW)
    tab_to(w, w.cb_head)
    focused_key(w.cb_head, Qt.Key_Tab, Qt.ShiftModifier if backwards else Qt.NoModifier)
    assert QApplication.focusWidget() is not w.cb_head


def combo_arrow(box):
    opt = QStyleOptionComboBox()
    box.initStyleOption(opt)
    return box.style().subControlRect(QStyle.CC_ComboBox, opt,
                                      QStyle.SC_ComboBoxArrow, box).center()


def open_font(w):
    QTest.mouseClick(w.f_font, Qt.LeftButton, pos=combo_arrow(w.f_font))
    settle()
    assert w.f_font.view().isVisible()
    assert QApplication.focusWidget() is w.f_font.view()
    QTest.qWait(QApplication.doubleClickInterval() + 10)


def different_family(w, item):
    return next(w.f_font.itemText(i) for i in range(w.f_font.count())
                if not w.f_font.is_separator(i)
                and w.f_font.itemText(i) != item.props['font_family'])


def click_font(w, family):
    view = w.f_font.view()
    index = w.f_font.model().index(w.f_font.findText(family), 0)
    view.scrollTo(index)
    settle()
    rect = view.visualRect(index)
    assert rect.isValid() and view.viewport().rect().contains(rect.center())
    QTest.mouseMove(view.viewport(), rect.center() + QPoint(5, 0))
    QTest.mouseMove(view.viewport(), rect.center())
    QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=rect.center())
    assert not view.isVisible()
    finish_choice(w.f_font)


@pytest.mark.parametrize('tool', [Tool.TEXT, Tool.CALLOUT])
@pytest.mark.parametrize('formatting', ['font', 'size'])
@pytest.mark.parametrize('selection', [False, True])
def test_live_caret_mouse_format_resumes_typing(window, tool, formatting, selection):
    w = window
    pick(w, tool)
    drag(w, (50, 50), None)
    item = w.doc.editing_item
    focused_text(w, 'red blue')
    cursor = item.editor.textCursor()
    cursor.setPosition(4)
    if selection:
        cursor.setPosition(8, QTextCursor.KeepAnchor)
    item.editor.setTextCursor(cursor)
    saved = cursor.position(), cursor.anchor()
    original = item.props['font_family' if formatting == 'font' else 'font_px']
    before = w.doc.undo_stack.index()
    if formatting == 'font':
        family = different_family(w, item)
        open_font(w)
        click_font(w, family)
        assert item.props['font_family'] == family
        assert item.editor.font().family() == family
    else:
        opt = QStyleOptionSpinBox()
        w.s_size.initStyleOption(opt)
        up = w.s_size.style().subControlRect(QStyle.CC_SpinBox, opt,
                                            QStyle.SC_SpinBoxUp, w.s_size).center()
        QTest.mouseClick(w.s_size, Qt.LeftButton, pos=up)
        settle()
        assert item.props['font_px'] == original + 1
        assert item.editor.font().pixelSize() == original + 1
    assert w.doc.editing_item is item
    assert QApplication.focusWidget() is w.view
    assert item.editor.hasFocus()
    cursor = item.editor.textCursor()
    assert (cursor.position(), cursor.anchor()) == saved
    assert w.doc.undo_stack.index() == before + 1  # format only
    assert w.doc.undo_stack.command(before).text() == ('Font' if formatting == 'font' else 'Font size')
    focused_text(w, 'a')
    expected = 'red a' if selection else 'red ablue'
    assert item.editor.toPlainText() == expected
    assert w.doc.selected() == [item] and w.view.tool is Tool.SELECT
    assert w.tool_actions[Tool.SELECT].isChecked()
    assert w.doc.undo_stack.index() == before + 1  # pending typing
    chosen = item.props['font_family' if formatting == 'font' else 'font_px']
    pick(w, Tool.ARROW)
    assert not w.doc.is_editing() and item.props['text'] == expected
    assert w.doc.undo_stack.index() == before + 2
    assert w.doc.undo_stack.command(before + 1).text() == 'Edit text'
    pick(w, Tool.ARROW)
    assert w.doc.undo_stack.index() == before + 2
    w.undo()
    assert item.props['text'] == ''
    assert item.props['font_family' if formatting == 'font' else 'font_px'] == chosen
    w.undo()
    assert item.props['font_family' if formatting == 'font' else 'font_px'] == original


@pytest.mark.parametrize('tool', [Tool.TEXT, Tool.CALLOUT])
@pytest.mark.parametrize('ending', ['escape', 'field', 'dialog', 'size_field'])
def test_live_format_cancellation_or_later_destination(window, tool, ending):
    w = window
    pick(w, tool)
    drag(w, (50, 50), None)
    item = w.doc.editing_item
    focused_text(w, 'red blue')
    cursor = item.editor.textCursor()
    cursor.setPosition(4)
    cursor.setPosition(8, QTextCursor.KeepAnchor)
    item.editor.setTextCursor(cursor)
    saved = cursor.position(), cursor.anchor()
    before = w.doc.undo_stack.index()
    family = item.props['font_family']
    dialog = QDialog(w)
    layout = QVBoxLayout(dialog)
    field = QLineEdit(dialog)
    layout.addWidget(field)
    acquired = []
    def destination(*_):
        QApplication.setActiveWindow(w)
        w.s_width.setFocus(Qt.MouseFocusReason)
        acquired.append(QApplication.focusWidget() is w.s_width)
        if ending == 'dialog':
            dialog.show()
            QApplication.setActiveWindow(dialog)
            field.setFocus()
            acquired.append(QApplication.focusWidget() is field)
    try:
        if ending == 'size_field':
            w.s_size.valueChanged.connect(destination)
            opt = QStyleOptionSpinBox()
            w.s_size.initStyleOption(opt)
            up = w.s_size.style().subControlRect(QStyle.CC_SpinBox, opt,
                                                QStyle.SC_SpinBoxUp, w.s_size).center()
            QTest.mouseClick(w.s_size, Qt.LeftButton, pos=up)
        else:
            open_font(w)
            if ending == 'escape':
                focused_key(w.f_font.view(), Qt.Key_Escape)
                w.activateWindow()
                settle()
                assert w.doc.editing_item is item and item.editor.hasFocus()
                assert QApplication.focusWidget() is w.view
                c = item.editor.textCursor()
                assert (c.position(), c.anchor()) == saved
                assert item.props['font_family'] == family
                assert w.doc.undo_stack.index() == before
                focused_text(w, 'a')
                assert item.editor.toPlainText() == 'red a'
                return
            w.f_font.currentFontChanged.connect(destination)
            # No settle/reactivation between the commit and the observer.
            view = w.f_font.view()
            index = w.f_font.model().index(w.f_font.findText(different_family(w, item)), 0)
            view.scrollTo(index)
            settle()
            point = view.visualRect(index).center()
            QTest.mouseMove(view.viewport(), point + QPoint(5, 0))
            QTest.mouseMove(view.viewport(), point)
            QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=point)
            assert not view.isVisible()
        assert acquired and all(acquired)
        settle()
        if ending == 'dialog':
            assert QApplication.activeWindow() is dialog
            focused_key(field, Qt.Key_A)
            assert field.text() == 'a'
            dialog.hide()
            w.activateWindow()
            settle()
        else:
            w.activateWindow()
            settle()
        assert QApplication.focusWidget() is w.s_width
        assert w.doc.selected() == [item] and w.view.tool is Tool.SELECT
    finally:
        dialog.hide()
        dialog.deleteLater()


@pytest.mark.parametrize('ending', ['hover', 'refresh', 'index', 'bare_hide'])
def test_uncommitted_choice_never_hands_picture_focus(window, ending):
    w = window
    rect = selected_shape(w, Tool.RECT)
    open_choice(w, w.cb_line, 'keyboard')
    activations = []
    handbacks = []
    w.cb_line.activated.connect(activations.append)
    w.cb_line.mouseCommitted.connect(lambda: handbacks.append(True))
    if ending == 'hover':
        view = w.cb_line.view()
        index = w.cb_line.model().index(w.cb_line.findData('dashed'), 0)
        QTest.mouseMove(view.viewport(), view.visualRect(index).center())
    elif ending == 'refresh':
        w.refresh_props()
    elif ending == 'index':
        w.cb_line.setCurrentIndex(w.cb_line.findData('dashed'))
    settle()
    assert QApplication.focusWidget() is w.cb_line.view()
    w.cb_line.hidePopup()
    w.activateWindow()
    settle()
    assert QApplication.focusWidget() is w.cb_line
    assert activations == [] and handbacks == []
    assert w.doc.selected() == [rect] and w.view.tool is Tool.SELECT
