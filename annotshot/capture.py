"""Live capture on Windows/macOS, with an optional frozen picture.

All crops use CaptureOverlay.to_device: overlay-local logical coordinates
plus the actual overlay offset, scaled to the selected screen's pixels.
CaptureOverlay itself keeps its original frozen contract (also Linux's UI).
"""
from __future__ import annotations

import sys
import math
import time
from dataclasses import dataclass

from PySide6.QtCore import (QEvent, QObject, QPoint, QPointF, QRect, QRectF,
                            QSettings, QTimer, Qt, Signal, QVariantAnimation,
                            QRunnable, QThreadPool)
from PySide6.QtGui import (QColor, QCursor, QFontMetrics, QGuiApplication,
                           QImage, QPainter, QPen, QPixmap, QScreen)
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QMenu,
                               QPushButton, QWidget)

IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    from . import win32
else:                                    # never load Win32 off Windows
    win32 = None
from . import macos

HINT_WINDOWS = "Drag to capture an area · click a window · Esc to cancel"
HINT_OTHER = "Drag to capture an area · click for the whole screen · Esc to cancel"

DIM = QColor(0, 0, 0, 102)          # 40 % dim outside the selection
FRAME = QColor("#E53935")
GLOW = QColor(0, 200, 255)
GLOW_PULSE_MS = 700
GLOW_MARGIN = 10
SHOT_SETTLE_MS = 120
COUNTDOWN_TICK_MS = 1000
last_shot_ms: float | None = None

MIN_DRAG = 4                        # logical px before a press is a drag


@dataclass
class ScreenGrab:
    screen: QScreen
    image: QImage       # device pixels, devicePixelRatio 1
    geometry: QRect     # the screen's logical geometry
    dpr: float          # the screen's devicePixelRatio
    phys: QRect         # the monitor's physical rect

    @property
    def scale(self) -> float:
        """Image pixels per logical pixel; reported dpr before the live grab."""
        return (self.image.width() / max(1, self.geometry.width())
                if not self.image.isNull() else self.dpr)


@dataclass
class CaptureResult:
    image: QImage
    title: str | None = None


def _scaled_rect(r: QRect, dpr: float) -> QRect:
    """A logical rect in device pixels (geometry x dpr)."""
    return QRect(round(r.x() * dpr), round(r.y() * dpr),
                 round(r.width() * dpr), round(r.height() * dpr))


def _monitor_rect(screen: QScreen, img: QImage, mons: dict) -> QRect:
    """The monitor's physical rect. Qt 6 names screens by model (not
    \\\\.\\DISPLAYn), so match by name first, then by origin and size:
    Qt keeps a screen's top-left in native pixels."""
    if screen.name() in mons:
        return mons[screen.name()]
    origin = screen.geometry().topLeft()
    for r in mons.values():
        if r.topLeft() == origin and r.size() == img.size():
            return r
    return QRect(origin, img.size())


def _monitors() -> dict:
    if IS_WINDOWS:
        try:
            return win32.monitors()
        except OSError:
            pass
    return {}


def _grab_screen(screen: QScreen, mons: dict | None = None,
                 *, shot_started: float | None = None) -> ScreenGrab:
    """The single capture road, shared by live shots and frozen capture."""
    if mons is None:
        mons = _monitors()
    if shot_started is not None:
        global last_shot_ms
        last_shot_ms = (time.perf_counter() - shot_started) * 1000
    img = screen.grabWindow(0).toImage().convertToFormat(QImage.Format_RGB32)
    img.setDevicePixelRatio(1.0)
    dpr = screen.devicePixelRatio()
    phys = (_monitor_rect(screen, img, mons) if IS_WINDOWS
            else _scaled_rect(screen.geometry(), dpr))
    return ScreenGrab(screen, img, screen.geometry(), dpr, phys)


def grab_all_screens() -> list[ScreenGrab]:
    mons = _monitors()
    return [_grab_screen(screen, mons) for screen in QGuiApplication.screens()]


class CaptureOverlay(QWidget):
    """One per screen: the frozen screenshot, dimmed, with a lit region or
    the highlighted window under the mouse."""

    picked = Signal(object)       # CaptureResult, or None when cancelled

    def __init__(self, grab: ScreenGrab, windows: list):
        super().__init__(None, Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose)
        # The main window is hidden while capturing: closing the last
        # overlay must not count as closing the app's last window.
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.grab = grab
        self.windows = windows
        self.exclude: set[int] = set()
        self._pix = QPixmap.fromImage(grab.image)
        self._pix.setDevicePixelRatio(grab.scale)
        self._press: QPointF | None = None
        self._cur: QPointF | None = None
        self._hover = None
        self.setGeometry(grab.geometry)

    def show_on_screen(self) -> None:
        # Never showFullScreen(): on macOS that is native full screen (a
        # Space slides in and the window lands below the menu bar).
        self.setGeometry(self.grab.geometry)
        self.show()
        if macos.float_above_menu_bar(self):  # macOS only; False elsewhere
            # macOS first shows the window 20 px short of the screen on each
            # side (measured 2540×1420 on a 2560×1440 display); once the
            # window floats above the menu bar the full geometry sticks.
            self.setGeometry(self.grab.geometry)
        self.raise_()
        self.activateWindow()
        self.setFocus()
        local = QPointF(self.mapFromGlobal(QCursor.pos()))
        if self.rect().contains(local.toPoint()):
            self._set_hover(local)

    # -- mapping ----------------------------------------------------------
    def offset(self) -> QPoint:
        """Where the overlay sits on its screen, in logical px (0, 0 when
        the OS put it exactly on the screen)."""
        return self.geometry().topLeft() - self.grab.geometry.topLeft()

    def to_device(self, p: QPointF) -> QPoint:
        s, o = self.grab.scale, self.offset()
        return QPoint(round((p.x() + o.x()) * s), round((p.y() + o.y()) * s))

    def to_physical(self, p: QPointF) -> QPoint:
        return self.grab.phys.topLeft() + self.to_device(p)

    def to_local(self, r: QRect) -> QRectF:
        s, o = self.grab.scale, self.offset()
        return QRectF(r.x() / s - o.x(), r.y() / s - o.y(),
                      r.width() / s, r.height() / s)

    def window_rect(self, w) -> QRect:
        """A window's bounds in this screen's image pixels, clipped."""
        return w.rect.translated(-self.grab.phys.topLeft()) \
            .intersected(self.grab.image.rect())

    def region(self) -> QRect:
        a, b = self.to_device(self._press), self.to_device(self._cur)
        r = QRect(min(a.x(), b.x()), min(a.y(), b.y()),
                  abs(a.x() - b.x()), abs(a.y() - b.y()))
        return r.intersected(self.grab.image.rect())

    def _dragging(self) -> bool:
        return (self._press is not None and self._cur is not None
                and (self._cur - self._press).manhattanLength() >= MIN_DRAG)

    def _window_at(self, local: QPointF):
        if not IS_WINDOWS:
            return None                  # no window list off Windows
        p = self.to_physical(local)
        return win32.window_under_point(p.x(), p.y(), self.exclude,
                                        windows=self.windows)

    def _set_hover(self, local: QPointF) -> None:
        w = self._window_at(local)
        if w != self._hover:
            self._hover = w
            self.update()

    # -- painting ---------------------------------------------------------
    def paintEvent(self, event):
        p = QPainter(self)
        o = self.offset()
        p.drawPixmap(-o.x(), -o.y(), self._pix)
        p.fillRect(self.rect(), DIM)
        lit, label = None, ""
        if self._dragging():
            lit = self.region()
            label = f"{lit.width()} × {lit.height()}"
        elif self._hover is not None:
            lit = self.window_rect(self._hover)
            label = self._hover.title
        if lit is not None and not lit.isEmpty():
            target = self.to_local(lit)
            p.drawPixmap(target, self._pix, QRectF(lit))
            p.setPen(QPen(FRAME, 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(target.adjusted(1, 1, -1, -1))
            self._draw_label(p, target, label)
        self._draw_hint(p)

    def hint(self) -> str:
        return HINT_WINDOWS if IS_WINDOWS else HINT_OTHER

    def _draw_hint(self, p: QPainter) -> None:
        """The one line of help at the top centre, in the label's box."""
        font = p.font()
        font.setPixelSize(13)
        p.setFont(font)
        fm = QFontMetrics(font)
        text = self.hint()
        w, h = fm.horizontalAdvance(text) + 20, fm.height() + 10
        box = QRectF((self.width() - w) / 2, 12, w, h)
        p.fillRect(box, QColor(20, 20, 20, 225))
        p.setPen(QColor("#FFFFFF"))
        p.drawText(box, Qt.AlignCenter, text)

    def _draw_label(self, p: QPainter, target: QRectF, text: str) -> None:
        font = p.font()
        font.setPixelSize(13)
        p.setFont(font)
        fm = QFontMetrics(font)
        text = fm.elidedText(text, Qt.ElideRight, 480)
        w, h = fm.horizontalAdvance(text) + 14, fm.height() + 6
        y = target.top() - h - 3
        if y < 0:
            y = target.top() + 3
        x = max(0.0, min(target.left(), self.width() - w))
        box = QRectF(x, y, w, h)
        p.fillRect(box, QColor(20, 20, 20, 225))
        p.setPen(QColor("#FFFFFF"))
        p.drawText(box, Qt.AlignCenter, text)

    # -- input ------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.picked.emit(None)
        elif event.button() == Qt.LeftButton:
            self._press = self._cur = event.position()
            self.update()

    def mouseMoveEvent(self, event):
        if self._press is not None:
            self._cur = event.position()
            self.update()
        else:
            self._set_hover(event.position())

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self._press is None:
            return
        self._cur = event.position()
        if self._dragging():
            rect, title = self.region(), None
        else:
            w = self._window_at(self._cur)
            rect = self.window_rect(w) if w is not None else self.grab.image.rect()
            title = w.title if w is not None else None
        self._press = self._cur = None
        if rect.isEmpty():
            self.update()
            return
        self.picked.emit(CaptureResult(self.grab.image.copy(rect), title))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.picked.emit(None)
        else:
            super().keyPressEvent(event)


BAR_STYLE = """
            QWidget#captureBar { background: transparent; border: 0; }
            QWidget#captureBar QPushButton, QWidget#captureBar QLabel {
                color: white; font-size: 14px; font-family: sans-serif;
                background: transparent;
                border: 0; padding: 8px; min-width: 0; }
            QWidget#captureBar QPushButton:checked,
            QWidget#captureBar QPushButton:hover { background: #505050;
                                                   border-radius: 12px; }
            QWidget#captureBar QPushButton#captureMode:checked { border: 1px solid #00c8ff; }
            QWidget#captureBar QPushButton#shoot { background: #00c8ff;
                color: black; border: 0;
                border-radius: 12px; font-weight: bold; }
            QWidget#captureBar QPushButton:disabled { color: #999999; }
        """


class CaptureBar(QWidget):
    """One real child-widget bar, moved to the screen holding the pointer."""

    def __init__(self, session, overlay):
        super().__init__(overlay)
        self.session = session
        self.setObjectName("captureBar")
        self.setAttribute(Qt.WA_NoSystemBackground)
        self._glow_factor = 1.0
        self._pulse = None
        # ASSUMES: Qt's animation framework is available. Set GLOW_PULSE_MS
        # to 0 to use a full-strength, static glow without an animation.
        if GLOW_PULSE_MS > 0:
            self._pulse = QVariantAnimation(self)
            self._pulse.setDuration(2 * GLOW_PULSE_MS)
            self._pulse.setStartValue(0.35)
            self._pulse.setKeyValueAt(1 / 3, 1.0)
            self._pulse.setKeyValueAt(2 / 3, 0.35)
            self._pulse.setEndValue(1.0)
            self._pulse.valueChanged.connect(self._set_glow_factor)
        # Explicitly override the app's theme, including its primary buttons.
        self.setStyleSheet(BAR_STYLE)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10 + GLOW_MARGIN, 6 + GLOW_MARGIN,
                                  10 + GLOW_MARGIN, 6 + GLOW_MARGIN)
        layout.setSpacing(2)
        self.modes = QButtonGroup(self)
        self.modes.setExclusive(session.freeze)
        self.mode_buttons = {}
        choices = [("area", "Area"), ("window", "Window")]
        if session.freeze:
            choices.append(("screen", "Whole screen"))
        for mode, label in choices:
            tip = (f"Choose {label.lower()} capture" if session.freeze else
                   "Only drag an area" if mode == "area" else "Only click a window")
            button = self._button(label, tip)
            button.setObjectName("captureMode")
            button.setCheckable(True)
            button.setChecked(session.mode == mode)
            self.modes.addButton(button)
            self.mode_buttons[mode] = button
            button.clicked.connect(lambda checked=False, m=mode: session.set_mode(m if checked else "auto"))
            layout.addWidget(button)
        self.whole_screen_button = None
        if not session.freeze:
            self.whole_screen_button = self._button("Whole screen", "Capture this whole screen")
            self.whole_screen_button.clicked.connect(session.whole_screen)
            layout.addWidget(self.whole_screen_button)
        self.timer_button = self._button("Timer", "Delay the live shot")
        menu = QMenu(self.timer_button)
        menu.setStyleSheet("QMenu { background: #141414; color: white; font-size: 13px; font-family: sans-serif; }"
                          "QMenu::item:selected { background: #505050; }")
        self.timer_actions = {}
        for seconds in (0, 3, 5, 10):
            action = menu.addAction("Off" if seconds == 0 else f"{seconds} s")
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, n=seconds: session.set_timer(n))
            self.timer_actions[seconds] = action
        self.timer_button.setMenu(menu)
        layout.addWidget(self.timer_button)
        self.freeze_button = self._button("Freeze", "Choose from a frozen picture")
        self.freeze_button.setCheckable(True)
        self.freeze_button.clicked.connect(session.set_freeze)
        layout.addWidget(self.freeze_button)
        self.capture_button = None
        if session.freeze:
            self.capture_button = self._button("Capture", "Capture now (Return)")
            self.capture_button.setObjectName("shoot")
            self.capture_button.clicked.connect(session.shoot)
            layout.addWidget(self.capture_button)
        self.same_area_button = self._button(
            "Same area", "Capture the same area as last time")
        self.same_area_button.clicked.connect(session.same_area)
        self.same_area_button.installEventFilter(self)
        layout.addWidget(self.same_area_button)
        self.cancel_button = self._button("Cancel", "Cancel capture (Esc)")
        self.cancel_button.clicked.connect(lambda: session._finish(None))
        layout.addWidget(self.cancel_button)
        self.countdown = QLabel(self)
        self.countdown.setAccessibleName("Capture countdown")
        layout.addWidget(self.countdown)
        self.sync()

    def eventFilter(self, obj, event):
        if obj is self.same_area_button:
            if event.type() == QEvent.Enter:
                self.session.preview_same_area(True)
            elif event.type() == QEvent.Leave:
                self.session.preview_same_area(False)
        return super().eventFilter(obj, event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pill = self.pill_rect()
        painter.setBrush(Qt.NoBrush)
        for outset, alpha in ((8, 30), (5, 70), (2, 120)):
            color = QColor(GLOW)
            color.setAlpha(round(alpha * self._glow_factor))
            painter.setPen(QPen(color, 3))
            painter.drawRoundedRect(pill.adjusted(-outset, -outset, outset, outset),
                                    20 + outset, 20 + outset)
        painter.setPen(QPen(GLOW, 2))
        painter.setBrush(QColor(20, 20, 20, 235))
        painter.drawRoundedRect(pill, 20, 20)

    def pill_rect(self):
        return QRectF(self.rect()).adjusted(GLOW_MARGIN, GLOW_MARGIN,
                                            -GLOW_MARGIN, -GLOW_MARGIN)

    def _set_glow_factor(self, value):
        self._glow_factor = float(value)
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self._pulse is not None:
            self._pulse.stop()
            self._set_glow_factor(0.35)
            self._pulse.start()

    def _button(self, text, tip):
        button = QPushButton(text, self)
        button.setAccessibleName(text)
        button.setToolTip(tip)
        return button

    def sync(self):
        s = self.session
        for mode, button in self.mode_buttons.items():
            button.setChecked(s.mode == mode)
            button.setEnabled(s.state == "idle" and
                              (mode != "window" or s.freeze or s.windows_available))
        for seconds, action in self.timer_actions.items():
            action.setChecked(s.timer == seconds)
        self.timer_button.setEnabled(not s.freeze and s.state == "idle")
        self.freeze_button.setChecked(s.freeze)
        self.freeze_button.setEnabled(s.state == "idle" and not s._forced_freeze)
        if self.capture_button is not None:
            self.capture_button.setEnabled(s.state == "idle" and s.selected is not None
                                           and not s.selected.area.isEmpty())
        if self.same_area_button is not None:
            self.same_area_button.setVisible(s._saved_area() is not None)
            self.same_area_button.setEnabled(s.state == "idle")
        if self.whole_screen_button is not None:
            self.whole_screen_button.setEnabled(s.state == "idle")
        self.countdown.setText(f"{s.remaining} s" if s.state == "countdown" else "")
        self.countdown.setVisible(s.state == "countdown")
        self.adjustSize()
        self.place()

    def place(self):
        overlay = self.parentWidget()
        self.move(max(0, (overlay.width() - self.width()) // 2),
                  max(0, overlay.height() - 80 - self.height() + GLOW_MARGIN))


class LiveOverlay(CaptureOverlay):
    """Transparent mouse surface; inherited mapping is also used for the shot."""

    def __init__(self, screen, session, mons):
        QWidget.__init__(self, None, Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.session = session
        geo, dpr = screen.geometry(), screen.devicePixelRatio()
        # No screenshot or screen-sized allocation at live start.
        phys = mons.get(screen.name(), QRect(geo.topLeft(), _scaled_rect(geo, dpr).size()))
        self.grab = ScreenGrab(screen, QImage(), geo, dpr, phys)
        self.windows = []
        self.exclude = set()
        self._pix = QPixmap()
        self._press = self._cur = self._hover = None
        self._left_pressed = False
        self.area = QRectF()
        self.title = None
        self.preview = QRectF()
        self._press_window = None
        self._was_drag = False
        self.setGeometry(geo)

    def supports_translucency(self) -> bool:
        # ASSUMES: the platform gives us a translucent top-level window.
        # When it does not supply an alpha surface, start frozen instead.
        handle = self.windowHandle()
        return bool(self.testAttribute(Qt.WA_TranslucentBackground) and handle
                    and handle.format().alphaBufferSize() > 0)

    def pixel_rect(self) -> QRect:
        if not self.grab.image.isNull():
            return self.grab.image.rect()
        return QRect(QPoint(), _scaled_rect(self.grab.geometry, self.grab.dpr).size())

    def area_pixels(self) -> QRect:
        if self.area.isEmpty():
            return QRect()
        a = self.to_device(self.area.topLeft())
        b = self.to_device(self.area.bottomRight())
        return QRect(a.x(), a.y(), b.x() - a.x(), b.y() - a.y()).intersected(self.pixel_rect())

    def _window_at(self, local):
        if IS_WINDOWS:
            p = self.to_physical(local)
            return win32.window_under_point(p.x(), p.y(), self.exclude, windows=self.windows)
        # CoreGraphics window bounds are global logical points, not Retina pixels.
        point = QPointF(self.geometry().topLeft()) + local
        return next((w for w in self.windows if w.rect.contains(point)), None)

    def window_rect(self, window):
        if IS_WINDOWS:
            return window.rect.translated(-self.grab.phys.topLeft()).intersected(self.pixel_rect())
        local = QRectF(window.rect).translated(-QPointF(self.geometry().topLeft()))
        a, b = self.to_device(local.topLeft()), self.to_device(local.bottomRight())
        return QRect(a.x(), a.y(), b.x() - a.x(), b.y() - a.y()).intersected(self.pixel_rect())

    def _set_hover(self, local):
        if self.session.mode in ("auto", "window") or (self.session.freeze and IS_WINDOWS
                                               and self.session.mode == "area"):
            super()._set_hover(local)

    def set_still(self, grab):
        self.grab = grab
        self._pix = QPixmap.fromImage(grab.image)
        self._pix.setDevicePixelRatio(grab.scale)
        self.update()

    def hint(self):
        if self.session.freeze:
            return super().hint()
        mode = self.session.mode
        if mode == "window":
            text = "Click a window to capture it"
        elif mode == "auto" and self.session.windows_available:
            text = "Drag for an area · click a window"
        else:
            text = "Drag to capture an area"
        return text + " · Esc to cancel"

    def resizeEvent(self, event):
        super().resizeEvent(event)
        bar = self.session.bar
        if bar is not None and bar.parentWidget() is self:
            bar.place()

    def paintEvent(self, event):
        p = QPainter(self)
        # Alpha 1, including inside the selection, is required for hit-testing.
        # Source clears the preceding frame's dim and frame without accumulating.
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), QColor(0, 0, 0, 1))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        frozen = self.session.freeze and not self._pix.isNull()
        if frozen:
            o = self.offset()
            p.drawPixmap(-o.x(), -o.y(), self._pix)
        lit = self.area_pixels()
        label = self.title or f"{lit.width()} × {lit.height()}"
        if not self.preview.isEmpty():
            a = self.to_device(self.preview.topLeft())
            b = self.to_device(self.preview.bottomRight())
            lit = QRect(a.x(), a.y(), b.x() - a.x(), b.y() - a.y()).intersected(self.pixel_rect())
            label = "Same area"
        elif (self._hover is not None and not self._dragging()
              and (self.session.mode in ("auto", "window") or (frozen and IS_WINDOWS))):
            lit, label = self.window_rect(self._hover), self._hover.title
        target = self.to_local(lit) if not lit.isEmpty() else QRectF()
        # Four strips dim only the outside; nothing darkens the live selection.
        dimmed = frozen or (self.preview.isEmpty() and not target.isEmpty())
        if target.isEmpty():
            if frozen:
                p.fillRect(self.rect(), DIM)
        else:
            for strip in (QRectF(0, 0, self.width(), target.top()),
                          QRectF(0, target.bottom(), self.width(), self.height() - target.bottom()),
                          QRectF(0, target.top(), target.left(), target.height()),
                          QRectF(target.right(), target.top(), self.width() - target.right(), target.height())):
                if dimmed:
                    p.fillRect(strip, DIM)
            p.setPen(QPen(FRAME, 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(target.adjusted(-1, -1, 1, 1))  # stroke entirely outside
            self._draw_label(p, target, label)
        self._draw_hint(p)

    def enterEvent(self, event):
        if self.session.state == "idle":
            self.session.pointer_on(self)
        super().enterEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.session._finish(None)
            return
        if event.button() != Qt.LeftButton or self.session.state != "idle":
            return
        self.session.pointer_on(self)
        self._left_pressed = True
        self._press = self._cur = event.position()
        self._was_drag = False
        self._press_window = None
        if self.session.mode in ("auto", "window"):
            self.session.refresh_windows()
            self._set_hover(event.position())
            self._press_window = self._window_at(event.position())
            if self.session.mode == "window":
                window = self._press_window
                if window is not None:
                    self.session.select(self, self.to_local(self.window_rect(window)), window.title, window=window)
                else:
                    # Keep the press so its matching release can be recognized.
                    self.area = QRectF()
                    self.title = None
                    self.session.selected = None
                    self.session._update()
        self.session._update()

    def mouseMoveEvent(self, event):
        if self.session.state != "idle":
            return
        self.session.pointer_on(self)
        if self._press is not None:
            self._cur = event.position()
            self._was_drag = self._was_drag or self._dragging()
            if self._was_drag and self.session.mode in ("auto", "area"):
                self._hover = None
                self.session.select(self, QRectF(self._press, self._cur).normalized()
                                    .intersected(self.to_local(self.pixel_rect())))
        else:
            self._set_hover(event.position())

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self.session.state != "idle":
            return
        # ASSUMES: a release follows a press on the same overlay.
        # A stray release, including one from another overlay, takes nothing.
        if not self._left_pressed:
            return
        self._left_pressed = False
        self._cur = event.position()
        dragged = self._was_drag or self._dragging()
        mode = self.session.mode
        take = False
        if mode in ("auto", "area"):
            if dragged:
                self._hover = None
                self.session.select(self, QRectF(self._press, self._cur).normalized()
                                    .intersected(self.to_local(self.pixel_rect())))
                take = True
            elif self.session.freeze:
                window = self._window_at(self._cur) if IS_WINDOWS else None
                rect = self.window_rect(window) if window else self.pixel_rect()
                self.session._screen_action = window is None
                self.session.select(self, self.to_local(rect), window.title if window else None)
                take = True
            # ASSUMES: a press and release without a drag chooses its window.
            # A drag from that same point takes the area branch above.
            elif mode == "auto" and self._press_window is not None:
                window = self._press_window
                self.session.select(self, self.to_local(self.window_rect(window)), window.title, window=window)
                take = True
        elif mode == "window":
            take = self.session.selected is self and (self.session.freeze or not dragged)
        elif self.session.freeze and mode == "screen":
            self.session.pointer_on(self)
            take = True
        self._press = self._cur = self._press_window = None
        self._was_drag = False
        if take:
            self.session.shoot()
        else:
            self.update()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.RightButton:
            self.session._finish(None)
        elif (event.button() == Qt.LeftButton and self.session.state == "idle"
              and self.session.freeze and self.session.selected is self
              and self.area.contains(event.position())):
            self.session.shoot()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.session._finish(None)
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            if self.session.freeze:
                self.session.shoot()
        else:
            QWidget.keyPressEvent(self, event)

    def closeEvent(self, event):
        if not self.session._done:
            self.session._finish(None)
        event.accept()


class _WindowPictureSignals(QObject):
    finished = Signal(object)


class _WindowPictureTask(QRunnable):
    def __init__(self, number, signals):
        super().__init__()
        self.number, self.signals = number, signals

    def run(self):
        try:
            picture = macos.window_picture(self.number)
        except Exception:
            picture = None
        self.signals.finished.emit(picture)


class CaptureSession(QObject):
    """One capture, one completion; all timers belong to this session."""

    finished = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.overlays: list[CaptureOverlay] = []
        self._done = False
        self._started = False
        self.settings = QSettings("Annotshot", "Annotshot")
        # capture/mode is deliberately ignored and left untouched.
        self.mode = "auto"
        self.windows_available = False
        self._whole_screen_pending = False
        self._screen_action = False
        try:
            timer = int(self.settings.value("capture/timer", 0))
        except (TypeError, ValueError):
            timer = 0
        self.timer = timer if timer in (0, 3, 5, 10) else 0
        self.freeze = self.settings.value("capture/freeze", False, type=bool)
        self._forced_freeze = False
        self.state = "idle"
        self.remaining = 0
        # ASSUMES: a stored area may exist. It never arms a new session.
        self.selected = None
        self.bar = None
        self._shot_started = None
        self._window_pick = None
        self._window_fallback = None
        self._window_signals = None
        self.error: str | None = None
        self._countdown = QTimer(self)
        self._countdown.setTimerType(Qt.PreciseTimer)
        self._countdown.timeout.connect(self._tick)
        self._settle = QTimer(self)
        self._settle.setTimerType(Qt.PreciseTimer)
        self._settle.setSingleShot(True)
        self._settle.timeout.connect(self._settled)

    def start(self, mode=None) -> None:
        if self._started or self._done:
            return
        self._started = True
        self.mode = mode if mode in ("area", "window") else "auto"
        if self.freeze:
            self.mode = mode if mode in ("area", "window", "screen") else "area"
        self._whole_screen_pending = mode == "screen" and not self.freeze
        if not IS_WINDOWS and not macos.IS_MAC:
            # Linux retains the frozen CaptureOverlay and never creates a bar.
            self.overlays = [CaptureOverlay(g, []) for g in grab_all_screens()]
            for ov in self.overlays:
                ov.picked.connect(self._finish)
                ov.show_on_screen()
            if not self.overlays:
                self._finish(None)
            return
        screens = QGuiApplication.screens()
        mons = _monitors()
        self.overlays = [LiveOverlay(screen, self, mons) for screen in screens]
        if not self.overlays:
            self._finish(None)
            return
        exclude = {int(o.winId()) for o in self.overlays}
        for ov in self.overlays:
            ov.exclude = exclude
        QGuiApplication.instance().installEventFilter(self)
        active = self._pointer_overlay()
        self.refresh_windows()
        self.bar = CaptureBar(self, active)
        if self.freeze:
            self._begin_settle("freezing")
        else:
            self._show_overlays(active)
            if not all(ov.supports_translucency() for ov in self.overlays):
                self._forced_freeze = True
                self.freeze = True
                if self.mode == "auto":
                    self.mode = "area"
                self.bar.hide()
                self.bar.deleteLater()
                self.bar = CaptureBar(self, active)
                self._begin_settle("freezing")
        if self.mode == "screen":
            self.pointer_on(active)
        self._update()
        if self._whole_screen_pending and self.state == "idle":
            self._whole_screen_pending = False
            self.whole_screen()

    def _pointer_overlay(self):
        # ASSUMES: the pointer is on some attached screen. A gap or an offscreen
        # pointer falls back to the primary screen, then the first screen.
        pos = QCursor.pos()
        return next((ov for ov in self.overlays if ov.grab.geometry.contains(pos)),
                    next((ov for ov in self.overlays
                          if ov.grab.screen == QGuiApplication.primaryScreen()), self.overlays[0]))

    def _show_overlays(self, active):
        for ov in self.overlays:
            ov.show_on_screen()
        active.raise_()
        active.activateWindow()
        active.setFocus()
        if self.bar:
            self.bar.place()
            self.bar.show()
            self.bar.raise_()

    def pointer_on(self, overlay):
        if self.state != "idle" or self._done:
            return
        if self.bar and self.bar.parentWidget() is not overlay:
            self.bar.setParent(overlay)
            self.bar.place()
            self.bar.show()
            self.bar.raise_()
        if self.freeze and self.mode == "screen":
            self.select(overlay, overlay.to_local(overlay.pixel_rect()))

    def clear_selection(self):
        self._window_pick = None
        self.selected = None
        for ov in self.overlays:
            ov.area = QRectF()
            ov.title = None
            ov.preview = QRectF()
            ov._press = ov._cur = None
            ov._left_pressed = False
        self._update()

    def select(self, overlay, area, title=None, window=None):
        self._window_pick = window
        for ov in self.overlays:
            if ov is not overlay:
                ov.area = QRectF()
                ov.title = None
                ov.preview = QRectF()
                ov._press = ov._cur = None
                ov._left_pressed = False
        overlay.preview = QRectF()
        overlay.area = QRectF(area)
        overlay.title = title
        self.selected = overlay if not area.isEmpty() else None
        self._update()

    def preview_same_area(self, visible):
        # ASSUMES: hovering the button is only a preview. Keys cannot take it.
        for ov in self.overlays:
            ov.preview = QRectF()
        target = self._saved_area() if visible and self.state == "idle" else None
        if target is not None:
            overlay, rect = target
            overlay.preview = rect
        self._update()

    def same_area(self):
        if self.state != "idle" or self._done:
            return
        target = self._saved_area()
        if target is not None:
            overlay, rect = target
            self.select(overlay, rect)
            self.shoot()

    def whole_screen(self):
        if self.state != "idle" or self._done or self.bar is None:
            return
        overlay = self.bar.parentWidget()
        self.clear_selection()
        self._screen_action = True
        self.select(overlay, overlay.to_local(overlay.pixel_rect()))
        self.shoot()

    def set_mode(self, mode):
        allowed = ("auto", "area", "window", "screen") if self.freeze else ("auto", "area", "window")
        if self.state != "idle" or self._done or mode not in allowed:
            return
        self.mode = mode
        self.clear_selection()
        for ov in self.overlays:
            ov._hover = None
        if mode in ("auto", "window"):
            self.refresh_windows()
            active = self._pointer_overlay()
            active._set_hover(QPointF(active.mapFromGlobal(QCursor.pos())))
        if self.freeze and mode == "screen":
            self.pointer_on(self._pointer_overlay())
        self._update()

    def set_timer(self, seconds):
        if self.state == "idle" and seconds in (0, 3, 5, 10):
            self.timer = seconds
            self.settings.setValue("capture/timer", seconds)
            self._update()

    def set_freeze(self, checked):
        if self.state != "idle" or self._done or self._forced_freeze:
            return
        self.freeze = bool(checked)
        self.settings.setValue("capture/freeze", self.freeze)
        active = self.bar.parentWidget()
        self.bar.hide()
        self.bar.deleteLater()
        self.bar = None
        if self.freeze and self.mode == "auto":
            self.mode = "area"
        elif not self.freeze and self.mode == "screen":
            self.mode = "auto"
        self.clear_selection()
        self.bar = CaptureBar(self, active)
        self.bar.show()
        if self.freeze:
            self._begin_settle("freezing")
        else:
            for ov in self.overlays:
                ov.grab.image = QImage()
                ov._pix = QPixmap()
            self._update()

    def refresh_windows(self):
        try:
            windows = win32.list_windows() if IS_WINDOWS else macos.list_windows()
        except Exception:  # enumeration must never block a capture
            windows = []
        # ASSUMES: a window list is available. Empty lists leave auto as
        # area-only capture and disable Window, while area capture still works.
        self.windows_available = bool(windows)
        for ov in self.overlays:
            ov.windows = windows
            ov._hover = None

    def _saved_area(self):
        """Validate stored screen-local points without selecting anything."""
        saved = self.settings.value("capture/last_area")
        if not isinstance(saved, dict):
            return None
        # ASSUMES: the stored screen is attached and its rectangle still fits.
        # Missing screens, nonfinite values and out-of-bounds areas hide the button.
        for ov in self.overlays:
            if ov.grab.screen.name() != saved.get("screen"):
                continue
            try:
                values = [float(saved[key]) for key in ("x", "y", "width", "height")]
                if not all(math.isfinite(value) for value in values):
                    return None
                rect = QRectF(*values)
                bounds = QRectF(QPointF(), ov.grab.geometry.size())
                if rect.isEmpty() or not bounds.contains(rect):
                    return None
                return ov, rect.translated(-QPointF(ov.offset()))
            except (KeyError, TypeError, ValueError, OverflowError):
                return None
        return None

    def _remember_area(self, overlay):
        if self.mode not in ("auto", "area") or overlay.title is not None or self._screen_action:
            return
        rect = overlay.to_local(overlay.area_pixels()).translated(QPointF(overlay.offset()))
        self.settings.setValue("capture/last_area", {
            "screen": overlay.grab.screen.name(), "x": rect.x(), "y": rect.y(),
            "width": rect.width(), "height": rect.height()})

    def shoot(self):
        if (self._done or self.state != "idle" or self.selected is None
                or self.selected.area_pixels().isEmpty()):
            return
        self._shot_started = time.perf_counter()
        if self.freeze:
            self._deliver(self.selected)
        elif self.timer:
            self.state = "countdown"
            self.remaining = self.timer
            self._countdown.start(COUNTDOWN_TICK_MS)
            self._update()
        else:
            self._begin_settle("shooting")

    def _tick(self):
        if self._done or self.state != "countdown":
            return
        self.remaining -= 1
        if self.remaining <= 0:
            self._countdown.stop()
            self._begin_settle("shooting")
        else:
            self._update()

    def _begin_settle(self, state):
        self.state = state
        self._update()
        for ov in self.overlays:
            ov.hide()
        QGuiApplication.processEvents()
        # Processing events may deliver cancellation. Never arm a stale grab.
        if not self._done:
            self._settle.start(SHOT_SETTLE_MS)

    def _settled(self):
        if self._done:
            return
        try:
            if self.state == "freezing":
                grabs = grab_all_screens()
                by_screen = {grab.screen: grab for grab in grabs}
                for ov in self.overlays:
                    if ov.grab.screen not in by_screen:
                        self._finish(None)
                        return
                    ov.set_still(by_screen[ov.grab.screen])
                if IS_WINDOWS:
                    self.refresh_windows()
                self.state = "idle"
                active = self._pointer_overlay()
                self._show_overlays(active)
                self.pointer_on(active)
                self._update()
                if self._whole_screen_pending:
                    self._whole_screen_pending = False
                    self.whole_screen()
            elif self.state == "shooting":
                overlay = self.selected
                if overlay.grab.screen not in QGuiApplication.screens():
                    self._finish(None)
                    return
                overlay.grab = _grab_screen(overlay.grab.screen,
                                            shot_started=self._shot_started)
                self._deliver(overlay)
        except Exception:  # a detached screen or failed grab cancels cleanly
            # ASSUMES: a screen grab can fail. Keep cancellation observable
            # without exposing a platform traceback or technical exception.
            self.error = "Could not read the screen."
            self._finish(None)

    def _deliver(self, overlay):
        rect = overlay.area_pixels()
        if rect.isEmpty() or overlay.grab.image.isNull():
            self._finish(None)
            return
        self._remember_area(overlay)
        fallback = CaptureResult(overlay.grab.image.copy(rect), overlay.title)
        window = self._window_pick
        if macos.IS_MAC and not self.freeze and window is not None:
            self.state = "window-picture"
            self._window_fallback = fallback
            signals = _WindowPictureSignals(QGuiApplication.instance())
            self._window_signals = signals
            signals.finished.connect(self._window_picture_done)
            signals.finished.connect(signals.deleteLater)
            QThreadPool.globalInstance().start(_WindowPictureTask(window.hwnd, signals))
        else:
            self._finish(fallback)

    def _window_picture_done(self, image):
        if self._done:
            return
        fallback = self._window_fallback
        frame = self._window_pick.rect
        # ASSUMES: the system picture matches the frame. Wrong shape uses the crop.
        if (isinstance(image, QImage) and not image.isNull() and not frame.isEmpty()
                and abs((image.width() / image.height()) /
                        (frame.width() / frame.height()) - 1) <= 0.02):
            flat = QImage(image.size(), QImage.Format_RGB32)
            flat.fill(Qt.white)
            painter = QPainter(flat)
            source = QImage(image)
            source.setDevicePixelRatio(1)
            painter.drawImage(0, 0, source)
            painter.end()
            flat.setDevicePixelRatio(flat.width() / frame.width())
            fallback = CaptureResult(flat, fallback.title)
        self._finish(fallback)

    def _update(self):
        for ov in self.overlays:
            ov.update()
        if self.bar:
            self.bar.sync()

    def eventFilter(self, obj, event):
        if not self._done:
            if event.type() == QEvent.KeyPress:
                if event.key() == Qt.Key_Escape:
                    self._finish(None)
                    return True
                if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                    if not event.isAutoRepeat() and self.freeze:
                        self.shoot()
                    return True
            if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
                if event.button() == Qt.RightButton:
                    self._finish(None)
                    return True
        return super().eventFilter(obj, event)

    def _finish(self, result):
        if self._done:
            return
        self._done = True
        self._countdown.stop()
        self._settle.stop()
        QGuiApplication.instance().removeEventFilter(self)
        for ov in self.overlays:
            ov.close()
        self.overlays = []
        self.bar = None
        self.finished.emit(result)
