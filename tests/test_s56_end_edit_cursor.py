"""Qt cursor-reset regression; all pointer/window activity is offscreen."""
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PySide6.QtGui import QCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QGraphicsView, QWidget

from annotshot.items import CalloutItem, TextBoxItem
from annotshot.scene import Document
from annotshot.tools import Tool
from annotshot.view import EditorView


@pytest.fixture
def editor_view(qapp, white):
    assert qapp.platformName() == "offscreen"
    sink = QWidget()
    sink.setGeometry(20, 20, 640, 480)
    sink.show()
    QTest.mouseMove(sink, sink.rect().center())
    sink.hide()
    sink.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    view = EditorView(Document(white))
    view.resize(640, 480)
    view.move(20, 20)
    view.show()
    view.set_zoom(view.devicePixelRatioF())
    yield view
    view.doc.end_text_edit()
    view.hide()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def text_item(view, cls):
    item = cls()
    item.set_geom((100, 80, 300, 100))
    item.apply_props({"text": "Cursor reset"})
    view.doc.add_items([item])
    return item


def resting_pointer(view, item):
    """Put the text under the pointer left by the fixture's deleted window."""
    point = view.mapToScene(view.viewport().mapFromGlobal(QCursor.pos()))
    item.setPos(point - QPointF(26, 21))
    view.setAttribute(Qt.WA_UnderMouse, True)
    view.viewport().setAttribute(Qt.WA_UnderMouse, True)
    assert view.underMouse()
    assert view.itemAt(view.viewport().mapFromGlobal(QCursor.pos())) is item.editor


@pytest.mark.parametrize("cls", [TextBoxItem, CalloutItem], ids=["text", "callout"])
def test_end_edit_with_resting_pointer(editor_view, monkeypatch, cls):
    view = editor_view
    item = text_item(view, cls)
    delivered = []
    original = EditorView.mouseMoveEvent

    def moved(self, event):
        delivered.append(event)
        return original(self, event)

    monkeypatch.setattr(EditorView, "mouseMoveEvent", moved)
    resting_pointer(view, item)
    assert delivered == []
    item.start_edit()
    assert item.is_editing and view.doc.editing_item is item
    item.end_edit()
    assert not item.is_editing
    assert view.doc.editing_item is None
    assert item.editor.textInteractionFlags() == Qt.NoTextInteraction


@pytest.mark.parametrize("cls", [TextBoxItem, CalloutItem], ids=["text", "callout"])
def test_seen_pointer_loses_ibeam_immediately(editor_view, qapp, cls):
    view = editor_view
    item = text_item(view, cls)
    qapp.processEvents()
    point = view.mapFromScene(item.editor.mapToScene(QPointF(20, 15)))
    QTest.mouseMove(view.viewport(), point)
    normal_cursor = view.viewport().cursor().shape()
    assert normal_cursor != Qt.IBeamCursor
    item.start_edit()
    assert view.viewport().cursor().shape() == Qt.IBeamCursor
    item.end_edit()
    # No event processing or further move: the reset must be synchronous.
    assert view.viewport().cursor().shape() == normal_cursor


@pytest.mark.parametrize("tool", [Tool.SELECT, Tool.ARROW])
def test_priming_has_no_side_effects_and_runs_once(qapp, white, monkeypatch, tool):
    assert qapp.platformName() == "offscreen"
    doc = Document(white)
    item = TextBoxItem()
    item.set_geom((100, 80, 300, 100))
    doc.add_items([item])
    doc.select_only([item])
    hover = []
    item.setAcceptHoverEvents(True)
    for name in ("hoverEnterEvent", "hoverMoveEvent", "hoverLeaveEvent"):
        monkeypatch.setattr(item, name, lambda event, name=name: hover.append(name))
    primed = []
    tool_moves = []
    base_move = QGraphicsView.mouseMoveEvent

    def state(view):
        return (doc.to_dict(), doc.selected(), doc.focusItem(), doc.mouseGrabberItem(),
                item.isUnderMouse(), list(hover), view.underMouse(),
                view.viewport().underMouse(), view.tool, view._press, view._preview,
                view._handle_drag, view._before, doc.undo_stack.count(),
                doc.undo_stack.index(), view.horizontalScrollBar().value(),
                view.verticalScrollBar().value(), view.viewport().cursor().shape(),
                view.viewport().testAttribute(Qt.WA_SetCursor))

    def base_probe(view, event):
        assert event.type() == QEvent.MouseMove
        assert event.position() == QPointF(-10000, -10000)
        assert event.button() == event.buttons() == Qt.NoButton
        assert event.modifiers() == Qt.NoModifier
        before = state(view)
        base_move(view, event)
        assert state(view) == before
        primed.append(True)

    class ProbeView(EditorView):
        def setScene(self, scene):
            super().setScene(scene)
            # Exercise non-default state before the FIRST priming call.
            self.tool = tool
            self.setSceneRect(0, 0, 4000, 3000)
            self.horizontalScrollBar().setValue(37)
            self.verticalScrollBar().setValue(53)
            self.viewport().setCursor(Qt.PointingHandCursor)

        def mouseMoveEvent(self, event):
            tool_moves.append(True)
            super().mouseMoveEvent(event)

    monkeypatch.setattr(QGraphicsView, "mouseMoveEvent", base_probe)
    view = ProbeView(doc)
    try:
        assert primed == [True] and tool_moves == [] and hover == []
        # Rebinding either the same scene or a replacement never primes again.
        view.set_document(doc)
        view.set_document(Document(white))
        assert primed == [True] and tool_moves == [] and hover == []
    finally:
        view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
