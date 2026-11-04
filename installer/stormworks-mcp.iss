; Inno Setup script for the Stormworks MCP Windows installer.
; Build with tools/build_installer.py, which passes the version and the built server folder.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\stormworks-mcp"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#define AppName "Stormworks MCP"
#define AppExe "stormworks-mcp.exe"
; Never change: Windows finds earlier installs by this ID.
#define AppGuid "20748683-2FB1-4BC7-9C12-7CA37ABA71FF"

[Setup]
AppId={{{#AppGuid}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=macery12
AppPublisherURL=https://github.com/macery12/Stormworks-MCP
AppSupportURL=https://github.com/macery12/Stormworks-MCP/issues
AppUpdatesURL=https://github.com/macery12/Stormworks-MCP/releases
VersionInfoVersion={#AppVersion}
; Per-user by default (no admin); the first page offers all users, which needs elevation.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousPrivileges=yes
; Close running copies (servers the AI clients started, or the setup menu) before replacing them.
CloseApplications=force
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile=..\LICENSE
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
OutputDir={#OutputDir}
OutputBaseFilename=stormworks-mcp-setup
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
SetupLogging=yes

[InstallDelete]
; Each version ships its own Python libraries; never mix them with an older version's.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Tasks]
; Offered only for clients found on this account. checkedonce: preselected on a first install,
; not on upgrades (the entry already points at this folder).
Name: "clientclaude"; Description: "Add to Claude Desktop (close Claude first; it then starts the server by itself)"; GroupDescription: "Connect your AI client (replaces an existing Stormworks entry and keeps a backup; remove any older Stormworks MCP setup first):"; Check: HasClaude; Flags: checkedonce
Name: "clientcodex"; Description: "Add to ChatGPT / Codex (close it first)"; GroupDescription: "Connect your AI client (replaces an existing Stormworks entry and keeps a backup; remove any older Stormworks MCP setup first):"; Check: HasCodex; Flags: checkedonce

[Icons]
; Opens the setup menu (add to a client, open the log, check for updates). The server itself
; never needs it: the AI client starts the EXE with --stdio.
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; Comment: "Set up Stormworks MCP for your AI client"

[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#AppGuid}}_is1';

var
  MaintenancePage: TInputOptionWizardPage;
  PreviousUninstaller, PreviousVersion: String;
  Leaving: Boolean;

function FindPrevious(): Boolean;
var
  Roots: array[0..2] of Integer;
  I: Integer;
begin
  Result := False;
  Roots[0] := HKCU;
  Roots[1] := HKLM64;
  Roots[2] := HKLM32;
  for I := 0 to 2 do
    if RegQueryStringValue(Roots[I], UninstallKey, 'UninstallString', PreviousUninstaller) then
    begin
      if not RegQueryStringValue(Roots[I], UninstallKey, 'DisplayVersion', PreviousVersion) then
        PreviousVersion := 'unknown';
      Result := True;
      Exit;
    end;
end;

{ Stop any copy running from the install folder: the servers MCP clients start and the setup
  menu. Restart Manager covers most cases; this catches the rest. A client loses its tools until
  it is restarted, which is why the tasks ask to close clients first. }
procedure StopRunning(Dir: String);
var
  Code: Integer;
begin
  StringChangeEx(Dir, '''', '''''', True);
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "Get-Process stormworks-mcp -ErrorAction SilentlyContinue | ' +
    'Where-Object { $_.Path -and $_.Path.StartsWith(''' + Dir + '\'', [StringComparison]::OrdinalIgnoreCase) } | ' +
    'Stop-Process -Force"', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

procedure InitializeWizard();
begin
  if FindPrevious() then
  begin
    MaintenancePage := CreateInputOptionPage(wpWelcome,
      '{#AppName} is already installed',
      'Version ' + PreviousVersion + ' is installed on this computer.',
      'Choose what to do, then click Next.', True, False);
    MaintenancePage.Add('Upgrade or repair: install version {#AppVersion} in the same folder (keeps your settings, designs and prefabs)');
    MaintenancePage.Add('Uninstall {#AppName}');
    MaintenancePage.Values[0] := True;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Code: Integer;
begin
  Result := True;
  if (MaintenancePage <> nil) and (CurPageID = MaintenancePage.ID) and MaintenancePage.Values[1] then
  begin
    if not Exec(RemoveQuotes(PreviousUninstaller), '', '', SW_SHOW, ewWaitUntilTerminated, Code) then
      MsgBox('The uninstaller could not be started: ' + SysErrorMessage(Code), mbError, MB_OK);
    Leaving := True;
    WizardForm.Close;
    Result := False;
  end;
end;

procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if Leaving then
    Confirm := False;
end;

{ The EXE reads the same variables when it writes the settings, so these agree with it. }
function HasClaude(): Boolean;
begin
  Result := DirExists(AddBackslash(GetEnv('APPDATA')) + 'Claude');
end;

function HasCodex(): Boolean;
begin
  if GetEnv('CODEX_HOME') <> '' then
    Result := DirExists(GetEnv('CODEX_HOME'))
  else
    Result := DirExists(AddBackslash(GetEnv('USERPROFILE')) + '.codex');
end;

procedure AddClient(Task, Client, Name: String);
var
  Code: Integer;
begin
  if not WizardIsTaskSelected(Task) then
    Exit;
  WizardForm.StatusLabel.Caption := 'Adding Stormworks MCP to ' + Name + '...';
  { As the user who started setup, so an all-users install still writes their own settings. }
  if not ExecAsOriginalUser(ExpandConstant('{app}\{#AppExe}'), '--add-client ' + Client + ' --replace', '',
      SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then
    SuppressibleMsgBox('Could not add Stormworks MCP to ' + Name + '. Open Stormworks MCP and use MCP > Set up instead.',
      mbInformation, MB_OK, IDOK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    AddClient('clientclaude', 'claude', 'Claude Desktop');
    AddClient('clientcodex', 'codex', 'ChatGPT / Codex');
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunning(ExpandConstant('{app}'));
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    StopRunning(ExpandConstant('{app}'));
end;
