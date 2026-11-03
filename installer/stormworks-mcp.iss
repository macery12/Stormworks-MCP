; Inno Setup script for the Stormworks MCP Windows installer.
; Build with tools/build_installer.py, which passes the version and the built EXE.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceExe
  #define SourceExe "..\dist\stormworks-mcp.exe"
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
; Close a running copy (the desktop app or a client's --connect bridge) before replacing it.
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

[Files]
Source: "{#SourceExe}"; DestDir: "{app}"; DestName: "{#AppExe}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; Comment: "Build Stormworks vehicles with your AI client"

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

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

{ Stop any copy running from the install folder: the desktop app and the --connect bridges
  MCP clients start. Restart Manager covers most cases; this catches orphaned bridges. }
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
