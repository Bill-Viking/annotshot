"""The file type: the argument, Qt's FileOpen event and the Windows
registration (offscreen; the registry test runs only on Windows)."""
import os
import sys

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QFileOpenEvent
from PySide6.QtWidgets import QApplication

from annotshot import app as app_mod
from annotshot import filetype
from annotshot.items import RectItem
from annotshot.mainwindow import MainWindow
from annotshot.scene import Document

from test_items import add


@pytest.fixture
def window(qapp):
    app_mod.make_app()
    w = MainWindow()
    yield w
    w.deleteLater()


@pytest.fixture
def good_file(qapp, white, tmp_path):
    doc = Document(white)
    add(doc, RectItem, (10, 10, 50, 40))
    path = tmp_path / "shot.annotshot"
    doc.save(path)
    return str(path)


@pytest.fixture
def warnings_shown(monkeypatch):
    shown = []
    monkeypatch.setattr(MainWindow, "_warn", lambda self, text: shown.append(text))
    return shown


# -- open_path ------------------------------------------------------------------
def test_open_path_loads_a_good_file(window, good_file, warnings_shown):
    assert window.open_path(good_file) is True
    assert window.doc.path == good_file
    assert len(window.doc.annotation_items()) == 1
    assert warnings_shown == []


def test_open_path_warns_on_a_bad_file(window, tmp_path, warnings_shown):
    bad = tmp_path / "broken.annotshot"
    bad.write_bytes(b"not a zip")
    empty = window.doc
    assert window.open_path(str(bad)) is False
    assert len(warnings_shown) == 1 and "broken.annotshot" in warnings_shown[0]
    assert window.doc is empty                  # the window keeps its document


def test_open_path_keeps_an_unsaved_document_on_cancel(window, good_file,
                                                       white, monkeypatch):
    window._bind(Document(white))
    add(window.doc, RectItem, (5, 5, 20, 20))   # an unsaved change
    monkeypatch.setattr(MainWindow, "maybe_discard", lambda self: False)
    before = window.doc
    assert window.open_path(good_file) is False
    assert window.doc is before


# -- the command-line argument ----------------------------------------------------
def test_file_argument_picks_the_first_existing_editable_file(good_file, tmp_path):
    legacy = tmp_path / ("old" + filetype.EXTENSIONS[1].upper())
    legacy.write_bytes(b"x")
    missing = str(tmp_path / "gone.annotshot")
    assert app_mod.file_argument(["prog", "-x", missing, good_file]) == good_file
    assert app_mod.file_argument(["prog", str(legacy)]) == str(legacy)
    assert app_mod.file_argument(["prog", str(tmp_path / "a.png")]) is None
    assert app_mod.file_argument([good_file]) is None        # argv[0] is the program


def test_main_opens_the_file_argument(qapp, good_file, monkeypatch):
    opened, built = [], []
    monkeypatch.setattr(MainWindow, "show", lambda self: built.append(self))
    monkeypatch.setattr(MainWindow, "open_path",
                        lambda self, p, ask=True: opened.append(p) or True)
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    monkeypatch.setattr(filetype, "register", lambda *a, **k: None)
    monkeypatch.setattr(filetype, "user_choice", lambda: "SomeOther.Viewer")
    assert app_mod.main(["prog", "--flag", good_file]) == 0
    assert opened == [good_file]
    window = built[0]
    assert window.statusBar().currentMessage() == app_mod.OTHER_PROGRAM
    qapp.removeEventFilter(qapp._annotshot_file_filter)
    window.deleteLater()


def test_run_passes_the_argument_to_main(monkeypatch):
    from annotshot import __main__ as entry
    seen = []
    monkeypatch.setattr(app_mod, "main", lambda argv=None: seen.append(argv) or 0)
    assert entry.run(["some.annotshot"]) == 0
    assert seen[0][1:] == ["some.annotshot"]


# -- QFileOpenEvent (macOS Finder, the Dock) ----------------------------------------
def test_a_posted_file_open_event_opens_the_file(qapp, window, good_file,
                                                 warnings_shown):
    f = app_mod.FileOpenFilter(window)
    qapp.installEventFilter(f)
    try:
        QApplication.postEvent(qapp, QFileOpenEvent(QUrl.fromLocalFile(good_file)))
        qapp.processEvents()
    finally:
        qapp.removeEventFilter(f)
    assert os.path.samefile(window.doc.path, good_file)
    assert warnings_shown == []


# -- the command strings (pure) ------------------------------------------------------
def test_command_for_a_frozen_exe():
    exe = r"C:\Apps\Annotshot\Annotshot.exe"
    assert filetype.command_for(True, exe, r"C:\ignored") == \
        (f'"{exe}" "%1"', f'"{exe}",0')


def test_command_for_source_with_pythonw(tmp_path):
    scripts = tmp_path / "venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "pythonw.exe").write_bytes(b"")
    python = str(scripts / "python.exe")
    root = str(tmp_path / "repo")
    cmd, icon = filetype.command_for(False, python, root)
    pythonw = os.path.join(str(scripts), "pythonw.exe")
    script = os.path.join(root, "Annotshot.pyw")
    assert cmd == f'"{pythonw}" "{script}" "%1"'
    assert icon == f'"{os.path.join(root, "annotshot.ico")}",0'


def test_command_for_source_without_pythonw_uses_the_interpreter(tmp_path):
    python = str(tmp_path / "bin" / "python3")
    root = str(tmp_path / "repo")
    cmd, _ = filetype.command_for(False, python, root)
    assert cmd == f'"{python}" "{os.path.join(root, "Annotshot.pyw")}" "%1"'


def test_not_windows_returns_none_at_once(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert filetype.register() is None and filetype.user_choice() is None


def test_extensions_cover_the_current_and_legacy_names():
    assert filetype.EXTENSIONS[0] == ".annotshot" and len(filetype.EXTENSIONS) == 2


# -- the registry (Windows only, a scratch key) --------------------------------------
@pytest.mark.skipif(sys.platform != "win32", reason="the registry is Windows'")
def test_register_writes_then_finds_everything_the_same():
    import winreg
    base = "Software\\AnnotshotTest"
    hive = base + "\\Classes"

    def delete(root, path):
        try:
            with winreg.OpenKey(root, path) as k:
                while True:
                    try:
                        child = winreg.EnumKey(k, 0)
                    except OSError:
                        break
                    delete(root, f"{path}\\{child}")
            winreg.DeleteKey(root, path)
        except FileNotFoundError:
            pass

    delete(winreg.HKEY_CURRENT_USER, base)
    try:
        assert filetype.register(hive) == "written"
        assert filetype.register(hive) == "same"
        hk = winreg.HKEY_CURRENT_USER
        with winreg.OpenKey(hk, f"{hive}\\.annotshot") as k:
            assert winreg.QueryValueEx(k, "")[0] == filetype.PROGID
        cmd, _ = filetype.command_for(bool(getattr(sys, "frozen", False)),
                                      sys.executable, filetype._root())
        with winreg.OpenKey(hk, f"{hive}\\{filetype.PROGID}\\shell\\open\\command") as k:
            assert winreg.QueryValueEx(k, "")[0] == cmd
        if getattr(sys, "frozen", False):
            with winreg.OpenKey(hk, f"{hive}\\Applications\\Annotshot.exe\\SupportedTypes") as k:
                winreg.QueryValueEx(k, ".annotshot")
        else:
            with winreg.OpenKey(hk, f"{hive}\\{filetype.PROGID}\\shell\\open") as k:
                assert winreg.QueryValueEx(k, "FriendlyAppName")[0] == "Annotshot"
        with winreg.OpenKey(hk, f"{hive}\\{filetype.PROGID}\\shell\\open\\command",
                            0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "stale")
        assert filetype.register(hive) == "written"   # repaired on the next start
    finally:
        delete(winreg.HKEY_CURRENT_USER, base)


# -- s2 fixes: the registration plan (pure, every system) -----------------------
def test_plan_from_source_names_the_progid_and_writes_no_exe_entry(tmp_path):
    scripts = tmp_path / "venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "pythonw.exe").write_bytes(b"")
    python, root = str(scripts / "python.exe"), str(tmp_path / "repo")
    rows = filetype.plan(False, python, root)
    cmd, icon = filetype.command_for(False, python, root)
    values = {(sub, name): v for sub, name, v in rows}
    p = filetype.PROGID
    assert values[(f"{p}\\shell\\open", "FriendlyAppName")] == "Annotshot"
    assert values[(f"{p}\\shell\\open\\command", "")] == cmd
    assert values[(f"{p}\\DefaultIcon", "")] == icon
    for ext in filetype.EXTENSIONS:
        assert values[(ext, "")] == p
        assert (f"{ext}\\OpenWithProgids", p) in values
    assert not any(sub.startswith("Applications") for sub, _, _ in rows)


def test_plan_frozen_keeps_the_exe_entry():
    exe = r"C:\Apps\Annotshot\Annotshot.exe"
    rows = filetype.plan(True, exe, r"C:\ignored")
    cmd, _ = filetype.command_for(True, exe, r"C:\ignored")
    values = {(sub, name): v for sub, name, v in rows}
    app = f"Applications\\{filetype.APP_EXE}"
    assert values[(app, "FriendlyAppName")] == "Annotshot"
    assert values[(f"{app}\\shell\\open\\command", "")] == cmd
    for ext in filetype.EXTENSIONS:
        assert (f"{app}\\SupportedTypes", ext) in values
    assert (f"{filetype.PROGID}\\shell\\open", "FriendlyAppName") not in values


def test_register_writes_exactly_the_plan(monkeypatch):
    """register() on a stand-in registry: every row of the plan, nothing
    else, and nothing written the second time."""
    import types
    store = {}

    class Key:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def open_key(root, path, *a):
        if path not in store:
            raise FileNotFoundError(path)
        return Key(path)

    def query(k, name):
        if name not in store[k.path]:
            raise FileNotFoundError(name)
        return store[k.path][name], 1

    def create(root, path, *a):
        store.setdefault(path, {})
        return Key(path)

    def set_value(k, name, _reserved, _kind, value):
        store[k.path][name] = value

    fake = types.SimpleNamespace(
        HKEY_CURRENT_USER=0, KEY_SET_VALUE=2, REG_SZ=1, OpenKey=open_key,
        QueryValueEx=query, CreateKeyEx=create, SetValueEx=set_value)
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setitem(sys.modules, "ctypes", None)   # no notice to send
    monkeypatch.setattr(sys, "platform", "win32")
    assert filetype.register("H") == "written"
    assert filetype.register("H") == "same"
    monkeypatch.undo()
    rows = filetype.plan(bool(getattr(sys, "frozen", False)), sys.executable,
                         filetype._root())
    written = {(path[2:], name): v for path, values in store.items()
               for name, v in values.items()}
    assert written == {(sub, name): v for sub, name, v in rows}


@pytest.mark.parametrize("choice,ours", [
    ("Annotshot.Editable", True), ("annotshot.editable", True),
    ("Applications\\Annotshot.exe", True),
    ("APPLICATIONS\\annotshot.EXE", True),
    ("SomeOther.Viewer", False), ("Applications\\Other.exe", False),
    ("", False), (None, False)])
def test_is_ours(choice, ours):
    assert filetype.is_ours(choice) is ours


def test_main_is_quiet_when_annotshot_was_chosen_through_open_with(
        qapp, monkeypatch):
    built = []
    monkeypatch.setattr(MainWindow, "show", lambda self: built.append(self))
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    monkeypatch.setattr(filetype, "register", lambda *a, **k: None)
    monkeypatch.setattr(filetype, "user_choice",
                        lambda: "Applications\\Annotshot.exe")
    assert app_mod.main(["prog"]) == 0
    window = built[0]
    assert window.statusBar().currentMessage() != app_mod.OTHER_PROGRAM
    qapp.removeEventFilter(qapp._annotshot_file_filter)
    window.deleteLater()


# -- s2 fixes: the command line says why nothing opened ---------------------------
def test_argument_problem(tmp_path, good_file):
    missing = tmp_path / "gone.annotshot"
    folder = tmp_path / "x.annotshot"
    folder.mkdir()
    upper = tmp_path / "LOST.ANNOTSHOT"
    other = tmp_path / "nothere.png"
    assert app_mod.argument_problem(["prog", str(missing)]) == \
        "Could not find gone.annotshot"
    assert app_mod.argument_problem(["prog", str(upper)]) == \
        "Could not find LOST.ANNOTSHOT"
    assert app_mod.argument_problem(["prog", str(folder)]) == \
        "x.annotshot is a folder, not a file"
    assert app_mod.argument_problem(
        ["prog", "--x.annotshot", str(other)]) is None
    assert app_mod.argument_problem(["prog", good_file]) is None
    assert app_mod.argument_problem([str(missing)]) is None   # the program


def _missing(d):
    return d / "gone.annotshot"


def _folder(d):
    (d / "x.annotshot").mkdir()
    return d / "x.annotshot"


@pytest.mark.parametrize("make,line", [
    (_missing, "Could not find gone.annotshot"),
    (_folder, "x.annotshot is a folder, not a file")])
def test_main_shows_the_argument_problem(qapp, tmp_path, monkeypatch, make,
                                         line):
    built, opened = [], []
    monkeypatch.setattr(MainWindow, "show", lambda self: built.append(self))
    monkeypatch.setattr(MainWindow, "open_path",
                        lambda self, p, ask=True: opened.append(p) or True)
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    monkeypatch.setattr(filetype, "register", lambda *a, **k: None)
    monkeypatch.setattr(filetype, "user_choice", lambda: None)
    assert app_mod.main(["prog", "--flag", str(make(tmp_path))]) == 0
    window = built[0]
    assert opened == []
    assert window.statusBar().currentMessage() == line
    qapp.removeEventFilter(qapp._annotshot_file_filter)
    window.deleteLater()


# -- s2 fixes: open_path -------------------------------------------------------------
def test_open_path_makes_a_relative_path_absolute(window, good_file,
                                                  monkeypatch, tmp_path):
    folder = os.path.dirname(good_file)
    monkeypatch.chdir(folder)
    assert window.open_path(os.path.basename(good_file)) is True
    monkeypatch.chdir(str(tmp_path.parent))          # the cwd moves on
    assert os.path.isabs(window.doc.path)
    assert os.path.samefile(window.doc.path, good_file)
    remembered = window.settings.value("last_dir/project", type=str)
    assert os.path.isabs(remembered) and os.path.samefile(remembered, folder)


def _zip(path, members):
    import zipfile
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


def _not_a_zip(d):
    (d / "bad.annotshot").write_bytes(b"not a zip")
    return d / "bad.annotshot"


def _no_json(d):
    return _zip(d / "nojson.annotshot", {"base.png": b"x"})


def _bad_json(d):
    return _zip(d / "badjson.annotshot",
                {"project.json": b"{nope", "base.png": b"x"})


def _other_format(d):
    return _zip(d / "other.annotshot",
                {"project.json": b'{"format": "something-else"}',
                 "base.png": b"x"})


DAMAGED = "This is not an Annotshot file, or it is damaged:"


@pytest.mark.parametrize("make,first", [
    (_missing, "The file is no longer there:"),
    (_folder, "This is a folder, not a file:"),
    (_not_a_zip, DAMAGED), (_no_json, DAMAGED), (_bad_json, DAMAGED),
    (_other_format, "Could not open other.annotshot:")])
def test_open_path_says_plainly_why(window, tmp_path, warnings_shown, make,
                                    first):
    path = make(tmp_path)
    assert window.open_path(str(path)) is False
    assert len(warnings_shown) == 1
    head, _, rest = warnings_shown[0].partition("\n")
    assert head == first
    if not first.startswith("Could not open"):
        assert rest == path.name                    # the name, no errno
    assert "Errno" not in warnings_shown[0]


def test_open_project_asks_the_discard_question_once(window, good_file, white,
                                                     monkeypatch):
    from annotshot import mainwindow
    window._bind(Document(white))
    add(window.doc, RectItem, (5, 5, 20, 20))       # an unsaved change
    asked = []

    def question(*a, **k):
        asked.append(a)
        return mainwindow.QMessageBox.Discard
    monkeypatch.setattr(mainwindow.QMessageBox, "question",
                        staticmethod(question))
    monkeypatch.setattr(mainwindow.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (good_file, "")))
    window.open_project()
    assert len(asked) == 1
    assert os.path.samefile(window.doc.path, good_file)


# -- s2 fixes: two files arriving at once (macOS) ------------------------------------
def test_a_second_file_open_during_the_question_waits_its_turn(
        qapp, window, good_file, white, tmp_path, monkeypatch, warnings_shown):
    from annotshot import mainwindow
    second_doc = Document(white)
    add(second_doc, RectItem, (1, 1, 9, 9))
    second = str(tmp_path / "second.annotshot")
    second_doc.save(second)
    window._bind(Document(white))
    add(window.doc, RectItem, (5, 5, 20, 20))       # an unsaved change
    depth, deepest, asked = [0], [0], []

    def question(*a, **k):
        asked.append(a)
        depth[0] += 1
        deepest[0] = max(deepest[0], depth[0])
        if len(asked) == 1:                         # the second file arrives
            QApplication.postEvent(
                qapp, QFileOpenEvent(QUrl.fromLocalFile(second)))
            qapp.processEvents()
        depth[0] -= 1
        return mainwindow.QMessageBox.Discard
    monkeypatch.setattr(mainwindow.QMessageBox, "question",
                        staticmethod(question))
    f = app_mod.FileOpenFilter(window)
    qapp.installEventFilter(f)
    try:
        QApplication.postEvent(
            qapp, QFileOpenEvent(QUrl.fromLocalFile(good_file)))
        qapp.processEvents()
        qapp.processEvents()
    finally:
        qapp.removeEventFilter(f)
    assert deepest[0] == 1                          # never one inside another
    assert len(asked) == 1                          # the first file was clean
    assert os.path.samefile(window.doc.path, second)
    assert warnings_shown == []


def test_only_the_newest_waiting_file_is_kept(window, monkeypatch):
    f = app_mod.FileOpenFilter(window)
    opened = []

    def open_now(path, ask):
        opened.append(os.path.basename(path))
        if path.endswith("a"):
            f._open("b")
            f._open("c")                            # the newest wins
        return True
    monkeypatch.setattr(window, "_open_now", open_now)
    f._open("a")
    assert opened == ["a", "c"]
    f._open("d")                                    # the guard is released
    assert opened == ["a", "c", "d"]


def _saved(white, path, box):
    doc = Document(white)
    add(doc, RectItem, box)
    doc.save(path)
    return str(path)


def test_a_finder_open_during_opens_own_question_waits(
        qapp, window, good_file, white, tmp_path, monkeypatch,
        warnings_shown):
    """Open… asks its discard question; a file from Finder arrives while it
    is on screen: it is kept, never opened inside the question. The file
    then chosen in the Open window is the newest choice and is left open."""
    from annotshot import mainwindow
    finder = _saved(white, tmp_path / "finder.annotshot", (1, 1, 9, 9))
    window._bind(Document(white))
    add(window.doc, RectItem, (5, 5, 20, 20))       # an unsaved change
    depth, deepest, asked, loads = [0], [0], [], []

    def question(*a, **k):
        asked.append(a)
        depth[0] += 1
        deepest[0] = max(deepest[0], depth[0])
        if len(asked) == 1:
            QApplication.postEvent(
                qapp, QFileOpenEvent(QUrl.fromLocalFile(finder)))
            qapp.processEvents()                    # as a real box would
        depth[0] -= 1
        return mainwindow.QMessageBox.Discard
    monkeypatch.setattr(mainwindow.QMessageBox, "question",
                        staticmethod(question))
    monkeypatch.setattr(mainwindow.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (good_file, "")))
    real_open_now = MainWindow._open_now
    monkeypatch.setattr(
        window, "_open_now",
        lambda path, ask: loads.append((os.path.basename(path), depth[0]))
        or real_open_now(window, path, ask))
    f = app_mod.FileOpenFilter(window)
    qapp.installEventFilter(f)
    try:
        window.open_project()
        qapp.processEvents()
    finally:
        qapp.removeEventFilter(f)
    assert deepest[0] == 1 and len(asked) == 1      # one question, not nested
    assert loads == [("shot.annotshot", 0)]         # nothing ran inside it
    assert os.path.samefile(window.doc.path, good_file)
    assert window._kept is None and not window._opening
    assert warnings_shown == []


def test_a_finder_open_during_open_is_question_opens_after_cancel(
        qapp, window, white, tmp_path, monkeypatch, warnings_shown):
    """The user cancels Open…'s question: the Finder file kept meanwhile
    opens next, with its own question."""
    from annotshot import mainwindow
    finder = _saved(white, tmp_path / "finder.annotshot", (1, 1, 9, 9))
    window._bind(Document(white))
    add(window.doc, RectItem, (5, 5, 20, 20))       # an unsaved change
    answers = [mainwindow.QMessageBox.Cancel, mainwindow.QMessageBox.Discard]
    asked = []

    def question(*a, **k):
        asked.append(a)
        if len(asked) == 1:
            QApplication.postEvent(
                qapp, QFileOpenEvent(QUrl.fromLocalFile(finder)))
            qapp.processEvents()
        return answers[len(asked) - 1]
    monkeypatch.setattr(mainwindow.QMessageBox, "question",
                        staticmethod(question))
    monkeypatch.setattr(mainwindow.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: pytest.fail("no Open")))
    f = app_mod.FileOpenFilter(window)
    qapp.installEventFilter(f)
    try:
        window.open_project()
    finally:
        qapp.removeEventFilter(f)
    assert len(asked) == 2                          # one after the other
    assert os.path.samefile(window.doc.path, finder)


def test_a_failed_open_drops_the_kept_file(window, monkeypatch):
    """An open that raises clears the file kept meanwhile, so a stale one
    never opens later."""
    f = app_mod.FileOpenFilter(window)
    opened = []

    def open_now(path, ask):
        opened.append(os.path.basename(path))
        if path.endswith("first"):
            f._open("stale")                        # arrives meanwhile
            raise RuntimeError("bind failed")
        return True
    monkeypatch.setattr(window, "_open_now", open_now)
    with pytest.raises(RuntimeError):
        f._open("first")
    assert window._kept is None and not window._opening
    f._open("next")
    assert opened == ["first", "next"]


# -- the settings stay private to each test -------------------------------------------
def test_the_app_settings_are_private_to_the_test(window, tmp_path):
    from annotshot import mainwindow
    name = mainwindow.QSettings("Annotshot", "Annotshot").fileName()
    assert os.path.commonpath([name, str(tmp_path)]) == str(tmp_path)
    assert os.path.commonpath([window.settings.fileName(),
                               str(tmp_path)]) == str(tmp_path)


# -- s2 polish -----------------------------------------------------------------------
def test_a_folder_named_with_a_trailing_slash_is_a_folder(tmp_path):
    folder = _folder(tmp_path)
    for arg in (str(folder) + os.sep, str(folder) + "/", str(folder)):
        assert app_mod.argument_problem(["prog", arg]) == \
            "x.annotshot is a folder, not a file"


def test_a_damaged_compressed_member_is_said_plainly(window, good_file,
                                                     tmp_path, warnings_shown):
    """A cut-short or damaged download most often breaks a compressed
    member: zlib's own error, not BadZipFile."""
    import zipfile
    with zipfile.ZipFile(good_file) as z:
        members = {n: z.read(n) for n in z.namelist()}
    bad = tmp_path / "deflate.annotshot"
    with zipfile.ZipFile(bad, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data + (b" " * 4000 if name == "project.json"
                                     else b""))
    raw = bytearray(bad.read_bytes())
    at = raw.find(b"project.json") + len("project.json") + 5
    for k in range(at, at + 40):
        raw[k] ^= 0xFF
    bad.write_bytes(bytes(raw))
    assert window.open_path(str(bad)) is False
    assert warnings_shown == [
        "This is not an Annotshot file, or it is damaged:\ndeflate.annotshot"]


def test_open_warning_maps_a_zlib_error():
    import zlib
    from annotshot.mainwindow import open_warning
    assert open_warning("/x/a.annotshot", zlib.error("invalid stored block")) \
        == "This is not an Annotshot file, or it is damaged:\na.annotshot"
