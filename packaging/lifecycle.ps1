#Requires -RunAsAdministrator
param([ValidateSet('Prepare', 'Install', 'Uninstall', 'Resume')][string] $Mode)
$ErrorActionPreference = 'Stop'
trap {
    [Console]::Error.WriteLine(('Provisioning failed at line {0}: {1}' -f $_.InvocationInfo.ScriptLineNumber, $_.Exception.GetType().Name))
    exit 1
}
$program = Join-Path $env:ProgramFiles 'UacApproval'
$data = Join-Path $env:ProgramData 'UacApproval'
$manifestPath = Join-Path $data 'installation.json'
$runKey = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run'
$accountName = 'UacApproval'
$serviceName = 'UacApprovalService'
$tasks = @('UacApprovalWatchdog', 'UacApprovalWatchdogAtStartup')

function Native([string] $File, [string[]] $Arguments) {
    & $File @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "$File failed: $LASTEXITCODE" }
}
function SecureFile([string] $Path, [object] $Value) {
    if (-not (Test-Path -LiteralPath $Path)) { [IO.File]::WriteAllText($Path, '') }
    Native 'icacls.exe' @($Path, '/inheritance:r', '/grant:r', '*S-1-5-18:F', '*S-1-5-32-544:F')
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
}
function SaveManifest { SecureFile $manifestPath $script:manifest }
function StopComponents {
    foreach ($name in $tasks) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($task) {
            Disable-ScheduledTask -InputObject $task | Out-Null
            Stop-ScheduledTask -InputObject $task -ErrorAction SilentlyContinue
        }
    }
    $svc = Get-Service $serviceName -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -ne 'Stopped') {
        Stop-Service $serviceName -Force
        $svc.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(40))
    }
    Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath.StartsWith($program + '\', [StringComparison]::OrdinalIgnoreCase) -and
         $_.Name -in @('UacApproval.exe', 'UacApprovalService.exe')
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
# Reject junctions at the privileged storage roots.
foreach ($path in @($program, $data)) {
    if ((Test-Path -LiteralPath $path) -and ((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing reparse point: $path"
    }
}
$manifest = if (Test-Path $manifestPath) { Get-Content $manifestPath -Raw | ConvertFrom-Json } else { $null }
$existingAccount = Get-LocalUser -Name $accountName -ErrorAction SilentlyContinue
$existingService = Get-Service $serviceName -ErrorAction SilentlyContinue
if ($Mode -ne 'Uninstall' -and -not $manifest) {
    if ($existingAccount -or $existingService -or (Test-Path (Join-Path $data 'config.json'))) {
        throw 'UacApproval account, service or configuration already exists without an EXE installation record.'
    }
    foreach ($name in $tasks) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) { throw "Task already exists: $name" }
    }
}
if ($manifest -and $existingAccount -and $manifest.accountSid -ne $existingAccount.SID.Value) {
    throw 'Dedicated account SID has changed; refusing to alter this installation.'
}
if ($Mode -eq 'Resume') {
    foreach ($name in $tasks) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($task) { Enable-ScheduledTask -InputObject $task | Out-Null }
    }
    if ($existingService) { Start-Service $serviceName }
    exit 0
}
if ($Mode -eq 'Prepare') {
    StopComponents
    exit 0
}
if ($Mode -eq 'Install') {
    New-Item -ItemType Directory -Force -Path $program, $data | Out-Null
    foreach ($directory in @($program, $data)) {
        Native 'icacls.exe' @($directory, '/inheritance:r', '/grant:r', '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F', '*S-1-5-32-545:(OI)(CI)RX')
    }
    if (-not $manifest) {
        $key = Get-Item $runKey
        $oldRun = $key.GetValue('UacApprovalTray', $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        $kind = if ($null -ne $oldRun) { $key.GetValueKind('UacApprovalTray').ToString() } else { 'String' }
        $manifest = [pscustomobject]@{
            schema = 1; accountSid = $null
            runExisted = $null -ne $oldRun; runValue = $oldRun; runKind = $kind
        }
        SaveManifest
    }
    if (-not $manifest.accountSid) {
        $bytes = New-Object byte[] 48
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        $password = ConvertTo-SecureString ('Aa1!' + [Convert]::ToBase64String($bytes)) -AsPlainText -Force
        $account = New-LocalUser -Name $accountName -Password $password -PasswordNeverExpires -Description 'Temporary administrator credentials for UAC approval'
        $manifest.accountSid = $account.SID.Value
        SaveManifest
    }
    $account = Get-LocalUser -Name $accountName
    if ($account.SID.Value -ne $manifest.accountSid) { throw 'Dedicated account SID has changed; refusing to modify it.' }
    $admins = Get-LocalGroup -SID 'S-1-5-32-544'
    if (-not (Get-LocalGroupMember $admins | Where-Object { $_.SID.Value -eq $account.SID.Value })) {
        Add-LocalGroupMember -Group $admins -Member $account
    }
    $hostExe = Join-Path $program 'service\UacApprovalService.exe'
    if ($existingService) {
        Native 'sc.exe' @('config', $serviceName, 'binPath=', ('"{0}"' -f $hostExe), 'start=', 'auto', 'obj=', 'LocalSystem')
    } else {
        Native 'sc.exe' @('create', $serviceName, 'binPath=', ('"{0}"' -f $hostExe), 'start=', 'auto', 'DisplayName=', 'UAC Approval Discord Agent')
    }
    Native 'sc.exe' @('failure', $serviceName, 'reset=', '0', 'actions=', 'restart/60000/restart/60000/restart/60000')
    $action = '"{0}" --watchdog' -f $hostExe
    Native 'schtasks.exe' @('/Create', '/TN', $tasks[0], '/SC', 'MINUTE', '/MO', '1', '/RU', 'SYSTEM', '/RL', 'HIGHEST', '/TR', $action, '/F')
    Native 'schtasks.exe' @('/Create', '/TN', $tasks[1], '/SC', 'ONSTART', '/RU', 'SYSTEM', '/RL', 'HIGHEST', '/TR', $action, '/F')
    [IO.File]::WriteAllText((Join-Path $data 'tray.json'), '{"port":53927,"capture_interval_ms":750}', [Text.UTF8Encoding]::new($false))
    $configPath = Join-Path $data 'config.json'
    if (Test-Path $configPath) {
        $config = Get-Content $configPath -Raw | ConvertFrom-Json
        # Preserve existing port/interval on upgrades.
        [IO.File]::WriteAllText((Join-Path $data 'tray.json'), (@{port=$config.port; capture_interval_ms=$config.capture_interval_ms} | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
    }
    Start-Service $serviceName
    Set-ItemProperty $runKey -Name UacApprovalTray -Value ('"{0}" --background' -f (Join-Path $program 'UacApproval.exe'))
    # The frozen app owns its runtime; global Python and packages are not modified.
    exit 0
}
if ($Mode -eq 'Uninstall') {
    if (-not $manifest) { throw 'Installation ownership manifest is missing; automatic removal refused.' }
    StopComponents
    foreach ($name in $tasks) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
        }
    }
    if (Get-Service $serviceName -ErrorAction SilentlyContinue) { Native 'sc.exe' @('delete', $serviceName) }
    if ($existingAccount) {
        if ($existingAccount.SID.Value -ne $manifest.accountSid) { throw 'Dedicated account SID changed; removal refused.' }
        Remove-LocalUser -SID $existingAccount.SID
    }
    $current = (Get-Item $runKey).GetValue('UacApprovalTray')
    $ours = '"{0}" --background' -f (Join-Path $program 'UacApproval.exe')
    if ($current -eq $ours) {
        if ($manifest.runExisted) {
            New-ItemProperty $runKey -Name UacApprovalTray -Value $manifest.runValue -PropertyType $manifest.runKind -Force | Out-Null
        } else { Remove-ItemProperty $runKey -Name UacApprovalTray }
    }
    # Remove only this product's preferences in real local profiles. Never traverse links.
    foreach ($profile in Get-CimInstance Win32_UserProfile) {
        if (-not $profile.LocalPath) { continue }
        $safe = $true
        $candidate = $profile.LocalPath
        foreach ($part in @('', 'AppData', 'Local', 'UacApproval')) {
            if ($part) { $candidate = Join-Path $candidate $part }
            if (Test-Path -LiteralPath $candidate) {
                if ((Get-Item -LiteralPath $candidate -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { $safe = $false; break }
            }
        }
        if ($safe -and (Test-Path -LiteralPath $candidate)) {
            # Known files only: do not recurse through user-controlled child paths.
            foreach ($name in @('privacy.json', 'privacy.tmp')) {
                $file = Join-Path $candidate $name
                if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force }
            }
            if (-not (Get-ChildItem -LiteralPath $candidate -Force)) { [IO.Directory]::Delete($candidate) }
        }
    }
    Remove-Item -LiteralPath $data -Recurse -Force
}
