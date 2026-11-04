"""The Word / PowerPoint export: the picture on page 1 or on one slide, and
the Save window's two new types."""
import pytest
from PySide6.QtGui import QColor, QImage

from annotshot import office

PICTURE = 13                                       # MSO_SHAPE_TYPE.PICTURE


def picture(w, h):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor("#0878D5"))
    return img


def aspect_kept(cx, cy, w, h):
    return abs(cx * h / w - cy) <= 1 or abs(cy * w / h - cx) <= 1


@pytest.mark.parametrize("size", [(1600, 900), (300, 200), (400, 3000)])
def test_docx_holds_the_fitted_picture(qapp, tmp_path, size):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    out = tmp_path / "a.docx"
    office.export_docx(picture(*size), str(out))
    doc = Document(str(out))
    assert len(doc.inline_shapes) == 1
    shape, sec = doc.inline_shapes[0], doc.sections[-1]
    text_w = sec.page_width - sec.left_margin - sec.right_margin
    text_h = sec.page_height - sec.top_margin - sec.bottom_margin
    assert shape.width <= text_w and shape.height <= text_h
    assert shape.width <= size[0] / 96 * 914400 + 1    # never past 96 dpi
    assert aspect_kept(shape.width, shape.height, *size)
    assert doc.paragraphs[-1].alignment == WD_ALIGN_PARAGRAPH.CENTER
    if size == (1600, 900):
        assert abs(shape.width - text_w) <= 1          # as wide as the text
    if size == (300, 200):
        assert abs(shape.width - 300 / 96 * 914400) <= 1


@pytest.mark.parametrize("size", [(1600, 900), (300, 1200), (40, 30)])
def test_pptx_is_one_slide_with_the_centred_picture(qapp, tmp_path, size):
    from pptx import Presentation
    out = tmp_path / "b.pptx"
    office.export_pptx(picture(*size), str(out))
    prs = Presentation(str(out))
    assert len(prs.slides) == 1
    assert prs.slides[0].slide_layout.name == "Blank"
    shapes = list(prs.slides[0].shapes)
    assert len(shapes) == 1 and shapes[0].shape_type == PICTURE
    p, m = shapes[0], int(0.4 * 914400)
    assert p.left >= m - 1 and p.top >= m - 1
    assert p.left + p.width <= prs.slide_width - m + 1
    assert p.top + p.height <= prs.slide_height - m + 1
    assert abs(p.left * 2 + p.width - prs.slide_width) <= 1
    assert abs(p.top * 2 + p.height - prs.slide_height) <= 1
    assert aspect_kept(p.width, p.height, *size)


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    from annotshot import mainwindow
    from annotshot.app import make_app
    from annotshot.mainwindow import MainWindow
    make_app()
    w = MainWindow()
    monkeypatch.setattr(w.doc, "render_image", lambda: picture(320, 200))
    monkeypatch.setattr(mainwindow, "DEFAULT_DIR", tmp_path)
    yield w
    w.deleteLater()


def _save(window, monkeypatch, path, chosen):
    from annotshot import mainwindow
    monkeypatch.setattr(mainwindow.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a: (str(path), chosen)))
    return window.save_as()


@pytest.mark.parametrize("name,chosen", [
    ("shot", "Word document (*.docx)"),
    ("slide.pptx", "PowerPoint slide (*.pptx)")])
def test_save_as_word_or_powerpoint(window, monkeypatch, tmp_path, name,
                                    chosen):
    from annotshot.items import RectItem
    r = RectItem()
    r.set_geom((10, 10, 80, 60))
    window.doc.add_items([r])                         # an unsaved edit
    assert window.doc.undo_stack.needs_save()
    assert _save(window, monkeypatch, tmp_path / name, chosen)
    ext = "docx" if "Word" in chosen else "pptx"
    out = tmp_path / (name if name.endswith(ext) else f"{name}.{ext}")
    assert out.is_file()
    if ext == "docx":
        from docx import Document
        assert len(Document(str(out)).inline_shapes) == 1
    else:
        from pptx import Presentation
        assert len(Presentation(str(out)).slides) == 1
    assert window.statusBar().currentMessage() == f"Saved {out.name}"
    assert window.settings.value("last_filter/save") == chosen
    assert not window.doc.undo_stack.needs_save()     # counts as done
    assert not window.isWindowModified()


def test_a_failed_export_warns_and_counts_as_not_saved(window, monkeypatch,
                                                       tmp_path):
    from annotshot import mainwindow
    warned = []
    monkeypatch.setattr(mainwindow.QMessageBox, "warning",
                        staticmethod(lambda *a: warned.append(a[2])))
    out = tmp_path / "no-such-folder" / "z.docx"
    assert not _save(window, monkeypatch, out, "Word document (*.docx)")
    assert not out.exists()
    assert warned and warned[0].startswith("Could not save z.docx:")


def test_the_slide_is_16_by_9(qapp, tmp_path):
    from pptx import Presentation
    out = tmp_path / "wide.pptx"
    office.export_pptx(picture(1600, 900), str(out))
    prs = Presentation(str(out))
    assert (prs.slide_width, prs.slide_height) == (12192000, 6858000)


def _fail_on_third_write(monkeypatch):
    """The libraries' zip writer fails part-way, as a full disk would."""
    import zipfile
    real, calls = zipfile.ZipFile.writestr, []

    def writestr(self, *a, **k):
        calls.append(1)
        if len(calls) == 3:
            raise OSError(28, "No space left on device")
        return real(self, *a, **k)
    monkeypatch.setattr(zipfile.ZipFile, "writestr", writestr)
    return calls


@pytest.mark.parametrize("name,chosen", [
    ("keep.docx", "Word document (*.docx)"),
    ("keep.pptx", "PowerPoint slide (*.pptx)")])
def test_a_failed_save_leaves_an_existing_file_untouched(
        window, monkeypatch, tmp_path, name, chosen):
    from annotshot import mainwindow
    from annotshot.items import RectItem
    out = tmp_path / name
    assert _save(window, monkeypatch, out, chosen)    # a good file first
    before = out.read_bytes()
    r = RectItem()
    r.set_geom((10, 10, 80, 60))
    window.doc.add_items([r])                         # an unsaved edit
    warned = []
    monkeypatch.setattr(mainwindow.QMessageBox, "warning",
                        staticmethod(lambda *a: warned.append(a[2])))
    calls = _fail_on_third_write(monkeypatch)
    assert not _save(window, monkeypatch, out, chosen)
    assert len(calls) == 3                            # it did fail part-way
    assert out.read_bytes() == before                 # byte for byte
    assert sorted(p.name for p in tmp_path.iterdir()
                  if p.suffix != ".ini") == [name]    # no .tmp left
    assert warned and warned[0].startswith(f"Could not save {name}:")
    assert window.doc.undo_stack.needs_save()         # not counted as done
    assert window.isWindowModified()


@pytest.mark.parametrize("name,chosen", [
    ("fresh.docx", "Word document (*.docx)"),
    ("fresh.pptx", "PowerPoint slide (*.pptx)")])
def test_a_failed_save_leaves_no_new_file(window, monkeypatch, tmp_path,
                                          name, chosen):
    from annotshot import mainwindow
    monkeypatch.setattr(mainwindow.QMessageBox, "warning",
                        staticmethod(lambda *a: None))
    _fail_on_third_write(monkeypatch)
    assert not _save(window, monkeypatch, tmp_path / name, chosen)
    assert [p.name for p in tmp_path.iterdir() if p.suffix != ".ini"] == []


def _ask(monkeypatch, answer):
    from annotshot import mainwindow
    asked = []

    def question(*a, **k):
        asked.append(a)
        return answer
    monkeypatch.setattr(mainwindow.QMessageBox, "question",
                        staticmethod(question))
    return asked


def test_a_type_that_renames_onto_an_existing_file_asks_no(
        window, monkeypatch, tmp_path):
    """Typed report.png, the Word type chosen: report.docx is already there,
    so the app asks; No writes nothing."""
    from annotshot import mainwindow
    old = tmp_path / "report.docx"
    old.write_bytes(b"MY EARLIER REPORT")
    asked = _ask(monkeypatch, mainwindow.QMessageBox.No)
    assert not _save(window, monkeypatch, tmp_path / "report.png",
                     "Word document (*.docx)")
    assert len(asked) == 1
    parent, title, text = asked[0][:3]
    assert title == "Annotshot"
    assert text == (f"Replace report.docx?\n\nA file with this name is "
                    f"already in {tmp_path.name}.")
    assert asked[0][4] == mainwindow.QMessageBox.No       # the default
    assert old.read_bytes() == b"MY EARLIER REPORT"
    assert not (tmp_path / "report.png").exists()
    assert window.settings.value("last_filter/save") is None


def test_a_type_that_renames_onto_an_existing_file_asks_yes(
        window, monkeypatch, tmp_path):
    from docx import Document
    from annotshot import mainwindow
    old = tmp_path / "report.docx"
    old.write_bytes(b"MY EARLIER REPORT")
    asked = _ask(monkeypatch, mainwindow.QMessageBox.Yes)
    assert _save(window, monkeypatch, tmp_path / "report.png",
                 "Word document (*.docx)")
    assert len(asked) == 1
    assert len(Document(str(old)).inline_shapes) == 1     # replaced
    assert not (tmp_path / "report.png").exists()


def test_no_extra_question_when_the_name_is_unchanged_or_new(
        window, monkeypatch, tmp_path):
    """The Save window already asked about a name the type keeps; a new
    name needs no question."""
    (tmp_path / "same.docx").write_bytes(b"old")
    asked = _ask(monkeypatch, None)
    assert _save(window, monkeypatch, tmp_path / "same.docx",
                 "Word document (*.docx)")
    assert _save(window, monkeypatch, tmp_path / "new.png",
                 "Word document (*.docx)")
    assert asked == [] and (tmp_path / "new.docx").is_file()


# -- a copy without the Word / PowerPoint parts -------------------------------

PINS = "python-docx==1.2.0 python-pptx==1.0.2"


@pytest.mark.parametrize("hidden,name,chosen", [
    ("docx", "plain.docx", "Word document (*.docx)"),
    ("pptx", "plain.pptx", "PowerPoint slide (*.pptx)")])
def test_missing_parts_give_the_plain_install_line(window, monkeypatch,
                                                   tmp_path, hidden, name,
                                                   chosen):
    import sys
    from annotshot import mainwindow
    from annotshot.items import RectItem
    monkeypatch.setitem(sys.modules, hidden, None)    # the library is absent
    r = RectItem()
    r.set_geom((10, 10, 80, 60))
    window.doc.add_items([r])                         # an unsaved edit
    warned = []
    monkeypatch.setattr(mainwindow.QMessageBox, "warning",
                        staticmethod(lambda *a: warned.append(a[2])))
    assert not _save(window, monkeypatch, tmp_path / name, chosen)
    assert warned == [
        "Saving as Word or PowerPoint needs two more parts that this copy "
        "of Annotshot does not have yet.\n"
        "In a terminal, run:\n"
        + mainwindow.pip_command()]
    assert warned[0].endswith(f" -m pip install {PINS}")
    assert [p.name for p in tmp_path.iterdir() if p.suffix != ".ini"] == []
    assert window.doc.undo_stack.needs_save()         # not counted as done
    assert window.isWindowModified()
    assert window.settings.value("last_filter/save") is None


def test_the_install_line_names_the_release_pins():
    """The versions in the plain warning are the ones the release builds."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    workflow = (root / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8")
    source = (root / "annotshot" / "mainwindow.py").read_text(encoding="utf-8")
    for pin in PINS.split():
        assert f'"{pin}"' in workflow
        assert pin in source


# -- the licence texts a frozen app carries ------------------------------------

def test_the_licence_check_counts_the_texts(tmp_path):
    from annotshot.__main__ import _check_licences
    lic = tmp_path / "licenses"
    lic.mkdir()
    for n in ("LGPL-3.0.txt", "GPL-3.0.txt"):
        (lic / n).write_text("text", encoding="utf-8")
    assert _check_licences(tmp_path) == 2
    (tmp_path / "LICENSE").write_text("mit", encoding="utf-8")
    meta = tmp_path / "lxml-6.1.3.dist-info" / "licenses"
    meta.mkdir(parents=True)
    (meta / "LICENSE.txt").write_text("bsd", encoding="utf-8")
    (meta.parent / "METADATA").write_text("m", encoding="utf-8")
    assert _check_licences(tmp_path) == 4


@pytest.mark.parametrize("missing", ["LGPL-3.0.txt", "GPL-3.0.txt"])
def test_the_licence_check_fails_naming_the_missing_text(tmp_path, missing):
    from annotshot.__main__ import _check_licences
    lic = tmp_path / "licenses"
    lic.mkdir()
    for n in ("LGPL-3.0.txt", "GPL-3.0.txt"):
        if n != missing:
            (lic / n).write_text("text", encoding="utf-8")
    with pytest.raises(RuntimeError, match=f"licenses/{missing}"):
        _check_licences(tmp_path)


def test_the_bundled_texts_are_the_gnu_texts():
    """The two texts the app carries are the verbatim GNU version 3 texts."""
    import hashlib
    from pathlib import Path
    lic = Path(__file__).resolve().parent.parent / "packaging" / "licenses"
    sums = {n: hashlib.sha256((lic / n).read_bytes()).hexdigest()
            for n in ("LGPL-3.0.txt", "GPL-3.0.txt")}
    assert sums == {
        "LGPL-3.0.txt":
            "e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118",
        "GPL-3.0.txt":
            "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"}


# -- s2 polish: the 16:9 master and layouts, the safe save's edges -------------

def test_every_layout_fits_the_16_by_9_slide(qapp, tmp_path):
    """A slide a coworker adds in PowerPoint gets boxes across the whole
    slide: the master's and every layout's shapes were stretched with it."""
    from pptx import Presentation
    out = tmp_path / "wide.pptx"
    office.export_pptx(picture(1600, 900), str(out))
    prs = Presentation(str(out))
    sw, sh = prs.slide_width, prs.slide_height
    for part in (prs.slide_master, *prs.slide_layouts):
        for ph in part.placeholders:
            assert ph.left >= 0 and ph.top >= 0, (part.name, ph.name)
            assert ph.left + ph.width <= sw + 1, (part.name, ph.name)
            assert ph.top + ph.height <= sh + 1, (part.name, ph.name)
    content = next(l for l in prs.slide_layouts
                   if l.name == "Title and Content")
    boxes = [ph for ph in content.placeholders
             if ph.placeholder_format.idx in (0, 1)]   # title, content
    assert len(boxes) == 2
    for ph in boxes:
        assert ph.width >= 0.9 * sw, ph.name


def _others(folder, keep=()):
    return sorted(p.name for p in folder.iterdir()
                  if p.suffix != ".ini" and p.name not in keep)


def test_a_users_own_tmp_file_is_never_touched(window, monkeypatch, tmp_path):
    """The save's temp file is its own: keep.docx.tmp, a file of the user's,
    survives a failed save and a good one, byte for byte."""
    from annotshot import mainwindow
    out, mine = tmp_path / "keep.docx", tmp_path / "keep.docx.tmp"
    out.write_bytes(b"GOOD")
    mine.write_bytes(b"MY OWN NOTES")
    monkeypatch.setattr(mainwindow.QMessageBox, "warning",
                        staticmethod(lambda *a: None))
    _fail_on_third_write(monkeypatch)
    assert not _save(window, monkeypatch, out, "Word document (*.docx)")
    assert out.read_bytes() == b"GOOD"
    assert mine.read_bytes() == b"MY OWN NOTES"
    assert _others(tmp_path) == ["keep.docx", "keep.docx.tmp"]
    monkeypatch.undo()                                 # the disk is fine again
    monkeypatch.setattr(window.doc, "render_image", lambda: picture(320, 200))
    assert _save(window, monkeypatch, out, "Word document (*.docx)")
    assert out.read_bytes()[:2] == b"PK"               # the new document
    assert mine.read_bytes() == b"MY OWN NOTES"
    assert _others(tmp_path) == ["keep.docx", "keep.docx.tmp"]


@pytest.mark.skipif(__import__("sys").platform == "win32",
                    reason="POSIX permission bits")
def test_a_replaced_file_keeps_its_permission_bits(window, monkeypatch,
                                                   tmp_path):
    import os
    import stat
    out = tmp_path / "private.docx"
    out.write_bytes(b"P")
    out.chmod(0o600)
    assert _save(window, monkeypatch, out, "Word document (*.docx)")
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    fresh = tmp_path / "fresh.docx"
    mask = os.umask(0)
    os.umask(mask)
    assert _save(window, monkeypatch, fresh, "Word document (*.docx)")
    assert stat.S_IMODE(fresh.stat().st_mode) == 0o666 & ~mask


def test_a_link_is_followed_and_kept(window, monkeypatch, tmp_path):
    import os
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    real = elsewhere / "real.docx"
    real.write_bytes(b"REAL")
    link = tmp_path / "link.docx"
    try:
        os.symlink(real, link)
    except (OSError, NotImplementedError):
        pytest.skip("this system makes no links here")
    assert _save(window, monkeypatch, link, "Word document (*.docx)")
    assert link.is_symlink()
    assert real.read_bytes()[:2] == b"PK"              # written through it
    assert _others(elsewhere) == ["real.docx"]


def test_a_long_file_name_still_saves(window, monkeypatch, tmp_path):
    """A 250-character name, inside every system's 255, saves: the hidden
    temp file's own name stays short."""
    out = tmp_path / ("a" * 245 + ".docx")
    monkeypatch.setattr(window.doc, "render_image", lambda: picture(320, 200))
    assert _save(window, monkeypatch, out, "Word document (*.docx)")
    assert out.read_bytes()[:2] == b"PK"
    assert _others(tmp_path) == [out.name]


def test_a_read_only_file_is_refused_plainly(window, monkeypatch, tmp_path):
    import os
    import stat
    from annotshot import mainwindow
    ro = tmp_path / "ro.docx"
    ro.write_bytes(b"READONLY")
    ro.chmod(stat.S_IREAD)
    warned = []
    monkeypatch.setattr(mainwindow.QMessageBox, "warning",
                        staticmethod(lambda *a: warned.append(a[2])))
    try:
        assert not _save(window, monkeypatch, ro, "Word document (*.docx)")
        assert ro.read_bytes() == b"READONLY"
        assert warned == ["Could not save ro.docx: no permission"]
        assert _others(tmp_path) == ["ro.docx"]
    finally:
        os.chmod(ro, stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.parametrize("error,reason", [
    (FileNotFoundError(2, "No such file or directory",
                       "/x/.z.docx.ab12.tmp"), "the folder is missing"),
    (PermissionError(13, "Permission denied", "/x/.z.docx.ab12.tmp"),
     "no permission"),
    (OSError(28, "No space left on device"), "the disk is full"),
    (OSError(5, "Input/output error"), "Input/output error"),
    (OSError("the picture could not be encoded"),
     "the picture could not be encoded")])
def test_the_save_warning_names_the_chosen_file(error, reason):
    from annotshot.mainwindow import save_problem
    line = save_problem("/x/z.docx", error)
    assert line == f"Could not save z.docx: {reason}"
    assert ".tmp" not in line and "Errno" not in line


def test_a_missing_folder_is_said_plainly(window, monkeypatch, tmp_path):
    from annotshot import mainwindow
    warned = []
    monkeypatch.setattr(mainwindow.QMessageBox, "warning",
                        staticmethod(lambda *a: warned.append(a[2])))
    assert not _save(window, monkeypatch, tmp_path / "gone" / "z.docx",
                     "Word document (*.docx)")
    assert warned == ["Could not save z.docx: the folder is missing"]


@pytest.mark.parametrize("exe,platform,beside,line", [
    # pythonw has no console: python.exe beside it is named
    (r"C:\Py\pythonw.exe", "win32", True, r"C:\Py\python.exe"),
    (r"C:\Py\PYTHONW.EXE", "win32", True, r"C:\Py\python.exe"),
    (r"C:\Py\pythonw.exe", "win32", False, r"C:\Py\pythonw.exe"),
    # a path with a space: PowerShell's call operator, quoted
    (r"C:\Program Files\Py\python.exe", "win32", True,
     r'& "C:\Program Files\Py\python.exe"'),
    (r"C:\My Apps\Annotshot\.venv\Scripts\pythonw.exe", "win32", True,
     r'& "C:\My Apps\Annotshot\.venv\Scripts\python.exe"'),
    (r"C:\Users\a$b\py.exe", "win32", True, r'& "C:\Users\a`$b\py.exe"'),
    # elsewhere, the shell's own quoting
    ("/usr/bin/python3", "darwin", True, "/usr/bin/python3"),
    ("/home/a b/.venv/bin/python", "linux", True,
     "'/home/a b/.venv/bin/python'")])
def test_the_install_line_runs_where_it_is_pasted(exe, platform, beside, line):
    from annotshot.mainwindow import pip_command
    got = pip_command(exe, platform, isfile=lambda p: beside)
    assert got == f"{line} -m pip install {PINS}"
