# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Annotshot: onedir, windowed (no console), name Annotshot.

Build from the repository root:
    pyinstaller --noconfirm packaging/annotshot.spec
Windows/Linux -> dist/Annotshot/ ; macOS -> dist/Annotshot.app (plus dist/Annotshot/).
The PySide6 plugins (platforms incl. offscreen, imageformats, iconengines
for the SVG icons) are collected by PyInstaller's own PySide6 hooks.
"""
import os
import re
import sys

ROOT = os.path.dirname(SPECPATH)            # the repository root
with open(os.path.join(ROOT, "annotshot", "__init__.py"), encoding="utf-8") as f:
    VERSION = re.search(r'__version__ = "([^"]+)"', f.read()).group(1)


def at(*parts):
    return os.path.join(ROOT, *parts)


# The app finds its icons at <bundle>/annotshot/icons and the window icon at
# <bundle>/annotshot.ico or icon.png (annotshot/app.py: ROOT = package parent).
datas = [
    (at("annotshot", "icons", "*.svg"), os.path.join("annotshot", "icons")),
    (at("annotshot.ico"), "."),
    (at("icon.png"), "."),
]

if sys.platform == "win32":
    icon = at("annotshot.ico")
elif sys.platform == "darwin":
    try:                                    # .png -> .icns needs Pillow
        import PIL  # noqa: F401
        icon = at("icon.png")
    except ImportError:
        icon = None
else:
    icon = None                             # Linux executables carry no icon

a = Analysis(
    [at("packaging", "annotshot_entry.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=["PySide6.QtSvg"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Annotshot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                          # windowed: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Annotshot",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Annotshot.app",
        icon=icon,
        bundle_identifier="com.annotshot.Annotshot",
        info_plist={"NSHighResolutionCapable": True,
                    "CFBundleShortVersionString": VERSION},
    )
