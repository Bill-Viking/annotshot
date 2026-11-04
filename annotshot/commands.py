"""Undo commands for an Annotshot Document (pushed on its QUndoStack).

Each command keeps exactly the before/after state it needs. QUndoStack calls
redo() when a command is pushed, so redo() must also be safe as the first
apply (re-applying a state the scene already has is harmless).
"""
from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QUndoCommand


class AddItems(QUndoCommand):
    def __init__(self, doc, items, text: str = "Add"):
        super().__init__(text)
        self.doc = doc
        self.items = list(items)

    def _add(self):
        for item in self.items:
            if item.scene() is not self.doc:
                self.doc.addItem(item)

    def _remove(self):
        self.doc.end_text_edit(push=False)
        for item in self.items:
            if item.scene() is self.doc:
                self.doc.removeItem(item)

    def redo(self):
        self._add()

    def undo(self):
        self._remove()


class RemoveItems(AddItems):
    def redo(self):
        self._remove()

    def undo(self):
        self._add()


class MoveResize(QUndoCommand):
    """Geometry before/after for one drag (move or handle resize)."""

    def __init__(self, before: dict, after: dict, text: str = "Move"):
        super().__init__(text)
        self.before = dict(before)
        self.after = dict(after)

    def redo(self):
        for item, g in self.after.items():
            item.set_geom(g)

    def undo(self):
        for item, g in self.before.items():
            item.set_geom(g)


class ChangeProps(QUndoCommand):
    """Props before/after for one control change. Commands with the same
    merge_key on the same items merge (one slider drag = one undo step).
    Geometry is restored too, since a text box grows to fit its text."""

    MERGE_ID = 1

    def __init__(self, changes, text: str = "Change", merge_key=None,
                 geom_before: dict | None = None):
        super().__init__(text)
        self.changes = [(item, dict(new), {k: item.props[k] for k in new})
                        for item, new in changes]
        self.merge_key = merge_key
        geom_before = geom_before or {}
        self.geom_before = {item: geom_before.get(item) or item.geom()
                            for item, _, _ in self.changes}
        self.geom_after: dict | None = None

    def id(self) -> int:
        return self.MERGE_ID if self.merge_key is not None else -1

    def redo(self):
        for item, new, _ in self.changes:
            item.apply_props(new)
        if self.geom_after is None:
            self.geom_after = {item: item.geom() for item, _, _ in self.changes}
        else:
            for item, g in self.geom_after.items():
                item.set_geom(g)

    def undo(self):
        for item, _, old in self.changes:
            item.apply_props(old)
        for item, g in self.geom_before.items():
            item.set_geom(g)

    def mergeWith(self, other) -> bool:
        if (not isinstance(other, ChangeProps) or self.merge_key is None
                or other.merge_key != self.merge_key
                or len(other.changes) != len(self.changes)
                or any(a[0] is not b[0]
                       for a, b in zip(self.changes, other.changes))):
            return False
        self.changes = [(item, {**new, **new2}, {**old2, **old})
                        for (item, new, old), (_, new2, old2)
                        in zip(self.changes, other.changes)]
        self.geom_after = other.geom_after
        return True


class ZOrder(QUndoCommand):
    def __init__(self, new_z: dict, text: str):
        super().__init__(text)
        self.after = dict(new_z)
        self.before = {item: item.zValue() for item in new_z}

    def redo(self):
        for item, z in self.after.items():
            item.setZValue(z)

    def undo(self):
        for item, z in self.before.items():
            item.setZValue(z)


class Crop(QUndoCommand):
    """Keeps the old image; items move by -rect.topLeft and back."""

    def __init__(self, doc, rect: QRect):
        super().__init__("Crop")
        self.doc = doc
        self.rect = QRect(rect)
        self.old_base = doc.base
        self.new_base = doc.base.copy(self.rect)

    def _shift(self, base, dx: int, dy: int):
        self.doc.end_text_edit(push=False)
        self.doc.set_base(base)
        for item in self.doc.annotation_items():
            item.moveBy(dx, dy)

    def redo(self):
        self._shift(self.new_base, -self.rect.x(), -self.rect.y())

    def undo(self):
        self._shift(self.old_base, self.rect.x(), self.rect.y())
