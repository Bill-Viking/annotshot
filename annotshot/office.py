"""Word and PowerPoint export: the finished picture on page 1 of a Word
document, or on one PowerPoint slide."""
from __future__ import annotations

import errno
import io
import os
import shutil
import sys
import tempfile

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage

OFFICE_FORMATS = ("DOCX", "PPTX")
SLIDE_MARGIN_IN = 0.4
EMU_PER_INCH = 914400
SCREEN_DPI = 96
# 13.333 x 7.5 in: the 16:9 slide PowerPoint makes for a new presentation
SLIDE_WIDTH_EMU, SLIDE_HEIGHT_EMU = 12192000, 6858000


def png_stream(img: QImage) -> io.BytesIO:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    if not img.save(buf, "PNG"):
        raise OSError("the picture could not be encoded")
    stream = io.BytesIO(bytes(buf.data()))
    buf.close()
    return stream


def _new_file_mode() -> int:
    """The permission bits a newly created file gets here (0666 less the
    process's umask); a private temp file is opened to these."""
    if sys.platform == "win32":
        return 0o666
    mask = os.umask(0)
    os.umask(mask)
    return 0o666 & ~mask


def _write_safely(save, path: str) -> None:
    """Build the whole file in memory with `save(stream)`, write it to a
    hidden temp file of its own in the same folder, then put it in place.
    A failure at any point leaves an existing file untouched and removes
    only the temp file this save made; the error is raised again.

    The file put in place keeps the old file's permission bits; a link is
    followed, so the file it points at is replaced and the link stays; a
    read-only file is refused, as writing straight onto it would be."""
    target = os.path.realpath(path)
    if os.path.isdir(target):
        raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), path)
    exists = os.path.exists(target)
    if exists and not os.access(target, os.W_OK):
        raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), path)
    stream = io.BytesIO()
    save(stream)
    folder, name = os.path.split(target)
    tmp = None
    try:
        short = name.encode("utf-8")[:200].decode("utf-8", "ignore")
        fd, tmp = tempfile.mkstemp(prefix="." + short + ".", suffix=".tmp",
                                   dir=folder)  # at most 214 bytes: a long name still saves
        with os.fdopen(fd, "wb") as f:
            f.write(stream.getvalue())
        if exists:
            shutil.copymode(target, tmp)
        else:
            os.chmod(tmp, _new_file_mode())
        os.replace(tmp, target)
    except BaseException:
        if tmp is not None:
            try:
                os.remove(tmp)
            except OSError:
                pass                    # already gone
        raise


def export_docx(img: QImage, path: str) -> None:
    """The picture centred in a new paragraph, as wide as the text area at
    most and never wider than its own pixels at 96 dpi; never taller than
    the page's text area."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Emu
    doc = Document()
    sec = doc.sections[-1]
    text_w = sec.page_width - sec.left_margin - sec.right_margin
    text_h = sec.page_height - sec.top_margin - sec.bottom_margin
    w = img.width() / SCREEN_DPI * EMU_PER_INCH
    h = img.height() / SCREEN_DPI * EMU_PER_INCH
    scale = min(1.0, text_w / w, text_h / h)
    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.add_run().add_picture(png_stream(img), width=Emu(int(w * scale)),
                               height=Emu(int(h * scale)))
    _write_safely(doc.save, path)


def _blank_layout(prs):
    layouts = list(prs.slide_layouts)
    for layout in layouts:
        if layout.name.strip().lower() == "blank":
            return layout
    return min(reversed(layouts), key=lambda l: len(l.placeholders))


# Where each kind of shape keeps its own position and size.
_XFRM = {"sp": "p:spPr/a:xfrm", "pic": "p:spPr/a:xfrm",
         "cxnSp": "p:spPr/a:xfrm", "grpSp": "p:grpSpPr/a:xfrm",
         "graphicFrame": "p:xfrm"}


def _resize(prs, width: int, height: int) -> None:
    """Set the slide size and move and stretch the slide master's and every
    layout's own shapes to match, so a slide added later in PowerPoint has
    its title and content boxes across the whole slide."""
    from pptx.oxml.ns import qn
    sx, sy = width / prs.slide_width, height / prs.slide_height
    prs.slide_width, prs.slide_height = width, height
    for master in prs.slide_masters:
        for part in (master, *master.slide_layouts):
            for shape in part.shapes._spTree.iterchildren():
                tag = shape.tag.rsplit("}", 1)[-1]
                if tag not in _XFRM:
                    continue
                xfrm = shape.xpath(_XFRM[tag])
                if not xfrm:
                    continue            # placed by the master: follows it
                for el, x, y in (("a:off", "x", "y"), ("a:ext", "cx", "cy")):
                    for box in xfrm[0].findall(qn(el)):
                        box.set(x, str(round(int(box.get(x)) * sx)))
                        box.set(y, str(round(int(box.get(y)) * sy)))


def export_pptx(img: QImage, path: str) -> None:
    """One 16:9 slide (the blank layout) with the picture centred and
    fitted inside a 0.4 in margin."""
    from pptx import Presentation
    from pptx.util import Emu
    prs = Presentation()
    _resize(prs, SLIDE_WIDTH_EMU, SLIDE_HEIGHT_EMU)
    margin = SLIDE_MARGIN_IN * EMU_PER_INCH
    box_w, box_h = prs.slide_width - 2 * margin, prs.slide_height - 2 * margin
    scale = min(box_w / img.width(), box_h / img.height())
    w, h = int(img.width() * scale), int(img.height() * scale)
    slide = prs.slides.add_slide(_blank_layout(prs))
    for ph in list(slide.placeholders):
        ph._element.getparent().remove(ph._element)
    slide.shapes.add_picture(png_stream(img), Emu((prs.slide_width - w) // 2),
                             Emu((prs.slide_height - h) // 2), Emu(w), Emu(h))
    _write_safely(prs.save, path)


def export(fmt: str, img: QImage, path: str) -> None:
    (export_docx if fmt == "DOCX" else export_pptx)(img, path)
