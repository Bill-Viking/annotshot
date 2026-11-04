"""`python -m annotshot` starts the app.

    --version   print the version and exit 0
    --check     headless self-check: build the QApplication and the main
                window offscreen (never shown), print "Annotshot <version> OK"
                and exit 0; any exception is printed and exits 1
"""
import os
import sys
from pathlib import Path


def _say(line: str, to_file: bool = False) -> None:
    """Print a line where it can be read. A windowed (no console) frozen exe
    may have no stdout, so the frozen app also writes check.txt beside the
    exe."""
    if sys.stdout is not None:
        try:
            print(line, flush=True)
        except OSError:
            pass
    if to_file and getattr(sys, "frozen", False):
        try:
            (Path(sys.executable).resolve().parent / "check.txt").write_text(
                line + "\n", encoding="utf-8")
        except OSError:
            pass


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
    except BaseException as exc:            # noqa: BLE001 - report anything
        import traceback
        _say(f"Annotshot {__version__} FAILED: "
             + "".join(traceback.format_exception(exc)).strip(), True)
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
    return main()


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
