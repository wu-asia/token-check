param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# PySide6/Qt 6.11 has unreliable DLL loading from a PyInstaller one-file
# temporary extraction directory on this Windows environment. Build an onedir
# application so Qt's DLLs remain adjacent to the executable.
& $Python -m PyInstaller --noconfirm --clean --onedir --windowed --name CodexUsageMonitor `
    --collect-all PySide6 `
    --paths $root `
    app.py

if (-not (Test-Path "$root\dist\CodexUsageMonitor\CodexUsageMonitor.exe")) {
    throw "Build did not produce dist\CodexUsageMonitor\CodexUsageMonitor.exe"
}

# A portable archive prevents accidental distribution of only the EXE, which
# would omit the adjacent Qt runtime required by the desktop application.
Compress-Archive -Path "$root\dist\CodexUsageMonitor" `
    -DestinationPath "$root\dist\CodexUsageMonitor-portable.zip" -Force
