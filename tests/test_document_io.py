"""Document proofs: save/load (check 7), PNG export with pixel probes (the
file half of check 6), crop and its undo (check 5). Offscreen."""
import json
import warnings
import zipfile

import pytest
from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage

from annotshot.items import (ArrowItem, EllipseItem, HighlightItem, PenItem,
                          RectItem, TextBoxItem)
from annotshot.scene import Document

from test_items import add, near, px


def _repack(src, out, edit) -> None:
    """Copy project `src` to `out` with edit(meta) applied to project.json."""
    with zipfile.ZipFile(src) as z:
        meta, png = json.loads(z.read("project.json")), z.read("base.png")
    edit(meta)
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("project.json", json.dumps(meta))
        z.writestr("base.png", png)


def full_doc(base) -> Document:
    doc = Document(base)
    add(doc, TextBoxItem, (20, 20, 220, 80), text="Look here",
        text_color="#FF0000", fill_color="#0000FF", border_color="#00FF00",
        border_width=3, font_family="Arial", font_px=30, bold=True,
        italic=True, align="center", opacity=0.8)
    r = add(doc, RectItem, (300, 20, 100, 60), fill_color="#4000FF00",
            stroke_width=5)
    add(doc, EllipseItem, (300, 120, 120, 80))
    add(doc, ArrowItem, (20, 300, 250, 220), stroke_width=6)
    add(doc, HighlightItem, (20, 150, 200, 30))
    doc.bring_to_front([r])
    return doc


def test_save_and_reopen_keeps_everything_editable(qapp, white, tmp_path):
    doc = full_doc(white)
    path = tmp_path / "shot.annotshot"
    doc.save(path)
    assert doc.undo_stack.isClean() and doc.path == str(path)
    with zipfile.ZipFile(path) as z:
        assert set(z.namelist()) == {"project.json", "base.png"}
        meta = json.loads(z.read("project.json"))
    assert (meta["format"], meta["version"], meta["size"]) == ("annotshot", 1, [640, 360])
    assert [d["type"] for d in meta["items"]] == \
        ["text", "ellipse", "arrow", "highlight", "rect"]

    doc2 = Document.load(path)
    before = [i.to_dict() for i in doc.annotation_items()]
    after = [i.to_dict() for i in doc2.annotation_items()]
    assert after == before                       # count, types, rects, z, props
    assert [type(i) for i in doc2.annotation_items()] == \
        [type(i) for i in doc.annotation_items()]
    assert doc2.base == doc.base and doc2.base.size() == white.size()
    assert doc2.render_image() == doc.render_image()
    assert doc2.undo_stack.count() == 0 and doc2.path == str(path)

    text = next(i for i in doc2.annotation_items() if isinstance(i, TextBoxItem))
    text.start_edit()
    assert text.is_editing and doc2.is_editing()
    assert text.editor.textInteractionFlags() == Qt.TextEditorInteraction
    cursor = text.editor.textCursor()
    cursor.insertText(" now")
    text.end_edit()
    assert not text.is_editing
    assert text.to_dict()["text"] == "Look here now"
    assert doc2.undo_stack.count() == 1          # one edit = one undo step
    doc2.undo_stack.undo()
    assert text.props["text"] == "Look here"
    assert text.editor.toPlainText() == "Look here"

    shape = next(i for i in doc2.annotation_items() if isinstance(i, EllipseItem))
    before_geom = {shape: shape.geom()}
    shape.setPos(shape.pos().x() + 30, shape.pos().y() + 5)
    assert doc2.commit_geometry(before_geom)
    assert shape.to_dict()["rect"] == [330, 125, 120, 80]


def test_load_accepts_a_legacy_snagup_file(qapp, white, tmp_path):
    """A file saved before the rename (.snagup, format "snagup", same zip)
    still opens."""
    doc = full_doc(white)
    path = tmp_path / "new.annotshot"
    doc.save(path)
    legacy = tmp_path / "old.snagup"
    _repack(path, legacy, lambda meta: meta.update(format="snagup"))
    doc2 = Document.load(legacy)
    assert [i.to_dict() for i in doc2.annotation_items()] ==         [i.to_dict() for i in doc.annotation_items()]


def test_load_skips_unknown_items_and_rejects_strangers(qapp, white, tmp_path):
    doc = full_doc(white)
    path = tmp_path / "a.annotshot"
    doc.save(path)
    with zipfile.ZipFile(path) as z:
        meta, png = json.loads(z.read("project.json")), z.read("base.png")
    meta["items"].append({"type": "blur", "rect": [0, 0, 5, 5]})
    odd = tmp_path / "odd.annotshot"
    with zipfile.ZipFile(odd, "w") as z:
        z.writestr("project.json", json.dumps(meta))
        z.writestr("base.png", png)
    with pytest.warns(UserWarning, match="blur"):
        doc2 = Document.load(odd)
    assert len(doc2.annotation_items()) == 5
    meta["format"] = "other"
    with zipfile.ZipFile(odd, "w") as z:
        z.writestr("project.json", json.dumps(meta))
        z.writestr("base.png", png)
    with pytest.raises(ValueError):
        Document.load(odd)


def test_load_rejects_items_that_are_not_a_list(qapp, white, tmp_path):
    path = tmp_path / "a.annotshot"
    full_doc(white).save(path)
    for bad in (None, 5):
        odd = tmp_path / "odd.annotshot"
        _repack(path, odd, lambda meta: meta.update(items=bad))
        with pytest.raises(ValueError, match="items"):
            Document.load(odd)
    _repack(path, odd, lambda meta: meta.pop("items"))   # missing: an empty list
    assert Document.load(odd).annotation_items() == []


def test_load_keeps_an_item_with_a_bad_color(qapp, white, tmp_path):
    doc = Document(white)
    add(doc, TextBoxItem, (20, 20, 200, 60), text="Keep me",
        fill_color="#0000FF")
    add(doc, RectItem, (300, 20, 100, 60), stroke_color="#00FF00",
        stroke_width=5)
    path, odd = tmp_path / "a.annotshot", tmp_path / "odd.annotshot"
    doc.save(path)

    def spoil(meta):
        meta["items"][0]["text_color"] = "not a color"
        meta["items"][1]["stroke_color"] = "#GG0000"
    _repack(path, odd, spoil)
    with warnings.catch_warnings():
        warnings.simplefilter("error")           # nothing is skipped
        doc2 = Document.load(odd)
    t, r = doc2.annotation_items()
    assert isinstance(t, TextBoxItem) and isinstance(r, RectItem)
    assert t.props["text_color"] == TextBoxItem.DEFAULTS["text_color"]
    assert (t.props["text"], t.props["fill_color"]) == ("Keep me", "#0000FF")
    assert r.props["stroke_color"] == RectItem.DEFAULTS["stroke_color"]
    assert r.props["stroke_width"] == 5


def test_png_export_pixels(qapp, white, tmp_path):
    doc = Document(white)
    add(doc, TextBoxItem, (20, 20, 200, 80), text="Hi", fill_color="#0000FF")
    r = add(doc, RectItem, (300, 20, 100, 60))
    add(doc, HighlightItem, (20, 150, 100, 30))
    add(doc, EllipseItem, (300, 120, 120, 80))
    r.setSelected(True)                          # frames/handles must not export
    out = tmp_path / "out.png"
    assert doc.render_image().save(str(out))
    img = QImage(str(out))
    assert out.stat().st_size > 0 and img.size() == white.size()
    assert px(img, 216, 96) == (0, 0, 255)       # fill inside the padding
    assert px(img, 21, 60) == (229, 57, 53)      # text box border
    assert px(img, 301, 50) == (229, 57, 53)     # rect stroke along the edge
    assert px(img, 350, 50) == (255, 255, 255)   # no fill inside the rect
    r_, g, b = px(img, 70, 165)                  # highlight over white
    assert r_ >= 250 and g >= 250 and 120 <= b <= 160, (r_, g, b)
    assert px(img, 297, 17) == (255, 255, 255)   # no handle drawn
    assert near(px(img, 300, 160), (229, 57, 53), 12)   # ellipse stroke, left
    assert px(img, 360, 160) == (255, 255, 255)  # no fill inside the ellipse
    assert px(img, 302, 122) == (255, 255, 255)  # round: the box corner stays white
    assert px(img, 500, 300) == (255, 255, 255)


def test_crop_offsets_items_and_undoes(qapp, white):
    base = QImage(white)
    base.setPixelColor(110, 60, QColor("#FF0000"))
    doc = Document(base)
    r = add(doc, RectItem, (150, 100, 50, 50))
    a = add(doc, ArrowItem, (120, 80, 200, 90))
    outside = add(doc, RectItem, (10, 10, 20, 20))
    assert doc.crop(QRect(100, 50, 300, 200))
    assert doc.base.size().toTuple() == (300, 200)
    assert doc.sceneRect() == QRectF(0, 0, 300, 200)
    assert px(doc.base, 10, 10) == (255, 0, 0)
    assert r.geom() == (50, 50, 50, 50)
    assert a.geom() == (20, 30, 100, 40)
    assert outside.geom() == (-90, -40, 20, 20) and outside.scene() is doc
    assert doc.render_image().size().toTuple() == (300, 200)
    doc.undo_stack.undo()
    assert doc.base.size().toTuple() == (640, 360)
    assert doc.sceneRect() == QRectF(0, 0, 640, 360)
    assert r.geom() == (150, 100, 50, 50) and a.geom() == (120, 80, 200, 90)
    doc.undo_stack.redo()
    assert doc.base.size().toTuple() == (300, 200) and r.geom() == (50, 50, 50, 50)
    assert not doc.crop(QRect(0, 0, 300, 200))   # the whole image: nothing to do


def test_pen_stroke_saves_reopens_and_exports(qapp, white, tmp_path):
    """A pen stroke round-trips through .annotshot with equal points and props,
    stays a pen stroke (editable: it moves after reopening), and paints on
    the exported PNG."""
    doc = Document(white)
    pen = PenItem()
    pen.apply_props({"stroke_color": "#0000FF", "stroke_width": 8,
                     "opacity": 0.9})
    pen.set_points([(40, 300), (120, 260), (200.5, 300.25), (300, 250)])
    doc.add_items([pen])
    add(doc, RectItem, (400, 20, 100, 60))
    path = tmp_path / "pen.annotshot"
    doc.save(path)
    with zipfile.ZipFile(path) as z:
        meta = json.loads(z.read("project.json"))
    (d,) = [i for i in meta["items"] if i["type"] == "pen"]
    assert d["points"] == [[40, 300], [120, 260], [200.5, 300.25], [300, 250]]
    assert (d["stroke_color"], d["stroke_width"], d["opacity"]) == \
        ("#0000FF", 8, 0.9)

    doc2 = Document.load(path)
    pen2 = next(i for i in doc2.annotation_items() if isinstance(i, PenItem))
    assert pen2.to_dict() == pen.to_dict()
    assert [(p.x(), p.y()) for p in pen2.scene_points()] == \
        [(p.x(), p.y()) for p in pen.scene_points()]
    assert pen2.props == pen.props and pen2.zValue() == pen.zValue()
    assert doc2.render_image() == doc.render_image()
    before = {pen2: pen2.geom()}
    pen2.moveBy(10, 0)
    assert doc2.commit_geometry(before)
    assert pen2.to_dict()["points"][0] == [50, 300]

    out = tmp_path / "pen.png"
    doc.set_props([pen], {"opacity": 1.0})
    assert doc.render_image().save(str(out))
    img = QImage(str(out))
    assert px(img, 40, 300) == (0, 0, 255)       # the stroke's first point
    assert px(img, 300, 250) == (0, 0, 255)      # its last
    assert px(img, 40, 320) == (255, 255, 255)   # beside it: the picture
