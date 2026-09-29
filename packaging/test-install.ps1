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
        if ($p.ExitCode -ne 0) { Get-Content setup-test.log; throw "Install failed: $($p.ExitCode)" }
        (Get-Service UacApprovalService).WaitForStatus('Running', [TimeSpan]::FromSeconds(30))
        Start-Sleep -Seconds 2
        if ((Get-Service UacApprovalService).Status -ne 'Running') { throw 'Frozen service did not stay running' }
        $manifest = Get-Content "$data\installation.json" -Raw | ConvertFrom-Json
        if ($manifest.runValue -ne 'restore-me-test') { throw 'Original autorun not preserved across upgrade' }
        if ((Get-LocalUser UacApproval).SID.Value -ne $manifest.accountSid) { throw 'Account mismatch' }
    }
    $p = Start-Process "$program\unins000.exe" -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=uninstall-test.log' -Wait -PassThru
    if ($p.ExitCode -ne 0) { Get-Content uninstall-test.log; throw "Uninstall failed: $($p.ExitCode)" }
    if (Get-Service UacApprovalService -ErrorAction SilentlyContinue) { throw 'Service remained' }
    if (Get-LocalUser UacApproval -ErrorAction SilentlyContinue) { throw 'Account remained' }
    if (Test-Path $data) { throw 'Configuration remained' }
    if ((Get-ItemProperty $runKey).UacApprovalTray -ne 'restore-me-test') { throw 'Autorun not restored' }
    foreach ($name in @('UacApprovalWatchdog', 'UacApprovalWatchdogAtStartup')) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) { throw 'Watchdog remained' }
    }
} catch {
    Get-Content setup-test.log -ErrorAction SilentlyContinue | Select-Object -Last 100
    Get-Content uninstall-test.log -ErrorAction SilentlyContinue | Select-Object -Last 60
    Get-ChildItem $program, $data -ErrorAction SilentlyContinue
    # This disposable runner has no credentials; show provisioning errors directly.
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File packaging/lifecycle.ps1 -Mode Install
    throw
} finally {
    Remove-ItemProperty $runKey UacApprovalTray -ErrorAction SilentlyContinue
}
