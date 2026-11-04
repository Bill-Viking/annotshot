"""Live proofs on the real Windows platform (check 1, and the clipboard half
of check 6). No window is shown. Run with:
    .venv\\Scripts\\python -m pytest -q -m live tests\\test_live_windows.py
The clipboard test runs last and leaves a 640x360 picture on the clipboard
for `Get-Clipboard -Format Image` to read back."""
import ctypes
import os

import pytest
from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QGuiApplication, QImage

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("QT_QPA_PLATFORM") == "offscreen",
                       reason="live: needs the real platform (-m live)"),
]


def test_every_screen_grabs_at_device_pixels(qapp):
    from annotshot.capture import grab_all_screens
    grabs = grab_all_screens()
    assert grabs and len(grabs) == len(QGuiApplication.screens())
    for g in grabs:
        logical, dpr = g.screen.size(), g.screen.devicePixelRatio()
        expected = QSize(round(logical.width() * dpr), round(logical.height() * dpr))
        print(f"{g.screen.name()}: {logical.width()}x{logical.height()} x {dpr}"
              f" -> {g.image.width()}x{g.image.height()}, monitor {g.phys}")
        assert g.image.size() == expected
        assert g.image.devicePixelRatio() == 1.0 and not g.image.isNull()
        assert g.phys.size() == g.image.size()
        assert abs(g.scale - dpr) < 0.01


def test_monitors_cover_every_screen(qapp):
    from annotshot import win32
    mons = win32.monitors()
    assert mons and all(name.startswith("\\\\.\\DISPLAY") for name in mons)
    assert len(mons) == len(QGuiApplication.screens())


def test_list_windows_has_titled_windows_with_bounds(qapp):
    from annotshot import win32
    wins = win32.list_windows()
    assert any(w.title.strip() and not w.rect.isEmpty() for w in wins)
    assert all(w.title.strip() and w.rect.width() > 0 for w in wins)


def _uncovered_point(target, above):
    """A point inside target's bounds that no window above it covers."""
    r = target.rect
    for fy in (0.5, 0.25, 0.75, 0.1, 0.9):
        for fx in (0.5, 0.25, 0.75, 0.1, 0.9):
            p = QPoint(r.x() + int(r.width() * fx), r.y() + int(r.height() * fy))
            if not any(w.rect.contains(p) for w in above):
                return p
    return None


def test_window_under_point_finds_the_console_window(qapp):
    from annotshot import win32
    wins = win32.list_windows()
    console = win32.console_window()
    hwnds = [w.hwnd for w in wins]
    if console in hwnds:
        target, label = wins[hwnds.index(console)], "console"
    else:   # no visible console (run from a tool): the topmost window
        target, label = wins[0], "topmost"
    idx = hwnds.index(target.hwnd)
    p = _uncovered_point(target, wins[:idx])
    if p is None:
        pytest.skip(f"the {label} window is fully covered by windows above it")
    print(f"{label} window {target.title!r} {target.rect} at {p.x()},{p.y()}")
    found = win32.window_under_point(p.x(), p.y())
    assert found is not None and found.hwnd == target.hwnd
    assert win32.window_under_point(p.x(), p.y(), exclude={target.hwnd},
                                    windows=[target]) is None


def test_clipboard_holds_the_rendered_picture(qapp, white):
    from annotshot.items import RectItem, TextBoxItem
    from annotshot.scene import Document
    doc = Document(white)
    t = TextBoxItem()
    t.apply_props({"text": "Annotshot clipboard check", "fill_color": "#0000FF",
                   "text_color": "#FFFFFF"})
    t.set_geom((40, 40, 360, 60))
    r = RectItem()
    r.set_geom((420, 40, 160, 100))
    doc.add_items([t, r])
    img = doc.render_image()
    cb = QGuiApplication.clipboard()
    cb.setImage(img)
    back = cb.image()
    assert back.size() == img.size() == QSize(640, 360)
    fmt = QImage.Format_RGB32
    assert back.convertToFormat(fmt) == img.convertToFormat(fmt)
    user32 = ctypes.WinDLL("user32")
    CF_DIB = 8
    assert user32.IsClipboardFormatAvailable(CF_DIB)
    print("clipboard image 640x360 (read it back: Get-Clipboard -Format Image)")
