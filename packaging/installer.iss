; Inno Setup script for AutoDrums. Build with:
;   ISCC /DAppVersion=1.0.0 packaging\installer.iss
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{8F3C2A51-6B7E-4C1D-9E0A-AD7D2C1B5E42}
AppName=AutoDrums
AppVersion={#AppVersion}
AppVerName=AutoDrums {#AppVersion}
AppPublisher=AutoDrums
DefaultDirName={autopf}\AutoDrums
DefaultGroupName=AutoDrums
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=AutoDrums-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\AutoDrums.exe
Compression=lzma2
SolidCompression=yes
LZMANumBlockThreads=4
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\AutoDrums\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\AutoDrums"; Filename: "{app}\AutoDrums.exe"
Name: "{autodesktop}\AutoDrums"; Filename: "{app}\AutoDrums.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AutoDrums.exe"; Description: "{cm:LaunchProgram,AutoDrums}"; Flags: nowait postinstall skipifsilent
