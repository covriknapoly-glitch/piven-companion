#define AppName "PIVEN Companion"
#define AppVersion "0.1.0"
#define AppPublisher "covriknapoly-glitch"

[Setup]
AppId={{6F2C8D3A-5B71-4E0C-9A4D-2E8B7C1F9D05}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/covriknapoly-glitch
SourceDir=..
OutputDir=installer\Output
OutputBaseFilename=PIVEN-Companion-{#AppVersion}-Setup
SetupIconFile=assets\piven.ico
UninstallDisplayIcon={app}\assets\piven.ico
LicenseFile=LICENSE
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=4
CloseApplications=yes
WizardStyle=modern

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "zh"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[CustomMessages]
ru.NoWebView2=Для работы нужен Microsoft Edge WebView2 Runtime, а он не найден. Скачать его с сайта Microsoft после установки?
en.NoWebView2=The program needs Microsoft Edge WebView2 Runtime, which was not found. Open the Microsoft download page after setup?
zh.NoWebView2=程序需要 Microsoft Edge WebView2 Runtime，但未找到。安装完成后打开 Microsoft 下载页面吗？

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "app\*"; DestDir: "{app}\app"; Excludes: "__pycache__,*.pyc,*.log"; Flags: ignoreversion recursesubdirs
Source: "assets\*"; DestDir: "{app}\assets"; Excludes: "piven_logo_2026.png,piven_logo.png"; Flags: ignoreversion recursesubdirs
Source: "docs\*"; DestDir: "{app}\docs"; Flags: ignoreversion recursesubdirs
Source: "skills\*"; DestDir: "{app}\skills"; Flags: ignoreversion recursesubdirs
Source: "ui\dist\*"; DestDir: "{app}\ui\dist"; Flags: ignoreversion recursesubdirs
Source: "voice-engines\README.md"; DestDir: "{app}\voice-engines"; Flags: ignoreversion
Source: "voice-engines\model_server.py"; DestDir: "{app}\voice-engines"; Flags: ignoreversion
Source: "voice-engines\qwen-tts\server.py"; DestDir: "{app}\voice-engines\qwen-tts"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "NOTICE"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "Запустить PIVEN.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "runtime\Python311\*"; DestDir: "{app}\runtime\Python311"; Excludes: "__pycache__,*.pyc"; Flags: ignoreversion recursesubdirs
Source: ".packages\*"; DestDir: "{app}\.packages"; Excludes: "__pycache__,*.pyc"; Flags: ignoreversion recursesubdirs
Source: "llama.cpp\bin\*"; DestDir: "{app}\llama.cpp\bin"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\runtime\Python311\pythonw.exe"; Parameters: """{app}\app\window\main.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\piven.ico"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\runtime\Python311\pythonw.exe"; Parameters: """{app}\app\window\main.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\piven.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\runtime\Python311\pythonw.exe"; Parameters: """{app}\app\window\main.pyw"""; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\voice-engines"
Type: filesandordirs; Name: "{app}\app\__pycache__"
Type: files; Name: "{app}\*.log"

[Code]
function WebView2Installed: Boolean;
var
  Version: String;
begin
  Result :=
    RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version);
  Result := Result and (Version <> '') and (Version <> '0.0.0.0');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ErrorCode: Integer;
begin
  if (CurStep = ssPostInstall) and not WizardSilent and not WebView2Installed then
    if MsgBox(CustomMessage('NoWebView2'), mbConfirmation, MB_YESNO) = IDYES then
      ShellExec('open', 'https://developer.microsoft.com/microsoft-edge/webview2/', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;
