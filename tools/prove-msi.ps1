# Parent/worker SYSTEM deployment proof. Source-contract tests do not execute this.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Msi,
    [Parameter(Mandatory=$true)][string]$Version,
    [Parameter(Mandatory=$true)][string]$Manifest,
    [Parameter(Mandatory=$true)][string]$ProofDirectory,
    [switch]$Worker,
    [string]$Nonce,
    [switch]$Phase
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# All bounds are seconds. The normal phase includes validation and child waits;
# its supervisor owns cleanup even if that entire phase stalls. Conservatively
# charge every reconciliation bound outside the phase: 900+300+20+30+20+30=1300,
# leaving 140 seconds inside the task (120 spare, 20 startup/final receipt).
# Child reconciliation normally consumes phase time. Workflow: 28 min.
$Timing = @{
    InstallSeconds=300; CheckSeconds=120; UninstallSeconds=300
    ValidationSeconds=180; WorkSeconds=900; PhaseMarginSeconds=30
    CleanupSeconds=300; TaskSeconds=1440; ParentSeconds=1500
    ChildTerminationSeconds=20; PhaseTerminationSeconds=30
    CleanupTerminationSeconds=20; InstallerIdleSeconds=30
}
$workClock=[Diagnostics.Stopwatch]::StartNew()
$script:terminationConfirmed=$true

# Start suspended and attach a private, non-inheritable job before any code can
# spawn. Job membership retains descendants even after intermediate parents exit.
# Never select processes by executable name. Job handles cannot name other work.
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
public sealed class ProofProcessTree : IDisposable {
    [StructLayout(LayoutKind.Sequential)] struct Security { public int length; public IntPtr descriptor; public int inherit; }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct Startup {
        public int cb; public string reserved, desktop, title;
        public int x,y,xSize,ySize,xChars,yChars,fill,flags;
        public short show,reservedSize; public IntPtr reservedBytes,input,output,error;
    }
    [StructLayout(LayoutKind.Sequential)] struct ProcessInfo { public IntPtr process,thread; public uint pid,tid; }
    [StructLayout(LayoutKind.Sequential)] struct BasicLimits {
        public long processTime,jobTime; public uint flags; public UIntPtr min,max;
        public uint active; public UIntPtr affinity; public uint priority,scheduling;
    }
    [StructLayout(LayoutKind.Sequential)] struct IoCounters { public ulong r,w,o,rb,wb,ob; }
    [StructLayout(LayoutKind.Sequential)] struct ExtendedLimits {
        public BasicLimits basic; public IoCounters io; public UIntPtr processMemory,jobMemory,peakProcess,peakJob;
    }
    [StructLayout(LayoutKind.Sequential)] struct Accounting {
        public long user,kernel,periodUser,periodKernel; public uint faults,total,active,terminated;
    }
    [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)] static extern IntPtr CreateJobObject(IntPtr attributes,string name);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetInformationJobObject(IntPtr job,int kind,ref ExtendedLimits limits,int size);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool QueryInformationJobObject(IntPtr job,int kind,out Accounting info,int size,IntPtr returned);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool AssignProcessToJobObject(IntPtr job,IntPtr process);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateJobObject(IntPtr job,uint code);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateProcess(IntPtr process,uint code);
    [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)] static extern bool CreateProcess(string app,StringBuilder command,IntPtr pa,IntPtr ta,bool inherit,uint flags,IntPtr env,string cwd,ref Startup start,out ProcessInfo info);
    [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)] static extern IntPtr CreateFile(string name,uint access,uint share,ref Security security,uint disposition,uint flags,IntPtr template);
    [DllImport("kernel32.dll", SetLastError=true)] static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll", SetLastError=true)] static extern uint WaitForSingleObject(IntPtr handle,uint milliseconds);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetExitCodeProcess(IntPtr process,out uint code);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    IntPtr job,process; bool assigned;
    static void Check(bool ok) { if (!ok) throw new Win32Exception(Marshal.GetLastWin32Error()); }
    static void Close(IntPtr handle) { if (handle!=IntPtr.Zero && handle!=new IntPtr(-1)) CloseHandle(handle); }
    static IntPtr Stream(string path,bool input) {
        Security security=new Security { length=Marshal.SizeOf(typeof(Security)), inherit=1 };
        IntPtr handle=CreateFile(String.IsNullOrEmpty(path) ? "NUL" : path,input ? 0x80000000u : 0x40000000u,3,ref security,input ? 3u : 2u,0,IntPtr.Zero);
        Check(handle!=new IntPtr(-1)); return handle;
    }
    public void Start(string file,string arguments,string stdout,string stderr) {
        job=CreateJobObject(IntPtr.Zero,null); Check(job!=IntPtr.Zero);
        ExtendedLimits limits=new ExtendedLimits();
        limits.basic.flags=0x2000; // KILL_ON_JOB_CLOSE; no breakaway flags.
        Check(SetInformationJobObject(job,9,ref limits,Marshal.SizeOf(typeof(ExtendedLimits))));
        IntPtr input=IntPtr.Zero,output=IntPtr.Zero,error=IntPtr.Zero,thread=IntPtr.Zero;
        try {
            input=Stream(null,true); output=Stream(stdout,false); error=Stream(stderr,false);
            Startup startup=new Startup { cb=Marshal.SizeOf(typeof(Startup)),flags=0x100,input=input,output=output,error=error };
            ProcessInfo info;
            // CREATE_SUSPENDED | CREATE_NO_WINDOW. Attach before ResumeThread.
            Check(CreateProcess(file,new StringBuilder("\""+file+"\" "+arguments),IntPtr.Zero,IntPtr.Zero,true,0x08000004,IntPtr.Zero,null,ref startup,out info));
            process=info.process; thread=info.thread;
            Check(AssignProcessToJobObject(job,process)); assigned=true;
            Check(ResumeThread(thread)!=0xffffffff);
        } finally { Close(thread); Close(input); Close(output); Close(error); }
    }
    public bool WaitForExit(int milliseconds) {
        uint result=WaitForSingleObject(process,(uint)milliseconds);
        Check(result==0 || result==258); return result==0;
    }
    public int ExitCode { get { uint code; Check(GetExitCodeProcess(process,out code)); return unchecked((int)code); } }
    public bool Empty { get {
        if (!assigned) return process==IntPtr.Zero || WaitForExit(0);
        Accounting info; Check(QueryInformationJobObject(job,1,out info,Marshal.SizeOf(typeof(Accounting)),IntPtr.Zero));
        return info.active==0;
    } }
    // The caller's clock includes termination itself; confirmation never resets it.
    public bool TerminateAndWait(Stopwatch clock,int milliseconds) {
        if (assigned) { Check(TerminateJobObject(job,1)); }
        else if (process!=IntPtr.Zero && !WaitForExit(0)) { Check(TerminateProcess(process,1)); }
        while (clock.Elapsed.TotalMilliseconds<milliseconds) {
            if (Empty) return true;
            System.Threading.Thread.Sleep(50);
        }
        return Empty;
    }
    public void Dispose() { Close(process); Close(job); process=job=IntPtr.Zero; }
}
'@

function Require([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}
function FullFile([string]$Path) {
    Require ([IO.Path]::IsPathRooted($Path)) "absolute path required: $Path"
    $item = Get-Item -LiteralPath $Path
    Require (-not $item.PSIsContainer) "file required: $Path"
    return $item.FullName
}
function Quote([string]$Value) {
    # All passed values are Windows paths, canonical versions, GUIDs or nonces.
    # A path cannot contain a quote; refuse CR/LF rather than create command text.
    Require ($Value -notmatch '["\r\n]' -and -not $Value.EndsWith('\')) 'unsafe task argument'
    return '"' + $Value + '"'
}
function RunBounded([string]$File, [string]$Arguments, [int]$Seconds, [string]$Stdout='', [string]$Stderr='', [int]$TerminationSeconds=$Timing.ChildTerminationSeconds) {
    $process=New-Object ProofProcessTree
    try {
        $process.Start($File,$Arguments,$Stdout,$Stderr)
        if (-not $process.WaitForExit($Seconds * 1000)) {
            throw "child deadline exceeded ($Seconds seconds): $File"
        }
        Require $process.Empty 'child exited with surviving descendants'
        return [int]$process.ExitCode
    } catch {
        $failure=$_.Exception.Message
        $script:terminationConfirmed=$false
        $terminationClock=[Diagnostics.Stopwatch]::StartNew()
        try {
            $terminated=$process.TerminateAndWait($terminationClock,$TerminationSeconds * 1000)
            Require ($terminated -and $terminationClock.Elapsed.TotalSeconds -le $TerminationSeconds) "process tree termination UNCONFIRMED after $TerminationSeconds seconds"
            $script:terminationConfirmed=$true
        } catch { throw "$failure; process tree termination UNCONFIRMED: $($_.Exception.Message)" }
        throw "$failure; owned process tree termination confirmed"
    } finally { $process.Dispose() }
}
function WaitInstallerIdle() {
    # OpenExisting cannot create a competing mutex. Only probe/release it; never
    # terminate the service-side installer, which this proof did not start.
    $clock=[Diagnostics.Stopwatch]::StartNew()
    while ($clock.Elapsed.TotalSeconds -lt $Timing.InstallerIdleSeconds) {
        $mutex=$null; $held=$false
        try {
            try { $mutex=[Threading.Mutex]::OpenExisting('Global\_MSIExecute') }
            catch [Threading.WaitHandleCannotBeOpenedException] { return }
            try { $held=$mutex.WaitOne(0) }
            catch [Threading.AbandonedMutexException] { $held=$true }
            if ($held) { return }
        } finally {
            if ($held) { $mutex.ReleaseMutex() }
            if ($null -ne $mutex) { $mutex.Dispose() }
        }
        Start-Sleep -Milliseconds 100
    }
    throw "Windows Installer idle UNCONFIRMED after $($Timing.InstallerIdleSeconds) seconds (Global\_MSIExecute)"
}
function RequireWorkTime([int]$Seconds=0) {
    # Do not start a child that could outlive the normal-phase supervisor bound.
    Require (($workClock.Elapsed.TotalSeconds + $Seconds) -lt ($Timing.WorkSeconds - $Timing.PhaseMarginSeconds)) 'normal phase budget exhausted; cleanup reserved'
}
function AcceptMsi([int]$Code, [string]$Stage) {
    Require ($Code -in @(0,3010)) "$Stage msiexec exit $Code (only 0/3010 accepted; 1641/1618 fail)"
    if ($Code -eq 3010) { $script:receipt.reboot_required=$true; Write-Host "${Stage}: reboot-required (3010); no reboot performed" }
}
function OpenHive([Microsoft.Win32.RegistryHive]$Hive) {
    return [Microsoft.Win32.RegistryKey]::OpenBaseKey($Hive, [Microsoft.Win32.RegistryView]::Registry64)
}
function AbsentKey($Hive, [string]$Path) {
    $k=$Hive.OpenSubKey($Path)
    if ($null -ne $k) { $k.Dispose(); return $false }
    return $true
}
function PackedProductCode([string]$Code) {
    # {2869B2AB-0058-5282-9F29-18AB5F4A082A} -> BA2B968285002825F99281BAF5A480A2
    $hex=$Code -replace '[{}-]',''
    $packed=(-join $hex[7..0]) + (-join $hex[11..8]) + (-join $hex[15..12])
    for ($i=16; $i -lt 32; $i+=2) { $packed += [string]$hex[$i+1] + [string]$hex[$i] }
    return $packed
}
function RequireProductIcon($Hive, [string]$ArpPath, [string]$PublishedPath) {
    $k=$Hive.OpenSubKey($ArpPath)
    try {
        if ($null -ne $k -and -not [string]::IsNullOrWhiteSpace($k.GetValue('DisplayIcon'))) { return }
    } finally { if ($null -ne $k) { $k.Dispose() } }
    # ARPPRODUCTICON is recorded on the published product, not necessarily ARP.
    # Keep value DATA private; even file-probe errors must not expose the path.
    $k=$Hive.OpenSubKey($PublishedPath)
    try {
        Require ($null -ne $k) 'ARP icon missing: no published product key'
        $icon=[string]$k.GetValue('ProductIcon')
        Require (-not [string]::IsNullOrWhiteSpace($icon)) 'ARP icon missing: no ProductIcon value'
        Require (Test-Path -LiteralPath $icon -PathType Leaf -ErrorAction SilentlyContinue) 'ARP icon missing: icon file missing'
    } finally { if ($null -ne $k) { $k.Dispose() } }
}
function RegistryEquals($Hive, [string]$Path, [string]$Name, $Expected) {
    $k=$Hive.OpenSubKey($Path)
    try {
        Require ($null -ne $k) "registry key missing: $Path"
        Require ($Name -in $k.GetValueNames()) "registry value missing: $Path / $Name"
        $actual=$k.GetValue($Name, $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        Require ($actual -ceq $Expected) "registry value mismatch: $Path / $Name"
    } finally { if ($null -ne $k) { $k.Dispose() } }
}
function RegistryTree($Hive, [string]$Path) {
    $k=$Hive.OpenSubKey($Path)
    $state=[pscustomobject][ordered]@{ path=$Path; exists=($null -ne $k); values=@(); children=@() }
    try {
        if ($null -ne $k) {
            foreach ($name in @($k.GetValueNames() | Sort-Object)) {
                $state.values += [ordered]@{
                    name=$name; kind=$k.GetValueKind($name).ToString()
                    data=$k.GetValue($name, $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
                }
            }
            foreach ($child in @($k.GetSubKeyNames() | Sort-Object)) {
                $state.children += RegistryTree $Hive ($Path + '\' + $child)
            }
        }
    } finally { if ($null -ne $k) { $k.Dispose() } }
    return $state
}
function RegistryState($Hive) {
    # Record complete trees, including unrelated values, value kinds and empty
    # containers. This covers every authored association/menu value and ARP.
    $state=@()
    foreach ($path in $registryRoots) { $state += RegistryTree $Hive $path }
    return ConvertTo-Json -InputObject $state -Depth 100 -Compress
}
function NoAssociationValue($Tree, [string]$Label) {
    foreach ($value in $Tree.values) {
        Require ($value.name -ine 'Annotshot.Editable' -and @($value.data) -notcontains 'Annotshot.Editable') "$Label Annotshot association: $($Tree.path) / $($value.name)"
    }
    foreach ($child in $Tree.children) { NoAssociationValue $child $Label }
}
function NoUserRegistration($Hive, [string]$Label) {
    # Inno leaves empty shared extension/OpenWithProgids containers. They are
    # allowed; only an actual Annotshot association or product blocks the proof.
    foreach ($path in @('Software\Classes\.annotshot','Software\Classes\.snagup')) {
        NoAssociationValue (RegistryTree $Hive $path) $Label
    }
    foreach ($path in @('Software\Classes\Annotshot.Editable','Software\Classes\Applications\Annotshot.exe') + @($arp,$innoArp)) {
        Require (AbsentKey $Hive $path) "$Label product registration: $path"
    }
    $menu=RegistryTree $Hive 'Software\Annotshot\Installer'
    foreach ($value in $menu.values) { throw "$Label existing Annotshot menu registration: $($menu.path) / $($value.name)" }
    foreach ($child in $menu.children) { throw "$Label existing Annotshot menu key: $($child.path)" }
}
function RegistryEntries($Tree, $Entries) {
    if (-not $Tree.exists) { return }
    $Entries.Add(('K:' + $Tree.path), [pscustomobject]@{ key_path=$Tree.path; value_name=$null; signature='key' })
    foreach ($value in $Tree.values) {
        # The signature (including DATA) is private, and never returned or logged.
        $Entries.Add(('V:' + $Tree.path + [char]0 + $value.name), [pscustomobject]@{
            key_path=$Tree.path; value_name=$value.name
            signature=(ConvertTo-Json -InputObject $value -Depth 100 -Compress)
        })
    }
    foreach ($child in $Tree.children) { RegistryEntries $child $Entries }
}
function RegistryDifferences([string]$Before, [string]$After) {
    $old=New-Object 'Collections.Generic.Dictionary[string,object]'
    $new=New-Object 'Collections.Generic.Dictionary[string,object]'
    foreach ($tree in ($Before | ConvertFrom-Json)) { RegistryEntries $tree $old }
    foreach ($tree in ($After | ConvertFrom-Json)) { RegistryEntries $tree $new }
    foreach ($id in $old.Keys) {
        $entry=$old[$id]; $change=$null
        if (-not $new.ContainsKey($id)) { $change='removed' }
        elseif ($entry.signature -cne $new[$id].signature) { $change='changed' }
        if ($change) { [pscustomobject][ordered]@{ key_path=$entry.key_path; value_name=$entry.value_name; change=$change } }
    }
    foreach ($id in $new.Keys) {
        if (-not $old.ContainsKey($id)) {
            $entry=$new[$id]
            [pscustomobject][ordered]@{ key_path=$entry.key_path; value_name=$entry.value_name; change='added' }
        }
    }
}
function RegistryRestored($Hive, [string]$Before, [string]$Label) {
    # Baseline and comparison stay in the same process. Only these explicitly
    # projected key/name/change fields may cross the evidence boundary.
    $after=RegistryState $Hive
    $differences=@(RegistryDifferences $Before $after)
    $sanitized='equal'
    if ($differences.Count) { $sanitized=$differences }
    $comparisonFile=Join-Path $ProofDirectory ('registry-' + ($Label -replace '[^A-Za-z0-9-]','-') + '.json')
    ConvertTo-Json -InputObject $sanitized -Depth 10 | Set-Content -LiteralPath $comparisonFile -Encoding UTF8
    Require ($differences.Count -eq 0) "$Label registry differs from before install (keys, values or kinds); see sanitized comparison"
    NoUserRegistration $Hive $Label
}
function AtomicReceipt($Value, [string]$Name='completion.json') {
    $temporary=Join-Path $ProofDirectory ($Name + '.tmp')
    $Value | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination (Join-Path $ProofDirectory $Name)
}
function WorkerArguments([switch]$Phase) {
    $arguments='-NoProfile -NonInteractive -File ' + (Quote $PSCommandPath) + ' -Worker -Msi ' + (Quote $Msi) + ' -Version ' + (Quote $Version) + ' -Manifest ' + (Quote (Join-Path $ProofDirectory 'manifest.json')) + ' -ProofDirectory ' + (Quote $ProofDirectory) + ' -Nonce ' + (Quote $Nonce)
    if ($Phase) { $arguments += ' -Phase' }
    return $arguments
}

$Msi=FullFile $Msi
$Manifest=FullFile $Manifest
Require ([IO.Path]::IsPathRooted($ProofDirectory)) 'absolute proof directory required'
$ProofDirectory=[IO.Path]::GetFullPath($ProofDirectory)
$metadata=Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
Require ($metadata.product.version -ceq $Version) 'manifest version mismatch'
$productCode=[string]$metadata.product.product_code
$upgradeCode=[string]$metadata.product.upgrade_code
Require ($productCode -match '^\{[0-9A-F-]{36}\}$') 'invalid ProductCode'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$sessionId=[Diagnostics.Process]::GetCurrentProcess().SessionId
$machine=OpenHive ([Microsoft.Win32.RegistryHive]::LocalMachine)
$user=OpenHive ([Microsoft.Win32.RegistryHive]::CurrentUser)
$target=Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFiles)) 'Annotshot'
$exe=Join-Path $target 'Annotshot.exe'
$shortcut=Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::CommonPrograms)) 'Annotshot\Annotshot.lnk'
$arp="Software\Microsoft\Windows\CurrentVersion\Uninstall\$productCode"
$publishedProduct='Software\Classes\Installer\Products\' + (PackedProductCode $productCode)
$innoArp='Software\Microsoft\Windows\CurrentVersion\Uninstall\{0F17E8F7-0057-4379-9C3E-1C8E65862696}_is1'
$ownedKeys=@('Software\Classes\.annotshot','Software\Classes\.snagup','Software\Classes\Annotshot.Editable','Software\Classes\Applications\Annotshot.exe','Software\Annotshot\Installer')
$registryRoots=$ownedKeys + @($arp,$innoArp)
$msiexec=Join-Path $env:WINDIR 'System32\msiexec.exe'
$powershell=Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
Require (-not $Phase -or $Worker) 'phase requires worker mode'

if ($Worker -and -not $Phase) {
    # The scheduled worker supervises a separate, bounded normal phase. Registry,
    # hashing and COM work therefore cannot consume the reserved cleanup window.
    $receipt=[ordered]@{
        nonce=$Nonce; version=$Version; product_code=$productCode; upgrade_code=$upgradeCode
        identity_sid=$identity.User.Value; session_id=$sessionId
        install_exit=$null; check_exit=$null; uninstall_exit=$null; cleanup_exit=$null
        hashes_ok=$false; registry_ok=$false; shortcut_ok=$false; removal_ok=$false
        reboot_required=$false; success=$false; error=$null; cleanup_error=$null
    }
    try {
        Require ($identity.User.Value -eq 'S-1-5-18' -and $sessionId -eq 0) 'SYSTEM UNPROVEN: supervisor identity/session'
        $phaseExit=RunBounded $powershell (WorkerArguments -Phase) $Timing.WorkSeconds (Join-Path $ProofDirectory 'phase.stdout.txt') (Join-Path $ProofDirectory 'phase.stderr.txt') $Timing.PhaseTerminationSeconds
        $phaseReceipt=Get-Content -LiteralPath (Join-Path $ProofDirectory 'phase.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        Require ($null -ne $phaseReceipt -and $phaseReceipt.nonce -ceq $Nonce) 'missing/mismatched normal phase receipt'
        $receipt=$phaseReceipt
        Require ($phaseExit -eq 0 -and $receipt.success) "normal phase failed: $($receipt.error)"
    } catch {
        $receipt.success=$false
        $receipt.error=$_.Exception.Message
        Write-Host "SYSTEM proof failed: $($receipt.error)"
        if ((Test-Path -LiteralPath (Join-Path $ProofDirectory 'install-start.json')) -and -not $receipt.removal_ok) {
            try {
                Require $script:terminationConfirmed 'cleanup refused: owned process tree termination UNCONFIRMED'
                WaitInstallerIdle
                $receipt.cleanup_exit=RunBounded $msiexec ('/x ' + (Quote $productCode) + ' /qn /norestart /l*v ' + (Quote (Join-Path $ProofDirectory 'cleanup.log'))) $Timing.CleanupSeconds '' '' $Timing.CleanupTerminationSeconds
                AcceptMsi $receipt.cleanup_exit 'cleanup'
            } catch { $receipt.cleanup_error=$_.Exception.Message; Write-Host "cleanup failed: $($receipt.cleanup_error)" }
        }
    } finally {
        $machine.Dispose(); $user.Dispose(); $identity.Dispose()
        AtomicReceipt $receipt
    }
    if (-not $receipt.success) { exit 1 }
    exit 0
}

if ($Worker) {
    $receipt=[ordered]@{
        nonce=$Nonce; version=$Version; product_code=$productCode; upgrade_code=$upgradeCode
        identity_sid=$identity.User.Value; session_id=$sessionId
        install_exit=$null; check_exit=$null; uninstall_exit=$null; cleanup_exit=$null
        hashes_ok=$false; registry_ok=$false; shortcut_ok=$false; removal_ok=$false
        reboot_required=$false; success=$false; error=$null; cleanup_error=$null
    }
    try {
        Require ($Nonce -match '^[0-9a-f]{32}$') 'missing worker nonce'
        # Retained even if a capability/cleanliness check fails before completion.
        $receipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $ProofDirectory 'worker-start.json') -Encoding UTF8
        Require ($identity.User.Value -eq 'S-1-5-18') 'SYSTEM UNPROVEN: worker is not SYSTEM'
        Require ($sessionId -eq 0) 'SYSTEM UNPROVEN: worker is not in session 0'
        Require ([Environment]::Is64BitProcess) 'worker must be a 64-bit process'
        $env:QT_QPA_PLATFORM='offscreen'
        Require (-not (Test-Path -LiteralPath $target)) 'pre-existing Program Files target; refusing to remove it'
        Require (-not (Test-Path -LiteralPath $shortcut)) 'pre-existing common shortcut'
        NoUserRegistration $machine 'HKLM before install'
        NoUserRegistration $user 'SYSTEM HKCU'
        $machineBefore=RegistryState $machine
        $systemBefore=RegistryState $user
        RequireWorkTime $Timing.InstallSeconds
        $receipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $ProofDirectory 'install-start.json') -Encoding UTF8
        $receipt.install_exit=RunBounded $msiexec ('/i ' + (Quote $Msi) + ' /qn /norestart /l*v ' + (Quote (Join-Path $ProofDirectory 'install.log'))) $Timing.InstallSeconds
        AcceptMsi $receipt.install_exit 'install'
        Require (Test-Path -LiteralPath $exe -PathType Leaf) 'installed EXE missing from 64-bit Program Files'
        foreach ($location in @($env:LOCALAPPDATA,$env:APPDATA)) {
            if ($location) {
                Require (-not (Test-Path -LiteralPath (Join-Path $location 'Programs\Annotshot'))) 'unexpected AppData installation'
                Require (-not (Test-Path -LiteralPath (Join-Path $location 'Annotshot\Annotshot.exe'))) 'unexpected AppData EXE'
            }
        }
        foreach ($file in $metadata.files) {
            RequireWorkTime
            $installed=Join-Path $target $file.path
            Require (Test-Path -LiteralPath $installed -PathType Leaf) "missing installed file: $($file.path)"
            Require ((Get-FileHash -LiteralPath $installed -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $file.sha256) "installed hash mismatch: $($file.path)"
        }
        foreach ($folder in $metadata.empty_directories) {
            RequireWorkTime
            Require (Test-Path -LiteralPath (Join-Path $target $folder.path) -PathType Container) 'missing empty payload directory'
        }
        $receipt.hashes_ok=$true
        RequireWorkTime
        $command='"' + $exe + '" "%1"'
        $rows=@(
            @('.annotshot','','Annotshot.Editable'),
            @('.annotshot\OpenWithProgids','Annotshot.Editable',''),
            @('.snagup','','Annotshot.Editable'),
            @('.snagup\OpenWithProgids','Annotshot.Editable',''),
            @('Annotshot.Editable','','Annotshot editable file'),
            @('Annotshot.Editable\DefaultIcon','',('"' + $exe + '",0')),
            @('Annotshot.Editable\shell\open\command','',$command),
            @('Applications\Annotshot.exe','FriendlyAppName','Annotshot'),
            @('Applications\Annotshot.exe\shell\open\command','',$command),
            @('Applications\Annotshot.exe\SupportedTypes','.annotshot',''),
            @('Applications\Annotshot.exe\SupportedTypes','.snagup','')
        )
        foreach ($row in $rows) { RegistryEquals $machine ('Software\Classes\' + $row[0]) $row[1] $row[2] }
        RegistryEquals $machine $arp 'DisplayName' 'Annotshot'
        RegistryEquals $machine $arp 'DisplayVersion' $Version
        RegistryEquals $machine $arp 'Publisher' 'Bill Moldestad'
        RegistryEquals $machine $arp 'WindowsInstaller' 1
        RegistryEquals $machine $arp 'InstallLocation' ($target + '\')
        foreach ($name in @('UninstallString','ModifyPath')) {
            $k=$machine.OpenSubKey($arp)
            try { Require ($k.GetValue($name) -match [regex]::Escape($productCode)) "ARP $name missing product code" } finally { $k.Dispose() }
        }
        RequireProductIcon $machine $arp $publishedProduct
        RegistryRestored $user $systemBefore 'SYSTEM HKCU after install'
        $receipt.registry_ok=$true
        Require (Test-Path -LiteralPath $shortcut -PathType Leaf) 'common shortcut missing'
        $shell=New-Object -ComObject WScript.Shell
        $link=$shell.CreateShortcut($shortcut)
        try {
            Require ($link.TargetPath -ieq $exe) 'shortcut target mismatch'
            Require ($link.WorkingDirectory.TrimEnd('\') -ieq $target) 'shortcut working directory mismatch'
        } finally {
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($link)
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)
        }
        $receipt.shortcut_ok=$true
        $diagnostic=Join-Path $target 'check.txt'
        if (Test-Path -LiteralPath $diagnostic) { Remove-Item -LiteralPath $diagnostic }
        $stdout=Join-Path $ProofDirectory 'check.stdout.txt'
        $stderr=Join-Path $ProofDirectory 'check.stderr.txt'
        RequireWorkTime $Timing.CheckSeconds
        $receipt.check_exit=RunBounded $exe '--check' $Timing.CheckSeconds $stdout $stderr
        $lines=@(Get-Content -LiteralPath $stdout | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        $last=''
        if ($lines.Count) { $last=$lines[-1].Trim() }
        elseif (Test-Path -LiteralPath $diagnostic) {
            $lines=@(Get-Content -LiteralPath $diagnostic | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
            if ($lines.Count) { $last=$lines[-1].Trim() }
        }
        if (Test-Path -LiteralPath $diagnostic) {
            Copy-Item -LiteralPath $diagnostic -Destination (Join-Path $ProofDirectory 'check.receipt.txt')
            Remove-Item -LiteralPath $diagnostic
        }
        Require ($receipt.check_exit -eq 0 -and $last -ceq "Annotshot $Version OK") 'installed self-check verdict/exit failed'
        RequireWorkTime $Timing.UninstallSeconds
        $receipt.uninstall_exit=RunBounded $msiexec ('/x ' + (Quote $productCode) + ' /qn /norestart /l*v ' + (Quote (Join-Path $ProofDirectory 'uninstall.log'))) $Timing.UninstallSeconds
        AcceptMsi $receipt.uninstall_exit 'uninstall'
        Require (AbsentKey $machine $publishedProduct) 'uninstall left the published product key'
        Require (-not (Test-Path -LiteralPath $target)) 'uninstall left install folder'
        Require (-not (Test-Path -LiteralPath $shortcut)) 'uninstall left common shortcut'
        Require (-not (Test-Path -LiteralPath (Split-Path -LiteralPath $shortcut))) 'uninstall left empty shortcut folder'
        RegistryRestored $machine $machineBefore 'HKLM after uninstall'
        RegistryRestored $user $systemBefore 'SYSTEM HKCU after uninstall'
        $receipt.removal_ok=$true
        $receipt.success=$true
    } catch {
        $receipt.error=$_.Exception.Message
        Write-Host "SYSTEM proof failed: $($receipt.error)"
    } finally {
        $machine.Dispose(); $user.Dispose(); $identity.Dispose()
        AtomicReceipt $receipt 'phase.json'
    }
    if (-not $receipt.success) { exit 1 }
    exit 0
}

# Parent does not create an alternate user-run proof on any failure.
$taskName=$null
$registered=$false
$parentError=$null
$cleanupErrors=@()
try {
    $principal=New-Object Security.Principal.WindowsPrincipal($identity)
    Require ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'SYSTEM UNPROVEN: parent must already be elevated'
    Require ([Environment]::Is64BitProcess -and [Environment]::Is64BitOperatingSystem) 'SYSTEM UNPROVEN: x64 Windows process required'
    foreach ($command in @('New-ScheduledTaskAction','New-ScheduledTaskPrincipal','New-ScheduledTaskSettingsSet','Register-ScheduledTask','Start-ScheduledTask','Get-ScheduledTask','Get-ScheduledTaskInfo','Stop-ScheduledTask','Unregister-ScheduledTask')) {
        $present=$null -ne (Get-Command $command -ErrorAction SilentlyContinue)
        Write-Host "ScheduledTasks $command present: $present"
        Require $present "SYSTEM UNPROVEN: missing $command"
    }
    $service=Get-Service -Name Schedule
    Write-Host "Task Scheduler service: $($service.Status)"
    Require ($service.Status -eq 'Running') 'SYSTEM UNPROVEN: Task Scheduler not running'
    NoUserRegistration $user 'runner HKCU before proof'
    Require (-not (Test-Path -LiteralPath $target)) 'pre-existing target folder'
    NoUserRegistration $machine 'HKLM before proof'
    Require (-not (Test-Path -LiteralPath $ProofDirectory)) 'proof directory must be unique and fresh'
    [void][IO.Directory]::CreateDirectory($ProofDirectory)
    # Protected ACL: SYSTEM, built-in Administrators and the current runner only.
    $acl=New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true,$false)
    foreach ($sid in @('S-1-5-18','S-1-5-32-544',$identity.User.Value) | Select-Object -Unique) {
        $rule=New-Object Security.AccessControl.FileSystemAccessRule((New-Object Security.Principal.SecurityIdentifier($sid)), 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $ProofDirectory -AclObject $acl
    $runnerBefore=RegistryState $user
    $parentMachineBefore=RegistryState $machine
    # A local immutable input copy is covered by the protected directory ACL.
    Copy-Item -LiteralPath $Manifest -Destination (Join-Path $ProofDirectory 'manifest.json')
    $Nonce=[guid]::NewGuid().ToString('N')
    $runIdentity=($env:GITHUB_RUN_ID + '-' + $env:GITHUB_RUN_ATTEMPT) -replace '[^0-9-]',''
    $taskName="Annotshot-MSI-$runIdentity-$Nonce"
    Require (Test-Path -LiteralPath $powershell -PathType Leaf) 'SYSTEM UNPROVEN: no fully qualified 64-bit PowerShell'
    $arguments=WorkerArguments
    $action=New-ScheduledTaskAction -Execute $powershell -Argument $arguments
    $system=New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest
    $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds $Timing.TaskSeconds) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $taskName -Action $action -Principal $system -Settings $settings | Out-Null
    $registered=$true
    $started=Get-Date
    Start-ScheduledTask -TaskName $taskName
    $deadline=$started.AddSeconds($Timing.ParentSeconds)
    $completion=Join-Path $ProofDirectory 'completion.json'
    $finished=$false
    while ((Get-Date) -lt $deadline) {
        $task=Get-ScheduledTask -TaskName $taskName
        $info=Get-ScheduledTaskInfo -TaskName $taskName
        if ($info.LastRunTime -ge $started.AddSeconds(-2) -and $task.State -ne 'Running' -and $task.State -ne 'Queued') {
            Require (Test-Path -LiteralPath $completion -PathType Leaf) "SYSTEM UNPROVEN: missing completion receipt (LastTaskResult $($info.LastTaskResult))"
            $finished=$true
            break
        }
        Start-Sleep -Seconds 1
    }
    Require $finished "SYSTEM UNPROVEN: parent $($Timing.ParentSeconds)-second deadline; receipt/task incomplete"
    $result=Get-Content -LiteralPath $completion -Raw -Encoding UTF8 | ConvertFrom-Json
    Require ((Get-Item -LiteralPath $completion).LastWriteTimeUtc -ge $started.ToUniversalTime()) 'stale completion receipt'
    Require ($result.nonce -ceq $Nonce -and $result.version -ceq $Version -and $result.product_code -ceq $productCode -and $result.upgrade_code -ceq $upgradeCode) 'mismatched completion receipt'
    Require ($result.identity_sid -eq 'S-1-5-18' -and $result.session_id -eq 0) 'SYSTEM UNPROVEN: identity/session receipt mismatch'
    Require ($info.LastTaskResult -eq 0) "SYSTEM UNPROVEN: LastTaskResult $($info.LastTaskResult); $($result.error); cleanup: $($result.cleanup_error)"
    Require ($result.success -and $result.hashes_ok -and $result.registry_ok -and $result.shortcut_ok -and $result.removal_ok) "worker proof failed: $($result.error)"
    RegistryRestored $user $runnerBefore 'runner HKCU after proof'
    RegistryRestored $machine $parentMachineBefore 'HKLM after proof'
    if ($result.reboot_required) { Write-Host 'reboot-required: post-reboot behavior UNPROVEN' }
    Write-Host 'SYSTEM session 0 install/check/remove passed; literal logged-off operation UNPROVEN'
} catch {
    $parentError=$_.Exception.Message
    Write-Host "SYSTEM UNPROVEN: $parentError"
} finally {
    if ($registered) {
        try {
            $task=Get-ScheduledTask -TaskName $taskName
            if ($task.State -in @('Running','Queued')) { Stop-ScheduledTask -TaskName $taskName }
        } catch { $cleanupErrors += "stop own task: $($_.Exception.Message)" }
        try { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false } catch { $cleanupErrors += "unregister own task: $($_.Exception.Message)" }
    }
    $summary=[ordered]@{ error=$parentError; cleanup_errors=$cleanupErrors; task=$taskName }
    if (Test-Path -LiteralPath $ProofDirectory -PathType Container) {
        $summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $ProofDirectory 'parent.json') -Encoding UTF8
    }
    $machine.Dispose(); $user.Dispose(); $identity.Dispose()
}
foreach ($failure in $cleanupErrors) { Write-Host "cleanup failure: $failure" }
if ($parentError -or $cleanupErrors.Count) { exit 1 }
exit 0
