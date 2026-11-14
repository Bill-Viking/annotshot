"""MSIX layout, package identity and profile-only automatic writes, offscreen."""
import ctypes
import importlib.util
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image
from PySide6.QtCore import QDateTime, QSettings, QStandardPaths

from annotshot import app, filetype, mainwindow, packaged, recent, theme
from annotshot import __main__ as entry

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools/make-msix.py"
NS = {
    "p": "http://schemas.microsoft.com/appx/manifest/foundation/windows10",
    "uap": "http://schemas.microsoft.com/appx/manifest/uap/windows10",
    "rescap": "http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities",
}
DEFAULTS = {
    "MSIX_IDENTITY_NAME": "StetSoftware.Annotshot",
    "MSIX_PUBLISHER": "CN=Stet Software",
    "MSIX_PUBLISHER_DISPLAY": "Stet Software",
}
ASSETS = {
    "Square44x44Logo.png": (44, 44),
    "Square150x150Logo.png": (150, 150),
    "Wide310x150Logo.png": (310, 150),
    "StoreLogo.png": (50, 50),
    "Square44x44Logo.targetsize-44_altform-unplated.png": (44, 44),
}


@pytest.fixture
def dist(tmp_path):
    folder = tmp_path / "dist" / "Annotshot"
    internal = folder / "_internal"
    internal.mkdir(parents=True)
    (folder / "Annotshot.exe").write_bytes(b"frozen executable fixture")
    (internal / "python312.dll").write_bytes(b"runtime fixture")
    (internal / "licenses").mkdir()
    (internal / "licenses/LGPL-3.0.txt").write_text("licence fixture")
    return folder


def run_tool(dist, out, version="0.3.1", values=None):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    for name in DEFAULTS:
        env.pop(name, None)
    env.update(values or {})
    return subprocess.run(
        [sys.executable, str(TOOL), "--dist", str(dist), "--version", version,
         "--out", str(out)], env=env, capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("values", [{}, {
    "MSIX_IDENTITY_NAME": "Example.Annotshot",
    "MSIX_PUBLISHER": 'CN=Example & "Company"',
    "MSIX_PUBLISHER_DISPLAY": "Example & Company",
}])
def test_manifest_identity_and_store_contract(dist, tmp_path, values):
    out = tmp_path / "msix"
    result = run_tool(dist, out, values=values)
    assert result.returncode == 0, result.stdout + result.stderr
    expected = DEFAULTS | values
    identity_line, ready_line = result.stdout.splitlines()
    for key, value in expected.items():
        assert f"{key}={value}" in identity_line
    assert "MSIX layout ready" in ready_line
    manifest = ET.parse(out / "AppxManifest.xml").getroot()
    assert manifest.attrib == {"IgnorableNamespaces": "uap rescap"}
    assert manifest.find("p:Identity", NS).attrib == {
        "Name": expected["MSIX_IDENTITY_NAME"],
        "Publisher": expected["MSIX_PUBLISHER"],
        "Version": "0.3.1.0", "ProcessorArchitecture": "x64"}
    assert manifest.findtext("p:Properties/p:PublisherDisplayName", namespaces=NS) == \
        expected["MSIX_PUBLISHER_DISPLAY"]
    assert manifest.findtext("p:Properties/p:DisplayName", namespaces=NS) == "Annotshot"
    assert manifest.findtext("p:Properties/p:Description", namespaces=NS) == \
        'Annotshot is a screenshot app for Windows, macOS and Linux with PowerPoint-style editing.'
    assert manifest.findtext("p:Properties/p:Logo", namespaces=NS) == "Assets/StoreLogo.png"
    assert manifest.find("p:Dependencies/p:TargetDeviceFamily", NS).attrib == {
        "Name": "Windows.Desktop", "MinVersion": "10.0.17763.0",
        "MaxVersionTested": "10.0.22621.0"}
    assert manifest.find("p:Resources/p:Resource", NS).attrib == {"Language": "en-us"}
    applications = manifest.findall("p:Applications/p:Application", NS)
    assert len(applications) == 1
    application = applications[0]
    assert application.attrib == {"Id": "Annotshot", "Executable": "Annotshot.exe",
                                  "EntryPoint": "Windows.FullTrustApplication"}
    visual = application.find("uap:VisualElements", NS)
    assert visual.attrib["DisplayName"] == "Annotshot"
    assert visual.attrib["BackgroundColor"] == "transparent"
    assert visual.attrib["Square150x150Logo"] == "Assets/Square150x150Logo.png"
    assert visual.attrib["Square44x44Logo"] == "Assets/Square44x44Logo.png"
    assert visual.find("uap:DefaultTile", NS).attrib == {
        "Wide310x150Logo": "Assets/Wide310x150Logo.png"}
    extension = application.find("p:Extensions/uap:Extension", NS)
    assert extension.attrib == {"Category": "windows.fileTypeAssociation"}
    association = extension.find("uap:FileTypeAssociation", NS)
    assert association.attrib == {"Name": "annotshot"}
    assert association.findtext("uap:DisplayName", namespaces=NS) == "Annotshot editable"
    assert association.findtext("uap:SupportedFileTypes/uap:FileType", namespaces=NS) == ".annotshot"
    capabilities = list(manifest.find("p:Capabilities", NS))
    assert [(c.tag, c.attrib) for c in capabilities] == [
        (f"{{{NS['rescap']}}}Capability", {"Name": "runFullTrust"})]


def test_layout_copies_contents_and_makes_the_five_assets(dist, tmp_path):
    out = tmp_path / "msix"
    assert run_tool(dist, out).returncode == 0
    assert not (out / "Annotshot").exists()
    for original in dist.rglob("*"):
        if original.is_file():
            assert (out / original.relative_to(dist)).read_bytes() == original.read_bytes()
    assert not (dist / "AppxManifest.xml").exists()
    assert {p.name for p in (out / "Assets").iterdir()} == set(ASSETS)
    for name, size in ASSETS.items():
        with Image.open(out / "Assets" / name) as image:
            assert image.size == size
            assert image.mode == "RGBA"
    with Image.open(out / "Assets/Wide310x150Logo.png") as wide:
        assert wide.crop((0, 0, 80, 150)).getchannel("A").getbbox() is None
        assert wide.crop((230, 0, 310, 150)).getchannel("A").getbbox() is None
        with Image.open(out / "Assets/Square150x150Logo.png") as square:
            assert wide.crop((80, 0, 230, 150)).tobytes() == square.tobytes()
    assert (out / "Assets/Square44x44Logo.png").read_bytes() == \
        (out / "Assets/Square44x44Logo.targetsize-44_altform-unplated.png").read_bytes()
    (out / "obsolete.dll").write_bytes(b"old")
    assert run_tool(dist, out, version="0.3.2").returncode == 0
    assert not (out / "obsolete.dll").exists()


@pytest.mark.parametrize("version", ["0.3", "0.3.1.0", "v0.3.1", "0.3.x", "-1.3.1", "65536.0.1"])
def test_bad_version_stops_without_an_output(dist, tmp_path, version):
    out = tmp_path / "msix"
    result = run_tool(dist, out, version)
    assert result.returncode == 1
    assert result.stdout.startswith("STOP ")
    assert not out.exists()


def test_missing_executable_stops(dist, tmp_path):
    (dist / "Annotshot.exe").unlink()
    result = run_tool(dist, tmp_path / "msix")
    assert result.returncode == 1
    assert result.stdout.startswith("STOP no Annotshot.exe")


@pytest.mark.parametrize("name", DEFAULTS)
@pytest.mark.parametrize("empty", ["", "   "])
def test_empty_identity_stops(dist, tmp_path, name, empty):
    result = run_tool(dist, tmp_path / "msix", values={name: empty})
    assert result.returncode == 1
    assert f"STOP {name} must not be empty" in result.stdout


def load_tool(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_pillow_says_what_to_install(dist, tmp_path, monkeypatch, capsys):
    import builtins
    real_import = builtins.__import__

    def without_pillow(name, *args, **kwargs):
        if name == "PIL":
            raise ImportError("Pillow missing")
        return real_import(name, *args, **kwargs)

    tool = load_tool("make_msix", TOOL)
    monkeypatch.setattr(builtins, "__import__", without_pillow)
    assert tool.main(["--dist", str(dist), "--version", "0.3.1",
                      "--out", str(tmp_path / "msix")]) == 1
    assert capsys.readouterr().out == "STOP Pillow is needed: run python -m pip install Pillow\n"


def test_staging_refuses_to_replace_input_or_unrelated_files(dist, tmp_path):
    assert run_tool(dist, dist).returncode == 1
    assert run_tool(dist, dist.parent).returncode == 1
    assert run_tool(dist, dist / "msix").returncode == 1
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.txt").write_text("keep")
    assert run_tool(dist, other).returncode == 1
    assert (other / "keep.txt").read_text() == "keep"


def test_package_detection_is_false_off_windows(monkeypatch):
    monkeypatch.setattr(packaged, "sys", SimpleNamespace(platform="darwin"))
    assert packaged.is_packaged() is False
    monkeypatch.setattr(packaged, "sys", SimpleNamespace(platform="linux"))
    assert packaged.is_packaged() is False


@pytest.mark.parametrize("location", ["", "relative"])
def test_missing_app_data_location_still_stays_under_home(monkeypatch, tmp_path, location):
    monkeypatch.setattr(QStandardPaths, "writableLocation", lambda _: location)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "profile")
    assert packaged.app_data_directory() == tmp_path / "profile/AppData/Local/Annotshot"


@pytest.mark.parametrize("code,name,expected", [
    (15700, "", False), (122, "", False),
    (122, "Example.Annotshot_0.3.1.0_x64__abc", True)])
def test_windows_package_api(monkeypatch, code, name, expected):
    calls = []

    def get_name(length, buffer):
        calls.append(buffer)
        if buffer is None:
            ctypes.cast(length, ctypes.POINTER(ctypes.c_uint32)).contents.value = len(name) + 1
            return code
        buffer.value = name
        return 0

    function = Mock(side_effect=get_name)
    dll = Mock(return_value=SimpleNamespace(GetCurrentPackageFullName=function))
    monkeypatch.setattr(packaged, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(ctypes, "WinDLL", dll, raising=False)
    assert packaged.is_packaged() is expected
    dll.assert_called_once_with("kernel32", use_last_error=True)
    assert len(calls) == (1 if code == 15700 else 2)


def test_windows_package_api_error_is_false(monkeypatch):
    monkeypatch.setattr(packaged, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(ctypes, "WinDLL", Mock(side_effect=OSError("unavailable")), raising=False)
    assert packaged.is_packaged() is False


def test_packaged_registration_is_silent_and_never_touches_registry(monkeypatch, capsys):
    registry = Mock()
    monkeypatch.setitem(sys.modules, "winreg", registry)
    monkeypatch.setattr(filetype, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(filetype, "is_packaged", lambda: True)
    assert filetype.register() is None
    assert registry.mock_calls == []
    assert capsys.readouterr().out == ""
    assert capsys.readouterr().err == ""


def test_custom_app_id_is_only_used_unpacked(monkeypatch):
    backend = SimpleNamespace(set_app_id=Mock())
    monkeypatch.setattr(app, "win32", backend)
    monkeypatch.setattr(app, "is_packaged", lambda: True)
    app.set_app_id("Annotshot.Annotshot")
    backend.set_app_id.assert_not_called()
    monkeypatch.setattr(app, "is_packaged", lambda: False)
    app.set_app_id("Annotshot.Annotshot")
    backend.set_app_id.assert_called_once_with("Annotshot.Annotshot")


def test_store_file_type_id_does_not_warn_as_another_program(qapp, monkeypatch):
    from PySide6.QtWidgets import QApplication
    built = []
    monkeypatch.setattr(app, "is_packaged", lambda: True)
    monkeypatch.setattr(filetype, "register", lambda: None)
    monkeypatch.setattr(filetype, "user_choice", lambda: "AppXStoreGeneratedID")
    monkeypatch.setattr(mainwindow.MainWindow, "show", lambda self: built.append(self))
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    assert app.main(["Annotshot.exe"]) == 0
    window = built[0]
    try:
        assert window.statusBar().currentMessage() != app.OTHER_PROGRAM
    finally:
        qapp.removeEventFilter(qapp._annotshot_file_filter)
        window.deleteLater()
        qapp.processEvents()


def test_all_automatic_write_paths_are_in_profile_locations(qapp, tmp_path, monkeypatch, white):
    """Exercise settings, Recent, autosave + atomic temp, exports and receipt.

    Explicit Open/Save paths remain the user's choice. These operations use
    a selected profile folder here, including the exports' adjacent temp.
    """
    profile = tmp_path / "profile"
    data = profile / "AppData" / "Annotshot"
    temp = profile / "Temp"
    data.mkdir(parents=True)
    temp.mkdir()
    locations = {QStandardPaths.AppDataLocation: str(data),
                 QStandardPaths.TempLocation: str(temp)}
    monkeypatch.setattr(QStandardPaths, "writableLocation", locations.__getitem__)
    monkeypatch.setattr(mainwindow, "is_packaged", lambda: True)
    monkeypatch.setattr(entry, "is_packaged", lambda: True)
    ini = data / "settings.ini"
    settings = lambda *a, **k: QSettings(str(ini), QSettings.IniFormat)
    monkeypatch.setattr(mainwindow, "QSettings", settings)
    monkeypatch.setattr(theme, "QSettings", settings)
    window = mainwindow.MainWindow()
    try:
        assert not window.isVisible()
        window.settings.setValue("props/text/font_px", 24)
        window.settings.sync()
        theme.save("Light")
        assert Path(window.settings.fileName()).is_relative_to(data)
        assert mainwindow.default_directory() == data / "Captures"
        assert window.recent_store.folder == data / "Captures/Recent"
        assert window._folder("save").is_relative_to(data)
        window.settings.setValue("last_dir/save", str(profile / "missing"))
        assert window._folder("save").is_relative_to(data)
        assert Path(window._default_path("save", "png")).is_relative_to(data)
        capture = window.recent_store.reserve(QDateTime.currentDateTime())
        window.recent_store.file(white, path=capture)
        editable = recent.editable_for(capture)
        assert editable.is_relative_to(data)
        from annotshot.scene import Document
        document = Document(white)
        document.path = str(editable)
        window._bind(document)
        # Force a generation through the normal autosave entry point.
        from annotshot.items import RectItem
        document.add_items([RectItem()])
        window.autosave_now(end_edit=True)
        recent.writer().waitForDone(5000)
        qapp.processEvents()
        assert editable.is_file()
        assert not Path(str(editable) + ".tmp").exists()
        from annotshot import office
        real_mkstemp = office.tempfile.mkstemp
        temporary_paths = []

        def mkstemp(*args, **kwargs):
            result = real_mkstemp(*args, **kwargs)
            temporary_paths.append(Path(result[1]))
            return result

        monkeypatch.setattr(office.tempfile, "mkstemp", mkstemp)
        office.export_docx(white, str(data / "export.docx"))
        office.export_pptx(white, str(data / "export.pptx"))
        assert len(temporary_paths) == 2
        assert all(path.is_relative_to(data) for path in temporary_paths)
        monkeypatch.setattr(entry, "sys", SimpleNamespace(
            stdout=None, frozen=True, executable=str(tmp_path / "install/Annotshot.exe")))
        entry._say("Annotshot check OK", True)
        assert entry._check_file() == data / "check.txt"
        assert (data / "check.txt").read_text() == "Annotshot check OK\n"
        # Self-check scratch files use the OS temp area, with no install path.
        entry._check_office()
        assert all(path.is_relative_to(profile) for path in temporary_paths)
        assert all(path.is_relative_to(temp) for path in temporary_paths[-2:])
        assert not (tmp_path / "install").exists()
        assert all(path.is_relative_to(profile) for path in profile.rglob("*"))
        monkeypatch.setattr(mainwindow, "is_packaged", lambda: False)
        assert mainwindow.default_directory() == mainwindow.DEFAULT_DIR
        monkeypatch.setattr(entry, "is_packaged", lambda: False)
        assert entry._check_file() == tmp_path / "install/check.txt"
    finally:
        window._autosave_timer.stop()
        recent.writer().waitForDone(5000)
        window.deleteLater()
        qapp.processEvents()


def test_workflow_msix_order_and_outputs():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert workflow.index("- name: Installer (Windows)") < workflow.index("- name: MSIX (Windows)")
    assert workflow.index("- name: MSIX (Windows)") < workflow.index("- name: Zip (Windows)")
    assert "            Annotshot-*.msix\n" in workflow
    assert "            zips/Annotshot-*.msix\n" in workflow
    assert "pack /d build/msix /p" in workflow
    assert workflow.index("$makepri createconfig") < workflow.index("$makepri new")
    assert workflow.index("$makepri new") < workflow.index("$makeappx.FullName pack")
    assert "/of build/msix/resources.pri /o" in workflow
    for name, default in DEFAULTS.items():
        assert f"vars.{name} || '{default}'" in workflow


def add_docx_templates(dist):
    templates = dist / "_internal/docx/templates"
    unpacked = templates / "default-docx-template"
    (unpacked / "_rels").mkdir(parents=True)
    (unpacked / "[Content_Types].xml").write_text("<Types/>")
    (unpacked / "_rels/.rels").write_text("<Relationships/>")
    (templates / "default.docx").write_bytes(b"the template python-docx opens")
    return templates


def test_layout_drops_the_unpacked_template_and_keeps_default_docx(dist, tmp_path):
    add_docx_templates(dist)
    out = tmp_path / "layout"
    assert run_tool(dist, out).returncode == 0
    templates = out / "_internal/docx/templates"
    assert (templates / "default.docx").read_bytes() == b"the template python-docx opens"
    assert not (templates / "default-docx-template").exists()
    assert not [path for path in out.rglob("*") if "[" in path.name]
    assert (dist / "_internal/docx/templates/default-docx-template/[Content_Types].xml").is_file()


def test_any_other_bracketed_name_stops_and_names_the_file(dist, tmp_path):
    (dist / "_internal/odd[1].txt").write_text("a name MakeAppx refuses")
    out = tmp_path / "layout"
    result = run_tool(dist, out)
    assert result.returncode == 1
    assert "STOP" in result.stdout and "_internal/odd[1].txt" in result.stdout
    assert not out.exists()
