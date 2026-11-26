"""Candidate A geometry, production pixels and the unchanged strip budget.

Qt is offscreen via conftest. No browser or native window proof lives here.
"""
import math

import pytest
from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (QColor, QFont, QImage, QPainter, QPainterPath,
                           QPalette)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QComboBox, QStyle, QStyleOptionViewItem)

from annotshot import theme, typefaces
from annotshot.items import (HEAD_KINDS, HEAD_SIZES, LINE_STYLES, ArrowItem,
                            CalloutItem, EllipseItem, PenItem, RectItem,
                            TextBoxItem, arrow_ink,
                            fit_cycle, intervals, rhythm, styled_pen)
from annotshot.scene import Document
from annotshot.tools import Tool
from annotshot.view import EditorView


PATTERNS = ("dashed", "long_dash", "dotted", "dash_dot")


def painted(item, scale=2):
    image = QImage(1000 * scale, 300 * scale, QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(scale)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(100, 100)
    p.translate(item.pos())
    p.setOpacity(item.opacity())
    item.paint(p, None)
    p.end()
    return image


def alpha(image, x, y):
    dpr = image.devicePixelRatio()
    return image.pixelColor(round((x + 100) * dpr),
                            round((y + 100) * dpr)).alpha()


@pytest.mark.parametrize("width", (1, 2, 4, 8))
@pytest.mark.parametrize("size,factor", HEAD_SIZES.items())
@pytest.mark.parametrize("head", HEAD_KINDS)
@pytest.mark.parametrize("both", (False, True))
@pytest.mark.parametrize("end", ((400, 0), (240, 320), (-240, -320)))
def test_head_geometry_orientation_and_bounds(qapp, width, size, factor, head, both, end):
    a = ArrowItem()
    a.set_geom((0, 0, *end))
    a.apply_props(dict(stroke_width=width, head=head, head_size=size,
                       both_ends=both, line_style="dash_dot"))
    depth = 4 * width * factor * (1.5 if head == "open" else 1)
    trim = (0 if head == "none" else min(width, 400 / (2 if both else 1))
            if head == "bar" else min(depth, width / (2 * math.tan(math.pi / 8)))
            if head == "open" else depth)
    expected_depth = 0 if head == "none" else trim if head == "bar" else depth
    assert a._head_len() == pytest.approx(expected_depth)
    start, finish, heads = a._heads()
    unit = QPointF(end[0] / 400, end[1] / 400)
    assert start.x() == pytest.approx(unit.x() * (trim if both else 0))
    assert start.y() == pytest.approx(unit.y() * (trim if both else 0))
    assert finish.x() == pytest.approx(end[0] - unit.x() * trim)
    assert finish.y() == pytest.approx(end[1] - unit.y() * trim)
    assert len(heads) == (0 if head == "none" else 2 if both else 1)
    inverse, ok = a._axis().inverted()
    assert ok
    if heads:
        r = inverse.map(heads[0]).boundingRect()
        span = 4 * width * factor if head == "bar" else \
            2 * depth * math.tan(math.pi / 8)
        assert r.width() == pytest.approx(expected_depth)
        assert r.height() == pytest.approx(span)
        assert r.right() == pytest.approx(400)
    for path in heads:
        assert a.boundingRect().contains(path.boundingRect())
        # Actual solid wing/crossbar ink must also be a selectable body.
        # Boolean subtraction of coincident diagonal edges can retain a
        # zero-area contour in Qt; probe interior head ink instead.
        r = path.boundingRect()
        body = a.body_shape()
        checked = 0
        for i in range(9):
            for j in range(9):
                point = QPointF(r.left() + r.width() * (i + 0.37) / 9,
                                r.top() + r.height() * (j + 0.27) / 9)
                if path.contains(point):
                    checked += 1
                    assert body.contains(point)
        assert checked
    # A shaft gap remains a generous target in every orientation.
    mid = unit * 180
    assert a.body_shape().contains(mid)


@pytest.mark.parametrize("width", (1, 2, 4, 8))
@pytest.mark.parametrize("size", HEAD_SIZES)
@pytest.mark.parametrize("head", HEAD_KINDS)
@pytest.mark.parametrize("both", (False, True))
@pytest.mark.parametrize("span", (0, 1e-8, 1e-5, 1, 5, 9))
def test_short_heads_never_cross_handles(qapp, width, size, head, both, span):
    ink = arrow_ink(span, width, "dash_dot", head, size, both)
    if span < 1e-6:
        assert ink.isEmpty()
        return
    r = ink.boundingRect()
    assert r.left() >= -1e-9 and r.right() <= span + 1e-9
    a = ArrowItem()
    a.set_geom((0, 0, span, 0))
    a.apply_props(dict(stroke_width=width, head=head, head_size=size, both_ends=both))
    assert a._head_len() <= span / (2 if both else 1) + 1e-9


@pytest.mark.parametrize("width", (1, 2, 4, 8))
def test_nominal_rhythms_and_fitted_fixed_dots(width):
    gap = max(2, 2 * width)
    expected = {"dashed": [max(4, 4 * width), gap],
                "long_dash": [max(8, 8 * width), gap],
                "dotted": [width, gap],
                "dash_dot": [max(4, 4 * width), gap, width, gap]}
    for style, nominal in expected.items():
        assert rhythm(style, width) == nominal
        pen = styled_pen(QColor("red"), width, style)
        assert pen.capStyle() == Qt.FlatCap
        assert pen.dashPattern() == pytest.approx([v / width for v in nominal])
        assert pen.dashOffset() == 0
        assert list(intervals(sum(nominal) - 0.1, nominal, style)) == \
            [(0, sum(nominal) - 0.1)]
        span = 487
        cycle, count = fit_cycle(span, nominal, style)
        assert count == math.floor(span / sum(nominal) + 0.5)
        assert sum(cycle) * count == pytest.approx(span)
        if style in ("dotted", "dash_dot"):
            assert cycle[0 if style == "dotted" else 2] == width
        parts = list(intervals(span, nominal, style))
        assert parts[0][0] == 0 and parts[-1][1] == pytest.approx(span)
        assert parts[0][1] == pytest.approx(span - parts[-1][0])


@pytest.mark.parametrize("width", (1, 2, 4, 8))
@pytest.mark.parametrize("style", PATTERNS)
@pytest.mark.parametrize("cls", (ArrowItem, RectItem, EllipseItem, PenItem))
def test_each_pattern_has_visible_ink_and_clear_gaps(qapp, width, style, cls):
    item = cls()
    item.apply_props(dict(stroke_width=width, line_style=style))
    if cls is PenItem:
        item.set_points([(0, 0), (200, 0), (600, 0)])
    else:
        item.set_geom((0, 0, 600, 80 if cls in (RectItem, EllipseItem) else 0))
    image = painted(item)
    if cls is EllipseItem:
        path = QPainterPath()
        path.addEllipse(QRectF(width / 2, width / 2, 600 - width, 80 - width))
        values = [alpha(image, pt.x(), pt.y()) for pt in
                  (path.pointAtPercent(i / 720) for i in range(720))]
    else:
        y = width / 2 if cls is RectItem else 0
        values = [alpha(image, x, y) for x in range(30, 500)]
    assert sum(v > 80 for v in values) > 10
    assert sum(v == 0 for v in values) > 10


@pytest.mark.parametrize("width", (1, 2, 4, 8))
@pytest.mark.parametrize("style", LINE_STYLES)
def test_rectangle_corners_inked_and_stroke_inside(qapp, width, style):
    r = RectItem()
    r.set_geom((0, 0, 313, 97))
    r.apply_props(dict(stroke_width=width, line_style=style))
    image = painted(r)
    for x, y in ((0.25, 0.25), (312.5, 0.25), (0.25, 96.5), (312.5, 96.5)):
        assert alpha(image, x, y) == 255
    assert alpha(image, -0.5, 20) == alpha(image, 313.5, 20) == 0


@pytest.mark.parametrize("cls", (RectItem, EllipseItem))
@pytest.mark.parametrize("style", LINE_STYLES)
@pytest.mark.parametrize("stroke,rgba", (("#0000FF", (0, 0, 255, 255)),
                                        ("#80FF0000", (255, 0, 0, 128))))
def test_consumed_inset_fills_outer_silhouette(qapp, cls, style, stroke, rgba):
    item = cls()
    item.set_geom((0, 0, 8, 20))
    item.apply_props(dict(stroke_width=8, line_style=style,
                         stroke_color=stroke, fill_color="#0000FF"))
    image = painted(item)
    assert image.pixelColor(208, 220).getRgb() == rgba
    assert alpha(image, -1, 10) == 0


@pytest.mark.parametrize("cls", (RectItem, EllipseItem))
def test_ordinary_inset_keeps_fill_and_translucent_outline(qapp, cls):
    item = cls()
    item.set_geom((0, 0, 40, 20))
    item.apply_props(dict(stroke_width=8, stroke_color="#80FF0000",
                         fill_color="#0000FF"))
    image = painted(item)
    assert image.pixelColor(240, 220).getRgb() == (0, 0, 255, 255)
    assert image.pixelColor(202, 220).getRgb() == (255, 0, 0, 128)
    assert image.pixelColor(212, 220).getRgb() == (128, 0, 127, 255)
    assert alpha(image, -1, 10) == 0


@pytest.fixture
def select_view(qapp, white):
    assert qapp.platformName() == "offscreen"
    doc = Document(white)
    view = EditorView(doc)
    doc.setParent(view)
    view.resize(700, 420)
    view.set_zoom(view.devicePixelRatioF())   # one scene pixel per logical pixel
    view.centerOn(320, 180)
    assert view.tool is Tool.SELECT
    yield view, doc
    view.deleteLater()


def drag_selected_handle(view, doc, item, handle, drop):
    doc.add_items([item])
    doc.select_only([item])
    before, count = item.geom(), doc.undo_stack.count()
    start = item.mapToScene(item.handle_points()[handle])
    a, b = view.mapFromScene(start), view.mapFromScene(drop)
    # Exercise the scene's Select dispatch, not drag_handle directly.
    QTest.mousePress(view.viewport(), Qt.LeftButton, pos=a)
    assert doc.mouseGrabberItem() is item
    QTest.mouseMove(view.viewport(), (a + b) / 2)
    QTest.mouseMove(view.viewport(), b)
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=b)
    after = item.geom()
    assert after != before
    assert doc.undo_stack.count() == count + 1
    doc.undo_stack.undo()
    assert item.geom() == before
    doc.undo_stack.redo()
    assert item.geom() == after
    return after


@pytest.mark.parametrize("head", HEAD_KINDS)
@pytest.mark.parametrize("both", (False, True))
@pytest.mark.parametrize("handle", (1, 0), ids=("end", "start"))
def test_select_arrow_handles_drag_to_drop(select_view, head, both, handle):
    view, doc = select_view
    item = ArrowItem()
    item.set_geom((40, 90, 240, 90))
    item.apply_props(dict(head=head, both_ends=both))
    drop = QPointF(265, 110) if handle == 1 else QPointF(65, 110)
    after = drag_selected_handle(view, doc, item, handle, drop)
    expected = (40, 90, 265, 110) if handle == 1 else (65, 110, 240, 90)
    assert after == expected


@pytest.mark.parametrize("cls", (RectItem, EllipseItem, TextBoxItem, CalloutItem))
@pytest.mark.parametrize("handle", range(8))
def test_select_box_handles_still_resize(select_view, cls, handle):
    view, doc = select_view
    item = cls()
    item.set_geom((100, 80, 120, 60))
    start = item.mapToScene(item.handle_points()[handle])
    drop = start + QPointF(20, 15)
    after = drag_selected_handle(view, doc, item, handle, drop)
    left = 120 if handle in (0, 6, 7) else 100
    top = 95 if handle in (0, 1, 2) else 80
    right = 240 if handle in (2, 3, 4) else 220
    bottom = 155 if handle in (4, 5, 6) else 140
    assert after[:4] == (left, top, right - left, bottom - top)


@pytest.mark.parametrize("head", HEAD_KINDS)
@pytest.mark.parametrize("style", LINE_STYLES)
@pytest.mark.parametrize("via", ("opacity", "stroke_color"))
def test_half_alpha_has_no_darker_joint(qapp, head, style, via):
    a = ArrowItem()
    a.set_geom((0, 0, 250, 0))
    a.apply_props(dict(stroke_width=8, head=head, both_ends=True, line_style=style))
    a.apply_props({via: 0.5 if via == "opacity" else "#80E53935"})
    image = painted(a)
    # Full scan includes wing/shaft intersections and the two head bases.
    values = [image.pixelColor(x, y).alpha()
              for y in range(170, 230) for x in range(195, 710)]
    assert 126 <= max(values) <= 128
    assert sum(v >= 126 for v in values) > 20


@pytest.mark.parametrize("cls", (ArrowItem, RectItem, EllipseItem, PenItem))
@pytest.mark.parametrize("props", ({"stroke_width": 0}, {"stroke_width": -1},
                                  {"stroke_color": "#00E53935"}))
def test_invisible_stroke_has_no_ink(qapp, cls, props):
    item = cls()
    if cls is PenItem:
        item.set_points([(0, 0), (100, 30), (200, 0)])
    else:
        item.set_geom((0, 0, 200, 60))
    item.apply_props(dict(line_style="long_dash", **props))
    image = painted(item)
    assert not any(image.constBits())


def test_bar_tips_are_selectable_even_outside_shaft_hit_band(qapp):
    a = ArrowItem()
    a.set_geom((0, 0, 200, 0))
    a.apply_props(dict(head="bar", head_size="large", both_ends=True, stroke_width=8))
    for point in (QPointF(196, 23), QPointF(4, -23)):
        assert a.body_shape().contains(point)
        assert a.boundingRect().contains(point)
    assert not a.body_shape().contains(QPointF(100, 23))


@pytest.mark.parametrize("style", PATTERNS)
def test_pen_extension_keeps_earlier_dashes_and_midpoint_curve(qapp, style):
    pen = PenItem()
    pen.apply_props(dict(line_style=style, stroke_width=4))
    pen.set_points([(0, 0), (100, 0), (200, 0)])
    before = painted(pen)
    pen.add_point(QPointF(300, 0))
    after = painted(pen)
    assert [alpha(before, x, 0) for x in range(150)] == \
        [alpha(after, x, 0) for x in range(150)]
    pen.set_points([(0, 0), (100, 100), (200, 0), (300, 100)])
    expected = QPainterPath(QPointF(0, 0))
    expected.quadTo(QPointF(100, 100), QPointF(150, 50))
    expected.quadTo(QPointF(200, 0), QPointF(250, 50))
    expected.lineTo(QPointF(300, 100))
    assert pen.path() == expected


@pytest.fixture
def window(qapp):
    from annotshot.app import make_app
    from annotshot.mainwindow import MainWindow
    make_app()
    w = MainWindow()
    yield w
    w.deleteLater()


def original_width(box, entries):
    probe = QComboBox(box.parentWidget())
    probe.setFont(box.font())
    probe.setMinimumHeight(28)
    for name in entries:
        probe.addItem(name)
    probe.ensurePolished()
    width = probe.sizeHint().width()
    probe.deleteLater()
    return width


def test_closed_choices_keep_original_width_after_theme_font_and_style_changes(window, qapp):
    typefaces.load_bundled()
    for name in ("light", "dark", "retro", "light"):
        window.set_theme(name)
        qapp.processEvents()
        for box, names in ((window.cb_line, ("Solid", "Dashed", "Dotted")),
                           (window.cb_head, ("Filled", "Open", "None"))):
            baseline = original_width(box, names)
            assert box.width() == box.sizeHint().width() == baseline
            for i in range(box.count()):
                box.setCurrentIndex(i)
                assert box.width() == baseline
                assert box.currentText() in box.toolTip()
                assert box.currentText() == box.accessibleDescription()
        assert window.prop_strip.layout().count() == 2
        assert window.prop_row1.height() == window.prop_row2.height() == 36
        assert window.prop_scroll.height() == 76
    for box, names in ((window.cb_line, ("Solid", "Dashed", "Dotted")),
                       (window.cb_head, ("Filled", "Open", "None"))):
        font = QFont(box.font())
        font.setPixelSize(19)
        box.setFont(font)
        assert box.width() == original_width(box, names)
        qapp.setStyle("Fusion")
        assert box.width() == original_width(box, names)


def test_popup_samples_full_names_palette_and_stock_navigation(window, qapp, monkeypatch):
    from PySide6.QtTest import QTest
    from annotshot.tools import Tool
    text_paints = []
    draw_text = QPainter.drawText

    def witnessed_text(painter, rect, flags, text):
        before = painter.device().copy(rect)
        result = draw_text(painter, rect, flags, text)
        text_paints.append((text, painter.pen().color(), before,
                            painter.device().copy(rect)))
        return result

    monkeypatch.setattr(QPainter, 'drawText', witnessed_text)
    window.view.set_tool(Tool.ARROW)
    assert [(window.cb_line.itemData(i), window.cb_line.itemText(i))
            for i in range(window.cb_line.count())] == [
                ("solid", "Solid"), ("dashed", "Dashed"), ("long_dash", "Long dash"),
                ("dotted", "Dotted"), ("dash_dot", "Dash-dot")]
    assert [(window.cb_head.itemData(i), window.cb_head.itemText(i))
            for i in range(window.cb_head.count())] == [
                ("filled", "Filled"), ("open", "Open"), ("none", "None"), ("bar", "Bar")]
    for box in (window.cb_line, window.cb_head):
        box.setCurrentIndex(0)
        QTest.keyClick(box, Qt.Key_End)
        assert box.currentIndex() == box.count() - 1
        QTest.keyClick(box, Qt.Key_Home)
        assert box.currentIndex() == 0
        for selected in (False, True):
            for row in range(box.count()):
                option = QStyleOptionViewItem()
                option.initFrom(box)
                option.font = box.font()
                option.rect = QRect(0, 0, 220, 28)
                option.palette.setColor(QPalette.Text, QColor("#123456"))
                option.palette.setColor(QPalette.HighlightedText, QColor("#FEDCBA"))
                if selected:
                    option.state |= QStyle.State_Selected
                image = QImage(220, 28, QImage.Format_ARGB32_Premultiplied)
                image.fill(Qt.transparent)
                painter = QPainter(image)
                index = box.model().index(row, 0)
                text_paints.clear()
                box.itemDelegate().paint(painter, option, index)
                painter.end()
                ink = QColor("#FEDCBA" if selected else "#123456")
                # Sample and full-name columns both paint with the active text role.
                assert any(image.pixelColor(x, y) == ink
                           for x in range(6, 62) for y in range(6, 22))
                # Antialiased system glyphs need not contain a fully covered
                # pixel. Witness the exact pen and full name, and actual ink.
                assert len(text_paints) == 1
                text, pen, before, after = text_paints[0]
                assert text == box.itemText(row) and pen == ink
                assert before != after
                hint = box.itemDelegate().sizeHint(option, index)
                assert hint.height() >= 20
