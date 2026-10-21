; Inno Setup script for SchemeUp. packaging/build.ps1 runs it after the program is built.
;
; It installs for the current user only (no administrator rights needed) into
; %LOCALAPPDATA%\Programs\SchemeUp, adds a Start menu entry, and can add a desktop
; shortcut and start SchemeUp when Windows starts, so the quick capture hotkey is ready.
; Uninstalling removes the program but never the notes: they stay in %LOCALAPPDATA%\SchemeUp.

#define AppName "SchemeUp"
#define AppVersion GetEnv("SCHEMEUP_VERSION")
#if AppVersion == ""
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{56494C91-8A3B-49B5-813B-86D0F1590071}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Xuanyi Qiu
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=schemeup.ico
UninstallDisplayIcon={app}\SchemeUp.exe
UninstallDisplayName={#AppName}
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=SchemeUp-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; SchemeUp lives in the tray, so it may be running while it is updated.
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "startup"; Description: "Start SchemeUp when Windows starts (keeps the quick note hotkey ready)"; Flags: unchecked

[Files]
Source: "..\dist\SchemeUp\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\SchemeUp.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\SchemeUp.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "SchemeUp"; ValueData: """{app}\SchemeUp.exe"""; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\SchemeUp.exe"; Description: "Start SchemeUp"; Flags: nowait postinstall skipifsilent
