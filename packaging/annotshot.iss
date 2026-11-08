; Annotshot's Windows installer (Inno Setup 6), built from the PyInstaller
; folder dist\Annotshot after its frozen self-check:
;
;   iscc /DAppVersion=<annotshot.__version__> packaging\annotshot.iss
;
; The version is never typed here: the release workflow and
; packaging\build-win.ps1 read it from annotshot/__init__.py and pass it in.
; Out: Annotshot-<version>-setup.exe in the repository folder (build-win.ps1
; passes /O<dist> to put it beside its zip).
;
; Per-user by default (no administrator): the app goes to
; {localappdata}\Programs\Annotshot unless the user picks another folder on
; the folder page, which is always shown. The .annotshot file type is
; registered as annotshot/filetype.py registers it (the same ProgID, verbs
; and icon), under HKEY_CURRENT_USER for a per-user install, and removed on
; uninstall. The user's own files are never removed.
;
; ASSUMES: dist\Annotshot holds the whole frozen app (Annotshot.exe at its
; top) - iscc stops with "no files found" when it does not.

#ifndef AppVersion
  #error Pass the version: iscc /DAppVersion=<annotshot.__version__> packaging\annotshot.iss
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\Annotshot"
#endif

[Setup]
AppId={{0F17E8F7-0057-4379-9C3E-1C8E65862696}
AppName=Annotshot
AppVersion={#AppVersion}
AppVerName=Annotshot {#AppVersion}
AppPublisher=Viking Software
AppPublisherURL=https://github.com/Bill-Viking/annotshot
AppSupportURL=https://github.com/Bill-Viking/annotshot/issues
AppUpdatesURL=https://github.com/Bill-Viking/annotshot/releases
VersionInfoVersion={#AppVersion}
VersionInfoCompany=Viking Software
VersionInfoProductName=Annotshot
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\Annotshot
DisableDirPage=no
DefaultGroupName=Annotshot
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
SetupIconFile=..\annotshot.ico
UninstallDisplayIcon={app}\Annotshot.exe
UninstallDisplayName=Annotshot
#ifexist "..\LICENSE"
LicenseFile=..\LICENSE
#endif
CloseApplications=yes
ChangesAssociations=yes
OutputDir=..
OutputBaseFilename=Annotshot-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Annotshot"; Filename: "{app}\Annotshot.exe"
Name: "{autodesktop}\Annotshot"; Filename: "{app}\Annotshot.exe"; Tasks: desktopicon

; The file type, row for row annotshot/filetype.py's plan() for a frozen app
; (the test reads these lines against it). HKA is HKEY_CURRENT_USER for a
; per-user install and HKEY_LOCAL_MACHINE for an all-users one.
[Registry]
Root: HKA; Subkey: "Software\Classes\.annotshot"; ValueType: string; ValueName: ""; ValueData: "Annotshot.Editable"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.annotshot\OpenWithProgids"; ValueType: string; ValueName: "Annotshot.Editable"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.snagup"; ValueType: string; ValueName: ""; ValueData: "Annotshot.Editable"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.snagup\OpenWithProgids"; ValueType: string; ValueName: "Annotshot.Editable"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Annotshot.Editable"; ValueType: string; ValueName: ""; ValueData: "Annotshot editable file"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Annotshot.Editable\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\Annotshot.exe"",0"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Annotshot.Editable\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Annotshot.exe"" ""%1"""; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\Annotshot.exe"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "Annotshot"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\Annotshot.exe\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Annotshot.exe"" ""%1"""; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\Annotshot.exe\SupportedTypes"; ValueType: string; ValueName: ".annotshot"; ValueData: ""; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\Annotshot.exe\SupportedTypes"; ValueType: string; ValueName: ".snagup"; ValueData: ""; Flags: uninsdeletekey

; The one file the app may leave in its own folder (its --check verdict when
; there is no console); nothing of the user's lives here.
[UninstallDelete]
Type: files; Name: "{app}\check.txt"

[Run]
Filename: "{app}\Annotshot.exe"; Description: "{cm:LaunchProgram,Annotshot}"; Flags: nowait postinstall skipifsilent
