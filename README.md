<p align="center"><img src="docs/icon.svg" width="96" alt="Annotshot icon"></p>

# Annotshot

Annotshot is a Windows screenshot app with PowerPoint-style editing. Capture a region or a window, then edit it like a slide: text boxes with their own text color and background fill, arrows, shapes, highlights, crop and undo. Copy the image or save a PNG in one click, and save the project to keep editing later.

## Download the app

<p>
<a href="https://github.com/Bill-Viking/annotshot/releases/download/v0.1.1/Annotshot-0.1.1-windows.zip"><img src="https://img.shields.io/badge/Download%20for-Windows-2563EB?style=for-the-badge" alt="Download for Windows"></a>
<a href="https://github.com/Bill-Viking/annotshot/releases/download/v0.1.1/Annotshot-0.1.1-macos.zip"><img src="https://img.shields.io/badge/Download%20for-macOS-2563EB?style=for-the-badge" alt="Download for macOS"></a>
<a href="https://github.com/Bill-Viking/annotshot/releases/download/v0.1.1/Annotshot-0.1.1-linux.zip"><img src="https://img.shields.io/badge/Download%20for-Linux-2563EB?style=for-the-badge" alt="Download for Linux"></a>
</p>

Version 0.1.1. Each button downloads one zip file into your **Downloads** folder. (The green **Code** button at the top of this page is the program's source code, not the app — you do not need it.)

![Annotshot with a text box, an arrow, a highlight and a pen stroke](docs/screenshot.png)

## Install

### Windows (10 and 11) — three steps

1. **Download:** click **Download for Windows** above. `Annotshot-0.1.1-windows.zip` appears in your Downloads folder.
2. **Unzip:** open Downloads, right-click `Annotshot-0.1.1-windows.zip`, choose **Extract All…**, then click **Extract**. A folder named `Annotshot-0.1.1-windows` opens, and inside it is a folder named `Annotshot`. That `Annotshot` folder is the app — keep it whole, and move it anywhere you like (for example into `C:\Program Files` or onto `D:\`).
3. **Start it:** open the `Annotshot` folder and double-click **Annotshot.exe** (the blue A). The first time, Windows may show a blue box, **Windows protected your PC**: click **More info**, then **Run anyway**. That box appears once.

To start it from the Start menu next time: right-click **Annotshot.exe** → **Pin to Start**.

### macOS — four steps

1. **Download:** click **Download for macOS** above. `Annotshot-0.1.1-macos.zip` appears in your Downloads folder.
2. **Unzip and move:** open Downloads and double-click `Annotshot-0.1.1-macos.zip`. **Annotshot.app** (the blue A) appears next to it. Drag **Annotshot.app** into your **Applications** folder.
3. **Tell macOS the app is safe:** Annotshot is not signed by Apple yet, so macOS refuses to open it until you clear its download flag. Open **Terminal** (press ⌘ Space, type `Terminal`, press Return), paste this line and press Return:

   ```
   xattr -cr /Applications/Annotshot.app
   ```

4. **Start it:** open **Applications** and double-click **Annotshot**. The first time you click **Capture**, macOS asks to let Annotshot record your screen — click **Allow**. If a capture shows only your wallpaper and no windows, open **System Settings → Privacy & Security → Screen & System Audio Recording**, switch Annotshot on, quit Annotshot and start it again.

### Linux — three steps

1. **Download:** click **Download for Linux** above. `Annotshot-0.1.1-linux.zip` appears in your Downloads folder.
2. **Unzip:** right-click the zip in your file manager and choose **Extract Here** (or in a terminal: `cd ~/Downloads && unzip Annotshot-0.1.1-linux.zip`). A folder named `Annotshot` appears; it is the app — keep it whole, and move it anywhere you like (for example to `~/Apps/Annotshot`).
3. **Start it:** double-click the file named **Annotshot** inside that folder (or in a terminal: `~/Downloads/Annotshot/Annotshot`). If it says **permission denied**, run `chmod +x ~/Downloads/Annotshot/Annotshot` once, then start it again. Tested on Ubuntu 24.04 (X11); Wayland is untested.

**You should see** — on every system — a window titled **Annotshot — Untitled** with a blue **Capture** button at the top left.

## Your first screenshot

1. Click **Capture** (or press Ctrl+N; ⌘N on a Mac). Your screen freezes and dims.
2. Drag a box around the part you want, or click a window to take all of it.
3. Click **Text**, click on the picture, type — then **Copy image** and paste it anywhere, or **Save…**.

The whole app, button by button: **[User manual](docs/USER-MANUAL.md)**.

## More

- The user manual, every button and shortcut: [docs/USER-MANUAL.md](docs/USER-MANUAL.md)
- How Annotshot compares with Snagit, ShareX, Greenshot and others:
  [docs/COMPARISON.md](docs/COMPARISON.md)

## How to build

- **Windows, by hand:** in Windows PowerShell, from the repository folder, with
  the virtual environment above plus `pip install pyinstaller`:

  ```
  powershell -ExecutionPolicy Bypass -File packaging\build-win.ps1
  ```

  It builds `dist\Annotshot\`, runs the program's headless self-check, and
  writes `dist\Annotshot-<version>-windows.zip`.
- **All three systems:** the GitHub Actions workflow
  [`.github/workflows/release.yml`](.github/workflows/release.yml) builds,
  tests and zips Windows, macOS and Linux. Push a tag `v<version>` (matching
  `annotshot/__init__.py`) and it attaches `Annotshot-<version>-windows.zip`,
  `Annotshot-<version>-macos.zip` and `Annotshot-<version>-linux.zip` to that
  release; run it by hand from the **Actions** tab for a dry run.
- **Tests:** `python -m pytest -q` (they run offscreen; no window opens).
- **Self-check:** `python -m annotshot --check` prints `Annotshot <version> OK`.

## Licence

Annotshot is MIT-licensed: see [LICENSE](LICENSE). It uses Qt for Python and
Qt 6 under the LGPL v3: see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## For developers

### From the source code (any system with Python 3.12)

1. Download this repository (**Code → Download ZIP**, then unzip it) or clone it.
2. Open a terminal in the repository folder and make a virtual environment with
   Qt for Python:

   ```
   python -m venv .venv
   .venv/bin/pip install PySide6-Essentials==6.12.0
   ```

   On Windows: `.venv\Scripts\pip install PySide6-Essentials==6.12.0`
3. Start the app:

   ```
   .venv/bin/python -m annotshot
   ```

   On Windows: `.venv\Scripts\python -m annotshot`, or double-click
   `Annotshot.cmd` once the virtual environment exists.
