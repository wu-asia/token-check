param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

& $Python -m PyInstaller --noconfirm --clean --onefile --windowed --name CodexUsageMonitor `
    --collect-all PySide6 `
    --paths $root `
    app.py

if (-not (Test-Path "$root\dist\CodexUsageMonitor.exe")) {
    throw "Build did not produce dist\CodexUsageMonitor.exe"
}
