"""The fonts Annotshot carries: one pixel font, VT323 (Peter Hull, SIL Open
Font License 1.1, its text in licenses/OFL-VT323.txt), loaded into Qt's font
database at start so a text box set to it looks the same on every system.
"""
from __future__ import annotations

import sys
from pathlib import Path

# (file in the fonts folder, the family it holds, the Font box's tooltip)
BUNDLED = (("VT323-Regular.ttf", "VT323", "Pixel font (bundled)"),)
LICENCE = "OFL-VT323.txt"

_loaded: dict[str, str] = {}            # file name -> the family Qt read


def public_families() -> list[str]:
    """Installed families that can be offered as annotation fonts."""
    from PySide6.QtGui import QFontDatabase
    return [f for f in QFontDatabase.families()
            if not f.startswith(".") and not QFontDatabase.isPrivateFamily(f)]


def text_family() -> str:
    """A public annotation font; the interface may use a private system face."""
    families = public_families()
    if sys.platform == "darwin":
        for family in ("Helvetica Neue", "Arial"):
            if family in families:
                return family
    else:
        family = interface_family()
        if family in families:
            return family
    if families:
        return families[0]
    raise RuntimeError("No public installed or bundled font is available")


def interface_family() -> str:
    """An actual installed family for the ordinary UI.

    ASSUMES: Qt can read the system interface font. If it cannot, choose
    an installed fallback instead of naming a font this machine lacks.
    """
    from PySide6.QtGui import QFontDatabase, QFontInfo
    families = QFontDatabase.families()
    if sys.platform == "win32" and "Segoe UI" in families:
        return "Segoe UI"
    try:
        system = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
        for family in (system.family(), QFontInfo(system).family()):
            if family in families:
                return family
    except (RuntimeError, AttributeError):
        pass
    for family in ("Helvetica Neue", "Arial", "DejaVu Sans", "Liberation Sans"):
        if family in families:
            return family
    if families:
        return families[0]
    raise RuntimeError("No installed or bundled font is available")


def font_folder() -> Path:
    """annotshot/fonts: under the frozen app's root in a build (the spec
    lays it there), the package folder otherwise.
    ASSUMES: a frozen build lays the fonts at <root>/annotshot/fonts, as
    packaging/annotshot.spec says; check_fonts() is where that is false."""
    if getattr(sys, "frozen", False):
        from .__main__ import app_root
        return app_root() / "annotshot" / "fonts"
    return Path(__file__).resolve().parent / "fonts"


def _add(path: Path) -> str | None:
    """Add one font file to Qt's database; the family it holds, or None."""
    from PySide6.QtGui import QFontDatabase
    if not path.is_file():
        return None
    fid = QFontDatabase.addApplicationFont(str(path))
    families = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
    return families[0] if families else None


def load_bundled(folder: Path | None = None) -> list[str]:
    """Add the bundled fonts to Qt's font database (once per file); returns
    the families that are in it. A missing or broken file is skipped: the
    Font box then simply has no bundled entry. Needs a QGuiApplication."""
    folder = folder or font_folder()
    for name, _family, _tip in BUNDLED:
        if name not in _loaded:
            family = _add(folder / name)
            if family:
                _loaded[name] = family
    return bundled_families()


def bundled_families() -> list[str]:
    """The bundled families that are loaded now, in BUNDLED's order."""
    return [_loaded[name] for name, _f, _t in BUNDLED if name in _loaded]


def tooltip(family: str) -> str | None:
    for name, fam, tip in BUNDLED:
        if _loaded.get(name) == family or fam == family:
            return tip
    return None


def check_fonts(folder: Path | None = None) -> list[str]:
    """For --check: every bundled font is in `folder` and loads under its
    own family name (read from the file itself, never from the cache);
    raises naming the first one that does not."""
    folder = folder or font_folder()
    found = []
    for name, family, _tip in BUNDLED:
        if not (folder / name).is_file():
            raise RuntimeError(f"the font annotshot/fonts/{name} is missing "
                               "from the app")
        if _add(folder / name) != family:
            raise RuntimeError(f"the font {name} did not load as {family}")
        found.append(family)
    return found
