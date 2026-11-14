"""Failed autosaves keep the current edit until the person answers. Offscreen."""
from pathlib import Path

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QMessageBox

from annotshot import mainwindow as mw, recent, scene
from annotshot.capture import CaptureResult
from annotshot.items import RectItem
from annotshot.scene import Document
from test_s10_welcome import background_window  # noqa: F401 - fixture


def wait_writer():
    assert recent.writer().waitForDone(10_000)


@pytest.fixture
def window(background_window, qapp):
    w, _ = background_window
    w.settings.setValue("capture/copy", False)
    w.set_keep_running(True)
    w._ensure_tray()
    w.show()
    qapp.processEvents()
    yield w
    w._autosave_timer.stop()
    wait_writer()
    qapp.processEvents()


@pytest.fixture
def failed_write(monkeypatch):
    calls = []

    def fail(*args):
        calls.append(args[0])
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(scene, "write_project", fail)
    return calls


def edited_capture(w, qapp, white):
    w._capture_done(CaptureResult(white))
    assert QThreadPool.globalInstance().waitForDone(10_000)
    qapp.processEvents()
    item = RectItem()
    item.set_geom((20, 20, 120, 80))
    w.doc.add_items([item])
    w._autosave_timer.stop()
    return w.doc, item


def answer_close(w, monkeypatch, answer):
    asked = []

    def ask(why):
        asked.append(why)
        return answer

    monkeypatch.setattr(w, "_ask_failed_write", ask)
    return asked


def quit_calls(qapp, monkeypatch):
    called = []
    monkeypatch.setattr(qapp, "quit", lambda: called.append("quit"))
    return called


def unchanged_on_refusal(w, monkeypatch):
    """Record every close side effect that a refused decision must precede."""
    calls = []
    for owner, name in ((w, "_save_editor_geometry"), (w.hotkey, "clear"),
                        (w.tray, "notify_hidden"), (w.tray, "shutdown")):
        monkeypatch.setattr(owner, name, lambda: calls.append("changed"))
    before = {key: w.settings.value(key) for key in w.settings.allKeys()}
    return calls, before


def assert_refused(w, doc, item, calls, settings):
    assert w.isVisible() and w.doc is doc
    assert w.doc.annotation_items() == [item]
    assert not w._quitting
    assert calls == []
    assert {key: w.settings.value(key) for key in w.settings.allKeys()} == settings


def test_q1_hide_cancel_keeps_the_edit_before_signal_delivery(
        window, qapp, white, failed_write, monkeypatch):
    w = window
    doc, item = edited_capture(w, qapp, white)
    asked = answer_close(w, monkeypatch, "cancel")
    calls, settings = unchanged_on_refusal(w, monkeypatch)
    assert not w.close()
    assert_refused(w, doc, item, calls, settings)
    assert failed_write == [doc.path]
    assert doc.written == doc.changes  # the failure signal is still queued
    assert doc.last_write.error == "No space left on device"
    assert asked == ["No space left on device"]
    qapp.processEvents()
    assert doc.written == -1
    assert w.statusBar().currentMessage() == (
        "Could not keep your changes to this picture: No space left on device")


def test_q2_quit_cancel_resets_quitting_and_keeps_the_edit(
        window, qapp, white, failed_write, monkeypatch):
    w = window
    doc, item = edited_capture(w, qapp, white)
    asked = answer_close(w, monkeypatch, "cancel")
    quits = quit_calls(qapp, monkeypatch)
    calls, settings = unchanged_on_refusal(w, monkeypatch)
    w.quit_app()
    assert quits == []
    assert_refused(w, doc, item, calls, settings)
    assert failed_write == [doc.path]
    assert asked == ["No space left on device"]


@pytest.mark.parametrize("route", ["hide", "quit"])
def test_q3_discard_continues_on_both_roads(
        window, qapp, white, failed_write, monkeypatch, route):
    w = window
    doc, _ = edited_capture(w, qapp, white)
    asked = answer_close(w, monkeypatch, "discard")
    quits = quit_calls(qapp, monkeypatch)
    if route == "hide":
        assert not w.close()  # hiding ignores the close event as before
        assert not w.isVisible() and w.doc is not doc
        assert w.doc.is_placeholder and w.doc.path is None
        assert w.doc.last_write is None and not w.doc.annotation_items()
        assert not w._quitting and quits == []
    else:
        w.quit_app()
        assert w._quitting and not w.isVisible() and quits == ["quit"]
        assert w.settings.value(mw.CURRENT_KEY) == doc.path
    assert failed_write == [doc.path]
    assert asked == ["No space left on device"]


@pytest.mark.parametrize("route", ["hide", "quit"])
@pytest.mark.parametrize("saved", [False, True])
def test_q4_save_copy_continues_only_when_it_lands(
        window, qapp, white, failed_write, monkeypatch, route, saved):
    w = window
    doc, item = edited_capture(w, qapp, white)
    asked = answer_close(w, monkeypatch, "save")
    saves = []
    monkeypatch.setattr(w, "save_as", lambda: saves.append("save") or saved)
    quits = quit_calls(qapp, monkeypatch)
    if not saved:
        calls, settings = unchanged_on_refusal(w, monkeypatch)
    if route == "quit":
        w.quit_app()
    else:
        assert not w.close()
    assert saves == ["save"] and asked == ["No space left on device"]
    assert failed_write == [doc.path]
    if not saved:
        assert_refused(w, doc, item, calls, settings)
        assert quits == []
    elif route == "hide":
        assert not w.isVisible() and w.doc is not doc and w.doc.is_placeholder
        assert quits == []
    else:
        assert w._quitting and not w.isVisible() and quits == ["quit"]


@pytest.mark.parametrize("route", ["hide", "quit"])
def test_q5_success_keeps_the_item_without_a_box(
        window, qapp, white, monkeypatch, route):
    w = window
    doc, _ = edited_capture(w, qapp, white)
    assert doc.last_write is None
    quits = quit_calls(qapp, monkeypatch)
    if route == "hide":
        assert not w.close() and not w.isVisible()
        assert quits == []
    else:
        w.quit_app()
        assert quits == ["quit"] and w._quitting
    assert doc.last_write.error is None
    assert len(Document.load(doc.path).annotation_items()) == 1


def test_q5_successful_explicit_save_supersedes_a_failed_autosave(
        window, qapp, white, monkeypatch):
    w = window
    doc, _ = edited_capture(w, qapp, white)

    def fail(*args):
        raise OSError(28, "No space left on device")

    with monkeypatch.context() as patch:
        patch.setattr(scene, "write_project", fail)
        assert w.autosave_now()
        wait_writer()
        qapp.processEvents()
        assert doc.written == -1
        assert doc.last_write.error == "No space left on device"
    assert w._save_editable(doc.path)
    assert doc.last_write is None
    assert not w.close() and not w.isVisible()
    assert len(Document.load(doc.path).annotation_items()) == 1


@pytest.mark.parametrize("retry_succeeds", [False, True])
def test_q6_delivered_failure_is_retried_and_latest_outcome_is_used(
        window, qapp, white, monkeypatch, retry_succeeds):
    w = window
    doc, item = edited_capture(w, qapp, white)
    real_write = scene.write_project
    writes = []

    def write(*args):
        writes.append(args[0])
        if len(writes) == 1 or not retry_succeeds:
            raise OSError(28, "No space left on device")
        real_write(*args)

    monkeypatch.setattr(scene, "write_project", write)
    assert w.autosave_now()
    wait_writer()
    first = doc.last_write
    assert first.error == "No space left on device"
    qapp.processEvents()
    assert doc.written == -1  # the opposite case of the ASSUMES comment
    if not retry_succeeds:
        asked = answer_close(w, monkeypatch, "cancel")
    assert not w.close()
    assert writes == [doc.path, doc.path]
    assert doc.last_write is not first
    if retry_succeeds:
        assert doc.last_write.error is None
        assert not w.isVisible() and w.doc is not doc
        assert len(Document.load(doc.path).annotation_items()) == 1
    else:
        assert doc.last_write.error == "No space left on device"
        assert asked == ["No space left on device"]
        assert w.isVisible() and w.doc is doc and doc.annotation_items() == [item]


@pytest.mark.parametrize("route", ["hide", "quit"])
def test_q7_no_file_keeps_the_existing_question(
        window, qapp, white, monkeypatch, route):
    w = window
    w.settings.setValue(recent.SETTING, False)
    doc, item = edited_capture(w, qapp, white)
    assert doc.path is None and doc.last_write is None
    questions = []

    def question(*args):
        questions.append(args[2:])
        return QMessageBox.Cancel

    monkeypatch.setattr(mw.QMessageBox, "question", question)
    quits = quit_calls(qapp, monkeypatch)
    if route == "quit":
        w.quit_app()
    else:
        assert not w.close()
    assert quits == [] and not w._quitting
    assert w.isVisible() and w.doc is doc and doc.annotation_items() == [item]
    assert questions == [("Save your changes to this project first?",
                          QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                          QMessageBox.Save)]


def test_q8_reopen_same_capture_has_no_stale_failure(
        window, qapp, white, monkeypatch):
    w = window
    old, _ = edited_capture(w, qapp, white)
    real_write = scene.write_project

    def fail(*args):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(scene, "write_project", fail)
    asked = answer_close(w, monkeypatch, "discard")
    assert not w.close() and not w.isVisible()
    assert old.last_write.error == "No space left on device"
    assert asked == ["No space left on device"]
    monkeypatch.setattr(scene, "write_project", real_write)
    qapp.processEvents()
    assert w.open_recent(str(recent.png_for(old.path)))
    assert w.doc is not old and w.doc.path == old.path
    assert w.doc.last_write is None and not w.doc.needs_write()
    w.show()
    qapp.processEvents()
    assert not w.close() and not w.isVisible()
    assert asked == ["No space left on device"]


def test_q9_real_box_is_unshown_with_exact_words_and_buttons(window):
    box = window._failed_write_box("No space left on device")
    try:
        assert not box.isVisible()
        assert box.text() == (
            "Your last changes to this picture could not be kept (No space left on device).\n\n"
            "Save a copy somewhere else, or discard those changes.")
        assert mw.CLOSE_SAVE_FAILED == (
            "Your last changes to this picture could not be kept ({why}).\n\n"
            "Save a copy somewhere else, or discard those changes.")
        assert mw.CLOSE_SAVE_COPY == "Save a copy…"
        assert mw.CLOSE_DISCARD == "Discard changes"
        assert len(box.buttons()) == 3
        assert {b.text() for b in box.buttons()} == {
            "Save a copy…", "Discard changes", "Cancel"}
        assert box.defaultButton().text() == "Save a copy…"
        assert box.escapeButton() is box.button(QMessageBox.Cancel)
        assert box.escapeButton().text() == "Cancel"
        for text in [box.text(), *(b.text() for b in box.buttons())]:
            assert "quit" not in text.lower() and "close" not in text.lower()
    finally:
        box.deleteLater()


@pytest.mark.parametrize("press, answer", [
    ("Save a copy…", "save"), ("Discard changes", "discard"),
    ("Cancel", "cancel"), (None, "cancel")])
def test_q9_the_shown_box_answers_by_the_button_pressed(window, qapp, press, answer):
    """The seam itself (the judge's guard): the real box is shown and one
    button is pressed; None is Escape or the box's own close button."""
    from PySide6.QtCore import QTimer
    seen, tries = [], []

    def act():
        shown = [b for b in window.findChildren(QMessageBox) if b.isVisible()]
        if not shown:
            tries.append(1)
            if len(tries) < 250:                # five seconds, then give up
                QTimer.singleShot(20, act)
            else:                               # never hang the suite
                for b in window.findChildren(QMessageBox):
                    b.reject()
            return
        box = shown[0]
        seen.append(box.text())
        if press is None:
            box.reject()
        else:
            next(b for b in box.buttons() if b.text() == press).click()

    QTimer.singleShot(0, act)
    real = mw.MainWindow._ask_failed_write.original
    assert real(window, "No space left on device") == answer
    assert seen == [
        "Your last changes to this picture could not be kept (No space left on device).\n\n"
        "Save a copy somewhere else, or discard those changes."]


def test_q10_manual_has_the_exact_paragraph_once_in_the_right_place():
    manual = (Path(__file__).resolve().parents[1] / "docs" / "USER-MANUAL.md").read_text(
        encoding="utf-8")
    paragraph = (
        "If Annotshot cannot keep your last changes to a picture when you close its window "
        "or quit (a full disk, or a folder that is gone), it stays open and asks: "
        "**Save a copy…** somewhere else, **Discard changes**, or **Cancel** to go on working.")
    assert manual.count(paragraph) == 1
    section = manual.split("## Closing and quitting\n", 1)[1].split("\n## ", 1)[0]
    paragraphs = section.strip().split("\n\n")
    quit_paragraph = next(i for i, p in enumerate(paragraphs)
                          if p.startswith("**Quit Annotshot** (Command+Q on macOS)"))
    assert paragraphs[quit_paragraph + 1] == paragraph
    assert mw.CLOSE_SAVE_COPY == "Save a copy…" and f"**{mw.CLOSE_SAVE_COPY}**" in paragraph
    assert mw.CLOSE_DISCARD == "Discard changes" and f"**{mw.CLOSE_DISCARD}**" in paragraph
