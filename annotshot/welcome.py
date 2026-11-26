"""The small opening screen, using the editor's actions and Recent store."""
from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QKeyCombination, QSize, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMenu, QPushButton,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from . import hotkey, recent, theme
from .capture import BAR_STYLE, CaptureBar, GLOW_MARGIN
from .keywords import key_words


class _WelcomeLinkRow(QHBoxLayout):
    geometryChanged = Signal()

    def setGeometry(self, rect):
        super().setGeometry(rect)
        # The trailing stretch can resize the row without moving either link.
        self.geometryChanged.emit()


class KeyButton(QPushButton):
    """A secondary menu button whose word label wraps at its own width."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedWidth(166)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.StrongFocus)
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.label.setStyleSheet("padding: 0; background: transparent; border: 0;")
        self.face = "plain"

    def sizeHint(self):
        return QSize(166, max(34, self.height()))

    def minimumSizeHint(self):
        return self.sizeHint()

    def set_face(self, text, face):
        self.setText(text)
        self.face = face
        width = self.width() - 32
        lines, line = [], ""
        visible = ("✓ " if face == "green" else "") + text
        for word in visible.replace("+", "+ ").split():
            addition = (" " if line and not line.endswith("+") else "") + word
            if line and self.label.fontMetrics().horizontalAdvance(line + addition) > width:
                lines.append(line)
                line = word
            else:
                line += addition
        lines.append(line)
        self.label.setText("\n".join(lines))
        self.setFixedHeight(max(34, len(lines) * self.label.fontMetrics().height() + 16))
        color = {"plain": "white", "green": "#91efae", "amber": "#ffd283"}[face]
        self.label.setStyleSheet(f"color: {color}; padding: 0; background: transparent; border: 0;")
        self.label.setGeometry(6, 4, self.width() - 26, self.height() - 8)

    def paintEvent(self, event):
        from PySide6.QtWidgets import QStyle, QStyleOptionButton, QStylePainter
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""  # the child paints the wrapped label
        painter = QStylePainter(self)
        painter.drawControl(QStyle.CE_PushButton, option)


class InlineRecorder(QWidget):
    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.setFocusPolicy(Qt.StrongFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.prompt = QLabel("Press the new capture key.", self)
        self.draft = QLabel(self)
        self.error = QLabel(self)
        for label in (self.prompt, self.draft, self.error):
            label.setWordWrap(True)
            label.setTextFormat(Qt.PlainText)
            layout.addWidget(label)
        self.cancel = QPushButton("Cancel", self)
        self.cancel.clicked.connect(page.cancel_recording)
        layout.addWidget(self.cancel, 0, Qt.AlignLeft)

    def show_error(self, text):
        self.error.setText(text)
        self.error.setMinimumHeight(self.error.heightForWidth(max(1, self.width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.error.text():
            self.error.setMinimumHeight(self.error.heightForWidth(max(1, self.width())))

    def event(self, event):
        if event.type() == QEvent.ShortcutOverride:
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        event.accept()
        if event.isAutoRepeat():
            return
        if event.key() == Qt.Key_Escape and event.modifiers() == Qt.NoModifier:
            self.page.cancel_recording()
            return
        modifiers = (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta,
                     Qt.Key_AltGr)
        if event.key() in modifiers:
            words = key_words(QKeySequence(QKeyCombination(event.modifiers(), Qt.Key_Space)))
            self.draft.setText(words.removesuffix("+Space").removesuffix("Space"))
            return
        seq = QKeySequence(QKeyCombination(event.modifiers(), Qt.Key(event.key())))
        self.draft.setText(key_words(seq))
        w = self.page.window_
        problem = w.validate_capture_key(seq)
        w.set_hotkey(seq, w.hotkey_off())
        if problem:
            self.show_error(problem)

    def keyReleaseEvent(self, event):
        event.accept()
        modifiers = {Qt.Key_Control: Qt.ControlModifier, Qt.Key_Shift: Qt.ShiftModifier,
                     Qt.Key_Alt: Qt.AltModifier, Qt.Key_Meta: Qt.MetaModifier,
                     Qt.Key_AltGr: Qt.GroupSwitchModifier}
        if event.key() in modifiers:
            held = event.modifiers() & ~modifiers[event.key()]
            words = key_words(QKeySequence(QKeyCombination(held, Qt.Key_Space)))
            self.draft.setText(words.removesuffix("+Space").removesuffix("Space"))



class WelcomeCaptureBar(CaptureBar):
    """The live bar's pill and resting glow, with launch actions."""

    def __init__(self, window, parent):
        QWidget.__init__(self, parent)
        self.setObjectName("captureBar")
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setStyleSheet(BAR_STYLE)
        self._glow_factor = 1.0
        self._pulse = None
        self.window_ = window
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10 + GLOW_MARGIN, 6 + GLOW_MARGIN,
                                  10 + GLOW_MARGIN, 6 + GLOW_MARGIN)
        layout.setSpacing(2)
        self.mode_buttons = {}
        self.timer_button = None
        self.timer_actions = {}
        if sys.platform != "linux":
            for mode, label in (("area", "Area"), ("window", "Window"),
                                ("screen", "Whole screen")):
                button = self._button(label, f"Start {label.lower()} capture")
                button.clicked.connect(lambda _=False, m=mode: window.capture(m))
                self.mode_buttons[mode] = button
                layout.addWidget(button)
            self.timer_button = self._button("Timer", "Delay the live shot")
            menu = QMenu(self.timer_button)
            for seconds in (0, 3, 5, 10):
                action = menu.addAction("Off" if seconds == 0 else f"{seconds} s")
                action.setCheckable(True)
                action.triggered.connect(lambda _=False, n=seconds: self.set_timer(n))
                self.timer_actions[seconds] = action
            self.timer_button.setMenu(menu)
            layout.addWidget(self.timer_button)
        self.capture_button = self._button("Capture", "Capture an area or a window")
        self.capture_button.setObjectName("shoot")
        self.capture_button.clicked.connect(lambda: window.capture())
        layout.addWidget(self.capture_button)
        self.key_button = None
        if sys.platform != "linux":
            self.key_button = KeyButton(self)
            self.key_button.setToolTip("Capture key")
            self.key_menu = QMenu(self.key_button)
            self.key_button.setMenu(self.key_menu)
            self.key_menu.aboutToHide.connect(
                lambda: self.key_button.setFocus(Qt.OtherFocusReason))
            self.key_button.installEventFilter(parent)
            layout.addWidget(self.key_button)
        self.refresh()

    def set_timer(self, seconds):
        self.window_.settings.setValue("capture/timer", seconds)
        self.refresh()

    def refresh(self):
        try:
            seconds = int(self.window_.settings.value("capture/timer", 0))
        except (TypeError, ValueError):
            seconds = 0
        for value, action in self.timer_actions.items():
            action.setChecked(value == seconds)


class WelcomeWidget(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window_ = window
        self.setObjectName("welcome")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 12, 24, 10)
        outer.setSpacing(8)
        top = QHBoxLayout()
        top.addStretch()
        self.settings_button = QToolButton(self)
        self.settings_button.setDefaultAction(window.a_settings)
        self.settings_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        top.addWidget(self.settings_button)
        outer.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(22)
        left = QVBoxLayout()
        left.setSpacing(10)
        heading = QLabel("Capture, mark up, paste", self)
        font = heading.font()
        font.setPointSizeF(font.pointSizeF() * 1.35 if font.pointSizeF() > 0 else 18)
        font.setBold(True)
        heading.setFont(font)
        left.addWidget(heading)
        self.intro = QLabel("Take a picture of your screen, add arrows and notes, "
                            "and paste it where you need it.", self)
        self.intro.setWordWrap(True)
        left.addWidget(self.intro)
        self.key_row = self._row(left, "capture")
        self.key_row.setTextFormat(Qt.PlainText)
        self.recording = False
        self.recorder = InlineRecorder(self)
        self.key_row.row_widget.layout().addWidget(self.recorder, 1)
        self.recorder.hide()
        self.copy_row = self._row(left, "copy-image")
        self.copy_row.setText("Every capture is copied, ready to paste.")
        self.privacy_row = self._row(left, "lock")
        self.privacy_row.linkActivated.connect(lambda _: window.show_privacy())
        self.running_row = self._row(left, "running")
        self.running_row.row_widget.hide()  # Filled by keep-running integration.
        self.open_link = QLabel('<a href="open">Open a saved file…</a>', self)
        self.open_link.linkActivated.connect(lambda _: window.a_open.trigger())
        self.feedback_link = QLabel('<a href="feedback">Send feedback…</a>', self)
        self.feedback_link.linkActivated.connect(lambda _: window.a_feedback.trigger())
        self.feedback_link.setToolTip(window.a_feedback.toolTip())
        self.link_row = _WelcomeLinkRow()
        self.link_row.setContentsMargins(0, 0, 0, 0)
        self.link_row.setSpacing(16)
        for link in (self.open_link, self.feedback_link):
            link.setTextInteractionFlags(Qt.LinksAccessibleByMouse |
                                         Qt.LinksAccessibleByKeyboard)
            link.setFocusPolicy(Qt.StrongFocus)
            self.link_row.addWidget(link)
        self.link_row.addStretch()
        left.addLayout(self.link_row)
        QWidget.setTabOrder(self.open_link, self.feedback_link)
        self.status_label = QLabel(self)
        self.status_label.setTextFormat(Qt.PlainText)
        self.status_label.setWordWrap(True)
        self.status_label.installEventFilter(self)
        # Recompute wrapping when the links or theme change.
        self.link_row.geometryChanged.connect(self._place_status)
        self.open_link.installEventFilter(self)
        self.feedback_link.installEventFilter(self)
        window.statusBar().messageChanged.connect(self.refresh_status)
        self.status_label.setText(window.statusBar().currentMessage())
        left.addStretch()
        body.addLayout(left, 1)

        right = QWidget(self)
        right.setFixedWidth(120)
        self.recent_layout = QVBoxLayout(right)
        self.recent_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_layout.setSpacing(5)
        self.recent_heading = QLabel("Recent", right)
        self.recent_layout.addWidget(self.recent_heading)
        self.recent_buttons = []
        self.empty_recent = QLabel("Your captures appear here", right)
        self.empty_recent.setWordWrap(True)
        self.recent_layout.addWidget(self.empty_recent)
        self.recent_layout.addStretch()
        body.addWidget(right)
        outer.addLayout(body, 1)
        self.capture_bar = WelcomeCaptureBar(window, self)
        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(self.capture_bar)
        bottom.addStretch()
        outer.addLayout(bottom)
        self.refresh()
        self.recorder.cancel.installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is getattr(self, "status_label", None) and event.type() in (QEvent.Resize, QEvent.FontChange):
            self._place_status()
        key_button = getattr(getattr(self, "capture_bar", None), "key_button", None)
        if watched in (key_button, self.recorder.cancel) and event.type() == QEvent.ShortcutOverride:
            if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape):
                event.accept()
                return True
        if watched is key_button and event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if not event.isAutoRepeat():
                key_button.showMenu()
            return True
        if watched is self.recorder.cancel and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.cancel_recording()
            return True
        if watched in (self.open_link, self.feedback_link) and event.type() in (
                QEvent.ShortcutOverride, QEvent.KeyPress):
            if not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
                key = event.key()
                if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space,
                           Qt.Key_Tab, Qt.Key_Backtab):
                    # Focused links own these keys ahead of capture shortcuts.
                    if event.type() == QEvent.ShortcutOverride:
                        event.accept()
                        return True
                    if key in (Qt.Key_Tab, Qt.Key_Backtab):
                        forward = key == Qt.Key_Tab and not event.modifiers() & Qt.ShiftModifier
                        self.focusNextPrevChild(forward)
                    elif not event.isAutoRepeat():
                        action = (self.window_.a_open if watched is self.open_link
                                  else self.window_.a_feedback)
                        action.trigger()
                    event.accept()
                    return True
        if watched is self.open_link and event.type() in (
                QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.FontChange):
            self._place_status()
        return super().eventFilter(watched, event)

    def _place_status(self):
        from PySide6.QtCore import QRect
        label = self.status_label
        rect = self.open_link.geometry()
        rect.setWidth(self.link_row.geometry().width())
        rect.moveTop(rect.bottom() + 1)
        painted = label.fontMetrics().boundingRect(
            QRect(0, 0, max(1, rect.width()), 10000),
            Qt.TextWordWrap | Qt.AlignLeft, label.text())
        rect.setHeight(max(painted.height(), label.heightForWidth(rect.width())))
        label.setGeometry(rect)

    def _row(self, layout, icon):
        row = QWidget(self)
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        mark = QLabel(row)
        mark.setProperty("welcomeIcon", icon)
        mark.setFixedSize(16, 16)
        line.addWidget(mark, 0, Qt.AlignTop)
        label = QLabel(row)
        label.setWordWrap(True)
        label.setTextFormat(Qt.RichText)
        line.addWidget(label, 1)
        layout.addWidget(row)
        label.row_widget = row
        return label

    def refresh(self):
        w = self.window_
        self.refresh_key()
        self.copy_row.row_widget.setVisible(w.quick_copy())
        where = "this Mac" if sys.platform == "darwin" else "this PC" if sys.platform == "win32" else "this computer"
        self.privacy_row.setText(
            f'Private. Your pictures stay on {where}. Annotshot sends nothing anywhere. '
            '<a href="privacy">How it stays private</a>')
        self.running_row.setText("Close this window to keep Annotshot running.")
        self.running_row.row_widget.setVisible(w.can_hide_on_close())
        self.capture_bar.refresh()
        self.refresh_recent()
        self.retheme()

    def refresh_status(self, message=None):
        text = self.window_.statusBar().currentMessage()
        if text == self.window_.key_state()["line"]:
            text = ""
        self.status_label.setText(text)
        self._place_status()

    def refresh_key(self):
        state = self.window_.key_state()
        self.key_row.setText(state["line"])
        self.key_row.row_widget.setVisible(sys.platform != "linux")
        button = self.capture_bar.key_button if hasattr(self, "capture_bar") else None
        if button is not None:
            button.set_face(state["button"], state["face"])
            button.setAccessibleName(f'Capture key: {state["button"]}')
            previous = button.accessibleDescription()
            button.setAccessibleDescription(state["line"])
            if previous != state["line"]:
                from PySide6.QtGui import QAccessible, QAccessibleEvent
                QAccessible.updateAccessibility(QAccessibleEvent(button, QAccessible.DescriptionChanged))
            menu = self.capture_bar.key_menu
            menu.clear()
            commands = {"Try this key": self.window_.try_capture_key,
                        "Change key": self.start_recording,
                        "Turn off": lambda: self.window_.set_hotkey(self.window_.hotkey_sequence(), True),
                        "Turn on": lambda: self.window_.set_hotkey(self.window_.hotkey_sequence(), False),
                        "Retry turn off": lambda: self.window_.set_hotkey(self.window_.hotkey_sequence(), True)}
            for name in state["menu"]:
                menu.addAction(name).triggered.connect(commands[name])
        if hasattr(self, "status_label"):
            self.refresh_status()

    def start_recording(self):
        self.window_.end_key_interaction()
        self.window_._key_line = ""
        self.window_._key_edit_error = ""
        self.window_._key_status(self.window_._key_feedback,
                                  error=bool(self.window_._key_feedback))
        self.window_._publish_key()
        self.recording = True
        self.key_row.hide()
        self.recorder.draft.clear()
        self.recorder.error.clear()
        self.recorder.error.setMinimumHeight(0)
        self.recorder.show()
        self.recorder.setFocus(Qt.OtherFocusReason)

    def cancel_recording(self):
        if not self.recording:
            return
        self.recording = False
        self.recorder.draft.clear()
        self.recorder.error.clear()
        w = self.window_
        if w._key_edit_error:
            w._key_edit_error = ""
            w._key_status(w._key_feedback, error=bool(w._key_feedback))
            w._publish_key()
        self.recorder.hide()
        self.key_row.show()
        if self.capture_bar.key_button:
            self.capture_bar.key_button.setFocus(Qt.OtherFocusReason)

    def refresh_recent(self):
        for button in self.recent_buttons:
            self.recent_layout.removeWidget(button)
            button.hide()
            button.deleteLater()
        self.recent_buttons = []
        # ASSUMES: Recent can be read. A missing or unreadable store leaves
        # the small opening screen usable, with its empty line.
        try:
            paths = self.window_.recent_store.files()[:4]
            for path in paths:
                pixmap = recent.thumbnail(path, QSize(112, 42), self.devicePixelRatioF())
                if pixmap.isNull():
                    continue
                button = QToolButton(self)
                from PySide6.QtGui import QIcon
                button.setIcon(QIcon(pixmap))
                button.setIconSize(QSize(112, 42))
                button.setFixedSize(120, 64)
                button.setStyleSheet("QToolButton { padding: 2px; border: 0; }")
                button.setText(recent.time_label(recent.taken_at(path)))
                button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                button.setToolTip(path.name)
                button.setAccessibleName(f"Open capture {button.text()}")
                button.clicked.connect(lambda _=False, p=str(path): self.window_.open_recent(p))
                self.recent_layout.insertWidget(len(self.recent_buttons) + 1, button)
                self.recent_buttons.append(button)
        except Exception:
            pass
        self.empty_recent.setVisible(not self.recent_buttons)

    def retheme(self):
        from .mainwindow import themed_icon
        muted = theme.color("time-ink").name()
        self.empty_recent.setStyleSheet(f"color: {muted};")
        self.recent_heading.setStyleSheet(f"color: {muted};")
        self.status_label.setStyleSheet(f"color: {muted};")
        for label in self.findChildren(QLabel):
            icon = label.property("welcomeIcon")
            if icon:
                label.setPixmap(themed_icon(icon, size=16).pixmap(16, 16))

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        for action in self.window_.menu_actions(False):
            if action is None:
                menu.addSeparator()
            else:
                menu.addAction(action)
        menu.exec(event.globalPos())
        menu.deleteLater()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            if not event.isAutoRepeat():
                self.window_.capture()
            event.accept()
        else:
            super().keyPressEvent(event)
