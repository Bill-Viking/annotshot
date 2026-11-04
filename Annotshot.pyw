"""Annotshot from the source folder, no console: pythonw Annotshot.pyw [file]

A double-click on this file runs the system's pythonw, which may not have
PySide6. Then, when the folder's own virtual environment is there, that
interpreter is started instead, with the same arguments; when there is none
either, a plain message says so (pythonw has no console to show an error)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TRIED = "ANNOTSHOT_STARTED_FROM_PYW"    # set once, so it never loops


def venv_path(here, platform):
    """Where the folder's own virtual environment keeps its interpreter."""
    if platform == "win32":
        return os.path.join(here, ".venv", "Scripts", "pythonw.exe")
    return os.path.join(here, ".venv", "bin", "python")


def venv_interpreter(here, platform, running, tried, isfile=os.path.isfile):
    """The interpreter of the virtual environment beside this file, when it
    is there, is not the one running, and has not been tried; else None."""
    if tried:
        return None
    target = venv_path(here, platform)
    if not isfile(target):
        return None
    same = (os.path.normcase(os.path.abspath(target))
            == os.path.normcase(os.path.abspath(running or "")))
    return None if same else target


NO_QT = ("Annotshot cannot start: Qt for Python is not installed for this "
         "Python. Make the virtual environment in the Annotshot folder, as "
         "the manual's \"From the source code\" says, then start Annotshot "
         "again.")
NO_QT_IN_VENV = ("Annotshot cannot start: Qt for Python is not installed in "
                 "the Annotshot folder's virtual environment. Install the "
                 "packages into it, as the manual's \"From the source code\" "
                 "says, then start Annotshot again.")


def no_qt_text(here, platform, isfile=os.path.isfile):
    """The message for a start without Qt: install into the folder's virtual
    environment when it is there, else make one."""
    return NO_QT_IN_VENV if isfile(venv_path(here, platform)) else NO_QT


def say_no_qt(platform=None, message_box=None, stderr=None, text=None,
              console=None):
    """Tell the user that PySide6 is missing: a message box on Windows when
    there is no console (a double-clicked pythonw shows nothing else); one
    line on stderr otherwise. Returns the exit code, 1."""
    platform = sys.platform if platform is None else platform
    text = NO_QT if text is None else text
    if console is None:
        console = sys.stderr is not None        # pythonw has no stderr
    if platform == "win32" and not console:
        try:
            if message_box is None:
                import ctypes
                message_box = ctypes.windll.user32.MessageBoxW
            message_box(None, text, "Annotshot", 0x10)   # MB_ICONERROR
            return 1
        except Exception:               # noqa: BLE001 - fall back to stderr
            pass
    stream = sys.stderr if stderr is None else stderr
    if stream is not None:
        try:
            print(text, file=stream, flush=True)
        except (OSError, ValueError):
            pass
    return 1


def _start():
    sys.path.insert(0, HERE)
    try:
        import PySide6  # noqa: F401 - only asks whether it is there
    except ImportError:
        target = venv_interpreter(HERE, sys.platform, sys.executable,
                                  bool(os.environ.get(TRIED)))
        if target is not None:
            args = [target, os.path.abspath(__file__), *sys.argv[1:]]
            env = dict(os.environ, **{TRIED: "1"})
            if sys.platform == "win32":
                import subprocess
                raise SystemExit(subprocess.call(args, env=env))
            os.execve(target, args, env)
        raise SystemExit(say_no_qt(text=no_qt_text(HERE, sys.platform)))
    from annotshot.__main__ import run
    raise SystemExit(run(sys.argv[1:]))


if __name__ == "__main__":
    _start()
