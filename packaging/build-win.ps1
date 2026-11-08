# Build Annotshot for Windows with PyInstaller (Windows PowerShell 5.1).
#   powershell -ExecutionPolicy Bypass -File packaging\build-win.ps1
# Builds dist\Annotshot\ from packaging\annotshot.spec, proves the exe with its
# headless --check (no window) and the user manual Help shows, builds the installer
# dist\Annotshot-<version>-setup.exe from packaging\annotshot.iss when Inno Setup 6 is on
# this computer (else one line says it was skipped and why), then zips the folder to
# dist\Annotshot-<version>-windows.zip.
# Prints one line per step, then OK <zip> <size> or STOP <reason>.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Total = 6

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
$Manual = Get-ChildItem -Path (Join-Path $Dist 'Annotshot') -Recurse -Filter 'USER-MANUAL.md' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $Manual) { Stop-Build 'the user manual docs\USER-MANUAL.md is missing from dist\Annotshot (Help shows it)' }
Step 3 "Annotshot.exe --check -> $stdout . manual in the bundle"

# 4. the installer (Inno Setup 6), from the folder step 3 proved
$Iss = Join-Path $Root 'packaging\annotshot.iss'
$Iscc = $null
foreach ($base in @(${env:ProgramFiles(x86)}, $env:ProgramFiles, (Join-Path "$env:LOCALAPPDATA" 'Programs'))) {
    if (-not $base) { continue }
    $c = Join-Path $base 'Inno Setup 6\ISCC.exe'
    if (Test-Path -LiteralPath $c) { $Iscc = $c; break }
}
if ($null -eq $Iscc) { $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue; if ($cmd) { $Iscc = $cmd.Source } }
$Setup = Join-Path $Dist "Annotshot-$Version-setup.exe"
Remove-Item $Setup -ErrorAction SilentlyContinue
if ($null -eq $Iscc) {
    $Setup = $null
    Step 4 'installer skipped: Inno Setup 6 (ISCC.exe) is not on this computer - the zip is still built; install Inno Setup 6 to get the setup.exe too'
} else {
    & $Iscc /Qp "/DAppVersion=$Version" "/DSourceDir=$(Join-Path $Dist 'Annotshot')" "/O$Dist" $Iss
    if ($LASTEXITCODE -ne 0) { Stop-Build "Inno Setup failed (exit $LASTEXITCODE) on $Iss" }
    if (-not (Test-Path $Setup)) { Stop-Build "no installer at $Setup" }
    Step 4 ("installer {0} ({1} MB)" -f $Setup, [math]::Round((Get-Item $Setup).Length / 1MB, 1))
}

# 5. the zip
$Zip = Join-Path $Dist "Annotshot-$Version-windows.zip"
Remove-Item $Zip -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $Dist 'Annotshot') -DestinationPath $Zip -CompressionLevel Optimal
if (-not (Test-Path $Zip)) { Stop-Build "no zip at $Zip" }
Step 5 "zipped dist\Annotshot\"

# 6. the result
$mb = [math]::Round((Get-Item $Zip).Length / 1MB, 1)
Step 6 'done'
Write-Host ("OK {0} {1} MB" -f $Zip, $mb)
if ($Setup) { Write-Host ("OK {0}" -f $Setup) }
exit 0
