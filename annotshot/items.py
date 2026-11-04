"""Annotation items: a shared base (selection frame, resize handles, to/from
dict, clone) and the six kinds -- text box, rectangle, ellipse, arrow,
highlight and pen stroke.

Geometry convention: one scene unit is one pixel of the captured image. A
box item's scene top-left is its pos() and its local rect is always
(0, 0, w, h); geom() returns (x, y, w, h) in scene units. An arrow's geom()
is (x1, y1, x2, y2), its two endpoints in scene units. A pen stroke's geom()
is its points' bounding box (x, y, w, h); its points are kept local to pos().
"""
from __future__ import annotations

import math

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QPainter, QPainterPath,
                           QPainterPathStroker, QPen, QPolygonF,
                           QTextBlockFormat, QTextCursor, QTextOption)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsTextItem

SELECT_COLOR = QColor("#1E88E5")
MIN_SIZE = 8.0            # smallest box a handle drag can make (scene px)
DUPLICATE_OFFSET = 12.0
HANDLE_VIEW_PX = 8.0      # handle size on screen, in logical view pixels
HIGHLIGHT_ALPHA = 0x73    # a highlight's fixed fill alpha (~0.45)

# Handle order: 0 top-left, 1 top, 2 top-right, 3 right, 4 bottom-right,
# 5 bottom, 6 bottom-left, 7 left.
HANDLE_CURSORS = [Qt.SizeFDiagCursor, Qt.SizeVerCursor, Qt.SizeBDiagCursor,
                  Qt.SizeHorCursor, Qt.SizeFDiagCursor, Qt.SizeVerCursor,
                  Qt.SizeBDiagCursor, Qt.SizeHorCursor]
ALIGNMENTS = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter,
              "right": Qt.AlignRight}


def color_hex(value) -> str:
    """Normalise a color to '#RRGGBB' (opaque) or '#AARRGGBB'."""
    c = QColor(value)
    if not c.isValid():
        raise ValueError(f"not a color: {value!r}")
    fmt = QColor.HexRgb if c.alpha() == 255 else QColor.HexArgb
    return c.name(fmt).upper()


def without_alpha(value) -> str:
    """The same color with alpha 0 -- 'no fill' / 'no border'."""
    c = QColor(value)
    c.setAlpha(0)
    return color_hex(c)


def _num(v: float):
    """Integral floats as ints so project.json stays tidy."""
    v = float(v)
    return int(v) if v.is_integer() else round(v, 3)


def handle_points(r: QRectF) -> list[QPointF]:
    l, t, rt, b = r.left(), r.top(), r.right(), r.bottom()
    cx, cy = r.center().x(), r.center().y()
    return [QPointF(l, t), QPointF(cx, t), QPointF(rt, t), QPointF(rt, cy),
            QPointF(rt, b), QPointF(cx, b), QPointF(l, b), QPointF(l, cy)]


def resized_rect(r: QRectF, handle: int, p: QPointF,
                 min_size: float = MIN_SIZE) -> QRectF:
    """The rect after dragging `handle` to scene point `p`. The opposite
    edges stay put; the result never gets smaller than min_size."""
    l, t, rt, b = r.left(), r.top(), r.right(), r.bottom()
    x, y = round(p.x()), round(p.y())
    if handle in (0, 6, 7):
        l = min(x, rt - min_size)
    if handle in (2, 3, 4):
        rt = max(x, l + min_size)
    if handle in (0, 1, 2):
        t = min(y, b - min_size)
    if handle in (4, 5, 6):
        b = max(y, t + min_size)
    return QRectF(l, t, rt - l, b - t)


def _pen(color: QColor, width: float) -> QPen:
    pen = QPen(color, width)
    pen.setJoinStyle(Qt.MiterJoin)
    return pen


class BaseItem(QGraphicsItem):
    """Shared behaviour for every annotation item."""

    KIND = ""
    LABEL = ""
    DEFAULTS: dict = {}
    COLOR_KEYS: tuple = ()
    ALIASES: dict = {}        # control key -> this kind's prop key
    SHOW_FRAME = True

    def __init__(self):
        super().__init__()
        self.rect = QRectF(0, 0, 100, 60)
        self.props = dict(self.DEFAULTS)
        self._handle: int | None = None
        self.setFlags(QGraphicsItem.ItemIsMovable
                      | QGraphicsItem.ItemIsSelectable
                      | QGraphicsItem.ItemIsFocusable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)

    # -- properties -------------------------------------------------------
    def key_for(self, control_key: str) -> str | None:
        """This item's prop key for a properties-bar key, or None."""
        key = self.ALIASES.get(control_key, control_key)
        return key if key in self.DEFAULTS else None

    def normalize(self, key: str, value):
        if key in self.COLOR_KEYS:
            return color_hex(value)
        default = self.DEFAULTS[key]
        if key == "align":
            return value if value in ALIGNMENTS else "left"
        if isinstance(default, bool):
            return bool(value)
        if isinstance(default, int):
            return int(round(float(value)))
        if isinstance(default, float):
            return min(1.0, max(0.0, float(value))) if key == "opacity" \
                else float(value)
        return str(value)

    def apply_props(self, props: dict) -> None:
        for key, value in props.items():
            if key in self.DEFAULTS:
                try:
                    self.props[key] = self.normalize(key, value)
                except (ValueError, TypeError):
                    # One malformed value (an older or hand-edited file) falls
                    # back to that key's default; the item is kept.
                    self.props[key] = self.DEFAULTS[key]
        self._props_changed()

    def _props_changed(self) -> None:
        self.prepareGeometryChange()
        self.setOpacity(float(self.props.get("opacity", 1.0)))
        self.update()

    # -- geometry ---------------------------------------------------------
    def geom(self) -> tuple:
        p = self.pos()
        return (p.x() + self.rect.x(), p.y() + self.rect.y(),
                self.rect.width(), self.rect.height())

    def set_geom(self, g) -> None:
        x, y, w, h = (float(v) for v in g)
        self.prepareGeometryChange()
        self.setPos(x, y)
        self.rect = QRectF(0, 0, max(1.0, w), max(1.0, h))
        self._geometry_changed()
        self.update()

    def _geometry_changed(self) -> None:
        pass

    def scene_rect(self) -> QRectF:
        x, y, w, h = self.geom()
        return QRectF(x, y, w, h)

    def refresh_geometry(self) -> None:
        """Called when the view zoom changes the handle size."""
        self.prepareGeometryChange()
        self.update()

    def itemChange(self, change, value):
        # Snap positions to whole image pixels so edges stay crisp.
        if change == QGraphicsItem.ItemPositionChange:
            return QPointF(round(value.x()), round(value.y()))
        return super().itemChange(change, value)

    # -- dict / clone -----------------------------------------------------
    def geom_dict(self) -> dict:
        return {"rect": [_num(v) for v in self.geom()]}

    def to_dict(self) -> dict:
        d = {"type": self.KIND, "z": _num(self.zValue())}
        d.update(self.geom_dict())
        d.update(self.props)
        return d

    def geom_from_dict(self, d: dict) -> tuple:
        return tuple(d["rect"])

    @classmethod
    def from_dict(cls, d: dict) -> "BaseItem":
        item = cls()
        item.apply_props({k: d[k] for k in cls.DEFAULTS if k in d})
        item.set_geom(item.geom_from_dict(d))
        item.setZValue(float(d.get("z", 0)))
        return item

    def clone(self) -> "BaseItem":
        return type(self).from_dict(self.to_dict())

    # -- handles ----------------------------------------------------------
    def _rendering(self) -> bool:
        sc = self.scene()
        return bool(sc is not None and getattr(sc, "rendering", False))

    def _handle_size(self) -> float:
        sc = self.scene()
        return float(getattr(sc, "handle_size", HANDLE_VIEW_PX)) if sc \
            else HANDLE_VIEW_PX

    def handle_points(self) -> list[QPointF]:
        return handle_points(self.rect)

    def handle_rects(self) -> list[QRectF]:
        s = self._handle_size()
        return [QRectF(p.x() - s / 2, p.y() - s / 2, s, s)
                for p in self.handle_points()]

    def handle_at(self, local: QPointF) -> int | None:
        if not self.isSelected():
            return None
        for i, r in enumerate(self.handle_rects()):
            if r.adjusted(-1, -1, 1, 1).contains(local):
                return i
        return None

    def handle_cursor(self, handle: int):
        return HANDLE_CURSORS[handle]

    def drag_handle(self, handle: int, scene_pos: QPointF) -> None:
        """Resize by dragging `handle` to `scene_pos` (min MIN_SIZE)."""
        self.set_geom(resized_rect(self.scene_rect(), handle, scene_pos)
                      .getRect())

    def _stroke_margin(self) -> float:
        return 0.0

    def boundingRect(self) -> QRectF:
        m = self._handle_size() + self._stroke_margin() + 2
        return self.rect.adjusted(-m, -m, m, m)

    def body_shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(self.rect)
        return path

    def shape(self) -> QPainterPath:
        path = self.body_shape()
        if self.isSelected():
            for r in self.handle_rects():
                path.addRect(r)
        return path

    def paint_selection(self, p: QPainter) -> None:
        if not self.isSelected() or self._rendering():
            return
        p.save()
        p.setOpacity(1.0)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.setBrush(Qt.NoBrush)
        if self.SHOW_FRAME:
            p.setPen(QPen(SELECT_COLOR, 0, Qt.DashLine))
            p.drawRect(self.rect)
        p.setPen(QPen(SELECT_COLOR, 0))
        p.setBrush(QColor("#FFFFFF"))
        for r in self.handle_rects():
            p.drawRect(r)
        p.restore()

    # -- mouse ------------------------------------------------------------
    def hoverMoveEvent(self, event):
        h = self.handle_at(event.pos())
        self.setCursor(self.handle_cursor(h) if h is not None
                       else Qt.SizeAllCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            h = self.handle_at(event.pos())
            if h is not None:
                self._handle = h
                event.accept()
                return
        self._handle = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._handle is not None:
            self.drag_handle(self._handle, event.scenePos())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._handle is not None:
            self._handle = None
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _TextEditor(QGraphicsTextItem):
    """The child that holds a text box's QTextDocument and edits it."""

    def __init__(self, box: "TextBoxItem"):
        super().__init__(box)
        self.box = box
        self.document().setDocumentMargin(0)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        # A color dialog or a window switch is not the end of an edit.
        if event.reason() not in (Qt.ActiveWindowFocusReason,
                                  Qt.PopupFocusReason):
            self.box.end_edit()


class TextBoxItem(BaseItem):
    """A PowerPoint-style text box: its own text color, fill and border."""

    KIND = "text"
    LABEL = "Text"
    DEFAULTS = {
        "text": "", "text_color": "#000000", "fill_color": "#FFFFFF",
        "border_color": "#E53935", "border_width": 2,
        "font_family": "Segoe UI", "font_px": 24, "bold": False,
        "italic": False, "align": "left", "opacity": 1.0, "padding": 6,
    }
    COLOR_KEYS = ("text_color", "fill_color", "border_color")

    def __init__(self):
        super().__init__()
        self._editing = False
        self._edit_geom: tuple | None = None
        self.rect = QRectF(0, 0, 300, 44)
        self.editor = _TextEditor(self)
        self.editor.document().contentsChanged.connect(self._autofit)
        self._props_changed()

    @property
    def is_editing(self) -> bool:
        return self._editing

    def _props_changed(self) -> None:
        super()._props_changed()
        p, ed = self.props, self.editor
        font = QFont(p["font_family"])
        font.setPixelSize(max(1, int(p["font_px"])))
        font.setBold(p["bold"])
        font.setItalic(p["italic"])
        ed.setFont(font)
        ed.setDefaultTextColor(QColor(p["text_color"]))
        if not self._editing and ed.toPlainText() != p["text"]:
            ed.setPlainText(p["text"])
        self._apply_alignment()
        self._layout_editor()

    def _apply_alignment(self) -> None:
        align = ALIGNMENTS.get(self.props["align"], Qt.AlignLeft)
        doc = self.editor.document()
        opt = doc.defaultTextOption()
        opt.setAlignment(align)
        opt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        doc.setDefaultTextOption(opt)
        # Every merge is a step in the text's own undo history (the one
        # Undo drives while typing), so merge only when a block differs.
        block = doc.begin()
        while block.isValid() and block.blockFormat().alignment() == align:
            block = block.next()
        if not block.isValid():
            return
        cursor = QTextCursor(doc)
        cursor.select(QTextCursor.Document)
        fmt = QTextBlockFormat()
        fmt.setAlignment(align)
        cursor.mergeBlockFormat(fmt)

    def _geometry_changed(self) -> None:
        self._layout_editor()

    def drag_handle(self, handle: int, scene_pos: QPointF) -> None:
        r = resized_rect(self.scene_rect(), handle, scene_pos)
        self.set_geom(r.getRect())
        x, y, w, h = self.geom()
        if handle in (0, 1, 2) and h > r.height():   # grew to fit: keep the bottom
            self.set_geom((x, r.bottom() - h, w, h))

    def _layout_editor(self) -> None:
        pad = self.props["padding"]
        self.editor.setPos(pad, pad)
        self.editor.setTextWidth(max(1.0, self.rect.width() - 2 * pad))
        self._autofit()

    def _autofit(self) -> None:
        """Grow (never shrink) the box so the text fits."""
        need = math.ceil(self.editor.document().size().height()
                         + 2 * self.props["padding"])
        if need > self.rect.height():
            self.prepareGeometryChange()
            self.rect.setHeight(need)
            self.update()

    def _stroke_margin(self) -> float:
        return float(self.props["border_width"])

    def paint(self, p: QPainter, option, widget=None):
        r, pr = self.rect, self.props
        fill = QColor(pr["fill_color"])
        if fill.alpha():
            p.fillRect(r, fill)
        bw, bc = float(pr["border_width"]), QColor(pr["border_color"])
        if bw > 0 and bc.alpha():
            p.setPen(_pen(bc, bw))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r.adjusted(bw / 2, bw / 2, -bw / 2, -bw / 2))
        self.paint_selection(p)

    # -- editing ----------------------------------------------------------
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_edit(event.pos())
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def start_edit(self, local_pos: QPointF | None = None) -> None:
        if self._editing:
            return
        sc = self.scene()
        if sc is not None and hasattr(sc, "end_text_edit"):
            sc.end_text_edit()
        self._editing = True
        self._edit_geom = self.geom()
        ed = self.editor
        ed.setTextInteractionFlags(Qt.TextEditorInteraction)
        ed.setAcceptedMouseButtons(Qt.AllButtons)
        # The editor child takes the hover events over the text, so the
        # I-beam is set on it (the view shows the topmost item's cursor).
        ed.setCursor(Qt.IBeamCursor)
        ed.setFocus(Qt.MouseFocusReason)
        # Undo while typing covers this edit only (character level).
        ed.document().clearUndoRedoStacks()
        cursor = ed.textCursor()
        if local_pos is not None:
            hit = ed.document().documentLayout().hitTest(
                ed.mapFromParent(local_pos), Qt.FuzzyHit)
            cursor.setPosition(max(0, hit))
        else:
            cursor.movePosition(QTextCursor.End)
        ed.setTextCursor(cursor)
        if sc is not None and hasattr(sc, "editing_item"):
            sc.editing_item = self

    def end_edit(self, push: bool = True) -> None:
        """Leave edit mode; push ONE undoable text change if it changed
        (push=False keeps the text without an undo step -- used from inside
        an undo command, where pushing would corrupt the stack)."""
        if not self._editing:
            return
        self._editing = False
        ed = self.editor
        ed.setTextInteractionFlags(Qt.NoTextInteraction)
        ed.setAcceptedMouseButtons(Qt.NoButton)
        ed.unsetCursor()
        cursor = ed.textCursor()
        cursor.clearSelection()
        ed.setTextCursor(cursor)
        if ed.hasFocus():
            ed.clearFocus()
        sc = self.scene()
        if sc is not None and getattr(sc, "editing_item", None) is self:
            sc.editing_item = None
        new = ed.toPlainText()
        if new != self.props["text"]:
            if push and sc is not None and hasattr(sc, "commit_text_edit"):
                sc.commit_text_edit(self, new, self._edit_geom)
            else:
                self.props["text"] = new
        elif (push and sc is not None and self._edit_geom is not None
              and self.geom() != self._edit_geom
              and hasattr(sc, "commit_geometry")):
            # Same text, but grow-only autofit made the box taller while
            # typing: one undo step so Ctrl+Z restores the height.
            sc.commit_geometry({self: self._edit_geom})


class _ShapeItem(BaseItem):
    DEFAULTS = {"stroke_color": "#E53935", "stroke_width": 3,
                "fill_color": "#00FFFFFF", "opacity": 1.0}
    COLOR_KEYS = ("stroke_color", "fill_color")
    ALIASES = {"border_color": "stroke_color", "border_width": "stroke_width"}

    def _stroke_margin(self) -> float:
        return float(self.props["stroke_width"])

    def _draw(self, p: QPainter, r: QRectF) -> None:
        raise NotImplementedError

    def paint(self, p: QPainter, option, widget=None):
        sw, sc = float(self.props["stroke_width"]), \
            QColor(self.props["stroke_color"])
        fill = QColor(self.props["fill_color"])
        p.setPen(_pen(sc, sw) if sw > 0 and sc.alpha() else Qt.NoPen)
        p.setBrush(fill if fill.alpha() else Qt.NoBrush)
        inset = sw / 2 if sw > 0 else 0
        self._draw(p, self.rect.adjusted(inset, inset, -inset, -inset))
        self.paint_selection(p)


class RectItem(_ShapeItem):
    KIND = "rect"
    LABEL = "Rectangle"

    def _draw(self, p, r):
        p.drawRect(r)


class EllipseItem(_ShapeItem):
    KIND = "ellipse"
    LABEL = "Ellipse"

    def _draw(self, p, r):
        p.drawEllipse(r)

    def body_shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addEllipse(self.rect)
        return path


class HighlightItem(BaseItem):
    """A translucent marker band, multiplied so the text under it reads."""

    KIND = "highlight"
    LABEL = "Highlight"
    DEFAULTS = {"fill_color": "#73FFFF00", "opacity": 1.0}
    COLOR_KEYS = ("fill_color",)

    def normalize(self, key: str, value):
        """The band's alpha stays fixed: a new fill changes its hue only."""
        value = super().normalize(key, value)
        if key == "fill_color":
            c = QColor(value)
            c.setAlpha(HIGHLIGHT_ALPHA)
            value = color_hex(c)
        return value

    def paint(self, p: QPainter, option, widget=None):
        p.save()
        p.setCompositionMode(QPainter.CompositionMode_Multiply)
        p.fillRect(self.rect, QColor(self.props["fill_color"]))
        p.restore()
        self.paint_selection(p)


class ArrowItem(BaseItem):
    """A line with a filled triangular head at p2; two endpoint handles."""

    KIND = "arrow"
    LABEL = "Arrow"
    DEFAULTS = {"stroke_color": "#E53935", "stroke_width": 4, "opacity": 1.0}
    COLOR_KEYS = ("stroke_color",)
    ALIASES = {"border_color": "stroke_color", "border_width": "stroke_width"}
    SHOW_FRAME = False

    def __init__(self):
        super().__init__()
        self.p1 = QPointF(0, 0)
        self.p2 = QPointF(100, 0)

    def geom(self) -> tuple:
        a, b = self.mapToScene(self.p1), self.mapToScene(self.p2)
        return (a.x(), a.y(), b.x(), b.y())

    def set_geom(self, g) -> None:
        x1, y1, x2, y2 = (float(v) for v in g)
        self.prepareGeometryChange()
        self.setPos(x1, y1)
        self.p1 = QPointF(0, 0)
        self.p2 = QPointF(x2 - x1, y2 - y1)
        self.update()

    def scene_rect(self) -> QRectF:
        x1, y1, x2, y2 = self.geom()
        return QRectF(QPointF(x1, y1), QPointF(x2, y2)).normalized()

    def geom_dict(self) -> dict:
        x1, y1, x2, y2 = self.geom()
        return {"p1": [_num(x1), _num(y1)], "p2": [_num(x2), _num(y2)]}

    def geom_from_dict(self, d: dict) -> tuple:
        return (*d["p1"], *d["p2"])

    def handle_points(self) -> list[QPointF]:
        return [QPointF(self.p1), QPointF(self.p2)]

    def handle_cursor(self, handle: int):
        return Qt.CrossCursor

    def drag_handle(self, handle: int, scene_pos: QPointF) -> None:
        x1, y1, x2, y2 = self.geom()
        x, y = round(scene_pos.x()), round(scene_pos.y())
        g = (x, y, x2, y2) if handle == 0 else (x1, y1, x, y)
        if math.hypot(g[2] - g[0], g[3] - g[1]) >= MIN_SIZE:
            self.set_geom(g)

    def _head_len(self) -> float:
        return 4.0 * float(self.props["stroke_width"])

    def _stroke_margin(self) -> float:
        return self._head_len()

    def boundingRect(self) -> QRectF:
        m = self._handle_size() + self._stroke_margin() + 2
        return QRectF(self.p1, self.p2).normalized().adjusted(-m, -m, m, m)

    def _head(self) -> tuple[QPointF, QPolygonF]:
        """The line's end (base of the head) and the head triangle."""
        line = QLineF(self.p1, self.p2)
        length = line.length()
        if length < 1e-6:
            return QPointF(self.p2), QPolygonF()
        head = min(self._head_len(), length)
        ux, uy = line.dx() / length, line.dy() / length
        base = QPointF(self.p2.x() - ux * head, self.p2.y() - uy * head)
        px, py = -uy * head / 2, ux * head / 2
        tri = QPolygonF([QPointF(self.p2), QPointF(base.x() + px, base.y() + py),
                         QPointF(base.x() - px, base.y() - py)])
        return base, tri

    def body_shape(self) -> QPainterPath:
        path = QPainterPath(self.p1)
        path.lineTo(self.p2)
        stroker = QPainterPathStroker()
        stroker.setWidth(max(10.0, float(self.props["stroke_width"]) + 6))
        out = stroker.createStroke(path)
        out.addPolygon(self._head()[1])
        return out

    def paint(self, p: QPainter, option, widget=None):
        color = QColor(self.props["stroke_color"])
        width = float(self.props["stroke_width"])
        base, tri = self._head()
        if width > 0:
            pen = QPen(color, width)
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)
            p.drawLine(QLineF(self.p1, base))
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawPolygon(tri)
        self.paint_selection(p)


class PenItem(BaseItem):
    """A freehand stroke. Its points are kept local to pos() (the bounding
    box's top-left, snapped to a whole pixel); `rect` is their bounding box,
    so the frame, the 8 handles and geom() -> (x, y, w, h) work as for a
    rect. Resizing scales the points inside the box; moving moves them."""

    KIND = "pen"
    LABEL = "Pen stroke"
    DEFAULTS = {"stroke_color": "#E53935", "stroke_width": 4, "opacity": 1.0}
    COLOR_KEYS = ("stroke_color",)
    ALIASES = {"border_color": "stroke_color", "border_width": "stroke_width"}

    def __init__(self):
        super().__init__()
        self.points: list[QPointF] = []
        self.rect = QRectF()

    # -- points -----------------------------------------------------------
    def scene_points(self) -> list[QPointF]:
        o = self.pos()
        return [QPointF(o.x() + p.x(), o.y() + p.y()) for p in self.points]

    def set_points(self, pts) -> None:
        """Replace the stroke with `pts` (scene px: QPointF or [x, y])."""
        pts = [QPointF(p) if isinstance(p, QPointF)
               else QPointF(float(p[0]), float(p[1])) for p in pts]
        self.prepareGeometryChange()
        if not pts:
            self.points, self.rect = [], QRectF()
            self.update()
            return
        self.setPos(min(p.x() for p in pts), min(p.y() for p in pts))
        o = self.pos()                     # snapped to a whole pixel
        self.points = [QPointF(p.x() - o.x(), p.y() - o.y()) for p in pts]
        self._fit_rect()
        self.update()

    def add_point(self, p: QPointF) -> None:
        """Extend the stroke being drawn (points closer than 1 px are
        dropped)."""
        pts = self.scene_points()
        if pts and QLineF(pts[-1], p).length() < 1.0:
            return
        self.set_points(pts + [QPointF(p)])

    def _fit_rect(self) -> None:
        xs = [p.x() for p in self.points]
        ys = [p.y() for p in self.points]
        self.rect = QRectF(min(xs), min(ys), max(xs) - min(xs),
                           max(ys) - min(ys))

    # -- geometry ---------------------------------------------------------
    def set_geom(self, g) -> None:
        """Map the stroke onto the box (x, y, w, h): a move when the size is
        the same, a scale inside the box when it differs. An axis with no
        extent (a straight stroke) only moves along it."""
        if not self.points:
            return
        x, y, w, h = (float(v) for v in g)
        sx, sy, sw, sh = self.geom()
        fx = w / sw if sw > 1e-9 else 0.0
        fy = h / sh if sh > 1e-9 else 0.0
        self.set_points([QPointF(x + (p.x() - sx) * fx, y + (p.y() - sy) * fy)
                         for p in self.scene_points()])

    def geom_dict(self) -> dict:
        return {"points": [[_num(p.x()), _num(p.y())]
                           for p in self.scene_points()]}

    @classmethod
    def from_dict(cls, d: dict) -> "PenItem":
        item = cls()
        item.apply_props({k: d[k] for k in cls.DEFAULTS if k in d})
        pts = d["points"]
        if not isinstance(pts, list) or not pts:
            raise ValueError("a pen stroke needs points")
        item.set_points(pts)
        item.setZValue(float(d.get("z", 0)))
        return item

    # -- painting ---------------------------------------------------------
    def path(self) -> QPainterPath:
        """A smooth path through the points: quadratic segments from
        midpoint to midpoint, each bent at a recorded point."""
        pts = self.points
        path = QPainterPath()
        if not pts:
            return path
        path.moveTo(pts[0])
        if len(pts) == 1:
            path.lineTo(pts[0])
            return path
        for a, b in zip(pts[1:-1], pts[2:]):
            path.quadTo(a, QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2))
        path.lineTo(pts[-1])
        return path

    def _stroke_margin(self) -> float:
        return float(self.props["stroke_width"]) / 2 + 1

    def body_shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(max(10.0, float(self.props["stroke_width"]) + 6))
        stroker.setCapStyle(Qt.RoundCap)
        stroker.setJoinStyle(Qt.RoundJoin)
        out = stroker.createStroke(self.path())
        if self.isSelected():               # a selected stroke drags by its box
            out.addRect(self.rect)
        return out

    def paint(self, p: QPainter, option, widget=None):
        color = QColor(self.props["stroke_color"])
        width = float(self.props["stroke_width"])
        if width > 0 and color.alpha() and self.points:
            pen = QPen(color, width)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(self.path())
        self.paint_selection(p)


ITEM_TYPES: dict[str, type[BaseItem]] = {
    cls.KIND: cls for cls in (TextBoxItem, RectItem, EllipseItem,
                              ArrowItem, HighlightItem, PenItem)}


def item_from_dict(d: dict) -> BaseItem:
    """Rebuild an item; raises KeyError for an unknown type."""
    return ITEM_TYPES[d["type"]].from_dict(d)
