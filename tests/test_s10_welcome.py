"""The s10 welcome contract, using offscreen Qt and isolated settings only."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QEnterEvent, QImage
from PySide6.QtTest import QTest

from test_s10_capture import rig, drag, settle


def with_window(rig):
    window = SimpleNamespace(hwnd=42, rect=QRectF(100, 100, 300, 200), title="Playing video")
    rig.monkeypatch.setattr(rig.cap.macos, "list_windows", lambda: [window])
    return window


def test_auto_drag_shoots_area_and_remembers_it(rig):
    with_window(rig)
    session, results = rig.start()
    ov = session.overlays[0]
    assert session.mode == "auto" and ov._hover is not None
    drag(ov)
    assert ov._hover is None and session.state == "shooting"
    settle(session)
    assert results[0].title is None and results[0].image.size().toTuple() == (400, 200)
    assert session.settings.value("capture/last_area")["width"] == 200


def test_auto_click_keeps_pressed_window_title(rig):
    window = with_window(rig)
    session, results = rig.start()
    ov = session.overlays[0]
    QTest.mousePress(ov, Qt.LeftButton, pos=QPoint(150, 150))
    assert session.state == "idle" and not results
    QTest.mouseRelease(ov, Qt.LeftButton, pos=QPoint(150, 150))
    settle(session)
    assert results[0].title == window.title
    assert results[0].image.size().toTuple() == (600, 400)
    assert session.settings.value("capture/last_area") is None


def test_auto_click_on_no_window_does_nothing(rig):
    with_window(rig)
    session, results = rig.start()
    QTest.mouseClick(session.overlays[0], Qt.LeftButton, pos=QPoint(500, 100))
    assert session.state == "idle" and not results and session.selected is None


def test_area_ignores_click_and_window_ignores_drag(rig):
    with_window(rig)
    session, results = rig.start(mode="area")
    ov = session.overlays[0]
    assert session.bar.mode_buttons["area"].isChecked()
    QTest.mouseClick(ov, Qt.LeftButton, pos=QPoint(150, 150))
    assert session.state == "idle" and not results and ov._hover is None
    session.set_mode("window")
    drag(ov)
    assert session.state == "idle" and not results


def test_bar_toggle_returns_to_auto_and_is_mutually_exclusive(rig):
    with_window(rig)
    session, _ = rig.start()
    buttons = session.bar.mode_buttons
    assert list(buttons) == ["area", "window"]
    assert not any(b.isChecked() for b in buttons.values())
    buttons["area"].click()
    assert session.mode == "area"
    buttons["window"].click()
    assert session.mode == "window" and not buttons["area"].isChecked()
    buttons["window"].click()
    assert session.mode == "auto" and not any(b.isChecked() for b in buttons.values())
    assert session.bar.capture_button is None
    assert not session.bar.whole_screen_button.isCheckable()
    assert buttons["area"].toolTip() == "Only drag an area"
    assert buttons["window"].toolTip() == "Only click a window"
    assert session.bar.whole_screen_button.toolTip() == "Capture this whole screen"


@pytest.mark.parametrize("seconds", [0, 3])
def test_whole_screen_action_uses_bar_screen_and_timer(rig, seconds):
    session, results = rig.start(timer=seconds)
    session.pointer_on(session.overlays[1])
    session.bar.whole_screen_button.click()
    assert session.selected is session.overlays[1]
    assert session.state == ("countdown" if seconds else "shooting")
    if seconds:
        for _ in range(seconds):
            session._tick()
    settle(session)
    assert results[0].image.size().toTuple() == (1200, 900)
    assert rig.screens[0].calls == []
    assert session.settings.value("capture/last_area") is None


def test_stored_capture_mode_is_ignored_and_left_alone(rig):
    store = rig.cap.QSettings("Annotshot", "Annotshot")
    store.setValue("capture/mode", "window")
    session, _ = rig.start()
    assert session.mode == "auto"
    session.set_mode("area")
    assert store.value("capture/mode") == "window"


@pytest.mark.parametrize("stored", [False, True])
@pytest.mark.parametrize("key", [Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space])
def test_live_keys_and_double_click_never_take_stored_area(rig, key, stored):
    settings = {"last_area": {"screen": "main", "x": 120, "y": 120,
                              "width": 200, "height": 100}} if stored else {}
    session, results = rig.start(**settings)
    ov = session.overlays[0]
    assert session.selected is None and all(o.area.isEmpty() for o in session.overlays)
    assert session.bar.same_area_button.isHidden() == (not stored)
    image = QImage(ov.size(), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    ov.render(image)
    assert image.pixelColor(119, 170).alpha() == 1
    QTest.keyClick(ov, key)
    QTest.keyClick(session.bar.same_area_button, key)
    QTest.mouseDClick(ov, Qt.LeftButton, pos=QPoint(200, 160))
    QTest.mouseRelease(ov, Qt.LeftButton, pos=QPoint(200, 160))
    assert session.state == "idle" and not results and session.selected is None
    assert not session._settle.isActive() and not session._countdown.isActive()
    assert all(not screen.calls for screen in rig.screens)


@pytest.mark.parametrize("mode,marked,expected", [
    (None, False, "Drag for an area · click a window · Esc to cancel"),
    (None, True, "Drag for an area · click a window · Esc to cancel"),
    ("area", False, "Drag to capture an area · Esc to cancel"),
    ("area", True, "Drag to capture an area · Esc to cancel"),
    ("window", False, "Click a window to capture it · Esc to cancel"),
    ("window", True, "Click a window to capture it · Esc to cancel"),
])
def test_live_hints(rig, mode, marked, expected):
    with_window(rig)
    settings = {"last_area": {"screen": "main", "x": 120, "y": 120,
                              "width": 200, "height": 100}} if marked else {}
    session, _ = rig.start(mode=mode, **settings)
    assert session.overlays[0].hint() == expected
    assert session.selected is None
    assert session.bar.same_area_button.isHidden() == (not marked)


def test_empty_window_list_falls_back_to_area(rig):
    session, results = rig.start()
    assert session.mode == "auto" and not session.windows_available
    assert not session.bar.mode_buttons["window"].isEnabled()
    assert session.overlays[0].hint() == "Drag to capture an area · Esc to cancel"
    with_window(rig)
    session.set_mode("auto")
    assert session.bar.mode_buttons["window"].isEnabled()
    rig.monkeypatch.setattr(rig.cap.macos, "list_windows", lambda: [])
    QTest.mouseClick(session.overlays[0], Qt.LeftButton, pos=QPoint(500, 100))
    assert not session.bar.mode_buttons["window"].isEnabled()
    assert session.overlays[0].hint() == "Drag to capture an area · Esc to cancel"
    drag(session.overlays[0])
    settle(session)
    assert results[0].title is None


# Every allowed browser call is on the user's click, including Recent's
# local folder. No dynamic imports are needed in the application today.
BROWSER_CALL_MODULES = {"help.py", "recent.py"}
DYNAMIC_IMPORT_ALLOWLIST = set()  # Entries: (package-relative file, full call text).


def privacy_scan(package):
    forbidden = ("socket", "ssl", "urllib.request", "http.client", "ftplib",
                 "smtplib", "requests", "httpx", "aiohttp", "websockets",
                 "webbrowser", "importlib", "PySide6.QtNetwork",
                 "PySide6.QtWebSockets", "PySide6.QtWebEngine")
    findings, browsers = [], set()
    for path in sorted(package.rglob("*.py")):
        relative = path.relative_to(package).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imports = []
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                imports = [base, *(f"{base}.{alias.name}" for alias in node.names)]
            for name in imports:
                if any(name == bad or name.startswith(bad + ".") or
                       (bad.endswith("QtWebEngine") and name.startswith(bad))
                       for bad in forbidden):
                    findings.append(f"{path}:{node.lineno} imports {name}")
            if isinstance(node, ast.Attribute) and node.attr == "openUrl":
                browsers.add(relative)
            if isinstance(node, ast.Call):
                function = node.func
                dynamic = (isinstance(function, ast.Name) and
                           function.id == "__import__") or (
                    isinstance(function, ast.Attribute) and
                    function.attr in ("import_module", "__import__"))
                if dynamic and (relative, ast.unparse(node)) not in DYNAMIC_IMPORT_ALLOWLIST:
                    findings.append(f"{path}:{node.lineno} dynamic import {ast.unparse(node)}")
    return findings, browsers


def test_the_app_has_no_network_code(monkeypatch, tmp_path):
    package = Path(__file__).resolve().parents[1] / "annotshot"
    monkeypatch.chdir(tmp_path)
    findings, browsers = privacy_scan(package)
    assert not findings, "\n".join(findings)
    assert browsers == BROWSER_CALL_MODULES


@pytest.mark.parametrize("source,network,browser", [
    ("import webbrowser", True, False),
    ("send = QDesktopServices.openUrl", False, True),
    ("importlib.import_module(chosen_name)", True, False),
    ("__import__(chosen_name)", True, False),
    ("builtins.__import__(chosen_name)", True, False),
])
def test_privacy_scan_rejects_new_roads(tmp_path, source, network, browser):
    (tmp_path / "new.py").write_text(source, encoding="utf-8")
    findings, browsers = privacy_scan(tmp_path)
    assert bool(findings) is network
    assert (browsers == {"new.py"}) is browser


@pytest.fixture
def welcome_window(qapp):
    from annotshot.app import make_app
    from annotshot.mainwindow import MainWindow
    make_app()
    window = MainWindow()
    yield window
    window.doc.undo_stack.mark_exported()
    window.hide()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()


def test_launch_is_welcome_and_never_reopens_recent_current(welcome_window, white):
    from annotshot.mainwindow import MainWindow, CURRENT_KEY
    from annotshot.scene import Document
    path = welcome_window.recent_store.reserve()
    path.parent.mkdir(parents=True, exist_ok=True)
    white.save(str(path))
    welcome_window.settings.setValue(CURRENT_KEY, str(path))
    again = MainWindow()
    try:
        assert again.state_name == "welcome" and again.doc.is_placeholder
        assert again.doc.path is None and again.size().toTuple() == (640, 430)
        assert again.minimumSize() == again.maximumSize()
        assert not again.welcome.empty_recent.isVisible()  # parent is hidden
        assert len(again.welcome.recent_buttons) == 1
    finally:
        again.deleteLater()


def test_welcome_chrome_and_picture_actions_and_copy_button(welcome_window, white):
    from PySide6.QtWidgets import QToolBar
    from annotshot.scene import Document
    w = welcome_window
    assert all(bar.isHidden() for bar in w.findChildren(QToolBar))
    assert w.recent.isHidden() and w.statusBar().isHidden()
    assert not w.a_copy.isEnabled() and not w.a_save.isEnabled()
    assert all(not action.isEnabled() for action in w.tool_actions.values())
    assert w.findChild(QToolBar, "main").widgetForAction(w.a_copy).objectName() != "outline"
    w._bind(Document(white))
    assert w.state_name == "editor" and w.pages.currentWidget() is w.view
    assert all(not bar.isHidden() for bar in w.findChildren(QToolBar))
    assert not w.statusBar().isHidden() and w.a_copy.isEnabled()
    w.clear_picture()
    assert w.state_name == "welcome" and w.pages.currentWidget() is w.welcome


def test_editor_geometry_is_saved_only_from_editor(welcome_window, white):
    from PySide6.QtCore import QSize
    from annotshot.scene import Document
    w = welcome_window
    w.settings.setValue("window/size", QSize(620, 610))
    w.show_welcome()
    assert w.settings.value("window/size", type=QSize) == QSize(620, 610)
    w._bind(Document(white))
    assert w.size() == QSize(620, 610).boundedTo(w._cap(w._screen_area())).expandedTo(w.minimumSize())
    w.resize(630, 620)
    expected = w.size()
    w.clear_picture()
    assert w.settings.value("window/size", type=QSize) == expected
    w.show_welcome()
    assert w.settings.value("window/size", type=QSize) == expected
    w._bind(Document(white))
    assert w.size() == expected


def test_file_argument_and_file_open_event_enter_editor(welcome_window, qapp, white, tmp_path, monkeypatch):
    from annotshot import app as app_module
    from annotshot.scene import Document
    path = tmp_path / "opened.annotshot"
    Document(white).save(path)
    monkeypatch.setattr(app_module, "MainWindow", lambda: welcome_window)
    monkeypatch.setattr(app_module.filetype, "register", lambda: None)
    monkeypatch.setattr(app_module.filetype, "user_choice", lambda: None)
    monkeypatch.setattr(qapp, "exec", lambda: 0)
    assert app_module.main(["annotshot", str(path)]) == 0
    assert welcome_window.state_name == "editor" and welcome_window.doc.path == str(path)
    welcome_window.clear_picture()
    from PySide6.QtGui import QFileOpenEvent
    event = QFileOpenEvent(str(path))
    assert app_module.FileOpenFilter(welcome_window).eventFilter(qapp, event)
    assert welcome_window.state_name == "editor"
    qapp.removeEventFilter(qapp._annotshot_file_filter)


def test_capture_result_and_recent_click_enter_editor(welcome_window, white, qapp):
    from annotshot.capture import CaptureResult
    w = welcome_window
    w._capture_done(CaptureResult(white, "Captured"))
    assert w.state_name == "editor" and not w.doc.is_placeholder
    from annotshot import recent
    from PySide6.QtCore import QThreadPool
    assert QThreadPool.globalInstance().waitForDone(10000)
    qapp.processEvents()
    w.clear_picture()
    assert w.state_name == "welcome"
    assert len(w.welcome.recent_buttons) == 1
    w.welcome.recent_buttons[0].click()
    assert w.state_name == "editor" and w.doc.path


@pytest.mark.parametrize("initial", ["welcome", "editor"])
def test_escape_returns_to_capture_starting_state(welcome_window, white, rig, initial):
    from annotshot.scene import Document
    w = welcome_window
    if initial == "editor":
        w._bind(Document(white))
    w.show()
    session, _ = rig.start()
    w._capture = session
    session.finished.connect(w._capture_done)
    w.hide()
    QTest.keyClick(session.overlays[0], Qt.Key_Escape)
    assert w.state_name == initial and w.isVisible()


def test_welcome_text_rows_follow_copy_key_and_platform(welcome_window, monkeypatch):
    from annotshot import welcome
    from PySide6.QtGui import QKeySequence
    w = welcome_window
    assert w.welcome.intro.text() == "Take a picture of your screen, add arrows and notes, and paste it where you need it."
    assert w.welcome.copy_row.text() == "Every capture is copied, ready to paste."
    assert not w.welcome.copy_row.row_widget.isHidden()
    w.settings.setValue("capture/copy", False)
    w.welcome.refresh()
    assert w.welcome.copy_row.row_widget.isHidden()
    for platform, word in (("darwin", "this Mac"), ("win32", "this PC"), ("linux", "this computer")):
        monkeypatch.setattr(welcome.sys, "platform", platform)
        w.welcome.refresh()
        assert f"Private. Your pictures stay on {word}. Annotshot sends nothing anywhere." in w.welcome.privacy_row.text()
    w.set_hotkey(QKeySequence("Ctrl+Alt+9"), False)
    assert QKeySequence("Ctrl+Alt+9").toString(QKeySequence.NativeText) in w.welcome.key_row.text()
    assert "Change keys" in w.welcome.key_row.text()
    w.set_hotkey(QKeySequence(), False)
    assert w.welcome.key_row.text() == '<a href="keys">Set a key to capture from anywhere</a>'


def test_change_keys_selects_shortcuts_tab(welcome_window, monkeypatch):
    from annotshot.settings_dialog import SettingsDialog
    seen = []
    monkeypatch.setattr(SettingsDialog, "exec", lambda dialog: seen.append(dialog.tabs.tabText(dialog.tabs.currentIndex())))
    welcome_window.welcome.key_row.linkActivated.emit("keys")
    assert seen == ["Shortcuts"]


def test_welcome_open_link_uses_open_action(welcome_window, monkeypatch):
    calls = []
    monkeypatch.setattr(welcome_window.a_open, "trigger", lambda: calls.append("open"))
    welcome_window.welcome.open_link.linkActivated.emit("open")
    assert calls == ["open"]


def test_welcome_capture_bar_calls_and_timer(welcome_window, monkeypatch):
    from annotshot import welcome
    monkeypatch.setattr(welcome.sys, "platform", "darwin")
    bar = welcome.WelcomeCaptureBar(welcome_window, welcome_window.welcome)
    calls = []
    monkeypatch.setattr(welcome_window, "capture", lambda mode=None: calls.append(mode))
    for button in bar.mode_buttons.values():
        button.click()
    bar.capture_button.click()
    assert calls == ["area", "window", "screen", None]
    bar.timer_actions[5].trigger()
    assert welcome_window.settings.value("capture/timer", type=int) == 5
    assert bar.timer_actions[5].isChecked() and not bar.timer_actions[0].isChecked()


def test_linux_welcome_bar_has_only_capture(welcome_window, monkeypatch):
    from annotshot import welcome
    from PySide6.QtWidgets import QPushButton
    monkeypatch.setattr(welcome.sys, "platform", "linux")
    bar = welcome.WelcomeCaptureBar(welcome_window, welcome_window.welcome)
    assert [button.text() for button in bar.findChildren(QPushButton)] == ["Capture"]


@pytest.mark.parametrize("key", [Qt.Key_Return, Qt.Key_Space])
def test_welcome_keys_capture_and_tool_letters_do_nothing(welcome_window, qapp, monkeypatch, key):
    from annotshot.tools import Tool
    w = welcome_window
    w.show()
    calls = []
    monkeypatch.setattr(w, "capture", lambda mode=None: calls.append(mode))
    w.welcome.setFocus()
    QTest.keyClick(w.welcome, Qt.Key_A)
    assert w.view.tool is Tool.SELECT
    QTest.keyClick(w.welcome, key)
    assert calls == [None]


def test_recent_empty_or_unreadable_leaves_welcome_usable(welcome_window, monkeypatch):
    w = welcome_window
    assert not w.welcome.recent_buttons and not w.welcome.empty_recent.isHidden()
    def unreadable():
        raise OSError("unreadable Recent")
    monkeypatch.setattr(w.recent_store, "files", unreadable)
    w.welcome.refresh()
    assert not w.welcome.recent_buttons and not w.welcome.empty_recent.isHidden()
    assert w.state_name == "welcome"


def test_welcome_recent_is_limited_to_newest_four(welcome_window, white):
    from PySide6.QtCore import QDateTime
    w = welcome_window
    for minute in range(5):
        when = QDateTime.fromString(f"2026-11-11T06:0{minute}:00", Qt.ISODate)
        w.recent_store.file(white, when=when)
    w.welcome.refresh()
    assert len(w.welcome.recent_buttons) == 4
    assert "0604" in w.welcome.recent_buttons[0].toolTip().replace("-", "")


def test_privacy_section_and_link(welcome_window):
    from annotshot.help import help_markdown, manual_text
    text = manual_text()
    paragraph = text.split("## Privacy\n\n", 1)[1].split("\n\n", 1)[0]
    assert paragraph.startswith("Annotshot works entirely on this computer. It has no internet code: it cannot upload, sync or report anything, and it never checks for updates by itself.")
    assert "Pictures folder, under Annotshot/Recent" in paragraph
    assert "app data folder under Captures/Recent" in paragraph
    assert paragraph in help_markdown([], text)
    w = welcome_window
    w.welcome.privacy_row.linkActivated.emit("privacy")
    assert w._help_window is not None
    assert paragraph in w._help_window.browser.toPlainText()
    w._help_window.close()


def test_mainwindow_capture_passes_optional_mode(welcome_window, monkeypatch):
    from annotshot import mainwindow
    modes = []
    class Session:
        finished = SimpleNamespace(connect=lambda _: None)
        def __init__(self, parent):
            pass
        def start(self, mode=None):
            modes.append(mode)
    monkeypatch.setattr(mainwindow, "CaptureSession", Session)
    for mode in (None, "area", "window", "screen"):
        welcome_window._start_capture(mode)
    welcome_window._capture = None
    assert modes == [None, "area", "window", "screen"]


def test_every_theme_renders_offscreen(welcome_window, qapp, white, rig):
    """Requested visual artifacts use synthetic Recent pictures and private settings."""
    from annotshot import theme
    from PySide6.QtCore import QDateTime
    from PySide6.QtGui import QPainter
    from PySide6.QtWidgets import QWidget
    out = Path("docs/briefs/renders-s10-welcome")
    out.mkdir(parents=True, exist_ok=True)
    w = welcome_window
    for minute in range(4):
        image = QImage(360, 170, QImage.Format_RGB32)
        image.fill(theme.color("thumb-ground"))
        painter = QPainter(image)
        painter.setPen(theme.color("icon"))
        painter.drawText(image.rect(), Qt.AlignCenter, f"Captured picture {minute + 1}")
        painter.end()
        when = QDateTime.fromString(f"2026-11-11T06:0{minute}:00", Qt.ISODate)
        w.recent_store.file(image, when=when)
    w.show()
    for name in ("Light", "Dark", "Retro"):
        theme.apply(qapp, name)
        w.welcome.refresh()
        qapp.processEvents()
        assert w.size().toTuple() == (640, 430)
        assert w.grab().save(str(out / f"welcome-{name.lower()}.png"))
        for button in w.welcome.recent_buttons:
            assert w.welcome.rect().contains(button.mapTo(w.welcome, button.rect().bottomRight()))
    theme.apply(qapp, "Light")
    w.recent_store.clear()
    w.welcome.refresh()
    qapp.processEvents()
    assert w.grab().save(str(out / "welcome-no-recent.png"))
    with_window(rig)
    session, _ = rig.start(last_area={"screen": "main", "x": 120, "y": 120,
                                      "width": 200, "height": 100})
    session.state = "rendering"  # Pointer events cannot move the bar during this render.
    host = QWidget()
    host.resize(900, 200)
    host.setStyleSheet("background: #404040;")  # Requested dark-grey render ground.
    bar = session.bar
    bar.setParent(host)
    bar._pulse.stop()
    bar._set_glow_factor(1.0)
    bar.adjustSize()
    bar.move((900 - bar.width()) // 2, (200 - bar.height()) // 2)
    bar.show()
    host.show()
    qapp.processEvents()
    bar._pulse.stop()
    bar._set_glow_factor(1.0)
    assert host.grab().save(str(out / "live-bar-auto.png"))
    bar.setParent(session.overlays[0])
    host.close()


def test_unreadable_recent_store_still_opens_at_launch(qapp, monkeypatch):
    from annotshot import recent
    from annotshot.mainwindow import MainWindow
    def unreadable(_):
        raise OSError("unreadable Recent")
    monkeypatch.setattr(recent.RecentStore, "files", unreadable)
    window = MainWindow()
    try:
        assert window.state_name == "welcome"
        assert not window.welcome.empty_recent.isHidden()
    finally:
        window.deleteLater()


@pytest.mark.parametrize("mode", [None, "window"])
@pytest.mark.parametrize("stored", [False, True])
def test_window_click_starts_shot_in_same_event_turn(rig, mode, stored):
    window = with_window(rig)
    settings = {"last_area": {"screen": "main", "x": 120, "y": 120,
                              "width": 200, "height": 100}} if stored else {}
    session, results = rig.start(mode=mode, **settings)
    ov = session.overlays[0]
    QTest.mousePress(ov, Qt.LeftButton, pos=QPoint(150, 150))
    QTest.mouseRelease(ov, Qt.LeftButton, pos=QPoint(150, 150))
    assert session.state == "shooting" and session._settle.isActive()
    assert not hasattr(session, "_click_timer") and not hasattr(session, "_window_click")
    assert ov.area_pixels() == QRect(200, 200, 600, 400)
    settle(session)
    assert results[0].title == window.title
    assert results[0].image.size().toTuple() == (600, 400)
    assert session.settings.value("capture/last_area") == settings.get("last_area")


@pytest.fixture
def background_window(qapp, monkeypatch):
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QSystemTrayIcon
    from annotshot import mainwindow, tray
    from annotshot.app import make_app
    class FakeTray(QObject):
        activated = Signal(object)
        Trigger = QSystemTrayIcon.Trigger
        DoubleClick = QSystemTrayIcon.DoubleClick
        tray_available = True
        @staticmethod
        def isSystemTrayAvailable():
            return FakeTray.tray_available
        def __init__(self, icon, parent):
            super().__init__(parent)
            self.messages = []
            self.shown = False
        def setToolTip(self, text):
            self.tooltip = text
        def setContextMenu(self, menu):
            self.menu = menu
        def show(self):
            self.shown = True
        def hide(self):
            self.shown = False
        def showMessage(self, title, text):
            self.messages.append((title, text))
    monkeypatch.setattr(tray, "QSystemTrayIcon", FakeTray)
    monkeypatch.setattr(mainwindow.sys, "platform", "win32")
    make_app()
    window = mainwindow.MainWindow()
    yield window, FakeTray
    window.hide()
    window.doc.undo_stack.mark_exported()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()


@pytest.mark.parametrize("platform,tray_available,hides_on_close", [
    ("darwin", False, True),
    ("linux", True, False),
    ("win32", True, True),
    ("win32", False, False),
])
def test_keep_running_setting_defaults_on_and_checkbox_updates(
        background_window, monkeypatch, qapp, platform, tray_available, hides_on_close):
    from annotshot import mainwindow
    from annotshot.settings_dialog import SettingsDialog
    w, fake_tray = background_window
    monkeypatch.setattr(mainwindow.sys, "platform", platform)
    fake_tray.tray_available = tray_available
    w.configure_background()
    assert w.keep_running()
    assert w.can_hide_on_close() is hides_on_close
    assert qapp.quitOnLastWindowClosed() is (not hides_on_close)
    dialog = SettingsDialog(w)
    assert dialog.keep_running.text() == "Keep Annotshot running when its window is closed"
    assert dialog.keep_running.isChecked()
    dialog.keep_running.setChecked(False)
    assert not w.keep_running() and qapp.quitOnLastWindowClosed()
    assert w.settings.value("app/keep_running", type=bool) is False
    dialog.deleteLater()
    w.set_keep_running(True)
    w.show()
    assert w.close() is (not hides_on_close)
    assert not w.isVisible()
    assert w._quitting is (not hides_on_close)
    assert qapp.quitOnLastWindowClosed() is (not hides_on_close)


def test_close_hides_returns_welcome_and_keeps_hotkey(background_window, white, monkeypatch, qapp):
    from annotshot.scene import Document
    w, _ = background_window
    cleared = []
    monkeypatch.setattr(w.hotkey, "clear", lambda: cleared.append(1))
    w._bind(Document(white))
    w.show()
    w.close()
    assert not w.isVisible() and w.state_name == "welcome"
    assert cleared == [] and not qapp.quitOnLastWindowClosed()
    assert w.doc.is_placeholder


def test_quit_uses_close_guard_clears_key_and_really_quits(background_window, monkeypatch):
    w, _ = background_window
    calls = []
    monkeypatch.setattr(w.hotkey, "clear", lambda: calls.append("clear"))
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(QApplication.instance(), "quit", lambda: calls.append("quit"))
    w.show()
    w.a_quit.trigger()
    assert calls == ["clear", "quit"]
    assert w.tray is None and not w.isVisible()


def test_quit_respects_unsaved_guard(background_window, monkeypatch):
    w, _ = background_window
    calls = []
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(QApplication.instance(), "quit", lambda: calls.append("quit"))
    monkeypatch.setattr(w, "maybe_discard", lambda: False)
    w.show()
    w.quit_app()
    assert not calls and w.isVisible() and not w._quitting


def test_setting_off_quits_on_close(background_window, monkeypatch, qapp):
    w, _ = background_window
    calls = []
    monkeypatch.setattr(w.hotkey, "clear", lambda: calls.append("clear"))
    w.set_keep_running(False)
    w.show()
    assert w.close()
    assert calls == ["clear"] and qapp.quitOnLastWindowClosed()


def test_no_tray_quits_on_close(background_window, monkeypatch, qapp):
    from annotshot.mainwindow import MainWindow
    _, fake = background_window
    fake.tray_available = False
    w = MainWindow()
    cleared = []
    monkeypatch.setattr(w.hotkey, "clear", lambda: cleared.append(1))
    try:
        assert w.tray is None and qapp.quitOnLastWindowClosed()
        w.show()
        assert w.close() and cleared == [1]
    finally:
        w.deleteLater()


def test_mac_activation_with_hidden_window_shows_welcome(welcome_window, monkeypatch, qapp):
    from PySide6.QtCore import QEvent
    from annotshot import app as app_module
    w = welcome_window
    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    w.show()
    w.close()
    assert not w.isVisible()
    app_module.FileOpenFilter(w).eventFilter(qapp, QEvent(QEvent.ApplicationActivate))
    assert w.isVisible() and w.state_name == "welcome"


def test_tray_menu_three_entries_and_actions(background_window, monkeypatch):
    w, fake = background_window
    key = w.capture_key_text()
    w.show()
    w.hide()
    assert [action.text() for action in w.tray.menu.actions()] == [
        f"Capture ({key})", "Open Annotshot", "Quit Annotshot"]
    calls = []
    monkeypatch.setattr(w, "capture_from_anywhere", lambda: calls.append("capture"))
    monkeypatch.setattr(w, "reopen", lambda: calls.append("open"))
    monkeypatch.setattr(w, "quit_app", lambda: calls.append("quit"))
    for action in w.tray.menu.actions():
        action.trigger()
    w.tray.icon.activated.emit(fake.Trigger)
    assert calls == ["capture", "open", "quit", "open"]
    from PySide6.QtGui import QKeySequence
    w.set_hotkey(QKeySequence(), True)
    assert w.tray.capture_action.text() == "Capture"


def test_first_hide_message_is_shown_once(background_window):
    w, _ = background_window
    key = w.capture_key_text()
    for _ in range(2):
        w.show()
        w.close()
    assert w.tray.icon.messages == [("Annotshot is still running", f"{key} captures. Quit from this icon.")]
    assert w.settings.value("app/keep_running_told", type=bool)


@pytest.mark.parametrize("pending", [False, True])
def test_close_during_capture_is_ignored(background_window, pending, monkeypatch):
    w, _ = background_window
    calls = []
    monkeypatch.setattr(w.hotkey, "clear", lambda: calls.append("clear"))
    w.show()
    w._capture_pending = pending
    w._capture = None if pending else object()
    assert not w.close() and w.isVisible()
    assert not calls and w.tray is None
    w._capture_pending = False
    w._capture = None


@pytest.mark.parametrize("success", [False, True])
def test_capture_key_while_hidden_returns_editor_or_stays_hidden(background_window, rig, monkeypatch, white, success):
    from annotshot.capture import CaptureResult
    w, _ = background_window
    w.settings.setValue("capture/minimize", True)
    w.show()
    w.close()
    assert not w.isVisible()
    monkeypatch.setattr(w, "_may_record_screen", lambda: True)
    # Deliver the normal delayed start synchronously, with the capture rig.
    def start(mode=None):
        w._capture_pending = False
        session, _ = rig.start(mode=mode)
        w._capture = session
        session.finished.connect(w._capture_done)
    from annotshot import mainwindow
    monkeypatch.setattr(mainwindow.QTimer, "singleShot", lambda _ms, callback: callback())
    monkeypatch.setattr(w, "_start_capture", start)
    w.capture_from_anywhere()
    assert not w.isVisible() and w._capture is not None
    if success:
        w._capture._finish(CaptureResult(white))
        assert w.isVisible() and w.state_name == "editor"
        assert not w.isMinimized()
        assert w.settings.value("capture/minimize", type=bool) is True
    else:
        QTest.keyClick(w._capture.overlays[0], Qt.Key_Escape)
        assert not w.isVisible() and w.state_name == "welcome"


@pytest.mark.parametrize("platform,tray_available,hides_on_close", [
    ("darwin", False, True),
    ("linux", True, False),
    ("win32", True, True),
    ("win32", False, False),
])
def test_keep_running_welcome_row_conditions(
        background_window, monkeypatch, platform, tray_available, hides_on_close):
    from annotshot import mainwindow
    from PySide6.QtGui import QKeySequence
    w, fake_tray = background_window
    monkeypatch.setattr(mainwindow.sys, "platform", platform)
    fake_tray.tray_available = tray_available
    w.configure_background()
    key = w.capture_key_text()
    assert w.welcome.running_row.text() == f"Close this window and Annotshot keeps running; {key} still captures."
    assert w.can_hide_on_close() is hides_on_close
    assert w.welcome.running_row.row_widget.isHidden() is (not hides_on_close)
    assert not w.welcome.running_row.isHidden()
    w.set_keep_running(False)
    assert w.welcome.running_row.row_widget.isHidden()
    w.set_keep_running(True)
    assert w.welcome.running_row.row_widget.isHidden() is (not hides_on_close)
    w.set_hotkey(QKeySequence(), True)
    assert w.welcome.running_row.row_widget.isHidden()


def test_native_quit_event_uses_window_close_guard(welcome_window, monkeypatch, qapp):
    from annotshot.app import FileOpenFilter
    from PySide6.QtCore import QEvent
    called = []
    monkeypatch.setattr(welcome_window, "quit_app", lambda: called.append("quit"))
    assert FileOpenFilter(welcome_window).eventFilter(qapp, QEvent(QEvent.Quit))
    assert called == ["quit"]


def test_tray_disappearing_before_close_falls_back_to_quit(background_window, qapp):
    w, fake = background_window
    assert w.tray is None and w.can_hide_on_close()
    fake.tray_available = False
    w.show()
    assert w.close() and qapp.quitOnLastWindowClosed()


def test_welcome_is_centered_on_its_last_screen(welcome_window, monkeypatch):
    from PySide6.QtCore import QRect
    area = QRect(-1200, 80, 1200, 800)
    monkeypatch.setattr(welcome_window, "_screen_area", lambda: area)
    welcome_window.show_welcome()
    assert welcome_window.frameGeometry().center() == area.center()


def test_capture_entry_points_pass_modes_and_default_to_auto(welcome_window, monkeypatch):
    from annotshot import mainwindow
    modes = []
    class Session:
        finished = SimpleNamespace(connect=lambda _: None)
        def __init__(self, parent):
            pass
        def start(self, mode=None):
            modes.append(mode)
    w = welcome_window
    monkeypatch.setattr(mainwindow, "CaptureSession", Session)
    monkeypatch.setattr(w, "_may_record_screen", lambda: True)
    monkeypatch.setattr(mainwindow.QTimer, "singleShot", lambda _ms, callback: callback())
    for mode in (None, "area", "window", "screen"):
        w.capture(mode)
        w._capture = None
    w.a_capture.trigger()
    w._capture = None
    w.capture_from_anywhere()
    w._capture = None
    assert modes == [None, "area", "window", "screen", None, None]


def test_editor_dock_state_is_saved_and_welcome_never_overwrites_it(welcome_window, white):
    from PySide6.QtCore import QByteArray
    from annotshot.scene import Document
    w = welcome_window
    w._bind(Document(white))
    w.recent.show()
    saved = w.saveState()
    w.clear_picture()
    assert w.settings.value("window/state", type=QByteArray) == saved
    w.show_welcome()
    assert w.settings.value("window/state", type=QByteArray) == saved
    w._bind(Document(white))
    assert not w.recent.isHidden()


def test_frozen_fallback_preserves_explicit_window_mode(rig):
    window = with_window(rig)
    rig.monkeypatch.setattr(rig.cap.LiveOverlay, "supports_translucency", lambda _: False)
    session, results = rig.start(mode="window")
    assert session.freeze and session._forced_freeze and session.mode == "window"
    settle(session)
    assert session.bar.mode_buttons["window"].isChecked()
    QTest.mouseClick(session.overlays[0], Qt.LeftButton, pos=QPoint(150, 150))
    assert results[0].title == window.title
    assert results[0].image.size().toTuple() == (600, 400)


def test_capture_result_fits_the_visible_editor(welcome_window, monkeypatch, white):
    from PySide6.QtCore import QRect
    from annotshot.capture import CaptureResult
    from annotshot.scene import Document
    w = welcome_window
    monkeypatch.setattr(w, "_screen_area", lambda: QRect(0, 0, 1920, 1200))
    w.settings.setValue("recent/keep", False)
    w._bind(Document(white))
    w.resize(1400, 900)
    w.show()
    before = w.size()
    small = QImage(400, 200, QImage.Format_RGB32)
    small.fill(Qt.white)
    w._capture_done(CaptureResult(small))
    assert w.isVisible() and w.state_name == "editor"
    assert w.width() < before.width() and w.height() < before.height()


def unsaved_picture(window, white):
    from annotshot.items import RectItem
    from annotshot.scene import Document
    window._bind(Document(white))
    window.doc.add_items([RectItem()])
    assert window.doc.path is None and window.doc.undo_stack.needs_save()


@pytest.mark.parametrize("reason", ["setting_off", "no_tray"])
@pytest.mark.parametrize("answer_name", ["Discard", "Cancel"])
def test_close_without_background_asks_once(background_window, white, monkeypatch,
                                            qapp, reason, answer_name):
    from PySide6.QtWidgets import QMessageBox
    from annotshot.app import FileOpenFilter
    w, fake = background_window
    if reason == "setting_off":
        w.set_keep_running(False)
    else:
        fake.tray_available = False
    unsaved_picture(w, white)
    questions, quits = [], []
    answer = getattr(QMessageBox, answer_name)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: questions.append(args[2]) or answer)
    monkeypatch.setattr(qapp, "quit", lambda: quits.append("quit"))
    w.show()
    accepted = w.close()
    if answer_name == "Cancel":
        assert not accepted and w.isVisible() and not w._quitting
    else:
        assert accepted and not w.isVisible()
        # Qt sends Quit after the last accepted close; it must pass through.
        assert not FileOpenFilter(w).eventFilter(qapp, QEvent(QEvent.Quit))
        assert w._quitting
    assert questions == ["Save your changes to this project first?"]
    assert quits == []


@pytest.mark.parametrize("answer_name", ["Discard", "Cancel"])
def test_quit_action_asks_once(background_window, white, monkeypatch, qapp, answer_name):
    from PySide6.QtWidgets import QMessageBox
    w, _ = background_window
    unsaved_picture(w, white)
    questions, quits = [], []
    answer = getattr(QMessageBox, answer_name)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: questions.append(args[2]) or answer)
    monkeypatch.setattr(qapp, "quit", lambda: quits.append("quit"))
    w.show()
    w.a_quit.trigger()
    assert questions == ["Save your changes to this project first?"]
    assert quits == (["quit"] if answer_name == "Discard" else [])
    assert w.isVisible() is (answer_name == "Cancel")
    assert w._quitting is (answer_name == "Discard")


def test_welcome_context_menu_keeps_the_window_actions(welcome_window, monkeypatch):
    from PySide6.QtGui import QContextMenuEvent
    from annotshot import welcome
    w = welcome_window
    menus = []
    class Menu:
        def __init__(self, parent):
            self.actions = []
        def addSeparator(self):
            pass
        def addAction(self, action):
            self.actions.append(action)
        def exec(self, pos):
            menus.append(self.actions)
        def deleteLater(self):
            pass
    monkeypatch.setattr(welcome, "QMenu", Menu)
    event = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(10, 10), QPoint(20, 20))
    w.welcome.contextMenuEvent(event)
    assert event.isAccepted() and len(menus) == 1
    assert [a for a in menus[0] if not a.isSeparator()] == [
        a for a in w.menu_actions(False) if a is not None]
    for action in (w.a_help, w.a_feedback, w.a_about, w.a_recent, w.a_quit):
        assert action in menus[0] and action.isEnabled()
    assert not w.a_copy.isEnabled() and not w.a_save.isEnabled()


def test_failed_capture_from_welcome_shows_its_message(welcome_window, rig, monkeypatch):
    from annotshot import mainwindow
    w = welcome_window
    w.show()
    monkeypatch.setattr(w, "_may_record_screen", lambda: True)
    monkeypatch.setattr(mainwindow.QTimer, "singleShot", lambda _ms, callback: callback())
    def start(mode=None):
        w._capture_pending = False
        session, _ = rig.start(mode=mode)
        w._capture = session
        session.finished.connect(w._capture_done)
    monkeypatch.setattr(w, "_start_capture", start)
    w.capture()
    session = w._capture
    session.error = "Could not read the screen."
    session._finish(None)
    assert w.isVisible() and w.state_name == "welcome"
    assert w.welcome.status_label.isVisible()
    assert w.welcome.status_label.text() == "Capture failed: Could not read the screen."


def test_stale_welcome_thumbnail_shows_its_message(welcome_window, white):
    w = welcome_window
    path = w.recent_store.file(white)
    w.welcome.refresh()
    w.show()
    button = w.welcome.recent_buttons[0]
    path.unlink()
    button.click()
    assert w.state_name == "welcome" and w.welcome.status_label.isVisible()
    assert w.welcome.status_label.text() == "That capture is no longer in the Recent folder"


def test_launch_file_problem_shows_on_welcome(welcome_window, monkeypatch, tmp_path, qapp):
    from annotshot import app as app_module
    w = welcome_window
    monkeypatch.setattr(app_module, "MainWindow", lambda: w)
    monkeypatch.setattr(app_module.filetype, "register", lambda: None)
    monkeypatch.setattr(app_module.filetype, "user_choice", lambda: None)
    monkeypatch.setattr(qapp, "exec", lambda: 0)
    try:
        assert app_module.main(["annotshot", str(tmp_path / "missing.annotshot")]) == 0
        assert w.state_name == "welcome" and w.welcome.status_label.isVisible()
        assert w.welcome.status_label.text() == "Could not find missing.annotshot"
    finally:
        qapp.removeEventFilter(qapp._annotshot_file_filter)


def test_welcome_message_timeout_keeps_the_layout(welcome_window, qapp):
    w = welcome_window
    w.show()
    qapp.processEvents()
    page = w.welcome
    widgets = [page.open_link, page.intro, page.key_row.row_widget,
               page.privacy_row.row_widget, page.capture_bar, page.recent_heading]
    before = [widget.geometry() for widget in widgets]
    label = page.status_label
    assert label.y() >= page.open_link.geometry().bottom()
    assert not label.wordWrap()
    w.statusBar().showMessage("A current message " * 20, 30)
    qapp.processEvents()
    assert label.text() == w.statusBar().currentMessage()
    assert w.size().toTuple() == (640, 430)
    assert [widget.geometry() for widget in widgets] == before
    for _ in range(20):
        if not w.statusBar().currentMessage():
            break
        QTest.qWait(10)
    assert not w.statusBar().currentMessage() and label.text() == ""
    assert [widget.geometry() for widget in widgets] == before


def test_welcome_does_not_offer_background_without_tray(background_window):
    w, fake = background_window
    assert not w.welcome.running_row.row_widget.isHidden()
    fake.tray_available = False
    w.welcome.refresh()
    assert w.welcome.running_row.row_widget.isHidden()


@pytest.mark.parametrize("state", ["maximized", "full_screen"])
def test_welcome_leaves_expanded_editor_state(welcome_window, white, qapp, state):
    from annotshot.scene import Document
    w = welcome_window
    w._bind(Document(white))
    w.showMaximized() if state == "maximized" else w.showFullScreen()
    qapp.processEvents()
    assert w.isMaximized() or w.isFullScreen()
    w.clear_picture()
    assert w.state_name == "welcome"
    assert not w.isMaximized() and not w.isFullScreen()
    assert w.size().toTuple() == (640, 430)


@pytest.mark.parametrize("state", ["normal", "maximized", "full_screen"])
def test_close_hides_editor_before_binding_welcome(background_window, white, monkeypatch, state):
    from annotshot.scene import Document
    w, _ = background_window
    w._bind(Document(white))
    if state == "maximized":
        w.showMaximized()
    elif state == "full_screen":
        w.showFullScreen()
    else:
        w.show()
    visible_at_bind = []
    bind = w._bind
    def record_bind(doc):
        visible_at_bind.append(w.isVisible())
        bind(doc)
    monkeypatch.setattr(w, "_bind", record_bind)
    w.close()
    assert visible_at_bind == [False] and w.state_name == "welcome"
    assert not w.isVisible()


def test_freeze_transitions_and_mode_changes_stay_unselected(rig):
    session, _ = rig.start(last_area={"screen": "main", "x": 120, "y": 120,
                                      "width": 200, "height": 100})
    session.set_freeze(True)
    settle(session)
    session.set_freeze(False)
    assert session.selected is None and all(ov.area.isEmpty() for ov in session.overlays)
    assert not session.bar.same_area_button.isHidden()
    assert "Return" not in session.overlays[0].hint()
    session.set_mode("window")
    session.set_mode("area")
    assert session.selected is None and all(ov.area.isEmpty() for ov in session.overlays)


def test_linux_close_quits_and_never_promises_background(background_window, monkeypatch, qapp):
    from annotshot import mainwindow
    w, fake = background_window
    assert fake.tray_available and w.tray is None and w.can_hide_on_close() and w.capture_key_text()
    monkeypatch.setattr(mainwindow.sys, "platform", "linux")
    w.configure_background()
    assert not w.can_hide_on_close() and qapp.quitOnLastWindowClosed()
    assert w.welcome.running_row.row_widget.isHidden()
    w.show()
    assert w.close() and not w.isVisible() and w._quitting


def test_linux_background_checkbox_is_disabled(welcome_window, monkeypatch):
    from annotshot import settings_dialog
    monkeypatch.setattr(settings_dialog.sys, "platform", "linux")
    dialog = settings_dialog.SettingsDialog(welcome_window)
    try:
        assert not dialog.keep_running.isEnabled()
        assert dialog.keep_running.toolTip() == "Not available on Linux yet"
    finally:
        dialog.deleteLater()


@pytest.mark.parametrize("platform", ["mac", "windows", "linux"])
@pytest.mark.parametrize("freeze", [False, True])
@pytest.mark.parametrize("stored", [False, True])
def test_capture_start_never_selects_stored_area(rig, platform, freeze, stored):
    if platform == "windows":
        rig.monkeypatch.setattr(rig.cap, "IS_WINDOWS", True)
        rig.monkeypatch.setattr(rig.cap, "win32", SimpleNamespace(
            monitors=lambda: {}, list_windows=lambda: [],
            window_under_point=lambda *a, **k: None))
    elif platform == "linux":
        rig.monkeypatch.setattr(rig.cap.macos, "IS_MAC", False)
    settings = {"last_area": {"screen": "main", "x": 120, "y": 120,
                              "width": 200, "height": 100}} if stored else {}
    session, results = rig.start(freeze=freeze, **settings)
    assert session.selected is None
    if platform != "linux" and freeze:
        settle(session)
    assert session.selected is None and not results
    assert not hasattr(session, "has_same_area")
    for ov in session.overlays:
        if platform == "linux":
            assert type(ov) is rig.cap.CaptureOverlay and ov._press is None
        else:
            assert ov.area.isEmpty() and ov.preview.isEmpty()
            assert "Return" not in ov.hint()
    if platform == "linux":
        assert session.bar is None
    else:
        assert session.bar.same_area_button.isHidden() == (not stored)
        assert session.bar.same_area_button.accessibleName() == "Same area"
        assert session.bar.same_area_button.toolTip() == "Capture the same area as last time"
        assert session.bar.same_area_button.objectName() != "shoot"


@pytest.mark.parametrize("freeze", [False, True])
def test_same_area_hover_draws_preview_only_and_leave_clears_it(rig, freeze):
    session, results = rig.start(freeze=freeze, last_area={
        "screen": "second", "x": 120, "y": 120, "width": 200, "height": 100})
    if freeze:
        settle(session)
    ov = session.overlays[1]
    button = session.bar.same_area_button
    labels = []
    rig.monkeypatch.setattr(ov, "_draw_label", lambda painter, rect, label: labels.append((rect, label)))
    QCoreApplication.sendEvent(button, QEnterEvent(QPoint(), QPoint(), QPoint()))
    assert ov.preview == QRectF(120, 120, 200, 100)
    assert session.overlays[0].preview.isEmpty()
    assert session.selected is None and all(o.area.isEmpty() for o in session.overlays)
    image = QImage(ov.size(), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    ov.render(image)
    assert labels == [(QRectF(120, 120, 200, 100), "Same area")]
    assert image.pixelColor(119, 170).red() == rig.cap.FRAME.red()
    for key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
        QTest.keyClick(button, key)
        QTest.keyClick(ov, key)
    assert session.state == "idle" and not results and session.selected is None
    QCoreApplication.sendEvent(button, QEvent(QEvent.Leave))
    assert all(o.preview.isEmpty() and o.area.isEmpty() for o in session.overlays)
    labels.clear()
    ov.render(image)
    assert labels == [] and session.selected is None
    assert not session._settle.isActive() and not session._countdown.isActive()


@pytest.mark.parametrize("key", [Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space, "double_click"])
def test_freeze_keys_require_a_selection_from_this_session(rig, key):
    session, results = rig.start(freeze=True, last_area={
        "screen": "main", "x": 10, "y": 10, "width": 20, "height": 30})
    settle(session)
    ov = session.overlays[0]
    if key == "double_click":
        QTest.mouseDClick(ov, Qt.LeftButton, pos=QPoint(150, 150))
        QTest.mouseRelease(ov, Qt.LeftButton, pos=QPoint(150, 150))
    else:
        QTest.keyClick(ov, key)
    assert session.selected is None and not results
    # Return can confirm the current drag before its release.
    QTest.mousePress(ov, Qt.LeftButton, pos=QPoint(120, 120))
    QTest.mouseMove(ov, QPoint(320, 220))
    assert session.selected is ov and ov.area == QRectF(120, 120, 200, 100)
    if key == "double_click":
        QTest.mouseDClick(ov, Qt.LeftButton, pos=QPoint(150, 150))
    else:
        QTest.keyClick(ov, key)
    QTest.mouseRelease(ov, Qt.LeftButton, pos=QPoint(320, 220))
    assert len(results) == 1 and results[0].image.size().toTuple() == (400, 200)


def test_drag_from_window_inside_old_area_takes_only_new_area(rig):
    with_window(rig)
    session, results = rig.start(last_area={
        "screen": "main", "x": 120, "y": 120, "width": 200, "height": 100})
    drag(session.overlays[0], QPoint(150, 150), QPoint(250, 200))
    assert session.state == "shooting"
    settle(session)
    assert results[0].title is None and results[0].image.size().toTuple() == (200, 100)
    assert session.settings.value("capture/last_area") == {
        "screen": "main", "x": 150.0, "y": 150.0, "width": 100.0, "height": 50.0}


def test_real_case_size_requires_same_area_button(rig):
    rig.screens[0]._geometry = QRect(0, 0, 2560, 1440)
    session, results = rig.start(last_area={
        "screen": "main", "x": 10, "y": 10, "width": 989.5, "height": 513.5})
    ov = session.overlays[0]
    assert session.selected is None and ov.area.isEmpty()
    QTest.keyClick(ov, Qt.Key_Return)
    assert session.state == "idle" and not results
    session.bar.same_area_button.click()
    assert ov.area_pixels() == QRect(20, 20, 1979, 1027)
    settle(session)
    assert results[0].image.size().toTuple() == (1979, 1027)


def test_same_area_manual_and_help_describe_only_the_button():
    from annotshot.help import help_markdown
    root = Path(__file__).resolve().parents[1]
    manual = (root / "docs" / "USER-MANUAL.md").read_text()
    help_text = help_markdown([], manual)
    assert "**Same area**" in manual and "Hover over it to preview" in manual
    assert "No key or double-click takes the last area" in manual
    assert "Same area is a button on the capture bar" in help_text
    assert "No key takes the last area" in help_text
    assert "Return: same area" not in help_text
    assert "Return for the same area" not in help_text
