; Inno Setup script for the RideSims Panel companion.
; Built by CI: the version comes from the RSP_VERSION environment variable and the app files from
; companion/dist-dir/RideSimsPanel (a PyInstaller one-folder build).

#define AppVersion GetEnv("RSP_VERSION")

[Setup]
; Never change this GUID. It is how a newer installer finds and upgrades an existing install.
AppId={{B6E1D0A4-5C0F-4E27-9A52-3D7B1C6F8E21}
AppName=RideSims Panel Companion
AppVersion={#AppVersion}
AppPublisher=FoldedLettuce
AppPublisherURL=https://github.com/FoldedLettuce/ridesims-panel
; Per-user install: no admin prompt, and the in-app updater can upgrade it silently.
PrivilegesRequired=lowest
DefaultDirName={autopf}\RideSims Panel
DefaultGroupName=RideSims Panel
DisableProgramGroupPage=yes
OutputDir=..\installer-out
OutputBaseFilename=RideSimsPanel-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=RideSims Panel Companion
UninstallDisplayIcon={app}\RideSimsPanel.exe
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked
Name: "startup"; Description: "Start RideSims Panel when I sign in to Windows"; Flags: unchecked

[Files]
Source: "..\dist-dir\RideSimsPanel\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\RideSims Panel"; Filename: "{app}\RideSimsPanel.exe"
Name: "{autodesktop}\RideSims Panel"; Filename: "{app}\RideSimsPanel.exe"; Tasks: desktopicon
Name: "{userstartup}\RideSims Panel"; Filename: "{app}\RideSimsPanel.exe"; Tasks: startup

[Run]
; Interactive install: offer to launch at the end. Silent install (the in-app updater): start it straight away.
Filename: "{app}\RideSimsPanel.exe"; Description: "Launch RideSims Panel"; Flags: nowait postinstall skipifsilent
Filename: "{app}\RideSimsPanel.exe"; Flags: nowait skipifnotsilent

[Code]
// Profiles and settings live in %APPDATA%\RideSimsPanel, outside the program folder, so upgrades never touch
// them. On a manual uninstall, ask before removing them (default is to keep).
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then
  begin
    DataDir := ExpandConstant('{userappdata}\RideSimsPanel');
    if DirExists(DataDir) then
      if MsgBox('Also delete your profiles and settings?' + #13#10 + DataDir + #13#10#13#10 +
                'Choose No to keep them for a future install.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
