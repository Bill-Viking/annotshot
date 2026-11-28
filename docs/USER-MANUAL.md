# Annotshot user manual

Wednesday 2026-11-25 · for Annotshot 0.4.4

## Your first screenshot

1. Click **Capture**. Drag over the part of the screen you want and release.
2. Click **Text**, click the picture, and type your note.
3. Press **Escape**, then click **Copy image** to copy the picture with your note.
4. In your message, choose **Paste**.

To send an attachment, click **Save…**, choose **PNG image**, and save it in a folder you can find. Attach that file to your message.

## What Annotshot is

Annotshot takes screenshots. You can add text, arrows and shapes, then copy the marked picture or save it as a file. Save an editable `.annotshot` file if you want to change the marks later.

By default, Annotshot keeps screenshots in **Recent captures**.

Annotshot is made by Bill Moldestad.

## Install and start

Go to [Annotshot releases on GitHub](https://github.com/Bill-Viking/annotshot/releases) and choose the download for your system.

### Windows (10 and 11)

For your own Windows computer, choose the installer or the zip. For a central installation, see **For IT departments: the MSI** below.

#### The installer

1. From **Releases**, download the Windows installer (the file ending in `-setup.exe`).
2. Open the downloaded file and follow the installer.
3. Open Annotshot. If needed, search the Start menu for `Annotshot`.

#### The zip

1. From **Releases**, choose the Windows zip.
2. Extract the whole zip into a folder.
3. Open **Annotshot.exe** from the extracted folder. Keep the files together.

#### For IT departments: the MSI

The MSI is for IT departments. It is set up to install Annotshot in **Program Files** for all users and register editable files for the machine. The Windows installer and MSI have been signed in each completed release run since 0.4.1.

For a personal installation, use the Windows installer above.

For a silent install or removal, download the MSI from **Releases**. Run the matching command from its folder, using the name of the MSI you downloaded.

**Install:**

```
msiexec /i Annotshot-0.4.4.msi /qn
```

**Remove:**

```
msiexec /x Annotshot-0.4.4.msi /qn
```

### macOS

1. From **Releases**, choose the macOS zip.
2. Extract the zip and move **Annotshot.app** to **Applications**.

3. Open **Annotshot** from **Applications** and click **Capture**. If Annotshot asks for screen recording permission, click **Open System Settings** and turn on screen recording for Annotshot.

   If Annotshot is already on the list and capture is still blocked, remove it from the list, add **Annotshot** again from **Applications**, and switch it on. Annotshot may restart. If capture is still blocked, click **Capture** and choose **Restart Annotshot** when offered.

### Linux

1. From **Releases**, choose the Linux zip.
2. Extract the whole zip and keep the files together.
3. Start **Annotshot** from the extracted folder.

The Linux build has not been run by hand. If a capture is blank on Wayland, try an X11 session if your computer offers one.

When you open Annotshot on its own, look for **Capture** at the bottom of the welcome window.

### After installing

- **Windows:** If you use the zip, start Annotshot once before trying to open a saved file from File Explorer. If your organisation blocks the app, ask your IT team.
- **macOS:** If **Capture** asks for permission, follow the screen recording steps above.
- **Any system:** To open an editable file, click **Open a saved file…** in the welcome window and choose the `.annotshot` file.

### Updating to a new version

- **Windows installer:** Close Annotshot and run the new installer.
- **Windows zip:** Close Annotshot, extract the new zip to a separate folder, and start the new copy.
- **Windows MSI:** An MSI upgrade over an installed copy passed on a Windows machine on 16 November 2026.
- **macOS:** Close Annotshot and replace **Annotshot.app** in **Applications** with the new copy. After an update of the unsigned app, capture may need permission again. If Annotshot is already enabled in the screen recording list, remove it, add it again from **Applications**, and switch it on.
- **Linux:** Close Annotshot and extract the new zip to a separate folder.

### Removing Annotshot

Before removing Annotshot, keep a copy of any pictures and editable files you want outside the app folder.

- **Windows installer:** Find Annotshot in Windows settings and choose the uninstall option.
- **Windows zip or Linux:** Remove the extracted app folder.
- **macOS:** Move **Annotshot.app** from **Applications** to the Bin.

## Privacy

Annotshot captures and edits pictures on your computer. By default, it keeps each capture in **Recent captures** and copies it to the clipboard. You can turn either option off in **Settings… → Capture**. Turning off Recent leaves earlier pictures in place. Opening the feedback page does not attach your screenshot.

[How it stays private](https://github.com/Bill-Viking/annotshot/blob/main/docs/PRIVACY.md)

## The opening window

When you open Annotshot on its own, you can take a screenshot, click one of up to four recent captures, or click **Open a saved file…**.

On Windows and Mac, **Area**, **Window** and **Whole screen** let you choose what to capture. **Timer** sets a delay for live capture. The key button beside **Capture** lets you try, change or turn off **Capture from anywhere**.

Click the key button beside **Capture** and choose **Try this key**. Wait for Annotshot to minimize, then press the capture key. This try takes no screenshot.

If Annotshot receives the press, it reopens and says “Annotshot received your key”. If it receives no press within ten seconds, it reopens and says “No press received”. To try another key, choose **Change key**.

## Closing and quitting

**Keep Annotshot running when its window is closed** is on in Settings → Capture. Closing the window keeps your edits, returns to welcome, and hides the window. A registered capture key stays active while the window is closed. A capture brings back the editor. Cancelling with Esc leaves a hidden window hidden.

On macOS, click Annotshot in the Dock to reopen welcome. On Windows, the Annotshot tray icon offers **Capture**, **Open Annotshot**, and **Quit Annotshot**. The tray lists the key only when it is registered for capture. Clicking the icon reopens the window. The first hide shows a message explaining that Annotshot is still running. If the tray is unavailable, closing quits.

**Quit Annotshot** (Command+Q on macOS) closes the app. Turn off **Keep Annotshot running when its window is closed** to quit when closing the window.

If Annotshot cannot keep your last changes to a picture when you close its window or quit (a full disk, or a folder that is gone), it stays open and asks: **Save a copy…** somewhere else, **Discard changes**, or **Cancel** to go on working.

## Capture options

1. Click **Capture** in the opening window or editor, or press **Ctrl+N** (Command+N on a Mac). Return or Space in the opening window also starts Capture.
2. On Windows and Mac, the capture bar appears on the screen with your pointer.
3. In live capture, drag to choose an area, or click a window when one is available. Choose **Area** or **Window** to limit the choice to that gesture. Click the selected choice again to use either gesture. **Whole screen** captures the screen with the bar.
4. To reuse your last area, look for **Same area** on the capture bar. It appears when the area still fits on the same screen. Hover over it to preview the area, then click to capture it. No key or double-click takes the last area.
5. **Wait after pick** delays a live shot by **3 s**, **5 s** or **10 s** after you finish the pick; **Off** takes it straight away. A countdown appears in the bar. **Esc**, a right-click, or **Cancel** cancels, including during the countdown.

Click **Freeze now** to hold the screen still while you choose.

- **Area** — Drag over the part you want and release. A click takes the whole screen. On Windows, clicking an available window takes just that window.
- **Window** — Click the window you want.
- **Whole screen** — Click the screen you want.

**Wait after pick** is unavailable while the screen is frozen. Click **Go live** when available to use live capture with your previous delay.

Annotshot remembers the wait and whether you froze the screen. Each capture stays on one screen.

On **Linux**, capture keeps the frozen screen and has no capture bar: drag an area or click for the whole screen. Esc or a right-click cancels.


## The editor, row by row

The Annotshot window opens in the middle of your screen at a moderate size, never full screen, and it remembers the size you leave it at. After a capture it grows to fit the picture, up to 80 % of your screen; a bigger picture scrolls or zooms inside the window.

The bottom of the window shows the picture's size in pixels and a zoom button. Click the percent for **Fit**, **100 %**, **200 %**, **Zoom in** or **Zoom out**. Fit uses 100 % when the picture already fits. Hold **Ctrl** and turn the mouse wheel to zoom. Zoom changes only your view, never the picture.

### Row 1: the picture

These are the default editor shortcuts. On a Mac, use **Command** wherever the table says **Ctrl**. To see your current shortcuts, right-click the picture and choose **Help**.

| Button | What it does | Shortcut |
|---|---|---|
| **Capture** | Starts a new screenshot. Drag to choose an area, or click an available window on Windows or Mac. | Ctrl+N |
| **Open…** | Opens an Annotshot editable file (`.annotshot`) so you can keep editing it. | Ctrl+O |
| **Save…** | Choose a picture, a Word document, a PowerPoint slide or an editable `.annotshot` file. See **Saving** for what the two shortcuts do. | Ctrl+S, Ctrl+Shift+S |
| **Copy image** | Puts the finished picture, with all your marks, on the clipboard. | Ctrl+C |
| **Close picture** | Closes the current picture and returns to the welcome window. | Ctrl+W |
| **Undo** | Takes back the last change. Hover over it to see which change. | Ctrl+Z |
| **Redo** | Puts it back again. | Ctrl+Y or Ctrl+Shift+Z |
| **Settings…** (the gear, far right) | Opens the settings: your own shortcuts, the capture key that works from anywhere, quick capture, and the theme. See "Settings" below. | Ctrl+, (Comma) |

### Row 2: the tools and the object buttons

On the left are the tools: **Select, Text, Callout, Rect, Ellipse, Arrow, Highlight, Pen, Crop**. On the right are the buttons that act on what you have selected: **Duplicate, Front, Back, Delete**.

**Duplicate, Front, Back and Delete show their word beside the icon.** Undo, Redo and Settings… show an icon; hover over a button to see its name and current shortcut.

After you place a shape or finish a pen stroke, Annotshot returns to **Select**. The object you just made is selected, except a pen stroke. Pull its handles to adjust it, or choose a drawing tool to draw another. Crop returns to **Select**. Choosing a drawing tool clears the selection and shows that tool’s starting values in the property strip.

### Row 3: the property strip

The strip names what you are changing: for example, **New arrows**, **This arrow**, **3 arrows** or **3 objects**. It uses two rows when they fit and adds whole rows when the window is narrow. Only controls that apply are shown. A control changes every selected object that has that property. **Head**, **Head size** and **Both ends** appear only for arrows.

Every tool starts with the settings you used last, even after you close and reopen Annotshot. With nothing selected, the strip sets the active tool's starting values (Select and Crop show a plain instruction with no style controls). In Settings → Look, turn off **Start each tool with the settings I used last** to start from factory values, or click **Reset to factory settings** to clear the saved tool values. With that setting off, a starting value you choose applies to the next object only.

## The tools

- **Select**: click an object to select it, drag it to move it, and pull one of its eight square handles to resize it. An arrow has two handles, one at each end. Drag across empty picture to select several objects; Ctrl+click adds or removes one.
- **Text**: click once for a ready-sized text box, or drag to set its width. You start typing right away. The box grows taller when the text needs more room. Double-click a text box later to edit its text again. With factory settings, you start with 32-pixel text and no border.
- **Callout**: a speech bubble. Drag to draw its box (or click once for a ready-sized one) and type, just as in a text box: the same font, size, style, alignment and colors. Its pointer starts below and to the left of the box; select the callout and drag the small square handle at the pointer's end to point at anything. Moving the callout moves the pointer with it; resizing the box leaves the pointer's end where you put it. With factory settings, you start with 32-pixel text and a 4-pixel red outline.
- **Rect**: drag to draw a rectangle (red outline, no fill to start).
- **Ellipse**: drag to draw an ellipse or circle.
- **Arrow**: drag from the tail to where the arrow should point. The head appears at the end where you let go. With an arrow selected, the strip's **Head** picks Filled, Open (two wings), None or Bar (a crossbar), **Head size** picks Small, Medium or Large (the head grows with the line's width too), and **Both ends** puts the same head at the tail as well.
- **Highlight**: drag a see-through yellow band over text, like a highlighter pen. The text underneath stays readable.
- **Pen**: draw freehand while holding the mouse button down.
- **Crop**: drag a box. The picture is cut down to that box, and your objects stay where they were on the picture. A crop never deletes an object: any part that now lies outside the picture stays, drawn faded, and you can still select it and drag it back in. The faded part is never in what you copy or save; the picture you get is exactly the cropped picture. Undo brings the full picture back.

While you are drawing with any tool, a right-click cancels that drawing.

## The property strip, control by control

| Control | What it changes | Works on |
|---|---|---|
| **Font** | The typeface. The bundled **VT323** pixel font appears above your computer’s fonts when it is available. | Text box, callout |
| **Size** | The text size, in pixels (6 to 400). | Text box, callout |
| **Style** | **B** bold, *I* italic. | Text box, callout |
| **Align** | Left, center or right inside the box. | Text box, callout |
| **Text colour** | The color of the letters only. | Text box, callout |
| **Fill** | The background color inside the shape. Changing it never changes the text color. | Text box, callout, rectangle, ellipse, highlight (color only) |
| **No fill** (slashed square) | Makes the inside see-through. | Text box, callout, rectangle, ellipse |
| **Border** (**Line colour** for arrows and pens) | The outline or line color. | Text box, callout, rectangle, ellipse, arrow, pen stroke |
| **No border** (slashed square) | Removes the outline, including for the next shape when nothing is selected; hidden for arrows and pens. | Text box, callout, rectangle, ellipse |
| **Width** | How thick the outline or line is, in pixels (0 to 40). | Same as Border |
| **Line style** | Solid, Dashed, Long dash, Dotted or Dash-dot. | Rectangle, ellipse, arrow, pen stroke |
| **Opacity** | How see-through the whole object is, from 0% (invisible) to 100% (solid). | Every object |
| **Head** | Filled, Open, None or Bar. | Arrow |
| **Head size** | Small, Medium or Large. | Arrow |
| **Both ends** | A head at both ends. | Arrow |

Clicking a color opens a color picker. It has a transparency setting too, so you can make a fill half see-through. A highlight always keeps its own see-through level; Fill changes only its color. While typing, choosing a **Font** from its list or clicking the **Size** arrows lets you continue at the same place in the text.

## Undo while typing

While you are typing in a text box, **Undo** and **Redo** work on your typing, a few letters at a time. When you finish (click outside the box or press **Esc**), the whole edit becomes one step, and Undo takes back the whole edit at once.

Press **Esc** to stop typing. Press **Esc** again to clear the selection.

## Duplicate, Front, Back, Delete

- **Duplicate** (Ctrl+D): makes a copy of the selected objects, a little down and to the right, on top of everything.
- **Front** (Ctrl+] (Right Bracket)): brings the selected objects in front of all the others.
- **Back** (Ctrl+[ (Left Bracket)): sends them behind all the others (but always above the screenshot itself).
- **Delete**: removes the selected objects. The default key is **Delete** on Windows and **Forward Delete** on a Mac.

All four can be undone.

## Close picture and the empty start

**Close picture** (Ctrl+W), at the right of the main toolbar before Undo, closes the picture and returns to the small welcome window. Kept captures and their edits stay in Recent captures.

## The right-click menu

Right-click the picture to copy it, save it or start another capture. The menu also has **Settings…**, **Help**, **Send feedback…**, **About Annotshot…** and **Quit Annotshot**. Right-click an object for **Duplicate**, **Front**, **Back** and **Delete**. While drawing a new object, right-click to cancel the drag.

## Recent captures

The **Recent captures** pane shows your screenshots newest first, with the time or date beneath each one. It starts on the right of the editor. Annotshot removes unedited captures that fall outside the newest 12. Captures with saved edits can stay longer. Quick captures appear here too when keeping captures is on.

- Click a picture in **Recent captures** to reopen it with its saved marks.
- **Right-click** a picture for **Open**, **Delete** (removes the capture and your changes to it at once), **Show in folder**, and **Clear recent captures** (asks once, then empties the pane).
- Each kept capture starts as a PNG in `Pictures/Annotshot/Recent` (the Store app uses `Captures/Recent` in app data). Its saved edits go in a `.annotshot` file beside it. To find these files, right-click the capture and choose **Show in folder**. To remove both, choose **Delete**. If you delete only the PNG yourself, the editable file can still open.
- Drag the pane by its title to the left side of the window, or out of the window to float it; close it with its **×**. Right-click the picture and choose **Recent captures** to bring it back. Annotshot remembers where you left it.
- To stop keeping captures, untick **Keep the last 12 captures in the Recent pane** in **Settings… → Capture**; the pane still shows what is already there.

## Help and About

**Help** (press **F1**, or right-click the picture and choose **Help**) opens this manual inside Annotshot, with a **Keyboard shortcuts** table at the top that shows your keys as they are set now. **Open on GitHub** links to the manual. **Report a problem** links to the project’s issues page. The Help window stays open beside the editor while you work.

**About Annotshot…** shows the version, the publisher, the licence and a link to the project. A **Build** line appears when a build date is available. Open About from the picture’s right-click menu or the **About** tab in **Settings…**.

Use **Send feedback…** in About or the picture’s right-click menu for the project’s feedback link.
<!-- Feedback email: add a feedback email here when a mailbox exists. -->

## Saving

By default, Annotshot keeps each new screenshot in **Recent captures**. It saves your marks automatically after you pause. If you are typing, press **Escape** or click outside the text box to finish the edit. If Annotshot says it could not keep your changes, use **Save…** and choose **Annotshot editable** in another folder.

If you turn off **Keep the last 12 captures in the Recent pane**, choose **Save…** and **Annotshot editable** to keep a new capture editable. Later edits save to that file. When you open a `.annotshot` file, your edits save directly into the file you opened. Reopening a picture starts a new **Undo** history.

Click **Save…**, choose where to save, and pick a file type.

| Type | What you get |
|---|---|
| **PNG image** | The finished picture. The best choice for most uses. Sharp text, any see-through parts kept. |
| **JPEG image** | The finished picture in JPEG format. See-through parts become white. |
| **BMP image** | The finished picture, uncompressed. See-through parts become white. |
| **WebP image** | The finished picture in WebP format. |
| **Word document (.docx)** | The finished picture on page 1 of a Word document, centred. |
| **PowerPoint slide (.pptx)** | The finished picture on one PowerPoint slide, centred. |
| **Annotshot editable (.annotshot)** | Your work, kept editable. |

**What "editable" means:** a PNG or JPEG is a flat photo. Once saved, the text is part of the picture, and you cannot fix a typo without painting over it. A `.annotshot` file keeps the screenshot and every text box, arrow and shape as separate objects. Open it again later with **Open…** and you can still double-click the text to retype it, change its colors, move an arrow or delete a shape. Keep a `.annotshot` copy whenever you may need to change something later.

For a kept capture, the Save window suggests the **Recent** folder and the capture’s name. To keep a separate picture, choose another folder or a new name. For an opened editable file, the Save window starts in that file’s folder. Without an editable file, it suggests the last save folder if available. The last file type you saved is selected.

If the picture already has an editable file, saving another `.annotshot` file makes a separate copy. Later edits still save to the original file. To continue editing the new copy, open it with **Open…**.

With the default shortcuts, **Ctrl+S** (Mac: **Command+S**) saves changes to the current editable file. If the picture has no editable file, it opens the Save window. Click **Save…** or press **Ctrl+Shift+S** (Mac: **Shift+Command+S**) to choose a file.

When a picture has no editable file, a `*` in its title means it has changes you have neither saved nor copied. Annotshot asks about those changes before you close or replace the picture.

## Word and PowerPoint

Choose **Word document** to save a `.docx` with the marked picture centred between the margins. Choose **PowerPoint slide** to save a `.pptx` with the picture centred on one slide.

## Copy and paste a picture

If you are typing, press **Escape** to finish. Click **Copy image**, switch to your message or document, and choose **Paste** where you want the picture. If the app does not accept pasted pictures, use **Save…** to save a **PNG image** you can attach.

The default shortcut for **Copy image** is **Ctrl+C** on Windows or **Command+C** on a Mac.

Copying or saving a picture counts as "done": the next **Capture** will not ask you to save, unless you have made more changes since.

## Opening an editable file

Click **Open…** (Ctrl+O) and choose a `.annotshot` file. Everything comes back as you left it, still editable. **Open…** opens only Annotshot editable files; it does not open ordinary PNG or JPEG pictures in this version.

With the Windows zip, start Annotshot once before trying to open a `.annotshot` file from File Explorer. If double-clicking a file in File Explorer or Finder opens another app, use **Open…** in Annotshot. On Linux, use **Open…** or pass the file name when starting Annotshot.

## Keyboard shortcuts

On a Mac, use the **Command** key wherever this table says Ctrl.

| Keys | Does |
|---|---|
| Ctrl+N | Capture |
| Ctrl+O | Open… |
| Ctrl+S | Save changes to the current editable file, or open the Save window if there is none |
| Ctrl+Shift+S | Save… (always opens the Save window) |
| Ctrl+C | Copy image |
| Ctrl+Z | Undo |
| Ctrl+Y or Ctrl+Shift+Z | Redo |
| Ctrl+D | Duplicate |
| Ctrl+] (Right Bracket) | Front |
| Ctrl+[ (Left Bracket) | Back |
| Delete on Windows; Forward Delete on a Mac | Delete |
| Ctrl+W | Close picture |
| Ctrl+, (Comma) | Settings… |
| F1 | Help |
| Control+Command+Space on Mac, Ctrl+Alt+Space on Windows | Capture from anywhere |
| Esc | Stop typing, then clear the selection; during capture, cancel |
| V / T / B / R / E / A / H / P / C | Select / Text / Callout / Rect / Ellipse / Arrow / Highlight / Pen / Crop |
| Ctrl+0 | Fit |
| Ctrl+1 | 100 % |
| Ctrl+= (Equals) / Ctrl+- (Minus) | Zoom in / Zoom out |
| Ctrl + mouse wheel | Zoom in and out |
| Double-click a text box | Edit its text |

You can change action and tool keys in **Settings…**. Tool letters work with the picture, a property button or the **Opacity** slider focused; text fields, drop-down lists and **Recent captures** keep your typing or search. Buttons, hints and Help show your current keys in words for your platform.

## Settings

Click the gear at the right end of the top row, or press **Ctrl+, (Comma)**. Every change takes effect at once and is kept for next time; click **Close** when you are done.

**Shortcuts.** Each button and tool has a row with its key drawn as keycaps. **Capture from anywhere** is first, followed by **Capture**, **Copy image** and **Save…**; click **More shortcuts (24)** for the other rows. Click the key box and press the new key, holding any modifiers with it; the change takes effect at once. Hints below the key box explain which extra key to press. A key that another button already uses is refused, and one line at the bottom names that button. **Reset** puts one row back to Annotshot's own key; **Reset all** puts every row back. Clear an action or tool’s box (the small ×) to leave it with no key.

**Capture from anywhere.** One key that starts a capture even while another app is in front. The default capture key is Control+Command+Space on Mac and Ctrl+Alt+Space on Windows. Annotshot comes back if it was minimized and starts a capture with your saved wait and frozen-screen choice. Updates keep your saved key. Click Reset beside Capture from anywhere to use the current default. On Mac, Control+Command+Space can also open Emoji & Symbols. If the picker opens instead of a capture, or you want the shortcut back for emoji, choose Change key or Turn off from the key button beside Capture. Tick **Off** to turn it off; clearing this key box only lets you enter a replacement and keeps your working key. If the system or another app holds the key you pick, Annotshot keeps the key you had. If no key is registered, the requested key stays selected for retry. The amber key button offers a way to choose another key. Use Ctrl, Alt or Shift (on a Mac: Control, Option, Shift or Command) with a letter, a digit or Space, or an F key alone. On a Mac, keypad keys cannot be used for **Capture from anywhere**. On Windows, use the digit keys above the letters instead of keypad digits. Reset all restores the default capture key and keeps your Off setting. On Linux this row is greyed out: it is not available on Linux yet.

**Capture.** Copying starts on. Minimizing after copying starts off. For **Keep Annotshot running when its window is closed**, see **Closing and quitting**.

- **Copy to the clipboard right after each capture.** On to begin with: paste works at once, with no click on **Copy image**. After you add arrows or text, use **Copy image** again to copy the marked-up picture. The picture goes straight to the clipboard; the status line says, for example, "Copied 1280 × 720 — Ctrl+V to paste". It counts as copied, so the next capture does not ask about saving.
- **Then minimize the window.** (Only with the first box on.) After the copy the window goes to the taskbar (the Dock on a Mac). Click Annotshot in the Dock to bring it back. On Windows: Click Annotshot on the taskbar to bring it back.

With both on and the capture key, a screenshot is one key, one drag or window click, and a paste. With **Wait after pick · Off**, releasing the gesture takes the picture.

- **Keep the last 12 captures in the Recent pane.** On to begin with. Off: captures are no longer kept (see "Recent captures").

**Look — Themes.** One pull-down, **Theme**, with three looks; the one you pick shows at once on the whole app (the editor, Settings, About, Help and the Recent pane) and is kept for next time. Your pictures, shapes and text, and every picture you save or copy, look the same in all three.

- **Light** (to begin with): pale grey and white with a blue accent.
- **Dark**: dark slate grey with light text and a brighter blue accent.
- **Retro**: an amber-on-black terminal look, with the pixel font **VT323** for every word of the app. VT323 comes with Annotshot (nothing to install) and is licensed under the Open Font License.

## Known limits in this first version

- **Linux:** The capture control uses a still image. Drag to choose an area or click for the whole screen.
- **One screen per capture.** A region cannot stretch across two monitors.
- **No scrolling capture, no screen recording and no picture library yet.** Annotshot must be open (it may be minimized) for the capture key to work. On Linux there is no capture key yet: start each capture from Annotshot's window.
- **Linux:** no double-click on saved `.annotshot` files yet. Use **Open…**, or start Annotshot with the file's name after it.
- **One style per text box.** You cannot make one word bold and the next one plain inside the same box; use two boxes.
- If another app uses your capture key, click the key button beside **Capture** and choose **Change key**.

## How Annotshot was built

Annotshot’s maker directed the work and tested the app on screen. AI models wrote the code. One model prepared a brief, another built from it, and a model from a different vendor reviewed the result. The maker decided when to release it.

The first commit was on November 3, 2026. That day the Windows app could already capture a screenshot, add an arrow and save the picture. The project notes record submission to the Microsoft Store on November 15, an approval email dated November 17 and a check of the public listing on November 19.

The study ends on November 19, 2026. By the end of that day, the project had 511 commits across 13 dates. Each date counts once, however much work happened that day. The app had about 9,600 lines of Python code, with another 14,500 or so in its tests.

One AI model estimated that an experienced desktop programmer working alone would need 85 to 130 full-time working days to build and ship the app as it stood then. No programmer built a comparison copy or checked that estimate.

## Licence

Annotshot is made by Bill Moldestad and is MIT-licensed. It uses Qt for Python and Qt 6 under the LGPL v3, and python-docx, python-pptx and their helpers under their own licences. Its pixel font, VT323 (by Peter Hull), is under the SIL Open Font License 1.1. In **About Annotshot…**, choose **Third-party notices** to read the licence texts included with your copy.

## For developers

### From source

With Python 3.12, you can use a virtual environment in the project folder. Example commands follow.

**Windows**

```text
python -m venv .venv
.venv\Scripts\python -m pip install PySide6-Essentials==6.12.0 python-docx==1.2.0 python-pptx==1.0.2 pytest
.venv\Scripts\python -m annotshot
```

**macOS or Linux**

```text
python3 -m venv .venv
.venv/bin/python -m pip install PySide6-Essentials==6.12.0 python-docx==1.2.0 python-pptx==1.0.2 pytest
.venv/bin/python -m annotshot
```

To run the tests, use the same environment’s Python with `-m pytest -q`. If an export reports missing Word or PowerPoint libraries, use the install command in that message.
