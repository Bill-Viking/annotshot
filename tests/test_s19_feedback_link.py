"""Opening-window feedback uses the existing action, entirely offscreen."""
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
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
    assert page.feedback_link.hasFocus(), page.focusWidget()
    QTest.keyClick(page.feedback_link, Qt.Key_Backtab)
    assert page.open_link.hasFocus()


def test_feedback_sits_right_of_open_on_the_same_line(feedback_window):
    page = feedback_window.welcome
    opened = page.open_link.geometry()
    feedback = page.feedback_link.geometry()
    assert feedback.left() - opened.right() - 1 == 16
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
        assert status.top() == page.open_link.geometry().bottom() + 11
        assert status.height() == page.status_label.fontMetrics().height()
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
    assert status.top() == page.open_link.geometry().bottom() + 11
    feedback_window.statusBar().showMessage("Feedback layout check")
    qapp.processEvents()
    assert page.status_label.text() == "Feedback layout check"
    assert [widget.geometry() for widget in widgets] == with_feedback

    # Reconstruct the original single-widget layout as a geometry reference.
    row = page.link_row
    left = row.parent()
    index = next(i for i in range(left.count()) if left.itemAt(i).layout() is row)
    row.removeWidget(page.open_link)
    page.feedback_link.hide()
    left.removeItem(row)
    left.insertWidget(index, page.open_link)
    left.activate()
    qapp.processEvents()
    # The original event filter uses the full-width Open geometry.
    expected_status = page.open_link.geometry()
    expected_status.moveTop(expected_status.bottom() + 11)
    expected_status.setHeight(page.status_label.fontMetrics().height())
    page.status_label.setGeometry(expected_status)
    assert status == expected_status
    assert page.open_link.pos() == open_position
    assert [widget.geometry() for widget in widgets] == with_feedback
    assert feedback_window.size() == window_size
    theme.apply(qapp, "Light")
