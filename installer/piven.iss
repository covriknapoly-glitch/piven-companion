; PIVEN Companion installer (Inno Setup 6.3+ / 7).
; Build:  "%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe" installer\piven.iss
; Packs the program with its bundled Python, Qt, packages and llama.cpp.
; Neural-network models and voice engines are not included: the program downloads them on request.

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
; Installed per user: the program writes voice engines and their models next to itself.
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
ru.WebInterface=PIVEN Companion
en.WebInterface=PIVEN Companion
zh.WebInterface=PIVEN Companion
ru.ClassicWindow=PIVEN Companion (обычное окно)
en.ClassicWindow=PIVEN Companion (classic window)
zh.ClassicWindow=PIVEN Companion（经典窗口）
ru.NoWebView2=Для веб-интерфейса нужен Microsoft Edge WebView2 Runtime, а он не найден. Скачать его с сайта Microsoft после установки?
en.NoWebView2=The web interface needs Microsoft Edge WebView2 Runtime, which was not found. Open the Microsoft download page after setup?
zh.NoWebView2=网页界面需要 Microsoft Edge WebView2 Runtime，但未找到。安装完成后打开 Microsoft 下载页面吗？

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; The program itself
Source: "app\*"; DestDir: "{app}\app"; Excludes: "__pycache__,*.pyc,*.log"; Flags: ignoreversion recursesubdirs
Source: "assets\*"; DestDir: "{app}\assets"; Excludes: "piven_logo_2026.png,piven_logo.png"; Flags: ignoreversion recursesubdirs
Source: "docs\*"; DestDir: "{app}\docs"; Flags: ignoreversion recursesubdirs
Source: "skills\*"; DestDir: "{app}\skills"; Flags: ignoreversion recursesubdirs
Source: "modern-ui\dist\*"; DestDir: "{app}\modern-ui\dist"; Flags: ignoreversion recursesubdirs
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "NOTICE"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "Запустить веб-интерфейс.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "Запустить компаньон.cmd"; DestDir: "{app}"; Flags: ignoreversion
; Voice: only the launch scripts; engines and models are installed from the program
Source: "voice\README.md"; DestDir: "{app}\voice"; Flags: ignoreversion
Source: "voice\asr-bridge.py"; DestDir: "{app}\voice"; Flags: ignoreversion
Source: "voice\start-*.bat"; DestDir: "{app}\voice"; Flags: ignoreversion
Source: "voice-servers\README.md"; DestDir: "{app}\voice-servers"; Flags: ignoreversion
Source: "voice-servers\server.py"; DestDir: "{app}\voice-servers"; Flags: ignoreversion
Source: "voice-servers\hf_voice_server.py"; DestDir: "{app}\voice-servers"; Flags: ignoreversion
Source: "voice-servers\start-qwen-tts.bat"; DestDir: "{app}\voice-servers"; Flags: ignoreversion
; Bundled runtimes
Source: "runtime\Python311\*"; DestDir: "{app}\runtime\Python311"; Excludes: "__pycache__,*.pyc"; Flags: ignoreversion recursesubdirs
Source: ".packages\*"; DestDir: "{app}\.packages"; Excludes: "__pycache__,*.pyc"; Flags: ignoreversion recursesubdirs
Source: ".qt_runtime\*"; DestDir: "{app}\.qt_runtime"; Excludes: "__pycache__,*.pyc"; Flags: ignoreversion recursesubdirs
Source: "llama.cpp\bin\*"; DestDir: "{app}\llama.cpp\bin"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\{cm:WebInterface}"; Filename: "{app}\runtime\Python311\pythonw.exe"; Parameters: """{app}\app\web_companion.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\piven.ico"
Name: "{group}\{cm:ClassicWindow}"; Filename: "{app}\runtime\Python311\pythonw.exe"; Parameters: """{app}\app\desktop_companion.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\piven.ico"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{cm:WebInterface}"; Filename: "{app}\runtime\Python311\pythonw.exe"; Parameters: """{app}\app\web_companion.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\piven.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\runtime\Python311\pythonw.exe"; Parameters: """{app}\app\web_companion.pyw"""; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; What the program added next to itself: caches, logs, voice engines and their models.
; Chats, settings and chat models in %LOCALAPPDATA%\OllamaCompanion stay.
Type: filesandordirs; Name: "{app}\voice"
Type: filesandordirs; Name: "{app}\voice-servers"
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
