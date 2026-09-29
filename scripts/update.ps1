#Requires -RunAsAdministrator
param(
    [ValidatePattern('^[A-Za-z0-9._/-]+$')]
    [string] $Ref = 'main',
    [string] $SourcePath,
    [switch] $CheckOnly,
    [switch] $Force
)

$ErrorActionPreference = 'Stop'
$repo = 'Kawadian/windows-discord-authenticator'
$program = Join-Path $env:ProgramFiles 'UacApproval'
$code = Join-Path $program 'source'
$data = Join-Path $env:ProgramData 'UacApproval'
$marker = Join-Path $data 'installed-version.json'
$serviceName = 'UacApprovalService'
$work = Join-Path $program ('update-' + [guid]::NewGuid().ToString('N'))
$backup = Join-Path $program ('source.backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
$stopped = $false
$swapped = $false
$updated = $false
$previousMarker = if (Test-Path $marker) { [IO.File]::ReadAllText($marker) } else { $null }

function Invoke-Python {
    param([string[]] $Arguments)
    & $script:python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python コマンドが終了コード $LASTEXITCODE で失敗しました。"
    }
}

function Set-ServiceState([string] $State) {
    $service = Get-Service -Name $script:serviceName -ErrorAction Stop
    if ($State -eq 'Stopped' -and $service.Status -ne 'Stopped') {
        Stop-Service -Name $script:serviceName -ErrorAction Stop
    } elseif ($State -eq 'Running' -and $service.Status -ne 'Running') {
        Start-Service -Name $script:serviceName -ErrorAction Stop
    }
    $desired = if ($State -eq 'Stopped') {
        [System.ServiceProcess.ServiceControllerStatus]::Stopped
    } else {
        [System.ServiceProcess.ServiceControllerStatus]::Running
    }
    (Get-Service -Name $script:serviceName).WaitForStatus($desired, [TimeSpan]::FromSeconds(30))
}

if (-not (Test-Path (Join-Path $data 'config.json')) -or
    -not (Test-Path (Join-Path $data 'tray.json')) -or
    -not (Test-Path (Join-Path $code 'pyproject.toml')) -or
    -not (Get-Service -Name $serviceName -ErrorAction SilentlyContinue) -or
    -not (Get-ScheduledTask -TaskName 'UacApprovalWatchdog' -ErrorAction SilentlyContinue)) {
    throw '既存のインストールが見つかりません。先に install.ps1 を実行してください。'
}

$python = (& py -3 -c 'import sys; print(sys.executable)').Trim()
$pythonSite = (& py -3 -c 'import sysconfig; print(sysconfig.get_path("purelib"))').Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $python) -or
    $python.StartsWith($env:USERPROFILE, [StringComparison]::OrdinalIgnoreCase) -or
    $pythonSite.StartsWith($env:USERPROFILE, [StringComparison]::OrdinalIgnoreCase)) {
    throw '全ユーザー向け Python が見つかりません。現在のインストールと同じ Python を使ってください。'
}

$target = 'local'
if (-not $SourcePath) {
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $headers = @{ 'User-Agent' = 'UacApprovalUpdater'; 'Accept' = 'application/vnd.github+json' }
    $escapedRef = [uri]::EscapeDataString($Ref)
    $commit = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/commits/$escapedRef" -Headers $headers
    $target = [string] $commit.sha
    if ($target -notmatch '^[a-f0-9]{40}$') { throw 'GitHub のコミット SHA を確認できませんでした。' }
    if (-not $Force -and $previousMarker) {
        $previous = $previousMarker | ConvertFrom-Json
        if ($previous.commit -eq $target) {
            Write-Host "更新済みです: $target"
            return
        }
    }
} elseif (-not (Test-Path $SourcePath -PathType Container)) {
    throw "ソースディレクトリが見つかりません: $SourcePath"
}

Write-Host "更新対象: $target"
if ($CheckOnly) { return }

New-Item -ItemType Directory -Path $work | Out-Null
try {
    if ($SourcePath) {
        $repoRoot = (Resolve-Path $SourcePath).Path
    } else {
        $zip = Join-Path $work 'source.zip'
        $extract = Join-Path $work 'archive'
        Invoke-WebRequest -UseBasicParsing -Headers $headers -Uri "https://api.github.com/repos/$repo/zipball/$target" -OutFile $zip
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive = [IO.Compression.ZipFile]::OpenRead($zip)
        try {
            foreach ($entry in $archive.Entries) {
                if ($entry.FullName.StartsWith('/') -or $entry.FullName.Contains('\') -or
                    ($entry.FullName -split '/') -contains '..') {
                    throw 'アーカイブに不正なパスが含まれます。'
                }
            }
        } finally {
            $archive.Dispose()
        }
        Expand-Archive -Path $zip -DestinationPath $extract
        $roots = @(Get-ChildItem -Path $extract -Directory)
        if ($roots.Count -ne 1) { throw 'GitHub アーカイブの構成が想定と異なります。' }
        $repoRoot = $roots[0].FullName
    }

    $stagedCode = Join-Path $work 'source'
    New-Item -ItemType Directory -Path $stagedCode | Out-Null
    foreach ($required in @('approval_agent', 'pyproject.toml', 'README.md')) {
        $item = Join-Path $repoRoot $required
        if (-not (Test-Path $item)) { throw "更新元に $required がありません。" }
        Copy-Item -Path $item -Destination $stagedCode -Recurse -Force
    }
    foreach ($optional in @('scripts', 'docs', 'LICENSE')) {
        $item = Join-Path $repoRoot $optional
        if (Test-Path $item) { Copy-Item -Path $item -Destination $stagedCode -Recurse -Force }
    }

    # Build both wheels while the existing Service is running. No unreviewed
    # source from a user-writable location is executed by the SYSTEM Service.
    $newWheels = Join-Path $work 'new-wheels'
    $oldWheels = Join-Path $work 'rollback-wheels'
    New-Item -ItemType Directory -Path $newWheels, $oldWheels | Out-Null
    Invoke-Python -Arguments @('-m', 'compileall', '-q', (Join-Path $stagedCode 'approval_agent'))
    Invoke-Python -Arguments @('-m', 'pip', 'wheel', '--disable-pip-version-check', '--wheel-dir', $newWheels, $stagedCode)
    Invoke-Python -Arguments @('-m', 'pip', 'wheel', '--disable-pip-version-check', '--no-deps', '--wheel-dir', $oldWheels, $code)
    $newWheel = @(Get-ChildItem $newWheels -Filter 'uac_approval_discord-*.whl') | Select-Object -First 1
    $oldWheel = @(Get-ChildItem $oldWheels -Filter 'uac_approval_discord-*.whl') | Select-Object -First 1
    if (-not $newWheel -or -not $oldWheel) { throw '更新用または復旧用の wheel を作成できませんでした。' }

    # Graceful Service stop revokes any active temporary password.
    $stopped = $true
    Set-ServiceState 'Stopped'
    Invoke-Python -Arguments @('-m', 'pip', 'install', '--no-user', '--no-index', '--find-links', $newWheels,
                               '--upgrade', $newWheel.FullName)
    # Same project version can contain new code; force replacement after deps.
    Invoke-Python -Arguments @('-m', 'pip', 'install', '--no-user', '--no-deps', '--force-reinstall', $newWheel.FullName)

    Move-Item -Path $code -Destination $backup
    $swapped = $true
    Move-Item -Path $stagedCode -Destination $code
    Set-ServiceState 'Running'
    Start-Sleep -Seconds 3
    if ((Get-Service -Name $serviceName).Status -ne 'Running') {
        throw '更新後の Service が停止しました。'
    }
    $record = @{ commit = $target; updated_at = (Get-Date).ToUniversalTime().ToString('o') } | ConvertTo-Json -Compress
    [IO.File]::WriteAllText($marker, $record, [Text.UTF8Encoding]::new($false))
    $updated = $true
    Write-Host "更新完了: $target"
    Write-Host 'Tray の新コードは、親ユーザーが再ログオンした後に反映されます。'
    Write-Host "以前のソース: $backup"
} catch {
    $failure = $_
    if ($stopped -and -not $updated) {
        try {
            Set-ServiceState 'Stopped'
            if ($swapped) {
                if (Test-Path $code) { Remove-Item -Path $code -Recurse -Force }
                Move-Item -Path $backup -Destination $code
            }
            if ($oldWheel) {
                Invoke-Python -Arguments @('-m', 'pip', 'install', '--no-user', '--no-deps', '--force-reinstall', $oldWheel.FullName)
            }
            if ($null -eq $previousMarker) {
                Remove-Item -Path $marker -ErrorAction SilentlyContinue
            } else {
                [IO.File]::WriteAllText($marker, $previousMarker, [Text.UTF8Encoding]::new($false))
            }
            Set-ServiceState 'Running'
            Write-Warning '以前のコードを復旧し、Service を再起動しました。'
        } catch {
            Write-Warning "自動復旧にも失敗しました。バックアップ: $backup。エラー: $_"
        }
    }
    throw $failure
} finally {
    Remove-Item -Path $work -Recurse -Force -ErrorAction SilentlyContinue
}
