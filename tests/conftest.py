"""Test setup. The normal suite runs Qt offscreen; `-m live` runs on the real
Windows platform (no window is ever shown). The platform is chosen here,
before any test module imports Qt."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def pytest_configure(config):
    if (config.getoption("markexpr") or "").strip() != "live":
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        # The offscreen platform has no fonts of its own; give it Windows'.
        fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        if fonts.is_dir():
            os.environ.setdefault("QT_QPA_FONTDIR", str(fonts))


# Every module of the app that builds a QSettings; each test gets its own.
SETTINGS_MODULES = ("annotshot.mainwindow", "annotshot.theme", "annotshot.capture")


@pytest.fixture(autouse=True)
def private_settings(monkeypatch, tmp_path):
    """No test reads or writes this machine's real Annotshot settings: the
    app's QSettings(...) becomes an ini file in the test's own folder."""
    import importlib
    from PySide6.QtCore import QSettings
    ini = str(tmp_path / "settings.ini")
    for name in SETTINGS_MODULES:
        monkeypatch.setattr(importlib.import_module(name), "QSettings",
                            lambda *a, **k: QSettings(ini, QSettings.IniFormat))
    return ini


@pytest.fixture(scope="session")
def qapp():
    from annotshot.app import collect_on_this_thread
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    collect_on_this_thread(app)
    yield app


@pytest.fixture(autouse=True)
def released_test_mouse_buttons():
    """Retire synthetic presses even when their original widget was closed.

    QTest keeps mouse buttons on the shared application, beyond the lifetime
    of a viewport. A cancelled drag may intentionally leave its last press
    down during the assertion; it must not carry that press into another test.
    """
    yield
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget
    app = QApplication.instance()
    if app is not None and app.mouseButtons() != Qt.NoButton:
        sink = QWidget()
        held = app.mouseButtons()
        for button in Qt.MouseButton:
            if held & button:
                QTest.mouseRelease(sink, button)
        assert app.mouseButtons() == Qt.NoButton
        sink.deleteLater()
        QCoreApplication.sendPostedEvents(sink, QEvent.DeferredDelete)


@pytest.fixture(autouse=True)
def no_failed_write_box(monkeypatch, request):
    """A test must answer the failed-write seam explicitly to ask it."""
    from annotshot.mainwindow import MainWindow

    def unexpected(self, why):
        raise AssertionError(
            f"{request.node.nodeid}: the failed-write box was asked ({why})")

    unexpected.original = MainWindow._ask_failed_write   # for the seam's own test
    monkeypatch.setattr(MainWindow, "_ask_failed_write", unexpected)


@pytest.fixture
def white():
    """A plain white 640x360 base image."""
    from PySide6.QtGui import QColor, QImage
    img = QImage(640, 360, QImage.Format_RGB32)
    img.fill(QColor("#FFFFFF"))
    return img


@pytest.fixture(autouse=True)
def no_system_hotkey(monkeypatch):
    """No test registers a real system-wide key (main() registers the
    capture key): the default hotkey backend is the one that does nothing.
    A test that means the real call makes its backend itself."""
    from annotshot import hotkey
    monkeypatch.setattr(hotkey, "backend_class", lambda: hotkey.NoBackend)


@pytest.fixture(autouse=True)
def private_pictures(monkeypatch, tmp_path):
    """No test writes under this machine's real Pictures folder: the app's
    Pictures/Annotshot (the save folder and the Recent captures beneath it)
    is a folder in the test's own tmp path."""
    from annotshot import mainwindow
    folder = tmp_path / "Pictures" / "Annotshot"
    monkeypatch.setattr(mainwindow, "DEFAULT_DIR", folder)
    yield folder
    from PySide6.QtCore import QThreadPool
    QThreadPool.globalInstance().waitForDone()   # a filing still running


@pytest.fixture(autouse=True)
def light_theme_after():
    """A test that picks Dark or Retro leaves the app in Light again, so the
    next test sees the look it expects."""
    yield
    from annotshot import theme
    if theme.current() != theme.DEFAULT:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            theme.apply(app, theme.DEFAULT)
