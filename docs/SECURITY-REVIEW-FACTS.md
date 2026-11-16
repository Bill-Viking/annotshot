# Annotshot 0.4.2 — security review

Annotshot captures and annotates still screenshots and exports images, editable projects, Word documents and PowerPoint slides.

## Capture and background operation
Capture starts through a button, tray action or keyboard shortcut; source inspection found no startup or recurring capture.
By default, closing the window leaves the app and its capture key running on macOS and on Windows when a tray is available.
“Quit Annotshot” exits after checking unsaved work; disabling keep-running restores quit-on-close.
The source and installer definitions contain no login-start registration.

## Pictures, files and clipboard
By default, selected captures are saved in full as PNG files in `Pictures/Annotshot/Recent` beneath the user's home folder, without consulting the redirected Pictures-folder setting.
Windows builds with package identity instead use `Captures/Recent` beneath Qt's app-data location.
Editing a retained capture creates a separate editable project containing a base image and annotations, and later edits autosave into that project.
Automatic pruning removes only unedited captures beyond the newest twelve; edited captures can remain indefinitely.
Turning retention off leaves existing files in place; Recent's Delete and Clear remove both the capture and its editable project.
By default, each capture is also copied to the clipboard; this option can be disabled.
Settings store preferences and paths, and the app provides no encryption layer for its files.
Exports go to selected destinations; project and Office saves create temporary files beside their destinations.
Live macOS window capture also creates a temporary PNG in a temporary directory.
The bundled app's `--check` self-check can write a local `check.txt` verdict or traceback beside the executable, or in app data for Windows builds with package identity.

## Network and updates
Source inspection found no network-client imports, automatic updater, usage reporting or remote crash reporting.
Help and feedback actions open public web pages through the system handler without attaching screenshots.
Clicked links in the bundled manual also use the system handler, and Show in folder passes the local capture-folder path.
Runtime network traffic from dependencies and external handlers has not been tested here.

## Permissions and opened files
The app contains no administrator-elevation request and requests Screen Recording permission on macOS.
Its macOS helpers capture windows, open permission settings, check permission in a child process and restart the app through a shell helper.
Editable projects are ZIP files whose named JSON and PNG contents are read without extracting files to disk.
The loader imposes no archive-size, decompressed-member-size, image-dimension or item-count limits.

## Windows installation
The x64 MSI installs for all users in Program Files and adds machine-wide file associations and a Start-menu shortcut.
The setup EXE defaults to a per-user installation and offers an all-user scope choice.
Ordinary Windows app startup also registers its editable file types in the current user's registry.
The public release run 43767734773 reported a successful MSI install as SYSTEM in session 0, app self-check and removal, with file hashes, registry and shortcut checks.
That proof used `msiexec /i "<MSI>" /qn` and `msiexec /x "<ProductCode>" /qn`, with additional no-restart and logging options.

## Signatures and licences
The same release run reported successful signing of the setup EXE and MSI and zero signature-check errors on 16 app files.
The downloaded installers have RSA 3072-bit signer keys and RSA 4096-bit chain keys.
The signer certificate is valid for three days, from 2026-11-14 13:16 to 2026-11-17 13:16 UTC.
The setup EXE's uninstaller has no configured signing or signature-verification step; its actual signature status has not been checked.
Annotshot's licence is MIT, and About provides a local third-party notices viewer.

## Not tested
An MSI-to-MSI upgrade, the Apps & Features listing, installation on a company-managed device and the MSI proof's deliberate failure cases have not been tested.
Whether Windows shows or stops showing a download warning, and whether certificate subjects or usage identifiers remain stable across releases, have not been tested.
Hostile-file resistance, clipboard-history behavior and operation with all users logged off have not been verified by this review.
