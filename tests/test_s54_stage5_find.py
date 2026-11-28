"""Stage 5, private libraries on the suite's existing offscreen Qt road."""
import json
import threading
import time
import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QDateTime, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit, QListWidget, QMessageBox, QToolButton

from annotshot import recent
from annotshot.mainwindow import MainWindow
from annotshot.scene import Document, LEGACY_FORMATS
from test_s3b2 import picture


SCOPE = 'Search words you typed in Text or Callout.'
NO_MATCH = 'No annotations match. Find looks at words you typed with Text or Callout.'


def settle(qapp, pane=None):
    deadline = time.monotonic() + 5
    while True:
        qapp.processEvents()
        if pane is None or not pane.find_pending():
            qapp.processEvents()
            return
        assert time.monotonic() < deadline, 'Find did not settle in 5 seconds'
        QTest.qWait(5)


@pytest.fixture
def window(qapp, monkeypatch):
    from annotshot.app import make_app
    make_app()
    w = MainWindow()
    w._bind(Document(picture()))
    w.show()
    settle(qapp)
    yield w
    w._autosave_timer.stop()
    w.recent.cancel_find()
    w.hide()
    w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def capture(w, index, texts=(), kind='pair', **meta):
    when = QDateTime.fromString('2020-01-01T00:00:00.000', Qt.ISODateWithMs).addSecs(index)
    p = w.recent_store.file(picture(24, 16), when, keep=100)
    if kind != 'png':
        data = dict(format='annotshot', version=1, size=[24, 16],
                    items=[dict(type=t, text=s) for t, s in texts])
        data.update(meta)
        with zipfile.ZipFile(p.with_suffix('.annotshot'), 'w') as z:
            z.writestr('project.json', json.dumps(data, ensure_ascii=False))
            # Deliberately not a usable base: Find must not decode it.
            z.writestr('base.png', b'not pixels: pixelword')
        if kind == 'editable':
            p.unlink()
            p = p.with_suffix('.annotshot')
    return p


def query(w, qapp, text):
    (w.recent if w.recent.isFloating() else w).activateWindow()
    qapp.processEvents()
    w.recent.find.setFocus()
    w.recent.find.setText(text)
    settle(qapp, w.recent)
    return w.recent.paths()


def marks(p):
    return [Path(p.list.item(i).data(Qt.UserRole)).stem for i in range(p.list.count())
            if p.list.item(i).data(recent.CURRENT_ROLE)]


def test_r24_live_normalized_literal_one_item_newest_once(window, qapp):
    a = capture(window, 1, [('text', 'Cafe\u0301 STRASSE')])
    b = capture(window, 2, [('callout', 'CAFÉ Straße'), ('text', 'café STRASSE')])
    capture(window, 3, [('text', 'café'), ('callout', 'STRASSE')])
    p = window.recent
    p.refresh()
    assert query(window, qapp, '  CAFE\u0301 straße  ') == [str(b), str(a)]
    QTest.keyClick(p.find, Qt.Key_Backspace)
    settle(qapp, p)
    assert p.find.hasFocus()
    assert query(window, qapp, '.*') == []  # literal, no regexp


def test_r25_scope_no_pixels_names_titles_and_skipped_alongside(window, qapp):
    from PySide6.QtGui import QPainter
    a = capture(window, 1, [('text', 'elsewhere')])
    named = a.with_name('pixelword.png')
    a.rename(named)
    window.setWindowTitle('pixelword')
    broken = capture(window, 2)
    broken.with_suffix('.annotshot').write_bytes(b'bad zip')
    pixels = picture()
    painter = QPainter(pixels)
    painter.drawText(10, 30, 'pixelword')
    painter.end()
    pixel_only = window.recent_store.file(pixels, keep=100)
    Document(pixels).save(str(pixel_only.with_suffix('.annotshot')))
    p = window.recent
    p.refresh()
    assert isinstance(p.find, QLineEdit)
    assert p.find.accessibleName() == p.find.placeholderText() == 'Find annotations'
    assert p.find.toolTip() == p.find.accessibleDescription() == SCOPE
    assert query(window, qapp, 'pixelword') == []
    assert p.empty.text() == NO_MATCH and not p.empty.isHidden()
    assert '1' in p.skipped.text() and not p.skipped.isHidden()
    assert 'could not be searched' in p.skipped.text()


def test_r26_hundred_mixed_metadata_only_and_legacy(window, qapp, monkeypatch):
    expected = []
    for i in range(100):
        kind = ('pair', 'editable', 'png')[i % 3]
        p = capture(window, i, [('callout', 'needle')], kind,
                    format=LEGACY_FORMATS[0] if i % 2 else 'annotshot')
        if kind != 'png':
            expected.append(str(p))
    window.recent.refresh()
    reads = []
    read = zipfile.ZipFile.open
    def opened(self, member, *args, **kwargs):
        reads.append(member.filename if isinstance(member, zipfile.ZipInfo) else member)
        return read(self, member, *args, **kwargs)
    monkeypatch.setattr(zipfile.ZipFile, 'open', opened)
    monkeypatch.setattr(recent, 'thumbnail', lambda *a, **k: pytest.fail('Find rendered pixels'))
    assert query(window, qapp, 'needle') == list(reversed(expected))
    assert reads == ['project.json'] * 67
    assert window.recent.skipped.isHidden()


@pytest.mark.parametrize('fault', ['zip', 'missing', 'json', 'format', 'version', 'items', 'text', 'large', 'vanished'])
def test_r26_failed_capture_count_once(window, qapp, monkeypatch, fault):
    p = capture(window, 1, [('text', 'needle')])
    e = p.with_suffix('.annotshot')
    if fault == 'zip':
        e.write_bytes(b'not zip')
    elif fault in ('missing', 'json'):
        with zipfile.ZipFile(e, 'w') as z:
            z.writestr('base.png' if fault == 'missing' else 'project.json', b'wrong')
    elif fault == 'vanished':
        original = window.recent_store.annotation_match
        def vanish(*args):
            e.unlink(missing_ok=True)
            return original(*args)
        monkeypatch.setattr(window.recent_store, 'annotation_match', vanish)
    else:
        overrides = {'format': {'format': 'other'}, 'version': {'version': 99},
                     'items': {'items': {}}, 'text': {'items': [{'type': 'text', 'text': 8}]},
                     'large': {'items': [{'type': 'text', 'text': 'x' * (recent.MAX_FIND_META + 1)}]}}
        capture(window, 1, [('text', 'needle')], **overrides[fault])
        # capture() reserves a distinct name at the same time; remove the first pair.
        window.recent_store.delete(p)
    window.recent.refresh()
    assert query(window, qapp, 'needle') == []
    assert window.recent.skipped.text() == '1 capture could not be searched.'


def test_r26_reverse_worker_order_input_usable_and_close_drops(window, qapp, monkeypatch):
    p = capture(window, 1, [('text', 'second')])
    window.recent.refresh()
    entered, release = threading.Event(), threading.Event()
    original = window.recent_store.find_annotations
    def ordered(text, cancel):
        if text == 'first':
            entered.set()
            assert release.wait(4)
        return original(text, cancel)
    monkeypatch.setattr(window.recent_store, 'find_annotations', ordered)
    pane = window.recent
    pane.find.setText('first')
    try:
        deadline = time.monotonic() + 2
        while not entered.is_set():
            qapp.processEvents()
            assert time.monotonic() < deadline
        pane.find.setFocus()
        pane.find.selectAll()
        QTest.keyClicks(pane.find, 'second')
        # Only two running jobs and one latest request, however fast the typing.
        assert pane._find_pool.maxThreadCount() == 2
        deadline = time.monotonic() + 2
        while pane.paths() != [str(p)]:
            qapp.processEvents()
            assert time.monotonic() < deadline
        assert pane.find.hasFocus()
    finally:
        release.set()
    settle(qapp, pane)
    assert pane.paths() == [str(p)]
    pane.cancel_find()
    assert not pane.find_pending()


def test_r27_disk_outcomes_autosave_failure_delete_expire_file(window, qapp, monkeypatch, tmp_path):
    from annotshot.items import TextBoxItem
    a = window.recent_store.file(picture(), keep=100)
    assert window.open_recent(str(a))
    assert query(window, qapp, 'needle') == []
    t = TextBoxItem()
    t.props['text'] = 'needle'
    t._props_changed()
    window.doc.add_items([t])
    assert window.autosave_now()
    assert recent.writer().waitForDone(5000)
    settle(qapp, window.recent)
    assert window.recent.paths() == [str(a)]
    # The live scene can change, but a failed disk write cannot change Find.
    window.doc.select_only([t])
    window.doc.remove_items([t])
    with monkeypatch.context() as fail:
        fail.setattr(recent, '_write_editable', lambda *a, **k: (_ for _ in ()).throw(OSError('denied')))
        assert window.autosave_now()
        assert recent.writer().waitForDone(5000)
        settle(qapp)
    assert window.recent.paths() == [str(a)]
    assert window.autosave_now()
    assert recent.writer().waitForDone(5000)
    settle(qapp, window.recent)
    assert window.recent.paths() == []
    b = capture(window, 2, [('text', 'needle')])
    window.recent._filed(str(b))
    settle(qapp, window.recent)
    assert window.recent.paths() == [str(b)]
    window.recent.delete(str(b))
    settle(qapp, window.recent)
    assert window.recent.paths() == []
    # Expiry and filing completion also invalidate a search with no matches.
    window.recent.file_capture(picture(), wait=True, keep=1)
    settle(qapp, window.recent)
    assert window.recent.paths() == []
    # No terms, title or index enters settings or the library.
    window.settings.sync()
    assert 'needle' not in Path(window.settings.fileName()).read_text()
    assert not any('index' in x.name or 'needle' in x.name for x in a.parent.iterdir())


@pytest.mark.parametrize('outcome', ['delete', 'replace'])
def test_r27_old_read_cannot_resurrect(window, qapp, monkeypatch, outcome):
    a = capture(window, 1, [('text', 'needle')])
    window.recent.refresh()
    entered, release = threading.Event(), threading.Event()
    original = window.recent_store.find_annotations
    def held(text, cancel):
        result = original(text, cancel)
        if not entered.is_set():
            entered.set()
            assert release.wait(4)
        return result
    monkeypatch.setattr(window.recent_store, 'find_annotations', held)
    window.recent.find.setText('needle')
    try:
        deadline = time.monotonic() + 2
        while not entered.is_set():
            qapp.processEvents()
            assert time.monotonic() < deadline
        if outcome == 'delete':
            window.recent.delete(str(a))
        else:
            with zipfile.ZipFile(a.with_suffix('.annotshot'), 'w') as z:
                z.writestr('project.json', json.dumps(dict(format='annotshot', version=1, items=[])))
            window.recent.refresh_one(a)
        for _ in range(5):
            qapp.processEvents()
    finally:
        release.set()
    settle(qapp, window.recent)
    assert window.recent.paths() == []


@pytest.mark.parametrize('how', ['control', 'backspace', 'escape', 'empty-escape'])
def test_r28_clear_restore_focus_and_arrow(window, qapp, how):
    from annotshot.tools import Tool
    a = capture(window, 1, [('text', 'needle')])
    b = capture(window, 2, kind='png')
    p, doc = window.recent, window.doc
    p.refresh()
    query(window, qapp, '' if how == 'empty-escape' else 'needle')
    if how == 'control':
        button = next(b for b in p.find.findChildren(QToolButton) if b.isVisible())
        QTest.mouseClick(button, Qt.LeftButton)
    elif how == 'backspace':
        p.find.selectAll()
        QTest.keyClick(p.find, Qt.Key_Backspace)
    else:
        p.setFloating(True)
        QTest.keyClick(p.find, Qt.Key_Escape)
    settle(qapp, p)
    assert p.paths() == [str(b), str(a)] and p.find.text() == ''
    assert p.empty.isHidden() and not p.isHidden() and window.doc is doc
    if how in ('control', 'backspace'):
        assert p.find.hasFocus()
    else:
        assert window.view.hasFocus()
        QTest.keyClick(window.view, Qt.Key_A)
        assert window.view.tool == Tool.ARROW
    window.recent_store.clear()
    p.refresh()
    assert p.empty.text() == recent.EMPTY_TEXT and not p.empty.isHidden()


@pytest.mark.parametrize('edge', [Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea,
    Qt.BottomDockWidgetArea, 'wide', 'tall'])
def test_r29_results_one_click_guard_frame_caret_layout_reveal(window, qapp, monkeypatch, edge):
    from annotshot.items import TextBoxItem
    a = window.recent_store.file(picture(), keep=100)
    b = window.recent_store.file(picture(), keep=100)
    for path, text in [(a, 'alpha'), (b, 'beta')]:
        doc = Document(picture())
        t = TextBoxItem()
        t.props['text'] = text
        t._props_changed()
        doc.add_items([t])
        doc.save(str(path.with_suffix('.annotshot')))
    p = window.recent
    p.refresh()
    assert window.open_recent(str(a))
    doc = window.doc
    if isinstance(edge, str):
        p.setFloating(True)
        p.resize(700, 300) if edge == 'wide' else p.resize(300, 700)
    else:
        window.addDockWidget(edge, p)
    query(window, qapp, 'beta')
    assert marks(p) == [] and window.doc is doc
    QTest.keyClick(p.list, Qt.Key_Down)
    QTest.keyClicks(p.find, 'x')
    settle(qapp, p)
    assert window.doc is doc
    query(window, qapp, 'beta')
    with monkeypatch.context() as guard:
        guard.setattr(window, 'maybe_discard', lambda: False)
        p._clicked(p.list.item(0))
        assert window.doc is doc
    with monkeypatch.context() as fail:
        fail.setattr(recent, 'load_edit', lambda *a: (_ for _ in ()).throw(OSError('read failed')))
        p._clicked(p.list.item(0))
        assert window.doc is doc
    settle(qapp, p)
    p._clicked(p.list.item(0))
    settle(qapp, p)
    assert window.doc is not doc and window.view.hasFocus() and marks(p) == [b.stem]
    live = window.doc
    t = live.annotation_items()[0]
    t.start_edit()
    cursor = t.editor.textCursor()
    cursor.setPosition(2)
    t.editor.setTextCursor(cursor)
    p._clicked(p.list.item(0))
    assert window.doc is live and t.is_editing and t.editor.textCursor().position() == 2
    query(window, qapp, 'alpha')
    assert marks(p) == []
    query(window, qapp, 'beta')
    assert marks(p) == [b.stem]
    p.refresh()
    settle(qapp, p)
    assert p.find.text() == 'beta' and p.find.hasFocus() and marks(p) == [b.stem]
    monkeypatch.setattr(window, '_recent_placement_valid', lambda: True)
    monkeypatch.setattr(window, '_raise_recent', lambda: True)
    window.a_recent.trigger()
    settle(qapp, p)
    assert p.find.hasFocus() and p.find.text() == 'beta' and window.doc is live


def test_r30_all_library_count_cancel_snapshot_and_filtered_save(window, qapp, monkeypatch, tmp_path):
    from annotshot import mainwindow
    a = capture(window, 1, [('text', 'alpha')])
    b = capture(window, 2, [('text', 'beta')])
    c = capture(window, 3, kind='png')
    assert window.open_recent(str(c))
    p, doc = window.recent, window.doc
    p.refresh()
    assert query(window, qapp, 'beta') == [str(b)]
    monkeypatch.setattr(mainwindow.QFileDialog, 'getSaveFileName', lambda *a, **k:
        (str(tmp_path / 'copy.png'), mainwindow.SAVE_TYPES[0][0]))
    # Save uses a real editable with a usable base.
    Document(picture()).save(str(b.with_suffix('.annotshot')))
    p.menu_for(p.list.item(0)).actions()[1].trigger()
    assert window.doc is doc and p._bound_stem == c.stem.casefold()
    assert query(window, qapp, 'absent') == []
    assert p.menu_for(None).actions()[-1].isEnabled()
    questions = []
    def cancel(*args):
        questions.append(args)
        return QMessageBox.Cancel
    monkeypatch.setattr(recent.QMessageBox, 'question', cancel)
    before = (p.find.text(), window.doc, marks(p), window.view.hasFocus())
    assert p.clear() is False
    assert (p.find.text(), window.doc, marks(p), window.view.hasFocus()) == before
    assert 'all 3' in questions[0][2] and 'including captures outside the results' in questions[0][2]
    assert questions[0][4] == QMessageBox.Cancel
    peer = MainWindow()  # another editor of the same private library
    arrival = None
    def confirm(*args):
        nonlocal arrival
        arrival = peer.recent_store.file(picture(), keep=100)
        return QMessageBox.Yes
    monkeypatch.setattr(recent.QMessageBox, 'question', confirm)
    assert p.clear() is True
    settle(qapp, p)
    assert all(not x.exists() for x in (a, b, c)) and arrival.exists()
    assert p.find.text() == 'absent'
    peer._autosave_timer.stop()
    peer.hide()
    peer.deleteLater()


def test_r15_unreadable_only_clear_count_and_menu_order(window, qapp, monkeypatch):
    folder = window.recent_store.folder
    folder.mkdir(parents=True, exist_ok=True)
    bad = folder / 'unreadable.AnNoTsHoT'
    bad.write_bytes(b'bad')
    p = window.recent
    p.refresh()
    assert p.list.count() == 0
    assert p.empty.text() != recent.EMPTY_TEXT  # a nonempty unreadable library is not empty
    menu = p.menu_for(None).actions()
    assert [a.text() for a in menu] == ['Open', 'Save…', 'Show in folder', '', 'Delete', '', 'Clear recent captures']
    assert not any(menu[i].isEnabled() for i in (0, 1, 4)) and menu[2].isEnabled() and menu[-1].isEnabled()
    asked = []
    monkeypatch.setattr(recent.QMessageBox, 'question', lambda *a: asked.append(a[2]) or QMessageBox.Yes)
    assert p.clear() and 'all 1' in asked[0] and not bad.exists()
    assert not p.menu_for(None).actions()[-1].isEnabled()


def test_r30_denied_listing_cannot_authorize_clear(window, monkeypatch):
    a = capture(window, 1)
    window.recent.refresh()
    monkeypatch.setattr(window.recent_store, 'source_entries', lambda: (_ for _ in ()).throw(PermissionError('denied')))
    monkeypatch.setattr(recent.QMessageBox, 'question', lambda *a: pytest.fail('unknown count asked'))
    assert not window.recent.menu_for(None).actions()[-1].isEnabled()
    assert not window.recent.clear() and a.exists()


@pytest.mark.parametrize('fault', ['unlink', 'replacement', 'companion-arrival'])
def test_r30_partial_failure_or_changed_current_keeps_scene(window, qapp, monkeypatch, fault):
    a = window.recent_store.file(picture(), keep=100)
    assert window.open_recent(str(a))
    doc, failures = window.doc, []
    window.recent.filingFailed.connect(failures.append)
    def answer(*args):
        if fault == 'replacement':
            a.unlink()
            assert picture(color='#00FF00').save(str(a))
        elif fault == 'companion-arrival':
            a.with_suffix('.annotshot').write_bytes(b'peer arrival')
        return QMessageBox.Yes
    monkeypatch.setattr(recent.QMessageBox, 'question', answer)
    if fault == 'unlink':
        original = recent._Root.unlink
        def fail(root, name, *args):
            if name.startswith('removed-'):
                raise PermissionError('fixture removal denied')
            return original(root, name, *args)
        monkeypatch.setattr(recent._Root, 'unlink', fail)
    assert window.recent.clear() is False
    settle(qapp, window.recent)
    assert a.exists() and window.doc is doc and failures
    assert marks(window.recent) == [a.stem]


def test_r26_r30_case_names_mixed_suffix_outside_link(window, qapp, monkeypatch, tmp_path):
    folder = window.recent_store.folder
    folder.mkdir(parents=True, exist_ok=True)
    png = folder / 'CAPTURE.PnG'
    assert picture().save(str(png), 'PNG')
    editable = folder / 'capture.AnNoTsHoT'
    with zipfile.ZipFile(editable, 'w') as z:
        z.writestr('project.json', json.dumps(dict(format=LEGACY_FORMATS[0], items=[dict(type='text', text='needle')])))
    outside = tmp_path / 'outside.annotshot'
    outside.write_bytes(editable.read_bytes())
    outside_bytes = outside.read_bytes()
    link = folder / 'outside.annotshot'
    link.symlink_to(outside)
    p = window.recent
    p.refresh()
    assert query(window, qapp, 'needle') == [str(png)]
    assert p.skipped.text() == '1 capture could not be searched.'
    asked = []
    monkeypatch.setattr(recent.QMessageBox, 'question', lambda *a: asked.append(a[2]) or QMessageBox.Yes)
    assert not p.clear()  # link is counted but retained, its target untouched
    assert 'all 2' in asked[0] and outside.read_bytes() == outside_bytes and link.is_symlink()
    assert not png.exists() and not editable.exists()


def test_find_retains_anchor_selection_after_zero_results(window, qapp):
    from test_s54_stage4_frame import first
    for i in range(25):
        capture(window, i, [('text', 'needle')])
    p = window.recent
    p.refresh()
    query(window, qapp, 'needle')
    p.list.setCurrentRow(12)
    p.list.scrollToItem(p.list.item(7), QListWidget.PositionAtTop)
    settle(qapp, p)
    anchor, selected = first(p), p.list.currentItem().data(Qt.UserRole)
    assert query(window, qapp, 'absent') == []
    query(window, qapp, 'needle')
    assert first(p) == anchor
    assert p.list.currentItem().data(Qt.UserRole) == selected and p.find.hasFocus()
    p.refresh()
    settle(qapp, p)
    assert first(p) == anchor and p.list.currentItem().data(Qt.UserRole) == selected


def test_windows_find_stream_uses_platform_road(window, qapp, monkeypatch):
    from test_s57_windows_recent import NativeCalls
    class Calls(NativeCalls):
        def read_at(self, handle, offset, size):
            with self.handles[handle].path.open('rb') as source:
                source.seek(offset)
                return source.read(size)
    native = Calls()
    with monkeypatch.context() as backend:
        backend.setattr(recent, '_HOST_WINDOWS', True)
        backend.setattr(recent, '_windows_native', lambda: native)
        backend.setattr(recent.os, 'supports_dir_fd', set())
        a = capture(window, 1, [('text', 'needle')])
        assert query(window, qapp, 'needle') == [str(a)]
        backend.setattr(recent.QMessageBox, 'question', lambda *a: QMessageBox.Yes)
        assert window.recent.clear()
        settle(qapp, window.recent)
        assert not a.exists() and not a.with_suffix('.annotshot').exists()
        window.recent.cancel_find()
        assert recent.find_pool().waitForDone(5000)
        qapp.processEvents()
    assert not native.handles


def test_find_close_while_reader_blocked_drops_results(window, qapp, monkeypatch):
    capture(window, 1, [('text', 'needle')])
    entered, release = threading.Event(), threading.Event()
    original = window.recent_store.find_annotations
    def held(text, cancel):
        result = original(text, cancel)
        entered.set()
        assert release.wait(4)
        return result
    monkeypatch.setattr(window.recent_store, 'find_annotations', held)
    p = window.recent
    p.find.setText('needle')
    try:
        deadline = time.monotonic() + 2
        while not entered.is_set():
            qapp.processEvents()
            assert time.monotonic() < deadline
        p.close()
        assert not p.find_pending() and p.paths() == []
    finally:
        release.set()
    assert recent.find_pool().waitForDone(5000)
    qapp.processEvents()
    assert p.paths() == []


def test_clear_exchange_during_move_restores_personal_arrival(window, monkeypatch):
    a = window.recent_store.file(picture(), keep=100)
    original = recent._rename_noreplace
    swapped = []
    def exchange(source, src, destination, dst):
        if src == a.name and not swapped:
            a.unlink()
            a.write_bytes(b'personal replacement')
            swapped.append(True)
        return original(source, src, destination, dst)
    monkeypatch.setattr(recent, '_rename_noreplace', exchange)
    monkeypatch.setattr(recent.QMessageBox, 'question', lambda *a: QMessageBox.Yes)
    assert not window.recent.clear()
    assert a.read_bytes() == b'personal replacement'


def test_clear_same_inode_change_during_move_is_kept(window, monkeypatch):
    import os
    a = window.recent_store.file(picture(), keep=100)
    before = a.stat()
    replacement = b'x' * before.st_size
    original = recent._rename_noreplace
    changed = []
    def exchange(source, src, destination, dst):
        if src == a.name and not changed:
            a.write_bytes(replacement)
            os.utime(a, ns=(before.st_atime_ns, before.st_mtime_ns))
            changed.append(True)
        return original(source, src, destination, dst)
    monkeypatch.setattr(recent, '_rename_noreplace', exchange)
    monkeypatch.setattr(recent.QMessageBox, 'question', lambda *a: QMessageBox.Yes)
    assert not window.recent.clear()
    assert a.read_bytes() == replacement


def test_float_escape_cancels_pending_reveal_focus(window, qapp, monkeypatch):
    from annotshot.tools import Tool
    p = window.recent
    p.setFloating(True)
    p.activateWindow()
    qapp.processEvents()
    p.find.setFocus()
    monkeypatch.setattr(window, '_recent_placement_valid', lambda: True)
    monkeypatch.setattr(window, '_raise_recent', lambda: None)
    window.a_recent.trigger()           # native result is delivered after 100 ms
    QTest.keyClick(p.find, Qt.Key_Escape)
    QTest.qWait(150)
    assert window.view.hasFocus() and not p.isHidden()
    QTest.keyClick(window.view, Qt.Key_A)
    assert window.view.tool == Tool.ARROW


def test_float_find_escape_ends_live_typing_for_arrow(window, qapp):
    from annotshot.items import TextBoxItem
    from annotshot.tools import Tool
    t = TextBoxItem()
    window.doc.add_items([t])
    t.start_edit()
    t.editor.setPlainText('live caret')
    p = window.recent
    p.setFloating(True)
    p.activateWindow()
    qapp.processEvents()
    p.find.setFocus()
    qapp.processEvents()
    QTest.keyClick(p.find, Qt.Key_Escape)
    qapp.processEvents()
    QTest.keyClick(window.view, Qt.Key_A)
    assert window.view.tool == Tool.ARROW and window.doc.editing_item is None
    assert t.props['text'] == 'live caret' and not p.isHidden()
