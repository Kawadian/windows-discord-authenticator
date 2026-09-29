#Requires -RunAsAdministrator
param([Parameter(Mandatory)][ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })][string] $InstallerPath)
$ErrorActionPreference = 'Stop'
$installer = (Resolve-Path -LiteralPath $InstallerPath).Path
if ([IO.Path]::GetExtension($installer) -ine '.exe') { throw 'EXE インストーラーを指定してください。' }
$process = Start-Process -FilePath $installer -Wait -PassThru
if ($process.ExitCode -notin @(0, 3010)) { throw "更新に失敗しました: $($process.ExitCode)" }
