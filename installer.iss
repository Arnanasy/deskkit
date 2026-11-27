; DeskKit（本地工具箱）Windows 标准安装包脚本（Inno Setup 6）
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

[Setup]
AppId={{4E2F9A61-3C8B-4B74-9E12-7A5C6D8E0F22}
AppName=DeskKit
AppVersion={#MyAppVersion}
AppPublisher=Eleven
AppPublisherURL=https://github.com/Arnanasy/deskkit
AppSupportURL=https://github.com/Arnanasy/deskkit/issues
DefaultDirName={localappdata}\Programs\DeskKit
DefaultGroupName=DeskKit
DisableProgramGroupPage=yes
LicenseFile=LICENSE
OutputDir=dist
OutputBaseFilename=DeskKit-Setup
SetupIconFile=DeskKit.ico
UninstallDisplayIcon={app}\DeskKit.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
CloseApplications=force

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut (创建桌面快捷方式)"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "dist\DeskKit.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\DeskKit"; Filename: "{app}\DeskKit.exe"
Name: "{group}\Uninstall DeskKit"; Filename: "{uninstallexe}"
Name: "{autodesktop}\DeskKit"; Filename: "{app}\DeskKit.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DeskKit.exe"; Description: "Launch DeskKit (立即启动本地工具箱)"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\DeskKit_error.log*"
