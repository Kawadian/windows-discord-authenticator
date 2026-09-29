#define AppVersion "0.2.0"
[Setup]
AppId={{DAEE1E8D-2A88-4A25-AD5D-76B726B478CB}
AppName=UAC Approval
AppVersion={#AppVersion}
DefaultDirName={autopf}\UacApproval
DisableDirPage=yes
DefaultGroupName=UAC Approval
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\dist\installer
OutputBaseFilename=UacApproval-Setup-{#AppVersion}-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\UacApproval.exe
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\UacApproval\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\UacApprovalService\*"; DestDir: "{app}\service"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "lifecycle.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "lifecycle.ps1"; Flags: dontcopy

[Icons]
Name: "{group}\UAC Approval"; Filename: "{app}\UacApproval.exe"
Name: "{group}\Uninstall UAC Approval"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\UacApproval.exe"; Parameters: "--configure"; Description: "Discord の認証情報を設定する"; Flags: postinstall nowait skipifsilent runascurrentuser unchecked; Check: InstallationSucceeded
Filename: "{app}\UacApproval.exe"; Description: "UAC Approval を起動する"; Flags: postinstall nowait skipifsilent runasoriginaluser; Check: InstallationSucceeded

[Messages]
japanese.ConfirmUninstall=Service、専用管理者アカウント、認証情報、全ユーザーの本アプリの設定を削除し、自動起動設定を復元します。%n%n%1 を完全にアンインストールしますか？

[Code]
var
  Prepared, Completed, ExistingInstallation, InstallFailed: Boolean;
function InstallationSucceeded: Boolean;
begin
  Result := not InstallFailed;
end;

function Lifecycle(Script, Mode: String): Boolean;
var Code: Integer;
begin
  Result := ExecAndLogOutput(ExpandConstant('{sysnative}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + Script + '" -Mode ' + Mode,
    '', SW_HIDE, ewWaitUntilTerminated, Code, nil) and (Code = 0);
  Log('Lifecycle ' + Mode + ': exit ' + IntToStr(Code));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  ExistingInstallation := FileExists(ExpandConstant('{commonappdata}\UacApproval\installation.json')) or
    FileExists(ExpandConstant('{commonappdata}\UacApproval\config.json'));
  ExtractTemporaryFile('lifecycle.ps1');
  if not Lifecycle(ExpandConstant('{tmp}\lifecycle.ps1'), 'Prepare') then
    Result := '既存環境の確認・停止に失敗しました。名前の衝突や Service の状態を確認してください。'
  else Prepared := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssDone then Completed := not InstallFailed;
  if CurStep = ssPostInstall then
    if not Lifecycle(ExpandConstant('{app}\lifecycle.ps1'), 'Install') then begin
      InstallFailed := True;
      SuppressibleMsgBox('Service の登録に失敗しました。インストーラーを再実行して修復してください。', mbError, MB_OK, IDOK);
    end;
end;

function GetCustomSetupExitCode: Integer;
begin
  if InstallFailed then Result := 1 else Result := 0;
end;

procedure DeinitializeSetup;
begin
  if Prepared and not Completed then begin
    if ExistingInstallation then
      Lifecycle(ExpandConstant('{tmp}\lifecycle.ps1'), 'Resume')
    else if FileExists(ExpandConstant('{commonappdata}\UacApproval\installation.json')) then
      Lifecycle(ExpandConstant('{tmp}\lifecycle.ps1'), 'Uninstall');
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then begin
    if not Lifecycle(ExpandConstant('{app}\lifecycle.ps1'), 'Uninstall') then begin
      SuppressibleMsgBox('削除処理に失敗しました。状態を確認して再試行してください。', mbError, MB_OK, IDOK);
      Abort;
    end;
  end;
end;
