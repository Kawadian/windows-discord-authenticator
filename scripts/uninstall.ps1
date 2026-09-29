#Requires -RunAsAdministrator
param([switch] $RemoveAccount)
$ErrorActionPreference = 'Stop'
& sc.exe stop UacApprovalService 2>$null | Out-Null
Start-Sleep -Seconds 3
& sc.exe delete UacApprovalService 2>$null | Out-Null
& schtasks.exe /Delete /TN UacApprovalWatchdog /F 2>$null | Out-Null
& schtasks.exe /Delete /TN UacApprovalWatchdogAtStartup /F 2>$null | Out-Null
Remove-ItemProperty 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run' -Name UacApprovalTray -ErrorAction SilentlyContinue
if ($RemoveAccount) {
    Remove-LocalUser -Name UacApproval -ErrorAction SilentlyContinue
}
Write-Host 'Service とタスクを削除しました。プログラムと設定は確認後に手動で削除してください。'
