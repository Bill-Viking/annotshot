"""EditorView: shows a Document, runs the tools (drag to create, a freehand
pen stroke, crop), turns
each select-tool drag into ONE undo step, and zooms with Ctrl+wheel.

Zoom 1.0 ("100 %") means one image pixel per physical screen pixel, so a
capture shows sharp and unscaled on a scaled display. Zoom is view-only.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QTransform
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsView

from .scene import Document
from .tools import MIN_DRAG, Tool, click_geom, drag_geom, make_item

ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.05, 16.0, 1.25


class EditorView(QGraphicsView):
    zoomChanged = Signal(float)
    toolDone = Signal()          # a create/crop tool finished: back to Select

    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setMouseTracking(True)
        self.zoom = 1.0
        self.tool = Tool.SELECT
        self._press = None           # (view pos, scene pos) of a tool drag
        self._preview = None
        self._before: dict | None = None
        self._fit_pending = True
        self.doc = doc
        self.set_document(doc)
        self.set_tool(Tool.SELECT)

    # -- document / zoom --------------------------------------------------
    def set_document(self, doc: Document) -> None:
        self._press = self._preview = self._before = None
        self.doc = doc
        self.setScene(doc)
        self._fit_pending = True
        self.set_zoom(1.0)
        if self.isVisible():
            self.zoom_to_fit_or_100()

    def _dpr(self) -> float:
        return max(1.0, self.devicePixelRatioF())

    def set_zoom(self, zoom: float) -> None:
        self.zoom = min(ZOOM_MAX, max(ZOOM_MIN, zoom))
        scale = self.zoom / self._dpr()
        self.setTransform(QTransform.fromScale(scale, scale))
        self.setRenderHint(QPainter.SmoothPixmapTransform, self.zoom < 1.0)
        self.doc.set_view_scale(scale)
        self.zoomChanged.emit(self.zoom)

    def zoom_to_fit_or_100(self) -> None:
        """100 % when the image fits, else zoom out until it does."""
        self._fit_pending = False
        size, vp = self.doc.base.size(), self.viewport().size()
        if size.isEmpty() or vp.isEmpty():
            return
        fit = min(vp.width() * self._dpr() / size.width(),
                  vp.height() * self._dpr() / size.height()) * 0.98
        self.set_zoom(min(1.0, fit))
        self.centerOn(self.doc.sceneRect().center())

    def showEvent(self, event):
        super().showEvent(event)
        if self._fit_pending:
            self.zoom_to_fit_or_100()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            steps = event.angleDelta().y() / 120.0
            if steps:
                self.set_zoom(self.zoom * ZOOM_STEP ** steps)
            event.accept()
            return
        super().wheelEvent(event)

    # -- tools ------------------------------------------------------------
    def set_tool(self, tool: Tool) -> None:
        self.doc.end_text_edit()
        self._cancel_preview()
        self.tool = tool
        select = tool is Tool.SELECT
        self.setInteractive(select)           # create tools own the mouse
        self.setDragMode(QGraphicsView.RubberBandDrag if select
                         else QGraphicsView.NoDrag)
        self.viewport().setCursor(Qt.ArrowCursor if select else Qt.CrossCursor)

    def _scene_pos(self, event) -> QPointF:
        return self.mapToScene(event.position().toPoint())

    def _cancel_preview(self) -> None:
        if self._preview is not None and self._preview.scene() is self.doc:
            self.doc.removeItem(self._preview)
        self._press = self._preview = None

    def _start_preview(self, p: QPointF) -> None:
        if self.tool is Tool.CROP:
            item = QGraphicsRectItem(QRectF(p, p))
            pen = QPen(QColor("#1E88E5"), 0, Qt.DashLine)
            item.setPen(pen)
            item.setBrush(QColor(30, 136, 229, 40))
            item.setZValue(1e9)
        else:
            item = make_item(self.tool)
            if self.tool is Tool.PEN:
                item.set_points([p])
            else:
                item.set_geom(drag_geom(self.tool, p, p))
            item.setZValue(self.doc.next_z())
        self.doc.addItem(item)
        self._preview = item

    def _update_preview(self, p0: QPointF, p1: QPointF) -> None:
        if self.tool is Tool.CROP:
            self._preview.setRect(QRectF(p0, p1).normalized())
        elif self.tool is Tool.PEN:
            self._preview.add_point(p1)
        else:
            self._preview.set_geom(drag_geom(self.tool, p0, p1))

    def _finish_tool(self, dragged: bool, p0: QPointF, p1: QPointF) -> None:
        item, tool = self._preview, self.tool
        self._press = self._preview = None
        if tool is Tool.CROP:
            self.doc.removeItem(item)
            item = None
            if dragged:
                self.doc.crop(QRectF(p0, p1).normalized())
        elif tool is Tool.PEN:
            if dragged:                       # the stroke as it was drawn
                item.add_point(p1)
                self.doc.add_items([item], f"Add {item.LABEL}")
            else:                             # under 4 px makes nothing
                self.doc.removeItem(item)
                item = None
        else:
            geom = drag_geom(tool, p0, p1, final=True) if dragged \
                else click_geom(tool, p0)
            if geom is None:
                self.doc.removeItem(item)
                item = None
            else:
                item.set_geom(geom)
                self.doc.add_items([item], f"Add {item.LABEL}")
        self.set_tool(Tool.SELECT)
        self.toolDone.emit()
        if item is not None:
            self.doc.select_only([item])
            if tool is Tool.TEXT:
                item.start_edit()

    # -- mouse ------------------------------------------------------------
    def mousePressEvent(self, event):
        if self.tool is Tool.SELECT:
            super().mousePressEvent(event)
            if event.button() == Qt.LeftButton:
                self._before = {i: i.geom() for i in self.doc.selected()}
            return
        if event.button() == Qt.LeftButton:
            p = self._scene_pos(event)
            self._press = (event.position(), p)
            self._start_preview(p)
        elif event.button() == Qt.RightButton:
            self._cancel_preview()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._press is not None and self._preview is not None:
            self._update_preview(self._press[1], self._scene_pos(event))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.tool is Tool.SELECT:
            super().mouseReleaseEvent(event)
            if self._before is not None and event.button() == Qt.LeftButton:
                self.doc.commit_geometry(self._before)
                self._before = None
            return
        if event.button() == Qt.LeftButton and self._press is not None:
            v0, p0 = self._press
            dragged = (event.position() - v0).manhattanLength() >= MIN_DRAG
            self._finish_tool(dragged, p0, self._scene_pos(event))
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if self.tool is Tool.SELECT:
            super().mouseDoubleClickEvent(event)
        else:
            event.accept()
