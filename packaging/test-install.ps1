# Runs only on a disposable, elevated Windows CI runner. No Discord credentials.
$ErrorActionPreference = 'Stop'
$program = Join-Path $env:ProgramFiles 'UacApproval'
$data = Join-Path $env:ProgramData 'UacApproval'
$runKey = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run'
Set-ItemProperty $runKey UacApprovalTray 'restore-me-test'
$setup = (Get-ChildItem dist/installer/*.exe | Select-Object -First 1).FullName
try {
    foreach ($attempt in 1..2) {
        $p = Start-Process $setup -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /LOG=setup-test.log' -Wait -PassThru
        if ($p.ExitCode -ne 0) { Get-Content setup-test.log | Select-Object -Last 55; throw "Install failed: $($p.ExitCode)" }
        (Get-Service UacApprovalService).WaitForStatus('Running', [TimeSpan]::FromSeconds(30))
        Start-Sleep -Seconds 2
        if ((Get-Service UacApprovalService).Status -ne 'Running') { throw 'Frozen service did not stay running' }
        $manifest = Get-Content "$data\installation.json" -Raw | ConvertFrom-Json
        if ($manifest.runValue -ne 'restore-me-test') { throw 'Original autorun not preserved across upgrade' }
        if ((Get-LocalUser UacApproval).SID.Value -ne $manifest.accountSid) { throw 'Account mismatch' }
        $task = Get-ScheduledTask -TaskName UacApprovalWatchdog
        if ($task.Actions[0].Execute -ne (Join-Path $program 'service\UacApprovalService.exe') -or
            $task.Actions[0].Arguments -ne '--watchdog' -or $task.Triggers.Count -ne 2) { throw 'Watchdog registration mismatch' }
    }
    # Re-run the installer with credentials/settings from the currently installed release.
    # The update must preserve the configuration byte-for-byte and keep the account SID.
    $configPath = Join-Path $data 'config.json'
    $existingConfig = '{"bot_token":"update-test","channel_id":123,"owner_id":456}'
    [IO.File]::WriteAllText($configPath, $existingConfig)
    $oldSid = (Get-LocalUser UacApproval).SID.Value
    $p = Start-Process $setup -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /LOG=setup-update-test.log' -Wait -PassThru
    if ($p.ExitCode -ne 0) { Get-Content setup-update-test.log | Select-Object -Last 55; throw "Update failed: $($p.ExitCode)" }
    if ([IO.File]::ReadAllText($configPath) -cne $existingConfig) { throw 'Existing configuration was changed' }
    if ((Get-LocalUser UacApproval).SID.Value -ne $oldSid) { throw 'Account was replaced during update' }
    $privacyFile = Join-Path $env:LOCALAPPDATA 'UacApproval\privacy.json'
    New-Item -ItemType Directory -Force (Split-Path $privacyFile) | Out-Null
    Set-Content -LiteralPath $privacyFile -Value '{"screenshots":false}'
    $p = Start-Process "$program\unins000.exe" -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=uninstall-test.log' -Wait -PassThru
    if ($p.ExitCode -ne 0) { Get-Content uninstall-test.log | Select-String 'Provisioning failed|Lifecycle Uninstall'; throw "Uninstall failed: $($p.ExitCode)" }
    if (Get-Service UacApprovalService -ErrorAction SilentlyContinue) { throw 'Service remained' }
    if (Get-LocalUser UacApproval -ErrorAction SilentlyContinue) { throw 'Account remained' }
    if (Test-Path $data) { throw 'Configuration remained' }
    if (Test-Path $privacyFile) { throw 'User privacy preferences remained' }
    if ((Get-ItemProperty $runKey).UacApprovalTray -ne 'restore-me-test') { throw 'Autorun not restored' }
    foreach ($name in @('UacApprovalWatchdog')) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) { throw 'Watchdog remained' }
    }
} catch {
    throw
} finally {
    Remove-ItemProperty $runKey UacApprovalTray -ErrorAction SilentlyContinue
}
