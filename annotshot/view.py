"""EditorView: shows a Document, runs the tools (drag to create, a freehand
pen stroke, crop), turns
each select-tool drag into ONE undo step, zooms with Ctrl+wheel, and shows
the right-click menu (its actions come from the window, through
`menu_actions`, so the view never imports the window).

Zoom 1.0 ("100 %") means one image pixel per physical screen pixel, so a
capture shows sharp and unscaled on a scaled display. Zoom is view-only.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QPainter,
                           QPainterPath, QPen, QTransform)
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsView, QMenu

from . import theme
from .items import BaseItem, ITEM_TYPES
from .scene import CANVAS_COLOR, Document
from .tools import (ITEM_FOR_TOOL, MIN_DRAG, TYPING_TOOLS, Tool, click_geom, drag_geom,
                    make_item)

ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.05, 16.0, 1.25
EMPTY_HINT = ("No picture yet",
              "Click Capture to take a screenshot, or Open… a saved file")
HINT_INK = QColor("#7D8994")         # Light's; the theme's "hint" token
# Beyond the picture (after a crop) shapes are kept and still editable, but
# drawn faded: the canvas surround laid over them at about 65 %, so they show
# at about 35 %. The saved picture never has them (it is the picture rect).
FADE_ALPHA = 166
FADE = QColor(CANVAS_COLOR)
FADE.setAlpha(FADE_ALPHA)


def fade_color() -> QColor:
    """The fade in the current theme: its canvas colour at FADE_ALPHA."""
    c = theme.color("canvas")
    c.setAlpha(FADE_ALPHA)
    return c


class EditorView(QGraphicsView):
    zoomChanged = Signal(float)
    toolDone = Signal()          # only Crop returns to Select
    toolChanged = Signal()

    def __init__(self, doc: Document, parent=None, settings=None):
        super().__init__(parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setMouseTracking(True)
        self.zoom = 1.0
        self.tool = Tool.SELECT
        self.empty_hint = EMPTY_HINT
        self._press = None           # (view pos, scene pos) of a tool drag
        self._preview = None
        self._handle_drag = None
        self._before: dict | None = None
        self._fit_pending = True
        self.settings = settings
        self.remember_props = self._remember_enabled()
        self.tool_defaults: dict[str, dict] = {}
        self.load_tool_defaults()
        # callable(on_item: bool) -> the menu's QActions, None = separator
        self.menu_actions = None
        self._menu_blocked = False       # a right-click that cancelled a drag
        self.set_document(doc)
        self.set_tool(Tool.SELECT)

    # -- starting styles --------------------------------------------------
    @staticmethod
    def factory_style(kind: str) -> dict:
        """Only style: never the previous object's text or geometry."""
        return {k: v for k, v in ITEM_TYPES[kind]().props.items()
                if k not in ("text", "padding")}

    def _remember_enabled(self) -> bool:
        value = self.settings.value("props/remember", True) \
            if self.settings is not None else True
        return str(value).lower() not in ("false", "0")

    @staticmethod
    def _style_value(item, key, value):
        """ASSUMES: saved settings can be hand edited; reject bad values."""
        if key in ("font_px", "border_width", "stroke_width", "opacity"):
            number = float(value)
            lo, hi = (6, 400) if key == "font_px" else \
                (0, 1) if key == "opacity" else (0, 40)
            if not math.isfinite(number) or not lo <= number <= hi:
                raise ValueError("style value out of range")
        if key in ("bold", "italic", "both_ends"):
            if str(value).lower() not in ("true", "false", "1", "0"):
                raise ValueError("not a boolean")
            value = str(value).lower() in ("true", "1")
        if key == "align" and value not in ("left", "center", "right"):
            raise ValueError("not an alignment")
        if key == "font_family" and (not isinstance(value, str) or not value.strip()
                                     or value.strip().startswith(".")):
            raise ValueError("not a font family")
        return item.normalize(key, value)

    def load_tool_defaults(self) -> None:
        """Read only when remembering is on; loading never writes settings."""
        self.tool_defaults = {kind: self.factory_style(kind) for kind in ITEM_TYPES}
        if not self.remember_props or self.settings is None:
            return
        for kind, style in self.tool_defaults.items():
            item = ITEM_TYPES[kind]()
            for key in style:
                value = self.settings.value(f"props/{kind}/{key}", None)
                if value is not None:
                    try:
                        style[key] = self._style_value(item, key, value)
                    except (ValueError, TypeError, OverflowError):
                        pass

    def starting_style(self, kind: str) -> dict:
        return dict(self.tool_defaults[kind] if self.remember_props
                    else self.factory_style(kind))

    def defaults_item(self) -> BaseItem | None:
        """The active drawing tool's target; Select and Crop have no style."""
        cls = ITEM_FOR_TOOL.get(self.tool)
        if cls is None:
            return None
        item = cls()
        item.apply_props(self.starting_style(item.KIND))
        return item

    def remember_style(self, item: BaseItem, keys) -> None:
        if not self.remember_props:
            return
        style = self.tool_defaults[item.KIND]
        for control_key in keys:
            key = item.key_for(control_key)
            if key in style:
                try:
                    value = self._style_value(item, key, item.props[key])
                except (ValueError, TypeError, OverflowError):
                    continue
                style[key] = value
                if self.settings is not None:
                    self.settings.setValue(f"props/{item.KIND}/{key}", value)
        if self.settings is not None:
            self.settings.sync()

    def set_remember_props(self, on: bool) -> None:
        self.remember_props = bool(on)
        if self.settings is not None:
            self.settings.setValue("props/remember", bool(on))
            self.settings.sync()
        self.load_tool_defaults()

    def reset_tool_defaults(self) -> None:
        if self.settings is not None:
            for kind in ITEM_TYPES:
                self.settings.remove(f"props/{kind}")
            self.settings.sync()
        self.tool_defaults = {kind: self.factory_style(kind) for kind in ITEM_TYPES}

    # -- document / zoom --------------------------------------------------
    def set_document(self, doc: Document) -> None:
        if hasattr(self, "doc"):
            self.doc.editingChanged.disconnect(self._typing_changed)
            self.doc.end_text_edit()
        self._press = self._preview = self._before = self._handle_drag = None
        self.doc = doc
        doc.editingChanged.connect(self._typing_changed)
        self.setScene(doc)
        self._typing_changed(doc.editing_item)
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

    def fit_after_resize(self) -> None:
        """Fit (or 100 %) once the window has taken its new size."""
        self._fit_pending = True
        QTimer.singleShot(0, self._fit_if_pending)

    def _fit_if_pending(self) -> None:
        if self._fit_pending and self.isVisible():
            self.zoom_to_fit_or_100()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fit_pending and self.isVisible():
            self.zoom_to_fit_or_100()

    def showEvent(self, event):
        super().showEvent(event)
        if self._fit_pending:
            self.zoom_to_fit_or_100()

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawForeground(painter, rect)
        self._fade_beyond_picture(painter, rect)
        if self.doc.is_placeholder:
            self._draw_empty_hint(painter)

    def _fade_beyond_picture(self, painter: QPainter, rect: QRectF) -> None:
        """Lay the fade over everything outside the picture, then draw the
        selection frames and handles again above it, so a shape half out
        of the picture is faded there but its handles are not."""
        picture = self.doc.sceneRect()
        if picture.contains(rect):
            return
        outside = QPainterPath()
        outside.addRect(rect)
        inside = QPainterPath()
        inside.addRect(picture)
        painter.save()
        painter.fillPath(outside.subtracted(inside), fade_color())
        for item in self.doc.selected():
            if picture.contains(item.sceneBoundingRect()):
                continue
            painter.save()
            painter.setTransform(item.sceneTransform(), True)
            item.paint_selection(painter)
            painter.restore()
        painter.restore()

    def _draw_empty_hint(self, painter: QPainter) -> None:
        """The start-up blank: two centred lines in the viewport, at the same
        size whatever the zoom."""
        painter.save()
        painter.resetTransform()
        box = QRectF(self.viewport().rect())
        title, line = self.empty_hint
        big = QFont(self.font())
        scale = theme.ui_scale()        # Retro's pixel font needs the size
        big.setPixelSize(round(20 * scale))
        big.setBold(True)
        small = QFont(self.font())
        small.setPixelSize(round(14 * scale))
        painter.setPen(theme.color("hint"))
        mid = box.center().y()
        painter.setFont(big)
        painter.drawText(QRectF(box.left(), mid - 34, box.width(), 30),
                         Qt.AlignHCenter | Qt.AlignBottom, title)
        painter.setFont(small)
        painter.drawText(QRectF(box.left(), mid + 2, box.width(), 24),
                         Qt.AlignHCenter | Qt.AlignTop, line)
        painter.restore()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            steps = event.angleDelta().y() / 120.0
            if steps:
                self.set_zoom(self.zoom * ZOOM_STEP ** steps)
            event.accept()
            return
        super().wheelEvent(event)

    # -- tools ------------------------------------------------------------
    def event(self, event):
        # An unmodified tool letter belongs to the text editor while typing.
        # Modified editing/action shortcuts retain their existing behaviour.
        if (event.type() == QEvent.ShortcutOverride
                and hasattr(self, "doc") and self.doc.is_editing()
                and not event.modifiers() & (Qt.ControlModifier
                                             | Qt.AltModifier
                                             | Qt.MetaModifier)
                and event.text() and event.text().isprintable()):
            event.accept()
            return True
        return super().event(event)

    def set_tool(self, tool: Tool) -> None:
        self.doc.end_text_edit()
        self._cancel_preview()
        self.tool = tool
        select = tool is Tool.SELECT
        self.setInteractive(select)           # create tools own the mouse
        self.setDragMode(QGraphicsView.RubberBandDrag if select
                         else QGraphicsView.NoDrag)
        self.viewport().setCursor(Qt.ArrowCursor if select else Qt.CrossCursor)
        self.toolChanged.emit()

    def _typing_changed(self, item):
        self.setInteractive(self.tool is Tool.SELECT or item is not None)

    def selected_handle_at(self, point):
        for item in reversed(self.doc.selected()):
            handle = item.handle_at(item.mapFromScene(point))
            if handle is not None:
                return item, handle
        return None

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
            item.apply_props(self.starting_style(item.KIND))
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
        if tool is Tool.CROP:
            self.set_tool(Tool.SELECT)
            self.toolDone.emit()
        self.doc.select_only([item] if item is not None and tool is not Tool.PEN else [])
        if item is not None:
            if tool in TYPING_TOOLS:
                item.start_edit()

    def viewportEvent(self, event):
        result = super().viewportEvent(event)
        if (event.type() == QEvent.MouseMove and self.tool is not Tool.SELECT
                and not self.doc.is_editing()):
            # Qt also chooses item cursors inside viewportEvent. Apply the
            # drawing tool's cursor after that, including over an object's body.
            hit = self.selected_handle_at(self._scene_pos(event))
            self.viewport().setCursor(hit[0].handle_cursor(hit[1]) if hit else Qt.CrossCursor)
        return result

    # -- mouse ------------------------------------------------------------
    def mousePressEvent(self, event):
        if self.tool is not Tool.SELECT and self.doc.is_editing():
            editor = self.doc.editing_item.editor
            if editor.contains(editor.mapFromScene(self._scene_pos(event))):
                super().mousePressEvent(event)
            else:
                self.doc.end_text_edit()
                event.accept()       # this press only ends typing
            return
        if self.tool is Tool.SELECT:
            super().mousePressEvent(event)
            if event.button() == Qt.LeftButton:
                self._before = {i: i.geom() for i in self.doc.selected()}
            return
        if event.button() == Qt.LeftButton:
            self._menu_blocked = False
            p = self._scene_pos(event)
            handle = self.selected_handle_at(p)
            if handle is not None:
                self._handle_drag = handle
                self._before = {handle[0]: handle[0].geom()}
                event.accept()
                return
            self.doc.clearSelection()
            self._press = (event.position(), p)
            self._start_preview(p)
        elif event.button() == Qt.RightButton:
            if self._press is not None:  # cancels the drag, shows no menu
                self._menu_blocked = True
            self._cancel_preview()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._handle_drag is not None:
            item, handle = self._handle_drag
            item.drag_handle(handle, self._scene_pos(event))
            event.accept()
            return
        if self._press is not None and self._preview is not None:
            self._update_preview(self._press[1], self._scene_pos(event))
            event.accept()
            return
        if self.tool is not Tool.SELECT and not self.doc.is_editing():
            hit = self.selected_handle_at(self._scene_pos(event))
            self.viewport().setCursor(hit[0].handle_cursor(hit[1]) if hit else Qt.CrossCursor)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._handle_drag is not None and event.button() == Qt.LeftButton:
            item, handle = self._handle_drag
            item.drag_handle(handle, self._scene_pos(event))
            self._handle_drag = None
            self.doc.commit_geometry(self._before)
            self._before = None
            event.accept()
            return
        if self.tool is not Tool.SELECT and self.doc.is_editing():
            super().mouseReleaseEvent(event)
            return
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

    # -- right-click menu ---------------------------------------------------
    def item_at(self, pos: QPoint):
        """The annotation item under the viewport point, or None."""
        for it in self.items(pos):
            while it is not None and not isinstance(it, BaseItem):
                it = it.parentItem()
            if it is not None:
                return it
        return None

    def context_menu_at(self, pos: QPoint) -> QMenu | None:
        """The menu for a right-click at the viewport point; None while a
        drag is under way (a right-click then only cancels it). An item
        under the point is selected first and adds the item actions."""
        if self._menu_blocked:
            self._menu_blocked = False
            return None
        if (self._press is not None or self.menu_actions is None
                or QGuiApplication.mouseButtons() & Qt.LeftButton):
            return None
        item = self.item_at(pos)
        if item is not None and not item.isSelected():
            self.doc.select_only([item])
        menu = QMenu(self)
        for action in self.menu_actions(item is not None):
            if action is None:
                menu.addSeparator()
            else:
                menu.addAction(action)
        return menu

    def contextMenuEvent(self, event):
        item = self.item_at(event.pos())
        if item is not None and item is self.doc.editing_item:
            super().contextMenuEvent(event)   # the text box's own menu
            return
        menu = self.context_menu_at(event.pos())
        if menu is not None:
            menu.exec(event.globalPos())
            menu.deleteLater()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if self.tool is Tool.SELECT:
            super().mouseDoubleClickEvent(event)
        else:
            event.accept()
