"""Capture-key recovery, offscreen and with counted fake system calls only."""
import ctypes
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QKeyCombination, QSettings, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest

from annotshot import hotkey
from annotshot.keywords import key_words
from annotshot.app import make_app
from annotshot.mainwindow import HOTKEY_NAME, MainWindow
from annotshot.settings_dialog import SettingsDialog


@pytest.fixture
def backend():
    class CountingBackend:
        available = True
        register_calls = []
        unregister_calls = 0
        successes = 0
        refuse = False
        fail = False
        fail_clear = False
        refusals = []

        def __init__(self, fire):
            self.fire = fire
            self.held = None

        def register(self, seq):
            type(self).register_calls.append(QKeySequence(seq))
            assert self.held is None, "each candidate owns a distinct native handle"
            if self.fail:
                raise RuntimeError("fake registration failure")
            refuse = self.refusals.pop(0) if self.refusals else self.refuse
            if refuse:
                return hotkey.TAKEN.format(
                    key=seq.toString(QKeySequence.NativeText))
            type(self).successes += 1
            self.held = QKeySequence(seq)
            return None

        def unregister(self):
            type(self).unregister_calls += 1
            if self.fail_clear:
                raise RuntimeError("fake unregister failure")
            self.held = None

    return CountingBackend


def assert_tracks_backend(capture_key):
    held = capture_key._backend.held if capture_key._backend is not None else None
    assert capture_key.registered == (held is not None)
    return held


@pytest.fixture
def make_window(qapp, monkeypatch, private_settings, backend):
    make_app()
    monkeypatch.setattr(hotkey, "backend_class", lambda: backend)
    windows = []

    def make(copy=hotkey.DEFAULT, off=False):
        settings = QSettings(private_settings, QSettings.IniFormat)
        if copy is not None:
            settings.setValue("shortcuts/copy", copy)
        if off:
            settings.setValue("hotkey/off", True)
        settings.sync()
        window = MainWindow()
        windows.append(window)
        return window

    yield make
    for window in windows:
        assert_tracks_backend(window.hotkey)
        assert window.hotkey.clear() is None
        assert_tracks_backend(window.hotkey)
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()


def start_with_clash(make_window, backend):
    window = make_window()
    assert window.a_copy.shortcut() == QKeySequence(hotkey.DEFAULT)
    assert not window.settings.contains("hotkey/sequence")
    problem = window.apply_hotkey()
    assert problem == window._taken(QKeySequence(hotkey.DEFAULT), "Copy image")
    assert window.statusBar().currentMessage() == f"{HOTKEY_NAME}: {problem}"
    assert not window.hotkey.registered
    assert backend.register_calls == []
    assert_tracks_backend(window.hotkey)
    return window


@pytest.fixture
def tray_for(make_window):
    from PySide6.QtGui import QAction
    from annotshot.tray import TrayController

    windows = []

    def attach(window):
        # The actual formatter, with no native tray icon or menu.
        tray = SimpleNamespace(window_=window, capture_action=QAction(window))
        tray.refresh = lambda: TrayController.refresh(tray)
        window.tray = tray
        windows.append(window)
        tray.refresh()
        return tray

    yield attach
    for window in windows:
        window.tray = None


@pytest.mark.parametrize("path", ["reset", "set", "all", "page_reset",
                                  "page_commit", "page_all"])
def test_freeing_button_recovers_capture_key(make_window, backend, path, tray_for):
    window = start_with_clash(make_window, backend)
    tray = tray_for(window)
    assert tray.capture_action.text() == "Capture"
    page = SettingsDialog(window) if path.startswith("page_") else None
    if page:
        # Produce the page's own stale capture-key sentence through its row.
        assert page.commit_hotkey()
        assert "Copy image" in page.message.text()
    if path == "reset":
        assert window.reset_shortcut("copy") is None
    elif path == "set":
        assert window.set_shortcut("copy", QKeySequence("Ctrl+K")) is None
    elif path == "all":
        assert window.reset_all_shortcuts() is None
    elif path == "page_reset":
        assert page.reset("copy") is None
    elif path == "page_commit":
        page.edits["copy"].setKeySequence(QKeySequence("Ctrl+K"))
        assert page.commit("copy") is None
    else:
        page._reset_all()
    assert window.hotkey.registered
    assert tray.capture_action.text() == f"Capture ({window.capture_key_text()})"
    assert backend.register_calls == [QKeySequence(hotkey.DEFAULT)]
    assert backend.successes == len(backend.register_calls)
    assert window.statusBar().currentMessage() == ""
    assert not window.settings.contains("hotkey/sequence")
    assert not window.settings.contains("hotkey/off")
    if path in ("set", "page_commit"):
        assert window.settings.value("shortcuts/copy") == "Ctrl+K"
    else:
        assert not window.settings.contains("shortcuts/copy")
    if page:
        assert page.message.text() == ""
        page.deleteLater()


@pytest.mark.parametrize("path", ["reset", "all", "page_all"])
def test_capture_key_off_stays_unregistered(make_window, backend, path):
    window = make_window(off=True)
    assert window.apply_hotkey() is None
    if path == "reset":
        assert window.reset_shortcut("copy") is None
    elif path == "all":
        assert window.reset_all_shortcuts() is None
    else:
        page = SettingsDialog(window)
        page._reset_all()
        assert page.message.text() == ""
        page.deleteLater()
    assert window.hotkey_off()
    assert not window.hotkey.registered
    assert backend.register_calls == [] and backend.unregister_calls == 0


def test_unavailable_platform_never_registers(make_window, backend):
    backend.available = False
    window = make_window()
    assert window.apply_hotkey() is None
    window.reset_all_shortcuts()
    assert not window.hotkey.registered
    assert backend.register_calls == [] and backend.unregister_calls == 0


def test_system_refusal_displays_current_reason(make_window, backend):
    window = start_with_clash(make_window, backend)
    backend.refuse = True
    assert window.reset_shortcut("copy") is None
    assert not window.hotkey.registered
    assert backend.register_calls == [QKeySequence(hotkey.DEFAULT)]
    assert backend.successes == 0
    problem = hotkey.TAKEN.format(
        key=window.hotkey_sequence().toString(QKeySequence.NativeText))
    assert window.statusBar().currentMessage() == f"{HOTKEY_NAME}: {problem}"


@pytest.mark.parametrize("path", ["set", "reset"])
def test_registered_capture_key_is_not_registered_again(make_window, backend, path):
    window = make_window(copy="Ctrl+K")
    assert window.apply_hotkey() is None
    assert window.hotkey.registered and backend.successes == 1
    calls = (list(backend.register_calls), backend.unregister_calls)
    if path == "set":
        assert window.set_shortcut("copy", QKeySequence("Ctrl+Alt+Y")) is None
    else:
        assert window.reset_shortcut("copy") is None
    assert window.hotkey.registered
    assert (backend.register_calls, backend.unregister_calls) == calls


@pytest.mark.parametrize("path", ["set", "reset"])
def test_refused_button_change_does_nothing(make_window, backend, path):
    window = start_with_clash(make_window, backend)
    if path == "reset":
        # A second legacy action owns Copy's shipped key.
        window._use_shortcuts("save", [QKeySequence("Ctrl+C")])
    keys = window.a_copy.shortcuts()
    saved = {key: window.settings.value(key) for key in window.settings.allKeys()}
    status = window.statusBar().currentMessage()
    problem = (window.reset_shortcut("copy") if path == "reset" else
               window.set_shortcut("copy", window.a_dup.shortcut()))
    assert problem
    assert window.a_copy.shortcuts() == keys
    assert {key: window.settings.value(key) for key in window.settings.allKeys()} == saved
    assert window.statusBar().currentMessage() == status
    assert not window.hotkey.registered
    assert backend.register_calls == [] and backend.unregister_calls == 0


def test_freeing_one_of_two_owners_reports_remaining_owner(make_window, backend):
    window = start_with_clash(make_window, backend)
    # Startup normally rejects duplicate saved keys; inject the second owner
    # to guard recovery when more than one action owns the capture key.
    window._use_shortcuts("save", [QKeySequence(hotkey.DEFAULT)])
    assert window.reset_shortcut("copy") is None
    assert not window.hotkey.registered
    assert backend.register_calls == [] and backend.unregister_calls == 0
    problem = window._taken(QKeySequence(hotkey.DEFAULT), window.shortcut_names["save"])
    assert window.statusBar().currentMessage() == f"{HOTKEY_NAME}: {problem}"


def test_recovery_preserves_unrelated_status(make_window, backend):
    window = start_with_clash(make_window, backend)
    window.statusBar().showMessage("Saved image")
    assert window.reset_shortcut("copy") is None
    assert window.hotkey.registered and backend.successes == 1
    assert window.statusBar().currentMessage() == "Saved image"


@pytest.mark.parametrize("path", ["set", "reset"])
def test_unchanged_button_keys_do_not_retry(make_window, backend, path):
    window = make_window(copy=None)
    if path == "set":
        assert window.set_shortcut("copy", window.a_copy.shortcut()) is None
    else:
        assert window.reset_shortcut("copy") is None
    assert not window.hotkey.registered
    assert backend.register_calls == [] and backend.unregister_calls == 0


@pytest.mark.parametrize("failure", ["refused", "exception", "invalid", "unavailable",
                                     "unregister", "unavailable_unregister",
                                     "invalid_unregister"])
def test_registered_property_tracks_failed_replacement(qapp, backend, failure):
    capture_key = hotkey.GlobalHotkey(backend=backend)
    assert not capture_key.registered
    assert_tracks_backend(capture_key)
    with pytest.raises(AttributeError):
        capture_key.registered = True
    assert capture_key.set_sequence(QKeySequence(hotkey.DEFAULT)) is None
    assert capture_key.registered
    assert assert_tracks_backend(capture_key) == QKeySequence(hotkey.DEFAULT)
    if failure == "refused":
        backend.refuse = True
    elif failure == "exception":
        backend.fail = True
    elif failure.startswith("unavailable"):
        backend.available = False
    backend.fail_clear = failure.endswith("unregister")
    seq = QKeySequence("A" if failure.startswith("invalid") else "Ctrl+Alt+Y")
    problem = capture_key.set_sequence(seq)
    assert problem
    assert capture_key.registered
    held = assert_tracks_backend(capture_key)
    swapped = failure == "unregister"
    assert held == QKeySequence("Ctrl+Alt+Y" if swapped else hotkey.DEFAULT)
    if swapped:
        assert problem == hotkey.RELEASE.format(key=key_words(QKeySequence(hotkey.DEFAULT)))
        assert len(capture_key._retained) == 1
    elif failure.startswith("unavailable"):
        assert problem == hotkey.NOT_ON_LINUX
    elif failure.startswith("invalid"):
        assert problem == hotkey.NEED_MODIFIER
    assert len(backend.register_calls) == (2 if failure in ("refused", "exception", "unregister") else 1)
    assert backend.unregister_calls == int(swapped)
    backend.fail_clear = False
    assert capture_key.clear() is None
    assert_tracks_backend(capture_key)
    capture_key.deleteLater()


@pytest.mark.parametrize("fail_clear", [False, True])
def test_clear_tracks_release_result(qapp, backend, fail_clear):
    capture_key = hotkey.GlobalHotkey(backend=backend)
    assert capture_key.set_sequence(QKeySequence(hotkey.DEFAULT)) is None
    assert capture_key.registered
    assert assert_tracks_backend(capture_key) == QKeySequence(hotkey.DEFAULT)
    assert backend.unregister_calls == 0
    backend.fail_clear = fail_clear
    problem = capture_key.clear()
    assert problem == (hotkey.RELEASE.format(key=key_words(QKeySequence(hotkey.DEFAULT)))
                       if fail_clear else None)
    assert capture_key.registered == fail_clear
    assert_tracks_backend(capture_key)
    assert backend.unregister_calls == 1
    backend.fail_clear = False
    assert capture_key.clear() is None
    assert_tracks_backend(capture_key)
    assert backend.unregister_calls == (2 if fail_clear else 1)
    capture_key.deleteLater()


@pytest.mark.parametrize("path", ["window", "page"])
@pytest.mark.parametrize("first_refused", [False, True])
def test_reset_all_uses_one_result(make_window, backend, monkeypatch, path, first_refused):
    window = start_with_clash(make_window, backend)
    page = SettingsDialog(window) if path == "page" else None
    if page:
        assert page.commit_hotkey()
    apply_calls = []
    apply = window.apply_hotkey

    def counted_apply():
        apply_calls.append(True)
        return apply()

    monkeypatch.setattr(window, "apply_hotkey", counted_apply)
    backend.refusals = [first_refused, not first_refused]
    expected = (hotkey.TAKEN.format(
        key=QKeySequence(hotkey.DEFAULT).toString(QKeySequence.NativeText))
        if first_refused else None)
    if page:
        page._reset_all()
        assert page.message.text() == (expected or "")
        assert page.hotkey_edit.keySequence() == QKeySequence(hotkey.DEFAULT)
        page.deleteLater()
    else:
        assert window.reset_all_shortcuts() == expected
    assert backend.register_calls == [QKeySequence(hotkey.DEFAULT)]
    assert len(apply_calls) == 1
    assert backend.refusals == [not first_refused]
    assert window.hotkey.registered == (not first_refused)
    assert_tracks_backend(window.hotkey)
    assert window.statusBar().currentMessage() == (
        f"{HOTKEY_NAME}: {expected}" if expected else "")


@pytest.mark.parametrize("path", ["window", "page"])
@pytest.mark.parametrize("custom_refused", [False, True])
@pytest.mark.parametrize("custom", [False, True])
def test_reset_all_with_default_buttons(make_window, backend, path, custom_refused, custom):
    window = make_window(copy=None)
    seq = QKeySequence("Ctrl+Alt+Y" if custom else hotkey.DEFAULT)
    if custom:
        window.settings.setValue("hotkey/sequence", seq.toString(QKeySequence.PortableText))
    backend.refuse = custom_refused
    assert bool(window.apply_hotkey()) == custom_refused
    assert_tracks_backend(window.hotkey)
    assert window.hotkey.registered == (not custom_refused)
    if not custom_refused:
        window.statusBar().showMessage(f"{HOTKEY_NAME}: stale problem")
    assert all(window.shortcut_actions[key].shortcuts() == list(default)
               for key, default in window.default_shortcuts.items())
    page = SettingsDialog(window) if path == "page" else None
    if page:
        page.say(window.statusBar().currentMessage())
    backend.refuse = False
    calls = len(backend.register_calls)
    releases = backend.unregister_calls
    if page:
        page._reset_all()
        assert page.message.text() == ""
        assert page.hotkey_edit.keySequence() == QKeySequence(hotkey.DEFAULT)
        page.deleteLater()
    else:
        assert window.reset_all_shortcuts() is None
    assert backend.register_calls[calls:] == ([QKeySequence(hotkey.DEFAULT)] if custom or custom_refused else [])
    assert backend.unregister_calls == releases + int(custom and not custom_refused)
    assert assert_tracks_backend(window.hotkey) == QKeySequence(hotkey.DEFAULT)
    assert not window.settings.contains("hotkey/sequence")
    assert window.statusBar().currentMessage() == ""


def test_window_returns_release_failure(make_window, backend):
    window = make_window(copy=None)
    custom = QKeySequence("Alt+Y")
    assert window.set_hotkey(custom, False) is None
    backend.fail_clear = True
    problem = hotkey.RELEASE.format(key=key_words(custom))
    assert window.reset_all_shortcuts() == problem
    assert window.statusBar().currentMessage() == f"{HOTKEY_NAME}: {problem}"
    assert assert_tracks_backend(window.hotkey) == QKeySequence(hotkey.DEFAULT)
    assert len(backend.register_calls) == 2
    assert window.hotkey._retained[0][1] == custom
    backend.fail_clear = False


@pytest.mark.parametrize("platform,status", [("mac", -50), ("mac", -1),
                                           ("windows", 0)])
def test_native_release_failure_keeps_handle_and_retries(qapp, platform, status):
    # No native library is loaded and no real key is registered.
    backend_type = hotkey.MacBackend if platform == "mac" else hotkey.WinBackend
    native = backend_type.__new__(backend_type)
    calls = []
    results = [status, 0 if platform == "mac" else 1]

    def release(*args):
        calls.append(args)
        return results.pop(0)

    if platform == "mac":
        native._key_ref = ctypes.c_void_p(123)
        native._carbon = SimpleNamespace(UnregisterEventHotKey=release)
        reason = f"UnregisterEventHotKey failed ({status})"
    else:
        native._on = True
        native._user32 = SimpleNamespace(UnregisterHotKey=release)
        reason = "UnregisterHotKey failed (returned zero)"
    capture_key = hotkey.GlobalHotkey(backend=backend_type)
    capture_key._backend = native
    capture_key._registered = True  # stands in for a previously registered key
    capture_key.sequence = QKeySequence(hotkey.DEFAULT)
    assert capture_key.clear() == hotkey.RELEASE.format(key=key_words(QKeySequence(hotkey.DEFAULT)))
    assert capture_key.registered
    if platform == "mac":
        assert native._key_ref.value == 123
    else:
        assert native._on
    assert len(calls) == 1
    assert capture_key.clear() is None
    assert not capture_key.registered
    assert len(calls) == 2
    assert calls[0] == calls[1]
    if platform == "mac":
        assert not native._key_ref
    else:
        assert not native._on
    assert capture_key.clear() is None
    assert len(calls) == 2
    capture_key.deleteLater()


@pytest.mark.parametrize("path", ["window", "page"])
@pytest.mark.parametrize("release_fails_again", [False, True])
def test_reset_all_off_retries_held_key(make_window, backend, path, release_fails_again):
    window = make_window(copy=None)
    assert window.apply_hotkey() is None
    page = SettingsDialog(window)
    backend.fail_clear = True
    page.hotkey_off.setChecked(True)
    problem = hotkey.RELEASE.format(key=key_words(QKeySequence(hotkey.DEFAULT)))
    assert page.message.text() == problem
    assert window.statusBar().currentMessage() == f"{HOTKEY_NAME}: {problem}"
    assert window.hotkey_off() and window.hotkey.registered
    assert_tracks_backend(window.hotkey)
    releases = backend.unregister_calls
    backend.fail_clear = release_fails_again
    if path == "page":
        page._reset_all()
        assert page.message.text() == (problem if release_fails_again else "")
    else:
        assert window.reset_all_shortcuts() == (problem if release_fails_again else None)
    assert backend.unregister_calls == releases + 1
    assert backend.register_calls == [QKeySequence(hotkey.DEFAULT)]
    assert window.hotkey_off()
    assert window.hotkey.registered == release_fails_again
    assert_tracks_backend(window.hotkey)
    assert window.statusBar().currentMessage() == (
        f"{HOTKEY_NAME}: {problem}" if release_fails_again else "")
    backend.fail_clear = False
    page.deleteLater()


@pytest.mark.parametrize("path", ["commit", "reset"])
@pytest.mark.parametrize("stale_capture_error", [False, True])
def test_capture_row_success_clears_only_capture_status(make_window, backend, path,
                                                       stale_capture_error):
    window = make_window(copy=None)
    backend.refuse = True
    page = SettingsDialog(window)
    page.show()
    page.activateWindow()
    page.hotkey_edit.setFocus()
    QTest.keyPress(page.hotkey_edit, Qt.Key_Control)
    QTest.keyPress(page.hotkey_edit, Qt.Key_Alt)
    QTest.keyPress(page.hotkey_edit, Qt.Key_Y, Qt.ControlModifier | Qt.AltModifier)
    assert page.message.text()
    QTest.keyRelease(page.hotkey_edit, Qt.Key_Y, Qt.ControlModifier | Qt.AltModifier)
    QTest.keyRelease(page.hotkey_edit, Qt.Key_Alt)
    QTest.keyRelease(page.hotkey_edit, Qt.Key_Control)
    if not stale_capture_error:
        window.statusBar().showMessage("Unrelated status")
    backend.refuse = False
    if path == "commit":
        # A retry is deliberate input, never a passive editingFinished.
        page.show()
        page.activateWindow()
        page.hotkey_edit.setFocus()
        QTest.keyClick(page.hotkey_edit, Qt.Key_Y, Qt.ControlModifier | Qt.AltModifier)
        QTest.qWait(1100)
    else:
        QTest.mouseClick(page.hotkey_reset, Qt.LeftButton)
    assert page.message.text() == ""
    assert window.statusBar().currentMessage() == (
        "" if stale_capture_error else "Unrelated status")
    assert window.hotkey.registered
    assert_tracks_backend(window.hotkey)
    page.deleteLater()


@pytest.mark.parametrize("path", ["window", "page"])
@pytest.mark.parametrize("result", ["success", "refused", "release_failure"])
def test_reset_all_refreshes_tray_capture_text(make_window, backend, path, result,
                                              tray_for):
    window = make_window(copy=None)
    tray = tray_for(window)
    try:
        custom = QKeySequence("Ctrl+Alt+Y")
        assert window.set_hotkey(custom, False) is None
        before = tray.capture_action.text()
        assert before == f"Capture ({window.capture_key_text()})"
        backend.refuse = result == "refused"
        backend.fail_clear = result == "release_failure"
        expected = (hotkey.RELEASE.format(key=key_words(custom))
                    if backend.fail_clear else
                    hotkey.STILL_USING.format(new=key_words(QKeySequence(hotkey.DEFAULT)),
                                             old=key_words(custom)) if backend.refuse else None)
        calls = len(backend.register_calls)
        refreshes = []
        refresh = tray.refresh

        def counted_refresh():
            refresh()
            refreshes.append(tray.capture_action.text())

        tray.refresh = counted_refresh
        page = SettingsDialog(window) if path == "page" else None
        if page:
            page._reset_all()
            assert page.message.text() == (expected or "")
            assert page.hotkey_edit.keySequence() == (custom if backend.refuse else QKeySequence(hotkey.DEFAULT))
            page.deleteLater()
        else:
            assert window.reset_all_shortcuts() == expected
        assert window.hotkey_sequence() == (custom if backend.refuse else QKeySequence(hotkey.DEFAULT))
        held = assert_tracks_backend(window.hotkey)
        assert held == (custom if backend.refuse else QKeySequence(hotkey.DEFAULT))
        assert bool(window.hotkey._retained) == backend.fail_clear
        assert len(backend.register_calls) - calls == 1
        text = f"Capture ({window.capture_key_text()})"
        assert tray.capture_action.text() == text
        assert refreshes == [text]
        # A later refresh keeps the confirmed new key after a failed old release.
        tray.refresh()
        assert tray.capture_action.text() == text
        assert (tray.capture_action.text() == before) == backend.refuse
    finally:
        backend.fail_clear = False


@pytest.mark.parametrize("result", ["success", "refused", "release_failure", "off"])
def test_capture_row_refreshes_tray_after_result(make_window, backend, tray_for, result):
    window = make_window(copy=None)
    tray = tray_for(window)
    assert tray.capture_action.text() == "Capture"
    assert window.apply_hotkey() is None
    assert tray.capture_action.text() == f"Capture ({window.capture_key_text()})"
    backend.refuse = result == "refused"
    backend.fail_clear = result == "release_failure"
    try:
        problem = window.set_hotkey(QKeySequence("Ctrl+Alt+Y"), result == "off")
        assert bool(problem) == (result in ("refused", "release_failure"))
        expected = (f"Capture ({window.capture_key_text()})"
                    if result != "off" else "Capture")
        assert tray.capture_action.text() == expected
    finally:
        backend.fail_clear = False


def test_mac_keypad_capture_refused_before_registration(qapp, backend, monkeypatch):
    monkeypatch.setattr(hotkey.sys, "platform", "darwin")
    seq = QKeySequence(QKeyCombination(Qt.AltModifier | Qt.KeypadModifier, Qt.Key_1))
    capture_key = hotkey.GlobalHotkey(backend=backend)
    assert capture_key.set_sequence(seq) == hotkey.MAC_KEYPAD
    assert backend.register_calls == []
    assert not capture_key.registered
    top_row = QKeySequence(QKeyCombination(Qt.AltModifier, Qt.Key_1))
    assert capture_key.set_sequence(top_row) is None
    assert backend.register_calls == [top_row]
    assert capture_key.clear() is None
    capture_key.deleteLater()


def test_mac_backend_rejects_keypad_before_native_registration():
    native = hotkey.MacBackend.__new__(hotkey.MacBackend)
    calls = []
    native.register_code = lambda *args: calls.append(args) or 0
    keypad = QKeySequence(QKeyCombination(Qt.AltModifier | Qt.KeypadModifier, Qt.Key_1))
    assert hotkey.mac_combo(keypad) is None
    assert native.register(keypad) == hotkey.MAC_KEYPAD
    assert calls == []
    assert native.register(QKeySequence("Alt+1")) is None
    assert calls == [(18, hotkey.OPTION_KEY)]


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_other_platform_keypad_validation_unchanged(monkeypatch, platform):
    monkeypatch.setattr(hotkey.sys, "platform", platform)
    seq = QKeySequence(QKeyCombination(Qt.AltModifier | Qt.KeypadModifier, Qt.Key_1))
    assert hotkey.check(seq) == (hotkey.WIN_KEYPAD if platform == "win32" else None)


def test_mac_button_shortcut_still_accepts_keypad(make_window, monkeypatch):
    monkeypatch.setattr(hotkey.sys, "platform", "darwin")
    window = make_window(copy=None)
    seq = QKeySequence(QKeyCombination(Qt.AltModifier | Qt.KeypadModifier, Qt.Key_1))
    assert window.set_shortcut("copy", seq) is None
    assert window.a_copy.shortcut() == seq
