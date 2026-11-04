"""Starting the app: Annotshot.pyw finds the folder's own virtual
environment when the system's Python has no PySide6, and the frozen
self-check writes check.txt only when there is no console to print to."""
import io
import os
import runpy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def pyw():
    """Annotshot.pyw's functions, without starting the app."""
    return runpy.run_path(str(ROOT / "Annotshot.pyw"), run_name="not_main")


@pytest.mark.parametrize("platform,parts", [
    ("win32", (".venv", "Scripts", "pythonw.exe")),
    ("darwin", (".venv", "bin", "python")),
    ("linux", (".venv", "bin", "python"))])
def test_the_venv_interpreter_beside_the_file_is_started(pyw, platform,
                                                         parts):
    here = os.path.join(os.sep, "repo")
    target = os.path.join(here, *parts)
    found = pyw["venv_interpreter"](here, platform, "/usr/bin/pythonw", False,
                                    isfile=lambda p: p == target)
    assert found == target


def test_no_restart_when_the_venv_is_already_running(pyw):
    here = os.path.join(os.sep, "repo")
    target = os.path.join(here, ".venv", "bin", "python")
    assert pyw["venv_interpreter"](here, "darwin", target, False,
                                   isfile=lambda p: True) is None


def test_no_restart_without_a_venv(pyw):
    assert pyw["venv_interpreter"](os.sep + "repo", "win32",
                                   r"C:\Python\pythonw.exe", False,
                                   isfile=lambda p: False) is None


def test_no_second_restart(pyw):
    """The restarted interpreter that still lacks PySide6 stops there."""
    assert pyw["venv_interpreter"](os.sep + "repo", "darwin", "/usr/bin/python",
                                   True, isfile=lambda p: True) is None


def test_the_pyw_runs_the_app_from_this_folder():
    import subprocess
    out = subprocess.run([sys.executable, str(ROOT / "Annotshot.pyw"),
                          "--version"], capture_output=True, text=True,
                         timeout=60)
    from annotshot import __version__
    assert out.returncode == 0 and out.stdout.strip() == __version__


def _say_frozen(monkeypatch, tmp_path, stdout):
    from annotshot import __main__ as entry
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Annotshot"))
    monkeypatch.setattr(sys, "stdout", stdout)
    entry._say("Annotshot 0.0.0 OK", True)
    return tmp_path / "check.txt"


def test_check_txt_is_not_written_beside_a_frozen_app_with_a_stdout(
        monkeypatch, tmp_path):
    """macOS: writing inside Annotshot.app would break its signature."""
    out = io.StringIO()
    assert not _say_frozen(monkeypatch, tmp_path, out).exists()
    assert out.getvalue() == "Annotshot 0.0.0 OK\n"


def test_check_txt_is_written_when_there_is_no_stdout(monkeypatch, tmp_path):
    """A windowed Windows exe has no console: the file is the only way."""
    check = _say_frozen(monkeypatch, tmp_path, None)
    assert check.read_text(encoding="utf-8") == "Annotshot 0.0.0 OK\n"


# -- s2 polish -----------------------------------------------------------------------
class _Broken(io.TextIOBase):
    def __init__(self, error):
        self.error = error

    def write(self, s):
        raise self.error


@pytest.mark.parametrize("error", [OSError(9, "Bad file descriptor"),
                                   ValueError("I/O operation on closed file")])
def test_check_txt_is_written_when_the_stdout_refuses_the_line(
        monkeypatch, tmp_path, error):
    """A stdout that is there but broken never loses the verdict."""
    check = _say_frozen(monkeypatch, tmp_path, _Broken(error))
    assert check.read_text(encoding="utf-8") == "Annotshot 0.0.0 OK\n"


def test_the_failure_line_uses_the_three_argument_traceback(monkeypatch):
    """Pythons before 3.10 take only format_exception(type, value, tb)."""
    import traceback
    from annotshot import __main__ as entry
    real = traceback.format_exception

    def old_style(etype, value, tb):
        return real(etype, value, tb)
    monkeypatch.setattr(traceback, "format_exception", old_style)

    def broken():
        raise RuntimeError("the parts are missing")
    monkeypatch.setattr(entry, "_check_office", broken)
    said = []
    monkeypatch.setattr(entry, "_say", lambda line, to_file=False:
                        said.append(line))
    assert entry.check() == 1
    assert said[-1].startswith("Annotshot ")
    assert " FAILED: Traceback" in said[-1]
    assert said[-1].endswith("RuntimeError: the parts are missing")


def test_no_qt_says_so_in_a_message_box_on_windows(pyw):
    shown, err = [], io.StringIO()
    rc = pyw["say_no_qt"]("win32", message_box=lambda *a: shown.append(a),
                          stderr=err, console=False)
    assert rc == 1 and err.getvalue() == ""
    assert len(shown) == 1
    owner, text, title, flags = shown[0]
    assert owner is None and title == "Annotshot"
    assert text.startswith("Annotshot cannot start: Qt for Python is not "
                           "installed for this Python.")


def test_no_qt_falls_back_to_one_line_when_the_box_fails(pyw):
    err = io.StringIO()

    def no_box(*a):
        raise OSError("no user32")
    assert pyw["say_no_qt"]("win32", message_box=no_box, stderr=err,
                            console=False) == 1
    assert err.getvalue().count("\n") == 1


def test_no_qt_names_the_venv_when_it_is_there(pyw, tmp_path):
    """A folder with its own virtual environment but no Qt in it is told to
    install into it, not to make one."""
    here = str(tmp_path)
    assert pyw["no_qt_text"](here, "darwin", isfile=lambda p: False) == pyw["NO_QT"]
    assert pyw["no_qt_text"](here, "darwin", isfile=lambda p: True) == pyw["NO_QT_IN_VENV"]
    assert pyw["no_qt_text"](here, "win32", isfile=lambda p: p.endswith(
        os.path.join(".venv", "Scripts", "pythonw.exe"))) == pyw["NO_QT_IN_VENV"]
    err = io.StringIO()
    assert pyw["say_no_qt"]("darwin", stderr=err, text=pyw["NO_QT_IN_VENV"]) == 1
    assert "virtual environment" in err.getvalue()


def test_no_qt_prints_instead_of_a_box_when_there_is_a_console(pyw):
    """Started from a console on Windows, the line is printed; no box waits
    for a click that never comes."""
    shown, err = [], io.StringIO()
    rc = pyw["say_no_qt"]("win32", message_box=lambda *a: shown.append(a),
                          stderr=err, console=True)
    assert rc == 1 and shown == []
    assert err.getvalue().startswith("Annotshot cannot start")


def test_a_pyw_without_qt_or_a_venv_says_so_and_exits_1():
    """No site-packages (so no PySide6) and the venv already tried: one
    plain line on stderr, never a traceback."""
    import subprocess
    env = dict(os.environ, ANNOTSHOT_STARTED_FROM_PYW="1")
    out = subprocess.run([sys.executable, "-S", str(ROOT / "Annotshot.pyw")],
                         capture_output=True, text=True, timeout=60, env=env)
    assert out.returncode == 1
    assert out.stdout == ""
    assert out.stderr.startswith("Annotshot cannot start: Qt for Python")
    assert "Traceback" not in out.stderr
    assert out.stderr.count("\n") == 1
