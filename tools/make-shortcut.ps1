# Make a Start Menu shortcut "Annotshot" that starts Annotshot.cmd with the Annotshot icon.
# The Start Menu (not the Desktop) because a Desktop is often cloud-mirrored;
# the Start Menu's Programs folder is local. After it runs, press Start, type Annotshot.
# Run once from PowerShell:
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\make-shortcut.ps1
# Prints OK with the shortcut's path, or STOP with the reason.
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root 'Annotshot.cmd'
$icon = Join-Path $root 'annotshot.ico'
if (-not (Test-Path $target)) { Write-Output "STOP: $target not found"; exit 1 }
$programs = [Environment]::GetFolderPath('Programs')
if (-not (Test-Path $programs)) { Write-Output "STOP: $programs not found"; exit 1 }
$lnk = Join-Path $programs 'Annotshot.lnk'
$old = Join-Path $programs 'SnagUp.lnk'      # the shortcut from before the rename
if (Test-Path $old) { Remove-Item $old -Force; Write-Output "removed the old shortcut: $old" }
$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($lnk)
$s.TargetPath = $target
$s.WorkingDirectory = $root
$s.WindowStyle = 7          # minimised, so the cmd window does not flash
if (Test-Path $icon) { $s.IconLocation = "$icon,0" }
$s.Description = 'Annotshot - capture a region or a window and annotate it'
$s.Save()
if (Test-Path $lnk) { Write-Output "OK: $lnk" } else { Write-Output "STOP: shortcut not written"; exit 1 }
