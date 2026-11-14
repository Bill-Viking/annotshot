"""The small opening screen, using the editor's actions and Recent store."""
from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMenu,
                               QToolButton, QVBoxLayout, QWidget)

from . import recent, theme
from .capture import BAR_STYLE, CaptureBar, GLOW_MARGIN


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
        self.key_row.linkActivated.connect(lambda _: window.open_shortcut_settings())
        self.copy_row = self._row(left, "copy-image")
        self.copy_row.setText("Every capture is copied, ready to paste.")
        self.privacy_row = self._row(left, "lock")
        self.privacy_row.linkActivated.connect(lambda _: window.show_privacy())
        self.running_row = self._row(left, "running")
        self.running_row.row_widget.hide()  # Filled by keep-running integration.
        self.open_link = QLabel('<a href="open">Open a saved file…</a>', self)
        self.open_link.linkActivated.connect(lambda _: window.a_open.trigger())
        left.addWidget(self.open_link)
        self.status_label = QLabel(self)
        self.status_label.setTextFormat(Qt.PlainText)
        # Use the existing space below Open without changing the layout.
        self.open_link.installEventFilter(self)
        window.statusBar().messageChanged.connect(self.status_label.setText)
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

    def eventFilter(self, watched, event):
        if watched is self.open_link and event.type() in (
                QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.FontChange):
            rect = self.open_link.geometry()
            rect.moveTop(rect.bottom() + 11)
            rect.setHeight(self.status_label.fontMetrics().height())
            self.status_label.setGeometry(rect)
        return super().eventFilter(watched, event)

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
        # ASSUMES: the capture key is set. Clearing it offers the setup link.
        seq = w.hotkey_sequence()
        key = "" if w.hotkey_off() or seq.isEmpty() else seq.toString(QKeySequence.NativeText)
        from html import escape
        self.key_row.setText(
            f'Capture from anywhere with {escape(key)} <a href="keys">Change keys</a>'
            if key else '<a href="keys">Set a key to capture from anywhere</a>')
        self.copy_row.row_widget.setVisible(w.quick_copy())
        where = "this Mac" if sys.platform == "darwin" else "this PC" if sys.platform == "win32" else "this computer"
        self.privacy_row.setText(
            f'Private. Your pictures stay on {where}. Annotshot sends nothing anywhere. '
            '<a href="privacy">How it stays private</a>')
        self.running_row.setText(
            f"Close this window and Annotshot keeps running; {escape(key)} still captures.")
        self.running_row.row_widget.setVisible(w.can_hide_on_close() and bool(key))
        self.capture_bar.refresh()
        self.refresh_recent()
        self.retheme()

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
