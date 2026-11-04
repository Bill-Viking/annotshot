# Third-party notices

Annotshot's own code, its toolbar icons (`annotshot/icons/*.svg`) and its app
icon (`annotshot.ico`, `icon.png`, `docs/icon.svg`) are the project's own work,
under the MIT licence in `LICENSE`.

## Qt for Python (PySide6, Shiboken6) and Qt 6

Annotshot is built on **Qt for Python** (the `PySide6-Essentials` and
`shiboken6` packages, version 6.12.0) and the **Qt 6** libraries they carry,
by The Qt Company. They are used under the **GNU Lesser General Public License
version 3** (LGPL-3.0-only). The wheels declare their licence in their own
metadata as `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`; Annotshot takes the
LGPL v3 option.

- Source of Qt for Python: <https://code.qt.io/cgit/pyside/pyside-setup.git/>
- Source of Qt 6: <https://code.qt.io/cgit/qt/qt5.git/>
- The LGPL v3 text: <https://www.gnu.org/licenses/lgpl-3.0.txt> (it builds on the
  GPL v3: <https://www.gnu.org/licenses/gpl-3.0.txt>)

Where the licence lives in an installed copy: the `PySide6-Essentials` wheel
states it in `pyside6_essentials-6.12.0.dist-info/METADATA` (the `License:`
line) inside your Python's `site-packages` folder; the wheel's
`pyside6_essentials-6.12.0.dist-info/licenses/` folder holds only
`LicenseRef-Qt-Commercial.txt` (the commercial alternative) and no copy of the
LGPL text, so the links above are the place to read it.

### The release zips

The release zips (`Annotshot-<version>-windows.zip`, `Annotshot-<version>-macos.zip`,
`Annotshot-<version>-linux.zip`) are built with PyInstaller in its one-folder
mode. They bundle Qt and PySide6 **unmodified, as separate shared libraries**
(`.dll` files on Windows, `.dylib` / framework files on macOS, `.so` files on
Linux) inside the app's folder, next to the program. They are not linked into
the program file. You may replace those libraries with your own build of the
same Qt and PySide6 version, compatible with the interface, and Annotshot will
use them. To rebuild Annotshot against another Qt, see "How to build" in
`README.md`; all of Annotshot's source is in this repository.

## Python

The release zips also carry the Python runtime (PSF License Agreement,
<https://docs.python.org/3/license.html>) and the PyInstaller bootloader (GPL v2
with the bootloader exception, which allows it in any program:
<https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt>).
