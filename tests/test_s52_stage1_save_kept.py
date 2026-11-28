"""Stage 1: save the capture under the pointer without opening it."""
from pathlib import Path
import zipfile

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QKeySequence, QShortcutEvent
from PySide6.QtWidgets import QApplication, QListWidgetItem, QMessageBox

from annotshot import mainwindow, recent
from annotshot.items import RectItem, TextBoxItem
from annotshot.scene import Document


@pytest.fixture
def window(qapp, monkeypatch):
    from annotshot.app import make_app
    make_app()
    w = mainwindow.MainWindow()
    warnings = []
    monkeypatch.setattr(w, "_warn", warnings.append)
    w.save_warnings = warnings
    yield w
    w._autosave_timer.stop()
    recent.writer().waitForDone(5000)
    w.deleteLater()


def capture(w, name="B", edited=False, png=True):
    folder = w.recent_store.folder
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.png"
    image = QImage(480, 260, QImage.Format_ARGB32)
    image.fill(Qt.white)
    if png:
        assert image.save(str(path), "PNG")
    doc = Document(image)
    if edited:
        r = RectItem()
        r.set_geom((40, 40, 100, 80))
        r.props.update(fill_color="#F02030", stroke_color="#F02030")
        doc.add_items([r])
        doc.crop(QRect(20, 20, 400, 220))
        doc.save(recent.editable_for(path))
    return path, doc


def item_for(path):
    item = QListWidgetItem()
    item.setData(Qt.UserRole, str(path))
    return item


def choose(monkeypatch, path, kind=0):
    calls = []
    chosen = mainwindow.SAVE_TYPES[kind][0]
    def dialog(*args, **kwargs):
        calls.append((args, kwargs))
        return (str(path) if path is not None else "", chosen)
    monkeypatch.setattr(mainwindow.QFileDialog, "getSaveFileName", dialog)
    return calls


def save(w, path):
    # Drive the real menu even on the baseline, where the missing action is
    # the specific missing route. Do not silently substitute editor Save.
    menu = w.recent.menu_for(item_for(path))
    action = next((a for a in menu.actions() if a.text() == "Save…"), None)
    assert action is not None, "Recent has no Save… route"
    action.trigger()


def remembered(w):
    return (w.settings.value("last_dir/save"),
            w.settings.value("last_filter/save"))


def test_r15_menu_targets_pointer_without_opening(window, monkeypatch, tmp_path):
    path, _ = capture(window)
    opened = []
    window.recent.openRequested.connect(opened.append)
    menu = window.recent.menu_for(item_for(path))
    assert [a.text() for a in menu.actions()] == [
        "Open", "Save…", "Show in folder", "", "Delete", "", "Clear recent captures"]
    bare = window.recent.menu_for(None).actions()
    assert [a.isEnabled() for a in bare[:3]] == [False, False, True]
    assert not bare[4].isEnabled()                  # Delete needs a thumbnail
    calls = choose(monkeypatch, tmp_path / "out.png")
    menu.actions()[1].trigger()
    assert len(calls) == 1 and calls[0][0][0] is window
    assert not opened


def test_r16_saving_b_preserves_unsaved_a(window, monkeypatch, tmp_path):
    b, _ = capture(window, edited=True)
    a = Document(QImage(200, 100, QImage.Format_ARGB32))
    mark = RectItem()
    mark.set_geom((5, 5, 40, 30))
    a.add_items([mark])
    a.select_only([mark])
    window._bind(a)
    stack = a.undo_stack
    before = (a.path, a.to_dict(), a.selected(), stack.index(), stack.count(),
              stack.isClean(), stack.needs_save(), window.isWindowModified())
    choose(monkeypatch, tmp_path / "B.png")
    save(window, b)
    assert (tmp_path / "B.png").is_file()
    assert window.doc is a and window.undo_group.activeStack() is stack
    assert before == (a.path, a.to_dict(), a.selected(), stack.index(), stack.count(),
                      stack.isClean(), stack.needs_save(), window.isWindowModified())


@pytest.mark.parametrize("kind", range(6))
@pytest.mark.parametrize("source", ["png", "pair", "editable-only"])
def test_r17_full_size_marks_crop_every_picture_type(
        window, monkeypatch, tmp_path, kind, source):
    b, expected_doc = capture(window, edited=source != "png", png=source != "editable-only")
    expected = expected_doc.render_image()
    ext, fmt = mainwindow.SAVE_TYPES[kind][1][0], mainwindow.SAVE_TYPES[kind][2]
    out = tmp_path / f"result.{ext}"
    choose(monkeypatch, out, kind)
    save(window, b)
    assert out.is_file()
    if fmt in ("DOCX", "PPTX"):
        with zipfile.ZipFile(out) as z:
            media = [n for n in z.namelist() if "/media/" in n and n.endswith(".png")]
            assert len(media) == 1
            actual = QImage.fromData(z.read(media[0]))
    else:
        actual = QImage(str(out))
    assert actual.size() == expected.size() and actual.width() > recent.THUMB.width()
    # Crop moved the mark from (40,40) to (20,20). The raw base is white.
    if source != "png":
        ink = actual.pixelColor(60, 50)
        assert ink.red() > 180 and ink.green() < 90
    if fmt in mainwindow.NO_ALPHA_FORMATS:
        assert actual.pixelColor(300, 180).alpha() == 255
        assert actual.pixelColor(300, 180).red() > 245
    elif fmt != "WEBP":
        assert actual.convertToFormat(QImage.Format_ARGB32) == \
            expected.convertToFormat(QImage.Format_ARGB32)


@pytest.mark.parametrize("edited", [False, True])
def test_r18_editable_copy_reopens_objects_without_adopting_path(
        window, monkeypatch, tmp_path, edited):
    b, doc = capture(window, edited=edited)
    active, path = window.doc, window.doc.path
    out = tmp_path / "copy.annotshot"
    choose(monkeypatch, out, 6)
    save(window, b)
    loaded = Document.load(out)
    assert loaded.to_dict() == doc.to_dict()
    assert loaded.base == doc.base
    assert window.doc is active and active.path == path


@pytest.mark.parametrize("queued", [False, True])
def test_r19_shown_capture_finishes_text_and_snapshots(window, monkeypatch, tmp_path, queued):
    b, doc = capture(window, edited=True)
    window._bind(doc)
    text = TextBoxItem()
    text.set_geom((5, 5, 200, 60))
    doc.add_items([text])
    text.start_edit()
    text.editor.setPlainText("Visible when Save was invoked")
    if queued:
        window.autosave_now(doc, end_edit=True)
    out = tmp_path / "live.annotshot"
    calls = choose(monkeypatch, out, 6)
    save(window, b)
    loaded = Document.load(out)
    assert not doc.is_editing()
    assert any(i.props.get("text") == "Visible when Save was invoked"
               for i in loaded.annotation_items())
    assert len(calls) == 1 and doc.path == str(recent.editable_for(b))


def test_r19_other_capture_waits_for_latest_write_or_reports_error(window, monkeypatch, tmp_path):
    b, doc = capture(window, edited=True)
    window._bind(doc)
    doc.set_props(doc.annotation_items(), {"border_width": 17})
    window.autosave_now()
    # Binding A leaves B's writer queued and its completion signal undelivered.
    window._bind(Document())
    out = tmp_path / "settled.annotshot"
    choose(monkeypatch, out, 6)
    save(window, b)
    assert Document.load(out).annotation_items()[0].props["stroke_width"] == 17


def test_r20_selected_type_final_collision_asks_once_safe_default(window, monkeypatch, tmp_path):
    b, _ = capture(window)
    final = tmp_path / "report.docx"
    final.write_bytes(b"existing")
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a: asked.append(a) or QMessageBox.Yes)
    calls = choose(monkeypatch, tmp_path / "report.png", 4)
    save(window, b)
    assert len(calls) == len(asked) == 1
    assert calls[0][0][3] == mainwindow.SAVE_FILTERS
    assert calls[0][1]["options"] & mainwindow.QFileDialog.DontConfirmOverwrite
    assert asked[0][4] == QMessageBox.No
    assert not (tmp_path / "report.png").exists()
    with zipfile.ZipFile(final) as z:
        assert "word/document.xml" in z.namelist()


@pytest.mark.parametrize("alias", ["direct", "symlink", "hardlink", "folder-alias"])
@pytest.mark.parametrize("editable", [False, True])
def test_r21_kept_sources_refused_by_resolved_identity(
        window, monkeypatch, tmp_path, alias, editable):
    b, _ = capture(window, edited=True)
    other, _ = capture(window, "Other", edited=True)
    source = recent.editable_for(other) if editable else other
    before = source.read_bytes()
    if alias == "direct":
        target = source
    elif alias == "folder-alias":
        folder = tmp_path / "alias-folder"
        folder.symlink_to(source.parent, target_is_directory=True)
        target = folder / source.name
    else:
        target = tmp_path / source.name
        if alias == "symlink":
            target.symlink_to(source)
        else:
            target.hardlink_to(source)
    calls = []
    kind = 6 if editable else 0
    def dialog(*args, **kwargs):
        calls.append(args)
        return (str(target), mainwindow.SAVE_TYPES[kind][0]) if len(calls) == 1 else ("", "")
    monkeypatch.setattr(mainwindow.QFileDialog, "getSaveFileName", dialog)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: pytest.fail("replacement offered for Recent"))
    save(window, b)
    assert source.read_bytes() == before
    sentence = ("Recent is where Annotshot keeps captures, and it removes older ones. "
                "Choose another folder for this copy." if alias != "hardlink"
                else "That file belongs to Recent. Choose another name or folder.")
    assert any(sentence in t
               for t in window.save_warnings)
    assert len(calls) == 2 and calls[1][2] == str(target)
    assert remembered(window) == (None, None)


@pytest.mark.parametrize("failure", ["corrupt", "vanished", "write"])
def test_r22_failure_names_reason_no_raw_fallback_no_success(
        window, monkeypatch, tmp_path, failure):
    b, _ = capture(window)
    if failure == "corrupt":
        recent.editable_for(b).write_bytes(b"broken zip")
    elif failure == "vanished":
        b.unlink()
    out = tmp_path / "existing.png"
    out.write_bytes(b"original destination")
    before_doc = window.doc
    choose(monkeypatch, out)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
    if failure == "write":
        # Failure during image encoding, after a valid existing destination.
        monkeypatch.setattr(QImage, "save", lambda *a, **k: False)
    save(window, b)
    assert out.read_bytes() == b"original destination"
    assert window.doc is before_doc and window.save_warnings
    if failure == "corrupt":
        assert "Could not read this capture’s edits." in window.save_warnings[-1]
        assert recent.editable_for(b).name in window.save_warnings[-1]
    else:
        assert (b.name if failure == "vanished" else out.name) in window.save_warnings[-1]
    assert not window.statusBar().currentMessage().startswith("Saved ")
    assert remembered(window) == (None, None)


@pytest.mark.parametrize("decline", [False, True])
def test_r23_cancel_or_decline_changes_nothing(window, monkeypatch, tmp_path, decline):
    b, _ = capture(window)
    window.settings.setValue("last_dir/save", str(tmp_path))
    window.settings.setValue("last_filter/save", mainwindow.SAVE_TYPES[1][0])
    previous = remembered(window)
    out = tmp_path / "untouched.png"
    out.write_bytes(b"original")
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.No)
    choose(monkeypatch, tmp_path / "untouched.jpg" if decline else None)
    save(window, b)
    assert out.read_bytes() == b"original"
    assert remembered(window) == previous


@pytest.mark.parametrize("kind", range(7))
def test_r48_both_routes_share_last_folder_and_type_across_restart(
        window, monkeypatch, tmp_path, kind):
    b, _ = capture(window, edited=True)
    folder = tmp_path / "chosen"
    folder.mkdir()
    ext = mainwindow.SAVE_TYPES[kind][1][0]
    choose(monkeypatch, folder / "first", kind)
    # Editor's successful dialog write sets the shared destination.
    window.doc.path = str(tmp_path / "original.annotshot")
    assert window.save_as()
    window.settings.sync()
    second = mainwindow.MainWindow()
    try:
        second.doc.path = str(b.with_name("editor-source.annotshot"))
        calls = choose(monkeypatch, None)
        assert not second.save_as()
        assert Path(calls[0][0][2]) == folder / f"editor-source.{ext}"
        save(second, b)
        assert Path(calls[1][0][2]) == folder / f"B.{ext}"
        assert all(c[0][4] == mainwindow.SAVE_TYPES[kind][0] for c in calls)
    finally:
        second._autosave_timer.stop()
        second.deleteLater()


def test_r49_open_autosave_plain_save_copy_do_not_move_save_folder(window, monkeypatch, tmp_path):
    a = tmp_path / "A"
    a.mkdir()
    b, doc = capture(window, edited=True)
    window.settings.setValue("last_dir/save", str(a))
    window.settings.setValue("last_filter/save", mainwindow.SAVE_TYPES[0][0])
    assert window.open_path(str(recent.editable_for(b)))
    assert Path(window.settings.value("last_dir/project")) == b.parent
    mark = window.doc.annotation_items()[0]
    window.doc.set_props([mark], {"border_width": 11})
    window.autosave_now()
    window.copy_image()
    calls = choose(monkeypatch, None)
    QApplication.sendEvent(window.a_save, QShortcutEvent(QKeySequence("Ctrl+S"), 0))
    assert not calls
    assert Document.load(recent.editable_for(b)).annotation_items()[0].props["stroke_width"] == 11
    assert remembered(window)[0] == str(a)
    assert not window.save_as()
    assert Path(calls[0][0][2]).parent == a


@pytest.mark.parametrize("case", ["fresh", "vanished", "unreadable", "default-bad", "both-bad", "store"])
def test_r50_usable_fallback_order_without_recreating_remembered(
        window, monkeypatch, tmp_path, case):
    b, _ = capture(window)
    missing = tmp_path / "vanished"
    default = tmp_path / "default"
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(mainwindow.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(mainwindow, "DEFAULT_DIR", default)
    if case != "fresh":
        window.settings.setValue("last_dir/save", str(missing))
    if case == "unreadable":
        missing.mkdir()
        real_access = mainwindow.os.access
        monkeypatch.setattr(mainwindow.os, "access", lambda p, m: False if Path(p) == missing else real_access(p, m))
    if case in ("default-bad", "both-bad"):
        default.write_bytes(b"not a directory")
    if case == "both-bad":
        home.rmdir()
    if case == "store":
        monkeypatch.setattr(mainwindow, "is_packaged", lambda: True)
        monkeypatch.setattr(mainwindow, "app_data_directory", lambda: tmp_path / "appdata")
        default = tmp_path / "appdata" / "Captures"
    calls = choose(monkeypatch, None)
    assert not window.save_as()
    if case == "both-bad":
        assert not calls and window.save_warnings
    else:
        assert len(calls) == 1
        assert Path(calls[0][0][2]).parent == (home if case == "default-bad" else default)
    assert not missing.exists() or case == "unreadable"


def test_r51_recent_success_remembers_pair_failure_cancel_refusal_preserve_it(
        window, monkeypatch, tmp_path):
    b, _ = capture(window, edited=True)
    folder = tmp_path / "destination"
    folder.mkdir()
    choose(monkeypatch, folder / "saved", 5)
    save(window, b)
    previous = (str(folder), mainwindow.SAVE_TYPES[5][0])
    assert remembered(window) == previous
    calls = choose(monkeypatch, None)
    assert not window.save_as()
    assert Path(calls[0][0][2]).parent == folder and calls[0][0][4] == previous[1]
    save(window, b)
    assert remembered(window) == previous
    choose(monkeypatch, tmp_path / "absent" / "failed.png")
    save(window, b)
    assert remembered(window) == previous
    choose(monkeypatch, recent.png_for(b))
    # The refused native picker is offered for correction; cancel it next.
    answers = [(str(b), mainwindow.SAVE_TYPES[0][0]), ("", "")]
    monkeypatch.setattr(mainwindow.QFileDialog, "getSaveFileName", lambda *a, **k: answers.pop(0))
    save(window, b)
    assert remembered(window) == previous


def test_r19_pending_other_write_failure_is_reported(window, monkeypatch, tmp_path):
    from annotshot import scene
    b, doc = capture(window, edited=True)
    window._bind(doc)
    doc.set_props(doc.annotation_items(), {"border_width": 19})
    def fail(*args):
        raise OSError("disk full during queued write")
    monkeypatch.setattr(scene, "write_project", fail)
    window.autosave_now()
    window._bind(Document())
    calls = choose(monkeypatch, tmp_path / "must-not-exist.png")
    save(window, b)
    assert not calls and not (tmp_path / "must-not-exist.png").exists()
    assert any("disk full during queued write" in w and b.stem in w
               for w in window.save_warnings)


@pytest.mark.parametrize("route", ["thumbnail", "editor"])
@pytest.mark.parametrize("folder_kind", ["direct", "alias", "subfolder", "outward-link"])
def test_r21_new_filename_in_recent_is_refused(
        window, monkeypatch, tmp_path, route, folder_kind):
    b, _ = capture(window)
    folder = b.parent
    if folder_kind == "alias":
        folder = tmp_path / "recent-alias"
        folder.symlink_to(b.parent, target_is_directory=True)
    elif folder_kind == "subfolder":
        folder = b.parent / "my-copies"
        folder.mkdir()
    out = folder / "chosen-new-name.annotshot"
    outside = tmp_path / "outside.annotshot"
    if folder_kind == "outward-link":
        # The entry sits in Recent and names a file elsewhere. The writer
        # would replace the entry itself, leaving the copy inside Recent.
        outside.write_bytes(b"MINE")
        out.symlink_to(outside)
    calls = correcting_picker(monkeypatch, out, 6)
    if route == "thumbnail":
        save(window, b)
    else:
        assert not window.save_as()
    if folder_kind == "outward-link":
        assert out.is_symlink() and outside.read_bytes() == b"MINE"
    else:
        assert not out.exists()
    assert window.save_warnings == [
        "Recent is where Annotshot keeps captures, and it removes older ones. "
        "Choose another folder for this copy."]
    assert_reoffered(calls, out, 6)
    assert remembered(window) == (None, None)


def test_r22_picture_commit_failure_keeps_destination(window, monkeypatch, tmp_path):
    b, _ = capture(window)
    out = tmp_path / "keep.png"
    out.write_bytes(b"original")
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
    def fail(*args):
        raise PermissionError("replacement refused")
    monkeypatch.setattr(mainwindow.os, "replace", fail)
    choose(monkeypatch, out)
    save(window, b)
    assert out.read_bytes() == b"original"
    assert not list(tmp_path.glob(".keep.png.*.tmp"))
    assert any("replacement refused" in w and "keep.png" in w for w in window.save_warnings)
    assert remembered(window) == (None, None)


def correcting_picker(monkeypatch, target, kind):
    """Reject once, then cancel without leaving a native dialog waiting."""
    calls = []
    def dialog(*args, **kwargs):
        calls.append((args, kwargs))
        return (str(target), mainwindow.SAVE_TYPES[kind][0]) if len(calls) == 1 else ("", "")
    monkeypatch.setattr(mainwindow.QFileDialog, "getSaveFileName", dialog)
    return calls


def assert_reoffered(calls, target, kind):
    assert len(calls) == 2
    assert calls[1][0][2] == str(target)
    assert calls[1][0][4] == mainwindow.SAVE_TYPES[kind][0]


@pytest.mark.parametrize("alias", ["direct", "symlink", "hardlink", "folder-alias"])
@pytest.mark.parametrize("companion", [False, True])
def test_f1_open_file_and_pair_refused_without_changing_a(
        window, monkeypatch, tmp_path, alias, companion):
    b, _ = capture(window)
    a = Document(QImage(200, 100, QImage.Format_ARGB32))
    bound = tmp_path / "A.annotshot"
    a.save(bound)
    png = bound.with_suffix(".png")
    assert a.base.save(str(png), "PNG")
    mark = RectItem()
    mark.set_geom((5, 5, 40, 30))
    a.add_items([mark])
    a.select_only([mark])
    window._bind(a)
    window._autosave_timer.stop()
    source = png if companion else bound
    before_bytes = (bound.read_bytes(), png.read_bytes())
    stack = a.undo_stack
    before = (a.path, a.to_dict(), a.selected(), stack.index(), stack.count(),
              stack.isClean(), stack.needs_save(), a.changes, a.written,
              window.isWindowModified())
    target = source
    if alias == "folder-alias":
        folder = tmp_path / "a-folder-alias"
        folder.symlink_to(tmp_path, target_is_directory=True)
        target = folder / source.name
    elif alias != "direct":
        target = tmp_path / ("alias" + source.suffix)
        if alias == "symlink":
            target.symlink_to(source)
        else:
            target.hardlink_to(source)
    kind = 0 if companion else 6
    calls = correcting_picker(monkeypatch, target, kind)
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a: asked.append(a) or QMessageBox.Yes)
    save(window, b)
    assert not asked
    assert before_bytes == (bound.read_bytes(), png.read_bytes())
    assert window.doc is a and window.undo_group.activeStack() is stack
    assert before == (a.path, a.to_dict(), a.selected(), stack.index(), stack.count(),
                      stack.isClean(), stack.needs_save(), a.changes, a.written,
                      window.isWindowModified())
    assert window.save_warnings == [
        "That file belongs to Recent. Choose another name or folder."]
    assert_reoffered(calls, target, kind)
    assert remembered(window) == (None, None)


def test_f2_failed_editable_encode_has_no_receipt_or_folder_memory(
        window, monkeypatch, tmp_path):
    b, _ = capture(window)
    window.settings.setValue("last_dir/save", str(tmp_path))
    window.settings.setValue("last_filter/save", mainwindow.SAVE_TYPES[1][0])
    previous = remembered(window)
    out = tmp_path / "keep.annotshot"
    out.write_bytes(b"GOOD DESTINATION")
    choose(monkeypatch, out, 6)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
    monkeypatch.setattr(QImage, "save", lambda *a, **k: False)
    save(window, b)
    assert out.read_bytes() == b"GOOD DESTINATION"
    assert any(out.name in w and "encode" in w for w in window.save_warnings)
    assert not window.statusBar().currentMessage().startswith("Saved ")
    assert remembered(window) == previous


def test_f4_uppercase_kept_source_alias_is_protected(window, monkeypatch, tmp_path):
    b, _ = capture(window)
    source = b.with_name("Other.PNG")
    assert window.doc.base.save(str(source), "PNG")
    if source.with_suffix(".png").exists():
        pytest.skip("volume folds filename case")
    before = source.read_bytes()
    target = tmp_path / "outside.png"
    target.hardlink_to(source)
    calls = correcting_picker(monkeypatch, target, 0)
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a: asked.append(a) or QMessageBox.Yes)
    save(window, b)
    assert not asked
    assert source.read_bytes() == target.read_bytes() == before
    assert window.save_warnings == [
        "That file belongs to Recent. Choose another name or folder."]
    assert_reoffered(calls, target, 0)
    assert remembered(window) == (None, None)


def test_f4_listing_error_refuses_destination_and_reoffers(window, monkeypatch, tmp_path):
    b, _ = capture(window)
    target = tmp_path / "outside.png"
    original = Path.iterdir
    def fail_recent(path):
        if path == b.parent:
            raise PermissionError("Recent listing denied")
        return original(path)
    monkeypatch.setattr(Path, "iterdir", fail_recent)
    calls = correcting_picker(monkeypatch, target, 0)
    save(window, b)
    assert not target.exists()
    assert any(str(target) in w and "Recent listing denied" in w for w in window.save_warnings)
    assert_reoffered(calls, target, 0)
    assert remembered(window) == (None, None)


@pytest.mark.parametrize("route", ["thumbnail", "editor"])
def test_f6_dangling_destination_asks_once_and_decline_keeps_link(
        window, monkeypatch, tmp_path, route):
    b, _ = capture(window)
    missing = tmp_path / "missing.annotshot"
    target = tmp_path / "copy.annotshot"
    target.symlink_to(missing)
    calls = choose(monkeypatch, target, 6)
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a: asked.append(a) or QMessageBox.No)
    if route == "thumbnail":
        save(window, b)
    else:
        assert not window.save_as()
    assert len(calls) == len(asked) == 1
    assert asked[0][4] == QMessageBox.No
    assert target.is_symlink() and target.readlink() == missing
    assert not missing.exists()
    assert not window.statusBar().currentMessage().startswith("Saved ")
    assert remembered(window) == (None, None)
