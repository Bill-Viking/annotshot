"""0.3.0: the capture on macOS (where the overlay really sits, the
permission road, the hint), Clear and the empty hint, the right-click menu,
the shortcuts the user sets with the capture hotkey, and quick capture.
Everything runs offscreen; no real dialog or menu is ever shown."""
import importlib
import sys

import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, QSettings, Qt
from PySide6.QtGui import QColor, QImage, QKeySequence
from PySide6.QtTest import QTest


@pytest.fixture
def window(qapp):
    from annotshot.app import make_app
    from annotshot.mainwindow import MainWindow
    make_app()
    w = MainWindow()
    w.view.resize(900, 600)
    yield w
    w.deleteLater()


def picture(w=320, h=200, color="#336699"):
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(color))
    return img


# -- Ruling 3: capture on macOS ---------------------------------------------
def make_overlay(scale=2.0):
    from PySide6.QtGui import QGuiApplication
    from annotshot.capture import CaptureOverlay, ScreenGrab
    img = QImage(round(640 * scale), round(400 * scale), QImage.Format_RGB32)
    img.fill(QColor("#336699"))
    grab = ScreenGrab(QGuiApplication.primaryScreen(), img,
                      QRect(0, 0, 640, 400), scale,
                      QRect(0, 0, img.width(), img.height()))
    return CaptureOverlay(grab, [])


def test_the_overlay_maps_from_where_it_really_sits(qapp):
    """An overlay the OS put 24 px below the screen's top (macOS's menu bar)
    maps its (0, 0) to image pixel (0, 24 x scale), and a lit region drawn
    back lands where it was dragged."""
    ov = make_overlay(2.0)
    assert ov.to_device(QPointF(0, 0)) == QPoint(0, 0)
    ov.setGeometry(ov.grab.geometry.translated(0, 24))
    assert ov.offset() == QPoint(0, 24)
    assert ov.to_device(QPointF(0, 0)) == QPoint(0, 48)
    assert ov.to_device(QPointF(10, 10)) == QPoint(20, 68)
    back = ov.to_local(QRect(20, 68, 40, 40))
    assert (back.x(), back.y(), back.width()) == (10, 10, 20)
    ov.deleteLater()


def test_the_overlay_is_never_native_full_screen(qapp, monkeypatch):
    from annotshot import capture
    ov = make_overlay(1.0)
    lifted = []
    monkeypatch.setattr(capture.macos, "float_above_menu_bar",
                        lambda w: lifted.append(w) or False)
    monkeypatch.setattr(ov, "showFullScreen",
                        lambda: pytest.fail("showFullScreen called"))
    ov.show_on_screen()
    assert ov.isVisible() and not ov.isFullScreen()
    assert ov.geometry() == ov.grab.geometry and lifted == [ov]
    ov.close()


def test_the_overlay_says_how_to_capture(qapp):
    from annotshot import capture
    ov = make_overlay(1.0)
    hint = ov.hint()
    assert "Esc to cancel" in hint and hint.startswith("Drag to capture")
    if sys.platform == "win32":
        assert "click a window" in hint
    else:
        assert "click for the whole screen" in hint
    ov.resize(640, 400)
    img = QImage(640, 400, QImage.Format_ARGB32)
    img.fill(QColor("#000000"))
    ov.render(img)                              # paints the hint, no crash
    top = img.pixelColor(320, 20)               # the hint's dark box
    assert top.red() < 40 and top.green() < 40
    ov.deleteLater()
    assert capture.HINT_OTHER != capture.HINT_WINDOWS


def test_the_macos_module_imports_without_side_effects():
    macos = importlib.import_module("annotshot.macos")
    assert macos._libs == {}                     # nothing loaded on import


def test_the_permission_reads_true_off_macos(monkeypatch):
    from annotshot import macos
    monkeypatch.setattr(macos, "IS_MAC", False)
    assert macos.screen_capture_allowed() is True
    assert macos.open_privacy_settings() is False


def test_a_failing_permission_check_never_blocks(monkeypatch):
    """ASSUMES CoreGraphics has the preflight call: when it does not (or
    the framework will not load), the check reads as allowed."""
    from annotshot import macos
    monkeypatch.setattr(macos, "IS_MAC", True)

    def broken():
        raise OSError("no CoreGraphics")
    monkeypatch.setattr(macos, "_cg", broken)
    assert macos.screen_capture_allowed() is True
    macos.request_screen_capture()               # no raise


def test_floating_is_skipped_off_cocoa(qapp, monkeypatch):
    """ASSUMES winId() is an NSView on cocoa: on any other platform plugin
    (the offscreen tests) nothing is sent to it."""
    from annotshot import macos
    monkeypatch.setattr(macos, "IS_MAC", True)
    ov = make_overlay(1.0)
    assert macos.float_above_menu_bar(ov) is False
    ov.deleteLater()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_the_permission_check_answers_on_this_mac():
    from annotshot import macos
    assert isinstance(macos.screen_capture_allowed(), bool)


def test_no_permission_means_no_capture_and_the_message(window, monkeypatch):
    from annotshot import mainwindow
    asked, requested, started = [], [], []
    monkeypatch.setattr(mainwindow.macos, "IS_MAC", True)
    monkeypatch.setattr(mainwindow.macos, "screen_capture_allowed",
                        lambda: False)
    monkeypatch.setattr(mainwindow.macos, "request_screen_capture",
                        lambda: requested.append(1))
    monkeypatch.setattr(window, "_permission_message",
                        lambda: asked.append(1))
    monkeypatch.setattr(window, "_start_capture", lambda mode=None: started.append(1))
    monkeypatch.setattr(window, "_fresh_permission", lambda callback: callback("denied"))
    window.capture()
    QTest.qWait(mainwindow.CAPTURE_DELAY_MS + 100)
    assert asked == [1] and requested == [1] and started == []
    assert window._capture is None and window.isVisible()
    assert window.statusBar().currentMessage() == mainwindow.PERMISSION_STATUS == (
        "Capture is waiting for macOS to allow it")
    window.hide()


def test_with_permission_the_capture_starts(window, monkeypatch):
    from annotshot import mainwindow
    started = []
    monkeypatch.setattr(mainwindow.macos, "IS_MAC", True)
    monkeypatch.setattr(mainwindow.macos, "screen_capture_allowed",
                        lambda: True)
    monkeypatch.setattr(window, "_permission_message",
                        lambda: pytest.fail("asked with permission"))
    monkeypatch.setattr(window, "_start_capture", lambda mode=None: started.append(1))
    window.capture()
    QTest.qWait(mainwindow.CAPTURE_DELAY_MS + 100)
    assert started == [1]


# -- Ruling 2: Clear and the empty hint ---------------------------------------
def test_the_start_up_blank_is_a_placeholder_until_edited(qapp):
    from annotshot.items import RectItem
    from annotshot.scene import Document
    doc = Document()
    assert doc.is_placeholder
    r = RectItem()
    r.set_geom((10, 10, 40, 30))
    doc.add_items([r])                           # the first edit
    assert not doc.is_placeholder
    assert not Document(picture()).is_placeholder     # a capture
    assert Document(QImage()).is_placeholder         # a null picture: the blank


def test_an_opened_file_is_not_a_placeholder(qapp, tmp_path):
    from annotshot.scene import Document
    path = tmp_path / "a.annotshot"
    Document(picture()).save(path)
    assert not Document.load(path).is_placeholder


def test_the_placeholder_shows_the_hint_not_white(window):
    """On screen the empty start shows the canvas grey and two lines of
    hint; Copy image still gives the white page."""
    from annotshot.scene import CANVAS_COLOR
    from annotshot.view import EMPTY_HINT
    view = window.view
    view.resize(900, 600)
    shot = view.viewport().grab().toImage()
    corner = shot.pixelColor(shot.width() // 2, 10)
    assert corner.name() == CANVAS_COLOR.name()          # no white page
    inked = sum(1 for x in range(0, shot.width(), 2)
                for y in range(shot.height() // 2 - 40, shot.height() // 2 + 30, 2)
                if shot.pixelColor(x, y).name() != CANVAS_COLOR.name())
    assert inked > 50                                    # the hint's letters
    assert EMPTY_HINT[0] == "No picture yet"
    out = window.doc.render_image()
    assert out.pixelColor(10, 10) == QColor("#FFFFFF")


def test_clear_replaces_the_document_and_the_title(window, monkeypatch):
    from annotshot.scene import Document
    window._bind(Document(picture()))
    window.doc.path = "/somewhere/shot.annotshot"
    window.update_title()
    assert "shot.annotshot" in window.windowTitle()
    old = window.doc
    monkeypatch.setattr(window, "maybe_discard", lambda: True)
    window.a_clear.trigger()
    assert window.doc is not old and window.doc.is_placeholder
    assert window.windowTitle() == "Annotshot — Untitled[*]"
    assert window.statusBar().currentMessage() == "Picture closed"
    assert window.a_clear.shortcut() == QKeySequence("Ctrl+W")
    assert window.a_clear.toolTip().startswith(
        "Close this picture; kept captures stay in Recent captures")


def test_clear_keeps_the_picture_when_the_question_says_cancel(window,
                                                               monkeypatch):
    from annotshot.scene import Document
    window._bind(Document(picture()))
    kept = window.doc
    monkeypatch.setattr(window, "maybe_discard", lambda: False)
    window.clear_picture()
    assert window.doc is kept


# -- Ruling 1: the right-click menu ------------------------------------------
def menu_texts(menu):
    return ["|" if a.isSeparator() else a.text() for a in menu.actions()]


def with_rect(window):
    from annotshot.items import RectItem
    from annotshot.scene import Document
    window._bind(Document(picture(640, 360)))
    r = RectItem()
    r.set_geom((100, 80, 200, 120))
    window.doc.add_items([r])
    window.view.zoom_to_fit_or_100()
    window.view.set_zoom(1.0)
    window.view.centerOn(320, 180)
    return r, window.view.mapFromScene(QPointF(200, 140))


def test_the_menu_on_an_item_lists_the_item_actions(window):
    r, on_item = with_rect(window)
    assert not r.isSelected()
    menu = window.view.context_menu_at(on_item)
    assert menu_texts(menu) == ["Copy image", "Save…", "|", "Duplicate",
                                "Front", "Back", "Delete", "|", "Close picture",
                                "Capture", "Recent captures", "|", "Settings…", "Help",
                                "Send feedback…", "About Annotshot…", "|", "Quit Annotshot"]
    assert r.isSelected()                        # selected first
    assert menu.actions()[0] is window.a_copy    # the same actions
    menu.deleteLater()


def test_the_menu_on_empty_canvas_has_no_item_actions(window):
    r, _ = with_rect(window)
    empty = window.view.mapFromScene(QPointF(600, 340))
    menu = window.view.context_menu_at(empty)
    assert menu_texts(menu) == ["Copy image", "Save…", "|", "Close picture",
                                "Capture", "Recent captures", "|", "Settings…", "Help",
                                "Send feedback…", "About Annotshot…", "|", "Quit Annotshot"]
    menu.deleteLater()


def test_the_same_menu_with_a_tool_active(window):
    from annotshot.tools import Tool
    _, _ = with_rect(window)
    window.tool_actions[Tool.ARROW].trigger()
    empty = window.view.mapFromScene(QPointF(600, 340))
    menu = window.view.context_menu_at(empty)
    assert menu_texts(menu)[-10:] == ["Close picture", "Capture", "Recent captures",
                                     "|", "Settings…", "Help",
                                     "Send feedback…", "About Annotshot…", "|", "Quit Annotshot"]
    menu.deleteLater()


def test_a_right_click_mid_drag_cancels_and_shows_no_menu(window):
    from annotshot.tools import Tool
    _, _ = with_rect(window)
    view = window.view
    window.tool_actions[Tool.RECT].trigger()
    a = view.mapFromScene(QPointF(400, 250))
    QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, a)
    QTest.mouseMove(view.viewport(), a + QPoint(30, 30))
    assert view._press is not None
    QTest.mousePress(view.viewport(), Qt.RightButton, Qt.NoModifier,
                     a + QPoint(30, 30))
    assert view._press is None                   # the drag is cancelled
    assert view.context_menu_at(a + QPoint(30, 30)) is None
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, a)
    menu = view.context_menu_at(a)               # the next right-click: a menu
    assert menu is not None
    menu.deleteLater()


# -- Ruling 4: the keys the user sets, and the capture key --------------------
class FakeBackend:
    """Stands in for the system's hotkey call; `refuse` says it is taken."""
    available = True
    refuse = False
    registered: list = []

    def __init__(self, fire):
        self.fire = fire

    def register(self, seq):
        if FakeBackend.refuse:
            from annotshot.hotkey import TAKEN
            return TAKEN.format(key=seq.toString())
        FakeBackend.registered.append(seq.toString())
        return None

    def unregister(self):
        pass


@pytest.fixture
def fake_hotkey(window):
    from annotshot.hotkey import GlobalHotkey
    FakeBackend.refuse, FakeBackend.registered = False, []
    window.hotkey = GlobalHotkey(window, backend=FakeBackend)
    window.hotkey.activated.connect(window.capture_from_anywhere)
    return FakeBackend


def test_saved_shortcuts_apply_at_start(qapp, private_settings):
    from annotshot.mainwindow import MainWindow
    s = QSettings(private_settings, QSettings.IniFormat)
    s.setValue("shortcuts/copy", "Ctrl+K")
    s.setValue("shortcuts/rect", "R")
    s.setValue("shortcuts/delete", "Ctrl+D")      # clashes: default kept
    s.sync()
    w = MainWindow()
    assert w.a_copy.shortcut() == QKeySequence("Ctrl+K")
    assert w.a_copy.toolTip().endswith("(" + QKeySequence("Ctrl+K").toString(QKeySequence.NativeText) + ")")
    from annotshot.tools import Tool
    assert w.tool_actions[Tool.RECT].shortcut() == QKeySequence("R")
    assert w.a_delete.shortcut() == QKeySequence("Delete")
    w.deleteLater()


def test_a_key_in_use_is_refused_naming_the_other_action(window):
    problem = window.set_shortcut("copy", QKeySequence("Ctrl+D"))
    assert problem and "Duplicate" in problem
    assert window.a_copy.shortcut() == QKeySequence("Ctrl+C")
    assert window.settings.value("shortcuts/copy") is None
    assert "Deselect" in window.set_shortcut("copy", QKeySequence("Esc"))
    assert window.set_shortcut("copy", QKeySequence("Ctrl+K")) is None
    assert window.a_copy.shortcut() == QKeySequence("Ctrl+K")
    assert window.reset_shortcut("copy") is None
    assert window.a_copy.shortcut() == QKeySequence("Ctrl+C")


def test_ctrl_s_follows_the_saves_own_key(window):
    """The quick save follows Save…'s first key once it is changed."""
    assert window.set_shortcut("save", QKeySequence("Ctrl+K")) is None
    assert window.a_save.shortcuts() == [QKeySequence("Ctrl+K")]
    assert window.reset_shortcut("save") is None
    assert window.a_save.shortcuts()[0] == QKeySequence("Ctrl+S")


def test_the_capture_key_round_trips(window, fake_hotkey, private_settings):
    from annotshot.mainwindow import MainWindow
    assert window.hotkey_sequence() == QKeySequence("Ctrl+Shift+2")
    assert not window.hotkey_off()
    assert window.set_hotkey(QKeySequence("Ctrl+Alt+P"), off=False) is None
    assert fake_hotkey.registered[-1] == "Ctrl+Alt+P"
    window.settings.sync()
    again = MainWindow()                         # the same private file
    assert again.hotkey_sequence() == QKeySequence("Ctrl+Alt+P")
    assert window.set_hotkey(QKeySequence("Ctrl+Alt+P"), off=True) is None
    window.settings.sync()
    assert MainWindow().hotkey_off()
    again.deleteLater()


def test_the_capture_key_may_not_be_an_actions_key(window, fake_hotkey):
    problem = window.set_hotkey(QKeySequence("Ctrl+N"), off=False)
    assert problem and "Capture" in problem
    assert window.hotkey_sequence() == QKeySequence("Ctrl+Shift+2")
    # and an action may not take the capture key
    problem = window.set_shortcut("copy", QKeySequence("Ctrl+Shift+2"))
    assert problem and "Capture from anywhere" in problem


def test_a_key_the_system_refuses_says_so_and_stays_as_typed(window,
                                                             fake_hotkey):
    """ASSUMES the system registers a free key: when it refuses, one line
    says so and the setting stays as typed."""
    fake_hotkey.refuse = True
    problem = window.set_hotkey(QKeySequence("Ctrl+Alt+Q"), off=False)
    assert problem and "taken" in problem
    assert window.hotkey_sequence() == QKeySequence("Ctrl+Alt+Q")
    assert "taken" in window.statusBar().currentMessage()


def test_the_capture_key_brings_the_window_back_then_captures(window,
                                                              fake_hotkey,
                                                              monkeypatch):
    started = []
    monkeypatch.setattr(window, "capture", lambda: started.append(1))
    window.showMinimized()
    window.hotkey._get().fire()                  # as the system would
    assert started == [1] and not window.isMinimized()
    window.hide()


def test_a_plain_letter_is_not_a_capture_key():
    from annotshot import hotkey
    assert hotkey.check(QKeySequence("A")) == hotkey.NEED_MODIFIER
    assert hotkey.check(QKeySequence("F5")) is None
    assert hotkey.check(QKeySequence("Ctrl+Shift+A")) is None


def test_the_windows_filter_reads_a_wm_hotkey_message():
    """The filter is written from the Win32 documentation; here a MSG shaped
    like the one the system posts is read back."""
    import ctypes
    from annotshot import hotkey
    fired = []
    f = hotkey.WinHotkeyFilter(lambda: fired.append(1))
    msg = hotkey.MSG(None, hotkey.WM_HOTKEY, hotkey.HOTKEY_ID, 0x410006)
    addr = ctypes.addressof(msg)
    assert hotkey.hotkey_id(addr) == hotkey.HOTKEY_ID
    assert f.nativeEventFilter(b"windows_dispatcher_MSG", addr) == (True, 0)
    assert fired == [1]
    other = hotkey.MSG(None, 0x0100, hotkey.HOTKEY_ID, 0)     # WM_KEYDOWN
    assert f.nativeEventFilter(b"windows_generic_MSG",
                               ctypes.addressof(other)) == (False, 0)
    assert f.nativeEventFilter(b"xcb_generic_event_t", addr) == (False, 0)
    assert fired == [1]
    assert hotkey.win_combo(QKeySequence("Ctrl+Shift+A")) == (
        hotkey.MOD_NOREPEAT | hotkey.MOD_CONTROL | hotkey.MOD_SHIFT, 0x41)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_carbon_registers_and_unregisters_ctrl_shift_a(qapp):
    from annotshot import hotkey
    backend = hotkey.MacBackend(lambda: None)
    code, mods = hotkey.mac_combo(QKeySequence("Ctrl+Shift+A"))
    assert (code, mods) == (0, hotkey.CMD_KEY | hotkey.SHIFT_KEY)
    assert backend.register_code(code, mods) == 0
    assert backend.unregister() == 0


def test_no_capture_key_on_linux(window, monkeypatch):
    from annotshot import hotkey
    from annotshot.settings_dialog import SettingsDialog
    window.hotkey = hotkey.GlobalHotkey(window, backend=hotkey.NoBackend)
    assert window.apply_hotkey() is None         # nothing tried, nothing said
    d = SettingsDialog(window)
    assert not d.hotkey_edit.isEnabled() and not d.hotkey_off.isEnabled()
    d.deleteLater()


def test_the_settings_page_lists_every_action(window, fake_hotkey):
    from annotshot.mainwindow import SHORTCUT_ROWS
    from annotshot.settings_dialog import SettingsDialog
    d = SettingsDialog(window)
    assert [d.tabs.tabText(i) for i in range(d.tabs.count())] == [
        "Shortcuts", "Capture", "Look", "About"]      # Look: s3b3
    assert list(d.edits) == [k for k, _ in SHORTCUT_ROWS]
    assert len(SHORTCUT_ROWS) == 27
    d.edits["copy"].setKeySequence(QKeySequence("Ctrl+D"))
    problem = d.commit("copy")
    assert "Duplicate" in problem and d.message.text() == problem
    assert d.edits["copy"].keySequence() == QKeySequence("Ctrl+C")
    d.edits["copy"].setKeySequence(QKeySequence("Ctrl+K"))
    assert d.commit("copy") is None and d.message.text() == ""
    d._reset_all()
    assert window.a_copy.shortcut() == QKeySequence("Ctrl+C")
    assert d.edits["copy"].keySequence() == QKeySequence("Ctrl+C")
    d.deleteLater()


def test_settings_opens_from_ctrl_comma(window):
    assert window.a_settings.shortcut() == QKeySequence("Ctrl+,")


# -- Ruling 5: quick capture --------------------------------------------------
class FakeClipboard:
    def __init__(self):
        self.images = []

    def setImage(self, img):
        self.images.append(img)


def stub_clipboard(monkeypatch):
    from annotshot import mainwindow
    board = FakeClipboard()

    class App:
        @staticmethod
        def clipboard():
            return board
    monkeypatch.setattr(mainwindow, "QApplication", App)
    return board


def test_quick_capture_copies_then_minimizes(window, monkeypatch):
    from annotshot.capture import CaptureResult
    board = stub_clipboard(monkeypatch)
    window.settings.setValue("capture/copy", True)
    window.settings.setValue("capture/minimize", True)
    window._capture_done(CaptureResult(picture(1280, 720)))
    assert len(board.images) == 1 and board.images[0].width() == 1280
    assert window.isMinimized()
    assert window.statusBar().currentMessage() == \
        f"Copied 1280 × 720 — {QKeySequence(QKeySequence.Paste).toString(QKeySequence.NativeText)} to paste"
    assert not window.doc.undo_stack.needs_save()    # counts as exported
    window.showNormal()
    assert window.statusBar().currentMessage().startswith("Copied 1280")
    window.hide()


def test_copy_only_keeps_the_window(window, monkeypatch):
    from annotshot.capture import CaptureResult
    board = stub_clipboard(monkeypatch)
    window.settings.setValue("capture/copy", True)
    window._capture_done(CaptureResult(picture()))
    assert len(board.images) == 1 and not window.isMinimized()
    window.hide()


def test_minimize_alone_does_nothing(window, monkeypatch):
    """The second box counts only while the first is on."""
    from annotshot.capture import CaptureResult
    board = stub_clipboard(monkeypatch)
    window.settings.setValue("capture/copy", False)     # the first box off
    window.settings.setValue("capture/minimize", True)
    window._capture_done(CaptureResult(picture()))
    assert board.images == [] and not window.isMinimized()
    assert window.statusBar().currentMessage().startswith("Captured")
    window.hide()


def test_the_capture_tab_copy_starts_on_minimize_off_and_follow(window):
    from annotshot.settings_dialog import COPY_TEXT, MINIMIZE_TEXT, SettingsDialog
    d = SettingsDialog(window)
    assert d.quick_copy.text() == COPY_TEXT
    assert d.quick_minimize.text() == MINIMIZE_TEXT
    assert d.quick_copy.isChecked() and not d.quick_minimize.isChecked()
    assert d.quick_minimize.isEnabled() and window.quick_copy()
    d.quick_copy.setChecked(False)          # the user's pick is kept
    assert not d.quick_minimize.isEnabled() and not window.quick_copy()
    d.quick_copy.setChecked(True)
    assert d.quick_minimize.isEnabled() and window.quick_copy()
    d.quick_minimize.setChecked(True)
    assert window.quick_minimize()
    d.deleteLater()
