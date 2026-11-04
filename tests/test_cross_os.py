"""Cross-OS guard and the headless self-check. Off Windows, annotshot.capture
must import without annotshot.win32 and give a region-only capture; the
`--check` entry builds the app offscreen and prints "Annotshot <version> OK"."""
import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage
from PySide6.QtTest import QTest

import annotshot

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def capture_as_darwin(monkeypatch):
    """annotshot.capture imported fresh with sys.platform == "darwin". The
    annotshot.win32 entry is set to None, so any import of it raises. The real
    module is imported first, so teardown puts it back for the other tests."""
    importlib.import_module("annotshot.capture")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "annotshot.win32", None)
    monkeypatch.delitem(sys.modules, "annotshot.capture")
    for name in ("capture", "win32"):
        if hasattr(annotshot, name):
            monkeypatch.setattr(annotshot, name, getattr(annotshot, name))
    mod = importlib.import_module("annotshot.capture")
    yield mod


def test_capture_imports_on_macos_without_win32(qapp, capture_as_darwin):
    cap = capture_as_darwin
    assert not cap.IS_WINDOWS and cap.win32 is None
    assert sys.modules["annotshot.win32"] is None      # never imported


def test_region_only_capture_off_windows(qapp, capture_as_darwin):
    cap = capture_as_darwin
    grabs = cap.grab_all_screens()                  # QScreen.grabWindow(0)
    assert len(grabs) == len(QGuiApplication.screens())
    for g in grabs:
        geo, dpr = g.screen.geometry(), g.screen.devicePixelRatio()
        assert g.phys == QRect(round(geo.x() * dpr), round(geo.y() * dpr),
                               round(geo.width() * dpr),
                               round(geo.height() * dpr))

    img = QImage(1920, 1200, QImage.Format_RGB32)
    img.fill(QColor("#336699"))
    grab = cap.ScreenGrab(QGuiApplication.primaryScreen(), img,
                          QRect(0, 0, 1280, 800), 1.5,
                          QRect(0, 0, 1920, 1200))
    ov = cap.CaptureOverlay(grab, [])
    results = []
    ov.picked.connect(results.append)
    a, b = QPoint(100, 100), QPoint(300, 200)       # a drag: the region
    QTest.mousePress(ov, Qt.LeftButton, Qt.NoModifier, a)
    QTest.mouseMove(ov, QPoint(200, 150))
    QTest.mouseMove(ov, b)
    QTest.mouseRelease(ov, Qt.LeftButton, Qt.NoModifier, b)
    region = results.pop()
    assert region.image.size().toTuple() == (300, 150) and region.title is None
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(400, 300))
    whole = results.pop()                           # a click: the whole screen
    assert whole.image.size().toTuple() == (1920, 1200) and whole.title is None
    QTest.keyClick(ov, Qt.Key_Escape)
    assert results == [None]
    ov.deleteLater()


def test_set_app_id_is_a_no_op_off_windows(monkeypatch):
    from annotshot import app
    monkeypatch.setattr(app, "win32", None)
    app.set_app_id("Annotshot.Annotshot")                 # nothing to call, no error


def _run(*args):
    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)                # --check sets it itself
    return subprocess.run([sys.executable, "-m", "annotshot", *args], cwd=ROOT,
                          env=env, capture_output=True, text=True,
                          timeout=120)


def test_check_entry_prints_ok():
    done = _run("--check")
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.strip() == f"Annotshot {annotshot.__version__} OK"
    assert annotshot.__version__ == "0.1.2"


def test_version_entry_prints_the_version():
    done = _run("--version")
    assert done.returncode == 0 and done.stdout.strip() == "0.1.2"
