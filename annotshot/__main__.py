"""`python -m annotshot` starts the app.

    --version   print the version and exit 0
    --check     headless self-check: build the QApplication and the main
                window offscreen (never shown), save a small picture as Word
                and PowerPoint and re-open both; a frozen app also finds its
                licence texts; print "Annotshot <version> OK"
                and exit 0; any exception is printed and exits 1
    <file>      an editable file (.annotshot) opens in the window
"""
import os
import sys
from pathlib import Path


def _say(line: str, to_file: bool = False) -> None:
    """Print a line where it can be read. A windowed (no console) frozen
    exe on Windows has no stdout, so only then does the frozen app write
    check.txt beside the exe; with a working stdout (always on macOS and
    Linux) it writes nothing, so a signed macOS bundle is never changed. A
    stdout that is there but refuses the line counts as none, so the
    verdict is never lost."""
    printed = False
    if sys.stdout is not None:
        try:
            print(line, flush=True)
            printed = True
        except (OSError, ValueError):   # a closed or broken stdout
            pass
    if to_file and not printed and getattr(sys, "frozen", False):
        try:
            (Path(sys.executable).resolve().parent / "check.txt").write_text(
                line + "\n", encoding="utf-8")
        except OSError:
            pass


def _check_office() -> None:
    """Save a 4x4 picture as Word and PowerPoint in a scratch folder and
    re-open each: proves the two libraries (and their own data files) ride
    with the app."""
    import tempfile
    from PySide6.QtGui import QColor, QImage
    from docx import Document
    from pptx import Presentation
    from annotshot.office import export_docx, export_pptx
    img = QImage(4, 4, QImage.Format_ARGB32)
    img.fill(QColor("#0878D5"))
    with tempfile.TemporaryDirectory() as tmp:
        docx_path, pptx_path = f"{tmp}/check.docx", f"{tmp}/check.pptx"
        export_docx(img, docx_path)
        export_pptx(img, pptx_path)
        if len(Document(docx_path).inline_shapes) != 1:
            raise RuntimeError("the Word export holds no picture")
        prs = Presentation(pptx_path)
        pictures = [s for slide in prs.slides for s in slide.shapes
                    if s.shape_type == 13]          # MSO_SHAPE_TYPE.PICTURE
        if len(pictures) != 1:
            raise RuntimeError("the PowerPoint export holds no picture")


LICENCE_TEXTS = ("LGPL-3.0.txt", "GPL-3.0.txt")


def _check_licences(root: Path) -> int:
    """In a frozen app, the two GNU licence texts must sit in <root>/licenses
    (the LGPL asks that Qt's licence text travel with it). Returns how many
    licence files the app carries; raises naming the first missing text."""
    folder = root / "licenses"
    for name in LICENCE_TEXTS:
        if not (folder / name).is_file():
            raise RuntimeError(
                f"the licence text licenses/{name} is missing from the app")
    found = [p for p in folder.iterdir() if p.is_file()]
    found += [root / n for n in ("LICENSE", "THIRD-PARTY-NOTICES.md")
              if (root / n).is_file()]
    found += [p for p in root.glob("*.dist-info/**/*")
              if p.is_file() and p.name.upper().startswith(("LICEN", "COPYING"))]
    return len(found)


def check() -> int:
    """Build the app and the main window offscreen; never show a window."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"   # before Qt loads
    if sys.platform == "win32":
        fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        if fonts.is_dir():
            os.environ.setdefault("QT_QPA_FONTDIR", str(fonts))
    from annotshot import __version__
    try:
        from annotshot.app import make_app
        from annotshot.mainwindow import MainWindow
        app = make_app([sys.argv[0]])
        window = MainWindow()
        if window.isVisible():
            raise RuntimeError("the main window was shown")
        window.deleteLater()
        app.processEvents()
        _check_office()
        _say("office export OK")
        if getattr(sys, "frozen", False):
            n = _check_licences(Path(getattr(sys, "_MEIPASS",
                                             Path(sys.executable).parent)))
            _say(f"licences OK ({n} files)")
    except BaseException as exc:            # noqa: BLE001 - report anything
        import traceback
        _say(f"Annotshot {__version__} FAILED: "
             + "".join(traceback.format_exception(
                 type(exc), exc, exc.__traceback__)).strip(), True)
        return 1
    _say(f"Annotshot {__version__} OK", True)
    return 0


def run(argv: list[str]) -> int:
    if "--version" in argv:
        from annotshot import __version__
        _say(__version__)
        return 0
    if "--check" in argv:
        return check()
    from annotshot.app import main
    return main([sys.argv[0], *argv])   # a file argument opens that file


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
