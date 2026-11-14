"""Live capture guards. All windows use offscreen Qt; native services are fakes."""
import ctypes
import importlib
import os
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QKeySequence, QMouseEvent, QPixmap
from PySide6.QtTest import QTest


class Screen:
    def __init__(self, name="main", geometry=QRect(0, 0, 900, 600), dpr=2):
        self._name, self._geometry, self._dpr = name, geometry, dpr
        self.calls = []
        self.before_grab = lambda: None

    def name(self):
        return self._name

    def geometry(self):
        return QRect(self._geometry)

    def devicePixelRatio(self):
        return self._dpr

    def grabWindow(self, ident):
        self.before_grab()
        self.calls.append(ident)
        image = QImage(round(self._geometry.width() * self._dpr),
                       round(self._geometry.height() * self._dpr), QImage.Format_RGB32)
        image.fill(QColor("#336699"))
        return QPixmap.fromImage(image)


@pytest.fixture
def rig(qapp, monkeypatch):
    cap = importlib.import_module("annotshot.capture")
    monkeypatch.setattr(cap, "IS_WINDOWS", False)
    monkeypatch.setattr(cap.macos, "IS_MAC", True)
    monkeypatch.setattr(cap.macos, "float_above_menu_bar", lambda _: False)
    monkeypatch.setattr(cap.macos, "list_windows", lambda: [])
    monkeypatch.setattr(cap.macos, "window_picture", lambda _: None)
    # The real compositor is caller-owned; deliberately simulate its capability.
    monkeypatch.setattr(cap.LiveOverlay, "supports_translucency", lambda _: True)
    screens = [Screen(), Screen("second", QRect(-800, 50, 800, 600), 1.5)]
    monkeypatch.setattr(cap.QGuiApplication, "screens", lambda: screens)
    monkeypatch.setattr(cap.QGuiApplication, "primaryScreen", lambda: screens[0] if screens else None)
    monkeypatch.setattr(cap.QCursor, "pos", lambda: QPoint(100, 100))
    sessions = []

    def start(mode=None, **settings):
        store = cap.QSettings("Annotshot", "Annotshot")
        for key, value in settings.items():
            store.setValue("capture/" + key, value)
        session = cap.CaptureSession()
        results = []
        session.finished.connect(results.append)
        sessions.append(session)
        session.start(mode)
        return session, results

    yield SimpleNamespace(cap=cap, screens=screens, start=start, monkeypatch=monkeypatch)
    for session in sessions:
        session._finish(None)
    qapp.processEvents()


def settle(session):
    """Deliver the single-shot timeout explicitly; never sleep in timer tests."""
    assert session._settle.isActive()
    session._settle.stop()
    session._settled()
    for _ in range(100):
        if session.state != "window-picture" or session._done:
            break
        QTest.qWait(10)


def drag(overlay, a=QPoint(120, 120), b=QPoint(320, 220)):
    QTest.mousePress(overlay, Qt.LeftButton, pos=a)
    QTest.mouseMove(overlay, b)
    QTest.mouseRelease(overlay, Qt.LeftButton, pos=b)


def test_live_start_has_no_still_and_one_translucent_overlay_per_screen(rig):
    session, results = rig.start()
    assert not results and all(not s.calls for s in rig.screens)
    assert len(session.overlays) == 2
    for ov, screen in zip(session.overlays, rig.screens):
        assert ov.geometry() == screen.geometry()
        assert ov.testAttribute(Qt.WA_TranslucentBackground)
        assert not ov.testAttribute(Qt.WA_QuitOnClose)
        for flag in (Qt.FramelessWindowHint, Qt.WindowStaysOnTopHint,
                     Qt.Tool, Qt.NoDropShadowWindowHint):
            assert ov.windowFlags() & flag
        assert ov.grab.image.isNull() and not ov.isFullScreen()


def test_live_shot_hides_all_before_grab_and_uses_existing_offset_mapping(rig):
    session, results = rig.start()
    ov = session.overlays[1]
    # Same menu-bar displacement regression as s3, on a mixed-DPI second screen.
    ov.setGeometry(ov.grab.geometry.translated(0, 24))
    session.select(ov, QRectF(120, 120, 200, 100))
    assert not results and all(not s.calls for s in rig.screens)
    hidden = []
    rig.screens[1].before_grab = lambda: hidden.append(all(not o.isVisible() for o in session.overlays))
    original_grab = rig.screens[1].grabWindow
    def marked_grab(ident):
        image = original_grab(ident).toImage()
        # 120 logical px + 24 px menu-bar offset, at 1.5x, is y=216.
        image.setPixelColor(180, 216, QColor("red"))
        return QPixmap.fromImage(image)
    rig.monkeypatch.setattr(rig.screens[1], "grabWindow", marked_grab)
    session.shoot()
    assert session._settle.interval() == rig.cap.SHOT_SETTLE_MS == 120
    assert not results and all(not s.calls for s in rig.screens)
    settle(session)
    assert hidden == [True] and rig.screens[0].calls == []
    assert rig.screens[1].calls == [0]
    assert len(results) == 1 and results[0].image.size().toTuple() == (300, 150)
    assert results[0].image.devicePixelRatio() == 1
    assert results[0].image.pixelColor(0, 0) == QColor("red")
    assert rig.cap.last_shot_ms >= 0
    session._finish(None)
    session._settled()
    assert len(results) == 1


def test_drag_replaces_remembered_area_and_release_shoots(rig):
    session, results = rig.start(last_area={
        "screen": "main", "x": 120, "y": 120, "width": 200, "height": 100})
    ov = session.overlays[0]
    drag(ov, QPoint(300, 200), QPoint(400, 250))
    assert ov.area_pixels() == QRect(600, 400, 200, 100)
    assert session.state == "shooting" and results == []
    assert all(not s.calls for s in rig.screens)
    settle(session)
    assert results[0].image.size().toTuple() == (200, 100)


def test_no_area_means_no_shot(rig):
    session, results = rig.start()
    ov = session.overlays[0]
    QTest.keyClick(ov, Qt.Key_Return)
    QTest.mouseDClick(ov, Qt.LeftButton, pos=QPoint(350, 225))
    QTest.mouseRelease(ov, Qt.LeftButton, pos=QPoint(350, 225))
    session.shoot()
    assert not results and not session._settle.isActive()
    assert all(not s.calls for s in rig.screens)


def test_bar_is_child_pill_with_accessible_controls_and_moves_with_pointer(rig):
    session, _ = rig.start()
    bar = session.bar
    assert bar.parentWidget() is session.overlays[0]
    for button in [*bar.mode_buttons.values(), bar.timer_button, bar.freeze_button,
                   bar.whole_screen_button, bar.same_area_button, bar.cancel_button]:
        assert button.accessibleName() and button.toolTip()
    assert sum(b.isChecked() for b in bar.mode_buttons.values()) == 0
    assert [a.text() for a in bar.timer_actions.values()] == ["Off", "3 s", "5 s", "10 s"]
    assert bar.y() + bar.pill_rect().bottom() == bar.parentWidget().height() - 80
    assert bar.same_area_button.toolTip() == "Capture the same area as last time"
    session.pointer_on(session.overlays[1])
    assert bar.parentWidget() is session.overlays[1] and bar.isVisible()
    assert bar.x() == (session.overlays[1].width() - bar.width()) // 2


def test_live_paint_keeps_selection_alpha_one_and_frame_outside(rig):
    session, _ = rig.start()
    ov = session.overlays[0]
    session.select(ov, QRectF(120, 120, 200, 100))
    image = QImage(ov.size(), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    ov.render(image)
    assert image.pixelColor(200, 170).alpha() == 1
    assert 101 <= image.pixelColor(50, 170).alpha() <= 104
    assert image.pixelColor(120, 170).alpha() == 1
    assert image.pixelColor(119, 170).red() == rig.cap.FRAME.red()


def test_mode_timer_freeze_and_last_area_survive_new_session(rig):
    first, _ = rig.start()
    ov = first.overlays[1]
    drag(ov)
    assert first.state == "shooting"
    settle(first)
    again, _ = rig.start()
    assert again.selected is None
    assert all(ov.area.isEmpty() for ov in again.overlays)
    assert not again.bar.same_area_button.isHidden()
    again.set_mode("window")
    again.set_timer(5)
    again.set_freeze(True)
    settle(again)
    again._finish(None)
    third, _ = rig.start()
    assert (third.mode, third.timer, third.freeze) == ("area", 5, True)
    settle(third)
    assert third.bar.freeze_button.isChecked() and not third.bar.timer_button.isEnabled()


@pytest.mark.parametrize("freeze", [False, True])
@pytest.mark.parametrize("saved", [
    None, {}, "not an area",
    {"screen": "unplugged", "x": 10, "y": 10, "width": 20, "height": 30},
    {"screen": "main", "x": 850, "y": 10, "width": 200, "height": 30},
    {"screen": "main", "x": -1, "y": 10, "width": 200, "height": 30},
    {"screen": "main", "x": "bad", "y": 10, "width": 200, "height": 30},
    {"screen": "main", "x": float("nan"), "y": 10, "width": 200, "height": 30},
    {"screen": "main", "x": 10, "y": 10, "width": float("inf"), "height": 30},
    {"screen": "main", "x": 10, "y": 10, "width": 0, "height": 30},
    {"screen": "main", "x": 10, "y": 10, "width": -20, "height": 30},
    {"screen": "main", "x": 10, "y": 10, "width": 20},
])
def test_invalid_stored_area_hides_button_and_cannot_capture(rig, saved, freeze):
    session, results = rig.start(last_area=saved, freeze=freeze)
    if freeze:
        settle(session)
    assert session.selected is None
    assert all(ov.area.isEmpty() for ov in session.overlays)
    assert session.bar.same_area_button.isHidden()
    # Even a stale callback cannot reach a capture with invalid stored data.
    session.bar.same_area_button.click()
    assert session.state == "idle" and not results and session.selected is None
    assert not session._settle.isActive() and not session._countdown.isActive()


def test_pointer_outside_all_screens_uses_primary(rig):
    rig.monkeypatch.setattr(rig.cap.QCursor, "pos", lambda: QPoint(9000, -9000))
    session, _ = rig.start()
    assert session.bar.parentWidget() is session.overlays[0]
    assert session.selected is None


def test_platform_without_translucency_starts_frozen(rig):
    rig.monkeypatch.setattr(rig.cap.LiveOverlay, "supports_translucency", lambda _: False)
    session, _ = rig.start()
    assert session.freeze and session._forced_freeze
    assert all(not ov.isVisible() for ov in session.overlays)
    settle(session)
    assert all(s.calls == [0] for s in rig.screens)
    assert all(not ov._pix.isNull() for ov in session.overlays)
    assert not session.bar.timer_button.isEnabled()
    # Capability fallback does not replace the user's preference.
    assert not session.settings.value("capture/freeze", False, type=bool)


def test_stored_freeze_drag_captures_immediately_from_still(rig):
    session, results = rig.start(freeze=True)
    assert all(not s.calls for s in rig.screens)
    settle(session)
    ov = session.overlays[0]
    assert ov.hint() == rig.cap.HINT_OTHER
    drag(ov)
    assert len(results) == 1 and results[0].image.size().toTuple() == (400, 200)
    assert all(s.calls == [0] for s in rig.screens)


def test_unchecking_freeze_returns_to_live_without_another_grab(rig):
    session, results = rig.start(freeze=True)
    settle(session)
    session.set_freeze(False)
    assert not session.freeze and session.bar.timer_button.isEnabled()
    assert all(ov._pix.isNull() for ov in session.overlays)
    drag(session.overlays[0])
    assert not results and all(s.calls == [0] for s in rig.screens)
    assert session.state == "shooting"


def test_timer_waits_ticks_then_settles_without_sleep(rig):
    rig.monkeypatch.setattr(rig.cap, "COUNTDOWN_TICK_MS", 50_000)
    rig.monkeypatch.setattr(rig.cap, "SHOT_SETTLE_MS", 50_000)
    session, results = rig.start(timer=3)
    drag(session.overlays[0])
    assert session.state == "countdown"
    assert session._countdown.interval() == 50_000
    assert session.remaining == 3 and session.bar.countdown.text() == "3 s"
    for remaining in (2, 1):
        session._tick()
        assert session.remaining == remaining
        assert not results and all(not s.calls for s in rig.screens)
        assert session.overlays[0].isVisible()
    session._tick()
    assert session.state == "shooting" and not session._countdown.isActive()
    assert all(not s.calls for s in rig.screens)
    settle(session)
    assert len(results) == 1


@pytest.mark.parametrize("phase", ["idle", "countdown", "shooting", "freezing"])
@pytest.mark.parametrize("cancel", ["escape", "right", "button"])
def test_cancel_at_every_stage_emits_once_and_stale_timers_cannot_grab(rig, phase, cancel):
    session, results = rig.start()
    ov = session.overlays[0]
    session.select(ov, QRectF(120, 120, 200, 100))
    if phase == "countdown":
        session.set_timer(10)
        session.shoot()
    elif phase == "shooting":
        session.shoot()
    elif phase == "freezing":
        session.set_freeze(True)
    if cancel == "escape":
        QTest.keyClick(ov, Qt.Key_Escape)
    elif cancel == "right":
        QTest.mouseClick(session.bar.freeze_button, Qt.RightButton)
    else:
        session.bar.cancel_button.click()
    session._tick()
    session._settled()
    assert results == [None] and all(not s.calls for s in rig.screens)


def test_window_mode_refreshes_on_entry_and_press_and_clips_mac_points(rig):
    calls = []
    window = SimpleNamespace(hwnd=42, rect=QRectF(-900, 100, 400, 200), title="Player — Fly-through")
    rig.monkeypatch.setattr(rig.cap.macos, "list_windows", lambda: calls.append(1) or [window])
    session, results = rig.start()
    session.set_mode("window")
    assert len(calls) == 2
    ov = session.overlays[1]
    # Offscreen's cursor cannot visit a fake negative-origin monitor; deliver
    # the same Qt mouse move directly instead of moving the real cursor.
    move = QMouseEvent(QEvent.MouseMove, QPointF(100, 100), QPointF(-700, 150),
                       Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    rig.cap.QGuiApplication.sendEvent(ov, move)
    assert ov._hover is window
    assert ov.hint() == "Click a window to capture it · Esc to cancel"
    QTest.mousePress(ov, Qt.LeftButton, pos=QPoint(100, 100))
    assert len(calls) == 3 and not results
    assert session.state == "idle" and not session._settle.isActive()
    assert ov.area_pixels() == QRect(0, 75, 450, 300)
    QTest.mouseRelease(ov, Qt.LeftButton, pos=QPoint(100, 100))
    assert session.state == "shooting" and not results
    settle(session)
    session._finish(None)
    session._settled()
    assert len(results) == 1
    assert results[0].title == window.title
    assert results[0].image.size().toTuple() == (450, 300)


def test_windows_window_pick_uses_physical_monitor_origin_and_excludes_overlays(rig):
    window = SimpleNamespace(hwnd=1234, title="Notepad", rect=QRect(-650, 200, 300, 150))
    calls = []
    def under(x, y, exclude, windows):
        calls.append((x, y, exclude))
        return next((w for w in windows if w.hwnd not in exclude and w.rect.contains(x, y)), None)
    rig.monkeypatch.setattr(rig.cap, "IS_WINDOWS", True)
    rig.monkeypatch.setattr(rig.cap, "win32", SimpleNamespace(
        monitors=lambda: {"second": QRect(-800, 50, 1200, 900)},
        list_windows=lambda: [window], window_under_point=under))
    session, results = rig.start(mode="window")
    ov = session.overlays[1]
    QTest.mouseClick(ov, Qt.LeftButton, pos=QPoint(150, 150))
    assert ov.area_pixels() == QRect(150, 150, 300, 150)
    assert calls[-1][0:2] == (-575, 275)
    assert calls[-1][2] == {int(o.winId()) for o in session.overlays}
    assert session.state == "shooting"
    settle(session)
    assert results[0].title == "Notepad" and results[0].image.width() == 300


@pytest.mark.parametrize("mode", ["window", "screen"])
def test_frozen_window_and_whole_screen_clicks_capture_from_still(rig, mode):
    window = SimpleNamespace(hwnd=42, rect=QRectF(100, 100, 200, 150), title="Player")
    rig.monkeypatch.setattr(rig.cap.macos, "list_windows", lambda: [window])
    session, results = rig.start(mode=mode, freeze=True, timer=10)
    settle(session)
    if mode == "screen":
        assert session.selected is session.overlays[0]
        assert session.bar.capture_button.isEnabled()
    QTest.mouseClick(session.overlays[0], Qt.LeftButton, pos=QPoint(150, 150))
    assert len(results) == 1 and not session._countdown.isActive()
    expected = (400, 300) if mode == "window" else (1800, 1200)
    assert results[0].image.size().toTuple() == expected
    assert all(s.calls == [0] for s in rig.screens)


def test_whole_screen_tracks_bar_and_grabs_only_that_screen(rig):
    session, results = rig.start()
    session.pointer_on(session.overlays[1])
    session.bar.whole_screen_button.click()
    settle(session)
    assert results[0].image.size().toTuple() == (1200, 900)
    assert rig.screens[0].calls == []


def test_linux_keeps_original_frozen_overlay_and_no_bar(rig):
    rig.monkeypatch.setattr(rig.cap.macos, "IS_MAC", False)
    session, results = rig.start()
    assert all(type(ov) is rig.cap.CaptureOverlay for ov in session.overlays)
    assert session.bar is None and all(s.calls == [0] for s in rig.screens)
    drag(session.overlays[0])
    assert results[0].image.size().toTuple() == (400, 200)


def test_no_screens_and_screen_detached_during_settle_cancel_once(rig):
    session, results = rig.start(mode="screen")
    session.shoot()
    rig.screens.clear()
    settle(session)
    assert results == [None]
    empty, results = rig.start()
    assert results == [None] and empty.overlays == []


def mac_row(**kw):
    return {"kCGWindowLayer": 0, "kCGWindowOwnerPID": os.getpid() + 1,
            "kCGWindowNumber": 42, "kCGWindowBounds": QRectF(-100, 50, 400, 200),
            "kCGWindowOwnerName": "Player", "kCGWindowName": "Movie", **kw}


def test_mac_window_list_parser_filters_own_process_and_layers_preserving_z_order(monkeypatch):
    from annotshot import macos
    monkeypatch.setattr(macos, "IS_MAC", True)
    rows = [mac_row(kCGWindowLayer=3), mac_row(kCGWindowOwnerPID=os.getpid()),
            mac_row(), mac_row(kCGWindowNumber=43, kCGWindowName="")]
    monkeypatch.setattr(macos, "_window_info", lambda: rows)
    windows = macos.list_windows()
    assert [w.hwnd for w in windows] == [42, 43]
    assert [w.title for w in windows] == ["Player — Movie", "Player"]
    assert windows[0].rect == QRectF(-100, 50, 400, 200)


@pytest.mark.parametrize("rows", [None, {}, [None], [{}], [mac_row(), "broken"],
                                  [mac_row(kCGWindowBounds="wrong")]])
def test_malformed_mac_window_dictionary_list_returns_empty(monkeypatch, rows):
    from annotshot import macos
    monkeypatch.setattr(macos, "IS_MAC", True)
    monkeypatch.setattr(macos, "_window_info", lambda: rows)
    assert macos.list_windows() == []


def test_mac_window_enumeration_failure_and_off_mac_return_empty(monkeypatch):
    from annotshot import macos
    def broken():
        raise OSError("No CoreGraphics")
    monkeypatch.setattr(macos, "_window_info", broken)
    monkeypatch.setattr(macos, "IS_MAC", True)
    assert macos.list_windows() == []
    monkeypatch.setattr(macos, "IS_MAC", False)
    assert macos.list_windows() == []


class NativeFunction:
    def __init__(self, callback):
        self.callback = callback
        self.calls = []
    def __call__(self, *args):
        self.calls.append(args)
        return self.callback(*args)


def test_new_default_digit_is_registered_by_both_native_backends(qapp, monkeypatch):
    from annotshot import hotkey
    assert hotkey.DEFAULT == "Ctrl+Shift+2"
    seq = QKeySequence(hotkey.DEFAULT)
    user = SimpleNamespace(RegisterHotKey=NativeFunction(lambda *args: 1),
                           UnregisterHotKey=NativeFunction(lambda *args: 1))
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: user, raising=False)
    win = hotkey.WinBackend(lambda: None)
    assert win.register(seq) is None
    assert user.RegisterHotKey.calls == [(None, hotkey.HOTKEY_ID,
        hotkey.MOD_NOREPEAT | hotkey.MOD_CONTROL | hotkey.MOD_SHIFT, 0x32)]
    win.unregister()
    qapp.removeNativeEventFilter(win._filter)
    carbon = SimpleNamespace(
        GetApplicationEventTarget=NativeFunction(lambda: 1),
        InstallEventHandler=NativeFunction(lambda *a: 0),
        RegisterEventHotKey=NativeFunction(lambda *a: 0),
        UnregisterEventHotKey=NativeFunction(lambda *a: 0))
    monkeypatch.setattr(ctypes, "CDLL", lambda *a, **k: carbon)
    mac = hotkey.MacBackend(lambda: None)
    assert mac.register(seq) is None
    assert carbon.RegisterEventHotKey.calls[0][:2] == (19, hotkey.CMD_KEY | hotkey.SHIFT_KEY)
    mac.unregister()


def test_previously_stored_hotkey_is_not_replaced(qapp):
    from annotshot.mainwindow import MainWindow
    cap = importlib.import_module("annotshot.capture")
    settings = cap.QSettings("Annotshot", "Annotshot")
    # The existing main-window preference path must remain untouched.
    settings.setValue("hotkey/sequence", "Ctrl+Shift+A")
    window = MainWindow()
    try:
        assert window.hotkey_sequence() == QKeySequence("Ctrl+Shift+A")
    finally:
        window.deleteLater()


def test_native_mac_list_uses_onscreen_flags_cg_bounds_and_releases_array(monkeypatch):
    """Exercise the ctypes adapter as well as the plain-dictionary parser."""
    from annotshot import macos
    values = {}
    def pointer(value):
        ident = len(values) + 1
        values[ident] = value
        return ident
    row = {"kCGWindowLayer": pointer(0),
           "kCGWindowOwnerPID": pointer(os.getpid() + 1),
           "kCGWindowNumber": pointer(42),
           "kCGWindowBounds": pointer({"X": -100, "Y": 50, "Width": 400, "Height": 200}),
           "kCGWindowOwnerName": pointer("Player"),
           "kCGWindowName": pointer("Movie")}
    array = pointer([pointer(row)])
    kinds = {list: 1, dict: 2, int: 3, str: 4}
    def number(ref, kind, out):
        assert kind == 4
        ctypes.cast(out, ctypes.POINTER(ctypes.c_int64))[0] = values[ref]
        return True
    def string(ref, buf, capacity, encoding):
        assert encoding == 0x08000100
        buf.value = values[ref].encode("utf-8")
        return True
    def bounds(ref, out):
        data = values[ref]
        rect = ctypes.cast(out, ctypes.POINTER(macos._CGRect)).contents
        rect.origin.x, rect.origin.y = data["X"], data["Y"]
        rect.size.width, rect.size.height = data["Width"], data["Height"]
        return True
    cg = SimpleNamespace(CGWindowListCopyWindowInfo=NativeFunction(lambda *_: array),
                         CGRectMakeWithDictionaryRepresentation=NativeFunction(bounds))
    cf = SimpleNamespace(
        CFRelease=NativeFunction(lambda _: None),
        CFGetTypeID=NativeFunction(lambda ref: kinds[type(values[ref])]),
        CFArrayGetTypeID=NativeFunction(lambda: 1),
        CFDictionaryGetTypeID=NativeFunction(lambda: 2),
        CFNumberGetTypeID=NativeFunction(lambda: 3),
        CFStringGetTypeID=NativeFunction(lambda: 4),
        CFArrayGetCount=NativeFunction(lambda ref: len(values[ref])),
        CFArrayGetValueAtIndex=NativeFunction(lambda ref, i: values[ref][i]),
        CFDictionaryGetValue=NativeFunction(lambda ref, key: values[ref].get(key)),
        CFNumberGetValue=NativeFunction(number),
        CFStringGetLength=NativeFunction(lambda ref: len(values[ref])),
        CFStringGetCString=NativeFunction(string))
    monkeypatch.setattr(macos, "IS_MAC", True)
    monkeypatch.setattr(macos, "_cg", lambda: cg)
    monkeypatch.setattr(macos, "_lib", lambda _: cf)
    monkeypatch.setattr(ctypes.c_void_p, "in_dll", lambda lib, name: SimpleNamespace(value=name))
    windows = macos.list_windows()
    assert [w.title for w in windows] == ["Player — Movie"]
    assert windows[0].rect == QRectF(-100, 50, 400, 200)
    assert cg.CGWindowListCopyWindowInfo.calls == [(17, 0)]
    assert len(cg.CGRectMakeWithDictionaryRepresentation.calls) == 1
    assert cf.CFRelease.calls == [(array,)]
    # A malformed native dictionary is rejected, and the retained array freed.
    del row["kCGWindowBounds"]
    assert macos.list_windows() == []
    assert cf.CFRelease.calls == [(array,), (array,)]


@pytest.mark.parametrize("theme_name", ["Light", "Dark", "Retro"])
def test_bar_and_live_alpha_are_independent_of_app_theme(rig, qapp, theme_name):
    from annotshot import theme
    from PySide6.QtGui import QPalette
    theme.apply(qapp, theme_name)
    session, _ = rig.start()
    ov, bar = session.overlays[0], session.bar
    session.select(ov, QRectF(120, 120, 200, 100))
    image = QImage(ov.size(), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    ov.render(image)
    assert min(image.bits().cast("B")[3::4]) >= 1
    assert image.pixelColor(200, 170).alpha() == 1
    for button in (*bar.mode_buttons.values(), bar.freeze_button, bar.same_area_button):
        assert button.font().pixelSize() == 14
    assert bar.same_area_button.palette().color(QPalette.ButtonText) == QColor("white")
    assert bar.same_area_button.objectName() != "shoot"
    pill = QImage(bar.size(), QImage.Format_ARGB32)
    pill.fill(Qt.transparent)
    bar.render(pill)
    color = pill.pixelColor(rig.cap.GLOW_MARGIN + 3, pill.height() // 2)
    assert color.getRgb() == (20, 20, 20, 235)


def test_window_press_on_no_window_clears_selection_and_takes_nothing(rig):
    session, results = rig.start(mode="window")
    ov = session.overlays[0]
    session.select(ov, QRectF(100, 100, 200, 150), "Old window")
    QTest.mousePress(ov, Qt.LeftButton, pos=QPoint(400, 100))
    assert session.selected is None and ov.area.isEmpty() and ov.title is None
    QTest.mouseRelease(ov, Qt.LeftButton, pos=QPoint(400, 100))
    assert session.state == "idle" and not session._settle.isActive()
    assert not results and all(not screen.calls for screen in rig.screens)


def test_start_screen_is_one_action_on_the_bar_screen(rig):
    session, results = rig.start(mode="screen")
    assert session.selected is session.overlays[0] and session.state == "shooting"
    settle(session)
    assert len(results) == 1 and results[0].image.size().toTuple() == (1800, 1200)
    assert rig.screens[0].calls == [0] and rig.screens[1].calls == []


@pytest.mark.parametrize("marked", [False, True])
def test_area_plain_click_takes_nothing_and_keeps_the_mark(rig, marked):
    session, results = rig.start()
    ov = session.overlays[0]
    rect = QRectF(100, 100, 200, 100) if marked else QRectF()
    if marked:
        session.select(ov, rect)
    QTest.mouseClick(ov, Qt.LeftButton, pos=QPoint(500, 100))
    assert ov.area == rect
    assert session.selected is (ov if marked else None)
    assert session.state == "idle" and not session._settle.isActive()
    assert not results and all(not screen.calls for screen in rig.screens)


@pytest.mark.parametrize("freeze", [False, True])
@pytest.mark.parametrize("seconds", [0, 3])
@pytest.mark.parametrize("mode", [None, "area", "window"])
def test_same_area_button_takes_stored_pixels_on_its_screen(rig, freeze, seconds, mode):
    first, _ = rig.start()
    drag(first.overlays[1])
    settle(first)
    saved = first.settings.value("capture/last_area")
    session, results = rig.start(mode=mode, freeze=freeze, timer=seconds)
    if freeze:
        settle(session)
    ov = session.overlays[1]
    assert session.selected is None and all(o.area.isEmpty() for o in session.overlays)
    assert not session.bar.same_area_button.isHidden()
    assert session.bar.same_area_button.objectName() != "shoot"
    before = [list(screen.calls) for screen in rig.screens]
    QTest.mouseClick(session.bar.same_area_button, Qt.LeftButton)
    if not freeze:
        assert session.selected is ov and ov.area_pixels() == QRect(180, 180, 300, 150)
        assert session.state == ("countdown" if seconds else "shooting")
        assert [screen.calls for screen in rig.screens] == before
        for _ in range(seconds):
            session._tick()
        settle(session)
    assert len(results) == 1 and results[0].image.size().toTuple() == (300, 150)
    assert results[0].title is None
    assert session.settings.value("capture/last_area") == saved


@pytest.mark.parametrize("mode", [None, "area", "window"])
@pytest.mark.parametrize("press_elsewhere", [False, True])
def test_release_without_press_on_same_overlay_takes_nothing(rig, mode, press_elsewhere):
    session, results = rig.start(mode=mode)
    first, second = session.overlays
    session.select(second, QRectF(100, 100, 200, 100), "Marked")
    if press_elsewhere:
        QTest.mousePress(first, Qt.LeftButton, pos=QPoint(100, 100))
    QTest.mouseRelease(second, Qt.LeftButton, pos=QPoint(200, 150))
    assert session.state == "idle" and not session._settle.isActive()
    assert not results and all(not screen.calls for screen in rig.screens)


@pytest.mark.parametrize("mode", ["area", "window", "screen"])
def test_release_with_timer_starts_countdown_and_overlay_mouse_input_is_ignored(rig, mode):
    window = SimpleNamespace(hwnd=42, rect=QRectF(100, 100, 300, 200), title="Moving picture")
    rig.monkeypatch.setattr(rig.cap.macos, "list_windows", lambda: [window])
    session, results = rig.start(mode=mode if mode != "screen" else None, timer=5)
    ov, other = session.overlays
    if mode == "area":
        drag(ov)
    elif mode == "screen":
        session.bar.whole_screen_button.click()
    else:
        QTest.mouseClick(ov, Qt.LeftButton, pos=QPoint(150, 150))
    assert session.state == "countdown" and session.remaining == 5
    assert session._countdown.isActive() and not session._settle.isActive()
    assert not results and all(not screen.calls for screen in rig.screens)
    selected, area, title = session.selected, QRectF(ov.area), ov.title
    bar_parent = session.bar.parentWidget()
    drag(other)
    QTest.mouseDClick(ov, Qt.LeftButton, pos=QPoint(200, 160))
    # QTest.mouseDClick sends the double-click press, not its final release.
    # Balance it even while capture ignores input, or later context menus
    # correctly refuse to open because Qt still reports LeftButton down.
    QTest.mouseRelease(ov, Qt.LeftButton, pos=QPoint(200, 160))
    assert not rig.cap.QGuiApplication.mouseButtons() & Qt.LeftButton
    assert session.selected is selected and ov.area == area and ov.title == title
    assert session.bar.parentWidget() is bar_parent and session.remaining == 5
    assert not results and all(not screen.calls for screen in rig.screens)


@pytest.mark.parametrize("mode,marked,freeze,expected", [
    ("area", False, False, "Drag to capture an area · Esc to cancel"),
    ("area", True, False, "Drag to capture an area · Esc to cancel"),
    ("window", False, False, "Click a window to capture it · Esc to cancel"),
    (None, False, False, "Drag to capture an area · Esc to cancel"),
    ("area", False, True, "Drag to capture an area · click for the whole screen · Esc to cancel"),
])
def test_live_hints_and_unchanged_frozen_hint(rig, mode, marked, freeze, expected):
    session, _ = rig.start(mode=mode, freeze=freeze)
    if freeze:
        settle(session)
    ov = session.overlays[0]
    if marked:
        session.select(ov, QRectF(100, 100, 200, 100))
    assert ov.hint() == expected


def test_failed_grab_emits_none_once_and_sets_plain_error(rig):
    def failed(*args, **kwargs):
        raise OSError("private platform details")
    rig.monkeypatch.setattr(rig.cap, "_grab_screen", failed)
    session, results = rig.start(mode="screen")
    assert session.error is None
    session.shoot()
    settle(session)
    assert results == [None] and session.error == "Could not read the screen."
    session._settled()
    session._finish(None)
    assert results == [None]


@pytest.mark.parametrize("failed", [False, True])
def test_capture_done_shows_error_for_eight_seconds_but_escape_is_silent(rig, failed):
    from annotshot.mainwindow import MainWindow
    window = MainWindow()
    session, results = rig.start()
    window._capture = session
    session.finished.connect(window._capture_done)
    status = window.statusBar()
    calls = []
    show_message = status.showMessage
    def record(text, timeout=0):
        calls.append((text, timeout))
        show_message(text, timeout)
    rig.monkeypatch.setattr(status, "showMessage", record)
    try:
        if failed:
            def broken(*args, **kwargs):
                raise RuntimeError("grab failed")
            rig.monkeypatch.setattr(rig.cap, "_grab_screen", broken)
            session.whole_screen()
            settle(session)
            assert calls == [("Capture failed: Could not read the screen.", 8000)]
            assert status.currentMessage() == calls[0][0]
        else:
            QTest.keyClick(session.overlays[0], Qt.Key_Escape)
            assert session.error is None and calls == []
        assert results == [None] and window._capture is None
    finally:
        window.hide()
        window.deleteLater()


def test_three_successive_sessions_keep_one_visible_bar_inside_pointer_overlay(rig):
    for _ in range(3):
        session, results = rig.start()
        bar = session.bar
        assert bar is not None
        for index in (0, 1, 0):
            overlay = session.overlays[index]
            session.pointer_on(overlay)
            assert session.bar is bar and bar.parentWidget() is overlay
            assert bar.isVisible() and overlay.rect().contains(bar.geometry())
            assert sum(len(o.findChildren(rig.cap.CaptureBar)) for o in session.overlays) == 1
            assert bar.x() == (overlay.width() - bar.width()) // 2
            assert bar.y() + bar.pill_rect().bottom() == overlay.height() - 80
        session.whole_screen()
        settle(session)
        assert len(results) == 1 and results[0] is not None


def test_show_overlays_places_shows_and_raises_bar(rig):
    session, _ = rig.start()
    bar, overlay = session.bar, session.overlays[0]
    calls = []
    place, show, raise_bar = bar.place, bar.show, bar.raise_
    for name, operation in (("place", place), ("show", show), ("raise_", raise_bar)):
        def record(op=operation, label=name):
            calls.append(label)
            op()
        rig.monkeypatch.setattr(bar, name, record)
    bar.hide()
    bar.move(0, 0)
    session._show_overlays(overlay)
    assert calls[-3:] == ["place", "show", "raise_"] and bar.isVisible()
    assert bar.y() + bar.pill_rect().bottom() == overlay.height() - 80
    calls.clear()
    session.pointer_on(session.overlays[1])
    assert calls[:3] == ["place", "show", "raise_"]


def test_overlay_resize_replaces_its_own_bar_with_glow_margin(rig, qapp):
    session, _ = rig.start()
    ov, other = session.overlays
    bar = session.bar
    for width, height in ((880, 580), (900, 600)):
        ov.resize(width, height)
        qapp.processEvents()
        assert bar.x() == (width - bar.width()) // 2
        assert bar.y() + bar.pill_rect().bottom() == height - 80
        assert bar.pill_rect().left() == bar.pill_rect().top() == 10
        assert bar.width() - bar.pill_rect().right() == 10
        assert bar.height() - bar.pill_rect().bottom() == 10
    kept = QRect(bar.geometry())
    other.resize(780, 580)
    qapp.processEvents()
    assert bar.geometry() == kept


def test_glow_pulses_twice_then_rests_at_full_strength(rig):
    session, _ = rig.start(mode="window")
    bar = session.bar
    assert rig.cap.GLOW == QColor(0, 200, 255) and rig.cap.GLOW_PULSE_MS == 700
    pulse = bar._pulse
    assert pulse.parent() is bar and pulse.duration() == 1400
    for time_ms, expected in ((0, 0.35), (467, 1.0), (933, 0.35), (1400, 1.0)):
        pulse.setCurrentTime(time_ms)
        assert bar._glow_factor == pytest.approx(expected, abs=0.002)
    assert pulse.state() == pulse.State.Stopped and bar._glow_factor == 1.0


def test_zero_pulse_uses_full_strength_glow_without_animation(rig):
    rig.monkeypatch.setattr(rig.cap, "GLOW_PULSE_MS", 0)
    def unavailable(*args, **kwargs):
        raise AssertionError("animation framework is unavailable")
    rig.monkeypatch.setattr(rig.cap, "QVariantAnimation", unavailable)
    session, _ = rig.start(mode="window")
    bar = session.bar
    assert bar._pulse is None and bar._glow_factor == 1.0
    image = QImage(bar.size(), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    bar.render(image)
    x = image.width() // 2
    # Straight top edge: each 3 px stroke, then the solid 2 px border.
    for y, alpha in ((2, 30), (5, 70), (8, 120), (10, 255)):
        color = image.pixelColor(x, y)
        assert color.alpha() == alpha
        assert color.green() == pytest.approx(200, abs=4) and color.blue() == 255
