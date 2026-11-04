# Build Annotshot for Windows with PyInstaller (Windows PowerShell 5.1).
#   powershell -ExecutionPolicy Bypass -File packaging\build-win.ps1
# Builds dist\Annotshot\ from packaging\annotshot.spec, proves the exe with its
# headless --check (no window), then zips it to dist\Annotshot-<version>-windows.zip.
# Prints one line per step, then OK <zip> <size> or STOP <reason>.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Total = 5

function Step($n, $what) { Write-Host ("{0} of {1} . {2}" -f $n, $Total, $what) }
function Stop-Build($why) { Write-Host "STOP $why"; exit 1 }

Set-Location $Root

# 1. the interpreter
$Py = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Py)) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $cmd) { Stop-Build 'no Python: neither .venv\Scripts\python.exe nor python on PATH' }
    $Py = $cmd.Source
}
try { & $Py -c "import PyInstaller, PySide6, docx, pptx" 2>$null } catch { }
if ($LASTEXITCODE -ne 0) { Stop-Build "PyInstaller, PySide6, python-docx or python-pptx missing: $Py -m pip install pyinstaller==6.22.3 PySide6-Essentials==6.12.0 python-docx==1.2.0 python-pptx==1.0.2" }
$Version = (& $Py -c "import annotshot; print(annotshot.__version__)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $Version) { Stop-Build 'could not read annotshot.__version__' }
Step 1 "python $Py . Annotshot $Version"

# 2. PyInstaller
$Spec = Join-Path $Root 'packaging\annotshot.spec'
$Dist = Join-Path $Root 'dist'
$Work = Join-Path $Root 'build'
$t0 = Get-Date
& $Py -m PyInstaller --noconfirm --clean --log-level WARN --distpath $Dist --workpath $Work $Spec
if ($LASTEXITCODE -ne 0) { Stop-Build "PyInstaller failed (exit $LASTEXITCODE)" }
$Exe = Join-Path $Dist 'Annotshot\Annotshot.exe'
if (-not (Test-Path $Exe)) { Stop-Build "no exe at $Exe" }
$secs = [int]((Get-Date) - $t0).TotalSeconds
Step 2 "built dist\Annotshot\ in $secs s"

# 3. the headless self-check of the frozen exe (offscreen; no window)
$Txt = Join-Path $Dist 'Annotshot\check.txt'
$Out = Join-Path $Work 'check-stdout.txt'
Remove-Item $Txt, $Out -ErrorAction SilentlyContinue
$p = Start-Process -FilePath $Exe -ArgumentList '--check' -NoNewWindow -Wait -PassThru -RedirectStandardOutput $Out
$stdout = ''
if (Test-Path $Out) { $lines = @(Get-Content $Out | Where-Object { $_.Trim() -ne '' }); if ($lines.Count) { $stdout = $lines[-1].Trim() } }   # the last line is the verdict; earlier lines are the check's own steps
$filed = ''
if (Test-Path $Txt) { $filed = (Get-Content $Txt -Raw).Trim(); Remove-Item $Txt }
$want = "Annotshot $Version OK"
if ($p.ExitCode -ne 0) { Stop-Build "Annotshot.exe --check exit $($p.ExitCode): $stdout $filed" }
if ($stdout -ne $want) { Stop-Build "Annotshot.exe --check printed '$stdout' (check.txt '$filed'), wanted '$want'" }
Step 3 "Annotshot.exe --check -> $stdout"

# 4. the zip
$Zip = Join-Path $Dist "Annotshot-$Version-windows.zip"
Remove-Item $Zip -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $Dist 'Annotshot') -DestinationPath $Zip -CompressionLevel Optimal
if (-not (Test-Path $Zip)) { Stop-Build "no zip at $Zip" }
Step 4 "zipped dist\Annotshot\"

# 5. the result
$mb = [math]::Round((Get-Item $Zip).Length / 1MB, 1)
Step 5 'done'
Write-Host ("OK {0} {1} MB" -f $Zip, $mb)
exit 0
