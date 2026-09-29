#Requires -RunAsAdministrator
param()
$ErrorActionPreference = 'Stop'

$source = Split-Path -Parent $PSScriptRoot
$program = Join-Path $env:ProgramFiles 'UacApproval'
$code = Join-Path $program 'source'
$data = Join-Path $env:ProgramData 'UacApproval'
$configPath = Join-Path $data 'config.json'
$account = 'UacApproval'

if ((Test-Path $configPath) -or (Get-LocalUser -Name $account -ErrorAction SilentlyContinue)) {
    throw '既存の設定または UacApproval アカウントがあります。新規インストール専用です。更新は operations.md を参照してください。'
}
$python = (& py -3 -c 'import sys; print(sys.executable)').Trim()
$site = (& py -3 -c 'import sysconfig; print(sysconfig.get_path("purelib"))').Trim()
$pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $pythonw) -or
    $python.StartsWith($env:USERPROFILE, [StringComparison]::OrdinalIgnoreCase) -or
    $site.StartsWith($env:USERPROFILE, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'すべてのユーザーがアクセスできるマシン全体の Python をインストールしてください。ユーザープロファイル内の Python は SYSTEM の Service から使用できません。'
}

$tokenSecure = Read-Host 'Discord Bot Token' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($tokenSecure)
try { $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
$channelId = [long](Read-Host '承認申請チャンネル ID')
$ownerId = [long](Read-Host '承認する本人の Discord ユーザー ID')
if ([string]::IsNullOrWhiteSpace($token) -or $channelId -le 0 -or $ownerId -le 0) {
    throw 'Bot Token と ID を入力してください。'
}

New-Item -ItemType Directory -Force -Path $program, $code, $data | Out-Null
# Service が読むコードを標準ユーザーが書き換えられないようにする。
& icacls.exe $program /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'コードディレクトリの ACL 設定に失敗しました。' }
& icacls.exe $data /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX' | Out-Null
if ($LASTEXITCODE -ne 0) { throw '設定ディレクトリの ACL 設定に失敗しました。' }

Copy-Item -Recurse -Force (Join-Path $source 'approval_agent') $code
Copy-Item -Force (Join-Path $source 'pyproject.toml') $code
Copy-Item -Force (Join-Path $source 'README.md') $code
& $python -m pip install --no-user --disable-pip-version-check $code
if ($LASTEXITCODE -ne 0) { throw 'パッケージのインストールに失敗しました。' }
& $python -m pywin32_postinstall -install
if ($LASTEXITCODE -ne 0) { throw 'pywin32 のマシン全体セットアップに失敗しました。' }

$config = @{
    bot_token = $token
    channel_id = $channelId
    owner_id = $ownerId
    admin_account = $account
    port = 53927
    capture_interval_ms = 750
    request_lifetime_seconds = 300
}
# Restrict the empty file before any token bytes are written to it.
[IO.File]::WriteAllText($configPath, '', [Text.UTF8Encoding]::new($false))
& icacls.exe $configPath /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Bot Token の ACL 設定に失敗しました。' }
[IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
Remove-Variable token
$tray = @{ port = 53927; capture_interval_ms = 750 } | ConvertTo-Json -Compress
[IO.File]::WriteAllText((Join-Path $data 'tray.json'), $tray, [Text.UTF8Encoding]::new($false))

$alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $bytes = New-Object byte[] 64
    $rng.GetBytes($bytes)
    $randomPassword = -join ($bytes | ForEach-Object { $alphabet[$_ % $alphabet.Length] })
}
finally { $rng.Dispose() }
$securePassword = ConvertTo-SecureString $randomPassword -AsPlainText -Force
New-LocalUser -Name $account -Password $securePassword -FullName 'Temporary UAC approval' -Description 'Temporary administrator credentials for UAC approval' -PasswordNeverExpires | Out-Null
$admins = Get-LocalGroup -SID 'S-1-5-32-544'
Add-LocalGroupMember -Group $admins.Name -Member $account
Remove-Variable randomPassword, securePassword

& $python -m approval_agent.service --startup auto install
if ($LASTEXITCODE -ne 0) { throw 'Windows Service の登録に失敗しました。' }
& sc.exe failure UacApprovalService reset= 0 actions= restart/60000/restart/60000/restart/60000 | Out-Null

$action = ('"{0}" -m approval_agent.watchdog' -f $python)
& schtasks.exe /Create /TN UacApprovalWatchdog /SC MINUTE /MO 1 /RU SYSTEM /RL HIGHEST /TR $action /F | Out-Null
if ($LASTEXITCODE -ne 0) { throw '期限監視タスクの登録に失敗しました。' }
& schtasks.exe /Create /TN UacApprovalWatchdogAtStartup /SC ONSTART /RU SYSTEM /RL HIGHEST /TR $action /F | Out-Null
if ($LASTEXITCODE -ne 0) { throw '起動時監視タスクの登録に失敗しました。' }

$runKey = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run'
Set-ItemProperty -Path $runKey -Name 'UacApprovalTray' -Value ('"{0}" -m approval_agent.tray' -f $pythonw)
& $python -m approval_agent.service start
if ($LASTEXITCODE -ne 0) { throw 'Windows Service を開始できませんでした。' }
& schtasks.exe /Run /TN UacApprovalWatchdog | Out-Null
Write-Host 'インストール完了。親の標準ユーザーで再ログオンし、Ctrl + Alt + F12 を試してください。'
