#ifndef AppVersion
  #define AppVersion "0.3.1"
#endif
[Setup]
AppId={{724B41D6-BA31-4933-A4BA-BEE14865313B}
AppName=Nawa
AppVersion={#AppVersion}
AppPublisher=Nawa contributors
AppPublisherURL=https://github.com/o8bo/nawa
DefaultDirName={localappdata}\Programs\Nawa
DefaultGroupName=Nawa
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist\windows
OutputBaseFilename=Nawa-{#AppVersion}-Windows-x64-Setup
SetupIconFile=..\assets\nawa.ico
UninstallDisplayIcon={app}\Nawa.exe
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\Nawa\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Nawa"; Filename: "{app}\Nawa.exe"
Name: "{autodesktop}\Nawa"; Filename: "{app}\Nawa.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Nawa.exe"; Description: "Launch Nawa"; Flags: nowait postinstall skipifsilent
