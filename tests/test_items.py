"""Model-level proofs for checks 2, 3, 4 and 5 (offscreen)."""
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor

from annotshot.commands import MoveResize
from annotshot.items import (MIN_SIZE, ArrowItem, EllipseItem, HighlightItem,
                          PenItem, RectItem, TextBoxItem)
from annotshot.scene import Document

BOX_KINDS = [TextBoxItem, RectItem, EllipseItem, HighlightItem]


def add(doc, cls, geom, **props):
    item = cls()
    item.apply_props(props)
    item.set_geom(geom)
    doc.add_items([item])
    return item


def px(img, x, y) -> tuple:
    c = img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue())


def near(a, b, tol=6) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def red_xs(img, rect):
    """x of every clearly red pixel inside rect (x, y, w, h)."""
    x0, y0, w, h = rect
    return [x for y in range(y0, y0 + h) for x in range(x0, x0 + w)
            if (lambda c: c[0] > 150 and c[1] < 110 and c[2] < 110)(px(img, x, y))]


# -- check 2 ---------------------------------------------------------------
def test_text_color_and_fill_are_independent(qapp, white):
    doc = Document(white)
    t = add(doc, TextBoxItem, (40, 40, 200, 80), text="Hi")
    doc.set_props([t], {"text_color": "#FF0000", "fill_color": "#0000FF"})
    doc.set_props([t], {"text_color": "#00FF00"})
    assert t.props["fill_color"] == "#0000FF"
    assert t.props["text_color"] == "#00FF00"
    doc.set_props([t], {"fill_color": "#FFFF00"})
    assert t.props["text_color"] == "#00FF00"
    assert t.props["fill_color"] == "#FFFF00"
    d = t.to_dict()
    assert (d["text_color"], d["fill_color"]) == ("#00FF00", "#FFFF00")
    assert t.editor.defaultTextColor() == QColor("#00FF00")
    img = doc.render_image()
    assert px(img, 40 + 200 - 4, 40 + 80 - 4) == (255, 255, 0)   # padding = fill
    assert px(img, 40 + 4, 40 + 40) == (255, 255, 0)
    glyphs = [px(img, x, y) for y in range(46, 80) for x in range(46, 90)]
    assert any(near(c, (0, 255, 0), 40) for c in glyphs)          # text = green


# -- check 3 ---------------------------------------------------------------
def test_text_box_font_size_and_style(qapp, white):
    doc = Document(white)
    t = add(doc, TextBoxItem, (10, 10, 300, 44), text="Hello")
    doc.set_props([t], {"font_family": "Arial"})
    doc.set_props([t], {"bold": True})
    doc.set_props([t], {"italic": True})
    f = t.editor.font()
    assert (f.family(), f.bold(), f.italic()) == ("Arial", True, True)
    d = t.to_dict()
    assert (d["font_family"], d["bold"], d["italic"]) == ("Arial", True, True)

    def rendered_height(font_px):
        doc2 = Document(white)
        b = add(doc2, TextBoxItem, (20, 20, 220, 8), text="Ag",
                font_px=font_px, fill_color="#0000FF", border_width=0)
        img = doc2.render_image()
        rows = [y for y in range(img.height()) if px(img, 230, y) == (0, 0, 255)]
        assert b.to_dict()["font_px"] == font_px
        return len(rows)
    h24, h48 = rendered_height(24), rendered_height(48)
    assert h48 > h24 + 20, (h24, h48)


def test_text_box_alignment_moves_the_text(qapp, white):
    doc = Document(white)
    t = add(doc, TextBoxItem, (20, 20, 400, 60), text="Hi",
            text_color="#FF0000", border_width=0)
    lefts = {}
    for align in ("left", "center", "right"):
        doc.set_props([t], {"align": align})
        assert t.to_dict()["align"] == align
        block = t.editor.document().firstBlock().blockFormat()
        assert block.alignment() & {"left": Qt.AlignLeft, "center": Qt.AlignHCenter,
                                    "right": Qt.AlignRight}[align]
        lefts[align] = min(red_xs(doc.render_image(), (20, 20, 400, 60)))
    assert lefts["left"] < lefts["center"] < lefts["right"]
    assert lefts["left"] < 20 + 6 + 8


def test_text_box_border_and_opacity(qapp, white):
    doc = Document(white)
    t = add(doc, TextBoxItem, (50, 50, 200, 80), fill_color="#0000FF")
    doc.set_props([t], {"border_color": "#00FF00", "border_width": 6})
    img = doc.render_image()
    assert px(img, 52, 90) == (0, 255, 0) and px(img, 55, 90) == (0, 255, 0)
    assert px(img, 58, 90) == (0, 0, 255)
    assert t.to_dict()["border_width"] == 6
    doc.set_props([t], {"opacity": 0.5})
    assert t.to_dict()["opacity"] == 0.5 and t.opacity() == 0.5
    r, g, b = px(doc.render_image(), 150, 100)      # blue over white at 50 %
    assert abs(r - 128) <= 3 and abs(g - 128) <= 3 and b == 255


# -- check 4 ---------------------------------------------------------------
@pytest.mark.parametrize("cls", BOX_KINDS)
def test_box_items_move_and_resize(qapp, white, cls):
    doc = Document(white)
    it = add(doc, cls, (100, 100, 120, 80))
    before = {it: it.geom()}
    it.setPos(150.4, 129.6)                         # snaps to whole pixels
    assert it.geom() == (150, 130, 120, 80)
    it.setSelected(True)
    h4 = it.mapFromScene(QPointF(270, 210))         # bottom-right corner
    assert it.handle_at(h4) == 4
    assert it.handle_at(it.mapFromScene(QPointF(210, 130))) == 1
    it.drag_handle(4, QPointF(300, 260))
    assert it.geom() == (150, 130, 150, 130)
    it.drag_handle(0, QPointF(1000, 1000))          # past the opposite corner
    x, y, w, h = it.geom()
    assert (x + w, y + h) == (300, 260) and w == MIN_SIZE
    assert h == MIN_SIZE or (cls is TextBoxItem and h >= MIN_SIZE)
    assert doc.commit_geometry(before)
    doc.undo_stack.undo()
    assert it.geom() == (100, 100, 120, 80)
    doc.undo_stack.redo()
    assert it.geom() == (x, y, w, h)


def test_arrow_move_and_endpoint_handles(qapp, white):
    doc = Document(white)
    a = add(doc, ArrowItem, (10, 20, 110, 20))
    a.setPos(a.pos() + QPointF(5, 5))
    assert a.geom() == (15, 25, 115, 25)
    a.setSelected(True)
    assert len(a.handle_rects()) == 2
    assert a.handle_at(a.mapFromScene(QPointF(115, 25))) == 1
    a.drag_handle(1, QPointF(200, 100))
    assert a.geom() == (15, 25, 200, 100)
    a.drag_handle(0, QPointF(198, 98))              # too short: refused
    assert a.geom() == (15, 25, 200, 100)
    assert a.to_dict()["p1"] == [15, 25] and a.to_dict()["p2"] == [200, 100]


@pytest.mark.parametrize("cls", BOX_KINDS + [ArrowItem])
def test_duplicate_offsets_and_keeps_props(qapp, white, cls):
    doc = Document(white)
    geom = (10, 20, 110, 80) if cls is ArrowItem else (10, 20, 100, 60)
    it = add(doc, cls, geom)
    other = add(doc, RectItem, (300, 200, 50, 50))
    (clone,) = doc.duplicate([it])
    g, cg = it.geom(), clone.geom()
    shift = (12, 12, 12, 12) if cls is ArrowItem else (12, 12, 0, 0)
    assert tuple(b - a for a, b in zip(g, cg)) == shift
    assert clone.props == it.props and clone is not it
    assert clone.isSelected() and not it.isSelected()
    assert clone.zValue() > max(it.zValue(), other.zValue())
    doc.undo_stack.undo()
    assert clone.scene() is None


def test_front_and_back_reorder_z(qapp, white):
    doc = Document(white)
    a, b, c = (add(doc, RectItem, (i * 10, 0, 50, 50)) for i in range(3))
    assert [i.zValue() for i in (a, b, c)] == [1, 2, 3]
    doc.bring_to_front([a])
    assert doc.annotation_items()[-1] is a
    doc.send_to_back([c])
    assert doc.annotation_items()[0] is c
    assert doc.annotation_items() == [c, b, a]
    doc.undo_stack.undo()
    doc.undo_stack.undo()
    assert doc.annotation_items() == [a, b, c]
    doc.undo_stack.redo()
    assert doc.annotation_items()[-1] is a


# -- check 5 ---------------------------------------------------------------
def test_defaults(qapp):
    assert RectItem().props == {"stroke_color": "#E53935", "stroke_width": 3,
                                "fill_color": "#00FFFFFF", "opacity": 1.0,
                                "line_style": "solid"}
    assert EllipseItem().props == RectItem().props
    assert ArrowItem().props == {"stroke_color": "#E53935", "stroke_width": 4,
                                 "opacity": 1.0, "head": "filled",
                                 "head_size": "medium", "both_ends": False,
                                 "line_style": "solid"}
    hl = QColor(HighlightItem().props["fill_color"])
    assert (hl.red(), hl.green(), hl.blue()) == (255, 255, 0)
    assert abs(hl.alphaF() - 0.45) < 0.01
    t = TextBoxItem().props
    assert (t["text_color"], t["fill_color"], t["border_color"]) == \
        ("#000000", "#FFFFFF", "#E53935")
    assert (t["border_width"], t["font_family"], t["font_px"], t["align"],
            t["opacity"], t["padding"]) == (2, "Segoe UI", 24, "left", 1.0, 6)


def test_undo_redo_add_remove_props(qapp, white):
    doc = Document(white)
    r = add(doc, RectItem, (10, 10, 50, 50))
    e = add(doc, EllipseItem, (100, 10, 50, 50))
    assert len(doc.annotation_items()) == 2
    doc.remove_items([r])
    assert r.scene() is None
    doc.set_props([e], {"border_color": "#0000FF", "border_width": 7})
    assert e.props["stroke_color"] == "#0000FF" and e.props["stroke_width"] == 7
    stack = doc.undo_stack
    stack.undo()
    assert e.props["stroke_color"] == "#E53935" and e.props["stroke_width"] == 3
    stack.undo()
    assert r.scene() is doc
    stack.undo()
    stack.undo()
    assert doc.annotation_items() == []
    for _ in range(4):
        stack.redo()
    assert doc.annotation_items() == [e] and e.props["stroke_width"] == 7


def test_text_edit_that_only_grew_the_box_is_one_undo_step(qapp, white):
    doc = Document(white)
    t = add(doc, TextBoxItem, (40, 40, 200, 44), text="Hi")
    g0, count = t.geom(), doc.undo_stack.count()
    t.start_edit()
    t.end_edit()
    assert doc.undo_stack.count() == count        # nothing changed: no step
    t.start_edit()
    cursor = t.editor.textCursor()                # at the end of "Hi"
    extra = "\nline two\nline three"
    cursor.insertText(extra)
    assert t.geom()[3] > g0[3]                    # autofit grew the box
    for _ in extra:
        cursor.deletePreviousChar()
    assert t.editor.toPlainText() == "Hi" and t.geom()[3] > g0[3]
    t.end_edit()
    assert doc.undo_stack.count() == count + 1
    assert isinstance(doc.undo_stack.command(count), MoveResize)
    assert t.props["text"] == "Hi"
    doc.undo_stack.undo()
    assert t.geom() == g0                         # Ctrl+Z restores the height


def test_slider_changes_merge_into_one_step(qapp, white):
    doc = Document(white)
    h = add(doc, HighlightItem, (10, 10, 50, 20))
    count = doc.undo_stack.count()
    for v in (0.9, 0.7, 0.4):
        doc.set_props([h], {"opacity": v}, "Opacity", merge_key=("opacity", 1))
    assert doc.undo_stack.count() == count + 1 and h.opacity() == 0.4
    doc.undo_stack.undo()
    assert h.props["opacity"] == 1.0


def test_no_fill_and_shapes_render(qapp, white):
    doc = Document(white)
    r = add(doc, RectItem, (300, 20, 100, 60), fill_color="#FF0000")
    doc.set_props([r], {"fill_color": lambda item, key: "#00FF0000"})
    img = doc.render_image()
    assert px(img, 301, 50) == (229, 57, 53) and px(img, 350, 21) == (229, 57, 53)
    assert px(img, 350, 50) == (255, 255, 255)        # no fill
    add(doc, ArrowItem, (20, 200, 220, 200))
    img = doc.render_image()
    assert px(img, 100, 200) == (229, 57, 53)
    assert px(img, 212, 200) == (229, 57, 53)          # the head
    assert px(img, 212, 197) == (229, 57, 53)          # wider than the line
    assert px(img, 100, 210) == (255, 255, 255)


# -- the pen ---------------------------------------------------------------
PEN_POINTS = [(100, 100), (130, 140), (160, 110), (200, 180)]


def add_pen(doc, points=PEN_POINTS, **props):
    pen = PenItem()
    pen.apply_props(props)
    pen.set_points(points)
    doc.add_items([pen])
    return pen


def pts(item):
    return [(p.x(), p.y()) for p in item.scene_points()]


def flat(points):
    return [v for p in points for v in p]


def test_pen_from_points_has_a_box_and_defaults(qapp, white):
    doc = Document(white)
    pen = add_pen(doc)
    assert pts(pen) == [(float(x), float(y)) for x, y in PEN_POINTS]
    assert pen.geom() == (100, 100, 100, 80)          # the points' box
    assert pen.props == {"stroke_color": "#E53935", "stroke_width": 4,
                         "opacity": 1.0, "line_style": "solid"}
    assert pen.key_for("border_color") == "stroke_color"
    assert pen.key_for("border_width") == "stroke_width"
    assert pen.key_for("fill_color") is None and pen.LABEL == "Pen stroke"
    pen.setSelected(True)
    assert len(pen.handle_rects()) == 8
    assert pen.handle_at(pen.mapFromScene(QPointF(200, 180))) == 4


def test_pen_moves_and_resizes_by_scaling_its_points(qapp, white):
    doc = Document(white)
    pen = add_pen(doc)
    before = {pen: pen.geom()}
    pen.setPos(pen.pos() + QPointF(20.4, 9.6))        # snaps to whole pixels
    assert pts(pen) == [(x + 20.0, y + 10.0) for x, y in PEN_POINTS]
    assert doc.commit_geometry(before)
    assert doc.undo_stack.undoText() == "Move"
    doc.undo_stack.undo()
    assert pts(pen) == [(float(x), float(y)) for x, y in PEN_POINTS]

    pen.setSelected(True)
    before = {pen: pen.geom()}
    pen.drag_handle(4, QPointF(300, 260))             # bottom-right: 2x
    assert pen.geom() == (100, 100, 200, 160)
    assert pts(pen) == [(100 + (x - 100) * 2.0, 100 + (y - 100) * 2.0)
                        for x, y in PEN_POINTS]
    pen.drag_handle(0, QPointF(150, 140))             # top-left: 3/4 of that
    assert pen.geom() == (150, 140, 150, 120)
    assert flat(pts(pen)) == pytest.approx(flat(
        (150 + (x - 100) * 1.5, 140 + (y - 100) * 1.5) for x, y in PEN_POINTS))
    assert doc.commit_geometry(before)
    assert doc.undo_stack.undoText() == "Resize"
    doc.undo_stack.undo()
    assert flat(pts(pen)) == pytest.approx(flat(PEN_POINTS))
    doc.undo_stack.redo()
    assert pen.geom() == pytest.approx((150, 140, 150, 120))


def test_pen_duplicate_z_order_and_undo(qapp, white):
    doc = Document(white)
    pen = add_pen(doc, stroke_color="#0000FF", stroke_width=7)
    other = add(doc, RectItem, (300, 200, 50, 50))
    (clone,) = doc.duplicate([pen])
    assert pts(clone) == [(x + 12, y + 12) for x, y in pts(pen)]
    assert clone.props == pen.props and isinstance(clone, PenItem)
    assert clone.isSelected() and clone.zValue() > other.zValue()
    doc.undo_stack.undo()
    assert clone.scene() is None
    doc.send_to_back([other])
    doc.bring_to_front([pen])
    assert doc.annotation_items() == [other, pen]
    doc.send_to_back([pen])
    assert doc.annotation_items() == [pen, other]
    doc.undo_stack.undo()
    assert doc.annotation_items() == [other, pen]
    doc.set_props([pen], {"border_color": "#00FF00", "border_width": 3,
                          "opacity": 0.5})
    assert (pen.props["stroke_color"], pen.props["stroke_width"],
            pen.opacity()) == ("#00FF00", 3, 0.5)
    doc.undo_stack.undo()
    assert pen.props["stroke_color"] == "#0000FF" and pen.opacity() == 1.0
    doc.remove_items([pen])
    assert pen.scene() is None
    doc.undo_stack.undo()
    assert pen.scene() is doc and len(pen.points) == len(PEN_POINTS)
    doc.undo_stack.redo()
    assert pen.scene() is None


def test_pen_stroke_renders_round_and_smooth(qapp, white):
    doc = Document(white)
    add_pen(doc, [(50, 200), (150, 200), (250, 200)], stroke_color="#0000FF",
            stroke_width=10)
    img = doc.render_image()
    assert px(img, 150, 200) == (0, 0, 255)           # on the stroke
    assert px(img, 150, 203) == (0, 0, 255)           # its width
    assert px(img, 46, 200) == (0, 0, 255)            # the round cap
    assert px(img, 150, 210) == (255, 255, 255)
    assert px(img, 40, 200) == (255, 255, 255)


# -- arrows: head, head size, both ends (0.3.0 round 2) ---------------------
def test_an_arrows_head_kinds_sizes_and_both_ends(qapp, white):
    doc = Document(white)
    a = add(doc, ArrowItem, (100, 180, 500, 180), stroke_width=4)
    small = ArrowItem()
    small.apply_props({"head_size": "small", "stroke_width": 4})
    big = ArrowItem()
    big.apply_props({"head_size": "large", "stroke_width": 4})
    assert small._head_len() == 16                  # today's head
    assert a._head_len() == pytest.approx(16 * 1.6)
    assert big._head_len() == pytest.approx(16 * 2.4)
    one = ArrowItem()
    one.apply_props({"stroke_width": 1, "head_size": "small"})
    assert one._head_len() >= 8                     # a 1 px arrow keeps a head
    img = doc.render_image()
    assert px(img, 495, 180)[0] > 150               # filled head at p2
    assert px(img, 103, 180)[0] > 150               # the line reaches p1
    assert px(img, 100 + 5, 180 + 10) == (255, 255, 255)
    doc.set_props([a], {"both_ends": True})
    img = doc.render_image()
    assert near(px(img, 118, 186), (229, 57, 53), 60)   # a head at p1 too
    assert a.boundingRect().contains(a.p1 - QPointF(4, 12))
    assert a.body_shape().contains(QPointF(18, 6))
    doc.set_props([a], {"head": "open"})
    img = doc.render_image()
    # open: the head's two strokes, not a filled triangle
    assert px(img, 480, 186) == (255, 255, 255)     # hollow inside
    assert px(img, 480, 190)[0] > 150 and px(img, 498, 180)[0] > 150
    doc.set_props([a], {"head": "none"})
    assert a._heads()[2] == []
    img = doc.render_image()
    assert px(img, 499, 180)[0] > 150 and px(img, 490, 186) == (255, 255, 255)


def test_an_arrows_head_is_undone_and_saved(qapp, white, tmp_path):
    doc = Document(white)
    a = add(doc, ArrowItem, (10, 10, 200, 10))
    doc.set_props([a], {"head": "open", "head_size": "large",
                        "both_ends": True})
    path = tmp_path / "a.annotshot"
    doc.save(path)
    back = Document.load(path).annotation_items()[0]
    assert (back.props["head"], back.props["head_size"],
            back.props["both_ends"]) == ("open", "large", True)
    doc.undo_stack.undo()
    assert (a.props["head"], a.props["head_size"], a.props["both_ends"]) == \
        ("filled", "medium", False)


def test_an_old_arrow_without_the_keys_loads_with_the_defaults(qapp):
    old = {"type": "arrow", "z": 1, "p1": [0, 0], "p2": [50, 0],
           "stroke_color": "#E53935", "stroke_width": 4, "opacity": 1.0}
    a = ArrowItem.from_dict(old)
    assert (a.props["head"], a.props["head_size"], a.props["both_ends"]) == \
        ("filled", "medium", False)
    bad = dict(old, head="spiky", head_size=7)     # a hand-edited file
    a = ArrowItem.from_dict(bad)
    assert (a.props["head"], a.props["head_size"]) == ("filled", "medium")


def test_the_strip_shows_the_head_controls_only_for_an_arrow(qapp, white):
    from annotshot.app import make_app
    from annotshot.mainwindow import MainWindow
    make_app()
    w = MainWindow()
    doc = Document(white)
    w._bind(doc)
    a = add(doc, ArrowItem, (10, 10, 200, 10))
    r = add(doc, RectItem, (20, 40, 50, 50))
    controls = w._key_widgets["head"]   # the divider, the two groups, the box
    doc.select_only([r])
    assert all(c.isHidden() for c in controls)
    doc.select_only([a])
    assert not any(c.isHidden() for c in controls)
    assert w.cb_head.currentData() == "filled"
    assert w.cb_head_size.currentData() == "medium"
    w.cb_head.setCurrentIndex(w.cb_head.findData("open"))
    w.cb_head_size.setCurrentIndex(w.cb_head_size.findData("large"))
    w.ch_both.setChecked(True)
    assert (a.props["head"], a.props["head_size"], a.props["both_ends"]) == \
        ("open", "large", True)
    w.undo()
    assert a.props["both_ends"] is False and a.props["head_size"] == "large"
    assert not w.ch_both.isChecked()
    doc.clearSelection()
    assert all(c.isHidden() for c in controls)
    w.deleteLater()


# -- line style on every stroked shape ---------------------------------------
def runs(values) -> int:
    """How many separate stretches of True a row of booleans has."""
    return sum(1 for i, v in enumerate(values) if v and (i == 0 or not values[i - 1]))


@pytest.mark.parametrize("width", [1, 3, 8])
def test_dashed_and_dotted_borders_have_gaps(qapp, white, width):
    doc = Document(white)
    r = add(doc, RectItem, (40, 40, 400, 200), stroke_width=width,
            stroke_color="#FF0000")
    y = 40 + max(1, width) // 2            # the middle of the top edge
    img = doc.render_image()
    solid = [px(img, x, y)[1] < 150 for x in range(80, 380)]
    assert runs(solid) == 1
    doc.set_props([r], {"line_style": "dashed"})
    img = doc.render_image()
    dashed = [px(img, x, y)[1] < 150 for x in range(80, 380)]
    doc.set_props([r], {"line_style": "dotted"})
    img = doc.render_image()
    dotted = [px(img, x, y)[1] < 150 for x in range(80, 380)]
    assert runs(dashed) >= 300 // (max(4 * width, 6) + max(2.5 * width, 4)) - 1
    assert runs(dotted) > runs(dashed) >= 4
    assert not all(dotted) and any(dotted)


def test_line_style_on_arrows_ellipses_and_pen_strokes(qapp, white, tmp_path):
    doc = Document(white)
    a = add(doc, ArrowItem, (40, 300, 600, 300), stroke_width=3)
    e = add(doc, EllipseItem, (40, 40, 200, 100))
    p = PenItem()
    p.set_points([(300, 60), (400, 60), (500, 60)])
    doc.add_items([p])
    t = add(doc, TextBoxItem, (300, 150, 100, 40))
    h = add(doc, HighlightItem, (300, 220, 100, 20))
    assert t.key_for("line_style") is None and h.key_for("line_style") is None
    doc.set_props([a, e, p, t, h], {"line_style": "dotted"})
    assert all(i.props["line_style"] == "dotted" for i in (a, e, p))
    img = doc.render_image()
    line = [px(img, x, 300)[1] < 150 for x in range(60, 500)]
    assert runs(line) >= 20
    stroke = [px(img, x, 60)[1] < 150 for x in range(310, 490)]
    assert runs(stroke) >= 10
    path = tmp_path / "s.annotshot"
    doc.save(path)
    back = {i.KIND: i for i in Document.load(path).annotation_items()}
    assert back["arrow"].props["line_style"] == "dotted"
    assert back["pen"].props["line_style"] == "dotted"
    doc.undo_stack.undo()
    assert all(i.props["line_style"] == "solid" for i in (a, e, p))
    old = {"type": "rect", "rect": [0, 0, 10, 10], "stroke_color": "#E53935"}
    assert RectItem.from_dict(old).props["line_style"] == "solid"
