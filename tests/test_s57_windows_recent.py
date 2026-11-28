"""Exercise the production Windows backend; only the OS call boundary is fake.

Native Windows runs use the real implementation as well (including peers).
The fake models identities, no-follow opens, sharing, and absent destinations.
"""
import ctypes
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QDateTime, Qt

from annotshot import recent
from test_s54_stage3_count import w, settle, bounded_line
from test_s3b2 import picture


class NativeCalls:
    """Small filesystem-backed model of the native Windows call contract."""
    def __init__(self):
        self.handles = {}
        self.serial = 0
        self.births = {}
        self.busy = set()
        self.hook = lambda *args: None
        self.attributes = {}
        self.created = []
        self.hidden_changes = []
        self.opens = []
        self.case_status = 0
        self.case_flags = 0
        self.case_queries = []
        self.w = SimpleNamespace(ULONG=ctypes.c_uint32)
        self.IO = ctypes.c_size_t  # unused output in the query boundary model
        self.nt = SimpleNamespace(NtQueryInformationFile=self._query)

    def _query(self, handle, io, buffer, size, kind):
        assert self.handles[handle].directory and kind == 71 and size == 4
        self.case_queries.append((handle, kind))
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_uint32))[0] = self.case_flags
        return ctypes.c_int32(self.case_status).value

    def _status(self, status):
        if status < 0:
            error = OSError('native query failed: ' + hex(status & 0xffffffff))
            error.winerror = 5
            raise error

    @staticmethod
    def sharing(path):
        error = PermissionError('sharing conflict: ' + str(path))
        error.winerror = 32
        return error

    @staticmethod
    def spelling(path):
        if os.path.lexists(path):
            return path
        if path.parent.is_dir():
            for entry in path.parent.iterdir():
                if entry.name.casefold() == path.name.casefold():
                    return entry
        return path

    def open(self, parent, name, *, directory=False, create=False,
             mutable=False, write=False, metadata=False, listing=False, hidden=False):
        self.opens.append((parent, name, directory, listing))
        if directory and name in ('.', '..'):
            error = OSError('invalid native directory name: ' + name)
            error.winerror = 123
            raise error
        path = Path(name) if parent is None else self.handles[parent].path / name
        if parent is not None:
            admitted = self.handles[parent]
            current = admitted.path.lstat()
            if (current.st_dev, current.st_ino) != (admitted.info.st_dev, admitted.info.st_ino):
                raise OSError('model directory handle no longer has its path')
        self.hook('open', path)
        if create:
            self.hook('create', path)
        path = self.spelling(path)
        if create and directory:
            path.mkdir()
        if not directory and not metadata and str(path) in self.busy:
            raise self.sharing(path)
        if create and not directory:
            with path.open('xb'):
                pass
        # These are logical native handles, independent of the host's CRT.
        # Files stay on disk for assertions; sharing is enforced by this model.
        info = path.lstat()
        if not directory and not metadata:
            for h in self.handles.values():
                if (not h.directory and not h.metadata and
                        (h.info.st_dev, h.info.st_ino) == (info.st_dev, info.st_ino)):
                    raise self.sharing(path)
        if create:
            self.attributes[(info.st_dev, info.st_ino)] = 2 if hidden else 0
            self.created.append((path, directory, hidden))
        self.births.setdefault((info.st_dev, info.st_ino), info.st_ctime_ns)
        self.serial += 1
        self.handles[self.serial] = SimpleNamespace(path=path, info=info,
            directory=directory, deleted=False, metadata=metadata,
            mutable=mutable, write=write)
        if directory and create and hidden:
            self.set_hidden(self.serial, True)
        return self.serial

    def info(self, handle):
        h = self.handles[handle]
        info = h.path.lstat()
        # Windows st_ctime is creation time, unaffected by rename/hard links.
        return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino,
            st_mode=info.st_mode, st_size=info.st_size, st_mtime_ns=info.st_mtime_ns,
            st_ctime_ns=self.births[(info.st_dev, info.st_ino)],
            st_file_attributes=(0x400 if h.path.is_symlink() else 0)
                | (0x10 if h.directory else 0)
                | self.attributes.get((info.st_dev, info.st_ino), 0)
                | (0 if info.st_mode & 0o222 else 1))

    def close(self, handle):
        h = self.handles.pop(handle)
        if h.deleted:
            if h.directory:
                h.path.rmdir()
            else:
                h.path.unlink()

    def duplicate(self, handle):
        h = self.handles[handle]
        self.serial += 1
        self.handles[self.serial] = SimpleNamespace(**vars(h))
        return self.serial

    names = recent._WindowsNative.names

    def _names(self, handle):
        path = self.handles[handle].path
        self.hook('names', path)
        return os.listdir(path)

    case_sensitive = recent._WindowsNative.case_sensitive

    def set_hidden(self, handle, hidden):
        h = self.handles[handle]
        key = h.info.st_dev, h.info.st_ino
        flags = self.attributes.get(key, 0)
        self.attributes[key] = (flags | 2) if hidden else (flags & ~2)
        self.hidden_changes.append((h.path, hidden))

    def hidden(self, path):
        info = path.stat()
        return bool(self.attributes.get((info.st_dev, info.st_ino), 0) & 2)

    def read(self, handle):
        h = self.handles[handle]
        return h.path.read_bytes()

    def write(self, handle, data):
        h = self.handles[handle]
        h.path.write_bytes(data)

    def seal(self, handle, mode):
        # Windows has a read-only attribute, not POSIX permission bits.
        # The native seal freezes times; it never makes the private temp
        # read-only just because the previous archive was read-only.
        self.handles[handle].path.chmod(0o666)

    def link(self, handle, parent, name):
        src, dst = self.handles[handle].path, self.handles[parent].path / name
        self.hook('link', dst)
        if os.path.lexists(self.spelling(dst)):
            raise FileExistsError(str(dst))
        os.link(src, dst)
        self.hook('linked', dst)

    def rename(self, handle, parent, name):
        src, dst = self.handles[handle].path, self.handles[parent].path / name
        self.hook('rename', dst)
        if os.path.lexists(self.spelling(dst)):
            raise FileExistsError(str(dst))
        src.rename(dst)
        for h in self.handles.values():
            if h.path == src:
                h.path = dst

    def delete(self, handle):
        h = self.handles[handle]
        self.hook('delete', h.path)
        if h.directory and os.listdir(h.path):
            raise OSError('directory not empty')
        if not h.path.lstat().st_mode & 0o200:
            raise PermissionError('read-only')
        h.deleted = True

    def compete(self, path, action, data=b'peer'):
        """A separate open cannot bypass the kernel sharing flags."""
        path = self.spelling(path)
        info = path.lstat() if os.path.lexists(path) else None
        for h in self.handles.values():
            if info is not None and (h.info.st_dev, h.info.st_ino) == (info.st_dev, info.st_ino):
                if h.directory or not h.metadata:
                    raise PermissionError('sharing conflict: ' + str(path))
        if action == 'write':
            path.write_bytes(data)
        elif action == 'replace':
            path.unlink()
            path.write_bytes(data)
        elif action == 'exchange':
            path.rename(path.with_name(path.name + '-peer'))


def when(year):
    return QDateTime.fromString(f'{year}-01-01T00:00:00.000', Qt.ISODateWithMs)


def bytes_in(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes()
            for p in folder.rglob('*') if p.is_file()}


@pytest.fixture
def win(monkeypatch, w):
    native = NativeCalls()
    monkeypatch.setattr(recent, '_HOST_WINDOWS', True, raising=False)
    monkeypatch.setattr(recent, '_windows_native', lambda: native, raising=False)
    # No POSIX capability may accidentally make the Windows proof green.
    monkeypatch.setattr(recent.os, 'supports_dir_fd', set())
    yield native
    w._autosave_timer.stop()
    assert recent.writer().waitForDone(5000)
    for doc, holds in list(w._pending_edits.items()):
        recent.finish_edits(doc.path, holds, abandon=True)
    w._pending_edits.clear()
    assert not native.handles, 'an admitted Windows handle leaked'


def test_windows_branch_keeps_reopens_autosaves_deletes_and_clears(w, qapp, win):
    from annotshot.items import RectItem
    store = w.recent_store
    first = store.file(picture(21, 11), keep=1)
    second = store.file(picture(22, 12), keep=1)
    assert not first.exists() and second.exists()
    from PySide6.QtGui import QImage
    assert QImage(str(second)).size().width() == 22
    assert QImage(str(second)).size().height() == 12
    assert w.open_recent(str(second))
    w.doc.add_items([RectItem()])
    assert w.autosave_now()
    settle(qapp)
    companion = second.with_suffix('.annotshot')
    assert companion.exists() and not w.doc.needs_write()
    assert w.open_recent(str(second))
    assert len(w.doc.annotation_items()) == 1
    store.delete(second)
    assert not second.exists() and not companion.exists()
    store.file(picture(), keep=1)
    store.clear()
    assert store.files() == []


def test_windows_rotation_proves_original_keeps_unrecorded_edited_and_choice(w, qapp, win):
    from annotshot.items import RectItem
    store = w.recent_store
    w.set_capture_count(1)
    edited = store.file(picture(21, 11), when(2020), keep=100)
    assert w.open_recent(str(edited))
    w.doc.add_items([RectItem()])
    assert w.autosave_now()
    settle(qapp)
    pair = edited.with_suffix('.annotshot')
    before = (edited.read_bytes(), pair.read_bytes())
    personal = store.folder / 'personal.png'
    personal.write_bytes(b'unrecorded personal picture')
    control = store.file(picture(22, 12), when(2021), keep=100)
    arrival = store.file(picture(23, 13), when(2019), keep=w.capture_count())
    assert not control.exists() and arrival.exists(), 'arrival wins even after clock rollback'
    assert (edited.read_bytes(), pair.read_bytes()) == before
    assert personal.read_bytes() == b'unrecorded personal picture'
    assert w.capture_count() == 1
    assert w.settings.value(recent.COUNT_SETTING, type=int) == 1


@pytest.mark.parametrize('boundary', ['publication', 'trim', 'autosave', 'cleanup'])
def test_windows_verified_handles_deny_root_and_child_exchange(w, qapp, win, tmp_path, boundary):
    from annotshot.items import RectItem
    from annotshot.scene import Document
    store = w.recent_store
    old = store.file(picture(21, 11), when(2020), keep=100)
    outside = tmp_path / 'outside'
    outside.mkdir()
    sentinel = outside / 'sentinel.png'
    sentinel.write_bytes(b'outside sentinel')
    denied = []
    def attack(event, path):
        hit = ((boundary == 'publication' and event == 'linked' and path.suffix == '.png')
               or (boundary == 'trim' and event == 'rename' and path.name == 'expired')
               or (boundary == 'autosave' and event == 'link' and path.suffix == '.annotshot')
               or (boundary == 'cleanup' and event == 'delete' and '.pending-' in path.name))
        if hit:
            for target, action in ((store.folder, 'exchange'), (old, 'replace')):
                # At trim the handle has not moved yet; at every other
                # boundary the original must still be locked or deliberately
                # outside this operation (publication gets its own new PNG).
                if boundary == 'publication' and target == old:
                    target = path
                with pytest.raises(PermissionError, match='sharing'):
                    win.compete(target, action)
                denied.append((event, target.name))
            if boundary == 'trim':
                with pytest.raises(PermissionError, match='sharing'):
                    win.compete(old.with_suffix('.annotshot'), 'write', b'late edits')
                denied.append((event, 'late editable'))
    if boundary in ('autosave', 'cleanup'):
        assert w.open_recent(str(old))
        w.doc.add_items([RectItem()])
        # The editor's production admission pins both loaded revisions
        # through its own cleanup; a separate caller pin would be a busy peer.
        win.hook = attack
        assert w.autosave_now()
        settle(qapp)
        assert not w.doc.needs_write()
        assert len(Document.load(old.with_suffix('.annotshot')).annotation_items()) == 1
    else:
        win.hook = attack
        store.file(picture(22, 12), when(2021), keep=1)
    assert denied and sentinel.read_bytes() == b'outside sentinel'
    assert not list(store.folder.glob('*.pending-*'))
    assert not list(store.folder.glob('.annotshot-stage-*'))


@pytest.mark.parametrize('spelling', ['same', 'case-only'])
def test_windows_publication_occupied_destination_keeps_both_and_reports_stage(w, win, spelling):
    store = w.recent_store
    control = store.file(picture(), when(2020), keep=100)
    path = store.reserve(when(2021))
    occupant = path if spelling == 'same' else path.with_suffix('.PNG')
    def collide(event, target):
        if event == 'link' and target == path:
            win.compete(occupant, 'write', b'publication occupant')
    win.hook = collide
    with pytest.raises(OSError) as notice:
        store.file(picture(17, 9), path=path, keep=1)
    staged = list(store.folder.glob('.annotshot-stage-*/capture.tmp'))
    assert control.exists() and occupant.read_bytes() == b'publication occupant'
    assert len(staged) == 1 and staged[0].read_bytes().startswith(b'\x89PNG')
    assert str(staged[0].parent) in str(notice.value)
    assert not (store.folder / recent._receipt_name(path)).exists()


@pytest.mark.parametrize('fault', ['busy', 'read-only', 'unrecorded', 'receipt', 'inventory'])
def test_windows_uncertain_or_busy_never_authorizes_expiry(w, win, fault):
    store = w.recent_store
    old = store.file(picture(21, 11), when(2020), keep=100)
    new = store.file(picture(22, 12), when(2021), keep=100)
    before = old.read_bytes()
    if fault == 'busy':
        win.busy.add(str(old))
    elif fault == 'read-only':
        old.chmod(0o444)
    elif fault == 'unrecorded':
        (store.folder / recent._receipt_name(old)).unlink()
    elif fault == 'receipt':
        (store.folder / recent._receipt_name(old)).write_bytes(b'bad receipt')
    else:
        def deny(event, target):
            if event == 'names' and target == store.folder:
                raise PermissionError('inventory denied')
        win.hook = deny
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        assert store.prune(keep=1) == []
    assert old.read_bytes() == before and new.exists()
    if fault == 'read-only':
        old.chmod(0o600)


def test_windows_denied_expiry_leaves_no_placeholder(w, win, monkeypatch):
    # Run the real Windows failure through the native-call model on the Mac.
    from test_s54_stage3_count import test_prune_uncertain_inventory_or_denied_unlink_preserves
    test_prune_uncertain_inventory_or_denied_unlink_preserves(w, monkeypatch, 'unlink')


@pytest.mark.parametrize('outcome', ['success', 'denied', 'exception', 'info-exception', 'body-exception',
                                    'inventory-exception', 'mark-denied', 'not-needed'])
def test_windows_expiry_placeholder_lifetime(w, win, monkeypatch, outcome):
    store = w.recent_store
    old = store.file(picture(), when(2020), keep=100)
    store.file(picture(), when(2021), keep=100)
    companion = old.with_suffix('.annotshot')
    if outcome == 'denied':
        def deny(event, path):
            if event == 'delete' and path.name == 'expired':
                raise PermissionError('picture removal denied')
        win.hook = deny
        with pytest.warns(RuntimeWarning, match='kept'):
            assert store.prune(keep=1) == []
    elif outcome == 'success':
        assert store.prune(keep=1) == [old]
    elif outcome in ('body-exception', 'inventory-exception', 'mark-denied'):
        marks = []
        def fail(event, path):
            if outcome == 'body-exception' and event == 'rename' and path.name == 'expired':
                raise OSError('expiry body failed')
            if (outcome == 'inventory-exception' and event == 'names'
                    and path == store.folder and companion.exists()):
                raise OSError('expiry inventory failed')
            if outcome == 'mark-denied' and event == 'delete' and path == companion:
                marks.append(path)
                if len(marks) == 1:
                    raise PermissionError('first placeholder mark denied')
        win.hook = fail
        with pytest.warns(RuntimeWarning):
            assert store.prune(keep=1) == []
        if outcome == 'mark-denied':
            assert len(marks) == 2, 'finally must retry on the creating handle'
    else:
        # Even a setup failure before the guard yields must retire our entry.
        if outcome in ('exception', 'info-exception'):
            if outcome == 'exception':
                def fail_seal(handle, mode):
                    raise OSError('placeholder setup failed')
                monkeypatch.setattr(win, 'seal', fail_seal)
            else:
                info, failed = win.info, []
                def fail_first_info(handle):
                    if win.handles[handle].path == companion and not failed:
                        failed.append(handle)
                        raise OSError('placeholder setup failed')
                    return info(handle)
                monkeypatch.setattr(win, 'info', fail_first_info)
            with recent._Root(store.folder) as root:
                with pytest.raises(OSError, match='setup failed'):
                    with recent._expiry_guard(root, old):
                        pytest.fail('setup should have failed')
        else:
            with recent._Root(store.folder) as root:
                with recent._expiry_guard(root, old):
                    assert companion.exists()
                    # The caller returns without expiring this capture.
                    pass
    assert not companion.exists()
    assert old.exists() is (outcome != 'success')


@pytest.mark.parametrize('change', ['bytes', 'identity'])
def test_windows_placeholder_cleanup_preserves_changed_entry(w, win, monkeypatch, change):
    old = w.recent_store.file(picture(), when(2020), keep=100)
    companion = old.with_suffix('.annotshot')
    def change_setup(handle, mode):
        # Deliberately bypass model sharing to exercise the last safety gate.
        # A real independent writer cannot acquire this exclusive handle.
        if change == 'identity':
            companion.rename(companion.with_suffix('.displaced'))
        companion.write_bytes(b'work' if change == 'bytes' else b'')
        info = companion.stat()
        win.births[(info.st_dev, info.st_ino)] = info.st_ctime_ns
    monkeypatch.setattr(win, 'seal', change_setup)
    with recent._Root(old.parent) as root:
        with pytest.raises(OSError, match='placeholder changed'):
            with recent._expiry_guard(root, old):
                pytest.fail('changed placeholder admitted')
    assert companion.read_bytes() == (b'work' if change == 'bytes' else b'')
    assert old.exists()


def test_windows_zero_byte_companion_is_not_an_edit_or_removed(w, win):
    store = w.recent_store
    old = store.file(picture(), when(2020), keep=100)
    newer = store.file(picture(), when(2021), keep=100)
    empty = old.with_suffix('.annotshot')
    empty.write_bytes(b'')
    identity = empty.stat().st_dev, empty.stat().st_ino
    assert not (store.folder / recent._claim_name(old)).exists()
    assert store.prune(keep=1) == [old]
    assert newer.exists() and empty.read_bytes() == b''
    assert (empty.stat().st_dev, empty.stat().st_ino) == identity


@pytest.mark.parametrize('protection', ['claim', 'nonempty', 'unrecorded', 'late-write'])
def test_windows_empty_companion_does_not_bypass_protection(w, win, protection):
    store = w.recent_store
    old = store.file(picture(), when(2020), keep=100)
    newer = store.file(picture(), when(2021), keep=100)
    companion = old.with_suffix('.annotshot')
    companion.write_bytes(b'work' if protection == 'nonempty' else b'')
    if protection == 'unrecorded':
        (store.folder / recent._receipt_name(old)).unlink()
    with recent._Root(store.folder) as root:
        claim = recent._claim(root, old) if protection == 'claim' else None
        if protection == 'late-write':
            # A writer wins just before the final exclusive create/pin.
            def late_write(event, path):
                if event == 'create' and path == companion:
                    companion.write_bytes(b'late work')
            win.hook = late_write
        try:
            if protection == 'late-write':
                with pytest.warns(RuntimeWarning):
                    assert store.prune(keep=1) == []
                assert companion.read_bytes() == b'late work'
            else:
                assert store.prune(keep=1) == []
        finally:
            if claim is not None:
                claim.release(root)
    assert old.exists() and newer.exists() and companion.exists()


def test_windows_rechecks_reservation_root_and_rejects_reparse(w, win, tmp_path, monkeypatch):
    store = w.recent_store
    path = store.reserve(when(2020))
    retired, outside = tmp_path / 'retired', tmp_path / 'outside'
    store.folder.rename(retired)
    outside.mkdir()
    (outside / 'sentinel.png').write_bytes(b'outside sentinel')
    store.folder.mkdir()
    actual_info = win.info
    def reparse(handle):
        info = actual_info(handle)
        if win.handles[handle].path == store.folder:
            info.st_file_attributes |= 0x400
        return info
    monkeypatch.setattr(win, 'info', reparse)
    with pytest.raises(OSError, match='link|junction|changed'):
        store.file(picture(), path=path, keep=1)
    assert bytes_in(outside) == {'sentinel.png': b'outside sentinel'}


@pytest.mark.parametrize('collision', [False, True])
@pytest.mark.parametrize('fail', [False, True])
def test_windows_restore_is_exclusive_and_failure_names_retained_file(w, win, collision, fail):
    store = w.recent_store
    store.folder.mkdir(parents=True, exist_ok=True)
    occupant = store.folder / 'picture.png'
    occupant.write_bytes(b'original-name occupant')
    previous = store.folder / 'previous.png'
    previous.write_bytes(b'displaced substitute')
    attempted = []
    def collide(event, target):
        if event != 'rename':
            return
        if fail:
            raise PermissionError('restore denied')
        if collision and 'recovered-' in target.name and not attempted:
            attempted.append(target)
            target.write_bytes(b'recovery-name occupant')
    with recent._Root(store.folder) as root:
        with recent._Stage(root) as stage:
            # A recovery is an existing picture moved to staging, not a newly
            # created bookkeeping temp (which would correctly be hidden).
            root.rename(previous.name, stage, 'previous')
            win.hook = collide
            retained = stage.folder / 'previous'
            if fail:
                with pytest.raises(OSError) as notice:
                    recent._restore(stage, 'previous', root, occupant.name)
                assert str(retained) in str(notice.value)
            else:
                name = recent._restore(stage, 'previous', root, occupant.name)
                assert 'recovered-' in name
                assert (store.folder / name).read_bytes() == b'displaced substitute'
                assert not win.hidden(store.folder / name)
    assert occupant.read_bytes() == b'original-name occupant'
    if fail:
        assert retained.read_bytes() == b'displaced substitute'
    if attempted:
        assert attempted[0].read_bytes() == b'recovery-name occupant'


def test_windows_stale_editor_preserves_winner_scene_undo_and_one_save_as(w, qapp, win, tmp_path):
    from annotshot.items import RectItem
    from annotshot.mainwindow import MainWindow
    from annotshot.scene import Document
    store = w.recent_store
    png = store.file(picture(), when(2020), keep=100)
    assert w.open_recent(str(png))
    other = MainWindow()
    try:
        assert other.open_recent(str(png))
        w.doc.add_items([RectItem()])
        assert w.autosave_now()
        settle(qapp)
        winner = png.with_suffix('.annotshot').read_bytes()
        other.doc.add_items([RectItem()])
        assert other.doc.path is None
        assert other.doc.needs_write() and other.doc.undo_stack.needs_save()
        other.doc.undo_stack.undo()
        assert not other.doc.annotation_items()
        other.doc.undo_stack.redo()
        assert len(other.doc.annotation_items()) == 1
        copy = tmp_path / 'one-save-as.annotshot'
        assert other._save_editable(str(copy))
        assert len(Document.load(copy).annotation_items()) == 1
        assert not other.doc.needs_write()
        assert png.with_suffix('.annotshot').read_bytes() == winner
    finally:
        other.deleteLater()


@pytest.mark.parametrize('fault', ['install-failure', 'install-occupant', 'restore-denied', 'busy-companion', 'read-only'])
def test_windows_autosave_install_failure_preserves_bytes_and_reports_recovery(w, qapp, win, fault):
    from annotshot.items import RectItem
    from annotshot.scene import Document
    store = w.recent_store
    png = store.file(picture(), when(2020), keep=100)
    editable = png.with_suffix('.annotshot')
    Document(picture()).save(editable)
    if fault == 'read-only':
        editable.chmod(0o444)
    previous, pixels = editable.read_bytes(), png.read_bytes()
    assert w.open_recent(str(png))
    w.doc.add_items([RectItem()])
    if fault == 'busy-companion':
        win.busy.add(str(editable))
    fired = []
    def fail(event, target):
        if event == 'link' and target == editable:
            fired.append(event)
            if fault == 'install-occupant':
                win.compete(target, 'write', b'autosave occupant')
            elif fault in ('install-failure', 'restore-denied'):
                raise PermissionError('install denied')
        if event == 'rename' and target == editable and fault == 'restore-denied':
            raise PermissionError('restore denied')
    win.hook = fail
    assert w.autosave_now()
    settle(qapp)
    assert w.doc.needs_write() and w.doc.undo_stack.needs_save()
    assert len(w.doc.annotation_items()) == 1 and png.read_bytes() == pixels
    w.doc.undo_stack.undo()
    assert not w.doc.annotation_items()
    w.doc.undo_stack.redo()
    if fault == 'install-occupant':
        recovery = list(store.folder.glob('*recovered*.annotshot'))
        assert editable.read_bytes() == b'autosave occupant'
        assert len(recovery) == 1 and recovery[0].read_bytes() == previous
        assert str(recovery[0]) in w.statusBar().currentMessage()
        assert w.doc.path is None
    elif fault == 'restore-denied':
        retained = list(store.folder.glob('.annotshot-stage-*/previous'))
        assert len(retained) == 1 and retained[0].read_bytes() == previous
        assert str(retained[0]) in w.statusBar().currentMessage()
    else:
        assert editable.read_bytes() == previous
    if fault in ('install-failure', 'busy-companion'):
        win.hook = lambda *args: None
        win.busy.clear()
        assert w.autosave_now()
        settle(qapp)
        assert not w.doc.needs_write()
        assert len(Document.load(editable).annotation_items()) == 1
    if fault == 'read-only':
        editable.chmod(0o600)


def test_windows_missing_primitive_refuses_before_mutation(w, win, monkeypatch):
    store = w.recent_store
    store.file(picture(), when(2020), keep=100)
    before = bytes_in(store.folder)
    def unavailable():
        raise OSError('Safe Windows Recent primitives are unavailable')
    monkeypatch.setattr(recent, '_windows_native', unavailable)
    with pytest.raises(OSError, match='primitives'):
        store.reserve(when(2021))
    assert store.prune(keep=1) == []
    assert bytes_in(store.folder) == before


@pytest.mark.parametrize('case', ['sensitive', 'unknown', 'late-companion'])
def test_windows_expiry_requires_proven_exclusive_companion_absence(w, win, monkeypatch, case):
    store = w.recent_store
    old = store.file(picture(), when(2020), keep=100)
    store.file(picture(), when(2021), keep=100)
    before = old.read_bytes()
    if case == 'sensitive':
        monkeypatch.setattr(win, 'case_sensitive', lambda handle: True)
    elif case == 'unknown':
        def unknown(handle):
            raise OSError('case query unavailable')
        monkeypatch.setattr(win, 'case_sensitive', unknown)
    else:
        def create_companion(event, target):
            if event == 'open' and target == old.with_suffix('.annotshot') and not target.exists():
                target.write_bytes(b'late companion must survive')
        win.hook = create_companion
    with pytest.warns(RuntimeWarning):
        assert store.prune(keep=1) == []
    assert old.read_bytes() == before
    if case == 'late-companion':
        assert old.with_suffix('.annotshot').read_bytes() == b'late companion must survive'


def test_windows_borrow_retains_handle_until_last_metadata_reader(w, win):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    png = w.recent_store.file(picture(), when(2020), keep=100)
    expected = png.read_bytes()
    admitted, release = threading.Event(), threading.Event()
    with recent._Root(png.parent) as root:
        def peer():
            with pytest.raises(PermissionError, match='busy'):
                with root.pin(png.name):
                    pass
            with root._lease(png.name, metadata=True) as handle:
                admitted.set()
                assert release.wait(5), 'borrower release timeout'
                assert not handle.closed and recent._fd_info(handle).st_size == len(expected)
                return handle
        with ThreadPoolExecutor(1) as pool:
            with root.pin(png.name) as (_, _, handle):
                future = pool.submit(peer)
                assert admitted.wait(5), 'borrower admission timeout'
            assert not handle.closed, 'the pin owner closed a borrowed native handle'
            release.set()
            assert future.result(timeout=5) is handle
            assert handle.closed
        with root.pin(png.name) as (data, _, _):
            assert data == expected
    assert png.read_bytes() == expected


def test_windows_empty_stage_cleanup_reopens_by_identity_and_keeps_substitute(w, win):
    store = w.recent_store
    store.folder.mkdir(parents=True, exist_ok=True)
    exchanged = []
    def exchange(event, target):
        if (event == 'open' and target.name.startswith('.annotshot-stage-')
                and target.exists() and not exchanged
                and not any(h.directory and h.path == target for h in win.handles.values())):
            retired = target.with_name(target.name + '-retired')
            target.rename(retired)
            target.mkdir()
            (target / 'sentinel.png').write_bytes(b'cleanup substitute sentinel')
            exchanged.append(target)
    win.hook = exchange
    with recent._Root(store.folder) as root:
        with recent._Stage(root):
            pass
    assert len(exchanged) == 1
    assert (exchanged[0] / 'sentinel.png').read_bytes() == b'cleanup substitute sentinel'


@pytest.mark.parametrize('name', ['.', '..'])
def test_windows_model_refuses_dot_directory_names_and_reopens_empty(w, win, name):
    folder = w.recent_store.folder
    folder.mkdir(parents=True, exist_ok=True)
    with recent._Root(folder) as root:
        with pytest.raises(OSError) as failure:
            win.open(root.fd.raw, name, directory=True)
        assert failure.value.winerror == 123
        before = set(win.handles)
        assert root.names() == []
        assert set(win.handles) == before, 'listing handle must close'
        assert win.opens[-1] == (root.fd.raw, '', True, True)
        with recent._Stage(root) as stage:
            staged = stage.folder
        assert not staged.exists(), 'empty-stage cleanup must enumerate too'


@pytest.mark.parametrize('busy_for', [0.1, None])
def test_windows_read_pin_retries_sharing_for_250ms_then_keeps(w, win, monkeypatch, busy_for):
    store = w.recent_store
    old = store.file(picture(), when(2020), keep=100)
    newer = store.file(picture(), when(2021), keep=100)
    original = old.read_bytes()
    elapsed, attempts, sleeps = [0.0], [], []
    def sleep(seconds):
        assert 0 < seconds <= 0.025
        sleeps.append(seconds)
        elapsed[0] += seconds
    # Deterministic elapsed time at the actual production retry seam.
    monkeypatch.setattr(recent, 'time', SimpleNamespace(
        monotonic=lambda: elapsed[0], sleep=sleep, time_ns=time.time_ns))
    def sharing(event, path):
        if event == 'open' and path == old:
            # Metadata opens do not invoke this refusal in the native model;
            # busy is checked only when acquiring a real read pin.
            if busy_for is None or elapsed[0] < busy_for:
                win.busy.add(str(old))
            else:
                win.busy.discard(str(old))
            attempts.append(elapsed[0])
    win.hook = sharing
    gone = store.prune(keep=1)
    assert newer.exists() and sleeps and len(attempts) > 1
    if busy_for is None:
        assert gone == [] and old.read_bytes() == original
        assert 0.25 <= elapsed[0] <= 0.251
    else:
        assert gone == [old] and not old.exists()
        assert 0.1 <= elapsed[0] < 0.25


def test_windows_read_pin_does_not_retry_other_errors(w, win, monkeypatch):
    png = w.recent_store.file(picture(), when(2020), keep=100)
    original = png.read_bytes()
    calls = []
    def denied(event, path):
        if event == 'open' and path == png:
            calls.append(path)
            error = PermissionError('access denied')
            error.winerror = 5
            raise error
    win.hook = denied
    with recent._Root(png.parent) as root:
        with pytest.raises(PermissionError, match='access denied'):
            root.read(png.name)
    assert len(calls) == 1 and png.read_bytes() == original


@pytest.mark.parametrize('status,flags,expires', [
    (0, 0, True), (0, 1, False),
    (0xc0000003, 0, True),   # STATUS_INVALID_INFO_CLASS
    (0xc000000d, 0, True),   # STATUS_INVALID_PARAMETER
    (0xc00000bb, 0, True),   # STATUS_NOT_SUPPORTED
    (0xc0000022, 0, False),  # STATUS_ACCESS_DENIED
    (0xc0000185, 0, False),  # STATUS_IO_DEVICE_ERROR
    (0xc0000004, 0, False),  # STATUS_INFO_LENGTH_MISMATCH is not unsupported
])
def test_windows_class71_only_unsupported_allows_expiry(w, win, status, flags, expires):
    store = w.recent_store
    old = store.file(picture(), when(2020), keep=100)
    newer = store.file(picture(), when(2021), keep=100)
    original = old.read_bytes()
    win.case_status, win.case_flags = status, flags
    if expires:
        assert store.prune(keep=1) == [old]
        assert not old.exists()
    else:
        with pytest.warns(RuntimeWarning):
            assert store.prune(keep=1) == []
        assert old.read_bytes() == original
    assert newer.exists() and win.case_queries


def test_windows_private_creations_hidden_publication_and_recovery_visible(w, qapp, win):
    from annotshot.items import RectItem
    store = w.recent_store
    reserved = store.reserve(when(2019))
    marker = store.folder / ('.' + reserved.name + '.reserve')
    assert win.hidden(marker)
    store.release(reserved)
    png = store.file(picture(), when(2020), keep=100)
    receipt = store.folder / recent._receipt_name(png)
    assert win.hidden(receipt) and not win.hidden(png)
    with recent._Root(store.folder) as root:
        claim = recent._claim(root, png)
        try:
            assert win.hidden(store.folder / claim.name)
            with recent._expiry_guard(root, png):
                assert win.hidden(png.with_suffix('.annotshot'))
        finally:
            root.unlink(claim.name, claim.identity)
        with recent._Stage(root) as stage:
            assert win.hidden(stage.folder)
            with stage.temporary('capture.tmp', b'retained temp'):
                assert win.hidden(stage.folder / 'capture.tmp')
            stage.unlink('capture.tmp')
    assert w.open_recent(str(png))
    w.doc.add_items([RectItem()])
    pending = list(store.folder.glob('*.pending-*'))
    assert pending and all(win.hidden(path) for path in pending)
    assert w.autosave_now()
    settle(qapp)
    editable = png.with_suffix('.annotshot')
    assert editable.exists() and not win.hidden(editable) and not win.hidden(png)
    # Force a genuine displaced editable down the recovery road.
    original = editable.read_bytes()
    with recent._Root(store.folder) as root:
        with recent._Stage(root) as stage:
            root.rename(editable.name, stage, 'previous')
            editable.write_bytes(b'new occupant')
            restored = recent._restore(stage, 'previous', root, editable.name)
            recovery = store.folder / restored
            assert '-recovered-' in restored and recovery.read_bytes() == original
            assert not win.hidden(recovery)
    private = [(path, directory, hidden) for path, directory, hidden in win.created
               if path.is_relative_to(store.folder) and path != store.folder]
    assert private and all(hidden for _, _, hidden in private)
    names = [path.name for path, _, _ in private]
    assert all(any(check(name) for name in names) for check in (
        lambda n: n.endswith('.reserve'), lambda n: n.endswith('.filed-v1'),
        lambda n: n.endswith('.claim-v1'), lambda n: '.pending-' in n,
        lambda n: n.endswith('.annotshot'), lambda n: n == 'capture.tmp',
        lambda n: n == 'editable.tmp', lambda n: n.startswith('.annotshot-stage-')))
    assert not any(hidden and path in (png, editable, recovery)
                   for path, hidden in win.hidden_changes)


def test_windows_old_unhidden_receipts_remain_readable(w, win):
    store = w.recent_store
    old = store.file(picture(), when(2020), keep=100)
    newer = store.file(picture(), when(2021), keep=100)
    receipt = store.folder / recent._receipt_name(old)
    info = receipt.stat()
    win.attributes[(info.st_dev, info.st_ino)] &= ~2
    assert not win.hidden(receipt)
    assert store.prune(keep=1) == [old] and newer.exists()


def test_windows_native_boundary_empty_unicode_hidden_create_and_attribute_update(monkeypatch):
    """Run production packing/access logic; replace only the DLL entry points."""
    class Function:
        def __init__(self, call=lambda *args: 1):
            self.call = call
        def __call__(self, *args):
            return self.call(*args)
    class DLL:
        def __getattr__(self, name):
            function = Function()
            setattr(self, name, function)
            return function
    nt, kernel = DLL(), DLL()
    monkeypatch.setattr(ctypes, 'WinDLL',
        lambda name, **kw: nt if name == 'ntdll' else kernel, raising=False)
    native = recent._WindowsNative()
    created, changes, attributes = [], [], [0]
    def create(handle, access, obj, io, allocation, flags, share, disposition, options, ea, length):
        obj = obj._obj
        name = obj.name.contents
        created.append((obj.root, name.length, name.maximum,
                        name.buffer, access, flags, share, disposition, options))
        attributes[0] = flags | (0x10 if options & 1 else 0)
        handle._obj.value = 123
        return 0
    def change(handle, io, value, size, kind):
        value = value._obj
        assert handle == 123 and kind == 4 and size == 40
        assert (value.created, value.accessed, value.written, value.changed) == (0, 0, 0, 0)
        changes.append(value.attributes)
        attributes[0] = value.attributes
        return 0
    nt.NtCreateFile.call, nt.NtSetInformationFile.call = create, change
    monkeypatch.setattr(native, 'info', lambda handle:
        SimpleNamespace(st_file_attributes=attributes[0]))
    # File HIDDEN is set in NtCreateFile, without modifying a public path.
    handle = native.open(7, 'private.tmp', create=True, write=True, mutable=True, hidden=True)
    assert created[-1][5:8] == (2, 1, 2)  # HIDDEN, share-read, FILE_CREATE
    assert created[-1][4] & 0x100  # FILE_WRITE_ATTRIBUTES
    native.set_hidden(handle, False)
    assert changes == [0x80], 'zero attributes would leave the temp hidden'
    # Directories also receive the immediate handle-based set after creation.
    native.open(7, '.annotshot-stage-test', directory=True, create=True, hidden=True)
    assert created[-1][5] == 2 and changes[-1] == 0x12
    monkeypatch.setattr(native, '_names', lambda listing: [])
    assert native.names(7) == []
    assert created[-1][:4] == (7, 0, 2, '')
    assert created[-1][4] & 1, 'reopened directory must have LIST_DIRECTORY'


native_windows = pytest.mark.skipif(os.name != 'nt', reason='requires real Windows NT handles; Mac native-call models are not native proof')


@native_windows
def test_native_windows_denied_expiry_leaves_no_placeholder(w, monkeypatch):
    test_windows_denied_expiry_leaves_no_placeholder(w, None, monkeypatch)


@native_windows
@pytest.mark.parametrize('outcome', ['success', 'exception', 'not-needed'])
def test_native_windows_expiry_placeholder_lifetime(w, monkeypatch, outcome):
    test_windows_expiry_placeholder_lifetime(w, recent._windows_native(), monkeypatch, outcome)


@native_windows
def test_native_windows_zero_byte_companion_is_not_an_edit_or_removed(w):
    test_windows_zero_byte_companion_is_not_an_edit_or_removed(w, None)


@native_windows
def test_native_windows_private_attributes_and_public_names(w, qapp):
    from annotshot.items import RectItem
    store = w.recent_store
    reserved = store.reserve(when(2019))
    marker = store.folder / ('.' + reserved.name + '.reserve')
    assert marker.stat().st_file_attributes & 2
    store.release(reserved)
    png = store.file(picture(), when(2020), keep=100)
    assert not png.stat().st_file_attributes & 2
    assert (store.folder / recent._receipt_name(png)).stat().st_file_attributes & 2
    with recent._Root(store.folder) as root:
        with recent._Stage(root) as stage:
            assert stage.folder.stat().st_file_attributes & 2
            with stage.temporary('private.tmp', b'private'):
                assert (stage.folder / 'private.tmp').stat().st_file_attributes & 2
            stage.unlink('private.tmp')
    assert w.open_recent(str(png))
    w.doc.add_items([RectItem()])
    assert all(p.stat().st_file_attributes & 2 for p in store.folder.glob('*.pending-*'))
    assert w.autosave_now()
    settle(qapp)
    assert not png.with_suffix('.annotshot').stat().st_file_attributes & 2
    assert not png.stat().st_file_attributes & 2


@native_windows
def test_native_windows_store_and_editor_roundtrip(w, qapp):
    # The very same store/editor scenario also runs against the real OS.
    test_windows_branch_keeps_reopens_autosaves_deletes_and_clears(w, qapp, None)


@native_windows
def test_native_windows_pinned_children_and_admitted_root_deny_independent_peer(w):
    import subprocess
    import sys
    store = w.recent_store
    png = store.file(picture(), when(2020), keep=100)
    before = png.read_bytes()
    code = '''import ctypes, os, sys
from ctypes import wintypes as w
k = ctypes.WinDLL('kernel32', use_last_error=True)
k.CreateFileW.argtypes = [w.LPCWSTR,w.DWORD,w.DWORD,w.LPVOID,w.DWORD,w.DWORD,w.HANDLE]
k.CreateFileW.restype = w.HANDLE
h = k.CreateFileW(sys.argv[1], 0x40000000, 7, None, 3, 0x00200000, None)
assert h == w.HANDLE(-1).value, 'peer acquired a competing write handle'
assert ctypes.get_last_error() == 32, ctypes.get_last_error()
h = k.CreateFileW(sys.argv[3], 0x40000000, 7, None, 1, 0x00200000, None)
assert h == w.HANDLE(-1).value, 'peer created a late editable companion'
assert ctypes.get_last_error() in (5, 32, 80, 183), ctypes.get_last_error()
try: os.rename(sys.argv[2], sys.argv[2] + '-peer')
except OSError as e: assert e.winerror in (5, 32), e
else: raise AssertionError('peer exchanged an admitted root')
print('DENIED', flush=True)
'''
    with recent._Root(store.folder) as root:
        with root.pin(png.name), recent._expiry_guard(root, png):
            result = subprocess.run([sys.executable, '-c', code, str(png), str(store.folder), str(png.with_suffix('.annotshot'))],
                                    capture_output=True, text=True, timeout=12)
    assert result.returncode == 0 and 'DENIED' in result.stdout, result.stderr
    assert png.read_bytes() == before


@native_windows
def test_native_windows_competing_open_preserves_busy_picture_then_expires_control(w):
    import subprocess
    import sys
    store = w.recent_store
    old = store.file(picture(21, 11), when(2020), keep=100)
    store.file(picture(22, 12), when(2021), keep=100)
    before = old.read_bytes()
    code = '''import ctypes, sys, queue, threading
from ctypes import wintypes as w
k = ctypes.WinDLL('kernel32', use_last_error=True)
k.CreateFileW.argtypes = [w.LPCWSTR,w.DWORD,w.DWORD,w.LPVOID,w.DWORD,w.DWORD,w.HANDLE]
k.CreateFileW.restype = w.HANDLE
k.CloseHandle.argtypes = [w.HANDLE]
h = k.CreateFileW(sys.argv[1], 0x40000000, 3, None, 3, 0x00200000, None)
assert h != w.HANDLE(-1).value, ctypes.get_last_error()
print('READY', flush=True)
q = queue.Queue()
threading.Thread(target=lambda: q.put(sys.stdin.readline()), daemon=True).start()
assert q.get(timeout=8).strip() == 'GO'
k.CloseHandle(h)
print('DONE', flush=True)
'''
    peer = subprocess.Popen([sys.executable, '-c', code, str(old)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert bounded_line(peer.stdout).strip() == 'READY'
        assert store.prune(keep=1) == []
        assert old.read_bytes() == before
        out, err = peer.communicate('GO\n', timeout=12)
        assert peer.returncode == 0 and 'DONE' in out, err
        assert store.prune(keep=1) == [old]
        assert not old.exists()
    finally:
        if peer.poll() is None:
            peer.kill()
            peer.communicate(timeout=5)


@native_windows
def test_native_windows_real_junction_never_reaches_outside(w, tmp_path):
    import subprocess
    store = w.recent_store
    store.folder.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'sentinel.png').write_bytes(b'outside native sentinel')
    result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J',
                             str(store.folder), str(outside)],
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr + result.stdout
    before = bytes_in(outside)
    with pytest.raises(OSError):
        store.reserve(when(2021))
    assert store.files() == [] and store.prune(keep=1) == []
    with pytest.raises(OSError):
        store.delete(store.folder / 'sentinel.png')
    assert bytes_in(outside) == before
