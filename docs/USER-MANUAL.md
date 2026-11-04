# Annotshot user manual

Tuesday 2026-11-03 · for Annotshot 0.1 (the first version)

## What Annotshot is

Annotshot takes a picture of part of your screen and lets you mark it up the way you would mark up a slide in PowerPoint. You drag out a text box, type into it, and give it its own text color, its own background fill and its own border. You can add arrows, rectangles, ellipses, highlighter bands and freehand pen strokes, crop the picture, and undo anything. When you are done, you copy the picture and paste it into Paint, PowerPoint, Teams or an email, or you save it as a file. You can also save an editable copy so you can reopen it later and keep changing the text.

This is a first version. It does one job: capture, mark up, copy or save. It has no screen recording, scrolling capture or picture library.

## Install and start

**Windows (10 and 11)**

1. Download `Annotshot-<version>-windows.zip`.
2. Right-click it and choose **Extract All…**. Keep the whole folder together. `Annotshot.exe` needs the files beside it.
3. Open the folder and double-click `Annotshot.exe`.

Annotshot is not signed yet, so Windows may show "Windows protected your PC" the first time. Click **More info**, then **Run anyway**.

**macOS**

1. Download `Annotshot-<version>-macos.zip` and double-click it. You get `Annotshot.app`.
2. Move `Annotshot.app` to your Applications folder and open it.
3. Annotshot is not signed by Apple yet. If macOS says it cannot check the app, open **System Settings → Privacy & Security**, scroll down, and click **Open Anyway** next to Annotshot.
4. The first time you click **Capture**, macOS asks to let Annotshot record your screen. Say yes. If the capture shows only your desktop background and no windows, open **System Settings → Privacy & Security → Screen & System Audio Recording**, switch Annotshot on, then quit Annotshot and open it again.

**Linux**

1. Download `Annotshot-<version>-linux.zip` and unzip it.
2. Open a terminal in the unzipped folder and run `./Annotshot`.
3. If it says "permission denied", run `chmod +x Annotshot` once, then `./Annotshot` again.

**From the source code (any system with Python 3.12)**

In the Annotshot folder, make a virtual environment, install Qt for Python, and start the app:

```
python -m venv .venv
.venv/bin/pip install PySide6-Essentials        (Windows: .venv\Scripts\pip install PySide6-Essentials)
.venv/bin/python -m annotshot                       (Windows: .venv\Scripts\python -m annotshot)
```

## The first ten seconds

1. Click **Capture** (the blue button, top left), or press **Ctrl+N**.
2. The Annotshot window steps aside for a moment, and your screen freezes and dims.
3. Either **drag** a box around the part you want (a size label shows its width × height in pixels), or **click** a window to take the whole window. On Windows the window under the mouse lights up with a red frame and its title before you click.
4. Your capture opens in the editor. Press **Esc** or right-click during capture to cancel.

Now click **Text**, click on the picture, and type.

## The editor, row by row

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
| **Text color** | The color of the letters only. | Text box |
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
| **Annotshot editable (.annotshot)** | Your work, kept editable. |

**What "editable" means:** a PNG or JPEG is a flat photo. Once saved, the text is part of the picture, and you cannot fix a typo without painting over it. A `.annotshot` file keeps the screenshot and every text box, arrow and shape as separate objects. Open it again later with **Open…** and you can still double-click the text to retype it, change its colors, move an arrow or delete a shape. Keep a `.annotshot` copy whenever you may need to change something later.

Pictures save to the `Annotshot` folder inside your Pictures folder unless you choose another place. Annotshot remembers the last folder and the last file type you used. New files are named with the date and time, for example `Annotshot 2026-11-03 14-05-09.png`.

Once you have saved an editable file, **Ctrl+S** saves it again straight away without asking. **Ctrl+Shift+S** always opens the Save window.

The window title shows the file name, with a `*` when there are changes not yet saved.

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
- **Linux:** not yet tested on Wayland desktops, where screen capture is often restricted. An X11 session is the safer choice for now.
- **One style per text box.** You cannot make one word bold and the next one plain inside the same box; use two boxes.
