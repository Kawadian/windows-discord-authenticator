$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
python -m pip install . 'pyinstaller==6.20.0'
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
python -m PyInstaller --noconfirm --clean --onedir --windowed --name UacApproval --paths . --collect-all dxcam --hidden-import pystray._win32 packaging/desktop_entry.py
if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed' }
python -m PyInstaller --noconfirm --clean --onedir --name UacApprovalService --paths . --hidden-import win32timezone packaging/service_entry.py
if ($LASTEXITCODE -ne 0) { throw 'Service build failed' }
$desktop = Start-Process -FilePath dist/UacApproval/UacApproval.exe -ArgumentList '--smoke-test' -Wait -PassThru
if ($desktop.ExitCode -ne 0) { throw 'Frozen desktop smoke test failed' }
& ./dist/UacApprovalService/UacApprovalService.exe --smoke-test
if ($LASTEXITCODE -ne 0) { throw 'Frozen service smoke test failed' }
$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { throw 'Inno Setup 6 is required' }
& $iscc packaging/installer.iss
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed' }
Get-ChildItem dist/installer/*.exe | Get-FileHash -Algorithm SHA256 | ForEach-Object {
    "$($_.Hash.ToLower())  $([IO.Path]::GetFileName($_.Path))" | Set-Content -Encoding ascii "$($_.Path).sha256"
}
