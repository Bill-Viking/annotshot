"""Screen capture: grab every screen at device pixels, then show a frozen,
dimmed copy of each screen where the user drags a region or clicks a
window. Esc or a right-click cancels.

Mapping on a screen with scale s (image px per logical px, = its dpr):
overlay-local logical (x, y) -> image pixel ((x, y) + offset) * s ->
physical screen point monitor.topLeft + that pixel. The offset is where the
overlay really sits on its screen (overlay top-left - screen top-left): a
window the OS places below the menu bar still picks the right pixels.

The overlay is an ordinary top-most window the size of the screen, never
native full screen (on macOS that slides a new Space in). On macOS,
annotshot.macos lifts it above the menu bar on every Space.

On Windows a click picks the window under the mouse (annotshot.win32). On
macOS and Linux there is no window list: a drag captures a region and a
click captures the whole screen; annotshot.win32 is never imported there.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QCursor, QFontMetrics, QGuiApplication,
                           QImage, QPainter, QPen, QPixmap, QScreen)
from PySide6.QtWidgets import QWidget

IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    from . import win32
else:                                    # region capture only
    win32 = None
from . import macos

HINT_WINDOWS = "Drag to capture an area · click a window · Esc to cancel"
HINT_OTHER = "Drag to capture an area · click for the whole screen · Esc to cancel"

DIM = QColor(0, 0, 0, 102)          # 40 % dim over the frozen screen
FRAME = QColor("#E53935")
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
        """Image pixels per logical pixel (the dpr, measured)."""
        return self.image.width() / max(1, self.geometry.width())


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


def grab_all_screens() -> list[ScreenGrab]:
    mons = {}
    if IS_WINDOWS:
        try:
            mons = win32.monitors()
        except OSError:
            mons = {}
    grabs = []
    for screen in QGuiApplication.screens():
        img = screen.grabWindow(0).toImage().convertToFormat(QImage.Format_RGB32)
        img.setDevicePixelRatio(1.0)
        dpr = screen.devicePixelRatio()
        phys = (_monitor_rect(screen, img, mons) if IS_WINDOWS
                else _scaled_rect(screen.geometry(), dpr))
        grabs.append(ScreenGrab(screen, img, screen.geometry(), dpr, phys))
    return grabs


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


class CaptureSession(QObject):
    """Grabs every screen, shows one overlay per screen, and emits
    finished(CaptureResult | None) once."""

    finished = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.overlays: list[CaptureOverlay] = []
        self._done = False

    def start(self) -> None:
        grabs = grab_all_screens()
        windows = []
        if IS_WINDOWS:
            try:
                windows = win32.list_windows()
            except OSError:
                windows = []
        self.overlays = [CaptureOverlay(g, windows) for g in grabs]
        exclude = {int(o.winId()) for o in self.overlays}
        for ov in self.overlays:
            ov.exclude = exclude
            ov.picked.connect(self._finish)
            ov.show_on_screen()
        if not self.overlays:
            self._finish(None)

    def _finish(self, result) -> None:
        if self._done:
            return
        self._done = True
        for ov in self.overlays:
            ov.close()
        self.overlays = []
        self.finished.emit(result)
