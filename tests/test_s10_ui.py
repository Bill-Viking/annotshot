"""s10 interface guards. All widgets use Qt offscreen and private settings."""
import ast
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QScrollArea, QStyle, QStyleFactory, QStyleOptionComboBox,
                               QStyleOptionToolButton, QToolBar, QToolButton)

from annotshot import theme, typefaces
from annotshot.items import ITEM_TYPES, ArrowItem, CalloutItem, RectItem, TextBoxItem
from annotshot.mainwindow import MainWindow, TOOL_HINTS, TOOL_KEYS
from annotshot.scene import Document
from annotshot.settings_dialog import SettingsDialog
from annotshot.tools import ITEM_FOR_TOOL, Tool


@pytest.fixture
def window(qapp, white):
    from annotshot.app import make_app
    make_app()
    w = MainWindow()
    w._bind(Document(white))  # These guards exercise the editor state.
    yield w
    w.doc.undo_stack.mark_exported()
    w.hide()
    w.deleteLater()
    qapp.processEvents()


def settle(w, qapp, width=1100):
    w.resize(width, 720)
    w.show()
    w.layout().activate()
    for _ in range(3):
        qapp.processEvents()


def test_01_shortcuts_reset_edges_inside_viewport(window, qapp):
    dialog = SettingsDialog(window)
    dialog.show()
    dialog.layout().activate()
    for _ in range(3):
        qapp.processEvents()
    assert (dialog.width(), dialog.height()) == (520, 640)
    scroll = dialog.tabs.widget(0)
    assert isinstance(scroll, QScrollArea)
    assert scroll.horizontalScrollBar().maximum() == 0
    for button in [*dialog.resets.values(), dialog.hotkey_reset]:
        right = button.mapTo(scroll.viewport(), QPoint(button.width(), 0)).x()
        assert right <= scroll.viewport().width()
        assert button.width() >= button.sizeHint().width()
    dialog.close()


@pytest.mark.parametrize('tool,cls', ITEM_FOR_TOOL.items())
def test_02_only_applicable_controls_show(window, qapp, tool, cls):
    settle(window, qapp)
    window.view.set_tool(tool)
    text = {'font_family', 'font_px', 'bold', 'italic', 'align', 'text_color',
            'fill_color', 'border_color', 'border_width', 'opacity'}
    shape = {'fill_color', 'border_color', 'border_width', 'line_style', 'opacity'}
    line = {'border_color', 'border_width', 'line_style', 'opacity'}
    expected = {
        Tool.TEXT: text, Tool.CALLOUT: text, Tool.RECT: shape, Tool.ELLIPSE: shape,
        Tool.ARROW: line | {'head', 'head_size', 'both_ends'}, Tool.PEN: line,
        Tool.HIGHLIGHT: {'fill_color', 'opacity'}}[tool]
    for control, key in window._controls.items():
        applicable = key in expected
        if control is window.b_nofill and tool is Tool.HIGHLIGHT:
            applicable = False
        if control is window.b_noborder and tool in (Tool.ARROW, Tool.PEN):
            applicable = False
        assert control.isVisibleTo(window) == applicable, (tool, key)


def test_02_mixed_selection_keeps_applicability_union(window, qapp):
    settle(window, qapp)
    text, arrow, highlight = TextBoxItem(), ArrowItem(), ITEM_TYPES['highlight']()
    window.doc.add_items([text, arrow, highlight])
    window.doc.select_only([text, arrow, highlight])
    assert window.f_font.isVisibleTo(window)
    assert window.cb_head.isVisibleTo(window)
    assert window.c_fill.isVisibleTo(window)
    window._set({'font_px': 37, 'border_color': '#0000FF'}, 'Mixed')
    assert text.props['font_px'] == 37 and 'font_px' not in arrow.props
    assert arrow.props['stroke_color'] == '#0000FF'
    window.doc.select_only([arrow])
    assert not window.f_font.isVisibleTo(window)
    assert not window.c_fill.isVisibleTo(window)


@pytest.mark.parametrize('width', [1100, 1360])
def test_03_two_rows_and_view_top_constant(window, qapp, width):
    settle(window, qapp, width)
    top = window.view.geometry().top()
    height = window.prop_scroll.height()
    for tool in Tool:
        window.doc.clearSelection()
        window.view.set_tool(tool)
        for _ in range(2):
            qapp.processEvents()
        assert window.view.geometry().top() == top, tool
        assert window.prop_scroll.height() == height, tool
        assert window.prop_strip.layout().count() == 2
        assert window.prop_scroll.horizontalScrollBar().maximum() == 0, tool
        for row in (window.prop_row1, window.prop_row2):
            assert row.sizeHint().width() <= window.prop_scroll.viewport().width(), tool
        if tool in ITEM_FOR_TOOL:
            items = [ITEM_FOR_TOOL[tool]() for _ in range(3)]
            window.doc.add_items(items)
            for selection in (items[:1], items):
                window.doc.select_only(selection)
                qapp.processEvents()
                assert window.view.geometry().top() == top
                assert window.prop_scroll.horizontalScrollBar().maximum() == 0
    window.doc.select_only(window.doc.annotation_items())
    qapp.processEvents()
    assert window.view.geometry().top() == top
    assert window.prop_scroll.horizontalScrollBar().maximum() == 0


def test_03_oversized_control_falsifies_fit_without_third_row(window, qapp):
    settle(window, qapp)
    window.view.set_tool(Tool.TEXT)
    top = window.view.geometry().top()
    window.f_font.setFixedWidth(1800)
    window.refresh_props()
    qapp.processEvents()
    assert window.prop_scroll.horizontalScrollBar().maximum() > 0
    assert window.prop_strip.layout().count() == 2
    assert window.view.geometry().top() == top


@pytest.mark.parametrize('tool', [Tool.SELECT, Tool.CROP])
def test_04_select_crop_are_instructions_without_defaults(window, qapp, tool):
    settle(window, qapp)
    before = dict(window.view.tool_defaults['text'])
    window.view.set_tool(tool)
    assert window.view.defaults_item() is None
    assert window.sel_heading.text() == TOOL_HINTS[tool]
    assert window.sel_heading.objectName() == 'stripHint'
    assert all(not control.isVisibleTo(window) for control in window._controls)
    window._set({'font_px': 73}, 'No target')
    assert window.view.tool_defaults['text'] == before


@pytest.mark.parametrize('tool,new,single,plural', [
    (Tool.TEXT, 'New text', 'This text', '3 text objects'),
    (Tool.CALLOUT, 'New callouts', 'This callout', '3 callouts'),
    (Tool.RECT, 'New rectangles', 'This rectangle', '3 rectangles'),
    (Tool.ELLIPSE, 'New ellipses', 'This ellipse', '3 ellipses'),
    (Tool.ARROW, 'New arrows', 'This arrow', '3 arrows'),
    (Tool.HIGHLIGHT, 'New highlights', 'This highlight', '3 highlights'),
    (Tool.PEN, 'New pen strokes', 'This pen stroke', '3 pen strokes')])
def test_05_plain_headings(window, tool, new, single, plural):
    window.view.set_tool(tool)
    assert window.sel_heading.text() == new
    items = [ITEM_FOR_TOOL[tool]() for _ in range(3)]
    window.doc.add_items(items)
    window.doc.select_only(items[:1])
    assert window.sel_heading.text() == single
    window.doc.select_only(items)
    assert window.sel_heading.text() == plural
    other = RectItem() if tool is Tool.TEXT else TextBoxItem()
    window.doc.add_items([other])
    window.doc.select_only([items[0], items[1], other])
    assert window.sel_heading.text() == '3 objects'


def test_06_item_action_words_and_no_tools_overflow(window, qapp):
    settle(window, qapp)
    bar = window.findChild(QToolBar, 'tools')
    for action in (window.a_dup, window.a_front, window.a_back, window.a_delete):
        button = bar.widgetForAction(action)
        assert button.toolButtonStyle() == Qt.ToolButtonTextBesideIcon
        assert button.text() == action.text()
    assert not bar.findChild(QToolButton, 'qt_toolbar_ext_button').isVisibleTo(window)
    for action in bar.actions():
        widget = bar.widgetForAction(action)
        assert widget.isVisibleTo(window)
        assert widget.geometry().right() < bar.width()


def test_07_close_picture_name_position_key_and_recent(window, white):
    bar = window.findChild(QToolBar, 'main')
    actions = bar.actions()
    index = actions.index(window.a_clear)
    assert window.a_clear.text() == 'Close picture'
    assert actions[index - 1].isSeparator()
    assert actions[index + 1] is window.a_undo
    assert window.a_clear.shortcut() == QKeySequence('Ctrl+W')
    assert 'stay in Recent captures' in window.a_clear.toolTip()
    window.recent.file_capture(white, wait=True)
    count = window.recent.list.count()
    kept = list(window.recent_store.folder.glob('*.png'))
    assert kept and window.open_recent(str(kept[0]))
    editable = Path(window.doc.path)
    window.doc.add_items([RectItem()])
    window.clear_picture()
    from annotshot import recent
    assert recent.writer().waitForDone(10000)
    assert window.statusBar().currentMessage() == 'Picture closed'
    assert window.doc.is_placeholder
    assert window.recent.list.count() == count
    assert all(path.exists() for path in kept)
    assert len(Document.load(editable).annotation_items()) == 1
    assert dict(window.shortcut_rows())['Close picture'] == [QKeySequence('Ctrl+W')]
    assert 'Close picture' in [a.text() for a in window.menu_actions(False) if a]


def test_08_direct_colour_dialog_uses_slashed_square(window, monkeypatch):
    from PySide6.QtWidgets import QColorDialog
    window.view.set_tool(Tool.TEXT)
    picked = []
    monkeypatch.setattr(QColorDialog, 'getColor', lambda *a, **k: picked.append(a) or QColor('blue'))
    for button, name in ((window.b_nofill, 'No fill'), (window.b_noborder, 'No border')):
        assert button.toolTip() == name
        assert button.text() == '' and not button.icon().isNull()
        button.click()
    window.c_fill.click()
    assert len(picked) == 1 and picked[0][0].alpha() == 255
    assert window.view.defaults_item().props['fill_color'] == '#0000FF'
    svg = Path('annotshot/icons/no-color.svg').read_text()
    assert '<rect' in svg and '<path' in svg


def test_09_native_current_keys_and_cleared_capture(window):
    assert window.set_shortcut('capture', QKeySequence('Alt+2')) is None
    key = window.a_capture.shortcut().toString(QKeySequence.NativeText)
    assert window.view.empty_hint[1] == f'Click Capture ({key}) to take a screenshot, or Open… a saved file'
    assert window.capture_status() == f'{key} to take a screenshot'
    assert window.statusBar().currentMessage() == window.capture_status()
    assert window.a_capture.toolTip().endswith(f'({key})')
    assert window.set_shortcut('capture', QKeySequence()) is None
    assert window.view.empty_hint[1] == 'Click Capture to take a screenshot, or Open… a saved file'
    assert '(' not in window.view.empty_hint[1]
    # Shortcut defaults are portable data; shown hints must not contain them.
    source = Path('annotshot/mainwindow.py').read_text()
    assert 'Ctrl+V to paste' not in source and 'Ctrl+N to capture' not in source
    assert 'QKeySequence.Paste' in source
    tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree)
               for child in ast.iter_child_nodes(node)}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and 'Ctrl+' in node.value):
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Expr):
            owner = parents.get(parent)
            if getattr(owner, 'body', [None])[0] is parent:
                continue  # documentation, never a shown UI string
        value = parent if isinstance(parent, (ast.List, ast.Tuple)) else node
        if isinstance(parents.get(value), ast.IfExp):
            value = parents[value]
        call = parents.get(value)
        assert (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == '_act' and len(call.args) > 2
                and call.args[2] is value), (node.lineno, node.value)


def test_10_default_and_ui_fonts_exist_and_saved_family_stays(window):
    family = TextBoxItem().props['font_family']
    assert not family.startswith('.')
    assert CalloutItem().props['font_family'] == family
    assert family in QFontDatabase.families()
    window.view.set_tool(Tool.TEXT)
    assert window.f_font.currentText() == family
    assert window.f_font.findText(family) >= 0
    for name in ('light', 'dark'):
        assert theme.font(name).family() in QFontDatabase.families()
    item = TextBoxItem()
    item.apply_props({'font_family': 'Unavailable saved family'})
    assert item.clone().props['font_family'] == 'Unavailable saved family'


def test_fix1_font_box_never_offers_or_displays_private_families(window):
    box = window.f_font
    assert all(not box.itemText(i).startswith('.') for i in range(box.count()))
    box.setCurrentFont(QFont('.AppleSystemUIFont'))
    assert box.currentText() == typefaces.text_family()
    assert box.findText(box.currentText()) >= 0
    item = TextBoxItem()
    item.apply_props({'font_family': '.AppleSystemUIFont'})
    assert item.props['font_family'] == typefaces.text_family()
    # Even a stale/foreign raw property cannot be written as a preference.
    item.props['font_family'] = '.AppleSystemUIFont'
    window.view.remember_style(item, ['font_family'])
    assert window.settings.value('props/text/font_family') is None


@pytest.mark.parametrize('kind', ['text', 'callout'])
def test_fix1_remembered_private_font_is_ignored(window, kind):
    key = f'props/{kind}/font_family'
    window.settings.setValue(key, '.AppleSystemUIFont')
    window.view.load_tool_defaults()
    factory = window.view.factory_style(kind)['font_family']
    assert not factory.startswith('.')
    assert window.view.starting_style(kind)['font_family'] == factory
    window.view.set_tool(Tool.TEXT if kind == 'text' else Tool.CALLOUT)
    assert window.f_font.currentText() == factory


@pytest.mark.parametrize('families,expected', [
    (['.Private', 'Zed', 'Arial', 'Helvetica Neue'], 'Helvetica Neue'),
    (['.Private', 'Zed', 'Arial'], 'Arial'),
    (['.Private', 'Zed', 'Another'], 'Zed')])
def test_fix1_mac_text_font_public_fallback_order(qapp, monkeypatch, families, expected):
    monkeypatch.setattr(typefaces.sys, 'platform', 'darwin')
    monkeypatch.setattr(QFontDatabase, 'families', lambda: families)
    monkeypatch.setattr(QFontDatabase, 'isPrivateFamily', lambda _: False)
    assert typefaces.text_family() == expected


def test_fix1_font_box_fits_public_default_names(window, qapp):
    settle(window, qapp)
    window.view.set_tool(Tool.TEXT)
    box = window.f_font
    option = QStyleOptionComboBox()
    box.initStyleOption(option)
    edit = box.style().subControlRect(QStyle.CC_ComboBox, option,
                                      QStyle.SC_ComboBoxEditField, box)
    assert box.width() >= 180
    for family in ('Helvetica Neue', 'Segoe UI'):
        assert box.fontMetrics().horizontalAdvance(family) <= edit.width()


@pytest.mark.parametrize('look', ['light', 'dark', 'retro'])
@pytest.mark.parametrize('zoom,label', [(1, '100 %'), (16, '1600 %')])
def test_fix1_zoom_text_and_arrow_have_separate_room(window, qapp, look, zoom, label):
    window.set_theme(look)
    settle(window, qapp)
    window.view.set_zoom(zoom)
    qapp.processEvents()
    button = window.zoom_label
    assert button.text() == label
    option = QStyleOptionToolButton()
    button.initStyleOption(option)
    # QSS reports zero for PM_MenuButtonIndicator when it styles the indicator
    # separately. Fusion's native arrow allowance is conservative (the QSS
    # arrow is smaller), and the app always uses Fusion under its stylesheet.
    native_style = QStyleFactory.create('Fusion')
    arrow = native_style.pixelMetric(QStyle.PM_MenuButtonIndicator, option, button)
    assert arrow > 0
    assert button.width() >= button.fontMetrics().horizontalAdvance(label) + arrow + 12


@pytest.mark.parametrize('is_mac', [True, False])
def test_fix1_redo_default_order_and_both_keys_work(qapp, monkeypatch, is_mac):
    from annotshot import macos
    from annotshot.app import make_app
    monkeypatch.setattr(macos, 'IS_MAC', is_mac)
    make_app()
    w = MainWindow()
    try:
        settle(w, qapp)
        keys = ['Ctrl+Shift+Z', 'Ctrl+Y'] if is_mac else ['Ctrl+Y', 'Ctrl+Shift+Z']
        expected = [QKeySequence(key) for key in keys]
        assert w.a_redo.shortcuts() == expected
        assert w.default_shortcuts['redo'] == expected
        assert dict(w.shortcut_rows())['Redo'] == expected
        assert w.a_redo.toolTip().endswith(f'({expected[0].toString(QKeySequence.NativeText)})')
        w.activateWindow()
        w.view.setFocus()
        for key in expected:
            item = RectItem()
            w.doc.add_items([item])
            w.undo()
            assert item not in w.doc.annotation_items()
            QTest.keySequence(w.view.viewport(), key)
            assert item in w.doc.annotation_items()
    finally:
        w.doc.undo_stack.mark_exported()
        w.hide()
        w.deleteLater()
        qapp.processEvents()


def test_10_unreadable_system_font_falls_back_to_installed(qapp, monkeypatch):
    def unreadable(*_):
        raise RuntimeError('system font unavailable')
    monkeypatch.setattr(QFontDatabase, 'systemFont', unreadable)
    monkeypatch.setattr(typefaces.sys, 'platform', 'darwin')
    assert typefaces.interface_family() in QFontDatabase.families()


def test_11_letters_type_in_text_and_font_but_select_tools_in_picture(window, qapp, white):
    settle(window, qapp)
    window._bind(Document(white))
    window.activateWindow()
    window.view.setFocus()
    letters = 'vtbreahpc'
    text = TextBoxItem()
    text.set_geom((10, 10, 300, 80))
    window.doc.add_items([text])
    window.doc.select_only([text])
    text.start_edit()
    qapp.processEvents()
    QTest.keyClicks(window.view.viewport(), letters)
    assert text.editor.toPlainText() == letters
    assert window.view.tool is Tool.SELECT
    window.doc.end_text_edit()
    window.view.set_tool(Tool.TEXT)
    font_edit = window.f_font.lineEdit()
    font_edit.setFocus()
    font_edit.selectAll()
    QTest.keyClicks(font_edit, letters)
    assert font_edit.text() == letters
    assert window.view.tool is Tool.TEXT
    window.view.setFocus()
    window.doc.clearSelection()
    for tool, key in TOOL_KEYS.items():
        QTest.keyClick(window.view.viewport(), getattr(Qt, 'Key_' + key))
        assert window.view.tool is tool
        assert window.tool_actions[tool].toolTip() == f'{tool.value} ({key})'
    assert window.set_shortcut('arrow', QKeySequence('X')) is None
    QTest.keyClick(window.view.viewport(), Qt.Key_X)
    assert window.view.tool is Tool.ARROW
    assert window.tool_actions[Tool.ARROW].toolTip() == 'Arrow (X)'
    assert 'arrow' in SettingsDialog(window).edits


def test_12_zoom_menu_reuses_view_zoom_and_settings(window, qapp):
    settle(window, qapp)
    assert isinstance(window.zoom_label, QToolButton)
    menu = window.zoom_label.menu()
    assert [a.text() for a in menu.actions()] == ['Fit', '100 %', '200 %', 'Zoom in', 'Zoom out']
    window.a_zoom200.trigger()
    assert window.view.zoom == 2 and window.zoom_label.text() == '200 %'
    window.a_zoom_in.trigger()
    assert window.view.zoom == 2.5
    window.a_zoom_out.trigger()
    assert window.view.zoom == 2
    window.a_zoom100.trigger()
    assert window.view.zoom == 1
    window.a_fit.trigger()
    assert 0 < window.view.zoom <= 1
    dialog = SettingsDialog(window)
    for name, key in [('fit', 'Ctrl+0'), ('zoom100', 'Ctrl+1'), ('zoom_in', 'Ctrl+='), ('zoom_out', 'Ctrl+-')]:
        assert window.shortcut_actions[name].shortcut() == QKeySequence(key)
        assert name in dialog.edits
    dialog.close()
