r"""Make annotshot.ico from icon.png with Qt's ICO writer.

Run from anywhere:  .venv\Scripts\python tools\make_icon.py
(Qt's writer stores one image, at icon.png's own size.)"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(src: Path = ROOT / "icon.png", dst: Path = ROOT / "annotshot.ico") -> int:
    from PySide6.QtGui import QGuiApplication, QImage, QImageWriter
    app = QGuiApplication.instance() or QGuiApplication(
        ["make_icon", "-platform", "offscreen"])
    img = QImage(str(src))
    if img.isNull():
        print(f"STOP: cannot read {src}")
        return 1
    if max(img.width(), img.height()) > 256:      # the ICO limit
        img = img.scaled(256, 256)
    writer = QImageWriter(str(dst), b"ico")
    if not writer.write(img):
        print(f"STOP: {writer.errorString()}")
        return 1
    check = QImage(str(dst))
    print(f"OK: {dst} ({check.width()}x{check.height()})")
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
