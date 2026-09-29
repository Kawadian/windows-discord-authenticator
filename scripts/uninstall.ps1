#Requires -RunAsAdministrator
param([switch] $RemoveAccount)
$ErrorActionPreference = 'Stop'
$program = Join-Path $env:ProgramFiles 'UacApproval'
$python = Join-Path $program '.venv\Scripts\python.exe'
if (Test-Path $python) {
    & $python -m approval_agent.service stop 2>$null
    & $python -m approval_agent.service remove 2>$null
}
& schtasks.exe /Delete /TN UacApprovalWatchdog /F 2>$null | Out-Null
& schtasks.exe /Delete /TN UacApprovalWatchdogAtStartup /F 2>$null | Out-Null
Remove-ItemProperty 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run' -Name UacApprovalTray -ErrorAction SilentlyContinue
if ($RemoveAccount) {
    Remove-LocalUser -Name UacApproval -ErrorAction SilentlyContinue
}
Write-Host 'Service とタスクを削除しました。プログラムと設定は確認後に手動で削除してください。'
