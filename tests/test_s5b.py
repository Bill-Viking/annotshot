"""Fix round 2 (s5b): captures keep themselves. Every Recent capture is a
pair (the original PNG and its editable `.annotshot`), every edit is written
by the autosave on the writer thread, the pane shows each capture WITH its
edits, and a relaunch opens the last capture again. Offscreen; every file a
test writes is under its own tmp folder."""
import os
import sys
from pathlib import Path

import pytest

from test_s3b2 import at, picture, settle, window  # noqa: F401 - fixtures


def wait_written(qapp, ms=900, path=None, deadline_ms=10_000):
    """The debounce runs out, the writer lands, its signal is handled.
    A slow runner (GitHub's Windows and Linux boxes) can take longer than
    the debounce to fire the timer, so when `path` is given the loop is
    pumped until that file exists, up to `deadline_ms`; the fixed wait is
    only the floor."""
    from PySide6.QtCore import QDeadlineTimer
    from PySide6.QtTest import QTest
    from annotshot import recent
    from annotshot.mainwindow import MainWindow
    QTest.qWait(ms)
    left = QDeadlineTimer(deadline_ms)
    windows = [w for w in qapp.topLevelWidgets() if isinstance(w, MainWindow)]
    while not left.hasExpired():
        pending = any(w._autosave_timer.isActive() for w in windows)
        if not pending and (path is None or path.exists()):
            break
        QTest.qWait(50)
    recent.writer().waitForDone()
    settle(qapp)


def captured(window, qapp, color="#3366CC"):
    """A capture through the real road; returns its PNG path."""
    from annotshot import recent
    from annotshot.capture import CaptureResult
    window._capture_done(CaptureResult(picture(color=color)))
    settle(qapp)
    return recent.png_for(window.doc.path)


# -- item 1: every Recent capture is an editable record ------------------------
def test_a_capture_knows_its_editable_beside_its_png(window, qapp, private_pictures):
    png = captured(window, qapp)
    assert png.is_file() and png.parent == private_pictures / "Recent"
    assert window.doc.path == str(png.with_suffix(".annotshot"))
    assert not png.with_suffix(".annotshot").exists()   # unedited: no file yet
    assert window.windowTitle() == f"Annotshot — {png.stem}[*]"
    window.hide()


def test_delete_removes_both_files_and_lets_go_of_the_open_one(window, qapp, private_pictures):
    from annotshot.scene import Document
    store = window.recent_store
    old = store.file(picture(color="#FF0000"), at(minutes_ago=5))
    new = store.file(picture(color="#00FF00"), at())
    Document(picture(color="#FF0000")).save(str(old.with_suffix(".annotshot")))
    window.recent.refresh()
    assert window.open_recent(str(old))
    window.recent.delete(str(old))
    assert not old.exists() and not old.with_suffix(".annotshot").exists()
    assert window.recent.paths() == [str(new)]
    assert window.doc.path is None                  # the window let go of it


def test_clear_clears_both_files(window, qapp, private_pictures, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from annotshot import recent
    from annotshot.scene import Document
    store = window.recent_store
    a = store.file(picture(), at(minutes_ago=5))
    Document(picture()).save(str(a.with_suffix(".annotshot")))
    monkeypatch.setattr(recent.QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    window.recent.refresh()
    assert window.recent.clear()
    assert list((private_pictures / "Recent").iterdir()) == []


def test_prune_keeps_an_edited_capture_beyond_twelve(tmp_path):
    from annotshot.recent import RecentStore
    from annotshot.scene import Document
    store = RecentStore(lambda: tmp_path)
    made = [store.file(picture(), at(minutes_ago=100 - i)) for i in range(12)]
    edited = made[0].with_suffix(".annotshot")
    Document(picture()).save(str(edited))           # the oldest has work
    store.file(picture(), at())                     # the 13th arrives
    store.file(picture(), at(minutes_ago=-1))       # and the 14th
    assert made[0].exists() and edited.exists()     # work is never pruned
    assert not made[1].exists()                     # an unedited one went
    assert made[2].exists() and len(store.files()) == 13


def test_an_editable_whose_png_is_gone_still_lists_and_opens(window, qapp, private_pictures):
    from annotshot.items import RectItem
    from annotshot.scene import Document
    store = window.recent_store
    png = store.file(picture(color="#00FF00"), at(minutes_ago=3))
    doc = Document(picture(color="#00FF00"))
    r = RectItem()
    r.set_geom((10, 10, 50, 40))
    doc.add_items([r])
    doc.save(str(png.with_suffix(".annotshot")))
    png.unlink()
    window.recent.refresh()
    assert window.recent.paths() == [str(png.with_suffix(".annotshot"))]
    assert window.recent.list.item(0).text()        # shown by its stamp
    assert window.open_recent(window.recent.paths()[0])
    assert len(window.doc.annotation_items()) == 1
    assert window.doc.path == str(png.with_suffix(".annotshot"))


def test_open_recent_opens_the_editable_when_there_is_one(window, qapp, private_pictures):
    from annotshot.items import RectItem
    from annotshot.scene import Document
    png = window.recent_store.file(picture(), at())
    doc = Document(picture())
    r = RectItem()
    r.set_geom((10, 10, 50, 40))
    doc.add_items([r])
    doc.save(str(png.with_suffix(".annotshot")))
    window.recent.refresh()
    assert window.open_recent(str(png))
    assert len(window.doc.annotation_items()) == 1


# -- item 2: autosave ----------------------------------------------------------
def draw(window, x=20, color=None):
    from annotshot.items import RectItem
    r = RectItem()
    r.set_geom((x, 20, 120, 80))
    window.doc.add_items([r])
    return r


def no_question(monkeypatch):
    from annotshot import mainwindow
    monkeypatch.setattr(mainwindow.QMessageBox, "question", staticmethod(
        lambda *a, **k: pytest.fail("the save question was asked")))


def test_a_shape_on_a_capture_is_written_within_the_debounce(window, qapp, private_pictures):
    from annotshot.scene import Document
    png = captured(window, qapp)
    editable = png.with_suffix(".annotshot")
    draw(window)
    assert not editable.exists()                    # not on the UI thread
    wait_written(qapp, path=editable)
    assert editable.is_file() and png.is_file()
    assert len(Document.load(editable).annotation_items()) == 1
    assert window.doc.undo_stack.isClean()          # the write made it clean
    assert not window.doc.undo_stack.needs_save()
    assert not window.isWindowModified()            # no * churn
    assert window.statusBar().currentMessage() == "" or \
        window.statusBar().currentMessage().startswith("Captured")
    window.hide()


def test_switching_captures_never_asks_and_keeps_the_edit(window, qapp, private_pictures, monkeypatch):
    from annotshot.scene import Document
    no_question(monkeypatch)
    store = window.recent_store
    a = store.file(picture(color="#FF0000"), at(minutes_ago=5))
    b = store.file(picture(color="#00FF00"), at())
    window.recent.refresh()
    assert window.open_recent(str(a))
    draw(window)                                    # no wait: still pending
    assert window.open_recent(str(b))               # no question box
    from annotshot import recent
    recent.writer().waitForDone()
    assert len(Document.load(a.with_suffix(".annotshot")).annotation_items()) == 1
    assert window.open_recent(str(a))               # back again, with it
    assert len(window.doc.annotation_items()) == 1
    assert window.doc.base.pixelColor(200, 150).name().upper() == "#FF0000"


def test_capture_clear_and_close_keep_the_edit_without_asking(window, qapp, private_pictures, monkeypatch):
    from annotshot.scene import Document
    from annotshot import recent
    no_question(monkeypatch)
    png = captured(window, qapp)
    draw(window)
    window.clear_picture()                          # Clear: no question
    recent.writer().waitForDone()
    assert len(Document.load(png.with_suffix(".annotshot")).annotation_items()) == 1
    png2 = captured(window, qapp)
    draw(window)
    draw(window, x=200)
    window.close()                                  # close: written first
    assert len(Document.load(png2.with_suffix(".annotshot")).annotation_items()) == 2


def test_typing_is_not_interrupted_by_the_timer(window, qapp, private_pictures):
    """The timer finds a text box being typed in: it leaves it alone; the
    edit is written when it ends."""
    from annotshot.items import TextBoxItem
    from annotshot.scene import Document
    png = captured(window, qapp)
    t = TextBoxItem()
    t.set_geom((10, 10, 200, 60))
    window.doc.add_items([t])
    t.start_edit()
    assert window.doc.is_editing()
    t.editor.setPlainText("hello")
    wait_written(qapp)
    assert window.doc.is_editing()                  # still typing
    window.doc.end_text_edit()
    wait_written(qapp)
    (back,) = Document.load(png.with_suffix(".annotshot")).annotation_items()
    assert back.props["text"] == "hello"
    window.hide()


def test_a_failed_write_is_one_status_sentence_and_never_raises(window, qapp, private_pictures):
    import shutil
    png = captured(window, qapp)
    folder = png.parent
    if sys.platform == "win32":                     # a read-only folder still
        shutil.rmtree(folder)                       # takes files on Windows:
        folder.write_text("a file where the folder goes")   # no folder at all
    else:
        os.chmod(folder, 0o555)                     # the folder made read-only
    try:
        draw(window)
        wait_written(qapp)                          # never raises
        msg = window.statusBar().currentMessage()
        assert msg.startswith("Could not keep your changes to this picture: ")
        assert "\n" not in msg
        assert window.doc.needs_write()             # tried again on the next change
    finally:
        if sys.platform != "win32":
            os.chmod(folder, 0o755)
    draw(window, x=200)                             # the folder is back
    if sys.platform != "win32":
        wait_written(qapp)
        assert png.with_suffix(".annotshot").is_file()
    window.hide()


def test_without_keep_recent_the_question_survives(window, qapp, private_pictures, monkeypatch):
    """The one place the save question is left: a capture with no file at
    all (Keep recent off). Asked once per double-click on the pane."""
    from annotshot import mainwindow
    from annotshot.capture import CaptureResult
    from annotshot.recent import SETTING
    store = window.recent_store
    kept = store.file(picture(color="#FF0000"), at(minutes_ago=5))
    window.recent.refresh()
    window.settings.setValue(SETTING, False)
    window._capture_done(CaptureResult(picture()))
    settle(qapp)
    assert window.doc.path is None
    draw(window)
    asked = []
    monkeypatch.setattr(mainwindow.QMessageBox, "question", staticmethod(
        lambda *a, **k: asked.append(a[2]) or mainwindow.QMessageBox.Cancel))
    before = window.doc
    item = window.recent.list.item(0)
    window.recent._clicked(item)
    window.recent._double_clicked(item)             # the same double-click
    assert asked == ["Save your changes to this project first?"]
    assert window.doc is before                     # Cancel kept it
    assert window.isWindowModified()
    window.hide()


# -- item 3: the pane shows each capture WITH its edits, live ------------------
def test_the_thumbnail_shows_the_edit_and_matches_a_fresh_render(window, qapp, private_pictures, tmp_path):
    import shutil
    from annotshot import recent
    png = captured(window, qapp, color="#FFFFFF")
    pane = window.recent
    dpr = max(1.0, pane.devicePixelRatioF())
    plain = tmp_path / "plain.png"                  # the PNG alone, no editable
    shutil.copy(png, plain)
    before = recent.thumbnail(plain, recent.THUMB, dpr).toImage()
    calls = []
    real = pane.refresh

    def counted():
        calls.append(1)
        real()
    pane.refresh = counted
    r = draw(window)
    window.doc.set_props([r], {"border_width": 12})
    wait_written(qapp)
    assert calls == []                              # one item, not the list
    key = recent._thumb_key(png)
    shown = pane._thumbs[key].toImage()
    assert shown != before                          # the shape is on it
    fresh = recent.thumbnail(png, recent.THUMB, dpr).toImage()
    assert shown == fresh                           # a fresh offscreen render
    icon = pane.list.item(0).icon().pixmap(recent.THUMB).toImage()
    assert icon.convertToFormat(fresh.format()).size() == fresh.size()
    window.hide()


def test_a_refresh_draws_an_unchanged_capture_from_its_cache(window, qapp, private_pictures, monkeypatch):
    from annotshot import recent
    png = captured(window, qapp)
    draw(window)
    wait_written(qapp)
    drawn = []
    monkeypatch.setattr(recent, "thumbnail",
                        lambda *a, **k: drawn.append(a[0]) or pytest.fail("redrawn"))
    window.recent.refresh()                         # nothing changed on disk
    assert drawn == [] and window.recent.paths() == [str(png)]
    window.hide()


# -- item 4: the app comes back where it was -----------------------------------
def test_a_relaunch_opens_the_last_capture_with_its_edits(window, qapp, private_pictures, monkeypatch):
    from annotshot.mainwindow import CURRENT_KEY, MainWindow
    no_question(monkeypatch)
    png = captured(window, qapp)
    draw(window)
    window.close()
    assert window.settings.value(CURRENT_KEY) == str(png.with_suffix(".annotshot"))
    again = MainWindow()                            # the same settings
    assert again.doc.path == str(png.with_suffix(".annotshot"))
    assert len(again.doc.annotation_items()) == 1
    assert again.windowTitle() == f"Annotshot — {png.stem}[*]"
    again.deleteLater()


def test_a_relaunch_with_the_capture_gone_starts_empty(window, qapp, private_pictures):
    from annotshot.mainwindow import MainWindow
    png = captured(window, qapp)
    window.close()
    png.unlink()
    again = MainWindow()
    assert again.doc.path is None and again.doc.is_placeholder
    again.deleteLater()


def test_an_opened_file_keeps_itself_and_comes_back(window, qapp, tmp_path, monkeypatch):
    from annotshot.mainwindow import MainWindow
    from annotshot.scene import Document
    no_question(monkeypatch)
    mine = tmp_path / "mine.annotshot"
    Document(picture()).save(str(mine))
    assert window.open_path(str(mine), ask=False)
    draw(window)
    wait_written(qapp)                              # written into THAT file
    assert len(Document.load(mine).annotation_items()) == 1
    assert window.windowTitle() == "Annotshot — mine.annotshot[*]"
    assert not window.isWindowModified()
    window.close()
    again = MainWindow()
    assert again.doc.path == str(mine)
    again.deleteLater()


def test_save_as_editable_is_a_copy_and_the_capture_keeps_itself(window, qapp, private_pictures, tmp_path, monkeypatch):
    from annotshot import mainwindow
    from annotshot.scene import Document
    png = captured(window, qapp)
    draw(window)
    copy = tmp_path / "copy.annotshot"
    monkeypatch.setattr(mainwindow.QFileDialog, "getSaveFileName", staticmethod(
        lambda *a, **k: (str(copy), mainwindow.PROJECT_FILTER)))
    assert window.save_as()
    assert len(Document.load(copy).annotation_items()) == 1
    assert window.doc.path == str(png.with_suffix(".annotshot"))   # still Recent's
    draw(window, x=200)
    wait_written(qapp)
    assert len(Document.load(png.with_suffix(".annotshot")).annotation_items()) == 2
    assert len(Document.load(copy).annotation_items()) == 1        # the copy stays
    window.hide()
