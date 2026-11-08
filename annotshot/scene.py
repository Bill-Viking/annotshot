"""The Annotshot document: a QGraphicsScene holding the captured image (painted
as the background) and the annotation items, with undoable operations,
PNG rendering and the .annotshot project file (a zip of project.json +
base.png).
"""
from __future__ import annotations

import json
import os
import warnings
import zipfile
from pathlib import Path

from PySide6.QtCore import (QBuffer, QIODevice, QPointF, QRect, QRectF, Qt,
                            Signal)
from PySide6.QtGui import QColor, QImage, QPainter, QUndoStack
from PySide6.QtWidgets import QGraphicsScene

from .commands import (AddItems, ChangeProps, Crop, MoveResize, RemoveItems,
                       ZOrder)
from . import theme
from .items import DUPLICATE_OFFSET, HANDLE_VIEW_PX, BaseItem, item_from_dict

FORMAT = "annotshot"
LEGACY_FORMATS = ("snagup",)       # files saved before the rename (same zip)
FORMAT_VERSION = 1
CANVAS_COLOR = QColor("#E9EDF2")    # Light's quiet grey around the picture
# (the surround follows the theme: theme.color("canvas"))


def blank_image(w: int = 1280, h: int = 720) -> QImage:
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor("#FFFFFF"))
    return img


def _is_move(item, a: tuple, b: tuple) -> bool:
    """True when geometry b is geometry a translated (no resize)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    moved = item.geom_moved(a, dx, dy)
    return len(moved) == len(b) and all(abs(m - v) < 1e-9
                                        for m, v in zip(moved, b))


def write_project(path, meta_json: str, base: QImage) -> None:
    """Write an editable file: project.json + base.png in a zip, through a
    temporary file replaced at once, so a file is never half-written. Safe
    on a worker thread (no scene object is touched)."""
    path = str(path)
    tmp = path + ".tmp"
    try:
        with zipfile.ZipFile(tmp, "w") as z:
            z.writestr("project.json", meta_json,
                       compress_type=zipfile.ZIP_DEFLATED)
            z.writestr("base.png", png_bytes(base))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def png_bytes(img: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


class UndoStack(QUndoStack):
    """A QUndoStack that also remembers the step last exported (Copy image
    or Save… as a picture): the picture is out, so that state counts as saved
    too."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.exported_index: int | None = None

    def mark_exported(self) -> None:
        self.exported_index = self.index()

    def needs_save(self) -> bool:
        """True when replacing or closing the document should ask: the
        current step is neither the saved one nor the exported one."""
        return not (self.isClean() or self.index() == self.exported_index)

    def push(self, cmd) -> None:
        before = self.index()
        if self.exported_index is not None and before < self.exported_index:
            self.exported_index = None      # the exported steps get discarded
        super().push(cmd)
        if self.index() == before and before == self.exported_index:
            self.exported_index = None      # merged into the exported step


class Document(QGraphicsScene):
    """The scene IS the model: 1 scene unit = 1 pixel of `base`."""

    # The text box now being edited, or None when the edit ends.
    editingChanged = Signal(object)

    def __init__(self, base: QImage | None = None, parent=None):
        super().__init__(parent)
        self.undo_stack = UndoStack(self)
        self.rendering = False
        self.handle_size = HANDLE_VIEW_PX
        self._editing_item = None
        self.path: str | None = None
        # The autosave's bookkeeping: every change to the stack (a push, an
        # undo, a redo, a merge) counts one; `written` is the count the
        # last write carried (-1 after a failed one).
        self.changes = 0
        self.written = 0
        self.base = QImage()
        # The start-up blank (no capture, no file): the view shows a hint
        # instead of a white page. Any capture or open makes a new Document
        # from a real picture; the first edit clears it.
        self.is_placeholder = base is None or base.isNull()
        self.set_base(blank_image() if self.is_placeholder else base)
        self.undo_stack.indexChanged.connect(self._edited)

    def _edited(self, *_) -> None:
        self.changes += 1
        if self.is_placeholder:
            self.is_placeholder = False
            self.update()

    # -- base image -------------------------------------------------------
    def set_base(self, img: QImage) -> None:
        img = img.convertToFormat(QImage.Format_RGB32)
        img.setDevicePixelRatio(1.0)
        self.base = img
        self.setSceneRect(QRectF(img.rect()))
        self.update()

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, theme.color("canvas"))   # the chrome, not the picture
        if self.rendering or not self.is_placeholder:  # the export: white
            painter.drawImage(QPointF(0, 0), self.base)

    # -- item queries -----------------------------------------------------
    def annotation_items(self) -> list[BaseItem]:
        """Every annotation item, bottom to top."""
        return sorted((i for i in self.items() if isinstance(i, BaseItem)),
                      key=lambda i: i.zValue())

    def selected(self) -> list[BaseItem]:
        return sorted((i for i in self.selectedItems()
                       if isinstance(i, BaseItem)), key=lambda i: i.zValue())

    def next_z(self) -> float:
        items = self.annotation_items()
        return items[-1].zValue() + 1 if items else 1.0

    def select_only(self, items) -> None:
        self.clearSelection()
        for item in items:
            item.setSelected(True)

    # -- text editing -----------------------------------------------------
    @property
    def editing_item(self):
        return self._editing_item

    @editing_item.setter
    def editing_item(self, item) -> None:
        if item is not self._editing_item:
            self._editing_item = item
            self.editingChanged.emit(item)

    def is_editing(self) -> bool:
        return self.editing_item is not None

    def end_text_edit(self, push: bool = True) -> None:
        if self.editing_item is not None:
            self.editing_item.end_edit(push)

    def commit_text_edit(self, item, text: str, geom_before) -> None:
        self.undo_stack.push(ChangeProps(
            [(item, {"text": text})], "Edit text",
            geom_before={item: geom_before} if geom_before else None))

    def set_view_scale(self, scale: float) -> None:
        """Keep handles ~8 screen pixels at any zoom."""
        self.handle_size = HANDLE_VIEW_PX / max(scale, 1e-6)
        for item in self.annotation_items():
            item.refresh_geometry()

    # -- undoable operations ----------------------------------------------
    def add_items(self, items, text: str = "Add") -> None:
        items = list(items)
        z = self.next_z()
        for item in items:
            if item.scene() is not self:
                item.setZValue(z)
                z += 1
        self.undo_stack.push(AddItems(self, items, text))

    def remove_items(self, items) -> None:
        items = list(items)
        if items:
            self.undo_stack.push(RemoveItems(self, items, "Delete"))

    def duplicate(self, items) -> list[BaseItem]:
        self.end_text_edit()
        clones = []
        for item in sorted(items, key=lambda i: i.zValue()):
            clone = item.clone()
            clone.moveBy(DUPLICATE_OFFSET, DUPLICATE_OFFSET)
            clones.append(clone)
        if clones:
            self.add_items(clones, "Duplicate")
            self.select_only(clones)
        return clones

    def bring_to_front(self, items) -> None:
        items = sorted(items, key=lambda i: i.zValue())
        if items:
            top = self.next_z()
            self.undo_stack.push(ZOrder(
                {item: top + n for n, item in enumerate(items)},
                "Bring to front"))

    def send_to_back(self, items) -> None:
        items = sorted(items, key=lambda i: i.zValue())
        if items:
            all_items = self.annotation_items()
            start = all_items[0].zValue() - len(items)
            self.undo_stack.push(ZOrder(
                {item: start + n for n, item in enumerate(items)},
                "Send to back"))

    def set_props(self, items, props: dict, text: str = "Change",
                  merge_key=None) -> bool:
        """Apply properties-bar values to every item that has the key.
        A value may be a callable(item, key) -> value. True if pushed."""
        changes = []
        for item in items:
            new = {}
            for control_key, value in props.items():
                key = item.key_for(control_key)
                if key is None:
                    continue
                v = value(item, key) if callable(value) else value
                v = item.normalize(key, v)
                if item.props[key] != v:
                    new[key] = v
            if new:
                changes.append((item, new))
        if not changes:
            return False
        self.undo_stack.push(ChangeProps(changes, text, merge_key))
        return True

    def commit_geometry(self, before: dict) -> bool:
        """Push ONE MoveResize for whatever a drag changed."""
        changed = {item: g for item, g in before.items()
                   if item.scene() is self and item.geom() != g}
        if not changed:
            return False
        after = {item: item.geom() for item in changed}
        moved = all(_is_move(item, g, after[item])
                    for item, g in changed.items())
        self.undo_stack.push(MoveResize(changed, after,
                                        "Move" if moved else "Resize"))
        return True

    def crop(self, rect) -> bool:
        r = QRectF(rect).toAlignedRect() if not isinstance(rect, QRect) \
            else QRect(rect)
        r = r.intersected(self.base.rect())
        if r.width() < 1 or r.height() < 1 or r == self.base.rect():
            return False
        self.undo_stack.push(Crop(self, r))
        return True

    # -- export -----------------------------------------------------------
    def render_image(self) -> QImage:
        """The flattened picture at the base size (no frames, no handles)."""
        self.end_text_edit()
        img = QImage(self.base.size(), QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        self.rendering = True
        try:
            p = QPainter(img)
            p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
            self.render(p, QRectF(img.rect()), self.sceneRect())
            p.end()
        finally:
            self.rendering = False
        return img

    # -- project file -----------------------------------------------------
    def to_dict(self) -> dict:
        return {"format": FORMAT, "version": FORMAT_VERSION,
                "size": [self.base.width(), self.base.height()],
                "items": [i.to_dict() for i in self.annotation_items()]}

    def snapshot(self) -> tuple[str, QImage]:
        """What a write needs, taken on the UI thread: the project text and
        the base (a shared copy; Qt copies it only if it changes)."""
        return json.dumps(self.to_dict(), indent=1), QImage(self.base)

    def needs_write(self) -> bool:
        """True when a change has not been carried by a write yet."""
        return self.changes != self.written

    def write(self, path) -> None:
        """Write the editable file at `path`; the document keeps its own
        path (a copy, as Save… makes one)."""
        self.end_text_edit()
        write_project(path, *self.snapshot())

    def save(self, path) -> None:
        self.write(path)
        self.path = str(path)
        self.written = self.changes
        self.undo_stack.setClean()

    @classmethod
    def load(cls, path) -> "Document":
        with zipfile.ZipFile(str(path)) as z:
            meta = json.loads(z.read("project.json").decode("utf-8"))
            data = z.read("base.png")
        if not isinstance(meta, dict) or meta.get("format") not in (FORMAT, *LEGACY_FORMATS):
            raise ValueError(f"{Path(path).name} is not an Annotshot project")
        if int(meta.get("version", 1)) > FORMAT_VERSION:
            warnings.warn(f"{Path(path).name} was saved by a newer Annotshot "
                          f"(version {meta.get('version')}); some parts may "
                          "be missing")
        img = QImage.fromData(data, "PNG")
        if img.isNull():
            raise ValueError(f"{Path(path).name}: the image is unreadable")
        items = meta.get("items", [])
        if not isinstance(items, list):
            raise ValueError(f"{Path(path).name}: \"items\" is not a list")
        doc = cls(img)
        for d in items:
            try:
                item = item_from_dict(d)
            except (KeyError, TypeError, ValueError) as e:
                kind = d.get("type") if isinstance(d, dict) else d
                warnings.warn(f"skipping item {kind!r}: {e!r}")
                continue
            doc.addItem(item)
        doc.path = str(path)
        return doc
