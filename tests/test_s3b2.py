"""Round 2 (B): the Windows installer, the SmartScreen step, the Recent
captures pane and the bundled pixel font. Offscreen; every file a test
writes is under its own tmp folder."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ISS = ROOT / "packaging" / "annotshot.iss"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
BUILD_WIN = ROOT / "packaging" / "build-win.ps1"


# -- 1. the Windows installer ------------------------------------------------
def _iss_sections() -> dict[str, list[str]]:
    """The script's lines by section, comments and preprocessor lines out."""
    out, name = {}, ""
    for raw in ISS.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        m = re.fullmatch(r"\[(\w+)\]", line)
        if m:
            name = m.group(1)
            out.setdefault(name, [])
            continue
        out.setdefault(name, []).append(line)
    return out


def _setup() -> dict[str, str]:
    return dict(line.split("=", 1) for line in _iss_sections()["Setup"])


def _params(line: str) -> dict[str, str]:
    """One Inno entry line (Key: value; Key: a quoted value with doubled
    quotes) as a dict."""
    out = {}
    for m in re.finditer(r'(\w+):\s*("(?:[^"]|"")*"|[^;]*)', line):
        value = m.group(2).strip()
        if value.startswith('"'):
            value = value[1:-1].replace('""', '"')
        out[m.group(1)] = value
    return out


def test_the_installer_script_is_ascii_and_takes_its_version_from_outside():
    text = ISS.read_text(encoding="utf-8")
    assert text.isascii()
    setup = _setup()
    assert setup["AppVersion"] == "{#AppVersion}"
    assert setup["OutputBaseFilename"] == "Annotshot-{#AppVersion}-setup"
    from annotshot import __version__
    assert __version__ not in text            # never typed twice
    # ASSUMES: the version is always passed in; without it iscc stops.
    assert re.search(r"#ifndef AppVersion\s*\n\s*#error", text)


def test_the_installer_is_per_user_and_asks_for_the_folder():
    s = _setup()
    assert s["PrivilegesRequired"] == "lowest"
    assert s["PrivilegesRequiredOverridesAllowed"] == "dialog"
    assert s["DefaultDirName"] == r"{autopf}\Annotshot"
    assert s["DisableDirPage"] == "no"
    assert s["DefaultGroupName"] == "Annotshot"
    assert s["CloseApplications"] == "yes"
    assert s["ChangesAssociations"] == "yes"
    assert s["ArchitecturesInstallIn64BitMode"] == "x64compatible"
    assert s["WizardStyle"] == "modern"


def test_the_installer_names_its_publisher_and_icon():
    s = _setup()
    assert s["AppName"] == "Annotshot"
    assert s["AppPublisher"] == "Viking Software"
    assert s["AppPublisherURL"] == "https://github.com/Bill-Viking/annotshot"
    assert s["AppSupportURL"] == "https://github.com/Bill-Viking/annotshot/issues"
    assert re.fullmatch(r"\{\{[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}\}",
                        s["AppId"])
    assert s["SetupIconFile"] == r"..\annotshot.ico"
    assert (ROOT / "annotshot.ico").is_file()
    assert s["UninstallDisplayIcon"] == r"{app}\Annotshot.exe"
    text = ISS.read_text(encoding="utf-8")
    # LICENSE is written by the public cut; the script uses it where it is.
    assert '#ifexist "..\\LICENSE"\nLicenseFile=..\\LICENSE\n#endif' in text


def test_the_start_menu_entry_and_the_unchecked_desktop_icon():
    sec = _iss_sections()
    tasks = [_params(l) for l in sec["Tasks"]]
    assert tasks == [{"Name": "desktopicon",
                      "Description": "{cm:CreateDesktopIcon}",
                      "GroupDescription": "{cm:AdditionalIcons}",
                      "Flags": "unchecked"}]
    icons = [_params(l) for l in sec["Icons"]]
    assert {"Name": r"{group}\Annotshot",
            "Filename": r"{app}\Annotshot.exe"} in icons
    desk = [i for i in icons if i["Name"].startswith("{autodesktop}")]
    assert desk and desk[0]["Tasks"] == "desktopicon"
    files = [_params(l) for l in sec["Files"]]
    assert files[0]["Source"] == "{#SourceDir}\\*"
    assert "recursesubdirs" in files[0]["Flags"]


def test_the_installer_registers_the_file_type_as_the_app_does():
    """Every row annotshot/filetype.py writes for a frozen app is a Registry
    line under HKA\\Software\\Classes, with the installed exe, and nothing
    else is; each is removed on uninstall."""
    from annotshot import filetype
    exe = r"{app}\Annotshot.exe"
    want = set(filetype.plan(True, exe, "unused"))
    rows = [_params(l) for l in _iss_sections()["Registry"]]
    got = set()
    for r in rows:
        assert r["Root"] == "HKA" and r["ValueType"] == "string"
        assert r["Subkey"].startswith("Software\\Classes\\")
        assert r["Flags"] in ("uninsdeletekey", "uninsdeletevalue")
        got.add((r["Subkey"][len("Software\\Classes\\"):], r["ValueName"],
                 r["ValueData"]))
    assert got == want
    progid = [r for r in rows
              if r["Subkey"] == f"Software\\Classes\\{filetype.PROGID}"]
    assert progid and progid[0]["Flags"] == "uninsdeletekey"
    # The extension keys are shared with Windows: only our values go.
    for ext in filetype.EXTENSIONS:
        for r in rows:
            if r["Subkey"] == f"Software\\Classes\\{ext}":
                assert r["Flags"] == "uninsdeletevalue"


def test_the_opposite_case_a_changed_progid_would_fail_the_match():
    """The comparison above is not vacuous: one changed value breaks it."""
    from annotshot import filetype
    rows = set(filetype.plan(True, r"{app}\Annotshot.exe", "unused"))
    changed = {(s, n, v.replace(filetype.PROGID, "Other.Editable"))
               for s, n, v in rows}
    assert changed != rows


def test_the_installer_never_removes_the_users_files():
    sec = _iss_sections()
    deletes = [_params(l) for l in sec.get("UninstallDelete", [])]
    assert deletes == [{"Type": "files", "Name": r"{app}\check.txt"}]


def _step(text: str, name: str) -> str:
    start = text.index(f"- name: {name}")
    nxt = text.find("\n      - ", start + 1)
    return text[start:nxt if nxt > 0 else len(text)]


def test_the_workflow_builds_and_proves_the_installer_between_check_and_zip():
    text = WORKFLOW.read_text(encoding="utf-8")
    order = [text.index(f"- name: {n}") for n in (
        "Frozen self-check", "Installer (Windows)", "Zip (Windows)")]
    assert order == sorted(order)
    step = _step(text, "Installer (Windows)")
    assert "if: runner.os == 'Windows'" in step
    assert r"${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'" in step
    assert "STOP Inno Setup 6 is not on this runner" in step
    assert '"/DAppVersion=$v"' in step and "packaging/annotshot.iss" in step
    assert "$v = '${{ steps.version.outputs.version }}'" in step
    for flag in ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                 "annot-inst", "/LOG="):
        assert flag in step
    assert "'--check'" in step and '"Annotshot $v OK"' in step
    assert "unins000.exe" in step
    # the opposite case: after the uninstall the folder must be gone
    assert "STOP the uninstall left $dir" in step
    assert "STOP the uninstall left the .annotshot file type" in step


def test_the_setup_exe_is_uploaded_and_attached_with_the_zips():
    text = WORKFLOW.read_text(encoding="utf-8")
    upload = text[text.index("actions/upload-artifact@v4"):]
    assert "Annotshot-*-setup.exe" in upload.split("release:")[0]
    release = text[text.index("softprops/action-gh-release@v2"):]
    assert "zips/*.zip" in release and "zips/*-setup.exe" in release


def test_the_windows_build_script_makes_the_installer_or_says_why_not():
    ps1 = BUILD_WIN.read_text(encoding="utf-8")
    assert ps1.isascii()
    assert "$Total = 6" in ps1
    assert r"'Inno Setup 6\ISCC.exe'" in ps1
    assert '"/DAppVersion=$Version"' in ps1
    assert "packaging\\annotshot.iss" in ps1
    # the opposite case: no Inno Setup -> one line, and the zip still comes
    assert ("installer skipped: Inno Setup 6 (ISCC.exe) is not on this "
            "computer - the zip is still built") in ps1
    assert ps1.index("# 4. the installer") < ps1.index("# 5. the zip")


def _manual() -> str:
    return (ROOT / "docs" / "USER-MANUAL.md").read_text(encoding="utf-8")


def test_the_manual_gives_the_installer_first_and_the_zip_second():
    from annotshot import __version__
    m = _manual()
    win = m[m.index("### Windows (10 and 11)"):m.index("### macOS — four steps")]
    assert win.index("#### The installer") < win.index("#### The zip")
    installer = win[:win.index("#### The zip")]
    assert f"Annotshot-{__version__}-setup.exe" in installer
    assert "Start menu" in installer and "**Install**" in installer
    assert f"Annotshot-{__version__}-windows.zip" in win[win.index("#### The zip"):]
    updating = m[m.index("### Updating to a new version"):]
    assert "it replaces the old copy in place" in updating
    removing = m[m.index("### Removing Annotshot"):m.index("## The first ten seconds")]
    assert "**Settings → Apps**" in removing and "**Uninstall**" in removing


# -- 2. the SmartScreen step: the words now, the picture when it exists ------
SMARTSCREEN = ("Windows will show a blue box, **Windows protected your PC**, "
               "because Annotshot is new and not yet signed: click **More "
               "info**, then **Run anyway**.")


def _public_readme() -> str:
    import importlib.util
    tool = ROOT / "tools" / "public-cut.py"
    if not tool.is_file():
        pytest.skip("the README is written by the repository's own cut tool")
    spec = importlib.util.spec_from_file_location("public_cut_readme", tool)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.README.format(description="D.", version="9.9.9")


@pytest.mark.parametrize("which", ["manual", "readme"])
def test_both_windows_roads_lead_with_the_box_and_hold_the_picture_spot(which):
    text = _manual() if which == "manual" else _public_readme()
    pic = "windows-protected.png" if which == "manual" \
        else "docs/windows-protected.png"
    win = text[text.index("### Windows (10 and 11)"):
               text.index("### macOS — four steps")]
    roads = win.split("#### ")[1:]
    assert [r.split(" — ")[0] for r in roads] == ["The installer", "The zip"]
    for road in roads:
        assert SMARTSCREEN in road
        comment = re.search(r"<!-- picture: (.*?) -->", road)
        assert comment and pic in comment.group(1)
        assert (f"![Windows protected your PC — click More info, then Run "
                f"anyway]({pic})") in comment.group(1)
    # no image tag outside the comment: the picture does not exist yet
    bare = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    assert "windows-protected" not in bare


def test_the_help_window_never_shows_the_picture_note(qapp):
    from PySide6.QtWidgets import QTextBrowser
    b = QTextBrowser()
    b.setMarkdown(_manual())
    shown = b.toPlainText()
    assert "Windows protected your PC" in shown
    assert "windows-protected" not in shown
    assert "is captured on a Windows computer" not in shown


# -- 3. the Recent captures pane --------------------------------------------
@pytest.fixture
def window(qapp):
    from annotshot.app import make_app
    from annotshot.mainwindow import MainWindow
    make_app()
    w = MainWindow()
    yield w
    w.deleteLater()


def picture(w=320, h=180, color="#3366CC"):
    from PySide6.QtGui import QColor, QImage
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(color))
    return img


def at(minutes_ago: int = 0, days_ago: int = 0):
    from PySide6.QtCore import QDateTime
    return QDateTime.currentDateTime().addDays(-days_ago).addSecs(
        -60 * minutes_ago)


def settle(qapp):
    from PySide6.QtCore import QThreadPool
    QThreadPool.globalInstance().waitForDone()
    qapp.processEvents()
    qapp.processEvents()


def test_the_store_keeps_the_last_twelve(tmp_path):
    from annotshot.recent import KEEP, RecentStore
    store = RecentStore(lambda: tmp_path / "Recent")
    assert KEEP == 12 and store.files() == []      # no folder: nothing
    made = [store.file(picture(), at(minutes_ago=100 - i)) for i in range(12)]
    assert len(store.files()) == 12
    assert store.files()[0] == made[-1]            # newest first
    newest = store.file(picture(), at())           # the 13th arrival
    files = store.files()
    assert len(files) == 12 and files[0] == newest
    assert not made[0].exists() and made[1].exists()   # the oldest went


def test_the_names_are_timestamps_that_windows_accepts(tmp_path):
    from annotshot.recent import RecentStore, taken_at
    store = RecentStore(lambda: tmp_path)
    when = at()
    p = store.file(picture(), when)
    assert ":" not in p.name and p.suffix == ".png"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d-\d{3}\.png", p.name)
    assert taken_at(p).toString("yyyy-MM-dd HH:mm:ss") == \
        when.toString("yyyy-MM-dd HH:mm:ss")
    twin = store.file(picture(), when)             # the same millisecond
    assert twin != p and twin.exists() and p.exists()
    # ASSUMES the names are ours; the opposite case: another .png is timed
    # by its file's own time and still listed.
    other = tmp_path / "holiday.png"
    picture().save(str(other))
    assert other in store.files()
    assert taken_at(other).isValid()


def test_the_time_under_each_thumbnail():
    from PySide6.QtCore import QDate, QDateTime, QTime
    from annotshot.recent import time_label
    now = QDateTime(QDate(2026, 11, 4), QTime(15, 0))        # a Wednesday
    assert time_label(QDateTime(QDate(2026, 11, 4), QTime(12, 34)), now) == "12:34"
    assert time_label(QDateTime(QDate(2026, 11, 3), QTime(9, 5)), now) == "Tue 09:05"
    assert time_label(QDateTime(QDate(2026, 10, 29), QTime(9, 5)), now) == "Thu 09:05"
    assert time_label(QDateTime(QDate(2026, 10, 28), QTime(9, 5)), now) == "28 Oct"
    assert time_label(QDateTime(QDate(2025, 12, 1), QTime(9, 5)), now) == "1 Dec 2025"


def test_the_thumbnail_is_letterboxed_16_by_9(tmp_path):
    from annotshot.recent import THUMB, THUMB_GROUND, thumbnail
    tall = tmp_path / "tall.png"
    picture(100, 400, "#FF0000").save(str(tall))
    pm = thumbnail(tall)
    assert (pm.width(), pm.height()) == (THUMB.width(), THUMB.height())
    img = pm.toImage()
    assert img.pixelColor(80, 45).name().upper() == "#FF0000"     # centred
    assert img.pixelColor(2, 45).name().upper() == THUMB_GROUND.upper()
    assert thumbnail(tmp_path / "missing.png").isNull()


def test_the_pane_docks_right_and_its_place_is_remembered(window, private_settings):
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtWidgets import QDockWidget
    from annotshot.mainwindow import MainWindow
    pane = window.recent
    assert window.dockWidgetArea(pane) == Qt.RightDockWidgetArea
    assert pane.allowedAreas() == Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea
    f = pane.features()
    assert f & QDockWidget.DockWidgetFloatable and f & QDockWidget.DockWidgetClosable
    assert not pane.isHidden()                     # shown the first time
    assert pane.windowTitle() == "Recent captures"
    window.addDockWidget(Qt.LeftDockWidgetArea, pane)   # the user drags it
    window.close()
    window.settings.sync()
    assert QSettings(private_settings, QSettings.IniFormat).contains(
        "window/state")
    again = MainWindow()
    assert again.dockWidgetArea(again.recent) == Qt.LeftDockWidgetArea
    again.recent.hide()                            # the user closes it
    again.close()
    third = MainWindow()
    assert third.recent.isHidden()
    for w in (again, third):
        w.deleteLater()


def test_the_menu_entry_shows_and_hides_the_pane(window, qapp):
    window.show()                       # offscreen: the entry follows a shown pane
    qapp.processEvents()
    a = window.a_recent
    assert a.isChecked()
    assert a.text() == "Recent captures" and a.isCheckable()
    assert a in window.menu_actions(False)
    assert window.menu_actions(False).index(a) == \
        window.menu_actions(False).index(window.a_capture) + 1
    a.trigger()
    assert window.recent.isHidden()
    a.trigger()
    assert not window.recent.isHidden() and a.isChecked()
    window.hide()


def test_a_capture_is_filed_in_the_recent_folder(window, qapp, private_pictures):
    from annotshot.capture import CaptureResult
    window._capture_done(CaptureResult(picture(1280, 720)))
    settle(qapp)
    folder = private_pictures / "Recent"
    files = list(folder.glob("*.png"))
    assert len(files) == 1
    from PySide6.QtGui import QImage
    assert QImage(str(files[0])).size().toTuple() == (1280, 720)   # full PNG
    assert window.recent.paths() == [str(files[0])]
    assert window.statusBar().currentMessage().startswith("Captured")
    assert private_pictures in folder.parents       # the test's own tmp
    window.hide()


def test_quick_capture_is_filed_too(window, qapp, private_pictures, monkeypatch):
    from annotshot import mainwindow
    from annotshot.capture import CaptureResult

    class Board:
        def setImage(self, img):
            pass

    class App:
        @staticmethod
        def clipboard():
            return Board()
    monkeypatch.setattr(mainwindow, "QApplication", App)
    window.settings.setValue("capture/copy", True)
    window._capture_done(CaptureResult(picture()))
    settle(qapp)
    assert len(list((private_pictures / "Recent").glob("*.png"))) == 1
    window.hide()


def test_with_the_setting_off_nothing_is_filed(window, qapp, private_pictures):
    from annotshot.capture import CaptureResult
    from annotshot.recent import SETTING
    window.settings.setValue(SETTING, False)
    window._capture_done(CaptureResult(picture()))
    settle(qapp)
    assert not (private_pictures / "Recent").exists()
    window.hide()


def test_opened_files_are_not_filed(window, qapp, private_pictures, tmp_path):
    from annotshot.scene import Document
    path = tmp_path / "mine.annotshot"
    Document(picture()).save(str(path))
    assert window.open_path(str(path), ask=False)
    settle(qapp)
    assert not (private_pictures / "Recent").exists()


def test_a_write_error_is_one_status_sentence(window, qapp, private_pictures):
    from annotshot.capture import CaptureResult
    private_pictures.mkdir(parents=True)
    (private_pictures / "Recent").write_text("a file where the folder goes")
    window._capture_done(CaptureResult(picture()))     # never raises
    settle(qapp)
    msg = window.statusBar().currentMessage()
    assert msg.startswith("Could not keep the capture in Recent captures: ")
    assert "\n" not in msg
    assert window.doc.base.width() == 320            # the capture still came
    window.hide()


def _two_kept(window, private_pictures):
    store = window.recent_store
    old = store.file(picture(color="#FF0000"), at(minutes_ago=5))
    new = store.file(picture(color="#00FF00"), at())
    window.recent.refresh()
    return old, new


def test_the_list_is_newest_first_and_a_vanished_file_just_drops(window, private_pictures):
    old, new = _two_kept(window, private_pictures)
    pane = window.recent
    assert pane.paths() == [str(new), str(old)]
    assert pane.empty.isHidden()
    texts = [pane.list.item(i).text() for i in range(pane.list.count())]
    assert all(re.fullmatch(r"\d\d:\d\d", t) for t in texts)
    old.unlink()                                    # removed outside the app
    pane.refresh()                                  # no error
    assert pane.paths() == [str(new)]
    new.unlink()
    pane.refresh()
    assert pane.paths() == [] and not pane.empty.isHidden()


def test_a_click_opens_the_capture(window, private_pictures):
    old, new = _two_kept(window, private_pictures)
    pane = window.recent
    pane._clicked(pane.list.item(1))
    assert window.doc.base.pixelColor(5, 5).name().upper() == "#FF0000"
    assert window.doc.path is None or not str(window.doc.path).endswith(".png")


# The double-click's one question: test_s5b's keep-recent-off test.


def test_a_capture_gone_before_the_click_drops_without_asking(window, private_pictures, monkeypatch):
    old, new = _two_kept(window, private_pictures)
    monkeypatch.setattr(window, "maybe_discard",
                        lambda: pytest.fail("asked for a missing file"))
    old.unlink()
    assert window.open_recent(str(old)) is False
    assert window.recent.paths() == [str(new)]


def test_the_right_click_menu(window, private_pictures, monkeypatch):
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QMessageBox
    from annotshot import recent
    old, new = _two_kept(window, private_pictures)
    pane = window.recent
    menu = pane.menu_for(pane.list.item(1))
    names = [a.text() for a in menu.actions()]
    assert names == ["Open", "Delete", "Show in folder", "", "Clear recent captures"]
    opened = []
    pane.openRequested.connect(opened.append)
    menu.actions()[0].trigger()
    assert opened == [str(old)]
    menu.actions()[1].trigger()                     # Delete: no question
    assert not old.exists() and pane.paths() == [str(new)]
    menu.deleteLater()
    urls = []
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda u: urls.append(u) or True))
    menu = pane.menu_for(None)
    assert not menu.actions()[0].isEnabled()       # no thumbnail under it
    menu.actions()[2].trigger()
    assert urls and Path(urls[0].toLocalFile()) == private_pictures / "Recent"
    menu.deleteLater()
    answers = [QMessageBox.Cancel, QMessageBox.Yes]
    asked = []
    monkeypatch.setattr(recent.QMessageBox, "question",
                        staticmethod(lambda *a, **k: asked.append(a[2]) or answers.pop(0)))
    assert pane.clear() is False and new.exists()   # asked, said Cancel
    assert pane.clear() is True and not new.exists()
    assert asked == [recent.CLEAR_QUESTION] * 2
    assert pane.paths() == []


def test_the_capture_tab_has_the_keep_box(window):
    from annotshot.recent import KEEP_TEXT, SETTING
    from annotshot.settings_dialog import SettingsDialog
    d = SettingsDialog(window)
    assert d.keep_recent.text() == KEEP_TEXT == \
        "Keep the last 12 captures in the Recent pane"
    assert d.keep_recent.isChecked()                # on by default
    d.keep_recent.setChecked(False)
    assert window.settings.value(SETTING, True, type=bool) is False
    assert not window.keep_recent()
    d.deleteLater()


def test_the_docked_pane_leaves_the_canvas_the_rest(window):
    window.resize(1100, 720)
    window.layout().setGeometry(window.rect())
    pane, view = window.recent.geometry(), window.view.geometry()
    assert pane.left() > view.right()               # on the right
    assert pane.width() < 260 and view.width() > 800


def test_the_manual_has_a_recent_captures_section():
    m = _manual()
    sec = m[m.index("## Recent captures"):m.index("## Help and About")]
    for words in ("last 12 captures", "Clear recent captures", "Show in folder",
                  "Pictures/Annotshot/Recent",
                  "Keep the last 12 captures in the Recent pane"):
        assert words in sec, words


# -- 4. the pixel font --------------------------------------------------------
def test_the_font_is_in_the_database_after_start(qapp):
    from PySide6.QtGui import QFontDatabase
    from annotshot.app import make_app
    from annotshot import typefaces
    make_app()
    assert "VT323" in QFontDatabase.families()
    assert typefaces.bundled_families() == ["VT323"]
    assert (ROOT / "annotshot" / "fonts" / "VT323-Regular.ttf").is_file()


def test_the_font_box_lists_vt323_first_then_a_line(window):
    from PySide6.QtCore import Qt
    box = window.f_font
    assert box.itemText(0) == "VT323"
    assert box.itemData(0, Qt.ToolTipRole) == "Pixel font (bundled)"
    assert box.is_separator(1)
    rest = [box.itemText(i) for i in range(2, box.count())]
    assert "VT323" not in rest and len(rest) > 0
    assert box.width() == 150


def test_a_text_box_set_to_vt323_draws_with_it_and_keeps_it(window, tmp_path):
    from PySide6.QtGui import QFontInfo
    from annotshot.items import TextBoxItem
    from annotshot.scene import Document
    doc = window.doc
    t = TextBoxItem()
    t.set_geom((10, 10, 300, 80))
    doc.add_items([t])
    doc.select_only([t])
    window.refresh_props()
    window.f_font.setCurrentIndex(0)                # the user picks VT323
    assert t.props["font_family"] == "VT323"
    assert QFontInfo(t.editor.font()).family() == "VT323"   # really drawn with it
    path = tmp_path / "pixel.annotshot"
    doc.save(str(path))
    again = Document.load(str(path))
    t2 = [i for i in again.items() if isinstance(i, TextBoxItem)][0]
    assert t2.props["font_family"] == "VT323"
    assert QFontInfo(t2.editor.font()).family() == "VT323"
    window._bind(again)
    again.select_only([t2])
    window.refresh_props()
    assert window.f_font.currentText() == "VT323"


def test_the_separator_line_is_never_a_font(window):
    picked = []
    window.f_font.currentFontChanged.connect(lambda f: picked.append(f.family()))
    window.f_font.setCurrentIndex(1)
    assert picked == []


def test_without_the_font_file_the_box_has_no_bundled_entry(qapp, tmp_path, monkeypatch):
    """ASSUMES the font rides with the app; the opposite case: no file, no
    entry and no line, and --check says which file is missing."""
    from annotshot import mainwindow, typefaces
    monkeypatch.setattr(typefaces, "_loaded", {})
    monkeypatch.setattr(typefaces, "font_folder", lambda: tmp_path)
    box = mainwindow.FontBox()
    assert box.bundled == [] and not box.is_separator(1)
    from PySide6.QtCore import Qt
    assert box.itemData(0, Qt.ToolTipRole) is None  # no "Pixel font" row
    with pytest.raises(RuntimeError, match="VT323-Regular.ttf is missing"):
        typefaces.check_fonts(tmp_path)
    (tmp_path / "VT323-Regular.ttf").write_bytes(b"not a font")
    with pytest.raises(RuntimeError, match="did not load as VT323"):
        typefaces.check_fonts(tmp_path)
    box.deleteLater()


def test_the_build_carries_the_font_and_its_licence():
    spec = (ROOT / "packaging" / "annotshot.spec").read_text(encoding="utf-8")
    assert 'at("annotshot", "fonts", "VT323-Regular.ttf")' in spec
    assert 'at("packaging", "licenses", "OFL-VT323.txt"), "licenses"' in spec
    yml = WORKFLOW.read_text(encoding="utf-8")
    assert "licenses/OFL-VT323.txt annotshot/fonts/VT323-Regular.ttf" in yml
    from annotshot.__main__ import LICENCE_TEXTS
    assert "OFL-VT323.txt" in LICENCE_TEXTS
    ofl = (ROOT / "packaging" / "licenses" / "OFL-VT323.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1" in ofl and "VT323" in ofl


def test_a_frozen_check_without_the_ofl_text_fails(tmp_path):
    from annotshot.__main__ import _check_licences
    lic = tmp_path / "licenses"
    lic.mkdir()
    for name in ("LGPL-3.0.txt", "GPL-3.0.txt"):
        (lic / name).write_text("x")
    with pytest.raises(RuntimeError, match="OFL-VT323.txt is missing"):
        _check_licences(tmp_path)
    (lic / "OFL-VT323.txt").write_text("x")
    assert _check_licences(tmp_path) == 3
