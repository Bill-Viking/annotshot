"""Opening-window feedback uses the existing action, entirely offscreen."""
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QDesktopServices, QKeyEvent, QTextDocument
from PySide6.QtTest import QSignalSpy, QTest

from test_s10_welcome import welcome_window


@pytest.fixture
def feedback_window(welcome_window, monkeypatch, qapp):
    def unexpected_browser(*args):
        pytest.fail("A welcome-link test tried to open a browser")

    monkeypatch.setattr(QDesktopServices, "openUrl", unexpected_browser)
    # Observe the real QAction signal without invoking its browser-opening slot.
    welcome_window.a_feedback.triggered.disconnect()
    welcome_window.show()
    welcome_window.activateWindow()
    qapp.processEvents()
    return welcome_window


def test_feedback_text_tooltip_and_link_style(feedback_window):
    page = feedback_window.welcome
    document = QTextDocument()
    document.setHtml(page.feedback_link.text())
    assert document.toPlainText() == "Send feedback…"
    assert page.feedback_link.toolTip() == feedback_window.a_feedback.toolTip()
    assert page.feedback_link.toolTip()
    assert page.feedback_link.styleSheet() == page.open_link.styleSheet()
    assert page.feedback_link.font() == page.open_link.font()
    assert page.feedback_link.textInteractionFlags() == page.open_link.textInteractionFlags()
    assert not page.feedback_link.openExternalLinks()


def test_feedback_mouse_click_triggers_existing_action(feedback_window):
    link = feedback_window.welcome.feedback_link
    spy = QSignalSpy(feedback_window.a_feedback.triggered)
    QTest.mouseClick(link, Qt.LeftButton, pos=QPoint(8, link.height() // 2))
    assert spy.count() == 1


@pytest.mark.parametrize("key", [Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space])
def test_feedback_keyboard_triggers_once_without_capturing(
        feedback_window, monkeypatch, key):
    page = feedback_window.welcome
    captures = []
    monkeypatch.setattr(feedback_window, "capture", lambda: captures.append(True))
    spy = QSignalSpy(feedback_window.a_feedback.triggered)
    page.open_link.setFocus(Qt.TabFocusReason)
    QTest.keyClick(page.open_link, Qt.Key_Tab)
    assert page.manual_link.hasFocus()
    QTest.keyClick(page.manual_link, Qt.Key_Tab)
    assert page.feedback_link.hasFocus(), page.focusWidget()
    QTest.keyClick(page.feedback_link, key)
    assert spy.count() == 1
    repeat = QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, "", True, 1)
    QCoreApplication.sendEvent(page.feedback_link, repeat)
    assert spy.count() == 1
    assert captures == []


@pytest.mark.parametrize("key", [Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space])
def test_open_keyboard_keeps_using_open_action(feedback_window, monkeypatch, key):
    calls = []
    monkeypatch.setattr(feedback_window.a_open, "trigger", lambda: calls.append("open"))
    monkeypatch.setattr(feedback_window, "capture", lambda: calls.append("capture"))
    link = feedback_window.welcome.open_link
    link.setFocus(Qt.TabFocusReason)
    QTest.keyClick(link, key)
    assert calls == ["open"]


def test_feedback_follows_open_in_both_tab_directions(feedback_window):
    page = feedback_window.welcome
    page.open_link.setFocus(Qt.TabFocusReason)
    assert page.open_link.hasFocus()
    QTest.keyClick(page.open_link, Qt.Key_Tab)
    assert page.manual_link.hasFocus()
    QTest.keyClick(page.manual_link, Qt.Key_Tab)
    assert page.feedback_link.hasFocus(), page.focusWidget()
    QTest.keyClick(page.feedback_link, Qt.Key_Backtab)
    assert page.manual_link.hasFocus()
    QTest.keyClick(page.manual_link, Qt.Key_Backtab)
    assert page.open_link.hasFocus()


def test_feedback_sits_right_of_open_on_the_same_line(feedback_window):
    page = feedback_window.welcome
    opened = page.open_link.geometry()
    feedback = page.feedback_link.geometry()
    assert feedback.left() - page.manual_link.geometry().right() - 1 == 16
    assert feedback.top() == opened.top()
    assert feedback.height() == opened.height()
    assert page.rect().contains(feedback)
    assert not feedback.intersects(page.recent_heading.geometry())


def test_status_tracks_link_row_through_window_resizes(feedback_window, qapp):
    page = feedback_window.welcome
    initial_size = feedback_window.size()
    # The welcome window starts with a fixed width; exercise layout resizing.
    feedback_window.setMinimumWidth(0)
    feedback_window.setMaximumWidth(initial_size.width() + 400)
    feedback_window.statusBar().showMessage("Feedback layout check " * 20)
    widths = []
    for extra_width in (0, 400, 200, 400, 0):
        feedback_window.resize(initial_size.width() + extra_width,
                               initial_size.height())
        qapp.processEvents()
        row = page.link_row.geometry()
        status = page.status_label.geometry()
        recent_left = page.recent_heading.mapTo(page, QPoint()).x()
        widths.append(row.width())
        assert status.width() == row.width()
        assert status.left() == row.left()
        assert status.right() < recent_left
        assert status.top() == page.open_link.geometry().bottom() + 1
        # A long message wraps and is shown whole (the key button fix of
        # 2026-11-20), so the line is as tall as its wrapped words need.
        assert status.height() > page.status_label.fontMetrics().height()
        assert status.height() >= page.status_label.heightForWidth(status.width())
    assert widths[1] > widths[2] > widths[0]
    assert widths[3] == widths[1]
    assert widths[4] == widths[0]


@pytest.mark.parametrize("theme_name", ["Light", "Dark", "Retro"])
def test_status_and_surrounding_layout_match_original_open_row(
        feedback_window, qapp, theme_name):
    from annotshot import theme

    page = feedback_window.welcome
    theme.apply(qapp, theme_name)
    page.refresh()
    qapp.processEvents()
    widgets = [page.status_label, page.intro, page.key_row.row_widget,
               page.copy_row.row_widget, page.privacy_row.row_widget,
               page.running_row.row_widget, page.capture_bar, page.recent_heading,
               page.settings_button]
    with_feedback = [widget.geometry() for widget in widgets]
    open_position = page.open_link.pos()
    window_size = feedback_window.size()
    status = page.status_label.geometry()
    assert status.left() == page.open_link.x()
    assert status.top() == page.open_link.geometry().bottom() + 1
    feedback_window.statusBar().showMessage("Feedback layout check")
    qapp.processEvents()
    assert page.status_label.text() == "Feedback layout check"
    assert [widget.geometry() for widget in widgets] == with_feedback

    links = (page.open_link, page.manual_link, page.feedback_link)
    for link in links:
        assert page.rect().contains(link.geometry())
        assert link.geometry().bottom() < status.top()
    for first, second in zip(links, links[1:]):
        assert not first.geometry().intersects(second.geometry())
    assert page.open_link.pos() == open_position
    assert feedback_window.size() == window_size
    theme.apply(qapp, "Light")


@pytest.mark.parametrize("key", [Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space])
@pytest.mark.parametrize("name", ["privacy_row", "open_link", "manual_link", "feedback_link"])
def test_s50_each_focused_link_owns_its_keys(feedback_window, monkeypatch, key, name):
    w = feedback_window
    page = w.welcome
    calls = []
    monkeypatch.setattr(w, "capture", lambda: calls.append("capture"))
    # The action slots are replaced only here; all four routes are observed.
    for action, destination in ((w.a_open, "open_link"), (w.a_help, "manual_link"),
                                (w.a_feedback, "feedback_link")):
        if action is not w.a_feedback:
            action.triggered.disconnect()
        action.triggered.connect(lambda _=False, d=destination: calls.append(d))
    page._link_destinations[page.privacy_row] = lambda: calls.append("privacy_row")
    link = getattr(page, name)
    link.setFocus(Qt.TabFocusReason)
    QTest.keyClick(link, key)
    assert calls == [name]
    QCoreApplication.sendEvent(link, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, "", True, 1))
    assert calls == [name]
    QTest.keyClick(link, Qt.Key_Tab)
    assert calls == [name]


def test_s50_manual_mouse_and_open_cancel_use_existing_actions(feedback_window, monkeypatch, qapp):
    from PySide6.QtWidgets import QFileDialog
    from test_s10_welcome import click_label_anchor
    w = feedback_window
    picks = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: picks.append(True) or ("", ""))
    click_label_anchor(w.welcome.open_link, "open", qapp)
    assert picks == [True] and w.state_name == "welcome"
    click_label_anchor(w.welcome.manual_link, "manual", qapp)
    assert w._help_window is not None and w._privacy_window is None
    assert "Keyboard shortcuts" in w._help_window.browser.toPlainText()
    w._help_window.close()


@pytest.mark.parametrize("theme_name", ["Light", "Dark", "Retro"])
def test_s50_wrapped_links_and_status_stay_in_visible_order(feedback_window, qapp, theme_name, white):
    from annotshot import theme
    page = feedback_window.welcome
    for _ in range(4):
        feedback_window.recent_store.file(white)
    theme.apply(qapp, theme_name)
    page.refresh()
    feedback_window.statusBar().showMessage("A capture could not be completed. Try another window. " * 3)
    qapp.processEvents()
    assert len(page.recent_buttons) == 4
    links = (page.open_link, page.manual_link, page.feedback_link)
    assert page.status_label.geometry().top() > max(link.geometry().bottom() for link in links)
    assert not page.status_label.geometry().intersects(page.capture_bar.geometry())
    assert page.rect().contains(page.status_label.geometry())
    recent_left = page.recent_heading.mapTo(page, QPoint()).x()
    assert page.status_label.geometry().right() < recent_left
    for link in links:
        assert link.geometry().right() < recent_left
    # Exercise the narrower-column path directly: whole links wrap in order.
    page.link_row.setGeometry(QRect(20, 200, 200, page.link_row.heightForWidth(200)))
    for first, second in zip(links, links[1:]):
        assert not first.geometry().intersects(second.geometry())
        assert (second.y(), second.x()) > (first.y(), first.x())
    assert page.status_label.y() > links[-1].geometry().bottom()


def test_s50_feedback_visible_link_requests_exact_chooser_once(welcome_window, monkeypatch, qapp):
    from annotshot.feedback import CHOOSER_URL
    from test_s10_welcome import click_label_anchor
    calls = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: calls.append(url.toString()) or True)
    monkeypatch.setattr(welcome_window, "capture", lambda: pytest.fail("capture"))
    welcome_window.show()
    qapp.processEvents()
    click_label_anchor(welcome_window.welcome.feedback_link, "feedback", qapp)
    assert calls == [CHOOSER_URL]
    assert welcome_window._help_window is None and welcome_window._privacy_window is None


@pytest.mark.parametrize("key", [Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space])
def test_s50_privacy_keyboard_opens_only_local_reader(welcome_window, monkeypatch, qapp, key):
    from annotshot import help
    monkeypatch.setattr(help, "open_url", lambda _: pytest.fail("URL"))
    monkeypatch.setattr(welcome_window, "capture", lambda: pytest.fail("capture"))
    welcome_window.show()
    welcome_window.activateWindow()
    qapp.processEvents()
    link = welcome_window.welcome.privacy_row
    link.setFocus(Qt.TabFocusReason)
    QTest.keyClick(link, key)
    reader = welcome_window._privacy_window
    assert reader is not None and welcome_window._help_window is None
    assert "Where pictures are kept" in reader.browser.toPlainText()
    reader.close()
    qapp.processEvents()
    assert link.hasFocus()
