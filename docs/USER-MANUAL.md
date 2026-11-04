# Annotshot user manual

Wednesday 2026-11-04 · for Annotshot 0.2.0

## What Annotshot is

Annotshot takes a picture of part of your screen and lets you mark it up the way you would mark up a slide in PowerPoint. You drag out a text box, type into it, and give it its own text color, its own background fill and its own border. You can add arrows, rectangles, ellipses, highlighter bands and freehand pen strokes, crop the picture, and undo anything. When you are done, you copy the picture and paste it into Paint, PowerPoint, Teams or an email, or you save it as a file. You can also save an editable copy so you can reopen it later and keep changing the text.

This is a first version. It does one job: capture, mark up, copy or save. It has no screen recording, scrolling capture or picture library.

## Install and start

Download the app from the repository's Releases page — the three download buttons at the top of the README — never from the green Code button, which is the source code.

### Windows (10 and 11) — three steps

1. **Download:** click **Download for Windows** at the top of the Annotshot page on GitHub. `Annotshot-0.2.0-windows.zip` appears in your Downloads folder.
2. **Unzip:** open Downloads, right-click `Annotshot-0.2.0-windows.zip`, choose **Extract All…**, then click **Extract**. A folder named `Annotshot-0.2.0-windows` opens, and inside it is a folder named `Annotshot`. That `Annotshot` folder is the app — keep it whole, and move it anywhere you like (for example into `C:\Program Files` or onto `D:\`).
3. **Start it:** open the `Annotshot` folder and double-click **Annotshot.exe** (the blue A). The first time, Windows may show a blue box, **Windows protected your PC**: click **More info**, then **Run anyway**. That box appears once.

To start it from the Start menu next time: right-click **Annotshot.exe** → **Pin to Start**.

### macOS — four steps

The macOS app is for Macs with Apple silicon (M1 or newer); it does not run on a Mac with an Intel processor.

1. **Download:** click **Download for macOS** at the top of the Annotshot page on GitHub. `Annotshot-0.2.0-macos.zip` appears in your Downloads folder.
2. **Unzip and move:** open Downloads and double-click `Annotshot-0.2.0-macos.zip`. **Annotshot.app** (the blue A) appears next to it. Drag **Annotshot.app** into your **Applications** folder.
3. **Tell macOS the app is safe:** Annotshot is not signed by Apple yet, so macOS refuses to open it until you clear its download flag. Open **Terminal** (press ⌘ Space, type `Terminal`, press Return), paste this line and press Return:

   ```
   xattr -cr /Applications/Annotshot.app
   ```

4. **Start it:** open **Applications** and double-click **Annotshot**. The first time you click **Capture**, macOS asks to let Annotshot record your screen — click **Allow**. If a capture shows only your wallpaper and no windows, open **System Settings → Privacy & Security → Screen & System Audio Recording**, switch Annotshot on, quit Annotshot and start it again.

### Linux — three steps

1. **Download:** click **Download for Linux** at the top of the Annotshot page on GitHub. `Annotshot-0.2.0-linux.zip` appears in your Downloads folder.
2. **Unzip:** right-click the zip in your file manager and choose **Extract Here** (or in a terminal: `cd ~/Downloads && unzip Annotshot-0.2.0-linux.zip`). A folder named `Annotshot` appears; it is the app — keep it whole, and move it anywhere you like (for example to `~/Apps/Annotshot`).
3. **Start it:** double-click the file named **Annotshot** inside that folder (or in a terminal: `~/Downloads/Annotshot/Annotshot`). If it says **permission denied**, run `chmod +x ~/Downloads/Annotshot/Annotshot` once, then start it again.

No one has run the Linux build by hand yet: the release workflow builds it and runs its self-check on an Ubuntu runner, and that is all it has been through. Two things to know:

- **Wayland:** Qt's screen grab returns an empty picture on Wayland, the default session on new GNOME and KDE desktops, so a capture there comes back blank. Until Annotshot uses the desktop's own screenshot service, log in to an X11 (**Xorg**) session where the login screen offers one (for example **Ubuntu on Xorg**, behind the gear button on the login screen).
- **A missing library:** if Annotshot does not start and a terminal shows that the Qt platform plugin **xcb** could not be loaded, install it with `sudo apt install libxcb-cursor0` (Debian, Ubuntu and relatives), then start Annotshot again.

**You should see** — on every system — a window titled **Annotshot — Untitled** with a blue **Capture** button at the top left.

### After installing

- **Windows:** start Annotshot once before you double-click a saved `.annotshot` file; it registers the file type each time it starts. If Windows still asks **How do you want to open this file?** or opens another program, right-click the file, choose **Open with**, then **Choose another app**, pick **Annotshot**, tick **Always use this app to open .annotshot files**, and click **OK**. On a computer managed by an organisation, apps that are not signed may be blocked: if the blue box shows no **Run anyway**, or **Annotshot.exe** will not start, the computer's administrator has to allow it.
- **macOS:** the first **Capture** asks for screen recording, as in step 4 above. A double-click on a saved `.annotshot` file in Finder opens it in Annotshot once the app is in **Applications**.
- **Linux:** no double-click on saved files yet. Use **Open…** inside Annotshot, or start Annotshot with the file's name after it: `~/Apps/Annotshot/Annotshot picture.annotshot`.

### Updating to a new version

- **Windows:** close Annotshot, delete the old `Annotshot` folder, unzip the new download in its place, and start it once so a double-click on a saved file uses the new copy.
- **macOS:** drag the new **Annotshot.app** into **Applications** and choose **Replace**. Run the Terminal line from step 3 again (every new download is flagged again). If macOS asks about screen recording again, click **Allow**.
- **Linux:** close Annotshot and replace the `Annotshot` folder with the one from the new zip.

## The first ten seconds

1. Click **Capture** (the blue button, top left), or press **Ctrl+N**.
2. The Annotshot window steps aside for a moment, and your screen freezes and dims.
3. Either **drag** a box around the part you want (a size label shows its width × height in pixels), or **click** a window to take the whole window. On Windows the window under the mouse lights up with a red frame and its title before you click.
4. Your capture opens in the editor. Press **Esc** or right-click during capture to cancel.

Now click **Text**, click on the picture, and type. Then **Copy image** and paste it anywhere, or **Save…** as a picture, a Word document or a PowerPoint slide.

## The editor, row by row

The Annotshot window opens in the middle of your screen at a moderate size, never full screen, and it remembers the size you leave it at. After a capture it grows to fit the picture, up to 80 % of your screen; a bigger picture scrolls or zooms inside the window.

The bottom of the window shows the picture's size in pixels and the zoom level. Hold **Ctrl** and turn the mouse wheel to zoom. Zoom changes only your view, never the picture.

### Row 1: the picture

| Button | What it does | Shortcut |
|---|---|---|
| **Capture** | Takes a new screenshot (drag a region or click a window). If your current picture has changes you have not saved or copied, Annotshot asks first. | Ctrl+N |
| **Open…** | Opens an Annotshot editable file (`.annotshot`) so you can keep editing it. | Ctrl+O |
| **Save…** | Saves the picture as PNG, JPEG, BMP or WebP, or saves an editable Annotshot file. See "Saving" below. | Ctrl+S, Ctrl+Shift+S |
| **Copy image** | Puts the finished picture, with all your marks, on the clipboard. | Ctrl+C |
| **Undo** | Takes back the last change. Hover over it to see which change. | Ctrl+Z |
| **Redo** | Puts it back again. | Ctrl+Y or Ctrl+Shift+Z |

### Row 2: the tools and the object buttons

On the left are the tools: **Select, Text, Rect, Ellipse, Arrow, Highlight, Pen, Crop**. On the right are the buttons that act on what you have selected: **Duplicate, Front, Back, Delete**.

**Undo, Redo, Duplicate, Front, Back and Delete show only a small picture, no word.** Hover over one to see its name and its shortcut.

After you draw one object (or crop), Annotshot switches back to **Select** by itself, so you can move or change what you just made.

### Row 3: the property strip

The strip starts with what is selected: "Nothing selected", "Text box", "Rectangle", "Ellipse", "Arrow", "Highlight", "Pen stroke", or "3 objects". Each control changes every selected object at once. A control is greyed out when the selection has no such property.

## The tools

- **Select**: click an object to select it, drag it to move it, and pull one of its eight square handles to resize it. An arrow has two handles, one at each end. Drag across empty picture to select several objects; Ctrl+click adds or removes one.
- **Text**: click once for a ready-sized text box, or drag to set its width. You start typing right away. The box grows taller when the text needs more room. Double-click a text box later to edit its text again.
- **Rect**: drag to draw a rectangle (red outline, no fill to start).
- **Ellipse**: drag to draw an ellipse or circle.
- **Arrow**: drag from the tail to where the arrow should point. The head appears at the end where you let go.
- **Highlight**: drag a see-through yellow band over text, like a highlighter pen. The text underneath stays readable.
- **Pen**: draw freehand while holding the mouse button down.
- **Crop**: drag a box. The picture is cut down to that box, and your objects stay where they were on the picture. Undo brings the full picture back.

While you are drawing with any tool, a right-click cancels that drawing.

## The property strip, control by control

| Control | What it changes | Works on |
|---|---|---|
| **Font** | The typeface. | Text box |
| **Size** | The text size, in pixels (6 to 400). | Text box |
| **Style** | **B** bold, *I* italic. | Text box |
| **Align** | Left, center or right inside the box. | Text box |
| **Text** | The color of the letters only (it was called "Text color" before). | Text box |
| **Fill** | The background color inside the shape. Changing it never changes the text color. | Text box, rectangle, ellipse, highlight (color only) |
| **No fill** | Makes the inside see-through. | Text box, rectangle, ellipse |
| **Border** | The outline color. For an arrow or pen stroke, this is the line color. | Text box, rectangle, ellipse, arrow, pen stroke |
| **No border** | Removes the outline. For an arrow or pen stroke it makes the line invisible, so use it with care. | Same as Border |
| **Width** | How thick the outline or line is, in pixels (0 to 40). | Same as Border |
| **Opacity** | How see-through the whole object is, from 0% (invisible) to 100% (solid). | Every object |

Clicking a color opens a color picker. It has a transparency setting too, so you can make a fill half see-through. A highlight always keeps its own see-through level; Fill changes only its color.

## Undo while typing

While you are typing in a text box, **Undo** and **Redo** work on your typing, a few letters at a time. When you finish (click outside the box or press **Esc**), the whole edit becomes one step, and Undo takes back the whole edit at once.

Press **Esc** to stop typing. Press **Esc** again to clear the selection.

## Duplicate, Front, Back, Delete

- **Duplicate** (Ctrl+D): makes a copy of the selected objects, a little down and to the right, on top of everything.
- **Front** (Ctrl+]): brings the selected objects in front of all the others.
- **Back** (Ctrl+[): sends them behind all the others (but always above the screenshot itself).
- **Delete** (Delete key): removes them.

All four can be undone.

## Saving

Click **Save…** to open the Save window. Pick a file type from the "Save as type" list:

| Type | What you get |
|---|---|
| **PNG image** | The finished picture. The best choice for most uses. Sharp text, any see-through parts kept. |
| **JPEG image** | The finished picture as a smaller file. See-through parts become white. |
| **BMP image** | The finished picture, uncompressed. See-through parts become white. |
| **WebP image** | The finished picture as a small modern file. |
| **Word document (.docx)** | The finished picture on page 1 of a Word document, centred. |
| **PowerPoint slide (.pptx)** | The finished picture on one PowerPoint slide, centred. |
| **Annotshot editable (.annotshot)** | Your work, kept editable. |

**What "editable" means:** a PNG or JPEG is a flat photo. Once saved, the text is part of the picture, and you cannot fix a typo without painting over it. A `.annotshot` file keeps the screenshot and every text box, arrow and shape as separate objects. Open it again later with **Open…** and you can still double-click the text to retype it, change its colors, move an arrow or delete a shape. Keep a `.annotshot` copy whenever you may need to change something later.

Pictures save to the `Annotshot` folder inside your Pictures folder unless you choose another place. Annotshot remembers the last folder and the last file type you used. New files are named with the date and time, for example `Annotshot 2026-11-03 14-05-09.png`.

Once you have saved an editable file, **Ctrl+S** saves it again straight away without asking. **Ctrl+Shift+S** always opens the Save window.

The window title shows the file name, with a `*` when there are changes not yet saved.

## Word and PowerPoint

Pick **Word document** or **PowerPoint slide** in the Save window and the finished picture goes straight into an Office file — no copy and paste. In Word it is centred on page 1, as wide as the space between the margins (never wider than the picture itself, and never taller than the page). In PowerPoint it is one blank slide with the picture centred and fitted, with a small margin all round. Saving either one counts as done, like saving a picture: closing or capturing again does not ask.

## Copy image and paste anywhere

Click **Copy image** (or press Ctrl+C). The status line says "Copied — paste it anywhere". Then go to the other app and paste with **Ctrl+V**:

- **Paint**: the picture appears as a new selection you can move.
- **PowerPoint**: the picture lands on the slide as a picture.
- **Teams**: paste into the message box; the picture appears in your message before you send it.
- **Email** (Outlook and most mail programs): paste into the body of the message.

If you are typing in a text box, press **Esc** first so Ctrl+C copies the whole picture rather than the letters you have selected.

Copying or saving a picture counts as "done": the next **Capture** will not ask you to save, unless you have made more changes since.

## Opening an editable file

Click **Open…** (Ctrl+O) and choose a `.annotshot` file. Everything comes back as you left it, still editable. **Open…** opens only Annotshot editable files; it does not open ordinary PNG or JPEG pictures in this version.

You can also double-click a `.annotshot` file in File Explorer (Windows) or Finder (macOS): Annotshot starts and opens it. Annotshot registers the file type itself each time it starts, so start it once before your first double-click. If Windows still asks "How do you want to open this file?" or opens another program, right-click the file, choose **Open with**, then **Choose another app**, pick **Annotshot**, tick **Always use this app to open .annotshot files**, and click **OK**; Windows lets only you make that choice, and Annotshot's status line reminds you when another program holds it. On Linux, start Annotshot with the file as its argument, for example `Annotshot picture.annotshot`.

## Keyboard shortcuts

On a Mac, use the **Command (⌘)** key wherever this table says Ctrl.

| Keys | Does |
|---|---|
| Ctrl+N | Capture |
| Ctrl+O | Open… |
| Ctrl+S | Save… (saves an editable file again without asking) |
| Ctrl+Shift+S | Save… (always opens the Save window) |
| Ctrl+C | Copy image |
| Ctrl+Z | Undo |
| Ctrl+Y or Ctrl+Shift+Z | Redo |
| Ctrl+D | Duplicate |
| Ctrl+] | Front |
| Ctrl+[ | Back |
| Delete | Delete |
| Esc | Stop typing, then clear the selection; during capture, cancel |
| Ctrl + mouse wheel | Zoom in and out |
| Double-click a text box | Edit its text |

## Known limits in this first version

- **Clicking a window to capture it works on Windows only.** On macOS and Linux, drag a region instead; a click without dragging takes the whole screen.
- **One screen per capture.** A region cannot stretch across two monitors.
- **No scrolling capture, no screen recording, no picture library, no capture delay and no global hotkey yet.** Annotshot must be open, and you start each capture from its window.
- **Linux on Wayland:** Qt's screen grab returns an empty picture on Wayland, the default session on new GNOME and KDE desktops, so a capture there comes back blank. Until Annotshot uses the desktop's own screenshot service, use an X11 (Xorg) session where the login screen offers one. No one has run the Linux build by hand yet.
- **Linux:** no double-click on saved `.annotshot` files yet. Use **Open…**, or start Annotshot with the file's name after it.
- **One style per text box.** You cannot make one word bold and the next one plain inside the same box; use two boxes.

## Licence

Annotshot is MIT-licensed. It uses Qt for Python and Qt 6 under the LGPL v3, and python-docx, python-pptx and their helpers under their own licences. The licence texts travel inside the app's folder: a `licenses` folder with the GNU texts, plus `LICENSE` and `THIRD-PARTY-NOTICES.md` in the public download.

## For developers

### From the source code (any system with Python 3.12)

In the Annotshot folder, make a virtual environment, install Qt for Python, the Word / PowerPoint libraries and pytest (for the tests: `python -m pytest -q`), and start the app. If a Word or PowerPoint save says this copy needs two more parts, run the `pip install` line the message shows.

```
python -m venv .venv
.venv/bin/pip install PySide6-Essentials==6.12.0 python-docx==1.2.0 python-pptx==1.0.2 pytest
        (Windows: .venv\Scripts\pip install PySide6-Essentials==6.12.0 python-docx==1.2.0 python-pptx==1.0.2 pytest)
.venv/bin/python -m annotshot                       (Windows: .venv\Scripts\python -m annotshot)
```
