<p align="center"><img src="docs/icon.svg" width="96" alt="Annotshot icon"></p>

# Annotshot

Annotshot is a screenshot app for Windows, macOS and Linux with PowerPoint-style editing. Capture a region or a window, then edit it like a slide: text boxes with their own text color and background fill, arrows, shapes, highlights, crop and undo. Copy the image or save a PNG in one click, and save the project to keep editing later. You can also save straight into a Word document or a PowerPoint slide.

## Download the app

<p>
<a href="https://github.com/Bill-Viking/annotshot/releases/download/v0.3.1/Annotshot-0.3.1-setup.exe"><img src="https://img.shields.io/badge/Download%20for-Windows-2563EB?style=for-the-badge" alt="Download for Windows"></a>
<a href="https://github.com/Bill-Viking/annotshot/releases/download/v0.3.1/Annotshot-0.3.1-macos.zip"><img src="https://img.shields.io/badge/Download%20for-macOS-2563EB?style=for-the-badge" alt="Download for macOS"></a>
<a href="https://github.com/Bill-Viking/annotshot/releases/download/v0.3.1/Annotshot-0.3.1-linux.zip"><img src="https://img.shields.io/badge/Download%20for-Linux-2563EB?style=for-the-badge" alt="Download for Linux"></a>
</p>

Version 0.3.1. The Windows button downloads the installer; the macOS download is for Macs with Apple silicon (M1 or newer). Each button downloads one file into your **Downloads** folder. (The green **Code** button at the top of this page is the program's source code, not the app — you do not need it.)

![Annotshot with a text box, an arrow, a highlight and a pen stroke](docs/screenshot.png)

## Install

### Windows (10 and 11)

There are two roads. The installer is the usual one: it puts Annotshot in the Start menu and registers the `.annotshot` file type. The zip needs no installing: the folder runs wherever you put it.

#### The installer — five steps

1. **Download:** click **Download for Windows** above. `Annotshot-0.3.1-setup.exe` appears in your Downloads folder.
2. **Run it:** open Downloads and double-click `Annotshot-0.3.1-setup.exe`. Windows will show a blue box, **Windows protected your PC**, because Annotshot is new and not yet signed: click **More info**, then **Run anyway**. It appears only the first time.

   <!-- picture: docs/windows-protected.png is captured on a Windows computer; when it exists, insert this line here: ![Windows protected your PC — click More info, then Run anyway](docs/windows-protected.png) -->
3. **Next:** if it asks whether to install for you only or for all users, click **Install for me only** (no administrator is needed). Accept the licence and click **Next**.
4. **Pick a folder:** keep the folder it suggests (your own `AppData\Local\Programs\Annotshot`) or click **Browse…** and pick another, then **Next**. Tick **Create a desktop shortcut** if you want one, click **Next**, then **Install**, then **Finish**.
5. **Start it:** Annotshot is in the Start menu — press the Windows key, type `Annotshot` and press Enter.

#### The zip — three steps

1. **Download:** [`Annotshot-0.3.1-windows.zip`](https://github.com/Bill-Viking/annotshot/releases/download/v0.3.1/Annotshot-0.3.1-windows.zip) appears in your Downloads folder.
2. **Unzip:** open Downloads, right-click `Annotshot-0.3.1-windows.zip`, choose **Extract All…**, then click **Extract**. A folder named `Annotshot-0.3.1-windows` opens, and inside it is a folder named `Annotshot`. That `Annotshot` folder is the app — keep it whole, and move it anywhere you like (for example into `C:\Program Files` or onto `D:\`).
3. **Start it:** open the `Annotshot` folder and double-click **Annotshot.exe** (the blue A). Windows will show a blue box, **Windows protected your PC**, because Annotshot is new and not yet signed: click **More info**, then **Run anyway**. It appears only the first time.

   <!-- picture: docs/windows-protected.png is captured on a Windows computer; when it exists, insert this line here: ![Windows protected your PC — click More info, then Run anyway](docs/windows-protected.png) -->

To start it from the Start menu next time: right-click **Annotshot.exe** → **Pin to Start**.

### macOS — four steps

The macOS app is for Macs with Apple silicon (M1 or newer); it does not run on a Mac with an Intel processor.

1. **Download:** click **Download for macOS** above. `Annotshot-0.3.1-macos.zip` appears in your Downloads folder.
2. **Unzip and move:** open Downloads and double-click `Annotshot-0.3.1-macos.zip`. **Annotshot.app** (the blue A) appears next to it. Drag **Annotshot.app** into your **Applications** folder.
3. **Tell macOS the app is safe:** Annotshot is not signed by Apple yet, so macOS refuses to open it until you clear its download flag. Open **Terminal** (press ⌘ Space, type `Terminal`, press Return), paste this line and press Return:

   ```
   xattr -cr /Applications/Annotshot.app
   ```

4. **Start it:** open **Applications** and double-click **Annotshot**. The first time you click **Capture**, macOS asks to let Annotshot record your screen — click **Allow**. If a capture shows only your wallpaper and no windows, open **System Settings → Privacy & Security → Screen & System Audio Recording**, switch Annotshot on, quit Annotshot and start it again.

### Linux — three steps

1. **Download:** click **Download for Linux** above. `Annotshot-0.3.1-linux.zip` appears in your Downloads folder.
2. **Unzip:** right-click the zip in your file manager and choose **Extract Here** (or in a terminal: `cd ~/Downloads && unzip Annotshot-0.3.1-linux.zip`). A folder named `Annotshot` appears; it is the app — keep it whole, and move it anywhere you like (for example to `~/Apps/Annotshot`).
3. **Start it:** double-click the file named **Annotshot** inside that folder (or in a terminal: `~/Downloads/Annotshot/Annotshot`). If it says **permission denied**, run `chmod +x ~/Downloads/Annotshot/Annotshot` once, then start it again.

No one has run the Linux build by hand yet: the release workflow builds it and runs its self-check on an Ubuntu runner, and that is all it has been through. Two things to know:

- **Wayland:** Qt's screen grab returns an empty picture on Wayland, the default session on new GNOME and KDE desktops, so a capture there comes back blank. Until Annotshot uses the desktop's own screenshot service, log in to an X11 (**Xorg**) session where the login screen offers one (for example **Ubuntu on Xorg**, behind the gear button on the login screen).
- **A missing library:** if Annotshot does not start and a terminal shows that the Qt platform plugin **xcb** could not be loaded, install it with `sudo apt install libxcb-cursor0` (Debian, Ubuntu and relatives), then start Annotshot again.

**You should see** — on every system — a window titled **Annotshot — Untitled** with a blue **Capture** button at the top left.

### After installing

- **Windows:** the installer registers the `.annotshot` file type, so a double-click on a saved file opens Annotshot. With the zip, start Annotshot once before you double-click a saved `.annotshot` file; it registers the file type each time it starts. If Windows still asks **How do you want to open this file?** or opens another program, right-click the file, choose **Open with**, then **Choose another app**, pick **Annotshot**, tick **Always use this app to open .annotshot files**, and click **OK**. On a computer managed by an organisation, apps that are not signed may be blocked: if the blue box shows no **Run anyway**, or **Annotshot.exe** will not start, the computer's administrator has to allow it.
- **macOS:** the first **Capture** asks for screen recording, as in step 4 above. A double-click on a saved `.annotshot` file in Finder opens it in Annotshot once the app is in **Applications**.
- **Linux:** no double-click on saved files yet. Use **Open…** inside Annotshot, or start Annotshot with the file's name after it: `~/Apps/Annotshot/Annotshot picture.annotshot`.

### Updating to a new version

- **Windows, the installer:** close Annotshot, download the new `Annotshot-<version>-setup.exe` and run it: it replaces the old copy in place, in the same folder, and keeps your settings.
- **Windows, the zip:** close Annotshot, delete the old `Annotshot` folder, unzip the new download in its place, and start it once so a double-click on a saved file uses the new copy.
- **macOS:** drag the new **Annotshot.app** into **Applications** and choose **Replace**. Run the Terminal line from step 3 again (every new download is flagged again). If macOS asks about screen recording again, click **Allow**.
- **Linux:** close Annotshot and replace the `Annotshot` folder with the one from the new zip.

### Removing Annotshot

- **Windows, the installer:** open **Settings → Apps**, find **Annotshot**, and click **Uninstall**. Your pictures and `.annotshot` files stay where you saved them.
- **Windows, the zip:** delete the `Annotshot` folder.
- **macOS:** drag **Annotshot.app** from **Applications** to the Bin.
- **Linux:** delete the `Annotshot` folder.

## Your first screenshot

1. Click **Capture** (or press Ctrl+N; ⌘N on a Mac). Your screen freezes and dims.
2. Drag a box around the part you want, or click a window to take all of it.
3. Click **Text**, click on the picture, type — then **Copy image** and paste it anywhere, or **Save…** as a picture, a Word document or a PowerPoint slide.

The whole app, button by button: **[User manual](docs/USER-MANUAL.md)**.

## More

- The user manual, every button and shortcut: [docs/USER-MANUAL.md](docs/USER-MANUAL.md)
- How Annotshot compares with Snagit, ShareX, Greenshot and others:
  [docs/COMPARISON.md](docs/COMPARISON.md)

## How to build

- **Windows, by hand:** in Windows PowerShell, from the repository folder, with
  the virtual environment from **For developers** below plus
  `pip install pyinstaller==6.22.3`:

  ```
  powershell -ExecutionPolicy Bypass -File packaging\build-win.ps1
  ```

  It builds `dist\Annotshot\`, runs the program's headless self-check,
  builds the installer `dist\Annotshot-<version>-setup.exe` when Inno Setup 6
  is installed (it says so in one line when it is not), and writes
  `dist\Annotshot-<version>-windows.zip`.
- **All three systems:** the GitHub Actions workflow
  [`.github/workflows/release.yml`](.github/workflows/release.yml) builds,
  tests and zips Windows, macOS and Linux, and builds the Windows installer
  from `packaging/annotshot.iss` (installed, checked and uninstalled again on
  the runner). Push a tag `v<version>` (matching `annotshot/__init__.py`) and
  it attaches `Annotshot-<version>-setup.exe`, `Annotshot-<version>-windows.zip`,
  `Annotshot-<version>-macos.zip` and `Annotshot-<version>-linux.zip` to that
  release; run it by hand from the **Actions** tab for a dry run.
- **Tests:** `python -m pytest -q` (they run offscreen; no window opens).
- **Self-check:** `python -m annotshot --check` saves a small Word and
  PowerPoint file in a scratch folder, re-opens both, and ends with
  `Annotshot <version> OK`.

## Licence

Annotshot is MIT-licensed: see [LICENSE](LICENSE). It uses Qt for Python and
Qt 6 under the LGPL v3, and python-docx, python-pptx and their helpers under
their own licences, listed in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
Its pixel font, VT323, is under the SIL Open Font License 1.1. The licence texts
travel inside the app's folder too: a `licenses` folder with the GNU texts and
the font's licence, plus `LICENSE` and `THIRD-PARTY-NOTICES.md`, in every download.

## For developers

### From the source code (any system with Python 3.12)

1. Download this repository (**Code → Download ZIP**, then unzip it) or clone it.
2. Open a terminal in the repository folder and make a virtual environment with
   Qt for Python and the Word / PowerPoint libraries:

   ```
   python -m venv .venv
   .venv/bin/pip install PySide6-Essentials==6.12.0 python-docx==1.2.0 python-pptx==1.0.2 pytest
   ```

   On Windows: `.venv\Scripts\pip install PySide6-Essentials==6.12.0 python-docx==1.2.0 python-pptx==1.0.2 pytest`
   (`pytest` is only for running the tests.)
3. Start the app:

   ```
   .venv/bin/python -m annotshot
   ```

   On Windows: `.venv\Scripts\python -m annotshot`, or double-click
   `Annotshot.cmd` once the virtual environment exists.
