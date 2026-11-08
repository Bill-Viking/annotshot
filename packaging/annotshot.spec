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

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

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
# The Word / PowerPoint libraries open their own blank document and
# presentation (and their default XML parts) from package data files.
datas += collect_data_files("docx") + collect_data_files("pptx")

# The licence texts ride inside the app. Qt is bundled as separate libraries
# under the LGPL, which asks that its notice and licence text travel with it:
# the two GNU texts go into licenses/ (the frozen --check looks for them).
datas += [
    (at("packaging", "licenses", "LGPL-3.0.txt"), "licenses"),
    (at("packaging", "licenses", "GPL-3.0.txt"), "licenses"),
]
# The bundled pixel font (VT323, SIL Open Font License 1.1) and its licence,
# which travels with it (the frozen --check looks for both).
datas += [
    (at("annotshot", "fonts", "VT323-Regular.ttf"), os.path.join("annotshot", "fonts")),
    (at("packaging", "licenses", "OFL-VT323.txt"), "licenses"),
]
# The user manual Help shows (the frozen --check looks for it).
datas += [(at("docs", "USER-MANUAL.md"), "docs")]
# The project's own licence and the third-party notices sit at the bundle's
# root when the repository has them (the public repository does; a copy
# without them builds without them).
for name in ("LICENSE", "THIRD-PARTY-NOTICES.md"):
    if os.path.isfile(at(name)):
        datas.append((at(name), "."))
# Every bundled library's own metadata folder, with the licence files it
# ships, rides along too.
for dist in ("PySide6-Essentials", "shiboken6", "python-docx", "python-pptx",
             "lxml", "pillow", "typing_extensions", "xlsxwriter"):
    datas += copy_metadata(dist)

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
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": VERSION,
            # The editable file: Finder opens a .annotshot file in the app.
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "Annotshot editable file",
                "CFBundleTypeRole": "Editor",
                "LSHandlerRank": "Owner",
                "LSItemContentTypes": ["com.annotshot.editable"],
            }],
            "UTExportedTypeDeclarations": [{
                "UTTypeIdentifier": "com.annotshot.editable",
                "UTTypeDescription": "Annotshot editable file",
                "UTTypeConformsTo": ["public.zip-archive", "public.data"],
                "UTTypeTagSpecification": {
                    "public.filename-extension": ["annotshot"]},
            }],
        },
    )
