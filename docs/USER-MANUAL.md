# Annotshot user manual

Tuesday 2026-11-10 · for Annotshot 0.4.0

## What Annotshot is

Annotshot takes a picture of part of your screen and lets you mark it up the way you would mark up a slide in PowerPoint. You drag out a text box, type into it, and give it its own text color, its own background fill and its own border. You can add arrows, speech-bubble callouts, rectangles, ellipses, highlighter bands and freehand pen strokes, crop the picture, and undo anything. When you are done, you copy the picture and paste it into Paint, PowerPoint, Teams or an email, or you save it as a file. You can also save an editable copy so you can reopen it later and keep changing the text.

This is a first version. It does one job: capture, mark up, copy or save. It has no screen recording, scrolling capture or picture library; it keeps only your last 12 captures, in the Recent captures pane.

Annotshot is made by Stet Software.

## Install and start

Download the app from the repository's Releases page — the three download buttons at the top of the README — never from the green Code button, which is the source code.

### Windows (10 and 11)

There are two roads. The installer is the usual one: it puts Annotshot in the Start menu and registers the `.annotshot` file type. The zip needs no installing: the folder runs wherever you put it.

#### The installer — five steps

1. **Download:** click **Download for Windows** at the top of the Annotshot page on GitHub. `Annotshot-0.4.0-setup.exe` appears in your Downloads folder.
2. **Run it:** open Downloads and double-click `Annotshot-0.4.0-setup.exe`. Windows will show a blue box, **Windows protected your PC**, because Annotshot is new and not yet signed: click **More info**, then **Run anyway**. It appears only the first time.

   <!-- picture: windows-protected.png is captured on a Windows computer; when it exists, insert this line here: ![Windows protected your PC — click More info, then Run anyway](windows-protected.png) -->
3. **Next:** if it asks whether to install for you only or for all users, click **Install for me only** (no administrator is needed). Accept the licence and click **Next**.
4. **Pick a folder:** keep the folder it suggests (your own `AppData\Local\Programs\Annotshot`) or click **Browse…** and pick another, then **Next**. Tick **Create a desktop shortcut** if you want one, click **Next**, then **Install**, then **Finish**.
5. **Start it:** Annotshot is in the Start menu — press the Windows key, type `Annotshot` and press Enter.

#### The zip — three steps

1. **Download:** on the Annotshot page on GitHub open **Releases** and download `Annotshot-0.4.0-windows.zip`. It appears in your Downloads folder.
2. **Unzip:** open Downloads, right-click `Annotshot-0.4.0-windows.zip`, choose **Extract All…**, then click **Extract**. A folder named `Annotshot-0.4.0-windows` opens, and inside it is a folder named `Annotshot`. That `Annotshot` folder is the app — keep it whole, and move it anywhere you like (for example into `C:\Program Files` or onto `D:\`).
3. **Start it:** open the `Annotshot` folder and double-click **Annotshot.exe** (the blue A). Windows will show a blue box, **Windows protected your PC**, because Annotshot is new and not yet signed: click **More info**, then **Run anyway**. It appears only the first time.

   <!-- picture: windows-protected.png is captured on a Windows computer; when it exists, insert this line here: ![Windows protected your PC — click More info, then Run anyway](windows-protected.png) -->

To start it from the Start menu next time: right-click **Annotshot.exe** → **Pin to Start**.

### macOS — four steps

The macOS app is for Macs with Apple silicon (M1 or newer); it does not run on a Mac with an Intel processor.

1. **Download:** click **Download for macOS** at the top of the Annotshot page on GitHub. `Annotshot-0.4.0-macos.zip` appears in your Downloads folder.
2. **Unzip and move:** open Downloads and double-click `Annotshot-0.4.0-macos.zip`. **Annotshot.app** (the blue A) appears next to it. Drag **Annotshot.app** into your **Applications** folder.
3. **Tell macOS the app is safe:** Annotshot is not signed by Apple yet, so macOS refuses to open it until you clear its download flag. Open **Terminal** (press ⌘ Space, type `Terminal`, press Return), paste this line and press Return:

   ```
   xattr -cr /Applications/Annotshot.app
   ```

4. **Start it:** open **Applications** and double-click **Annotshot**. The first time you click **Capture**, macOS has to allow Annotshot to take pictures of your screen. macOS shows its own question the first time — click **Allow**. macOS calls this setting **Screen & System Audio Recording**; Annotshot takes still pictures only, never video or sound. Until macOS allows it, Annotshot takes no picture and says so in a small window: click **Open System Settings** and switch Annotshot on under **Privacy & Security → Screen & System Audio Recording**. Annotshot then restarts by itself after keeping any changes to a picture that has a file; if the write fails, it stays open with your edits. (Click **Not now** to close the window; the status line keeps saying "Capture is waiting for macOS to allow it".) If Annotshot is already switched on there and macOS still refuses: remove it with −, add it again with + from Applications, and switch it on. If capture is still refused after a restart, the next **Capture** press offers **Restart Annotshot** to try again.

### Linux — three steps

1. **Download:** click **Download for Linux** at the top of the Annotshot page on GitHub. `Annotshot-0.4.0-linux.zip` appears in your Downloads folder.
2. **Unzip:** right-click the zip in your file manager and choose **Extract Here** (or in a terminal: `cd ~/Downloads && unzip Annotshot-0.4.0-linux.zip`). A folder named `Annotshot` appears; it is the app — keep it whole, and move it anywhere you like (for example to `~/Apps/Annotshot`).
3. **Start it:** double-click the file named **Annotshot** inside that folder (or in a terminal: `~/Downloads/Annotshot/Annotshot`). If it says **permission denied**, run `chmod +x ~/Downloads/Annotshot/Annotshot` once, then start it again.

No one has run the Linux build by hand yet: the release workflow builds it and runs its self-check on an Ubuntu runner, and that is all it has been through. Two things to know:

- **Wayland:** Qt's screen grab returns an empty picture on Wayland, the default session on new GNOME and KDE desktops, so a capture there comes back blank. Until Annotshot uses the desktop's own screenshot service, log in to an X11 (**Xorg**) session where the login screen offers one (for example **Ubuntu on Xorg**, behind the gear button on the login screen).
- **A missing library:** if Annotshot does not start and a terminal shows that the Qt platform plugin **xcb** could not be loaded, install it with `sudo apt install libxcb-cursor0` (Debian, Ubuntu and relatives), then start Annotshot again.

**You should see** — on every system — a window titled **Annotshot — Untitled** with a blue **Capture** button at the top left.

### After installing

- **Windows:** the installer registers the `.annotshot` file type, so a double-click on a saved file opens Annotshot. With the zip, start Annotshot once before you double-click a saved `.annotshot` file; it registers the file type each time it starts. If Windows still asks **How do you want to open this file?** or opens another program, right-click the file, choose **Open with**, then **Choose another app**, pick **Annotshot**, tick **Always use this app to open .annotshot files**, and click **OK**. On a computer managed by an organisation, apps that are not signed may be blocked: if the blue box shows no **Run anyway**, or **Annotshot.exe** will not start, the computer's administrator has to allow it.
- **macOS:** the first **Capture** needs macOS to allow it, as in step 4 above. A double-click on a saved `.annotshot` file in Finder opens it in Annotshot once the app is in **Applications**.
- **Linux:** no double-click on saved files yet. Use **Open…** inside Annotshot, or start Annotshot with the file's name after it: `~/Apps/Annotshot/Annotshot picture.annotshot`.

### Updating to a new version

- **Windows, the installer:** close Annotshot, download the new `Annotshot-<version>-setup.exe` and run it: it replaces the old copy in place, in the same folder, and keeps your settings.
- **Windows, the zip:** close Annotshot, delete the old `Annotshot` folder, unzip the new download in its place, and start it once so a double-click on a saved file uses the new copy.
- **macOS:** drag the new **Annotshot.app** into **Applications** and choose **Replace**. Run the Terminal line from step 3 again (every new download is flagged again). Annotshot is not signed by Apple yet, so after every update macOS asks again before Annotshot can take pictures of your screen: click **Allow**, or switch Annotshot on under **Privacy & Security → Screen & System Audio Recording** as in step 4. Nothing is broken. If Annotshot is already switched on there and macOS still refuses: remove it with −, add it again with + from Applications, and switch it on. Annotshot then restarts by itself after keeping any changes to a picture that has a file; if the write fails, it stays open with your edits. If capture is still refused after a restart, the next **Capture** press offers **Restart Annotshot** to try again.
- **Linux:** close Annotshot and replace the `Annotshot` folder with the one from the new zip.

### Removing Annotshot

- **Windows, the installer:** open **Settings → Apps**, find **Annotshot**, and click **Uninstall**. Your pictures and `.annotshot` files stay where you saved them.
- **Windows, the zip:** delete the `Annotshot` folder.
- **macOS:** drag **Annotshot.app** from **Applications** to the Bin.
- **Linux:** delete the `Annotshot` folder.

## Privacy

Annotshot works entirely on this computer. It has no internet code: it cannot upload, sync or report anything, and it never checks for updates by itself. Your captures are saved only in your Pictures folder, under Annotshot/Recent (or, for the Microsoft Store app, in your app data folder under Captures/Recent), and wherever you choose to save them. It opens your web browser only when you click a link, such as the project page. The source code is public, so anyone can check this.

## The opening window

Each launch opens a small welcome window. It shows the current capture key, privacy information, and the newest four captures. **Change keys** opens Settings → Shortcuts. Click a recent capture or **Open a saved file…** to open the editor. Opening an editable file from your file manager also opens the editor directly. **Close picture** returns to welcome. Every capture and its edits stay in Recent.

## Closing and quitting

**Keep Annotshot running when its window is closed** is on in Settings → Capture. Closing the window keeps your edits, returns to welcome, and hides the window. The capture-from-anywhere key stays active. A capture brings back the editor. Cancelling with Esc leaves a hidden window hidden.

On macOS, click Annotshot in the Dock to reopen welcome. On Windows and Linux, the Annotshot tray icon offers **Capture** with your current key, **Open Annotshot**, and **Quit Annotshot**. Clicking the icon reopens the window. The first hide shows a message explaining that Annotshot is still running. If the tray is unavailable, closing quits.

**Quit Annotshot** (Command+Q on macOS) exits through the existing save guard. Turn off **Keep Annotshot running when its window is closed** to quit when closing the window.

If Annotshot cannot keep your last changes to a picture when you close its window or quit (a full disk, or a folder that is gone), it stays open and asks: **Save a copy…** somewhere else, **Discard changes**, or **Cancel** to go on working.

## The first ten seconds

1. Click **Capture** in the opening window or editor, or press **Ctrl+N** (⌘N on a Mac). Return or Space in the opening window also starts Capture.
2. On Windows and macOS, the screen stays live: a video keeps playing while you pick the moment. The dark capture bar has a bright cyan border and glow, and sits near the bottom of the screen holding your pointer.
3. Each live session starts ready for either gesture. Drag a rectangle to capture an area, or click a window to capture it with its title. The picture is taken on release. **Area** restricts capture to drags. **Window** restricts it to clicks on windows. Click the checked choice again to return to both gestures. **Whole screen** takes the screen holding the bar in one click. The size label is in device pixels.
4. Every capture starts with no area selected. When the last area still fits an attached screen, **Same area** appears as a plain button on the bar, in live capture and Freeze. Hover over it to preview the area. Moving away hides the preview. Click it once to capture that area. No key or double-click takes the last area. In live capture, Return, Enter and Space take no picture. In Freeze, they can take a selection you made in this session. The bar and frame disappear before the shot.
5. **Timer** delays a live shot by **3 s**, **5 s** or **10 s**; **Off** takes it straight away. A countdown appears in the bar. **Esc**, a right-click, or **Cancel** cancels, including during the countdown.

**Freeze** takes a still to choose from. In Area, releasing a drag captures at once (a click takes the whole screen, or a window on Windows); in Window, a click captures that window; in Whole screen, a click captures the screen. Timer is disabled while frozen. Untick Freeze to return to the moving screen. If the platform cannot provide a translucent capture window, capture starts frozen.

Annotshot remembers the timer and Freeze choice. Every live session starts ready for both gestures. The Same area button is available when that screen is still attached and the rectangle fits. Each shot stays on one screen.

On **Linux**, capture keeps the frozen screen and has no capture bar: drag an area or click for the whole screen. Esc or a right-click cancels.

Now click **Text**, click on the picture, and type. Then **Copy image** and paste it anywhere, or **Save…** as a picture, a Word document or a PowerPoint slide.

## The editor, row by row

The Annotshot window opens in the middle of your screen at a moderate size, never full screen, and it remembers the size you leave it at. After a capture it grows to fit the picture, up to 80 % of your screen; a bigger picture scrolls or zooms inside the window.

The bottom of the window shows the picture's size in pixels and a zoom button. Click the percent for **Fit**, **100 %**, **200 %**, **Zoom in** or **Zoom out**. Fit uses 100 % when the picture already fits. Hold **Ctrl** and turn the mouse wheel to zoom. Zoom changes only your view, never the picture.

### Row 1: the picture

| Button | What it does | Shortcut |
|---|---|---|
| **Capture** | Takes a new screenshot (drag a region or click a window). If your current picture has changes you have not saved or copied, Annotshot asks first. | Ctrl+N |
| **Open…** | Opens an Annotshot editable file (`.annotshot`) so you can keep editing it. | Ctrl+O |
| **Save…** | Saves the picture as PNG, JPEG, BMP or WebP, or saves an editable Annotshot file. See "Saving" below. | Ctrl+S, Ctrl+Shift+S |
| **Copy image** | Puts the finished picture, with all your marks, on the clipboard. | Ctrl+C |
| **Close picture** | Removes the picture and starts empty. If your picture has changes you have not saved or copied, Annotshot asks first. | Ctrl+W |
| **Undo** | Takes back the last change. Hover over it to see which change. | Ctrl+Z |
| **Redo** | Puts it back again. | Ctrl+Y or Ctrl+Shift+Z |
| **Settings…** (the gear, far right) | Opens the settings: your own shortcuts, the capture key that works from anywhere, quick capture, and the theme. See "Settings" below. | Ctrl+, |

### Row 2: the tools and the object buttons

On the left are the tools: **Select, Text, Callout, Rect, Ellipse, Arrow, Highlight, Pen, Crop**. On the right are the buttons that act on what you have selected: **Duplicate, Front, Back, Delete**.

**Duplicate, Front, Back and Delete show their word beside the icon.** Undo, Redo and Settings… show an icon; hover over a button to see its name and current shortcut.

A drawing tool stays selected until you choose another tool. The object you just made is selected, except a pen stroke. Pull its handles to adjust it, or press elsewhere to draw another. Crop returns to **Select**.

### Row 3: the property strip

The strip names what you are changing: for example, **New arrows**, **This arrow**, **3 arrows** or **3 objects**. It keeps two rows for every tool, so the picture stays in place. Only controls that apply are shown. A control changes every selected object that has that property. **Head**, **Head size** and **Both ends** appear only for arrows.

Every tool starts with the settings you used last, even after you close and reopen Annotshot. With nothing selected, the strip sets the active tool's starting values (Select and Crop show a plain instruction with no style controls). In Settings → Look, turn off **Start each tool with the settings I used last** to start from factory values, or click **Reset to factory settings** to clear the saved tool values.

## The tools

- **Select**: click an object to select it, drag it to move it, and pull one of its eight square handles to resize it. An arrow has two handles, one at each end. Drag across empty picture to select several objects; Ctrl+click adds or removes one.
- **Text**: click once for a ready-sized text box, or drag to set its width. You start typing right away. The box grows taller when the text needs more room. Double-click a text box later to edit its text again.
- **Callout**: a speech bubble. Drag to draw its box (or click once for a ready-sized one) and type, just as in a text box: the same font, size, style, alignment and colors. Its pointer starts below and to the left of the box; select the callout and drag the small square handle at the pointer's end to point at anything. Moving the callout moves the pointer with it; resizing the box leaves the pointer's end where you put it.
- **Rect**: drag to draw a rectangle (red outline, no fill to start).
- **Ellipse**: drag to draw an ellipse or circle.
- **Arrow**: drag from the tail to where the arrow should point. The head appears at the end where you let go. With an arrow selected, the strip's **Head** picks a filled head, an open one (two strokes) or none, **Head size** picks Small, Medium or Large (the head grows with the line's width too), and **Both ends** puts the same head at the tail as well.
- **Highlight**: drag a see-through yellow band over text, like a highlighter pen. The text underneath stays readable.
- **Pen**: draw freehand while holding the mouse button down.
- **Crop**: drag a box. The picture is cut down to that box, and your objects stay where they were on the picture. A crop never deletes an object: any part that now lies outside the picture stays, drawn faded, and you can still select it and drag it back in. The faded part is never in what you copy or save; the picture you get is exactly the cropped picture. Undo brings the full picture back.

While you are drawing with any tool, a right-click cancels that drawing.

## The property strip, control by control

| Control | What it changes | Works on |
|---|---|---|
| **Font** | The typeface. **VT323**, a retro pixel font that comes with Annotshot, is first in the list (above a line, then your computer's own fonts); it looks the same on every computer. | Text box, callout |
| **Size** | The text size, in pixels (6 to 400). | Text box, callout |
| **Style** | **B** bold, *I* italic. | Text box, callout |
| **Align** | Left, center or right inside the box. | Text box, callout |
| **Text colour** | The color of the letters only. | Text box, callout |
| **Fill** | The background color inside the shape. Changing it never changes the text color. | Text box, callout, rectangle, ellipse, highlight (color only) |
| **No fill** (slashed square) | Makes the inside see-through. | Text box, callout, rectangle, ellipse |
| **Border** (**Line colour** for arrows and pens) | The outline or line color. | Text box, callout, rectangle, ellipse, arrow, pen stroke |
| **No border** (slashed square) | Removes the outline; hidden for arrows and pens. | Text box, callout, rectangle, ellipse |
| **Width** | How thick the outline or line is, in pixels (0 to 40). | Same as Border |
| **Line style** | Solid, Dashed or Dotted. | Rectangle, ellipse, arrow, pen stroke |
| **Opacity** | How see-through the whole object is, from 0% (invisible) to 100% (solid). | Every object |
| **Head** | Filled, Open or None. | Arrow |
| **Head size** | Small, Medium or Large. | Arrow |
| **Both ends** | A head at both ends. | Arrow |

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

## Close picture and the empty start

**Close picture** (Ctrl+W), at the right of the main toolbar before Undo, closes the picture and returns to the small welcome window. Kept captures and their edits stay in Recent captures.

## The right-click menu

Right-click the picture for a short menu: **Copy image**, **Save…**, then **Close picture**, **Capture** and **Recent captures** (ticked while the pane shows), then **Settings…**, **Help**, **Send feedback…** and **About Annotshot…** last. Right-click an object and the menu also has **Duplicate**, **Front**, **Back** and **Delete** for it (the object is selected first). The menu shows each item's shortcut. While you are dragging out a new object, a right-click only cancels that drag and shows no menu.

## Recent captures

The **Recent captures** pane on the right of the window keeps your last 12 captures as small pictures, newest at the top — each one showing what you drew on it, updated within a second of each change — each with the time it was taken underneath ("12:34" today, "Tue 12:34" earlier this week, the date before that). Quick captures are kept too; files you open are not (they are yours already).

- **Click** a picture to open that capture again as the current picture, with everything you drew on it. There is nothing to save: every change you make to a capture is kept the moment you make it, so you can click from one capture to another, close Annotshot, and find your work just as you left it.
- **Right-click** a picture for **Open**, **Delete** (removes the capture and your changes to it at once), **Show in folder**, and **Clear recent captures** (asks once, then empties the pane).
- Each capture is two files in `Pictures/Annotshot/Recent`: the full-size PNG exactly as it was taken (never changed, so the original is always there), and, from your first change on, a `.annotshot` file beside it with everything you drew. When the 13th capture arrives, the oldest one you never changed is deleted; a capture you have drawn on is never deleted for space — only **Delete** or **Clear recent captures** removes it. A file you delete there yourself simply disappears from the pane.
- Drag the pane by its title to the left side of the window, or out of the window to float it; close it with its **×**. Right-click the picture and choose **Recent captures** to bring it back. Annotshot remembers where you left it.
- To stop keeping captures, untick **Keep the last 12 captures in the Recent pane** in **Settings… → Capture**; the pane still shows what is already there.

## Help and About

**Help** (press **F1**, or right-click the picture and choose **Help**) opens this manual inside Annotshot, with a **Keyboard shortcuts** table at the top that shows your keys as they are set now. Two buttons at the bottom open pages in your browser: **Open on GitHub** shows the newest copy of this manual, and **Report a problem** opens the page where you can tell us what went wrong. The Help window stays open beside the editor while you work.

**About Annotshot…** (the last line of the right-click menu, and the **About** tab in **Settings…**) shows the version, a **Build** line with the date and time this copy was made (two copies with the same version number are told apart by it), who makes Annotshot (Stet Software), the project's page, its licence, and a **Third-party notices** button with the licence texts of the parts Annotshot is built from.

**Send feedback…**, in the right-click menu and About, opens a page in your browser where you can choose **Report a bug** or **Suggest an improvement**.
<!-- Feedback email: add the Stet Software mailbox here when it exists. -->

## Saving

You never have to save a capture. Every change you make to a capture is kept the moment you make it, in the Recent folder beside the original picture (see **Recent captures**); close Annotshot and open it again, then click the capture in Recent to find everything on it. A file you opened with **Open…** keeps itself the same way: your changes are written into that file as you work. **Undo** takes back mistakes while Annotshot is open; it does not reach back past a restart.

**Save…** makes a copy somewhere else. Click it to open the Save window. Pick a file type from the "Save as type" list:

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

A `.annotshot` copy you save this way is a second copy: the capture in Recent captures is still the one that keeps itself.

**Ctrl+S** on a capture or an opened file writes its changes at once without asking. **Ctrl+Shift+S** always opens the Save window.

Only when **Keep the last 12 captures in the Recent pane** is off does a capture have no file of its own; then Annotshot asks "Save your changes to this project first?" before it replaces a capture you changed. The window title shows the file name (a Recent capture by its date and time), with a `*` only for such a capture with changes not yet saved.

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
| Ctrl+W | Close picture |
| Ctrl+, | Settings… |
| F1 | Help |
| Ctrl+Shift+2 | Capture, even while Annotshot is not in front (Windows and macOS) |
| Esc | Stop typing, then clear the selection; during capture, cancel |
| V / T / B / R / E / A / H / P / C | Select / Text / Callout / Rectangle / Ellipse / Arrow / Highlight / Pen / Crop |
| Ctrl+0 | Fit |
| Ctrl+1 | 100 % |
| Ctrl+= / Ctrl+- | Zoom in / Zoom out |
| Ctrl + mouse wheel | Zoom in and out |
| Double-click a text box | Edit its text |

You can change action and tool keys in **Settings…**. Tool letters work with the picture focused; while typing in a text object or the Font box, they enter letters. Buttons, hints and Help show your current keys in your platform’s notation.

## Settings

Click the gear at the right end of the top row, or press **Ctrl+,**. Every change takes effect at once and is kept for next time; click **Close** when you are done.

**Shortcuts.** Each button and tool has a row with its key. Click the key box, press the new key, and wait a moment. A key that another button already uses is refused, and one line at the bottom names that button. **Reset** puts one row back to Annotshot's own key; **Reset all** puts every row back. Clear a box (the small x) to leave a button with no key.

**Capture from anywhere.** One key that starts a capture even while another app is in front: **Ctrl+Shift+2** to begin with (⇧⌘2 on a Mac). Annotshot comes back if it was minimized and starts live capture. A key you have already chosen stays unchanged. Tick **Off** to turn it off. If the system or another app already holds the key you chose, one line says so; pick another. Use Ctrl, Alt or Shift with a letter or a digit, or an F key alone. On Linux this row is greyed out: it is not available on Linux yet.

**Capture.** Two boxes, the first on and the second off to begin with, and the Recent captures box, on to begin with (the **About** tab, last, is described under "Help and About"):

- **Copy to the clipboard right after each capture.** On to begin with: paste works at once, with no click on **Copy image**. After you add arrows or text, use **Copy image** again to copy the marked-up picture. The picture goes straight to the clipboard; the status line says, for example, "Copied 1280 × 720 — Ctrl+V to paste". It counts as copied, so the next capture does not ask about saving.
- **Then minimize the window.** (Only with the first box on.) After the copy the window goes to the taskbar (the Dock on a Mac). The capture key or a click brings it back.

With both on and the capture key, a screenshot is one key, one drag or window click, and a paste. Releasing the gesture takes the picture.

- **Keep the last 12 captures in the Recent pane.** On to begin with. Off: captures are no longer kept (see "Recent captures").

**Look — Themes.** One pull-down, **Theme**, with three looks; the one you pick shows at once on the whole app (the editor, Settings, About, Help and the Recent pane) and is kept for next time. Your pictures, shapes and text, and every picture you save or copy, look the same in all three.

- **Light** (to begin with): pale grey and white with a blue accent.
- **Dark**: dark slate grey with light text and a brighter blue accent.
- **Retro**: an amber-on-black terminal look, with the pixel font **VT323** for every word of the app. VT323 comes with Annotshot (nothing to install) and is licensed under the Open Font License.

## Known limits in this first version

- **Linux captures the earlier way.** The capture bar, live capture, picking a window and the timer are for Windows and macOS. On Linux the screen freezes first: drag a region, or click without dragging for the whole screen.
- **One screen per capture.** A region cannot stretch across two monitors.
- **No scrolling capture, no screen recording and no picture library yet.** Annotshot must be open (it may be minimized) for the capture key to work. On Linux there is no capture key yet: start each capture from Annotshot's window.
- **Linux on Wayland:** Qt's screen grab returns an empty picture on Wayland, the default session on new GNOME and KDE desktops, so a capture there comes back blank. Until Annotshot uses the desktop's own screenshot service, use an X11 (Xorg) session where the login screen offers one. No one has run the Linux build by hand yet.
- **Linux:** no double-click on saved `.annotshot` files yet. Use **Open…**, or start Annotshot with the file's name after it.
- **One style per text box.** You cannot make one word bold and the next one plain inside the same box; use two boxes.

## Licence

Annotshot is made by Stet Software and is MIT-licensed. It uses Qt for Python and Qt 6 under the LGPL v3, and python-docx, python-pptx and their helpers under their own licences. Its pixel font, VT323 (by Peter Hull), is under the SIL Open Font License 1.1. The licence texts travel inside the app's folder: a `licenses` folder with the GNU texts and the font's licence, plus `LICENSE` and `THIRD-PARTY-NOTICES.md` in the public download. **About Annotshot… → Third-party notices** shows them inside the app.

## For developers

### From the source code (any system with Python 3.12)

In the Annotshot folder, make a virtual environment, install Qt for Python, the Word / PowerPoint libraries and pytest (for the tests: `python -m pytest -q`), and start the app. If a Word or PowerPoint save says this copy needs two more parts, run the `pip install` line the message shows.

```
python -m venv .venv
.venv/bin/pip install PySide6-Essentials==6.12.0 python-docx==1.2.0 python-pptx==1.0.2 pytest
        (Windows: .venv\Scripts\pip install PySide6-Essentials==6.12.0 python-docx==1.2.0 python-pptx==1.0.2 pytest)
.venv/bin/python -m annotshot                       (Windows: .venv\Scripts\python -m annotshot)
```
