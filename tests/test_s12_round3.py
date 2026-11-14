"""Round 3 guards: offscreen, isolated settings, harmless shell deadline probes."""
import builtins
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from annotshot import macos, mainwindow as mw
from annotshot.mainwindow import MainWindow
from annotshot.scene import Document
from annotshot.tools import Tool


@pytest.fixture
def window(qapp, monkeypatch, white):
    w = MainWindow()
    w._bind(Document(white))
    w.settings.setValue('recent/keep', False)
    w.show()
    w.view.set_zoom(w.view._dpr())
    qapp.processEvents()
    yield w
    w._permission_watch.stop()
    w._permission_timeout.stop()
    w._restart_pending = False
    w.hide()
    w.deleteLater()
    qapp.processEvents()


class FakeProcess(QObject):
    finished = Signal(int, object)
    errorOccurred = Signal(object)
    NormalExit = 0
    CrashExit = 1
    FailedToStart = 2
    instances = []
    detached = []

    def __init__(self, parent=None):
        super().__init__(parent)
        self.output = b''
        self.killed = False
        self.instances.append(self)

    def start(self, program, args):
        self.command = [program, *args]

    def kill(self):
        self.killed = True
        self.finished.emit(-1, self.CrashExit)

    def readAllStandardOutput(self):
        return self.output

    def answer(self, word, code=0, status=0):
        self.output = word
        self.finished.emit(code, status)

    @classmethod
    def startDetached(cls, program, args):
        cls.detached.append([program, *args])
        return True


@pytest.fixture
def processes(monkeypatch):
    FakeProcess.instances = []
    FakeProcess.detached = []
    monkeypatch.setattr(mw, 'QProcess', FakeProcess)
    monkeypatch.setattr(macos, 'IS_MAC', True)
    monkeypatch.setattr(macos, 'screen_capture_allowed', lambda: False)
    monkeypatch.setattr(macos, 'request_screen_capture', lambda: None)
    return FakeProcess


class Box(QMessageBox):
    """A real offscreen box whose event loop is replaced on this subclass."""
    seen = []
    choice = 'Later'

    def exec(self):
        self.seen.append(self)
        self.choice_button = next((b for b in self.buttons() if b.text() == self.choice), None)
        return 0

    def clickedButton(self):
        return self.choice_button


@pytest.mark.parametrize('value,expected', [(True, 'allowed'), (False, 'denied')])
def test_permission_three_states(monkeypatch, value, expected):
    monkeypatch.setattr(macos, 'IS_MAC', True)
    fn = SimpleNamespace(restype=None, argtypes=None)
    class Fn:
        def __call__(self):
            return value
    monkeypatch.setattr(macos, '_cg', lambda: SimpleNamespace(CGPreflightScreenCaptureAccess=Fn()))
    assert macos.screen_capture_state() == expected
    assert macos.screen_capture_allowed() is value


@pytest.mark.parametrize('case', ['off', 'missing', 'failure'])
def test_permission_unknown_is_allowed(monkeypatch, case):
    monkeypatch.setattr(macos, 'IS_MAC', case != 'off')
    def failure():
        if case == 'failure':
            raise RuntimeError('framework unavailable')
        return object()
    monkeypatch.setattr(macos, '_cg', failure)
    assert macos.screen_capture_state() == 'unknown'
    assert macos.screen_capture_allowed()


def test_permission_flag_imports_no_widgets(monkeypatch, capsys):
    from annotshot.__main__ import run
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        assert not name.startswith('PySide6')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(macos, 'screen_capture_state', lambda: 'denied')
    with monkeypatch.context() as imports:
        imports.setattr(builtins, '__import__', guarded)
        assert run(['--screen-permission']) == 0
    assert capsys.readouterr().out == 'denied\n'


@pytest.mark.parametrize('frozen', [False, True])
def test_permission_child_command(monkeypatch, frozen):
    monkeypatch.setattr(macos.sys, 'frozen', frozen, raising=False)
    assert macos.permission_check_command() == [macos.sys.executable, *([] if frozen else ['-m', 'annotshot']), '--screen-permission']


@pytest.mark.skipif(sys.platform == 'win32', reason='macOS app bundles use POSIX paths, which Windows rewrites with backslashes')
def test_relaunch_bundle_command_is_exact(monkeypatch):
    monkeypatch.setattr(macos.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(macos.sys, 'executable', '/A space/Annotshot.app/Contents/MacOS/Annotshot')
    assert macos.permission_relaunch_command() == ['/usr/bin/open', '-n', '/A space/Annotshot.app', '--args', '--permission-restart']
    monkeypatch.setattr(macos.sys, 'frozen', False)
    assert macos.permission_relaunch_command() == [macos.sys.executable, '-m', 'annotshot', '--permission-restart']


def test_fresh_allowed_requests_one_restart_no_permission_message(window, processes, monkeypatch):
    calls = []
    monkeypatch.setattr(window, 'quit_app', lambda: calls.append('quit'))
    monkeypatch.setattr(window, '_permission_message', lambda: calls.append('message'))
    window.capture()
    window.capture()
    assert len(processes.instances) == 1
    processes.instances[-1].answer(b'allowed\n')
    assert calls == ['quit']
    assert not processes.detached


@pytest.mark.parametrize('case', ['denied', 'unknown', 'timeout', 'crash', 'noise', 'start-failure'])
def test_fresh_not_allowed_shows_permission_without_restart(window, processes, monkeypatch, case):
    calls = []
    monkeypatch.setattr(window, '_permission_message', lambda: calls.append('message'))
    monkeypatch.setattr(window, 'quit_app', lambda: calls.append('quit'))
    window.capture()
    child = processes.instances[-1]
    if case == 'timeout':
        window._permission_check_timeout()
        assert child.killed
    elif case == 'start-failure':
        child.errorOccurred.emit(processes.FailedToStart)
    else:
        child.answer({'noise': b'allowed extra', 'crash': b'allowed'}.get(case, case.encode()),
                     -1 if case == 'crash' else 0)
    assert calls == ['message']
    assert not processes.detached


def test_permission_message_words_buttons_and_watch(window, processes, monkeypatch):
    Box.seen = []
    monkeypatch.setattr(mw, 'QMessageBox', Box)
    monkeypatch.setattr(Box, 'choice', 'Not now')
    window._permission_message()
    box = Box.seen[-1]
    assert box.text() == mw.PERMISSION_TEXT == (
        'macOS has not yet allowed Annotshot to take pictures of your screen.\n\n'
        'This is normal the first time, and it can come back after an update. '
        'Nothing is broken.\n\n'
        'Open System Settings and switch Annotshot on. macOS lists it under '
        '"Screen & System Audio Recording": that is macOS\'s own name for the setting. '
        'Annotshot takes still pictures only, never video or sound. '
        'Annotshot then restarts by itself.\n\n'
        'If Annotshot is already switched on there and macOS still refuses: '
        'remove it with −, add it again with + from '
        'Applications, and switch it on.')
    assert {b.text() for b in box.buttons()} == {'Open System Settings', 'Restart Annotshot', 'Not now'}
    assert box.defaultButton().text() == 'Open System Settings'
    assert window._permission_watch.isActive() and window._permission_watch.interval() == 3000
    assert 599 <= window._permission_deadline - time.monotonic() <= 600


@pytest.mark.parametrize('name', [
    'PERMISSION_TEXT', 'PERMISSION_STATUS', 'PERMISSION_ON', 'PERMISSION_RESTART',
    'RESTART_STILL_REFUSED', 'PERMISSION_FIX', 'PERMISSION_WAY_BACK',
])
def test_permission_words_use_record_only_in_the_macos_setting_name(name):
    text = getattr(mw, name).replace('Screen & System Audio Recording', '')
    assert 'record' not in text.casefold()


def test_permission_words_explain_the_repeat_ask_and_still_pictures():
    assert 'Nothing is broken.' in mw.PERMISSION_TEXT
    assert 'Nothing is broken.' in mw.RESTART_STILL_REFUSED
    assert 'never video or sound' in mw.PERMISSION_TEXT


def test_permission_words_end_with_the_matching_recovery_text():
    assert mw.PERMISSION_TEXT.endswith(mw.PERMISSION_WAY_BACK)
    assert mw.RESTART_STILL_REFUSED.endswith(mw.PERMISSION_FIX)
    assert mw.PERMISSION_WAY_BACK not in mw.RESTART_STILL_REFUSED


def test_manual_repeats_the_way_back_and_quotes_the_waiting_status_once():
    manual = (Path(__file__).resolve().parent.parent / 'docs' / 'USER-MANUAL.md').read_text(
        encoding='utf-8')
    assert manual.count(mw.PERMISSION_WAY_BACK) == 2
    assert manual.count(mw.PERMISSION_STATUS) == 1
    step = next(line for line in manual.splitlines() if line.startswith('4. **Start it:**'))
    assert f'"{mw.PERMISSION_STATUS}"' in step


def test_watch_single_flight_deadline_and_quit(window, processes, monkeypatch):
    window._permission_tick()
    assert not processes.instances
    window._permission_deadline = time.monotonic() + 600
    window._permission_watch.start()
    window._permission_tick()
    window._permission_tick()
    assert len(processes.instances) == 1
    processes.instances[-1].answer(b'denied')
    window._permission_deadline = time.monotonic() - 1
    window._permission_tick()
    assert not window._permission_watch.isActive() and len(processes.instances) == 1
    window._permission_deadline = time.monotonic() + 600
    window._permission_watch.start()
    window._permission_tick()
    window._permission_quitting()
    assert processes.instances[-1].killed and window._permission_process is None
    assert not window._permission_watch.isActive()


def test_activation_checks_only_while_watching(window, processes, monkeypatch, qapp):
    from annotshot.app import FileOpenFilter
    from PySide6.QtCore import QEvent
    monkeypatch.setattr(mw.sys, 'platform', 'darwin')
    f = FileOpenFilter(window)
    f.eventFilter(qapp, QEvent(QEvent.ApplicationActivate))
    assert not processes.instances
    window._permission_watch.start()
    window._permission_deadline = time.monotonic() + 600
    f.eventFilter(qapp, QEvent(QEvent.ApplicationActivate))
    assert len(processes.instances) == 1
    window._permission_quitting()


def test_unsaved_later_and_second_capture_show_restart_again(window, processes, monkeypatch):
    from annotshot.items import RectItem
    window.doc.add_items([RectItem()])
    assert window.doc.undo_stack.needs_save()
    Box.seen = []
    monkeypatch.setattr(mw, 'QMessageBox', Box)
    monkeypatch.setattr(Box, 'choice', 'Later')
    window.capture()
    processes.instances[-1].answer(b'allowed')
    assert Box.seen[-1].text() == mw.PERMISSION_RESTART == (
        'macOS now allows capture. Annotshot needs to restart to use it.')
    assert {b.text() for b in Box.seen[-1].buttons()} == {'Restart now', 'Later'}
    assert Box.seen[-1].defaultButton().text() == 'Restart now'
    assert window.statusBar().currentMessage() == 'Restart Annotshot to capture'
    window.capture()
    assert len(Box.seen) == 2 and len(processes.instances) == 1
    assert not processes.detached


def test_restart_refused_quit_never_arms_relauncher(window, processes, monkeypatch):
    from annotshot.items import RectItem
    window.doc.add_items([RectItem()])
    monkeypatch.setattr(mw, 'QMessageBox', Box)
    monkeypatch.setattr(Box, 'choice', 'Restart now')
    questions = []
    def refuse(*args):
        questions.append(args[2])
        return QMessageBox.Cancel
    monkeypatch.setattr(Box, 'question', refuse)
    window.capture()
    processes.instances[-1].answer(b'allowed')
    assert questions == ['Save your changes to this project first?']
    assert not window._restart_pending and not window._quitting
    window._permission_quitting()
    assert not processes.detached


def test_relauncher_only_at_certain_quit_and_once(window, processes, monkeypatch, qapp):
    calls = []
    monkeypatch.setattr(qapp, 'quit', lambda: calls.append('quit'))
    window._request_permission_restart()
    assert calls == ['quit'] and not processes.detached
    window._permission_quitting()
    window._permission_quitting()
    assert len(processes.detached) == 1
    command = processes.detached[0]
    assert command[:3] == ['/bin/sh', '-c', macos.RELAUNCH_WAIT]
    assert command[4] == str(os.getpid())
    assert command[5] == '30' and macos.RELAUNCH_SECONDS == 30
    assert command[6:] == macos.permission_relaunch_command()


@pytest.mark.parametrize('grant', ['allowed', 'denied'])
def test_restart_launch_status_and_no_loop(qapp, processes, monkeypatch, grant):
    monkeypatch.setattr(macos, 'screen_capture_state', lambda: grant)
    w = MainWindow(permission_restart=True)
    try:
        assert mw.PERMISSION_ON == 'macOS now allows capture'
        assert (w.statusBar().currentMessage() == mw.PERMISSION_ON) is (grant == 'allowed')
        calls = []
        monkeypatch.setattr(qapp, 'quit', lambda: calls.append('quit'))
        if grant == 'allowed':
            assert not processes.instances
            return
        Box.seen = []
        monkeypatch.setattr(mw, 'QMessageBox', Box)
        monkeypatch.setattr(Box, 'choice', 'Not now')
        for press in range(2):
            w.capture()
            processes.instances[-1].answer(b'allowed')
            assert len(Box.seen) == press + 1
            box = Box.seen[-1]
            assert box.text() == mw.RESTART_STILL_REFUSED == (
                'macOS shows Annotshot switched on but still refuses it. '
                'This can happen after an update. Nothing is broken.\n\n'
                'To fix it: open System Settings, find Annotshot under '
                '"Screen & System Audio Recording", remove it with −, '
                'add it again with + from Applications, and switch it on.')
            assert {b.text() for b in box.buttons()} == {
                'Restart Annotshot', 'Open System Settings', 'Not now'}
            assert box.defaultButton().text() == 'Restart Annotshot'
            assert w.statusBar().currentMessage() == 'Restart Annotshot to capture'
            assert not calls and not processes.detached
        monkeypatch.setattr(Box, 'choice', 'Restart Annotshot')
        w.capture()
        processes.instances[-1].answer(b'allowed')
        assert calls == ['quit']
        w._permission_quitting()
        assert len(processes.detached) == 1
        assert processes.detached[0][-1] == '--permission-restart'
    finally:
        w._restart_pending = False
        w.deleteLater()


class SaveWriter:
    """Run the real save job now, or hold its result until after Capture returns."""
    def __init__(self, immediate=False):
        self.immediate = immediate
        self.jobs = []
        self.waits = 0

    def start(self, job):
        self.jobs.append(job)
        if self.immediate:
            job.run()

    def finish(self):
        self.jobs[-1].run()

    def waitForDone(self):
        self.waits += 1


def edited_file(window, tmp_path):
    from annotshot.items import RectItem
    path = tmp_path / 'picture.annotshot'
    window.doc.save(path)
    item = RectItem()
    window.doc.add_items([item])
    return path, item


def record_quit(window, qapp, monkeypatch):
    calls = []
    def quit():
        calls.append('quit')
        window._permission_quitting()   # the app's certain-quit signal, faked
    monkeypatch.setattr(qapp, 'quit', quit)
    return calls


@pytest.mark.parametrize('immediate', [True, False])
@pytest.mark.parametrize('route', ['automatic', 'permission-button', 'restarted-button'])
def test_capture_restart_failed_save_keeps_edits_and_retries(
        window, processes, monkeypatch, tmp_path, qapp, immediate, route):
    from annotshot import scene
    failed_close_questions = []
    monkeypatch.setattr(window, '_ask_failed_write',
                        lambda why: failed_close_questions.append(why) or 'cancel')
    path, item = edited_file(window, tmp_path)
    writer = SaveWriter(immediate)
    monkeypatch.setattr(mw.recent, 'writer', lambda: writer)
    calls = record_quit(window, qapp, monkeypatch)
    if route != 'automatic':
        monkeypatch.setattr(mw, 'QMessageBox', Box)
        monkeypatch.setattr(Box, 'choice', 'Restart Annotshot')
        window._permission_restarted = route == 'restarted-button'
    fresh = b'denied' if route == 'permission-button' else b'allowed'
    real_write = scene.write_project
    def fail(*args):
        raise OSError(28, 'No space left on device')
    monkeypatch.setattr(scene, 'write_project', fail)
    window.capture()
    processes.instances[-1].answer(fresh)
    if not immediate:
        assert window._restart_pending and not window._quitting
        assert not calls and writer.waits == 0 and window.isVisible()
        writer.finish()
    assert not calls and not processes.detached and writer.waits == 0
    assert not window._restart_pending and not window._quitting
    assert window.isVisible() and window.doc.annotation_items() == [item]
    assert window.doc.needs_write()
    assert not Document.load(path).annotation_items()
    assert window.statusBar().currentMessage() == (
        'Annotshot did not restart: your changes to this picture could not be kept '
        '(No space left on device)')
    assert window.statusBar().currentMessage() == mw.RESTART_SAVE_FAILED.format(
        why='No space left on device')
    monkeypatch.setattr(scene, 'write_project', real_write)
    children = len(processes.instances)
    window.capture()
    if len(processes.instances) > children:
        processes.instances[-1].answer(fresh)
    assert len(writer.jobs) == 2
    if not immediate:
        writer.finish()
    assert calls == ['quit'] and len(processes.detached) == 1
    assert len(Document.load(path).annotation_items()) == 1
    assert failed_close_questions == []  # restart recovers before it quits


@pytest.mark.parametrize('already_queued', [False, True])
def test_capture_restart_waits_for_current_save_and_stays_usable(
        window, processes, monkeypatch, tmp_path, qapp, already_queued):
    from annotshot.items import RectItem
    path, _ = edited_file(window, tmp_path)
    writer = SaveWriter()
    monkeypatch.setattr(mw.recent, 'writer', lambda: writer)
    calls = record_quit(window, qapp, monkeypatch)
    if already_queued:
        window.autosave_now()
    window.capture()
    processes.instances[-1].answer(b'allowed')
    assert len(writer.jobs) == 1 and window._restart_pending
    assert not calls and not processes.detached and writer.waits == 0
    window.capture()                    # a second request does nothing
    assert len(writer.jobs) == 1
    window.doc.add_items([RectItem()])   # editing remains usable while waiting
    writer.finish()
    assert len(writer.jobs) == 2 and not calls
    assert writer.jobs[-1].gen == window.doc.changes
    writer.finish()
    assert calls == ['quit'] and len(processes.detached) == 1
    assert len(Document.load(path).annotation_items()) == 2


def test_person_quit_during_restart_save_has_no_relaunch(
        window, processes, monkeypatch, tmp_path, qapp):
    edited_file(window, tmp_path)
    writer = SaveWriter()
    monkeypatch.setattr(mw.recent, 'writer', lambda: writer)
    calls = record_quit(window, qapp, monkeypatch)
    window.capture()
    processes.instances[-1].answer(b'allowed')
    assert not calls and window._restart_pending
    window.quit_app()
    assert calls == ['quit'] and not processes.detached
    writer.finish()
    assert calls == ['quit'] and not processes.detached


@pytest.mark.parametrize('fresh', ['denied', 'unknown'])
def test_restarted_fresh_refused_keeps_permission_message(
        window, processes, monkeypatch, fresh):
    window._permission_restarted = True
    Box.seen = []
    monkeypatch.setattr(mw, 'QMessageBox', Box)
    monkeypatch.setattr(Box, 'choice', 'Not now')
    window.capture()
    processes.instances[-1].answer(fresh.encode())
    assert Box.seen[-1].text() == mw.PERMISSION_TEXT == (
        'macOS has not yet allowed Annotshot to take pictures of your screen.\n\n'
        'This is normal the first time, and it can come back after an update. '
        'Nothing is broken.\n\n'
        'Open System Settings and switch Annotshot on. macOS lists it under '
        '"Screen & System Audio Recording": that is macOS\'s own name for the setting. '
        'Annotshot takes still pictures only, never video or sound. '
        'Annotshot then restarts by itself.\n\n'
        'If Annotshot is already switched on there and macOS still refuses: '
        'remove it with −, add it again with + from Applications, and switch it on.')
    assert Box.seen[-1].defaultButton().text() == 'Open System Settings'
    assert window.statusBar().currentMessage() == mw.PERMISSION_STATUS == (
        'Capture is waiting for macOS to allow it')
    assert not window._restart_pending and not processes.detached


def test_restarted_watch_offers_settings_one_box_and_quit_closes_it(
        window, processes, monkeypatch, qapp):
    window._permission_restarted = True
    settings = []
    rejected = []
    calls = record_quit(window, qapp, monkeypatch)
    monkeypatch.setattr(macos, 'open_privacy_settings', lambda: settings.append(1))
    class RecoveryBox(Box):
        def reject(self):
            rejected.append(self)
            super().reject()

        def exec(self):
            self.show()
            count = len(processes.instances)
            window.capture()
            processes.instances[-1].answer(b'allowed')
            assert len(processes.instances) == count + 1
            assert window._permission_box is self
            if self.choice == 'Not now':
                window.quit_app()
                assert rejected == [self] and not self.isVisible()
            result = super().exec()
            self.hide()
            return result
    monkeypatch.setattr(mw, 'QMessageBox', RecoveryBox)
    monkeypatch.setattr(RecoveryBox, 'choice', 'Open System Settings')
    window._permission_watch.start()
    window._permission_deadline = time.monotonic() + 600
    window._permission_tick()
    processes.instances[-1].answer(b'allowed')
    assert settings == [1] and not window._permission_watch.isActive()
    monkeypatch.setattr(RecoveryBox, 'choice', 'Not now')
    window.capture()
    processes.instances[-1].answer(b'allowed')
    assert not window._restart_pending and not processes.detached
    assert calls == ['quit']


@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX relaunch script')
@pytest.mark.parametrize('seconds,alive,expected', [(5, False, 0), (1, True, 1), (0, False, 1)])
def test_real_relaunch_script_deadline(tmp_path, seconds, alive, expected):
    marker = tmp_path / 'a marker ; $ file'
    old = subprocess.Popen(['/bin/sleep', '10' if alive else '0'])
    try:
        if not alive:
            old.wait(timeout=2)
        started = time.monotonic()
        result = subprocess.run(
            ['/bin/sh', '-c', macos.RELAUNCH_WAIT, 'annotshot-relaunch',
             str(old.pid), str(seconds), '/bin/sh', '-c',
             'printf landed > "$1"', 'marker-command', str(marker)],
            timeout=4, check=False)
        assert time.monotonic() - started < 4
        assert result.returncode == expected
        assert marker.exists() is (expected == 0)
        if expected == 0:
            assert marker.read_text() == 'landed'
    finally:
        if old.poll() is None:
            old.kill()
        old.wait(timeout=2)


def test_off_mac_capture_starts_no_fresh_child(window, processes, monkeypatch):
    monkeypatch.setattr(macos, 'IS_MAC', False)
    assert window._may_record_screen()
    window._fresh_permission(lambda _: None)
    assert not processes.instances


def drag(view, a, b):
    a, b = view.mapFromScene(QPointF(*a)), view.mapFromScene(QPointF(*b))
    QTest.mousePress(view.viewport(), Qt.LeftButton, pos=a)
    QTest.mouseMove(view.viewport(), b)
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=b)


@pytest.mark.parametrize('tool', [Tool.ARROW, Tool.RECT, Tool.ELLIPSE, Tool.HIGHLIGHT, Tool.CALLOUT, Tool.PEN])
def test_two_objects_keep_tool_and_button(window, tool):
    v, doc = window.view, window.doc
    window.tool_actions[tool].trigger()
    done = []
    v.toolDone.connect(lambda: done.append(1))
    for i, (a, b) in enumerate([((40, 40), (160, 110)), ((240, 150), (370, 250))], 1):
        drag(v, a, b)
        assert len(doc.annotation_items()) == i
        assert v.tool is tool and window.tool_actions[tool].isChecked()
        assert doc.selected() == ([] if tool is Tool.PEN else [doc.annotation_items()[-1]])
        if tool is Tool.CALLOUT:
            assert doc.is_editing()
            window.escape()
    assert not done


@pytest.mark.parametrize('tool', [Tool.TEXT, Tool.CALLOUT])
def test_text_ending_press_only_ends_typing(window, tool):
    v, doc = window.view, window.doc
    window.tool_actions[tool].trigger()
    QTest.mouseClick(v.viewport(), Qt.LeftButton, pos=v.mapFromScene(QPointF(40, 40)))
    QTest.keyClicks(v.viewport(), 'a second note')
    QTest.mouseClick(v.viewport(), Qt.LeftButton, pos=v.mapFromScene(QPointF(450, 250)))
    assert len(doc.annotation_items()) == 1 and not doc.is_editing()
    assert doc.annotation_items()[0].props['text'] == 'a second note'
    assert v.tool is tool
    QTest.mouseClick(v.viewport(), Qt.LeftButton, pos=v.mapFromScene(QPointF(450, 250)))
    assert len(doc.annotation_items()) == 2 and doc.is_editing()


def test_drawing_tool_handle_resizes_one_undo_body_draws(window):
    v, doc = window.view, window.doc
    window.tool_actions[Tool.RECT].trigger()
    drag(v, (40, 40), (160, 110))
    item = doc.selected()[0]
    before, count = item.geom(), doc.undo_stack.count()
    handle = item.mapToScene(item.handle_points()[4])
    point = QPointF(v.mapFromScene(handle))
    QApplication.sendEvent(v.viewport(), QMouseEvent(
        QEvent.MouseMove, point, point, Qt.NoButton, Qt.NoButton, Qt.NoModifier))
    assert v.viewport().cursor().shape() == Qt.SizeFDiagCursor
    drag(v, (handle.x(), handle.y()), (200, 140))
    assert len(doc.annotation_items()) == 1 and doc.undo_stack.count() == count + 1
    assert item.geom()[2:4] == (160, 100)
    doc.undo_stack.undo()
    assert item.geom() == before
    point = QPointF(v.mapFromScene(QPointF(90, 70)))
    assert v.selected_handle_at(v.mapToScene(point.toPoint())) is None
    assert v._handle_drag is None
    QApplication.sendEvent(v.viewport(), QMouseEvent(
        QEvent.MouseMove, point, point, Qt.NoButton, Qt.NoButton, Qt.NoModifier))
    assert v.viewport().cursor().shape() == Qt.CrossCursor
    drag(v, (90, 70), (220, 160))
    assert len(doc.annotation_items()) == 2


def test_select_crop_escape_v_and_bind_capture_keep_tool(window, monkeypatch, white):
    v = window.view
    window.tool_actions[Tool.CROP].trigger()
    drag(v, (10, 10), (250, 200))
    assert v.tool is Tool.SELECT and window.tool_actions[Tool.SELECT].isChecked()
    window.tool_actions[Tool.ARROW].trigger()
    window.escape()
    assert v.tool is Tool.SELECT
    window.tool_actions[Tool.ARROW].trigger()
    QTest.mousePress(v.viewport(), Qt.LeftButton, pos=QPoint(40, 40))
    window.escape()
    assert v.tool is Tool.ARROW
    QTest.mouseRelease(v.viewport(), Qt.LeftButton, pos=QPoint(140, 140))
    QTest.keyClick(v.viewport(), Qt.Key_V)
    assert v.tool is Tool.SELECT
    window.tool_actions[Tool.RECT].trigger()
    window._bind(Document(white))
    assert v.tool is Tool.RECT and window.tool_actions[Tool.RECT].isChecked()
    from annotshot.capture import CaptureResult
    window.settings.setValue('capture/copy', False)
    window._capture_done(CaptureResult(white))
    assert v.tool is Tool.RECT
    window.hide()
    window.reopen()
    assert v.tool is Tool.RECT
    fresh = MainWindow()
    assert fresh.view.tool is Tool.SELECT
    fresh.deleteLater()


@pytest.mark.skipif(sys.platform == 'win32', reason='Windows temporary folders do not provide the POSIX 0700 permissions this macOS guard checks')
@pytest.mark.parametrize('outcome', ['success', 'failure', 'timeout', 'empty', 'missing', 'unreadable'])
def test_window_picture_command_and_private_cleanup(monkeypatch, outcome):
    monkeypatch.setattr(macos, 'IS_MAC', True)
    paths = []
    def run(command, **kwargs):
        path = Path(command[-1])
        paths.append(path)
        assert command == ['/usr/sbin/screencapture', '-x', '-o', '-l42', '-t', 'png', str(path)]
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert kwargs['timeout'] == 3
        if outcome == 'timeout':
            raise subprocess.TimeoutExpired(command, 3)
        if outcome == 'success':
            image = QImage(20, 10, QImage.Format_RGB32)
            image.fill(Qt.red)
            assert image.save(str(path))
        elif outcome in ('empty', 'unreadable', 'failure'):
            path.write_bytes(b'bad' if outcome != 'empty' else b'')
        return SimpleNamespace(returncode=1 if outcome == 'failure' else 0)
    monkeypatch.setattr(macos.subprocess, 'run', run)
    result = macos.window_picture(42)
    assert (result is not None) is (outcome == 'success')
    assert len(paths) == 1 and not paths[0].exists() and not paths[0].parent.exists()


@pytest.mark.parametrize('number', ['42', None, True, 42.0])
def test_window_picture_rejects_non_int(monkeypatch, number):
    monkeypatch.setattr(macos, 'IS_MAC', True)
    monkeypatch.setattr(macos.subprocess, 'run', lambda *a, **k: pytest.fail('native tool'))
    assert macos.window_picture(number) is None


def test_window_picture_off_mac(monkeypatch):
    monkeypatch.setattr(macos, 'IS_MAC', False)
    monkeypatch.setattr(macos.subprocess, 'run', lambda *a, **k: pytest.fail('native tool'))
    assert macos.window_picture(42) is None


@pytest.mark.parametrize('kind', ['matching', 'none', 'wrong'])
def test_window_worker_picture_or_fallback(qapp, monkeypatch, kind):
    from annotshot import capture as cap
    import threading
    gate = threading.Event()
    called = []
    image = QImage(600, 400 if kind != 'wrong' else 100, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    image.setPixelColor(300, 100, Qt.red)
    def picture(number):
        called.append(number)
        assert gate.wait(1)
        return None if kind == 'none' else image
    monkeypatch.setattr(macos, 'IS_MAC', True)
    monkeypatch.setattr(macos, 'window_picture', picture)
    s = cap.CaptureSession()
    fallback = QImage(300, 200, QImage.Format_RGB32)
    fallback.fill(Qt.blue)
    overlay = SimpleNamespace(area_pixels=lambda: fallback.rect(), title='Covered',
        grab=SimpleNamespace(image=fallback), close=lambda: None)
    s._remember_area = lambda _: None
    s._window_pick = SimpleNamespace(hwnd=42, rect=QRectF(10, 10, 300, 200))
    results = []
    s.finished.connect(results.append)
    s._deliver(overlay)
    assert not results and s.state == 'window-picture'
    gate.set()
    for _ in range(100):
        if results:
            break
        QTest.qWait(10)
    assert called == [42] and len(results) == 1 and results[0].title == 'Covered'
    out = results[0].image
    if kind == 'matching':
        assert out.size() == image.size() and out.pixelColor(0, 0) == QColor(Qt.white)
        assert out.pixelColor(300, 100) == QColor(Qt.red)
        assert out.format() == QImage.Format_RGB32 and out.devicePixelRatio() == 2
    else:
        assert out == fallback
    s.deleteLater()


@pytest.mark.parametrize('case', ['freeze', 'other-os', 'area', 'screen'])
def test_window_picture_only_live_mac_window(qapp, monkeypatch, case):
    from annotshot import capture as cap
    monkeypatch.setattr(macos, 'IS_MAC', case != 'other-os')
    monkeypatch.setattr(macos, 'window_picture', lambda _: pytest.fail('window picture'))
    s = cap.CaptureSession()
    s.freeze = case == 'freeze'
    if case not in ('area', 'screen'):
        s._window_pick = SimpleNamespace(hwnd=42, rect=QRectF(0, 0, 20, 10))
    image = QImage(20, 10, QImage.Format_RGB32)
    image.fill(Qt.blue)
    overlay = SimpleNamespace(area_pixels=lambda: image.rect(), title=None,
                              grab=SimpleNamespace(image=image))
    s._remember_area = lambda _: None
    results = []
    s.finished.connect(results.append)
    s._deliver(overlay)
    assert len(results) == 1 and results[0].image == image
    s.deleteLater()


@pytest.mark.parametrize('platform', ['win32', 'linux'])
def test_tray_created_only_first_hide(qapp, monkeypatch, platform):
    from annotshot import tray
    monkeypatch.setattr(mw.sys, 'platform', platform)
    created = []
    class Tray:
        def __init__(self, *args):
            created.append(self)
        def refresh(self): pass
    monkeypatch.setattr(tray, 'QSystemTrayIcon', SimpleNamespace(isSystemTrayAvailable=lambda: True))
    monkeypatch.setattr(tray, 'TrayController', Tray)
    w = MainWindow()
    assert w.can_hide_on_close() is (platform == 'win32')
    assert w.tray is None and not created
    w.show()
    w.hide()
    assert len(created) == 1
    w.show()
    w.hide()
    assert len(created) == 1
    w.deleteLater()
    w = MainWindow()
    w.set_keep_running(False)
    w.show()
    w.hide()
    assert w.tray is None and len(created) == 1
    w.deleteLater()


def test_welcome_four_distinct_loadable_icons(window):
    from PySide6.QtWidgets import QLabel
    from PySide6.QtSvg import QSvgRenderer
    icons = [label.property('welcomeIcon') for label in window.welcome.findChildren(QLabel)
             if label.property('welcomeIcon')]
    assert len(icons) == len(set(icons)) == 4
    assert {'lock', 'running'} <= set(icons)
    for icon in icons:
        assert QSvgRenderer(str(mw.ICON_DIR / f'{icon}.svg')).isValid()


def test_native_active_signal_checks_watch(window, processes, qapp):
    qapp.applicationStateChanged.emit(Qt.ApplicationActive)
    assert not processes.instances
    window._permission_deadline = time.monotonic() + 600
    window._permission_watch.start()
    qapp.applicationStateChanged.emit(Qt.ApplicationActive)
    assert len(processes.instances) == 1
    window._permission_quitting()


def test_watch_allowed_stops_and_requests_restart_once(window, processes, monkeypatch):
    calls = []
    monkeypatch.setattr(window, 'quit_app', lambda: calls.append('quit'))
    window._permission_deadline = time.monotonic() + 600
    window._permission_watch.start()
    window._permission_tick()
    processes.instances[-1].answer(b'allowed')
    assert calls == ['quit'] and not window._permission_watch.isActive()
    window._permission_tick()
    assert len(processes.instances) == 1


@pytest.mark.parametrize('button', ['Restart now', 'Restart Annotshot'])
def test_restart_buttons_use_one_unsaved_quit_guard(window, processes, monkeypatch, button):
    from annotshot.items import RectItem
    window.doc.add_items([RectItem()])
    calls = []
    monkeypatch.setattr(mw, 'QMessageBox', Box)
    monkeypatch.setattr(Box, 'choice', button)
    monkeypatch.setattr(window, 'maybe_discard', lambda: calls.append('guard') or False)
    if button == 'Restart now':
        window._permission_stale = True
        window._offer_permission_restart()
    else:
        window._permission_message()
    assert calls == ['guard'] and not window._quitting and not window._restart_pending
    window._permission_quitting()
    assert not processes.detached


def test_restart_flag_is_a_normal_launch_option(window, monkeypatch, qapp):
    from annotshot import app as app_module
    args = []
    monkeypatch.setattr(app_module, 'MainWindow', lambda **kw: args.append(kw) or window)
    monkeypatch.setattr(app_module.filetype, 'register', lambda: None)
    monkeypatch.setattr(app_module.filetype, 'user_choice', lambda: None)
    monkeypatch.setattr(qapp, 'exec', lambda: 0)
    assert app_module.file_argument(['annotshot', '--permission-restart']) is None
    assert app_module.argument_problem(['annotshot', '--permission-restart']) is None
    assert app_module.main(['annotshot', '--permission-restart']) == 0
    assert args == [{'permission_restart': True}]
    qapp.removeEventFilter(qapp._annotshot_file_filter)


def test_manual_matches_restart_and_sticky_tool_words():
    manual = (Path(__file__).resolve().parent.parent / 'docs/USER-MANUAL.md').read_text()
    assert manual.count('if the write fails, it stays open with your edits.') == 2
    assert manual.count('the next **Capture** press offers **Restart Annotshot** to try again.') == 2
    assert 'then quit Annotshot and start it again' not in manual
    assert 'then quit and reopen Annotshot' not in manual
    assert 'A drawing tool stays selected until you choose another tool.' in manual
    assert 'Crop returns to **Select**.' in manual
