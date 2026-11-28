"""s54 stage 3: real private folders, controls and capture/write outcomes."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import sys
import queue
import threading

import pytest
from PySide6.QtCore import QCoreApplication, QDateTime, QEvent, QSettings, Qt
from PySide6.QtGui import QFocusEvent, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from annotshot import recent
from annotshot.capture import CaptureResult
from annotshot.mainwindow import MainWindow
from annotshot.scene import Document
from annotshot.settings_dialog import SettingsDialog
from test_s3b2 import picture


def bounded_line(stream, timeout=8):
    """Pipes are not selectable on Windows. A daemon read has a hard waiter."""
    lines = queue.Queue()
    threading.Thread(target=lambda: lines.put(stream.readline()), daemon=True).start()
    return lines.get(timeout=timeout)


def deny_creation(monkeypatch, predicate, message='record creation denied'):
    """Fault the create operation actually used by this host's backend."""
    owner = recent._WindowsRoot if recent._HOST_WINDOWS else recent._Root
    original = owner.create
    def create(self, name, *args, **kwargs):
        if predicate(str(name)):
            raise PermissionError(message)
        return original(self, name, *args, **kwargs)
    monkeypatch.setattr(owner, 'create', create)


def symlink(path, target, *, directory=False):
    try:
        path.symlink_to(target, target_is_directory=directory)
    except OSError as error:
        if sys.platform == 'win32' and getattr(error, 'winerror', None) == 1314:
            pytest.skip('symlink privilege unavailable; Windows junction and reparse-model tests cover refusal')
        raise


@pytest.fixture
def w(qapp):
    from annotshot.app import make_app
    make_app()
    window = MainWindow()
    yield window
    recent.writer().waitForDone(5000)
    from PySide6.QtCore import QThreadPool
    QThreadPool.globalInstance().waitForDone(5000)
    window.hide()
    window.deleteLater()
    qapp.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def settle(qapp):
    from PySide6.QtCore import QThreadPool
    assert QThreadPool.globalInstance().waitForDone(5000)
    assert recent.writer().waitForDone(5000)
    qapp.processEvents()
    qapp.processEvents()


def seed(store, n, *, recorded=True):
    store.folder.mkdir(parents=True, exist_ok=True)
    paths = []
    start = QDateTime.fromString('2020-01-01T00:00:00.000', Qt.ISODateWithMs)
    for i in range(n):
        p = store.folder / recent.stamp_name(start.addSecs(i))
        if recorded:
            assert store.file(picture(20, 10), start.addSecs(i), keep=100) == p
        else:
            assert picture(20, 10).save(str(p), "PNG")
        paths.append(p)
    return paths


def disk(store):
    return {p.name: p.read_bytes() for p in store.folder.iterdir()
            if p.suffix.lower() in ('.png', '.annotshot')}


def enter(control, text, key=Qt.Key_Return):
    spin = control.spin
    spin.lineEdit().setText(text)
    QTest.keyClick(spin, key)


def restarted_count(settings):
    """Read the persisted choice in a fresh, Qt-core-only Python process."""
    settings.sync()
    code = '''import json, sys
from PySide6.QtCore import QSettings
from annotshot import recent
s = QSettings(sys.argv[1], QSettings.IniFormat)
number = recent.read_count(s)
legacy = s.value(recent.SETTING, True, type=bool)
print(json.dumps([number, legacy, type(legacy).__name__]))
'''
    result = subprocess.run([sys.executable, '-c', code, settings.fileName()],
                            capture_output=True, text=True, timeout=10, check=True)
    return json.loads(result.stdout)


def capture(w, qapp):
    w._capture_done(CaptureResult(picture(20, 10)))
    settle(qapp)


def test_r01_fresh_welcome_step_type_and_sentence(w, qapp):
    w.show()
    qapp.processEvents()
    c = w.welcome.count_control
    assert not c.isHidden() and c.spin.value() == 12
    assert 'newest 12 captures' in c.note.text()
    enter(c, '0')
    assert c.spin.text() == 'Off' and c.note.text() == 'New captures won’t be kept.'
    c.spin.stepUp()
    assert c.spin.value() == 1 and 'newest 1 captures' in c.note.text()
    enter(c, '100')
    assert w.capture_count() == 100 and 'newest 100 captures' in c.note.text()
    assert w.welcome.capture_bar.capture_button.isEnabled()
    assert c.note.height() >= c.note.heightForWidth(c.note.width())


@pytest.mark.parametrize('exit_by', ['capture', 'open', 'quit'])
def test_r02_first_visible_welcome_consumed(w, qapp, tmp_path, exit_by):
    w.show()
    qapp.processEvents()
    if exit_by == 'capture':
        capture(w, qapp)
    elif exit_by == 'open':
        path = tmp_path / 'own.annotshot'
        Document(picture()).save(str(path))
        assert w.open_path(str(path), ask=False)
    else:
        w.set_keep_running(False)
        assert w.close()
    assert w.settings.value(recent.FIRST_WELCOME, False, type=bool)
    w.show_welcome()
    assert w.welcome.count_control.isHidden()
    again = MainWindow()
    try:
        assert again.welcome.count_control.isHidden()
        assert SettingsDialog(again).keep_recent.value() == w.capture_count()
    finally:
        again.deleteLater()


def test_r02_file_argument_road_opens_before_visible_welcome(w, tmp_path):
    from annotshot.app import file_argument
    assert w.welcome.count_control.spin.value() == 12
    p = tmp_path / 'argument.annotshot'
    Document(picture()).save(str(p))
    assert file_argument(['annotshot', str(p)]) == str(p)
    assert w.open_path(str(p), ask=False) and w.state_name == 'editor'


@pytest.mark.parametrize('surface', ['welcome', 'settings'])
def test_r03_typed_commit_return_blur_capture_and_restart(w, qapp, surface, monkeypatch):
    d = SettingsDialog(w)
    c = w.welcome.count_control if surface == 'welcome' else d.count_control
    w.show()
    if surface == 'settings':
        d.tabs.setCurrentIndex(1)
        d.show()
    qapp.processEvents()
    c.spin.stepUp()
    assert w.capture_count() == 13
    c.spin.lineEdit().setText('20')
    c.spin.stepUp()
    assert w.capture_count() == 21
    c.spin.lineEdit().setText('3')
    assert w.capture_count() == 21
    QTest.keyClick(c.spin.lineEdit(), Qt.Key_Return)
    assert w.capture_count() == 3
    c.spin.lineEdit().setText('4')
    c.spin.setFocus()
    qapp.processEvents()
    target = w.welcome.capture_bar.capture_button if surface == 'welcome' else d.quick_copy
    target.setFocus()
    qapp.processEvents()
    assert w.capture_count() == 4
    seed(w.recent_store, 9)
    c.spin.lineEdit().setText('2')
    monkeypatch.setattr(w, '_may_record_screen', lambda: True)
    monkeypatch.setattr(w, '_start_capture', lambda mode=None: w._capture_done(CaptureResult(picture(20, 10))))
    w.welcome.capture_bar.capture_button.click()
    QTest.qWait(300)
    settle(qapp)
    assert w.capture_count() == 2 and len(w.recent_store.files()) == 2
    again = MainWindow()
    assert again.capture_count() == 2
    assert restarted_count(w.settings) == [2, False, 'bool']
    again.deleteLater()
    d.deleteLater()


def test_r04_invalid_drafts_restore_committed_without_disk_change(w, qapp):
    w.show()
    qapp.processEvents()
    seed(w.recent_store, 5)
    before = disk(w.recent_store)
    c = w.welcome.count_control
    for blur in (False, True):
        for text in ('', '1.5', '-1', '101'):
            c.spin.lineEdit().selectAll()
            QTest.keyClick(c.spin.lineEdit(), Qt.Key_Backspace)
            QTest.keyClicks(c.spin.lineEdit(), text)
            assert c.spin.lineEdit().text() == text
            assert w.capture_count() == 12 and disk(w.recent_store) == before
            if blur:
                QApplication.sendEvent(c.spin.lineEdit(), QFocusEvent(QEvent.FocusOut))
            else:
                QTest.keyClick(c.spin, Qt.Key_Return)
            assert c.spin.value() == 12 and c.spin.text() == '12'
            assert c.error.text() == 'Enter a whole number from 0 to 100.'
            qapp.processEvents()
            for label in (c.note, c.error):
                assert label.height() >= label.heightForWidth(label.width())
                assert w.welcome.rect().contains(label.mapTo(w.welcome, label.rect().bottomRight()))
            assert w.capture_count() == 12 and disk(w.recent_store) == before


@pytest.mark.parametrize('copy', [False, True])
def test_r05_off_ordinary_quick_edits_and_clipboard(w, qapp, monkeypatch, copy):
    from annotshot.items import RectItem
    seed(w.recent_store, 3)
    before = disk(w.recent_store)
    enter(w.welcome.count_control, '0')
    w.settings.setValue('capture/copy', copy)
    board = []
    monkeypatch.setattr(QApplication, 'clipboard', staticmethod(
        lambda: type('Board', (), {'setImage': lambda self, img: board.append(img)})()))
    for _ in range(2):
        capture(w, qapp)
        assert w.doc.path is None
        w.doc.add_items([RectItem()])
        assert not w.autosave_now()
        settle(qapp)
    assert len(board) == (2 if copy else 0)
    assert disk(w.recent_store) == before
    assert len(disk(w.recent_store)) == 3


def test_r06_edited_pair_and_editable_only_take_places(w, qapp):
    old, middle, newest = seed(w.recent_store, 3)
    Document(picture()).save(str(old.with_suffix('.annotshot')))
    Document(picture()).save(str(newest.with_suffix('.annotshot')))
    newest.unlink()
    w.set_capture_count(2)
    capture(w, qapp)
    assert old.exists() and not middle.exists() and newest.with_suffix('.annotshot').exists()
    assert len(w.recent_store.files()) == 3


@pytest.mark.parametrize('via_off', [False, True])
def test_r07_lower_goes_at_next_successful_capture(w, qapp, via_off):
    originals = seed(w.recent_store, 30)
    w.set_capture_count(30)
    w.set_capture_count(10)
    assert all(p.exists() for p in originals)
    if via_off:
        w.set_capture_count(0)
        capture(w, qapp)
        again = MainWindow()
        assert again.capture_count() == 0 and all(p.exists() for p in originals)
        again.deleteLater()
        w.set_capture_count(8)
    assert all(p.exists() for p in originals)
    capture(w, qapp)
    n = 8 if via_off else 10
    assert len(w.recent_store.files()) == n
    assert all(p.exists() == (i >= 31 - n) for i, p in enumerate(originals))


def test_r08_raise_cancels_unapplied_lower_and_full_rotates_one(w, qapp):
    originals = seed(w.recent_store, 29)
    for n in [30, 10, 30]:
        w.set_capture_count(n)
        assert all(p.exists() for p in originals)
    capture(w, qapp)
    assert len(w.recent_store.files()) == 30 and all(p.exists() for p in originals)
    capture(w, qapp)
    assert len(w.recent_store.files()) == 30 and not originals[0].exists()
    assert all(p.exists() for p in originals[1:])


@pytest.mark.parametrize('legacy', [True, False, None])
@pytest.mark.parametrize('copy', [True, False])
def test_r09_established_boolean_migration(qapp, private_settings, legacy, copy):
    settings = QSettings(private_settings, QSettings.IniFormat)
    settings.setValue('capture/copy', copy)
    if legacy is not None:
        settings.setValue(recent.SETTING, legacy)
    w = MainWindow()
    try:
        assert w.welcome.count_control.isHidden()
        assert w.capture_count() == (0 if legacy is False else 12)
        assert w.quick_copy() is copy
    finally:
        w.deleteLater()


def test_r10_overfull_discovery_readable_unique_order_untouched(w, qapp):
    paths = seed(w.recent_store, 20, recorded=False)
    paths[0].with_suffix('.annotshot').write_bytes(b'broken edits')
    Document(picture()).save(str(paths[1].with_suffix('.annotshot')))
    paths[1].unlink()
    w.settings.clear()  # entries alone establish the profile, before startup writes
    again = MainWindow()
    assert again.welcome.count_control.isHidden()
    again.deleteLater()
    w.set_capture_count(3)
    before = disk(w.recent_store)
    w.recent.refresh()
    assert len(w.recent.paths()) == 20
    assert len({Path(p).stem for p in w.recent.paths()}) == 20
    assert [Path(p).stem for p in w.recent.paths()] == [p.stem for p in reversed(paths)]
    assert disk(w.recent_store) == before
    capture(w, qapp)
    assert {p.stem for p in w.recent_store.files()} == {
        *(p.stem for p in paths), Path(w.doc.path).stem}
    assert paths[0].read_bytes() == before[paths[0].name]


def old_capture(settings, store):
    """0.4.4's Boolean gate and fixed-12 write/prune, from its published road."""
    if settings.value('recent/keep', True, type=bool):
        path = store.folder / '2025-01-01T00-00-00-000.png'
        assert picture(20, 10).save(str(path), 'PNG')
        for p in store.files()[12:]:
            if not p.with_suffix('.annotshot').exists():
                p.unlink()


def test_r11_shared_044_boolean_and_fixed_twelve_filer(w):
    seed(w.recent_store, 30)
    before = disk(w.recent_store)
    for count in [30, 0]:
        w.set_capture_count(count)
        assert w.settings.value(recent.SETTING) is False
        old_capture(w.settings, w.recent_store)
        assert disk(w.recent_store) == before
    w.set_capture_count(12)
    assert w.settings.value(recent.SETTING) is True
    assert disk(w.recent_store) == before
    old_capture(w.settings, w.recent_store)
    assert len(w.recent_store.files()) == 12


def test_r12_versioned_numeric_roundtrip_old_switch(w):
    w.set_capture_count(30)
    assert recent.COUNT_SETTING != recent.SETTING and 'v1' in recent.COUNT_SETTING
    w.settings.remove(recent.SETTING)
    assert w.capture_count() == 30
    assert w.settings.value(recent.SETTING) is False
    for old_switch, expected in [(False, 30), (True, 12), (False, 0)]:
        w.settings.setValue(recent.SETTING, old_switch)
        w.settings.sync()
        assert restarted_count(w.settings) == [expected, expected == 12, 'bool']
        again = MainWindow()
        assert again.capture_count() == expected
        assert type(again.settings.value(recent.SETTING)) is bool
        again.deleteLater()


@pytest.mark.parametrize('choice', [0, 3])
def test_r13_malformed_pauses_until_one_valid_choice(w, qapp, choice):
    seed(w.recent_store, 20)
    w.settings.setValue(recent.SETTING, True)
    for bad in ['2.5', -1, 101, True, 'oops']:
        w.settings.setValue(recent.COUNT_SETTING, bad)
        assert w.capture_count() is None
    d = SettingsDialog(w)
    assert d.keep_recent.value() == 0
    assert d.count_control.note.text() == 'Recent keeping is paused. Choose a count to start again.'
    before = disk(w.recent_store)
    capture(w, qapp)
    assert disk(w.recent_store) == before and w.doc.path is None
    enter(d.count_control, str(choice))
    assert w.capture_count() == choice and disk(w.recent_store) == before
    capture(w, qapp)
    assert len(w.recent_store.files()) == (choice or 20)
    d.deleteLater()


def test_r14_accepted_count_failed_png_and_pending_edit_outcomes(w, qapp, monkeypatch):
    from annotshot.items import RectItem
    original = seed(w.recent_store, 20)
    w.set_capture_count(30)
    jobs = []
    from PySide6.QtCore import QThreadPool
    pool = QThreadPool.globalInstance()
    with monkeypatch.context() as m:
        m.setattr(pool, 'start', jobs.append)
        w._capture_done(CaptureResult(picture(20, 10)))
        w.set_capture_count(10)
    assert len(jobs) == 1
    jobs.pop().run()
    settle(qapp)
    assert len(w.recent_store.files()) == 21
    before = disk(w.recent_store)
    with monkeypatch.context() as m:
        m.setattr(QImage, 'save', lambda *args, **kwargs: False)
        capture(w, qapp)  # actual accepted capture, worker, PNG failure and outcome
        assert w.doc.path is None
    assert disk(w.recent_store) == before
    other = MainWindow()
    try:
        for fail in [False, True]:
            path = original[0]
            if fail:
                path = w.recent_store.folder / '2019-01-01T00-00-00-000.png'
                when = QDateTime.fromString('2019-01-01T00:00:00.000', Qt.ISODateWithMs)
                assert w.recent_store.file(picture(20, 10), when, keep=100) == path
            assert other.open_recent(str(path))
            other.doc.add_items([RectItem()])
            saved_bytes = path.read_bytes()
            assert other._autosave_timer.isActive()
            held = []
            with monkeypatch.context() as m:
                m.setattr(recent.writer(), 'start', held.append)
                assert other.autosave_now()
                capture(w, qapp)
                assert path.read_bytes() == saved_bytes
            with monkeypatch.context() as m:
                if fail:
                    import annotshot.scene
                    m.setattr(annotshot.scene, 'write_project', lambda *a: (_ for _ in ()).throw(OSError('injected')))
                held[0].run()
            settle(qapp)
            assert path.read_bytes() == saved_bytes
            assert path.with_suffix('.annotshot').exists() is (not fail)
            capture(w, qapp)
            assert path.read_bytes() == saved_bytes
    finally:
        other.hide()
        other.deleteLater()


@pytest.mark.parametrize('fault', ['listing', 'unlink'])
def test_prune_uncertain_inventory_or_denied_unlink_preserves(w, monkeypatch, fault):
    seed(w.recent_store, 5)
    before = disk(w.recent_store)
    w.recent_store.keep = 1
    with monkeypatch.context() as m:
        if fault == 'listing':
            if recent._HOST_WINDOWS:
                m.setattr(recent._WindowsRoot, 'names', lambda p: (_ for _ in ()).throw(PermissionError('denied')))
            else:
                m.setattr(Path, 'iterdir', lambda p: (_ for _ in ()).throw(PermissionError('denied')))
        else:
            if recent._HOST_WINDOWS:
                m.setattr(recent._windows_native(), 'delete', lambda *a, **k: (_ for _ in ()).throw(PermissionError('denied')))
            else:
                m.setattr(recent.os, 'unlink', lambda *a, **k: (_ for _ in ()).throw(PermissionError('denied')))
        assert w.recent_store.prune() == []
    assert disk(w.recent_store) == before


def test_prune_actual_mixed_case_companions_collisions_links(w, tmp_path, monkeypatch):
    paths = seed(w.recent_store, 5)
    paths[0].with_suffix('.AnNoTsHoT').write_bytes(b'corrupt but edited')
    # On a case-sensitive volume, two actual names must both survive ambiguity.
    alias = paths[1].with_name(paths[1].stem + '.PNG')
    if alias != paths[1] and not alias.exists():
        alias.write_bytes(paths[1].read_bytes())
    target = tmp_path / 'outside.png'
    target.write_bytes(b'outside original')
    link = w.recent_store.folder / '2099-01-01T00-00-00-000.png'
    symlink(link, target)
    w.recent_store.keep = 1
    entries = list(w.recent_store.folder.iterdir())
    # Exercise the inventory's collision branch on this case-insensitive Mac
    # too: both spellings resolve to the real file, and neither may expire.
    if alias not in entries:
        entries.append(alias)
    real_iter = Path.iterdir
    with monkeypatch.context() as m:
        if recent._HOST_WINDOWS:
            names = recent._WindowsRoot.names
            m.setattr(recent._WindowsRoot, 'names', lambda r:
                [p.name for p in entries] if r.folder == w.recent_store.folder else names(r))
        else:
            m.setattr(Path, 'iterdir', lambda p: iter(entries) if p == w.recent_store.folder else real_iter(p))
        w.recent_store.prune()
    assert paths[0].exists() and paths[1].exists() and alias.exists()
    assert link.is_symlink() and target.read_bytes() == b'outside original'
    assert paths[-1].exists()  # a link cannot steal a real capture's newest place


def test_reserve_dangling_link_and_overlapping_same_timestamp(w, tmp_path):
    store = w.recent_store
    store.folder.mkdir(parents=True, exist_ok=True)
    when = QDateTime.fromString('2026-01-01T00:00:00.000', Qt.ISODateWithMs)
    link = store.folder / recent.stamp_name(when)
    target = tmp_path / 'absent.png'
    symlink(link, target)
    peer = recent.RecentStore(lambda: store.folder, keep=100)
    store.keep = 100
    with ThreadPoolExecutor(2) as pool:
        a, b = list(pool.map(lambda s: s.file(picture(20, 10), when), [store, peer]))
    assert a != b and a != link and b != link
    assert a.is_file() and b.is_file() and link.is_symlink() and not target.exists()
    before = a.read_bytes()
    with pytest.raises(OSError):
        peer.file(picture(5, 5), path=a)
    assert a.read_bytes() == before
    held = store.reserve(when)
    with pytest.raises(OSError):
        peer.file(picture(5, 5), path=held)
    assert str(held) in recent._RESERVED and not held.exists()
    assert store.file(picture(20, 10), path=held) == held
    assert held.is_file() and str(held) not in recent._RESERVED


def test_r10_large_folder_trial_discovery_and_edited_over_100(w, qapp):
    paths = seed(w.recent_store, 100)
    # Full provenance and release-hardware timing remain caller proofs.
    for p in paths[::2]:
        Document(picture(24, 12)).save(str(p.with_suffix('.annotshot')))
    before = disk(w.recent_store)
    w.recent.refresh()
    assert len(w.recent.paths()) == 100 and disk(w.recent_store) == before
    for i in range(5):
        p = w.recent_store.folder / f'2018-01-01T00-00-0{i}-000.annotshot'
        Document(picture()).save(str(p))
    for p in paths[1::2]:
        Document(picture(24, 12)).save(str(p.with_suffix('.annotshot')))
    w.set_capture_count(3)
    capture(w, qapp)
    assert len(w.recent_store.files()) == 106

# s57: subprocess peers use only this test's private files, with bounded IPC.
def peer(code, *args):
    result = subprocess.run([sys.executable, '-c', PEER_IMPORTS + code,
                             *map(str, args)], capture_output=True, text=True,
                            timeout=15)
    assert result.returncode == 0, result.stderr + result.stdout
    return result.stdout.strip()


PEER_IMPORTS = '''import sys, json, os, time, queue, threading
from pathlib import Path
from PySide6.QtCore import QDateTime, Qt, QSettings
from PySide6.QtGui import QImage
from annotshot import recent
folder = Path(sys.argv[1])
store = recent.RecentStore(lambda: folder, keep=100)
def image(color=0xff123456):
    img = QImage(20, 10, QImage.Format_RGB32)
    img.fill(color)
    return img
def file(stamp, keep=100):
    return store.file(image(), QDateTime.fromString(stamp, Qt.ISODateWithMs), keep=keep)
def bounded_line(stream, timeout=8):
    lines = queue.Queue()
    threading.Thread(target=lambda: lines.put(stream.readline()), daemon=True).start()
    return lines.get(timeout=timeout)
'''


def proven(store, n, year=2020):
    start = QDateTime.fromString(f'{year}-01-01T00:00:00.000', Qt.ISODateWithMs)
    return [store.file(picture(20, 10), start.addSecs(i), keep=100) for i in range(n)]


def all_bytes(folder):
    return {p.name: p.read_bytes() if p.is_file() else None for p in folder.iterdir()}


def test_s57_origin_receipts_restart_replacement_and_failure(w, qapp, monkeypatch):
    store = w.recent_store
    paths = proven(store, 4)
    bare = store.folder / 'family.png'
    assert picture().save(str(bare), 'PNG')
    unproven = []
    for year in (2018, 2098):
        p = store.folder / f'{year}-01-01T00-00-00-000.png'
        assert picture().save(str(p), 'PNG')
        unproven.append(p)
    paths[0].with_suffix('.AnNoTsHoT').write_bytes(b'broken edits')
    only = store.folder / '2017-01-01T00-00-00-000.annotshot'
    only.write_bytes(b'editable only')
    before = disk(store)
    expected = sorted(store.files(), key=lambda p: (recent.taken_at(p).toMSecsSinceEpoch(), p.stem), reverse=True)
    assert store.files() == expected and disk(store) == before
    arrival = store.file(picture(30, 20), keep=2)
    assert all(p.exists() for p in [bare, *unproven, only, paths[0], paths[3], arrival]), 'unrecorded PNGs must take no place and never expire'
    assert not paths[1].exists() and not paths[2].exists()
    survivors = disk(store)
    assert json.loads(peer('print(json.dumps(sorted(p.name for p in store.files())))', store.folder)) == sorted(survivors.keys() - {paths[0].with_suffix('.AnNoTsHoT').name})
    # Same name, changed identity AND pixels: the old receipt cannot authorize it.
    replacement = paths[3]
    replacement.unlink()
    assert picture(7, 9).save(str(replacement), 'PNG')
    new_bytes = replacement.read_bytes()
    store.file(picture(), keep=1)
    assert replacement.read_bytes() == new_bytes
    prior = disk(store)
    with monkeypatch.context() as m:
        deny_creation(m, lambda name: '.filed-v1' in name)
        with pytest.raises(OSError, match='(?i)(receipt|filing)'):
            store.file(picture(), keep=1)
    assert all((store.folder / name).read_bytes() == data for name, data in prior.items())
    assert len(disk(store)) == len(prior) + 1


@pytest.mark.parametrize('root_kind', ['link', 'dangling', 'exchanged'])
@pytest.mark.parametrize('operation', ['reserve', 'file', 'prune', 'edit', 'clear'])
def test_s57_linked_root_never_touches_target(tmp_path, root_kind, operation):
    outside = tmp_path / 'outside'
    outside.mkdir()
    target_store = recent.RecentStore(lambda: outside)
    proven(target_store, 3)
    (outside / '.sentinel').write_bytes(b'hidden sentinel')
    before = all_bytes(outside)
    root = tmp_path / 'Recent'
    store = recent.RecentStore(lambda: root)
    path = root / '2021-01-01T00-00-00-000.png'
    if root_kind == 'exchanged':
        path = store.reserve()
        root.rename(tmp_path / 'retired')
    symlink(root, outside if root_kind != 'dangling' else tmp_path / 'absent', directory=True)
    if operation == 'prune':
        assert store.prune(keep=1) == []
    elif operation == 'clear':
        try:
            store.clear()
        except OSError:
            pass
    else:
        with pytest.raises(OSError):
            if operation == 'reserve':
                store.reserve()
            elif operation == 'edit':
                recent.pending_edit(path.with_suffix('.annotshot'))
            else:
                store.file(picture(), path=path, keep=1)
    store.release(path)
    assert all_bytes(outside) == before, 'linked root target changed (including metadata)'
    assert not (tmp_path / 'absent').exists()
    assert store.files() == []


# A real process pauses at the production boundary, using stdin only as a
# bounded test barrier. No interactive keyboard or approval is involved.
def pruning_peer(folder, barrier, victim):
    code = PEER_IMPORTS + '''
boundary = ''' + repr(barrier) + '''
old_stage = not hasattr(recent.RecentStore, boundary)
if old_stage:
    boundary = '_edit_identity' if boundary == '_expiry_order' else None
owner = recent if boundary == '_edit_identity' else recent.RecentStore
original = getattr(owner, boundary) if boundary else Path.unlink
armed = True
def paused(self, *args, **kwargs):
    global armed
    result = original(self, *args, **kwargs)
    candidate = args[1] if boundary == '_expiry_candidate' else self
    if armed and (boundary != '_expiry_candidate' and boundary is not None
                  or Path(candidate).name == sys.argv[2]):
        armed = False
        print('READY', flush=True)
        assert bounded_line(sys.stdin).strip() == 'GO'
    return result
if boundary: setattr(owner, boundary, paused)
else: Path.unlink = paused
store.prune(keep=1)
print('DONE', flush=True)
'''
    return subprocess.Popen([sys.executable, '-c', code, str(folder), victim.name],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def ready(process):
    assert bounded_line(process.stdout).strip() == 'READY'


def resume(process):
    out, err = process.communicate('GO\n', timeout=12)
    assert process.returncode == 0 and 'DONE' in out, err + out


@pytest.mark.parametrize('saved', [False, True])
def test_s57_edit_wins_before_prune_claim(w, qapp, saved):
    from annotshot.items import RectItem
    store = w.recent_store
    victim, control, newest = proven(store, 3)
    original = victim.read_bytes()
    assert w.open_recent(str(victim))
    # _expiry_order is the selected list, before any final per-stem claim.
    p = pruning_peer(store.folder, '_expiry_order', victim)
    try:
        ready(p)
        w.doc.add_items([RectItem()])  # admission before the debounce fires
        assert w._autosave_timer.isActive()
        if saved:
            assert w.autosave_now()
            settle(qapp)
            assert victim.with_suffix('.annotshot').exists()
        resume(p)
        assert victim.read_bytes() == original
        assert not control.exists() and newest.exists()
    finally:
        if p.poll() is None:
            p.kill()
            p.communicate(timeout=5)


def test_s57_expiry_wins_editor_cannot_attach(w):
    from annotshot.items import RectItem
    store = w.recent_store
    victim, control, newest = proven(store, 3)
    assert w.open_recent(str(victim))
    p = pruning_peer(store.folder, '_expiry_candidate', victim)
    try:
        ready(p)  # final validation done, exclusive claim still held
        w.doc.add_items([RectItem()])
        assert w.doc.path is None, 'busy expiry must detach in-memory edit from Recent'
        assert w.doc.annotation_items() and not w._autosave_timer.isActive()
        resume(p)
        assert not victim.exists() and not control.exists() and newest.exists()
        assert not w.autosave_now()
        with pytest.raises(OSError):
            recent.pending_edit(victim.with_suffix('.annotshot'))
    finally:
        if p.poll() is None:
            p.kill()
            p.communicate(timeout=5)


def test_s57_marker_failure_claim_survives_process_death(w):
    store = w.recent_store
    victim, control = proven(store, 2)
    original = victim.read_bytes()
    code = PEER_IMPORTS + '''
from PySide6.QtWidgets import QApplication
from annotshot import mainwindow, hotkey, theme, capture as capture_module
from annotshot.items import RectItem
from annotshot.app import make_app
app = QApplication([])
hotkey.backend_class = lambda: hotkey.NoBackend
mainwindow.DEFAULT_DIR = folder.parent
private = lambda *a, **k: QSettings(str(folder.parent / 'editor-peer.ini'), QSettings.IniFormat)
mainwindow.QSettings = theme.QSettings = capture_module.QSettings = private
make_app()
window = mainwindow.MainWindow()
assert window.open_recent(str(folder / sys.argv[2]))
owner = recent._WindowsRoot if recent._HOST_WINDOWS else recent._Root
create = owner.create
def deny(self, name, *a, **k):
    if '.pending-' in str(name): raise PermissionError('denied marker')
    return create(self, name, *a, **k)
owner.create = deny
window.doc.add_items([RectItem()])
assert window._autosave_timer.isActive()
window._autosave_timer.stop()  # hold before debounce; no autosave_now call
assert window.doc.path == str(folder / sys.argv[2])
print('READY', flush=True)
assert bounded_line(sys.stdin).strip() == 'GO'
'''
    p = subprocess.Popen([sys.executable, '-c', code, str(store.folder), victim.with_suffix('.annotshot').name], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        ready(p)
        peer("file('2021-01-01T00:00:00.000', 1)", store.folder)
        assert victim.read_bytes() == original, 'failed marker must leave a durable exclusive claim'
        assert not control.exists()
        p.kill()
        p.communicate(timeout=5)
        peer("file('2022-01-01T00:00:00.000', 1)", store.folder)
        assert victim.read_bytes() == original
        assert not (store.folder / '2021-01-01T00-00-00-000.png').exists()
    finally:
        if p.poll() is None:
            p.kill()
            p.communicate(timeout=5)


def test_s57_failed_marker_failed_save_owner_retry(w, qapp, monkeypatch):
    from annotshot.items import RectItem
    import annotshot.scene
    store = w.recent_store
    victim, control = proven(store, 2)
    original = victim.read_bytes()
    assert w.open_recent(str(victim))
    with monkeypatch.context() as m:
        deny_creation(m, lambda name: '.pending-' in name)
        w.doc.add_items([RectItem()])
    with monkeypatch.context() as m:
        m.setattr(annotshot.scene, 'write_project', lambda *a: (_ for _ in ()).throw(OSError('failed save')))
        assert w.autosave_now()
        settle(qapp)
    peer("file('2021-01-01T00:00:00.000', 1)", store.folder)
    assert victim.read_bytes() == original and not control.exists()
    assert w.autosave_now()
    settle(qapp)
    assert victim.with_suffix('.annotshot').exists()
    assert not list(store.folder.glob('*.claim-v1'))
    peer("file('2022-01-01T00:00:00.000', 1)", store.folder)
    assert victim.read_bytes() == original


@pytest.mark.parametrize('tied', [False, True])
def test_s57_arrival_wins_clock_rollback_and_suffix(tmp_path, tied):
    store = recent.RecentStore(lambda: tmp_path, keep=100)
    when = QDateTime.fromString('2099-01-01T00:00:00.000', Qt.ISODateWithMs)
    first = store.file(picture(20, 10), when)
    if tied:
        # -9 sorts after -10; arrival cannot be selected by lexical order.
        for i in range(9):
            store.file(picture(20, 10), when)
    second = store.file(picture(7, 9), when if tied else when.addYears(-5), keep=1)
    assert second.exists(), 'a successful filing must never expire its own arrival'
    assert QImage(str(second)).size() == picture(7, 9).size()
    assert not first.exists() and store.files() == [second]


@pytest.mark.parametrize('legacy', [True, None])
def test_s57_malformed_disables_044_in_fresh_process(w, qapp, legacy):
    store = w.recent_store
    proven(store, 16)
    w.settings.setValue(recent.COUNT_SETTING, 'bad count')
    w.settings.setValue('capture/copy', False)
    if legacy is None:
        w.settings.remove(recent.SETTING)
    else:
        w.settings.setValue(recent.SETTING, legacy)
    before = all_bytes(store.folder)
    assert w.capture_count() is None
    assert w.settings.value(recent.SETTING, True, type=bool) is False, 'malformed numeric count must close the 0.4.4 Boolean gate'
    w.settings.sync()
    result = peer('''
s = QSettings(sys.argv[2], QSettings.IniFormat)
gate = s.value(recent.SETTING, True, type=bool)
if gate:
    file('2025-01-01T00:00:00.000')
    for path in store.files()[12:]:
        if not path.with_suffix('.annotshot').exists(): path.unlink()
print(json.dumps([gate, recent.read_count(s), s.value(recent.COUNT_SETTING)]))
''', store.folder, w.settings.fileName())
    assert json.loads(result) == [False, None, 'bad count']
    assert all_bytes(store.folder) == before
    again = MainWindow()
    try:
        assert again.capture_count() is None and not again.quick_copy()
        assert again.welcome.count_control.note.text() == recent.PAUSED_TEXT
    finally:
        again.deleteLater()
    w.set_capture_count(3)
    assert all_bytes(store.folder) == before
    capture(w, qapp)
    assert len(store.files()) == 3


def test_s57_replaced_recorded_png_is_unproven(w):
    store = w.recent_store
    victim, control = proven(store, 2)
    victim.unlink()
    assert picture(7, 9).save(str(victim), 'PNG')
    original = victim.read_bytes()
    store.file(picture(), keep=1)
    assert victim.exists(), 'a receipt cannot authorize deleting a replacement'
    assert victim.read_bytes() == original and not control.exists()


def test_s57_receipt_failure_preserves_publication_and_skips_prune(w, monkeypatch):
    store = w.recent_store
    proven(store, 3)
    before = disk(store)
    deny_creation(monkeypatch, lambda name: '.filed-v1' in name)
    with pytest.raises(OSError, match='(?i)(receipt|filing)'):
        store.file(picture(), keep=1)
    assert all((store.folder / name).read_bytes() == data for name, data in before.items())
    assert len(disk(store)) == len(before) + 1


@pytest.mark.parametrize('proof', ['receipt', 'editable'])
def test_s57_regular_companion_in_ambiguous_group_takes_one_place(w, monkeypatch, proof):
    store = w.recent_store
    victim = proven(store, 1)[0]
    pair = store.folder / '2021-01-01T00-00-00-000.png'
    if proof == 'receipt':
        when = QDateTime.fromString('2021-01-01T00:00:00.000', Qt.ISODateWithMs)
        assert store.file(picture(), when, keep=100) == pair
    else:
        assert picture().save(str(pair), 'PNG')
    edit = pair.with_suffix('.AnNoTsHoT')
    if proof == 'editable':
        edit.write_bytes(b'corrupt but real edits')
    alias = pair.with_suffix('.PNG')
    if not alias.exists():
        alias.write_bytes(pair.read_bytes())
    original_entries = store.source_entries
    def entries():
        found = original_entries()
        if alias not in found:
            found.append(alias)  # exercise case collision on insensitive Mac
        return found
    monkeypatch.setattr(store, 'source_entries', entries)
    if recent._HOST_WINDOWS:
        names = recent._WindowsRoot.names
        def actual_names(root):
            found = names(root)
            if root.folder == store.folder and alias.name not in found:
                found.append(alias.name)
            return found
        monkeypatch.setattr(recent._WindowsRoot, 'names', actual_names)
    arrival = store.file(picture(), keep=2)
    assert not victim.exists(), 'disk proof takes one place even in an ambiguous group'
    assert all(p.exists() for p in (pair, alias, arrival))
    assert edit.exists() == (proof == 'editable')


def test_s57_editable_only_can_autosave_twice(w, qapp):
    from annotshot.items import RectItem
    store = w.recent_store
    png = proven(store, 1)[0]
    editable = png.with_suffix('.annotshot')
    Document(picture()).save(str(editable))
    png.unlink()
    assert w.open_recent(str(editable))
    for _ in range(2):
        w.doc.add_items([RectItem()])
        assert w.doc.path == str(editable)
        assert w.autosave_now()
        settle(qapp)
    assert len(Document.load(editable).annotation_items()) == 2


def test_s57_initial_claim_failure_keeps_scene_and_detaches(w, monkeypatch):
    from annotshot.items import RectItem
    victim = proven(w.recent_store, 1)[0]
    original = victim.read_bytes()
    assert w.open_recent(str(victim))
    deny_creation(monkeypatch, lambda name: name.endswith('.claim-v1'), 'initial claim denied')
    w.doc.add_items([RectItem()])
    assert w.doc.path is None and w.doc.annotation_items()
    assert not w.autosave_now() and not w._autosave_timer.isActive()
    assert 'initial claim denied' in w.statusBar().currentMessage()
    assert victim.read_bytes() == original


@pytest.mark.skipif(recent._HOST_WINDOWS, reason='POSIX link syscall permits forced substitution; Windows publication/sharing peers deny it')
def test_fix3_receipt_binds_published_fd_not_substitute(w, monkeypatch):
    store = w.recent_store
    controls = proven(store, 2)
    path = store.reserve()
    real_link = recent.os.link
    personal = b'personal PNG swapped before receipt'
    def publish(src, dst, *a, **kw):
        result = real_link(src, dst, *a, **kw)
        if str(dst) == path.name:
            path.unlink()
            path.write_bytes(personal)
        return result
    with monkeypatch.context() as m:
        m.setattr(recent.os, 'link', publish)
        with pytest.raises(OSError, match='(?i)(incomplete|substitut|changed)'):
            store.file(picture(), path=path, keep=1)
    fresh = recent.RecentStore(lambda: store.folder)
    with recent._Root(store.folder) as root:
        assert not fresh._proven(root, path)
    assert all(p.exists() for p in controls), 'incomplete filing must skip pruning'
    fresh.file(picture(), keep=1)
    assert path.read_bytes() == personal
    assert not any(p.exists() for p in controls)


@pytest.mark.parametrize('collision', [False, True])
@pytest.mark.parametrize('linked', [False, True])
@pytest.mark.skipif(recent._HOST_WINDOWS, reason='POSIX rename-boundary forced swap; Windows handle/sharing and exclusive recovery tests cover the equivalent')
def test_fix3_expiry_syscall_swap_restores_without_overwrite(w, monkeypatch, collision, linked, tmp_path):
    store = w.recent_store
    victim, control, newest = proven(store, 3)
    personal = b'personal substitute'
    occupant = b'concurrent occupant'
    outside = tmp_path / 'personal.png'
    outside.write_bytes(personal)
    real_unlink = recent.os.unlink
    native = getattr(recent, '_rename_noreplace', None)
    injected = []
    restoring = []
    def swap():
        real_unlink(victim)
        if linked:
            victim.symlink_to(outside)
        else:
            victim.write_bytes(personal)
        injected.append(True)
    if native is None:
        def unlink(path, *a, **kw):
            if str(path) == victim.name and not injected:
                swap()
            return real_unlink(path, *a, **kw)
        monkeypatch.setattr(recent.os, 'unlink', unlink)
    else:
        def rename(src_root, src, dst_root, dst):
            if src_root.folder == store.folder and src == victim.name and not injected:
                swap()  # inside the last mutation boundary, after all checks
            elif dst_root.folder == store.folder and dst == victim.name and injected:
                restoring.append(True)
                if collision:
                    victim.write_bytes(occupant)  # at the no-replace restoration syscall
            return native(src_root, src, dst_root, dst)
        monkeypatch.setattr(recent, '_rename_noreplace', rename)
    import warnings
    with warnings.catch_warnings(record=True) as notices:
        warnings.simplefilter('always')
        gone = store.prune(keep=1)
    assert injected and restoring, 'expiry must move, verify and restore the substitute'
    assert gone == [control] and not control.exists() and newest.exists()
    if collision:
        assert victim.read_bytes() == occupant
        recovered = list(store.folder.glob('*recovered*'))
        assert len(recovered) == 1 and recovered[0].read_bytes() == personal
        assert str(recovered[0]) in ' '.join(str(n.message) for n in notices)
        assert recovered[0].is_symlink() == linked
    else:
        assert victim.read_bytes() == personal and victim.is_symlink() == linked
    assert outside.read_bytes() == personal


def tree_bytes_modes(folder):
    import stat
    return {p.name: (p.read_bytes(), stat.S_IMODE(p.stat().st_mode))
            for p in folder.iterdir() if p.is_file()}


@pytest.mark.parametrize('boundary', ['temp', 'install'])
@pytest.mark.skipif(recent._HOST_WINDOWS, reason='POSIX directory-swap syscall; Windows directory sharing peer and reservation exchange tests cover the equivalent')
def test_fix3_autosave_root_swap_is_handle_anchored(w, qapp, monkeypatch, tmp_path, boundary):
    from annotshot.items import RectItem
    import annotshot.scene as scene
    store = w.recent_store
    png = proven(store, 1)[0]
    editable = png.with_suffix('.annotshot')
    Document(picture()).save(editable)
    assert w.open_recent(str(png))
    w.doc.add_items([RectItem()])
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / editable.name).write_bytes(b'outside companion')
    (outside / editable.name).chmod(0o640)
    (outside / 'sentinel').write_bytes(b'sentinel')
    retired = tmp_path / 'admitted-root'
    snapshots = []
    def exchange(source=None):
        if source is not None:
            (outside / Path(source).name).write_bytes(b'outside exact source basename')
        snapshots.append(tree_bytes_modes(outside))
        store.folder.rename(retired)
        store.folder.symlink_to(outside, target_is_directory=True)
    real_open, real_mkstemp = recent.os.open, scene.tempfile.mkstemp
    real_link, real_replace = recent.os.link, recent.os.replace
    def open_(path, flags, *a, **kw):
        if boundary == 'temp' and flags & recent.os.O_CREAT and '.tmp' in str(path) and not snapshots:
            exchange()
        return real_open(path, flags, *a, **kw)
    def mkstemp(*a, **kw):
        if boundary == 'temp' and not snapshots:
            exchange()
        return real_mkstemp(*a, **kw)
    def link(src, dst, *a, **kw):
        if boundary == 'install' and str(dst) == editable.name and not snapshots:
            exchange()
        return real_link(src, dst, *a, **kw)
    def replace(src, dst, *a, **kw):
        if boundary == 'install' and Path(dst).name == editable.name and not snapshots:
            exchange(src)
        return real_replace(src, dst, *a, **kw)
    with monkeypatch.context() as m:
        m.setattr(recent.os, 'open', open_)
        m.setattr(scene.tempfile, 'mkstemp', mkstemp)
        m.setattr(recent.os, 'link', link)
        m.setattr(recent.os, 'replace', replace)
        assert w.autosave_now()
        settle(qapp)
    assert len(snapshots) == 1
    assert tree_bytes_modes(outside) == snapshots[0], 'outside entries, bytes and modes changed'
    assert w.doc.needs_write() and w.doc.annotation_items()
    assert w.doc.path is None
    assert not list(retired.glob('*.pending-*')) and not list(retired.glob('*.claim-v1'))


@pytest.mark.parametrize('unsupported', ['dir_fd', 'native-rename'])
@pytest.mark.skipif(recent._HOST_WINDOWS, reason='POSIX primitive gate only; Windows missing-native-primitive refusal tested separately')
def test_fix3_no_dir_fd_refuses_before_recent_mutation(w, qapp, monkeypatch, unsupported):
    from annotshot.items import RectItem
    png = proven(w.recent_store, 1)[0]
    assert w.open_recent(str(png))
    w.doc.add_items([RectItem()])
    before = all_bytes(w.recent_store.folder)
    with monkeypatch.context() as m:
        if unsupported == 'dir_fd':
            m.setattr(recent.os, 'supports_dir_fd', set())
        else:
            m.setattr(recent, '_native_rename', None)
        assert w.autosave_now()
        settle(qapp)
    assert all_bytes(w.recent_store.folder) == before
    assert w.doc.needs_write() and w.doc.annotation_items()


EDITOR_IMPORTS = PEER_IMPORTS + '''
from PySide6.QtWidgets import QApplication
from annotshot import mainwindow, hotkey, theme, capture as capture_module
from annotshot.items import RectItem
from annotshot.scene import Document
from annotshot.app import make_app
app = QApplication([])
hotkey.backend_class = lambda: hotkey.NoBackend
mainwindow.DEFAULT_DIR = folder.parent
private = lambda *a, **k: QSettings(str(folder.parent / 'fix3-peer.ini'), QSettings.IniFormat)
mainwindow.QSettings = theme.QSettings = capture_module.QSettings = private
make_app()
window = mainwindow.MainWindow()
assert window.open_recent(str(folder / sys.argv[2]))
item = RectItem()
item.set_geom((2, 3, 11, 7))
window.doc.add_items([item])
window._autosave_timer.stop()
'''


@pytest.mark.parametrize('existing', [False, True])
def test_fix3_two_process_first_save_wins_queued_stale_keeps_scene(w, qapp, tmp_path, existing):
    from annotshot.items import RectItem
    store = w.recent_store
    png = proven(store, 1)[0]
    editable = png.with_suffix('.annotshot')
    if existing:
        Document(picture()).save(editable)
    pixels = png.read_bytes()
    assert w.open_recent(str(png))
    a = RectItem()
    a.set_geom((4, 5, 9, 6))
    w.doc.add_items([a])
    code = EDITOR_IMPORTS + '''
from contextlib import contextmanager
original = recent._editing
@contextmanager
def parked(*a, **k):
    print('READY', flush=True)
    assert bounded_line(sys.stdin).strip() == 'GO'
    with original(*a, **k) as root:
        yield root
recent._editing = parked
assert window.autosave_now()
assert recent.writer().waitForDone(10000)
app.processEvents()
assert window.doc.path is None, 'stale editor stayed attached'
assert window.doc.needs_write() and window.doc.undo_stack.needs_save()
assert 'conflict' in window.statusBar().currentMessage().lower()
assert not window._autosave_timer.isActive()
assert window.doc.annotation_items() == [item]
window.doc.undo_stack.undo()
assert not window.doc.annotation_items()
window.doc.undo_stack.redo()
assert window.doc.annotation_items() == [item]
assert not window.autosave_now()
assert window._save_editable(sys.argv[3])
assert len(Document.load(sys.argv[3]).annotation_items()) == 1
window.doc.add_items([RectItem()])
recent._editing = original
assert window.autosave_now()
assert recent.writer().waitForDone(5000)
app.processEvents()
assert window.doc.path == sys.argv[3] and window.doc.undo_stack.isClean()
assert len(Document.load(sys.argv[3]).annotation_items()) == 2
print('DONE', flush=True)
'''
    copy = tmp_path / 'B-separate.annotshot'
    p = subprocess.Popen([sys.executable, '-c', code, str(store.folder), png.name, str(copy)],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        ready(p)
        assert w.autosave_now()
        settle(qapp)
        archive = editable.read_bytes()
        resume(p)
        assert editable.read_bytes() == archive and png.read_bytes() == pixels
        saved_b = Document.load(copy)
        assert saved_b.annotation_items()[0].geom() != a.geom()
        fresh = MainWindow()
        try:
            assert fresh.open_recent(str(png))
            fresh.doc.add_items([RectItem()])
            assert fresh.autosave_now()
            settle(qapp)
            assert len(Document.load(editable).annotation_items()) == 2
        finally:
            fresh.deleteLater()
        assert not list(store.folder.glob('*.pending-*'))
        assert not list(store.folder.glob('*.claim-v1'))
    finally:
        if p.poll() is None:
            p.kill()
            p.communicate(timeout=5)


def test_fix3_one_editor_two_queued_generations_chain(w, qapp, monkeypatch):
    from annotshot.items import RectItem
    png = proven(w.recent_store, 1)[0]
    assert w.open_recent(str(png))
    queued = []
    with monkeypatch.context() as m:
        m.setattr(recent.writer(), 'start', queued.append)
        for _ in range(2):
            w.doc.add_items([RectItem()])
            assert w.autosave_now()
    assert len(queued) == 2
    for index, job in enumerate(queued, 1):
        job.run()
        assert not job.outcome.error
        assert len(Document.load(png.with_suffix('.annotshot')).annotation_items()) == index
    settle(qapp)
    assert w.doc.path and w.doc.undo_stack.isClean()
    import stat
    from annotshot.scene import _NEW_FILE_MODE
    if recent._HOST_WINDOWS:
        assert png.with_suffix('.annotshot').stat().st_mode & stat.S_IWRITE
    else:
        assert stat.S_IMODE(png.with_suffix('.annotshot').stat().st_mode) == _NEW_FILE_MODE
    assert not list(png.parent.glob('.annotshot-stage-*'))


@pytest.mark.skipif(recent._HOST_WINDOWS, reason='POSIX forced swap after verification; Windows failed-restore test retains and names the exact stage file')
def test_fix3_expiry_failed_restore_retains_identified_stage(w, monkeypatch):
    store = w.recent_store
    victim, control, newest = proven(store, 3)
    native = recent._rename_noreplace
    injected = []
    def rename(src_root, src, dst_root, dst):
        if src_root.folder == store.folder and src == victim.name:
            victim.unlink()
            victim.write_bytes(b'retain this substitute')
            injected.append(True)
        elif dst_root.folder == store.folder and dst == victim.name:
            raise PermissionError('restore denied')
        return native(src_root, src, dst_root, dst)
    with monkeypatch.context() as m:
        m.setattr(recent, '_rename_noreplace', rename)
        with pytest.warns(RuntimeWarning) as notices:
            gone = store.prune(keep=1)
    staged = list(store.folder.glob('.annotshot-stage-*/expired'))
    assert injected and len(staged) == 1 and staged[0].read_bytes() == b'retain this substitute'
    assert str(staged[0]) in ' '.join(str(n.message) for n in notices)
    assert gone == [control] and newest.exists()
    store.file(picture(), keep=1)
    assert staged[0].read_bytes() == b'retain this substitute', 'later work must never sweep recovery staging'


@pytest.mark.parametrize('fault', ['failed-install', 'install-occupant', 'stage-substitute', 'restore-denied'])
@pytest.mark.skipif(recent._HOST_WINDOWS, reason='POSIX link/swap and mode bits; Windows autosave install/restore collision and read-only tests cover the equivalent')
def test_fix3_editable_restore_no_clobber_and_retry(w, qapp, monkeypatch, fault):
    from annotshot.items import RectItem
    import stat
    store = w.recent_store
    png = proven(store, 1)[0]
    editable = png.with_suffix('.annotshot')
    Document(picture()).save(editable)
    editable.chmod(0o640)
    previous = editable.read_bytes()
    assert w.open_recent(str(png))
    w.doc.add_items([RectItem()])
    native, link = recent._rename_noreplace, recent.os.link
    fired = []
    def publish(src, dst, *a, **kw):
        if str(dst) == editable.name:
            fired.append(True)
            if fault in ('failed-install', 'restore-denied'):
                raise PermissionError('install denied')
            if fault == 'install-occupant':
                editable.write_bytes(b'concurrent occupant')
        return link(src, dst, *a, **kw)
    def rename(src_root, src, dst_root, dst):
        if fault == 'restore-denied' and src == 'previous':
            raise PermissionError('restore denied')
        if fault == 'stage-substitute' and src_root.folder == store.folder and src == editable.name:
            editable.unlink()
            editable.write_bytes(b'substitute archive')
            fired.append(True)
        return native(src_root, src, dst_root, dst)
    with monkeypatch.context() as m:
        m.setattr(recent.os, 'link', publish)
        m.setattr(recent, '_rename_noreplace', rename)
        assert w.autosave_now()
        settle(qapp)
    assert fired and w.doc.needs_write() and w.doc.annotation_items()
    if fault == 'failed-install':
        assert editable.read_bytes() == previous and stat.S_IMODE(editable.stat().st_mode) == 0o640
        assert w.doc.path and w.autosave_now()
        settle(qapp)
        assert not w.doc.needs_write()
        assert stat.S_IMODE(editable.stat().st_mode) == 0o640
    elif fault == 'install-occupant':
        assert editable.read_bytes() == b'concurrent occupant'
        recovery = list(store.folder.glob('*recovered*.annotshot'))
        assert len(recovery) == 1 and recovery[0].read_bytes() == previous
        assert str(recovery[0]) in w.statusBar().currentMessage()
        assert stat.S_IMODE(recovery[0].stat().st_mode) == 0o640
        assert w.doc.path is None
    elif fault == 'stage-substitute':
        assert editable.read_bytes() == b'substitute archive' and w.doc.path is None
    else:
        retained = list(store.folder.glob('.annotshot-stage-*/previous'))
        assert len(retained) == 1 and retained[0].read_bytes() == previous
        assert str(retained[0]) in w.statusBar().currentMessage()
        store.file(picture(), keep=1)
        assert retained[0].read_bytes() == previous
    if fault != 'restore-denied':
        assert not list(store.folder.glob('.annotshot-stage-*'))


def test_fix3_loaded_archive_bound_under_claim_and_sync_stale_refused(w, qapp, monkeypatch):
    from annotshot.items import RectItem
    store = w.recent_store
    png = proven(store, 1)[0]
    editable = png.with_suffix('.AnNoTsHoT')
    Document(picture()).save(editable)
    loaded = Document.load_bytes
    claims = []
    def read(data, path):
        claims.extend(store.folder.glob('*.claim-v1'))
        return loaded(data, path)
    with monkeypatch.context() as m:
        m.setattr(Document, 'load_bytes', read)
        assert w.open_recent(str(png))
    assert claims and w.doc.path == str(editable)
    w.doc.add_items([RectItem()])
    other = MainWindow()
    try:
        assert other.open_recent(str(png))
        other.doc.add_items([RectItem()])
        assert other.autosave_now()
        settle(qapp)
        archive = editable.read_bytes()
        notices = []
        monkeypatch.setattr(w, '_warn', notices.append)
        assert not w._save_editable(str(editable))
        assert editable.read_bytes() == archive
        assert notices and 'conflict' in notices[0].lower()
        assert w.doc.path is None and w.doc.needs_write() and w.doc.undo_stack.needs_save()
        assert not w._pending_edits
    finally:
        other.deleteLater()


def test_fix3_queued_generations_advance_from_own_fd_not_callback_path(w, qapp, monkeypatch):
    from annotshot.items import RectItem
    png = proven(w.recent_store, 1)[0]
    assert w.open_recent(str(png))
    w.doc.add_items([RectItem()])
    assert w.autosave_now()
    assert recent.writer().waitForDone(5000)  # leave the written UI signal queued
    editable = png.with_suffix('.annotshot')
    other = MainWindow()
    try:
        assert other.open_recent(str(png))
        other.doc.add_items([RectItem()])
        assert other.autosave_now()
        assert recent.writer().waitForDone(5000)
        other_archive = editable.read_bytes()
        qapp.processEvents()  # the first writer must not adopt the second's path revision
        w.doc.add_items([RectItem()])
        assert w.doc.path is None and w.doc.needs_write()
        assert editable.read_bytes() == other_archive
    finally:
        other.deleteLater()


@pytest.mark.parametrize('route', ['recent', 'open-path'])
def test_fix3_loaded_baseline_survives_until_first_edit(w, qapp, route):
    from annotshot.items import RectItem
    png = proven(w.recent_store, 1)[0]
    editable = png.with_suffix('.annotshot')
    Document(picture()).save(editable)
    assert (w.open_recent(str(png)) if route == 'recent'
            else w.open_path(str(editable), ask=False))
    other = MainWindow()
    try:
        assert other.open_recent(str(png))
        other.doc.add_items([RectItem()])
        assert other.autosave_now()
        settle(qapp)
        committed = editable.read_bytes()
        w.doc.add_items([RectItem()])  # baseline is the load, not this later admission
        assert w.doc.path is None and not w.autosave_now()
        assert 'conflict' in w.statusBar().currentMessage().lower()
        assert w.doc.needs_write() and w.doc.undo_stack.needs_save()
        assert editable.read_bytes() == committed
    finally:
        other.deleteLater()
