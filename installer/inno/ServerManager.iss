; Server Manager — Inno Setup
; Built by: .\build.ps1
; Payload: artifacts\payload\  →  dist\ServerManager-Setup.exe

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#ifndef PayloadDir
  #define PayloadDir "..\..\artifacts\payload"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist"
#endif

#define MyAppName "Server Manager"
#define MyAppPublisher "Skywere Industries"
#define MyAppExeName "ServerManager.exe"
#define MyAppRegKey "Software\SkywereIndustries\Servermanager"
#define MyAppService "ServerManagerService"

[Setup]
AppId={{A8F3C2E1-9B4D-4F71-8E2A-1B2C3D4E5F60}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\ServerManager
DefaultGroupName=Skywere Industries
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=ServerManager-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\..\icons\servermanager.ico
UninstallDisplayIcon={app}\icons\servermanager.ico
CloseApplications=force
RestartApplications=no
SetupLogging=yes
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startmenuicon"; Description: "Create &Start Menu shortcuts (Skywere Industries)"; GroupDescription: "Additional icons:"; Flags: checkedonce
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: checkedonce
Name: "firewall"; Description: "Open Windows &Firewall ports for Web / HostRuntime / Cluster"; GroupDescription: "System:"; Flags: checkedonce
Name: "service"; Description: "Install / keep Windows &Service (auto-start)"; GroupDescription: "System:"; Flags: checkedonce
Name: "tray"; Description: "Start &tray icon at user logon"; GroupDescription: "System:"; Flags: checkedonce

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\icons\servermanager.ico"; DestDir: "{app}\icons"; DestName: "servermanager.ico"; Flags: ignoreversion
Source: "..\..\icons\servermanager.ico"; DestDir: "{app}"; DestName: "servermanager.ico"; Flags: ignoreversion

[Dirs]
Name: "{app}\runtime"
Name: "{app}\runtime\db"
Name: "{app}\runtime\logs"
Name: "{app}\runtime\logs\components"
Name: "{app}\runtime\temp"
Name: "{app}\runtime\ssl"
Name: "{app}\runtime\www"
Name: "{app}\runtime\config"
Name: "{app}\runtime\icons"

[Icons]
Name: "{autoprograms}\Skywere Industries\{#MyAppName}"; Filename: "{app}\ServerManager.HostUI.exe"; WorkingDir: "{app}"; IconFilename: "{app}\icons\servermanager.ico"; Comment: "Local Host Dashboard"; Tasks: startmenuicon
Name: "{autoprograms}\Skywere Industries\{#MyAppName} (AppHost)"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\icons\servermanager.ico"; Comment: "Start Server Manager services"; Tasks: startmenuicon
Name: "{autoprograms}\Skywere Industries\{#MyAppName} Tray"; Filename: "{app}\ServerManager.Tray.exe"; WorkingDir: "{app}"; IconFilename: "{app}\icons\servermanager.ico"; Comment: "Tray icon (user session)"; Tasks: startmenuicon
Name: "{autoprograms}\Skywere Industries\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"; IconFilename: "{app}\icons\servermanager.ico"; Tasks: startmenuicon
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\ServerManager.HostUI.exe"; WorkingDir: "{app}"; IconFilename: "{app}\icons\servermanager.ico"; Tasks: desktopicon
Name: "{commonstartup}\{#MyAppName} Tray"; Filename: "{app}\ServerManager.Tray.exe"; WorkingDir: "{app}"; IconFilename: "{app}\icons\servermanager.ico"; Tasks: tray

[Registry]
Root: HKLM; Subkey: "{#MyAppRegKey}"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKLM; Subkey: "{#MyAppRegKey}"; ValueType: string; ValueName: "Servermanagerdir"; ValueData: "{app}\runtime"
Root: HKLM; Subkey: "{#MyAppRegKey}"; ValueType: dword; ValueName: "WebPort"; ValueData: "{code:GetWebPort}"
Root: HKLM; Subkey: "{#MyAppRegKey}"; ValueType: dword; ValueName: "HostRuntimePort"; ValueData: "{code:GetRuntimePort}"
Root: HKLM; Subkey: "{#MyAppRegKey}"; ValueType: dword; ValueName: "ClusterPort"; ValueData: "{code:GetClusterPort}"
Root: HKLM; Subkey: "{#MyAppRegKey}"; ValueType: string; ValueName: "HostType"; ValueData: "standalone"
Root: HKLM; Subkey: "{#MyAppRegKey}"; ValueType: string; ValueName: "ClusterEnabled"; ValueData: "false"
Root: HKLM; Subkey: "{#MyAppRegKey}"; ValueType: string; ValueName: "SQLType"; ValueData: "sqlite"
Root: HKLM; Subkey: "{#MyAppRegKey}"; ValueType: string; ValueName: "SteamCmdPath"; ValueData: "{code:GetSteamCmd}"
Root: HKLM; Subkey: "{#MyAppRegKey}"; ValueType: dword; ValueName: "InstallAsService"; ValueData: "1"; Tasks: service; Flags: uninsdeletevalue
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ServerManagerTray"; ValueData: """{app}\ServerManager.Tray.exe"""; Tasks: tray; Flags: uninsdeletevalue

[Run]
; Interactive AppHost only when NOT keeping/using the Windows service
Filename: "{app}\{#MyAppExeName}"; Description: "Start {#MyAppName} services (interactive)"; Flags: nowait postinstall skipifsilent; Check: not ShouldUseService
; Tray must run in the user session (services cannot show NotifyIcon)
Filename: "{app}\ServerManager.Tray.exe"; Description: "Start tray icon"; Flags: nowait postinstall skipifsilent runasoriginaluser; Tasks: tray
Filename: "{app}\ServerManager.HostUI.exe"; Description: "Open local Host Dashboard"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
Filename: "sc.exe"; Parameters: "stop {#MyAppService}"; Flags: runhidden waituntilterminated; RunOnceId: "StopSvc"
Filename: "sc.exe"; Parameters: "delete {#MyAppService}"; Flags: runhidden waituntilterminated; RunOnceId: "DelSvc"

[Code]
var
  OptionsPage: TInputQueryWizardPage;
  WebPortValue: String;
  RuntimePortValue: String;
  ClusterPortValue: String;
  SteamCmdValue: String;

function GetWebPort(Param: String): String; begin Result := WebPortValue; end;
function GetRuntimePort(Param: String): String; begin Result := RuntimePortValue; end;
function GetClusterPort(Param: String): String; begin Result := ClusterPortValue; end;
function GetSteamCmd(Param: String): String; begin Result := SteamCmdValue; end;

function ServiceExists: Boolean;
var
  ResultCode: Integer;
begin
  Exec('sc.exe', 'query {#MyAppService}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := ResultCode = 0;
end;

function RegWantsService: Boolean;
var
  V: Cardinal;
begin
  Result := False;
  if RegQueryDWordValue(HKLM, '{#MyAppRegKey}', 'InstallAsService', V) then
    Result := V <> 0;
end;

function ShouldUseService: Boolean;
begin
  { Keep/upgrade existing service even if the task was left unchecked on a repair/upgrade. }
  Result := WizardIsTaskSelected('service') or ServiceExists or RegWantsService;
end;

function IsServiceTask: Boolean;
begin
  Result := WizardIsTaskSelected('service');
end;

function IsFirewallTask: Boolean;
begin
  Result := WizardIsTaskSelected('firewall');
end;

function JsonEscape(const S: String): String;
var
  I: Integer;
  C: Char;
begin
  Result := '';
  for I := 1 to Length(S) do
  begin
    C := S[I];
    if C = '\' then Result := Result + '\\'
    else if C = '"' then Result := Result + '\"'
    else Result := Result + C;
  end;
end;

procedure WriteRuntimeConfig;
var
  CfgDir, CfgFile, Json: String;
begin
  CfgDir := ExpandConstant('{app}\runtime\config');
  ForceDirectories(CfgDir);
  CfgFile := CfgDir + '\appsettings.json';
  Json :=
    '{' + #13#10 +
    '  "ServerManager": {' + #13#10 +
    '    "RootPath": "' + JsonEscape(ExpandConstant('{app}\runtime')) + '",' + #13#10 +
    '    "WebPort": ' + WebPortValue + ',' + #13#10 +
    '    "HostRuntimePort": ' + RuntimePortValue + ',' + #13#10 +
    '    "ClusterPort": ' + ClusterPortValue + ',' + #13#10 +
    '    "SteamCmdPath": "' + JsonEscape(SteamCmdValue) + '"' + #13#10 +
    '  }' + #13#10 +
    '}';
  SaveStringToFile(CfgFile, Json, False);
end;

procedure OpenFirewallPort(const RuleName, Port: String);
var
  ResultCode: Integer;
begin
  Exec('netsh.exe',
    'advfirewall firewall delete rule name="' + RuleName + '"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('netsh.exe',
    'advfirewall firewall add rule name="' + RuleName + '" dir=in action=allow protocol=TCP localport=' + Port,
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure StopServerManagerProcesses;
var
  ResultCode: Integer;
begin
  { Prefer a clean service stop so file locks clear before overwrite. }
  if ServiceExists then
  begin
    Exec('sc.exe', 'stop {#MyAppService}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(2000);
  end;
  Exec('taskkill.exe', '/F /IM ServerManager.HostUI.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/F /IM ServerManager.Tray.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/F /IM ServerManager.Web.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/F /IM ServerManager.HostRuntime.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/F /IM ServerManager.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1500);
end;

procedure EnsureWindowsService;
var
  ExePath, Args: String;
  ResultCode: Integer;
  Created: Boolean;
begin
  ExePath := ExpandConstant('{app}\{#MyAppExeName}');
  Created := False;

  if ServiceExists then
  begin
    { Upgrade path: NEVER delete the service (delete often leaves it "marked for deletion"). }
    Args := 'config {#MyAppService} binPath= "' + ExePath + '" start= auto DisplayName= ServerManager';
    Exec('sc.exe', Args, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end
  else
  begin
    Args := 'create {#MyAppService} binPath= "' + ExePath + '" start= auto DisplayName= ServerManager';
    if not Exec('sc.exe', Args, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    begin
      MsgBox('Failed to launch sc.exe to create the Windows service.', mbError, MB_OK);
      Exit;
    end;
    if ResultCode <> 0 then
    begin
      MsgBox('Windows service create failed (sc exit ' + IntToStr(ResultCode) + ').' + #13#10 +
        'You can still start ServerManager.exe manually.', mbError, MB_OK);
      Exit;
    end;
    Created := True;
  end;

  Exec('sc.exe', 'description {#MyAppService} "Skywere Industries Server Manager"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('sc.exe', 'failure {#MyAppService} reset= 86400 actions= restart/5000/restart/5000/restart/5000', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  RegWriteDWordValue(HKLM, '{#MyAppRegKey}', 'InstallAsService', 1);

  Sleep(500);
  if not Exec('sc.exe', 'start {#MyAppService}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    MsgBox('Service is registered but could not be started. Use services.msc.', mbError, MB_OK)
  else if ResultCode <> 0 then
  begin
    { 1056 = already running — treat as success }
    if ResultCode <> 1056 then
      MsgBox('Service start returned exit ' + IntToStr(ResultCode) +
        '. If this follows an upgrade, wait a few seconds and start ServerManagerService from services.msc.' + #13#10 +
        'Check Event Viewer if it keeps failing.', mbError, MB_OK);
  end
  else if Created then
    Log('Created and started {#MyAppService}');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  NeedsRestart := False;
  StopServerManagerProcesses;
  Result := '';
end;

procedure InitializeWizard;
begin
  WebPortValue := '18080';
  RuntimePortValue := '18091';
  ClusterPortValue := '15001';
  SteamCmdValue := '';

  OptionsPage := CreateInputQueryPage(wpSelectTasks,
    'Ports and SteamCMD',
    'Configure network ports and optional SteamCMD path.',
    'These values are written to the registry and runtime\config\appsettings.json.');
  OptionsPage.Add('Web port:', False);
  OptionsPage.Add('HostRuntime port:', False);
  OptionsPage.Add('Cluster port:', False);
  OptionsPage.Add('SteamCMD path (optional):', False);
  OptionsPage.Values[0] := WebPortValue;
  OptionsPage.Values[1] := RuntimePortValue;
  OptionsPage.Values[2] := ClusterPortValue;
  OptionsPage.Values[3] := SteamCmdValue;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpSelectTasks then
  begin
    { On upgrade/repair, keep service + tray selected when already in use. }
    if ServiceExists or RegWantsService then
      WizardSelectTasks('service');
    WizardSelectTasks('tray');
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = OptionsPage.ID then
  begin
    WebPortValue := Trim(OptionsPage.Values[0]);
    RuntimePortValue := Trim(OptionsPage.Values[1]);
    ClusterPortValue := Trim(OptionsPage.Values[2]);
    SteamCmdValue := Trim(OptionsPage.Values[3]);
    if WebPortValue = '' then WebPortValue := '18080';
    if RuntimePortValue = '' then RuntimePortValue := '18091';
    if ClusterPortValue = '' then ClusterPortValue := '15001';
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  WwwSrc, WwwDst: String;
  ResultCode: Integer;
begin
  if CurStep = ssInstall then
    StopServerManagerProcesses;

  if CurStep = ssPostInstall then
  begin
    WriteRuntimeConfig;

    WwwSrc := ExpandConstant('{app}\www');
    WwwDst := ExpandConstant('{app}\runtime\www');
    if DirExists(WwwSrc) then
      Exec('xcopy.exe', '"' + WwwSrc + '\*" "' + WwwDst + '\" /E /I /Y /Q', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    if IsFirewallTask then
    begin
      OpenFirewallPort('ServerManager-Web', WebPortValue);
      OpenFirewallPort('ServerManager-Runtime', RuntimePortValue);
      OpenFirewallPort('ServerManager-Cluster', ClusterPortValue);
    end;

    if ShouldUseService then
      EnsureWindowsService;
  end;
end;
