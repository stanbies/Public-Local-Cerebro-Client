; Inno Setup Script for Cerebro Companion
; Build with: ISCC.exe installer.iss

#define MyAppName "Cerebro Companion"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Cerebro Healthcare"
#define MyAppURL "https://cerebro.health"
#define MyAppExeName "CerebroCompanion.exe"

[Setup]
AppId={{8F3B9A2E-5C4D-4E6F-8A1B-2C3D4E5F6A7B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
; Output settings
OutputDir=dist
OutputBaseFilename=CerebroCompanion_Setup_{#MyAppVersion}
; Compression
Compression=lzma2/ultra64
SolidCompression=yes
; UI
WizardStyle=modern
; Privileges - install for current user by default
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Uninstaller
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "dutch"; MessagesFile: "compiler:Languages\Dutch.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Main application files from PyInstaller output
Source: "dist\CerebroCompanion\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
// Check if app is running before uninstall
function InitializeUninstall(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  // Try to gracefully close the app if running
  // The app listens on port 18421
end;
