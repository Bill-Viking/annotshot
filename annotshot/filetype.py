"""The editable file type: a double-click on a .annotshot file opens the app.

Windows: at every start the app writes its own per-user registration under
HKEY_CURRENT_USER (no installer, no admin), reading first and writing only
what differs, so a moved folder or a new version never leaves a dead file
type. Every error is swallowed: a start never fails on the registry.
Packaged Windows apps use the manifest's association and write nothing.
macOS: the bundle's Info.plist declares the type (packaging/annotshot.spec)
and the app answers Qt's FileOpen event (annotshot/app.py). Linux: the file
as the command-line argument.
"""
from __future__ import annotations

import os
import sys

from .scene import FORMAT, LEGACY_FORMATS
from .packaged import is_packaged

PROGID = "Annotshot.Editable"
PROGID_NAME = "Annotshot editable file"
APP_EXE = "Annotshot.exe"
EXTENSIONS = tuple("." + f for f in (FORMAT, *LEGACY_FORMATS))
USER_CHOICE = ("Software\\Microsoft\\Windows\\CurrentVersion\\Explorer"
               "\\FileExts\\.annotshot\\UserChoice")
SHCNE_ASSOCCHANGED = 0x08000000


def is_editable_file(path: str) -> bool:
    """An existing file whose name ends in one of the editable extensions."""
    return path.lower().endswith(EXTENSIONS) and os.path.isfile(path)


def command_for(frozen: bool, executable: str, root: str) -> tuple[str, str]:
    """(the shell open command, the DefaultIcon value) for this install.

    Frozen: the exe itself, its own icon. From source: pythonw beside the
    running interpreter (the venv's) runs Annotshot.pyw in `root`; with no
    pythonw there, the interpreter itself; the icon is root's annotshot.ico,
    in the same quoted "path",0 shape as the exe's.
    ASSUMES: a source run's interpreter folder holds pythonw.exe (a venv
    does); the opposite case falls back to the interpreter (a console).
    """
    if frozen:
        return f'"{executable}" "%1"', f'"{executable}",0'
    pythonw = os.path.join(os.path.dirname(executable), "pythonw.exe")
    runner = pythonw if os.path.isfile(pythonw) else executable
    script = os.path.join(root, "Annotshot.pyw")
    icon = os.path.join(root, "annotshot.ico")
    return f'"{runner}" "{script}" "%1"', f'"{icon}",0'


def plan(frozen: bool, executable: str,
         root: str) -> list[tuple[str, str, str]]:
    """Everything register() writes, as (subkey under the hive, value name
    — "" is the default, value). Pure, so it is tested on every system.

    Frozen: the ProgID plus an Applications\\Annotshot.exe entry, which
    names the exe Explorer actually runs. From source the open command runs
    pythonw, so an Annotshot.exe entry would point at nothing: the ProgID is
    the only entry, and its open verb carries the name "Annotshot" so the
    Open-with list does not say "Python".
    """
    command, icon = command_for(frozen, executable, root)
    rows = []
    for ext in EXTENSIONS:
        rows += [(ext, "", PROGID),
                 (f"{ext}\\OpenWithProgids", PROGID, "")]
    rows += [(PROGID, "", PROGID_NAME),
             (f"{PROGID}\\DefaultIcon", "", icon),
             (f"{PROGID}\\shell\\open\\command", "", command)]
    if not frozen:
        rows.append((f"{PROGID}\\shell\\open", "FriendlyAppName", "Annotshot"))
        return rows
    rows += [(f"Applications\\{APP_EXE}", "FriendlyAppName", "Annotshot"),
             (f"Applications\\{APP_EXE}\\shell\\open\\command", "", command)]
    rows += [(f"Applications\\{APP_EXE}\\SupportedTypes", ext, "")
             for ext in EXTENSIONS]
    return rows


def is_ours(choice: str | None) -> bool:
    """True when Explorer's own choice for .annotshot is Annotshot: the
    ProgID, or the Applications\\Annotshot.exe entry (what Explorer writes
    when the user picks Annotshot under Open with)."""
    if not choice:
        return False
    return choice.lower() in (PROGID.lower(),
                              f"Applications\\{APP_EXE}".lower())


def _root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def register(hive_path: str = "Software\\Classes") -> str | None:
    """Windows only: write the file type under HKCU\\<hive_path>.

    "written" when anything changed (and Explorer was told), "same" when all
    was already in place, None elsewhere or on any error (nothing raised).
    """
    if sys.platform != "win32" or is_packaged():
        return None
    try:
        import winreg
        wrote = False
        for sub, name, value in plan(bool(getattr(sys, "frozen", False)),
                                     sys.executable, _root()):
            key_path = f"{hive_path}\\{sub}"
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
                    current, kind = winreg.QueryValueEx(k, name)
                if current == value and kind == winreg.REG_SZ:
                    continue
            except OSError:
                pass                    # the key or the value is missing
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0,
                                    winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
            wrote = True
        if wrote:
            try:
                import ctypes
                ctypes.windll.shell32.SHChangeNotify(
                    SHCNE_ASSOCCHANGED, 0, None, None)
            except Exception:           # noqa: BLE001 - a notice, not a need
                pass
        return "written" if wrote else "same"
    except Exception:                   # noqa: BLE001 - never fail a start
        return None


def user_choice() -> str | None:
    """The ProgId Explorer's own choice names for .annotshot, or None."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, USER_CHOICE) as k:
            value, _ = winreg.QueryValueEx(k, "ProgId")
        return str(value) or None
    except Exception:                   # noqa: BLE001 - absent is normal
        return None
