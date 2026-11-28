from key_field_support import FocusOutWitness
"""s30 rows 01–21: isolated Qt offscreen, fake handles and deterministic time.

Only pytest's existing offscreen fixture selects a Qt platform. Native
backend constructors use stubbed OS libraries. No browser, physical key
or real tray is used here.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QKeyCombination, QObject, QSettings, Qt, Signal
from PySide6.QtGui import QIcon, QKeySequence
from PySide6.QtTest import QTest

from annotshot import help as help_module, hotkey, mainwindow, settings_dialog, tray, welcome, theme
from annotshot.app import make_app
from annotshot.keywords import key_words

Y = "Alt+Y"


class Clock:
    def __init__(self):
        self.now = 0
        self.queue = []

    def call_later(self, ms, callback):
        item = (self.now + ms, callback)
        self.queue.append(item)
        return lambda: self.queue.remove(item) if item in self.queue else None

    def advance(self, ms):
        until = self.now + ms
        while any(t <= until for t, _ in self.queue):
            t, callback = min(self.queue, key=lambda item: item[0])
            self.queue.remove((t, callback))
            self.now = t
            callback()
        self.now = until


class Icon(QObject):
    activated = Signal(object)
    Trigger = 3
    DoubleClick = 2
    @staticmethod
    def isSystemTrayAvailable():
        return True
    def __init__(self, icon, parent):
        super().__init__(parent)
        self.messages = []
    def setToolTip(self, text):
        pass
    def setContextMenu(self, menu):
        self.menu = menu
    def show(self):
        pass
    def hide(self):
        pass
    def showMessage(self, title, text):
        self.messages.append((title, text))


@pytest.fixture(params=["darwin", "win32"], ids=["Mac", "Windows"])
def rig(request, monkeypatch, qapp, private_settings):
    platform = request.param
    make_app()
    monkeypatch.setattr(hotkey.sys, "platform", platform)
    monkeypatch.setattr(hotkey, "DEFAULT", hotkey.default_for_platform(platform))
    # Independent literals: Qt PortableText storage and the words on screen.
    default_sequence, default_words, default_mods = {
        "darwin": ("Meta+Ctrl+Space", "Control+Command+Space", Qt.MetaModifier | Qt.ControlModifier),
        "win32": ("Ctrl+Alt+Space", "Ctrl+Alt+Space", Qt.ControlModifier | Qt.AltModifier),
    }[platform]
    words = lambda seq: key_words(seq, platform)
    for module in (hotkey, mainwindow, settings_dialog, tray, welcome, help_module):
        if hasattr(module, "key_words"):
            monkeypatch.setattr(module, "key_words", words)
    field_module = hotkey.sys.modules.get("annotshot.shortcut_field")
    if field_module is not None:
        monkeypatch.setattr(field_module, "key_words", words)
    monkeypatch.setattr(tray, "QSystemTrayIcon", Icon)
    class Backend:
        available = True
        calls = []
        held = {}
        refused = set()
        fail_release = set()
        next_id = 0
        deliveries = []
        def __init__(self, fire):
            self.fire = fire
            self.identity = Backend.next_id
            Backend.next_id += 1
            self.seq = None
        def register(self, seq):
            text = seq.toString(QKeySequence.PortableText)
            Backend.calls.append(("register", text))
            if text in Backend.refused:
                return hotkey.TAKEN.format(key=words(seq))
            self.seq = QKeySequence(seq)
            Backend.held[self.identity] = text
        def unregister(self):
            Backend.calls.append(("release", self.seq.toString(QKeySequence.PortableText), self.identity))
            if self.identity in Backend.fail_release:
                raise RuntimeError("stub release failure")
            Backend.held.pop(self.identity, None)
        def queue_press(self):
            return hotkey.native_callback(self.fire, True, False)
        def press(self, pressed=True, repeat=False):
            Backend.deliveries.append((self.identity, pressed, repeat))
            self.fire(pressed, repeat)
    monkeypatch.setattr(hotkey, "backend_class", lambda: Backend)
    windows = []
    def create(saved=None, off=False, refused=(), local=None, *, settings_page=True,
               help_window=True, relaunch=False):
        settings = QSettings(private_settings, QSettings.IniFormat)
        if not relaunch:
            settings.clear()
        if saved is not None:
            settings.setValue("hotkey/sequence", saved)
        if off:
            settings.setValue("hotkey/off", True)
        if local:
            settings.setValue("shortcuts/copy", local)
        settings.sync()
        Backend.refused = set(refused)
        w = mainwindow.MainWindow()
        w.key_clock = Clock()
        page = settings_dialog.SettingsDialog(w) if settings_page else None
        if help_window:
            w._help_window = help_module.HelpWindow(w.shortcut_rows(), w)
        if platform == "win32":
            w.tray = tray.TrayController(w, QIcon())
        windows.append(w)
        w._s30_page = page
        return w
    result = SimpleNamespace(create=create, backend=Backend, platform=platform,
                             qapp=qapp, words=words, monkeypatch=monkeypatch,
                             default_sequence=default_sequence, default_mods=default_mods, d=default_words,
                             y="Option+Y" if platform == "darwin" else "Alt+Y")
    yield result
    Backend.fail_release.clear()
    for w in windows:
        w.end_key_try()
        w.hotkey.clear()
        w.hide()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()


def saved(w):
    w.settings.sync()
    return {k: w.settings.value(k) for k in w.settings.allKeys()}


def ready(rig, seq=None):
    w = rig.create(seq)
    assert w.apply_hotkey() is None
    w.statusBar().clearMessage()
    return w


def surfaces(rig, w, *, key=None, line=None, field=None, off=False, message="", face="plain", status="", trying=False):
    """Compare all seven surfaces to row literals, including the real notice formatter."""
    key = rig.d if key is None else key
    field = key if field is None else field
    line = f"Capture from anywhere with {key}" if line is None else line
    page = w._s30_page
    button = w.welcome.capture_bar.key_button
    assert button.text() == ("Key off" if off and not w.hotkey.registered else
                             "Choose another key" if face == "amber" else key)
    assert button.face == face
    assert button.toolTip() == "Capture key"
    assert button.accessibleName() == f"Capture key: {button.text()}"
    assert button.accessibleDescription() == line
    assert w.welcome.key_row.text() == line
    assert rig.words(page.hotkey_edit.keySequence()) == field
    assert page.hotkey_off.isChecked() == off
    assert page.message.text() == message
    live = "" if off or face == "amber" or trying else key
    # Existing Help is refreshed without being reopened.
    help_key = help_module.keys_text(w.shortcut_rows()[-1][1])
    assert help_key == (live or "no key")
    assert f"{live or 'no key'}\nCapture from anywhere" in w._help_window.browser.toPlainText()
    assert w.statusBar().currentMessage() == status
    assert w.welcome.status_label.text() == ("" if status == line else status)
    if rig.platform == "win32":
        w.tray.refresh()
        assert [a.text() for a in w.tray.menu.actions()] == [
            f"Capture ({live})" if live else "Capture", "Open Annotshot", "Quit Annotshot"]
        before = saved(w)
        w.settings.remove("app/keep_running_told")
        w.tray.icon.messages.clear()
        tray.TrayController.notify_hidden(w.tray)
        tray.TrayController.notify_hidden(w.tray)
        notice_key = "" if off or face == "amber" or key == "Capture key" else key
        assert w.tray.icon.messages == [("Annotshot is still running",
            f"{notice_key} captures. Quit from this icon." if notice_key else "Quit from this icon.")]
        w.settings.remove("app/keep_running_told")
        if "app/keep_running_told" in before:
            w.settings.setValue("app/keep_running_told", before["app/keep_running_told"])
    else:
        assert w.tray is None
    expected_menu = ["Turn on"] if off and not w.hotkey.registered else ["Retry turn off"] if off else ["Try this key", "Change key", "Turn off"]
    assert [a.text() for a in w.welcome.capture_bar.key_menu.actions()] == expected_menu


def error(reason):
    return f"Capture from anywhere: {reason}"


def start_try(w):
    w.try_capture_key()
    w.key_clock.advance(1000)
    assert w.isMinimized() and w._key_try["phase"] == "armed"


def test_row_01_launch(rig):
    w = rig.create()
    surfaces(rig, w, key="Capture key", line="Setting up the capture key…", field=rig.d,
             status=w.capture_status(), trying=True)
    assert not w.hotkey.registered
    assert w.apply_hotkey() is None
    assert rig.backend.calls == [("register", rig.default_sequence)]
    assert not w.settings.contains("hotkey/sequence")
    surfaces(rig, w, status=w.capture_status())


@pytest.mark.parametrize("choice", ["missing", "old_shift_first", "old_alt_first", "other", "new_default"])
@pytest.mark.parametrize("off", [False, True])
def test_s50_preferences_survive_launch_and_relaunch(rig, choice, off):
    raw, held, words = {
        "missing": (None, rig.default_sequence, rig.d),
        "old_shift_first": ("Shift+Alt+Space", "Alt+Shift+Space",
                            "Option+Shift+Space" if rig.platform == "darwin" else "Alt+Shift+Space"),
        "old_alt_first": ("Alt+Shift+Space", "Alt+Shift+Space",
                          "Option+Shift+Space" if rig.platform == "darwin" else "Alt+Shift+Space"),
        "other": ("Alt+Y", "Alt+Y", rig.y),
        "new_default": (rig.default_sequence, rig.default_sequence, rig.d),
    }[choice]
    w = rig.create(raw, off=off)
    # Include the owner's explicit Off=false spelling, not only its absence.
    w.settings.setValue("hotkey/off", off)
    w.settings.setValue("unrelated/preference", "keep")
    before = saved(w)
    for launch in range(2):
        calls = list(rig.backend.calls)
        assert w.apply_hotkey() is None
        assert w.hotkey_sequence() == QKeySequence(held)
        assert w.hotkey.registered == (not off)
        if not off:
            assert w.hotkey.sequence.toString(QKeySequence.PortableText) == held
        assert rig.backend.calls == calls + ([] if off else [("register", held)])
        assert saved(w) == before
        assert w.settings.contains("hotkey/sequence") == (raw is not None)
        assert w.settings.value("hotkey/sequence") == raw
        assert w.hotkey_off() == off
        surfaces(rig, w, key=words, off=off,
                 line="Capture key is off." if off else None, status=w.capture_status())
        if launch == 0:
            assert w.hotkey.clear() is None
            w = rig.create(relaunch=True)


@pytest.mark.parametrize("refused", [False, True])
def test_s50_owner_reset_adopts_or_keeps_the_working_key(rig, refused):
    old = "Alt+Shift+Space"
    old_words = "Option+Shift+Space" if rig.platform == "darwin" else old
    w = ready(rig, old)
    w.settings.setValue("hotkey/off", False)
    w.settings.setValue("unrelated/preference", "keep")
    before = saved(w)
    identity = w.hotkey._backend.identity
    rig.backend.calls.clear()
    if refused:
        rig.backend.refused.add(rig.default_sequence)
    w._s30_page.hotkey_reset.click()
    assert rig.backend.calls == [("register", rig.default_sequence)] + (
        [] if refused else [("release", old, identity)])
    if refused:
        reason = f"{rig.d} is taken by the system or another app. Still using {old_words}."
        assert saved(w) == before
        surfaces(rig, w, key=old_words, line=reason, message=reason, status=error(reason))
        captures = []
        rig.monkeypatch.setattr(w, "capture", lambda: captures.append(1))
        w.hotkey._backend.press()
        assert captures == [1]
    else:
        assert saved(w) == {key: value for key, value in before.items() if key != "hotkey/sequence"}
        surfaces(rig, w)
    w.hotkey.clear()
    w = rig.create(relaunch=True)
    assert w.apply_hotkey() is None
    assert w.hotkey_sequence() == QKeySequence(old if refused else rig.default_sequence)
    assert w.settings.contains("hotkey/sequence") == refused
    surfaces(rig, w, key=old_words if refused else rig.d, status=w.capture_status())


@pytest.mark.parametrize("reset_all", [False, True])
def test_s50_reset_while_off_then_turn_on(rig, reset_all):
    w = rig.create("Alt+Shift+Space", off=True)
    assert w.apply_hotkey() is None
    if reset_all:
        w._s30_page._reset_all()
    else:
        w._s30_page.hotkey_reset.click()
    assert not rig.backend.calls and w.hotkey_off()
    assert not w.settings.contains("hotkey/sequence")
    surfaces(rig, w, field=rig.d, off=True, line="Capture key is off.", status=w.capture_status())
    w.welcome.capture_bar.key_menu.actions()[0].trigger()
    assert rig.backend.calls == [("register", rig.default_sequence)]
    assert not w.hotkey_off()
    surfaces(rig, w, status=w.capture_status())


def test_s50_reset_already_held_saved_default_needs_no_registration(rig):
    w = ready(rig, rig.default_sequence)
    calls = list(rig.backend.calls)
    w._s30_page.hotkey_reset.click()
    assert rig.backend.calls == calls
    assert not w.settings.contains("hotkey/sequence")
    surfaces(rig, w)


def test_s50_settings_replacement_while_off_enables_in_one_gesture(rig):
    w = rig.create("Alt+Shift+Space", off=True)
    assert w.apply_hotkey() is None
    type_capture_chord(rig, w._s30_page, Qt.Key_Y, Qt.AltModifier)
    assert rig.backend.calls == [("register", Y)]
    assert not w.hotkey_off() and w.settings.value("hotkey/sequence") == Y
    surfaces(rig, w, key=rig.y, status=w.capture_status())


@pytest.mark.parametrize("recovery", ["retry", "choice"])
def test_s50_empty_profile_refusal_leaves_capture_and_recovery(rig, recovery):
    w = rig.create(refused=[rig.default_sequence])
    assert w.apply_hotkey()
    assert not w.hotkey.registered and not w.settings.contains("hotkey/sequence")
    assert w.hotkey_sequence() == QKeySequence(rig.default_sequence)
    captures = []
    rig.monkeypatch.setattr(w, "_may_record_screen", lambda: captures.append(1) or False)
    w.welcome.capture_bar.capture_button.click()
    assert captures == [1]
    rig.backend.refused.clear()
    if recovery == "retry":
        assert w.apply_hotkey() is None
        assert not w.settings.contains("hotkey/sequence")
        expected = rig.d
    else:
        w._s30_page.hotkey_edit.setKeySequence(QKeySequence(Y))
        assert w._s30_page.commit_hotkey() is None
        assert w.settings.value("hotkey/sequence") == Y
        expected = rig.y
    surfaces(rig, w, key=expected)


def test_row_02_refused_launch(rig):
    w = rig.create(refused=[rig.default_sequence])
    reason = f"{rig.d} is taken by the system or another app; pick another key"
    assert w.apply_hotkey() == reason
    surfaces(rig, w, face="amber", line=f"{rig.d} is unavailable.", message=reason, status=error(reason))
    QTest.qWait(11000)  # include Qt coarse-timer tolerance; no manual clear
    w.welcome.refresh()
    w._help_window.close()
    w._help_window = help_module.HelpWindow(w.shortcut_rows(), w)
    surfaces(rig, w, face="amber", line=f"{rig.d} is unavailable.", message=reason)
    assert rig.backend.held == {}


def test_row_03_try_minimizes_and_checks_failure(rig):
    w = ready(rig)
    before = saved(w)
    calls = list(rig.backend.calls)
    captures = []
    rig.monkeypatch.setattr(w, "capture", lambda: captures.append(1))
    w.try_capture_key()
    surfaces(rig, w, line=f"Press {rig.d} now.", trying=True)
    w.hotkey._backend.press()
    w.hotkey._backend.press(False)
    w.hotkey.deliver(QKeySequence(Y))
    assert captures == [] and not w.isMinimized()
    w.key_clock.advance(999)
    assert not w.isMinimized()
    w.key_clock.advance(1)
    assert w.isMinimized() and w._key_try["phase"] == "armed"
    assert rig.backend.calls == calls and saved(w) == before
    w.end_key_try()
    w.showNormal()
    rig.monkeypatch.setattr(w, "showMinimized", lambda: None)
    w.try_capture_key()
    w.key_clock.advance(3000)
    assert w._key_try is None
    surfaces(rig, w, line="Annotshot could not minimize for the try.", status="Annotshot could not minimize for the try.")


def test_row_04_receipt_consumes_press_and_repeat(rig):
    w = ready(rig)
    captures = []
    rig.monkeypatch.setattr(w, "capture", lambda: captures.append(1))
    start_try(w)
    backend = w.hotkey._backend
    backend.press()
    backend.press(repeat=True)
    assert captures == [] and not w.isMinimized()
    surfaces(rig, w, face="green", line="Annotshot received your key", status="Annotshot received your key")
    rig.qapp.processEvents()
    assert w.isActiveWindow()
    assert w.welcome.capture_bar.key_button.hasFocus()
    backend.press(False)
    backend.press()
    assert captures == [1]


def test_row_05_timeout_restores_and_stale_callback(rig):
    w = ready(rig)
    start_try(w)
    epoch = w._key_try["epoch"]
    w.key_clock.advance(9999)
    assert w.isMinimized()
    w.key_clock.advance(1)
    assert not w.isMinimized()
    surfaces(rig, w, line="No press received", status="No press received")
    start_try(w)
    w.hotkey._backend.press()
    w._key_try_timeout(epoch)
    surfaces(rig, w, face="green", line="Annotshot received your key", status="Annotshot received your key")


@pytest.mark.parametrize("entry", ["reopen", "window_state"])
def test_row_06_manual_restore_cancels_once(rig, entry):
    w = ready(rig)
    start_try(w)
    old_epoch = w._key_epoch
    if entry == "reopen":
        w.reopen()
        w.reopen()
    else:
        w.showNormal()
    w.key_clock.advance(20000)
    assert not w.isMinimized() and w.isVisible()
    surfaces(rig, w, status="Try cancelled")
    captures = []
    rig.monkeypatch.setattr(w, "capture", lambda: captures.append(1))
    w._native_capture_key((QKeySequence(rig.default_sequence), True, False, old_epoch))
    assert captures == []
    w.hotkey._backend.press()
    assert captures == [1]


@pytest.mark.parametrize("accepted", [False, True])
def test_row_07_retry(rig, accepted):
    w = rig.create(refused=[rig.default_sequence])
    w.apply_hotkey()
    rig.backend.calls.clear()
    if accepted:
        rig.backend.refused.clear()
    w.try_capture_key()
    assert rig.backend.calls == [("register", rig.default_sequence)]
    if accepted:
        surfaces(rig, w, line=f"Press {rig.d} now.", trying=True)
        w.key_clock.advance(1000)
        assert w._key_try["phase"] == "armed"
    else:
        reason = f"{rig.d} is taken by the system or another app; pick another key"
        surfaces(rig, w, face="amber", line=f"{rig.d} is unavailable.", message=reason, status=error(reason))
        assert not w.key_clock.queue and w._key_try is None


@pytest.mark.parametrize("entry", ["recorder", "settings"])
def test_row_08_first_chord_swaps(rig, entry):
    w = ready(rig)
    before = saved(w)
    w.welcome.start_recording()
    QTest.keyClick(w.welcome.recorder, Qt.Key_Escape)
    assert saved(w) == before and len(rig.backend.calls) == 1
    rig.backend.calls.clear()
    old_id = w.hotkey._backend.identity
    if entry == "recorder":
        w.welcome.start_recording()
        QTest.keyPress(w.welcome.recorder, Qt.Key_Alt)
        assert w.welcome.recorder.draft.text() == ("Option" if rig.platform == "darwin" else "Alt")
        assert not rig.backend.calls
        QTest.keyClick(w.welcome.recorder, Qt.Key_Y, Qt.AltModifier)
        assert not w.welcome.recording
        assert [b.text() for b in w.welcome.recorder.findChildren(welcome.QPushButton)] == ["Cancel"]
    else:
        w._s30_page.hotkey_edit.setKeySequence(QKeySequence(Y))
        assert w._s30_page.commit_hotkey() is None
    assert rig.backend.calls == [("register", Y), ("release", rig.default_sequence, old_id)]
    assert list(rig.backend.held.values()) == [Y]
    assert w.settings.value("hotkey/sequence") == Y
    surfaces(rig, w, key=rig.y)


@pytest.mark.parametrize("entry", ["recorder", "settings"])
def test_row_09_refused_change_keeps_old(rig, entry):
    w = ready(rig)
    w.settings.setValue("unrelated/preference", "unchanged")
    before = saved(w)
    disk_before = Path(w.settings.fileName()).read_bytes()
    rig.backend.refused.add(Y)
    rig.backend.calls.clear()
    if entry == "recorder":
        w.welcome.start_recording()
        QTest.keyClick(w.welcome.recorder, Qt.Key_Y, Qt.AltModifier)
        assert not w.welcome.recording
    else:
        w._s30_page.hotkey_edit.setKeySequence(QKeySequence(Y))
        assert w._s30_page.commit_hotkey()
    reason = f"{rig.y} is taken by the system or another app. Still using {rig.d}."
    assert saved(w) == before and rig.backend.calls == [("register", Y)]
    assert Path(w.settings.fileName()).read_bytes() == disk_before
    assert list(rig.backend.held.values()) == [rig.default_sequence]
    surfaces(rig, w, line=reason, message=reason, status=error(reason))
    w.welcome.refresh()
    reopened = settings_dialog.SettingsDialog(w)
    assert reopened.message.text() == reason
    assert reopened.hotkey_edit.keySequence() == QKeySequence(rig.default_sequence)
    reopened.deleteLater()
    surfaces(rig, w, line=reason, message=reason, status=error(reason))


@pytest.mark.parametrize("entry", ["recorder", "settings", "direct"])
def test_row_10_mac_keypad_preflight(rig, entry):
    if rig.platform != "darwin":
        # This row is Mac-specific; Windows' control case belongs to 11.
        pytest.skip("row 10 applies to Mac; Windows digits are row 11")
    w = ready(rig)
    before = saved(w)
    rig.backend.calls.clear()
    rig.backend.fail_release.add(w.hotkey._backend.identity)
    seq = QKeySequence(QKeyCombination(Qt.AltModifier | Qt.KeypadModifier, Qt.Key_1))
    if entry == "direct":
        assert w.hotkey.set_sequence(seq) == hotkey.MAC_KEYPAD
        w.set_hotkey(seq, False)
    elif entry == "settings":
        w._s30_page.hotkey_edit.setKeySequence(seq)
        assert w._s30_page.commit_hotkey() == hotkey.MAC_KEYPAD
    else:
        w.welcome.start_recording()
        QTest.keyClick(w.welcome.recorder, Qt.Key_1, Qt.AltModifier | Qt.KeypadModifier)
        assert w.welcome.recording and w.welcome.recorder.error.text() == hotkey.MAC_KEYPAD
    for key in [Qt.Key_0, Qt.Key_9, Qt.Key_Enter, Qt.Key_Plus, Qt.Key_F1]:
        keypad = QKeySequence(QKeyCombination(Qt.AltModifier | Qt.KeypadModifier, key))
        assert w.hotkey.set_sequence(keypad) == hotkey.MAC_KEYPAD
        assert hotkey.MacBackend.__new__(hotkey.MacBackend).register(keypad) == hotkey.MAC_KEYPAD
    assert saved(w) == before and not rig.backend.calls
    assert hotkey.mac_combo(seq) is None
    assert hotkey.mac_combo(QKeySequence("Alt+1")) == (18, hotkey.OPTION_KEY)
    surfaces(rig, w, message=hotkey.MAC_KEYPAD, status=error(hotkey.MAC_KEYPAD))
    # The recorder's full local error must fit alongside ordinary Capture.
    w.show()
    rig.qapp.processEvents()
    if entry == "recorder":
        recorder = w.welcome.recorder
        assert recorder.error.height() >= recorder.error.heightForWidth(recorder.error.width())
        assert w.welcome.rect().contains(recorder.mapTo(w.welcome, recorder.rect().bottomRight()))
        assert w.welcome.capture_bar.capture_button.isVisibleTo(w)


@pytest.mark.parametrize("digit", range(10))
def test_row_11_windows_keypad_digits(rig, digit):
    if rig.platform != "win32":
        pytest.skip("row 11 applies to Windows; Mac keypad keys are row 10")
    w = ready(rig)
    before = saved(w)
    seq = QKeySequence(QKeyCombination(Qt.AltModifier | Qt.KeypadModifier, Qt.Key(Qt.Key_0 + digit)))
    rig.backend.calls.clear()
    assert hotkey.win_combo(seq) is None and hotkey.check(seq) == hotkey.WIN_KEYPAD
    assert hotkey.WinBackend.__new__(hotkey.WinBackend).register(seq) == hotkey.WIN_KEYPAD
    assert w.hotkey.set_sequence(seq) == hotkey.WIN_KEYPAD
    w._s30_page.hotkey_edit.setKeySequence(seq)
    assert w._s30_page.commit_hotkey() == hotkey.WIN_KEYPAD
    w.welcome.start_recording()
    QTest.keyClick(w.welcome.recorder, Qt.Key(Qt.Key_0 + digit), Qt.AltModifier | Qt.KeypadModifier)
    assert w.welcome.recording and w.welcome.recorder.error.text() == hotkey.WIN_KEYPAD
    assert saved(w) == before and not rig.backend.calls
    w.show()
    rig.qapp.processEvents()
    recorder = w.welcome.recorder
    assert recorder.error.height() >= recorder.error.heightForWidth(recorder.error.width())
    assert w.welcome.rect().contains(recorder.mapTo(w.welcome, recorder.rect().bottomRight()))
    surfaces(rig, w, message=hotkey.WIN_KEYPAD, status=error(hotkey.WIN_KEYPAD))
    w.welcome.cancel_recording()
    assert hotkey.win_combo(QKeySequence(f"Alt+{digit}")) == (hotkey.MOD_ALT | hotkey.MOD_NOREPEAT, 48 + digit)
    assert w.set_hotkey(QKeySequence(f"Alt+{digit}"), False) is None


@pytest.mark.parametrize("entry", ["button", "settings"])
def test_row_12_off(rig, entry):
    w = ready(rig)
    rig.backend.calls.clear()
    identity = w.hotkey._backend.identity
    if entry == "button":
        w.welcome.capture_bar.key_menu.actions()[2].trigger()
    else:
        w._s30_page.hotkey_off.setChecked(True)
    assert rig.backend.calls == [("release", rig.default_sequence, identity)]
    assert not rig.backend.held and w.hotkey_sequence() == QKeySequence(rig.default_sequence)
    surfaces(rig, w, off=True, line="Capture key is off.")


@pytest.mark.parametrize("refused", [False, True])
def test_row_13_turn_on_remembered_after_launch(rig, refused):
    w = rig.create(Y, off=True, refused=[Y] if refused else [])
    assert w.apply_hotkey() is None and not rig.backend.calls
    surfaces(rig, w, key=rig.y, off=True, line="Capture key is off.", status=w.capture_status())
    w.statusBar().clearMessage()
    w.welcome.capture_bar.key_menu.actions()[0].trigger()
    assert rig.backend.calls == [("register", Y)]
    if refused:
        reason = f"{rig.y} is taken by the system or another app; pick another key"
        surfaces(rig, w, key=rig.y, face="amber", line=f"{rig.y} is unavailable.", message=reason, status=error(reason))
    else:
        surfaces(rig, w, key=rig.y)


@pytest.mark.parametrize("refused", [False, True])
@pytest.mark.parametrize("local_clash", [False, True])
def test_row_14_reset_all_new_first(rig, refused, local_clash):
    w = ready(rig, Y)
    old_id = w.hotkey._backend.identity
    if local_clash:
        assert w.set_shortcut("copy", QKeySequence(rig.default_sequence)) is None
    rig.backend.calls.clear()
    rig.backend.refused = {rig.default_sequence} if refused else set()
    refreshes = []
    w.keyStateChanged.connect(lambda: refreshes.append(1))
    w._s30_page._reset_all()
    assert refreshes == [1]
    assert w.a_copy.shortcut() == QKeySequence("Ctrl+C")
    if refused:
        reason = f"{rig.d} is taken by the system or another app. Still using {rig.y}."
        assert rig.backend.calls == [("register", rig.default_sequence)]
        assert w.settings.value("hotkey/sequence") == Y
        surfaces(rig, w, key=rig.y, line=reason, message=reason, status=error(reason))
    else:
        assert rig.backend.calls == [("register", rig.default_sequence), ("release", Y, old_id)]
        assert not w.settings.contains("hotkey/sequence")
        surfaces(rig, w)


def test_row_15_reset_all_preserves_off(rig):
    w = rig.create(Y, off=True)
    w.apply_hotkey()
    w.statusBar().clearMessage()
    w._s30_page._reset_all()
    assert not rig.backend.calls
    surfaces(rig, w, field=rig.d, off=True, line="Capture key is off.")
    assert not w.settings.contains("hotkey/sequence")


@pytest.mark.parametrize("mode", ["enabled", "refused", "keypad", "off"])
def test_row_16_legacy_settings(rig, mode):
    sequence = "Alt+Num+1" if mode == "keypad" else Y
    w = rig.create(sequence, off=mode == "off", refused=[Y] if mode == "refused" else [], local="Alt+8")
    original = w.settings.value("hotkey/sequence")
    local = w.a_copy.shortcuts()
    assert local == [QKeySequence("Alt+8")]
    w.apply_hotkey()
    w.statusBar().clearMessage()
    assert w.settings.value("hotkey/sequence") == original and w.a_copy.shortcuts() == local
    if mode == "enabled":
        assert rig.backend.calls == [("register", Y)]
        surfaces(rig, w, key=rig.y)
    elif mode == "off":
        assert not rig.backend.calls
        surfaces(rig, w, key=rig.y, off=True, line="Capture key is off.")
    elif mode == "refused":
        reason = f"{rig.y} is taken by the system or another app; pick another key"
        surfaces(rig, w, key=rig.y, face="amber", line=f"{rig.y} is unavailable.", message=reason)
    else:
        reason = hotkey.MAC_KEYPAD if rig.platform == "darwin" else hotkey.WIN_KEYPAD
        assert not rig.backend.calls
        surfaces(rig, w, key=rig.words(QKeySequence(sequence)), face="amber", line=reason, message=reason)


@pytest.mark.parametrize("off", [False, True])
def test_row_17_release_failure(rig, off):
    w = ready(rig, Y)
    old = w.hotkey._backend
    rig.backend.fail_release.add(old.identity)
    rig.backend.calls.clear()
    reason = f"Could not release {rig.y}. Try again."
    if off:
        assert w.set_hotkey(QKeySequence(Y), True) == reason
        surfaces(rig, w, key=rig.y, off=True, face="amber", line=reason, message=reason, status=error(reason))
        assert w.hotkey._backend is old
    else:
        assert w.reset_all_shortcuts() == reason
        assert rig.backend.calls == [("register", rig.default_sequence), ("release", Y, old.identity)]
        assert w.hotkey._retained == [(old, QKeySequence(Y))]
        assert set(rig.backend.held.values()) == {rig.default_sequence, Y}
        surfaces(rig, w, message=reason, status=error(reason))
        captures = []
        rig.monkeypatch.setattr(w, "capture", lambda: captures.append(1))
        old.press()
        assert captures == [1]


@pytest.mark.parametrize("off", [False, True])
def test_row_18_retry_same_handle_no_register(rig, off):
    w = ready(rig, Y)
    old = w.hotkey._backend
    rig.backend.fail_release.add(old.identity)
    if off:
        w.set_hotkey(QKeySequence(Y), True)
    else:
        w.reset_all_shortcuts()
    rig.backend.fail_release.clear()
    rig.backend.calls.clear()
    w.statusBar().showMessage("Saved image")
    assert w.apply_hotkey() is None
    assert rig.backend.calls == [("release", Y, old.identity)]
    surfaces(rig, w, key=rig.y if off else rig.d, off=off,
             line="Capture key is off." if off else None, status="Saved image")


def test_row_19_close_notice_refused_key_and_click(rig):
    w = rig.create(Y, refused=[Y])
    reason = w.apply_hotkey()
    assert reason == f"{rig.y} is taken by the system or another app; pick another key"
    before = list(rig.backend.calls)
    w.show()
    w.close()
    w.show()
    w.close()
    assert rig.backend.calls == before and not w.isVisible()
    if rig.platform == "win32":
        assert w.tray.icon.messages == [("Annotshot is still running", "Quit from this icon.")]
        assert w.settings.value("app/keep_running_told", type=bool)
        captures = []
        rig.monkeypatch.setattr(w, "capture", lambda: captures.append(1))
        w.tray.capture_action.trigger()
        assert captures == [1]
    surfaces(rig, w, key=rig.y, face="amber", line=f"{rig.y} is unavailable.", message=reason, status=error(reason))


def test_row_20_local_owner_preserves_green(rig):
    w = ready(rig)
    start_try(w)
    w.hotkey._backend.press()
    before = saved(w)
    calls = list(rig.backend.calls)
    copy = "Command+C" if rig.platform == "darwin" else "Ctrl+C"
    reason = f"{copy} is already used by Copy image."
    assert w.set_hotkey(QKeySequence("Ctrl+C"), False) == reason
    assert rig.backend.calls == calls and saved(w) == before
    surfaces(rig, w, face="green", line="Annotshot received your key", message=reason, status=error(reason))


def test_row_21_tray_capture_disarms_before_usual_capture(rig):
    w = ready(rig)
    calls = []
    rig.monkeypatch.setattr(w, "_may_record_screen", lambda: calls.append("permission") or False)
    start_try(w)
    if rig.platform == "win32":
        w.tray.capture_action.trigger()
        assert calls == ["permission"] and w._key_try is None
    else:
        w.reopen()
        assert calls == [] and w._key_try is None
        w.statusBar().clearMessage()
    w.key_clock.advance(20000)
    surfaces(rig, w)
    w.welcome.start_recording()
    w.welcome.capture_bar.capture_button.click()
    assert not w.welcome.recording
    assert calls == (["permission", "permission"] if rig.platform == "win32" else ["permission"])


def test_removed_words():
    root = Path(__file__).resolve().parents[1]
    files = list((root / "annotshot").glob("*.py")) + [root / "docs/USER-MANUAL.md"]
    for file in files:
        for removed in ("Use key", "Cancel try", "Minimize Annotshot, then press", "still captures", "Change keys"):
            assert removed not in file.read_text(encoding="utf-8"), (file, removed)


def test_renders_for_caller(rig, tmp_path):
    w = ready(rig)
    out = tmp_path / "renders-s30-key-button"
    out.mkdir(parents=True, exist_ok=True)
    w.show()
    def render(name):
        w.welcome.refresh()
        rig.qapp.processEvents()
        assert w.size().toTuple() == (640, 430)
        button = w.welcome.capture_bar.key_button
        assert button.width() == 166
        assert button.rect().contains(button.label.geometry())
        label = button.label
        assert label.height() >= len(label.text().splitlines()) * label.fontMetrics().height()
        assert all(label.fontMetrics().horizontalAdvance(line) <= label.width()
                   for line in label.text().splitlines())
        if button.text() == rig.d:
            assert label.text().replace("\n", "").removeprefix("✓ ") == rig.d
            assert label.text().startswith("✓ ") == (button.face == "green")
        assert w.welcome.rect().contains(button.mapTo(w.welcome, button.rect().bottomRight()))
        assert w.grab().save(str(out / (name + ".png")))
    if rig.platform == "win32":
        render("plain-windows-words")
        return
    for name in ("Light", "Dark", "Retro"):
        theme.apply(rig.qapp, name)
        render("plain-" + name.lower())
    theme.apply(rig.qapp, "Light")
    start_try(w)
    w.hotkey._backend.press()
    render("green")
    w.hotkey._backend.press(False)
    w.set_hotkey(QKeySequence(rig.default_sequence), True)
    render("off")
    rig.backend.refused.add(rig.default_sequence)
    w.set_hotkey(QKeySequence(rig.default_sequence), False)
    render("amber")
    rig.backend.refused.clear()
    w.apply_hotkey()
    w.welcome.start_recording()
    render("recorder")
    w.welcome.cancel_recording()
    w.try_capture_key()
    render("trying")  # the one-second beat, before minimize
    w.end_key_try()
    rig.backend.refused.add(Y)
    w.set_hotkey(QKeySequence(Y), False)
    render("refused-change")
    rig.backend.refused.clear()
    # Four modifiers and the longest native-supported Mac named key.
    assert w.set_hotkey(QKeySequence("Meta+Alt+Shift+Ctrl+Space"), False) is None
    theme.apply(rig.qapp, "Retro")
    render("longest")
    longest = w.hotkey_sequence().toString(QKeySequence.PortableText)
    w.set_hotkey(w.hotkey_sequence(), True)
    rig.backend.refused.add(longest)
    w.set_hotkey(QKeySequence(longest), False)
    render("amber-longest")


def test_native_adapters_keep_independent_handles(qapp, monkeypatch):
    import ctypes
    class Function:
        def __init__(self, callback):
            self.callback = callback
        def __call__(self, *args):
            return self.callback(*args)
    for platform in ("win32", "darwin"):
        default_sequence = "Ctrl+Alt+Space" if platform == "win32" else "Meta+Ctrl+Space"
        calls, delivered = [], []
        if platform == "win32":
            user = SimpleNamespace(GetTickCount=Function(lambda: 100),
                RegisterHotKey=Function(lambda hwnd, identity, *args: calls.append(("register", identity)) or 1),
                UnregisterHotKey=Function(lambda hwnd, identity: calls.append(("release", identity)) or 1))
            monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: user, raising=False)
            first, second = hotkey.WinBackend(lambda: delivered.append(1)), hotkey.WinBackend(lambda: delivered.append(2))
            assert first.register(QKeySequence(default_sequence)) is None
            assert second.register(QKeySequence(Y)) is None
            assert first._id != second._id
            message = hotkey.MSG()
            message.message, message.wParam = hotkey.WM_HOTKEY, second._id
            assert first._filter.nativeEventFilter(b"windows_dispatcher_MSG", ctypes.addressof(message)) == (False, 0)
            assert second._filter.nativeEventFilter(b"windows_dispatcher_MSG", ctypes.addressof(message)) == (True, 0)
            assert delivered == [2]
            first.unregister()
            second.unregister()
        else:
            count = [0]
            def install(target, handler, n, types, data, out):
                ctypes.cast(out, ctypes.POINTER(ctypes.c_void_p))[0] = 77
                return 0
            def register(code, mods, identity, target, flags, out):
                count[0] += 1
                ctypes.cast(out, ctypes.POINTER(ctypes.c_void_p))[0] = count[0]
                calls.append(("register", count[0]))
                return 0
            identity = hotkey.EventHotKeyID(hotkey.fourcc("ANSH"), 0)
            kind = [hotkey.K_EVENT_HOTKEY_PRESSED]
            def parameter(event, name, type_, actual, size, actual_size, out):
                ctypes.memmove(out, ctypes.byref(identity), ctypes.sizeof(identity))
                return 0
            carbon = SimpleNamespace(
                GetApplicationEventTarget=Function(lambda: 1), InstallEventHandler=Function(install),
                RegisterEventHotKey=Function(register),
                UnregisterEventHotKey=Function(lambda ref: calls.append(("release", ref.value)) or 0),
                RemoveEventHandler=Function(lambda ref: 0), GetEventParameter=Function(parameter),
                GetEventKind=Function(lambda event: kind[0]),
                GetEventTime=Function(lambda event: 1.0),
                GetCurrentEventTime=Function(lambda: 1.0))
            monkeypatch.setattr(ctypes, "CDLL", lambda *a, **k: carbon)
            first = hotkey.MacBackend(lambda pressed: delivered.append((1, pressed)))
            second = hotkey.MacBackend(lambda pressed: delivered.append((2, pressed)))
            assert first.register(QKeySequence(default_sequence)) is None
            assert second.register(QKeySequence(Y)) is None
            assert first._id != second._id
            identity.id = second._id
            assert first._on_event(None, None, None) == -9874
            assert second._on_event(None, None, None) == 0
            kind[0] = hotkey.K_EVENT_HOTKEY_RELEASED
            second._on_event(None, None, None)
            assert delivered == [(2, True), (2, False)]
            first.unregister()
            second.unregister()
        assert [call[0] for call in calls] == ["register", "register", "release", "release"]
        assert calls[0][1] != calls[1][1]
        assert calls[0][1] == calls[2][1] and calls[1][1] == calls[3][1]


def test_off_edits_and_keypad_never_write(rig):
    w = rig.create(Y, off=True)
    w.apply_hotkey()
    w.statusBar().clearMessage()
    assert w.set_hotkey(QKeySequence("Alt+8"), True) is None
    assert not rig.backend.calls
    surfaces(rig, w, key="Option+8" if rig.platform == "darwin" else "Alt+8", off=True, line="Capture key is off.")
    before = saved(w)
    seq = QKeySequence(QKeyCombination(Qt.AltModifier | Qt.KeypadModifier, Qt.Key_1))
    reason = hotkey.MAC_KEYPAD if rig.platform == "darwin" else hotkey.WIN_KEYPAD
    assert w.set_hotkey(seq, True) == reason
    assert saved(w) == before and not rig.backend.calls


def test_focused_controls_own_activation_and_escape(rig):
    w = ready(rig)
    calls = []
    rig.monkeypatch.setattr(w, "capture", lambda: calls.append(1))
    w.show()
    button = w.welcome.capture_bar.key_button
    button.setFocus()
    # Inspect shortcut precedence without opening a blocking menu.
    from PySide6.QtGui import QKeyEvent
    for key in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Escape):
        event = QKeyEvent(QEvent.ShortcutOverride, key, Qt.NoModifier)
        assert w.welcome.eventFilter(button, event) and event.isAccepted()
    opened = []
    from PySide6.QtCore import QTimer
    menu = w.welcome.capture_bar.key_menu
    menu.aboutToShow.connect(lambda: (opened.append(True), QTimer.singleShot(0, menu.close)))
    rig.qapp.processEvents()
    QTest.keyClick(button, Qt.Key_Return)
    assert opened == [True] and calls == []
    w.welcome.start_recording()
    QTest.keyClick(w.welcome.recorder, Qt.Key_A)
    assert w.welcome.recording and calls == []
    QTest.keyClick(w.welcome.recorder, Qt.Key_Space)
    assert w.welcome.recording and calls == []
    QTest.keyClick(w.welcome.recorder, Qt.Key_Escape)
    assert not w.welcome.recording and calls == []


def test_help_scroll_survives_apply(rig):
    w = ready(rig)
    reader = w._help_window
    reader.resize(760, 300)
    reader.show()
    rig.qapp.processEvents()
    scroll = reader.browser.verticalScrollBar()
    assert scroll.maximum() > 200
    scroll.setValue(200)
    assert w.set_hotkey(QKeySequence(Y), False) is None
    assert scroll.value() == 200


def test_refused_choice_without_held_key_is_remembered(rig):
    w = rig.create(refused=[Y])
    reason = f"{rig.y} is taken by the system or another app; pick another key"
    assert w.set_hotkey(QKeySequence(Y), False) == reason
    assert rig.backend.calls == [("register", Y)]
    assert not rig.backend.held
    assert w.settings.value("hotkey/sequence") == Y
    surfaces(rig, w, key=rig.y, face="amber", line=f"{rig.y} is unavailable.",
             message=reason, status=error(reason))


@pytest.mark.parametrize("ending", ["timeout", "restore", "tray"])
def test_finding_1_backend_delivery_keeps_receipt_epoch(rig, ending):
    w = ready(rig)
    captures = []
    rig.monkeypatch.setattr(w, "_may_record_screen", lambda: captures.append(1) or False)
    start_try(w)
    # System delivery reaches the backend now; its callback runs only later.
    callback = w.hotkey._backend.queue_press()
    if ending == "timeout":
        w.key_clock.advance(10000)
    elif ending == "restore":
        w.reopen()
    elif rig.platform == "win32":
        w.tray.capture_action.trigger()
    else:
        w.capture_from_anywhere()  # same tray handler, absent on Mac
    baseline = list(captures)
    callback()
    assert captures == baseline
    assert baseline == ([1] if ending == "tray" else [])


@pytest.mark.parametrize("previous", ["recorder", "pending", "armed"])
@pytest.mark.parametrize("action", ["try", "off", "change", "recent", "file", "capture", "close"])
def test_finding_2_next_action_ends_previous(rig, tmp_path, white, previous, action):
    w = ready(rig)
    w.show()
    rig.qapp.processEvents()
    png = tmp_path / "recent.png"
    assert white.save(str(png))
    from annotshot.scene import Document
    editable = tmp_path / "saved.annotshot"
    Document(white).save(editable)
    rig.monkeypatch.setattr(w.recent_store, "files", lambda: [png])
    w.welcome.refresh_recent()
    if previous == "recorder":
        w.welcome.capture_bar.key_menu.actions()[1].trigger()
        QTest.keyPress(w.welcome.recorder, Qt.Key_Alt)
        assert w.welcome.recorder.draft.text()
    else:
        w.welcome.capture_bar.key_menu.actions()[0].trigger()
        if previous == "armed":
            w.key_clock.advance(1000)
    old_epoch = w._key_epoch
    old_callbacks = [callback for _, callback in w.key_clock.queue]
    rig.monkeypatch.setattr(w, "_may_record_screen", lambda: False)
    if action == "try":
        w.welcome.capture_bar.key_menu.actions()[0].trigger()
    elif action == "off":
        w.welcome.capture_bar.key_menu.actions()[2].trigger()
    elif action == "change":
        w.welcome.capture_bar.key_menu.actions()[1].trigger()
    elif action == "recent":
        w.welcome.recent_buttons[0].click()
    elif action == "file":
        rig.monkeypatch.setattr(mainwindow.QFileDialog, "getOpenFileName", lambda *a: (str(editable), ""))
        w.a_open.trigger()
    elif action == "capture":
        w.welcome.capture_bar.capture_button.click()
    else:
        w.close()
    assert w.welcome.recording == (action == "change")
    assert not w.welcome.recorder.draft.text()
    if action == "try":
        assert w._key_try and w._key_epoch != old_epoch
    else:
        assert w._key_try is None and not w.key_clock.queue
    for callback in old_callbacks:
        callback()  # already queued work must be inert even after cancellation
    if action in ("file", "recent"):
        assert w.state_name == "editor"
        assert not w.isMinimized() or previous == "armed"
    if action != "try":
        w.key_clock.advance(20000)
        assert not w.isMinimized() or previous == "armed"
        if action in ("file", "recent"):
            assert w.state_name == "editor"


def test_finding_3_restored_settings_focus_out_is_noop(rig):
    w = ready(rig)
    page = w._s30_page
    page.show()
    page.hotkey_edit.setFocus()
    rig.qapp.processEvents()
    rig.backend.refused.add(Y)
    QTest.keyClick(page.hotkey_edit, Qt.Key_Y, Qt.AltModifier)
    QTest.qWait(1100)
    reason = page.message.text()
    assert "Still using" in reason
    before = saved(w)
    settings_file = Path(w.settings.fileName())
    before_bytes = settings_file.read_bytes() if settings_file.exists() else b""
    calls = []
    apply = w.set_hotkey
    rig.monkeypatch.setattr(w, "set_hotkey", lambda *a: calls.append(a) or apply(*a))
    page.hotkey_off.setFocus()
    rig.qapp.processEvents()
    assert not calls and saved(w) == before
    assert (settings_file.read_bytes() if settings_file.exists() else b"") == before_bytes
    page.hotkey_edit.setFocus()
    QTest.keyRelease(page.hotkey_edit, Qt.Key_Alt)
    rig.qapp.processEvents()
    assert page.message.text() == reason


@pytest.mark.parametrize("entry", ["settings", "recorder"])
@pytest.mark.parametrize("case", ["off_owner", "unsupported", "keypad", "legacy_off"])
def test_finding_4_validate_new_choice_at_both_entries(rig, entry, case):
    if case == "unsupported" and rig.platform != "darwin":
        pytest.skip("Option+Left is the reproduced Mac converter case")
    w = rig.create("Alt+Num+1" if case == "legacy_off" else Y,
                   off=case == "off_owner", refused=[Y] if case == "unsupported" else [])
    w.apply_hotkey()
    page = w._s30_page
    before = saved(w)
    calls = list(rig.backend.calls)
    if case == "legacy_off":
        if entry == "settings":
            page.hotkey_off.setChecked(True)
        else:
            w.welcome.capture_bar.key_menu.actions()[2].trigger()
        assert w.hotkey_off() and not w.hotkey.registered
        assert w.hotkey_sequence() == QKeySequence("Alt+Num+1")
        return
    key, mods, reason = {
        "off_owner": (Qt.Key_C, Qt.ControlModifier, f"{'Command' if rig.platform == 'darwin' else 'Ctrl'}+C is already used by Copy image."),
        "unsupported": (Qt.Key_Left, Qt.AltModifier, hotkey.UNKNOWN_KEY),
        "keypad": (Qt.Key_1, Qt.AltModifier | Qt.KeypadModifier, hotkey.MAC_KEYPAD if rig.platform == "darwin" else hotkey.WIN_KEYPAD),
    }[case]
    if case == "unsupported":
        assert not w.hotkey.registered
    if entry == "settings":
        QTest.keyClick(page.hotkey_edit, key, mods)
        QTest.qWait(1100)
        assert page.hotkey_edit.keySequence() == QKeySequence(Y)
    else:
        w.welcome.start_recording()
        QTest.keyClick(w.welcome.recorder, key, mods)
        assert w.welcome.recording and w.welcome.recorder.error.text() == reason
    assert saved(w) == before and rig.backend.calls == calls
    assert page.message.text().splitlines()[0] == reason
    expected = (reason + "\n" + rig.y + " is unavailable."
                if case == "unsupported" and entry == "settings" else reason)
    assert page.message.text() == expected


@pytest.mark.parametrize("name", ["Light", "Dark", "Retro"])
@pytest.mark.parametrize("state", ["amber", "refused"])
def test_finding_5_painted_status_holds_wrapped_sentence(rig, name, state):
    from PySide6.QtCore import QRect
    seq = QKeySequence("Meta+Alt+Shift+Ctrl+Space")
    text = seq.toString(QKeySequence.PortableText)
    w = rig.create(text, refused=[text] if state == "amber" else [])
    w.apply_hotkey()
    if state == "refused":
        new = QKeySequence("Meta+Alt+Shift+Ctrl+F12")
        rig.backend.refused.add(new.toString(QKeySequence.PortableText))
        w.set_hotkey(new, False)
    theme.apply(rig.qapp, name)
    w.show()
    rig.qapp.processEvents()
    label = w.welcome.status_label
    assert label.text() == w.statusBar().currentMessage() and label.wordWrap()
    # QLabel paints plain text with QFontMetrics word wrapping, not a rich
    # text document's additional leading. Measure that exact paint rectangle.
    painted = label.fontMetrics().boundingRect(
        QRect(0, 0, label.contentsRect().width(), 10000),
        Qt.TextWordWrap | Qt.AlignLeft, label.text())
    assert label.contentsRect().height() >= painted.height()
    assert label.height() >= label.heightForWidth(label.width())
    page = w.welcome
    assert page.rect().contains(label.geometry())
    assert label.geometry().right() < page.recent_heading.parentWidget().geometry().left()
    bar = page.capture_bar
    for button in (bar.capture_button, bar.key_button):
        assert page.rect().contains(button.mapTo(page, button.rect().bottomRight()))
        assert button.isVisibleTo(w)
    assert label.geometry().bottom() < min(
        button.mapTo(page, button.rect().topLeft()).y()
        for button in (bar.capture_button, bar.key_button))
    assert w.size().toTuple() == (640, 430)


def test_finding_6_draft_error_preserves_registration_result(rig):
    w = rig.create(refused=[rig.default_sequence])
    outcome = w.apply_hotkey()
    line = w.welcome.key_row.text()
    w.welcome.start_recording()
    QTest.keyClick(w.welcome.recorder, Qt.Key_A)
    assert w.welcome.recorder.error.text() == hotkey.NEED_MODIFIER
    QTest.keyClick(w.welcome.recorder, Qt.Key_Escape)
    assert w.welcome.key_row.text() == line == f"{rig.d} is unavailable."
    assert w._s30_page.message.text() == outcome
    assert w.statusBar().currentMessage() == error(outcome)
    # A successful local edit retries the refused key; that outcome survives.
    page = w._s30_page
    page.edits["copy"].setKeySequence(QKeySequence("Alt+8"))
    assert page.commit("copy") is None
    assert page.message.text() == outcome
    assert w.statusBar().currentMessage() == error(outcome)
    assert rig.backend.calls[-1] == ("register", rig.default_sequence)


def test_finding_7_modifier_release_and_settings_recording(rig):
    w = ready(rig)
    w.show()
    w.welcome.start_recording()
    QTest.keyPress(w.welcome.recorder, Qt.Key_Alt)
    assert w.welcome.recorder.draft.text() == ("Option" if rig.platform == "darwin" else "Alt")
    QTest.keyRelease(w.welcome.recorder, Qt.Key_Alt)
    assert w.welcome.recorder.draft.text() == ""
    w.welcome.cancel_recording()
    page = w._s30_page
    page.show()
    page.hotkey_edit.setFocus()
    rig.qapp.processEvents()
    captures = []
    rig.monkeypatch.setattr(w, "capture", lambda: captures.append(1))
    modifier = Qt.Key_Meta if rig.platform == "darwin" else Qt.Key_Control
    QTest.keyPress(page.hotkey_edit, modifier)
    # Native delivery can precede the Qt key-down for the completed chord.
    w.hotkey._backend.press()
    QTest.keyClick(page.hotkey_edit, Qt.Key_Space, rig.default_mods)
    QTest.keyRelease(page.hotkey_edit, modifier)
    assert captures == []


def native_adapter(rig, *, wrap=False):
    """Production adapters and raw events; only OS calls are stubbed.

    Raw events wait outside dispatch. Native clocks follow the try clock.
    """
    import ctypes

    class Function:
        def __init__(self, callback):
            self.callback = callback
        def __call__(self, *args):
            return self.callback(*args)

    state = SimpleNamespace(window=None, calls=[])
    def now():
        ms = state.window.key_clock.now if state.window else 0
        return ((0xfffffb00 + ms) & 0xffffffff) if wrap else ms

    if rig.platform == "win32":
        user = SimpleNamespace(
            RegisterHotKey=Function(lambda hwnd, identity, *args: state.calls.append(("register", identity)) or 1),
            UnregisterHotKey=Function(lambda hwnd, identity: state.calls.append(("release", identity)) or 1))
        kernel = SimpleNamespace(GetTickCount=Function(now))
        rig.monkeypatch.setattr(ctypes, "WinDLL",
            lambda name, **kwargs: kernel if name == "kernel32" else user, raising=False)
        backend = hotkey.WinBackend
        def raw(pressed=True):
            event = hotkey.MSG()
            event.message = hotkey.WM_HOTKEY
            event.wParam = state.window.hotkey._backend._id
            event.time = now()
            return event
        def dispatch(event):
            adapter = state.window.hotkey._backend._filter
            assert adapter.nativeEventFilter(b"windows_dispatcher_MSG", ctypes.addressof(event)) == (True, 0)
    else:
        class RawEvent(ctypes.Structure):
            _fields_ = [("time", ctypes.c_double), ("kind", ctypes.c_uint32),
                        ("identity", hotkey.EventHotKeyID)]
        def read(event):
            return RawEvent.from_address(event)
        def assign(out):
            ctypes.cast(out, ctypes.POINTER(ctypes.c_void_p))[0] = 77
            return 0
        def register(code, mods, identity, target, flags, out):
            state.calls.append(("register", identity.id))
            return assign(out)
        def parameter(event, name, type_, actual, size, actual_size, out):
            ctypes.memmove(out, ctypes.byref(read(event).identity), ctypes.sizeof(hotkey.EventHotKeyID))
            return 0
        carbon = SimpleNamespace(
            GetApplicationEventTarget=Function(lambda: 1),
            InstallEventHandler=Function(lambda *args: assign(args[-1])),
            RegisterEventHotKey=Function(register),
            UnregisterEventHotKey=Function(lambda ref: state.calls.append(("release", ref.value)) or 0),
            RemoveEventHandler=Function(lambda ref: 0),
            GetEventParameter=Function(parameter),
            GetEventKind=Function(lambda event: read(event).kind),
            GetEventTime=Function(lambda event: read(event).time),
            GetCurrentEventTime=Function(lambda: now() / 1000))
        rig.monkeypatch.setattr(ctypes, "CDLL", lambda *args, **kwargs: carbon)
        backend = hotkey.MacBackend
        def raw(pressed=True):
            return RawEvent(now() / 1000,
                hotkey.K_EVENT_HOTKEY_PRESSED if pressed else hotkey.K_EVENT_HOTKEY_RELEASED,
                hotkey.EventHotKeyID(hotkey.fourcc("ANSH"), state.window.hotkey._backend._id))
        def dispatch(event):
            assert state.window.hotkey._backend._handler(None, ctypes.addressof(event), None) == 0
    rig.monkeypatch.setattr(hotkey, "backend_class", lambda: backend)
    state.raw, state.dispatch = raw, dispatch
    return state


@pytest.mark.parametrize("ending", ["timeout", "restore", "tray", "receipt", "next_try", "next_action"])
@pytest.mark.parametrize("wrap", [False, True], ids=["normal-clock", "tick-wrap"])
def test_s32_native_press_time_survives_raw_queue(rig, ending, wrap):
    if wrap and rig.platform != "win32":
        pytest.skip("tick wraparound is Windows-only")
    native = native_adapter(rig, wrap=wrap)
    w = ready(rig)
    native.window = w
    captures = []
    rig.monkeypatch.setattr(w, "_may_record_screen", lambda: captures.append(1) or False)
    start_try(w)
    w.key_clock.advance(1)
    raw = native.raw()  # held OUTSIDE the production adapter until after ending
    w.key_clock.advance(500 if wrap else 1)
    if ending == "timeout":
        w.key_clock.advance(10000)
    elif ending == "restore":
        w.reopen()
    elif ending == "tray":
        if rig.platform == "win32":
            w.tray.capture_action.trigger()
        else:
            w.capture_from_anywhere()
    elif ending == "receipt":
        native.dispatch(native.raw())
        if rig.platform == "darwin":
            native.dispatch(native.raw(False))
    elif ending == "next_try":
        w.welcome.capture_bar.key_menu.actions()[0].trigger()
        w.key_clock.advance(1000)
    else:
        w.welcome.capture_bar.key_menu.actions()[1].trigger()
    line = w.key_state()["line"]
    status = w.statusBar().currentMessage()
    baseline = [1] if ending == "tray" else []
    assert captures == baseline
    native.dispatch(raw)
    assert captures == baseline
    assert w.key_state()["line"] == line
    assert w.statusBar().currentMessage() == status
    if rig.platform == "darwin":
        native.dispatch(raw)  # Carbon repeat remains consumed too
        native.dispatch(native.raw(False))
    if ending == "next_try":
        assert w._key_try["phase"] == "armed"  # no receipt for the newer try
        w.reopen()
    elif ending == "next_action":
        w.welcome.recorder.cancel.click()
    w.key_clock.advance(1)
    native.dispatch(native.raw())
    assert captures == baseline + [1]
    if rig.platform == "darwin":
        native.dispatch(native.raw(False))


@pytest.mark.parametrize("ending", ["timeout", "receipt"])
def test_s32_change_then_cancel_clears_terminal_try_only(rig, ending):
    w = ready(rig)
    start_try(w)
    if ending == "timeout":
        w.key_clock.advance(10000)
    else:
        w.hotkey._backend.press()
    assert w.key_state()["line"] in ("No press received", "Annotshot received your key")
    feedback = w._key_feedback
    calls, before = list(rig.backend.calls), saved(w)
    w.welcome.capture_bar.key_menu.actions()[1].trigger()
    w.welcome.recorder.cancel.click()
    assert w.key_state()["line"] == f"Capture from anywhere with {rig.d}"
    assert w.key_state()["outcome"] == feedback
    assert not w.statusBar().currentMessage()
    assert rig.backend.calls == calls and saved(w) == before


def focus_capture_field(rig, page):
    page.show()
    page.activateWindow()
    page.hotkey_edit.setFocus()
    rig.qapp.processEvents()
    assert page.hotkey_edit.hasFocus() or page.hotkey_edit.isAncestorOf(rig.qapp.focusWidget())


def type_capture_chord(rig, page, key, mods=Qt.NoModifier):
    focus_capture_field(rig, page)
    QTest.keyClick(page.hotkey_edit, key, mods)
    QTest.qWait(1100)


@pytest.mark.parametrize("case", ["refused_swap", "unheld_invalid", "retained_release"])
def test_s32_settings_passive_and_explicit_roads(rig, case):
    w = rig.create(refused=[rig.default_sequence]) if case == "unheld_invalid" else ready(rig, Y if case == "retained_release" else None)
    if case == "unheld_invalid":
        w.apply_hotkey()
    page = w._s30_page
    if case == "refused_swap":
        rig.backend.refused.add(Y)
        type_capture_chord(rig, page, Qt.Key_Y, Qt.AltModifier)
        assert "Still using" in page.message.text()
    elif case == "unheld_invalid":
        key = Qt.Key_Left if rig.platform == "darwin" else Qt.Key_1
        mods = Qt.AltModifier if rig.platform == "darwin" else Qt.AltModifier | Qt.KeypadModifier
        type_capture_chord(rig, page, key, mods)
        reason = hotkey.UNKNOWN_KEY if rig.platform == "darwin" else hotkey.WIN_KEYPAD
        assert page.message.text().splitlines()[0] == reason
        assert page.message.text() == reason + "\n" + rig.d + " is unavailable."
        assert not w.hotkey.registered
    else:
        old = w.hotkey._backend.identity
        rig.backend.fail_release.add(old)
        page.hotkey_reset.click()  # row 17, real capture-row Reset
        assert w.hotkey._retained and w.hotkey.sequence == QKeySequence(rig.default_sequence)
        assert "Could not release" in page.message.text()
        rig.backend.fail_release.clear()
    before = saved(w)
    path = Path(w.settings.fileName())
    data = path.read_bytes() if path.exists() else b""
    reason, calls = page.message.text(), list(rig.backend.calls)
    apply_calls, chords = [], []
    apply = w.set_hotkey
    rig.monkeypatch.setattr(w, "set_hotkey", lambda *args: apply_calls.append(args) or apply(*args))
    witness = FocusOutWitness(page.hotkey_edit)
    page.hotkey_edit.chordEntered.connect(chords.append)
    focus_capture_field(rig, page)
    page.hotkey_off.setFocus()
    rig.qapp.processEvents()
    assert witness.events and not chords  # actual blur, no submission
    assert not apply_calls and saved(w) == before and rig.backend.calls == calls
    assert (path.read_bytes() if path.exists() else b"") == data
    assert page.message.text() == reason
    if case == "unheld_invalid":
        # Retyping the restored, unheld default is a deliberate retry.
        type_capture_chord(rig, page, Qt.Key_Space, rig.default_mods)
        assert len(apply_calls) == 1
        assert rig.backend.calls == calls + [("register", rig.default_sequence)]
    else:
        page.hotkey_reset.click()
        assert page.message.text() == "" and w.key_state()["outcome"] == ""
        assert w.hotkey_sequence() == QKeySequence(rig.default_sequence)
        assert not w.settings.contains("hotkey/sequence")
        assert not w.hotkey._retained
        assert rig.backend.calls == (calls + [("release", Y, old)] if case == "retained_release" else calls)


def test_s32_try_clears_previous_settings_edit_error(rig):
    w = ready(rig)
    page = w._s30_page
    type_capture_chord(rig, page, Qt.Key_C, Qt.ControlModifier)
    assert "already used by Copy image" in page.message.text()
    page.close()
    w.welcome.capture_bar.key_menu.actions()[0].trigger()
    w.key_clock.advance(1000)
    w.hotkey._backend.press()
    assert w.key_state()["line"] == "Annotshot received your key"
    assert page.message.text() == w.key_state()["outcome"] == ""
    reopened = settings_dialog.SettingsDialog(w)
    assert reopened.message.text() == ""
    reopened.deleteLater()


@pytest.mark.parametrize("leave", ["focus", "close", "inactive"])
def test_s32_native_f8_suppressed_by_current_field_focus(rig, leave):
    from PySide6.QtWidgets import QApplication
    native = native_adapter(rig)
    w = ready(rig)
    native.window = w
    page = w._s30_page
    captures = []
    rig.monkeypatch.setattr(w, "_may_record_screen", lambda: captures.append(1) or False)
    type_capture_chord(rig, page, Qt.Key_F8)
    assert w.hotkey.sequence == QKeySequence("F8")
    assert page.capture_key_has_focus()
    # No Qt key-down or focus change between commit and native delivery.
    w.key_clock.advance(1)
    native.dispatch(native.raw())
    assert captures == []
    if rig.platform == "darwin":
        native.dispatch(native.raw(False))
    if leave == "focus":
        page.hotkey_off.setFocus()
        rig.qapp.processEvents()
    elif leave == "close":
        page.close()
        rig.qapp.processEvents()
    else:
        # OS application-state seam models another application in front.
        rig.monkeypatch.setattr(QApplication, "applicationState", lambda: Qt.ApplicationInactive)
    assert not page.capture_key_has_focus()
    w.key_clock.advance(1)
    native.dispatch(native.raw())
    assert captures == [1]
    if rig.platform == "darwin":
        native.dispatch(native.raw(False))
