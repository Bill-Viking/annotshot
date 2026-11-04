"""The editor's tools and their drag-to-create geometry."""
from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QPointF, QRectF

from .items import (MIN_SIZE, ArrowItem, BaseItem, EllipseItem,
                    HighlightItem, PenItem, RectItem, TextBoxItem)

MIN_DRAG = 4                 # view px a press must travel to count as a drag
TEXT_CLICK_SIZE = (300, 44)  # a text box made by a plain click


class Tool(Enum):
    SELECT = "Select"
    TEXT = "Text"
    RECT = "Rect"
    ELLIPSE = "Ellipse"
    ARROW = "Arrow"
    HIGHLIGHT = "Highlight"
    PEN = "Pen"
    CROP = "Crop"


ITEM_FOR_TOOL: dict[Tool, type[BaseItem]] = {
    Tool.TEXT: TextBoxItem, Tool.RECT: RectItem, Tool.ELLIPSE: EllipseItem,
    Tool.ARROW: ArrowItem, Tool.HIGHLIGHT: HighlightItem, Tool.PEN: PenItem}


def make_item(tool: Tool) -> BaseItem:
    return ITEM_FOR_TOOL[tool]()


def snap(p: QPointF) -> QPointF:
    return QPointF(round(p.x()), round(p.y()))


def drag_geom(tool: Tool, p0: QPointF, p1: QPointF, final: bool = False):
    """Geometry for a drag from p0 to p1 (scene). `final` applies the
    minimum size a created box keeps."""
    p0, p1 = snap(p0), snap(p1)
    if tool is Tool.ARROW:
        return (p0.x(), p0.y(), p1.x(), p1.y())
    r = QRectF(p0, p1).normalized()
    least = MIN_SIZE if final else 1.0
    return (r.x(), r.y(), max(r.width(), least), max(r.height(), least))


def click_geom(tool: Tool, p: QPointF):
    """Geometry for a plain click, or None when a click makes nothing."""
    if tool is Tool.TEXT:
        p = snap(p)
        return (p.x(), p.y(), *TEXT_CLICK_SIZE)
    return None
