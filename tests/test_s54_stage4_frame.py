"""s54 stage 4. Qt's existing offscreen test road; no native proof claimed."""
from pathlib import Path

import pytest
from PySide6.QtCore import (QByteArray, QCoreApplication, QDateTime, QEvent,
                            QPoint, QRect, QSize, Qt)
from PySide6.QtGui import QImage, QPainter, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QDockWidget, QListWidget,
                               QMessageBox, QStyle, QStyleOptionViewItem)

from annotshot import recent, theme
from annotshot.mainwindow import MainWindow
from annotshot.scene import Document
from test_s3b2 import picture

LEFT, RIGHT, BOTTOM = Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea, Qt.BottomDockWidgetArea


def settle(qapp):
    assert recent.writer().waitForDone(5000)
    qapp.processEvents()
    qapp.processEvents()


@pytest.fixture
def windows(qapp, monkeypatch):
    from annotshot.app import make_app
    make_app()
    monkeypatch.setattr(MainWindow, '_warn', lambda self, text: pytest.fail(text))
    made = []
    def create(editor=True):
        w = MainWindow()
        made.append(w)
        if editor:
            w._bind(Document(picture()))
            w.show()
            settle(qapp)
        return w
    yield create
    settle(qapp)
    for w in made:
        w._autosave_timer.stop()
        w.hide()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def seed(w, n=3):
    when = QDateTime.fromString('2020-01-01T00:00:00.000', Qt.ISODateWithMs)
    paths = [w.recent_store.file(picture(24, 40, '#3366CC'),
                                when.addSecs(i), keep=100) for i in range(n)]
    w.recent.refresh()
    return paths


def framed(w):
    return [Path(w.recent.list.item(i).data(Qt.UserRole)).stem
            for i in range(w.recent.list.count())
            if w.recent.list.item(i).data(recent.CURRENT_ROLE)]


def first(pane):
    return next((p for p in pane.paths() if not pane.list.visualItemRect(
        pane.list.item(pane.paths().index(p))).intersected(pane.list.viewport().rect()).isEmpty()), None)


@pytest.mark.parametrize('state', ['empty', 'corrupt', 'left', 'hidden', 'float'])
def test_r38_default_and_legacy_layout_in_second_window(windows, monkeypatch, state):
    w = windows()
    if state == 'left':
        w.addDockWidget(LEFT, w.recent)
    elif state == 'hidden':
        w.recent.hide()
    elif state == 'float':
        w.recent.setFloating(True)
        w.recent.resize(600, 200)
    w._save_editor_geometry()
    if state in ('empty', 'corrupt'):
        w.settings.setValue('window/state', QByteArray() if state == 'empty' else QByteArray(b'broken'))
    for key in ('recent/edge-v1', 'recent/direction-v1'):
        w.settings.remove(key)  # legacy saveState, without stage-4 metadata
    monkeypatch.setattr(MainWindow, '_recent_placement_valid', lambda self: True)
    w2 = windows()
    assert len(w2.findChildren(QDockWidget, 'recentPane')) == 1
    if state == 'float':
        assert w2.recent.isFloating() and w2.recent.direction == 'horizontal'
    else:
        assert w2.dockWidgetArea(w2.recent) == (LEFT if state == 'left' else RIGHT)
        assert w2.recent.direction == 'vertical'
        assert w2.recent.isHidden() == (state == 'hidden')


def test_r39_bottom_is_one_row_and_fits_title_caption_and_scrollbar(windows, qapp):
    w = windows()
    paths = seed(w, 10)
    w.addDockWidget(BOTTOM, w.recent)
    for size in (QSize(1100, 720), QSize(900, 600), QSize(1300, 900)):
        w.resize(size)
        settle(qapp)
        p = w.recent
        rects = [p.list.visualItemRect(p.list.item(i)) for i in range(p.list.count())]
        assert p.direction == 'horizontal' and p.list.flow() == QListWidget.LeftToRight
        assert not p.list.isWrapping() and len({r.top() for r in rects}) == 1
        assert p.paths() == [str(x) for x in reversed(paths)]
        assert p.list.viewport().height() >= p.list.gridSize().height()
        assert p.height() <= p.sizeHint().height() + 12
        assert p.list.horizontalScrollBar().maximum() > 0


def test_r40_scroll_wheel_and_keyboard_reach_oldest_without_open(windows, qapp):
    w = windows()
    seed(w, 18)
    w.addDockWidget(BOTTOM, w.recent)
    settle(qapp)
    p, doc = w.recent, w.doc
    bar = p.list.horizontalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(bar.maximum())
    assert p.list.visualItemRect(p.list.item(17)).intersects(p.list.viewport().rect())
    bar.setValue(0)
    event = QWheelEvent(QPoint(20, 20), QPoint(20, 20), QPoint(), QPoint(0, -120),
                        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(p.list.viewport(), event)
    assert bar.value() > 0
    bar.setValue(0)
    p.list.setCurrentRow(0)
    p.list.setFocus()
    for _ in range(17):
        QTest.keyClick(p.list, Qt.Key_Right)
    assert p.list.currentRow() == 17
    assert p.list.visualItemRect(p.list.currentItem()).intersects(p.list.viewport().rect())
    QTest.keyClick(p.list, Qt.Key_Left)
    assert p.list.currentRow() == 16 and w.doc is doc


@pytest.mark.parametrize('edge', [LEFT, RIGHT])
def test_r41_bottom_to_side_keeps_selection_membership_and_column(windows, qapp, edge):
    w = windows()
    seed(w, 18)
    p = w.recent
    w.addDockWidget(BOTTOM, p)
    p.list.setCurrentRow(7)
    wanted, members = p.list.currentItem().data(Qt.UserRole), p.paths()
    w.addDockWidget(edge, p)
    settle(qapp)
    assert p.direction == 'vertical' and p.list.flow() == QListWidget.TopToBottom
    assert p.list.verticalScrollBar().maximum() > 0
    assert p.paths() == members and p.list.currentItem().data(Qt.UserRole) == wanted
    assert len({p.list.visualItemRect(p.list.item(i)).left() for i in range(18)}) == 1


@pytest.mark.parametrize('edge', [BOTTOM, LEFT])
@pytest.mark.parametrize('size,expected', [((600, 501), None), ((600, 500), 'horizontal'),
                                         ((600, 499), 'horizontal'), ((500, 600), 'vertical'),
                                         ((501, 600), None), ((499, 600), 'vertical')])
def test_r42_first_float_hysteresis_exact_client_boundaries(windows, edge, size, expected):
    w = windows()
    seed(w)
    p = w.recent
    w.addDockWidget(edge, p)
    initial = 'horizontal' if edge == BOTTOM else 'vertical'
    p.setFloating(True)
    p.set_direction(initial)
    p.resize(*size)
    assert p.direction == (expected or initial)
    assert p.list.flow() == (QListWidget.LeftToRight if p.direction == 'horizontal'
                             else QListWidget.TopToBottom)


def test_r42_resize_keeps_surviving_anchor_and_selection_then_clicks_once(windows, qapp, monkeypatch):
    w = windows()
    seed(w, 25)
    p = w.recent
    w.addDockWidget(BOTTOM, p)
    p.setFloating(True)
    p.resize(700, 300)
    settle(qapp)
    p.list.setCurrentRow(12)
    p.list.scrollToItem(p.list.item(7), QListWidget.PositionAtTop)
    settle(qapp)
    anchor, selected, members = first(p), p.list.currentItem().data(Qt.UserRole), p.paths()
    p.resize(300, 700)
    settle(qapp)
    assert p.direction == 'vertical' and first(p) == anchor
    assert p.paths() == members and p.list.currentItem().data(Qt.UserRole) == selected
    calls = []
    p.openRequested.connect(calls.append)
    p._clicked(p.list.item(0))
    settle(qapp)
    assert len(calls) == 1 and framed(w) == [Path(members[0]).stem]
    assert w.view.hasFocus()
    monkeypatch.setattr(MainWindow, '_recent_placement_valid', lambda self: True)
    for direction, wide in [('vertical', False), ('horizontal', True)]:
        p.resize(700, 300) if wide else p.resize(300, 700)
        p.resize(500, 500)  # dead band: restored direction must be saved, not guessed
        w._save_editor_geometry()
        again = windows()
        assert again.recent.isFloating() and again.recent.direction == direction


@pytest.mark.parametrize('edge', [LEFT, RIGHT, BOTTOM, Qt.NoDockWidgetArea])
def test_r43_close_float_redocks_same_object_and_persists(windows, qapp, edge):
    w = windows()
    p = w.recent
    w.addDockWidget(edge if edge != Qt.NoDockWidgetArea else RIGHT, p)
    p.setFloating(True)
    if edge == Qt.NoDockWidgetArea:
        p.last_edge = Qt.NoDockWidgetArea
    p.close()
    settle(qapp)
    want = edge if edge != Qt.NoDockWidgetArea else RIGHT
    assert w.recent is p and not p.isFloating() and not p.isHidden()
    assert w.dockWidgetArea(p) == want
    w.show_welcome()
    w2 = windows()
    assert not w2.recent.isHidden() and not w2.recent.isFloating()
    assert w2.dockWidgetArea(w2.recent) == want


def test_r44_bottom_close_frees_canvas_and_reveals_after_restart(windows, qapp):
    w = windows()
    w.addDockWidget(BOTTOM, w.recent)
    settle(qapp)
    before = w.view.height()
    w.recent.close()
    settle(qapp)
    assert w.view.height() > before
    w.show_welcome()
    w2 = windows()
    assert w2.recent.isHidden()
    for _ in range(2):
        w2.a_recent.trigger()
        settle(qapp)
        assert not w2.recent.isHidden() and w2.dockWidgetArea(w2.recent) == BOTTOM
        assert w2.recent.list.hasFocus()


@pytest.mark.parametrize('case,valid', [('flush', True), ('negative', True),
    ('one-out', False), ('title-out', False), ('seam', False), ('lost', False), ('unknown', False)])
def test_r45_visible_title_and_client_share_one_usable_logical_screen(windows, monkeypatch, case, valid):
    w = windows()
    p = w.recent
    w.addDockWidget(LEFT, p)
    p.setFloating(True)
    # Ignore an invisible native border/shadow, including snapped edges.
    from types import SimpleNamespace
    from PySide6.QtCore import QMargins
    with monkeypatch.context() as native:
        native.setattr(p, 'windowHandle', lambda: SimpleNamespace(frameMargins=lambda: QMargins(8, 38, 8, 8)))
        native.setattr(p, 'frameGeometry', lambda: QRect(-99999, -99999, 200000, 200000))
        title_rect, client_rect = w._recent_visible_rects()
        assert title_rect.height() == 30
        assert title_rect.bottom() + 1 == client_rect.top()
        assert client_rect.size() == p.size()
    screens = [QRect(0, 0, 1000, 800), QRect(-1000, 0, 1000, 800)]
    client, title = QRect(0, 30, 1000, 770), QRect(0, 0, 1000, 30)
    if case == 'negative':
        client.translate(-1000, 0)
        title.translate(-1000, 0)
    elif case == 'one-out':
        client.adjust(0, 0, 1, 0)
    elif case == 'title-out':
        title.translate(0, -1)
    elif case == 'seam':
        client.translate(-10, 0)
        title.translate(-10, 0)
    elif case == 'lost':
        screens = []
    monkeypatch.setattr(w, '_recent_screen_areas', lambda: screens)
    monkeypatch.setattr(w, '_recent_visible_rects', lambda: None if case == 'unknown' else (title, client))
    assert w._recent_placement_valid() is valid
    w._save_editor_geometry()
    w.show_welcome()
    w.show_editor()
    assert p.isFloating() is valid
    assert not p.isHidden()
    if not valid:
        assert w.dockWidgetArea(p) == LEFT
        # Inspect actual recovery, rather than trusting only _editor_state.
        w2 = windows()
        assert not w2.recent.isFloating() and not w2.recent.isHidden()
        assert w2.dockWidgetArea(w2.recent) == LEFT


@pytest.mark.parametrize('floating,placement,raised', [(False, True, True), (True, True, True),
                                                     (True, False, True), (True, True, False)])
def test_r46_repeat_reveal_and_escape_handoff(windows, qapp, monkeypatch, floating, placement, raised):
    from annotshot.tools import Tool
    w = windows()
    seed(w)
    p, doc = w.recent, w.doc
    w.addDockWidget(BOTTOM, p)
    p.setFloating(floating)
    p.hide()
    raises = []
    monkeypatch.setattr(w, '_recent_placement_valid', lambda: placement)
    native = w._raise_recent
    requested = []
    monkeypatch.setattr(p, 'raise_', lambda: requested.append('raise'))
    real_activate = p.activateWindow
    monkeypatch.setattr(p, 'activateWindow', lambda: (requested.append('activate'), real_activate()))
    def raise_result():
        raises.append(True)
        native()
        assert not p.isMinimized()
        return None
    monkeypatch.setattr(w, '_raise_recent', raise_result)
    monkeypatch.setattr(p, 'isActiveWindow', lambda: raised)
    if floating:
        p.showMinimized()
    for _ in range(2):
        w.a_recent.trigger()
        w._recent_raise_finished()  # deliver the controlled native result
        settle(qapp)
        assert not p.isHidden() and p.list.hasFocus()
        assert w.doc is doc
    assert p.isFloating() == (floating and placement and raised)
    if floating and placement:
        assert raises and requested[:2] == ['raise', 'activate']
    QTest.keyClick(p.list, Qt.Key_Escape)
    settle(qapp)
    assert w.view.hasFocus() and not p.isHidden() and w.doc is doc
    QTest.keyClick(w.view, Qt.Key_A)
    assert w.view.tool == Tool.ARROW


@pytest.mark.parametrize('valid', [True, False])
def test_r47_welcome_has_no_orphan_and_restores_or_recovers(windows, qapp, monkeypatch, valid):
    w = windows()
    p = w.recent
    w.addDockWidget(BOTTOM, p)
    p.setFloating(True)
    p.resize(600, 300)
    w.show_welcome()
    assert p.isHidden() and p.isFloating()
    saved = w.settings.value('window/state', type=QByteArray)
    w.close()
    assert w.settings.value('window/state', type=QByteArray) == saved
    monkeypatch.setattr(MainWindow, '_recent_placement_valid', lambda self: valid)
    w2 = windows()
    assert w2.recent.isFloating() == valid and not w2.recent.isHidden()
    assert w2.recent.direction == 'horizontal'


@pytest.mark.parametrize('source', ['png', 'paired-png', 'paired-editable', 'editable-only'])
def test_r52_every_open_road_matches_folder_and_stem(windows, source):
    w = windows()
    a, b, _ = seed(w)
    editable = recent.editable_for(a)
    if source != 'png':
        Document(picture()).save(str(editable))
    if source == 'editable-only':
        a.unlink()
    w.recent.refresh()
    path = editable if source in ('paired-editable', 'editable-only') else a
    assert (w.open_recent(str(path)) if path.suffix == '.png'
            else w.open_path(str(path)))
    assert framed(w) == [a.stem]
    outside = a.parent.parent / editable.name
    Document(picture()).save(str(outside))
    assert w.open_path(str(outside))
    assert framed(w) == []
    assert w.open_recent(str(b))
    late = w.recent_store.reserve()
    pending = Document(picture())
    pending.path = str(recent.editable_for(late))
    pending._recent_source = recent.capture_source(late)
    w._bind(pending)
    assert framed(w) == []  # accepted before its first PNG lands
    assert w.open_recent(str(b))
    w.recent.file_capture(picture(), wait=True, path=late, keep=100)
    assert framed(w) == [b.stem]
    w._bind(Document(picture()))
    assert framed(w) == []
    w.show_welcome()
    assert framed(w) == []


def test_r53_frame_moves_at_bind_only_and_save_does_not_move_it(windows, qapp, monkeypatch, tmp_path):
    from annotshot import mainwindow
    w = windows()
    a, b, _ = seed(w)
    assert w.open_recent(str(a))
    p = w.recent
    held = []
    real_request = w.open_recent
    monkeypatch.setattr(w, 'open_recent', lambda path: held.append(path) or False)
    p._clicked(p.list.item(1))
    assert framed(w) == [a.stem] and held == [str(b)]
    monkeypatch.setattr(w, 'open_recent', real_request)
    monkeypatch.setattr(w, 'maybe_discard', lambda: False)
    p._clicked(p.list.item(1))
    assert framed(w) == [a.stem]
    monkeypatch.setattr(w, 'maybe_discard', lambda: True)
    load = recent.load_edit
    def broken(*args, **kwargs):
        raise OSError('fixture read failure')
    monkeypatch.setattr(recent, 'load_edit', broken)
    p._clicked(p.list.item(1))
    assert framed(w) == [a.stem]
    monkeypatch.setattr(recent, 'load_edit', load)
    p._clicked(p.list.item(1))
    assert framed(w) == [b.stem] and w.view.hasFocus()
    p.list.setCurrentRow(2)
    menu = p.menu_for(p.list.item(2))
    assert framed(w) == [b.stem]
    menu.deleteLater()
    monkeypatch.setattr(mainwindow.QFileDialog, 'getSaveFileName',
                        lambda *args, **kwargs: (str(tmp_path / 'copy.png'), mainwindow.SAVE_TYPES[0][0]))
    assert w.save_recent(str(a))
    assert framed(w) == [b.stem]


def test_r54_current_click_preserves_live_edit_undo_selection_caret_zoom(windows, qapp, monkeypatch):
    from annotshot.items import TextBoxItem
    w = windows()
    a, _, _ = seed(w)
    assert w.open_recent(str(a))
    doc = w.doc
    t = TextBoxItem()
    t.set_geom((2, 2, 200, 80))
    doc.add_items([t])
    doc.select_only([t])
    t.start_edit()
    t.editor.setPlainText('unsaved live words')
    cursor = t.editor.textCursor()
    cursor.setPosition(7)
    t.editor.setTextCursor(cursor)
    w._autosave_timer.stop()
    w.view.set_zoom(1.7)
    snapshot = (doc.undo_stack.index(), t.editor.document().isUndoAvailable(),
                doc.selected(), t.editor.textCursor().position(), w.view.zoom)
    assert picture(color='#FF0000').save(str(a))
    calls = []
    with monkeypatch.context() as click_patch:
        click_patch.setattr(w, 'maybe_discard', lambda: calls.append('prompt') or False)
        click_patch.setattr(recent, 'load_edit', lambda *a, **k: calls.append('reload'))
        click_patch.setattr(w, 'autosave_now', lambda *a, **k: calls.append('write'))
        item = next(w.recent.list.item(i) for i in range(w.recent.list.count())
                    if Path(w.recent.list.item(i).data(Qt.UserRole)).stem == a.stem)
        w.recent._clicked(item)
        w.recent._double_clicked(item)
        w.recent._last_click = None
        w.recent._double_clicked(item)
        settle(qapp)
        assert calls == []
        assert w.doc is doc and doc.editing_item is t
        assert (doc.undo_stack.index(), t.editor.document().isUndoAvailable(),
                doc.selected(), t.editor.textCursor().position(), w.view.zoom) == snapshot
        assert t.editor.toPlainText() == 'unsaved live words'



@pytest.mark.parametrize('look', ['light', 'dark', 'retro'])
def test_r55_equal_gutters_two_pixel_frame_pixels_focus_and_accessible_names(windows, qapp, look):
    theme.apply(qapp, look)
    w = windows()
    a, b, _ = seed(w)
    assert w.open_recent(str(a))
    p = w.recent
    p.retheme()
    assert theme.current() == look
    assert p.list.gridSize() == QSize(recent.THUMB.width() + 12, recent.THUMB.height() + 26)
    delegate = p.list.itemDelegate()
    images = []
    for path in (a, b):
        row = p.paths().index(str(path))
        item = p.list.item(row)
        p.list.setCurrentItem(item)
        p.list.setFocus()
        settle(qapp)
        assert framed(w) == [a.stem]
        option = QStyleOptionViewItem()
        option.rect = QRect(QPoint(), p.list.gridSize())
        option.state = QStyle.State_Enabled | QStyle.State_HasFocus
        option.font = item.font()
        img = QImage(option.rect.size(), QImage.Format_ARGB32)
        img.fill(Qt.magenta)
        painter = QPainter(img)
        delegate.paint(painter, option, p.list.model().index(row, 0))
        painter.end()
        rect = delegate.image_rect(option.rect)
        assert rect.left() == option.rect.width() - rect.right() - 1
        plain = item.icon().pixmap(recent.THUMB).toImage()
        assert img.copy(rect).convertToFormat(plain.format()) == plain
        if path == a:
            for y in (rect.top() - 1, rect.top() - 2):
                assert img.pixelColor(rect.center().x(), y) == theme.color('accent')
            assert img.pixelColor(rect.center().x(), rect.top() - 3) == theme.color('surface')
            assert item.data(Qt.AccessibleTextRole) == 'Current, ' + item.text()
        else:
            assert item.data(Qt.AccessibleTextRole) == item.text()
            assert img.pixelColor(rect.center().x(), rect.top() - 1) == theme.color('surface')
        # A dotted focus perimeter encloses image AND caption independently.
        top = [img.pixelColor(x, 1) for x in range(2, img.width() - 2)]
        assert len({c.rgba() for c in top}) >= 2
        images.append(img)
    assert framed(w) == [a.stem]


@pytest.fixture
def displayed(monkeypatch):
    """Stage 5 owns Find. Filter membership here through the actual refresh road."""
    def filter_to(w, paths):
        monkeypatch.setattr(w.recent_store, 'files', lambda: list(paths))
        w.recent.refresh()
    return filter_to


@pytest.mark.parametrize('edge', [LEFT, RIGHT, BOTTOM, 'float-wide', 'float-tall'])
def test_r56_filtered_rebuild_keeps_canvas_focus_anchor_without_scroll_to_current(windows, qapp, displayed, edge):
    w = windows()
    paths = seed(w, 25)
    a = paths[-1]
    assert w.open_recent(str(a))
    p, doc = w.recent, w.doc
    if isinstance(edge, str):
        p.setFloating(True)
        p.resize(700, 300) if edge == 'float-wide' else p.resize(300, 700)
    else:
        w.addDockWidget(edge, p)
    settle(qapp)
    p.list.setCurrentRow(10)
    p.list.setFocus()
    p.list.scrollToItem(p.list.item(7), QListWidget.PositionAtTop)
    settle(qapp)
    anchor, focused = first(p), p.list.currentItem().data(Qt.UserRole)
    shown = [Path(x) for x in p.paths() if Path(x) != a]
    displayed(w, shown)
    settle(qapp)
    assert framed(w) == [] and w.doc is doc
    assert first(p) == anchor and p.list.currentItem().data(Qt.UserRole) == focused
    displayed(w, list(reversed(paths)))
    settle(qapp)
    assert framed(w) == [a.stem] and w.doc is doc and first(p) == anchor
    assert p.list.hasFocus() and p.list.currentItem().data(Qt.UserRole) == focused
    p.refresh_one(a)
    assert framed(w) == [a.stem] and first(p) == anchor


@pytest.mark.parametrize('action', ['delete-a', 'clear', 'expire-a', 'cancel', 'delete-b', 'lower'])
def test_r57_explicit_removal_and_rotation_never_mark_a_neighbour(windows, qapp, monkeypatch, action):
    w = windows()
    a, b, c = seed(w)
    assert w.open_recent(str(a))
    assert framed(w) == [a.stem]
    doc = w.doc
    if action == 'delete-a':
        w.recent.delete(str(a))
    elif action in ('clear', 'cancel'):
        monkeypatch.setattr(recent.QMessageBox, 'question',
                            lambda *args, **kwargs: QMessageBox.Yes if action == 'clear' else QMessageBox.Cancel)
        w.recent.clear()
    elif action == 'expire-a':
        w.recent.file_capture(picture(), wait=True, keep=2)
    elif action == 'delete-b':
        w.recent.delete(str(b))
    else:
        w.set_capture_count(1)
    settle(qapp)
    removed = action in ('delete-a', 'clear', 'expire-a')
    assert framed(w) == ([] if removed else [a.stem])
    if action in ('delete-a', 'clear'):
        assert w.state_name == 'welcome'
    else:
        assert w.doc is doc and w.state_name == 'editor'
    if removed:
        assert not a.exists() and not recent.editable_for(a).exists()
    if action == 'expire-a':
        from annotshot.items import TextBoxItem
        assert doc.path is None
        doc.add_items([TextBoxItem()])
        w.autosave_now(end_edit=True)
        settle(qapp)
        assert not a.exists() and not recent.editable_for(a).exists()


@pytest.mark.parametrize('fault', ['edge', 'direction', 'write', 'sync'])
def test_recovery_corrupt_metadata_or_settings_failure_stays_visible(windows, qapp, monkeypatch, fault):
    w = windows()
    w.recent.setFloating(True)
    w._save_editor_geometry()
    w.show_welcome()
    w.settings.setValue('recent/edge-v1', 'nonsense' if fault == 'edge' else 'bottom')
    w.settings.setValue('recent/direction-v1', 'nonsense' if fault == 'direction' else 'horizontal')
    monkeypatch.setattr(MainWindow, '_recent_placement_valid', lambda self: False)
    w2 = windows(False)
    if fault in ('write', 'sync'):
        def fail(*args, **kwargs):
            raise OSError('settings ' + fault + ' failed')
        monkeypatch.setattr(w2.settings, 'setValue' if fault == 'write' else 'sync', fail)
    w2.show_editor()
    settle(qapp)
    assert not w2.recent.isHidden() and not w2.recent.isFloating()
    assert w2.dockWidgetArea(w2.recent) in (RIGHT, BOTTOM)
