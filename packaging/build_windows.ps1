# Builds dist\SC-Toolkit-windows.exe (run from anywhere; needs pyinstaller).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
pyinstaller --noconfirm --clean --distpath dist --workpath build\work packaging\sc-toolkit.spec
if (-not (Test-Path dist\SC-Toolkit-windows.exe)) { throw "Build did not produce dist\SC-Toolkit-windows.exe" }
Write-Host "Built dist\SC-Toolkit-windows.exe"
