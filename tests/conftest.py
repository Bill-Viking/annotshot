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
SETTINGS_MODULES = ("annotshot.mainwindow",)


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
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def white():
    """A plain white 640x360 base image."""
    from PySide6.QtGui import QColor, QImage
    img = QImage(640, 360, QImage.Format_RGB32)
    img.fill(QColor("#FFFFFF"))
    return img
