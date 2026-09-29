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
Filename: "{app}\UacApproval.exe"; Parameters: "--configure"; Description: "Discord の認証情報を設定する"; Flags: postinstall nowait skipifsilent runascurrentuser unchecked
Filename: "{app}\UacApproval.exe"; Description: "UAC Approval を起動する"; Flags: postinstall nowait skipifsilent runasoriginaluser

[Code]
function Lifecycle(Script, Mode: String): Boolean;
var Code: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + Script + '" -Mode ' + Mode,
    '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  ExtractTemporaryFile('lifecycle.ps1');
  if not Lifecycle(ExpandConstant('{tmp}\lifecycle.ps1'), 'Prepare') then
    Result := '既存環境の確認・停止に失敗しました。名前の衝突や Service の状態を確認してください。';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    if not Lifecycle(ExpandConstant('{app}\lifecycle.ps1'), 'Install') then
      RaiseException('Service の登録に失敗しました。インストーラーを再実行して修復してください。');
end;

function InitializeUninstall(): Boolean;
begin
  if UninstallSilent then Result := True
  else Result := MsgBox('Service、専用管理者アカウント、認証設定、全ユーザーの本アプリのプライバシー設定を削除します。続行しますか？',
    mbConfirmation, MB_YESNO) = IDYES;
  if Result then begin
    Result := Lifecycle(ExpandConstant('{app}\lifecycle.ps1'), 'Uninstall');
    if not Result then MsgBox('削除処理に失敗しました。状態を確認して再試行してください。', mbError, MB_OK);
  end;
end;
