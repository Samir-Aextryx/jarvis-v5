# Stops the Jarvis desktop app started from this checkout (stock electron.exe
# with this repository's desktop folder). Other Electron apps are never touched.
$ErrorActionPreference = 'Stop'
$jarvisRepoRoot = Split-Path -Parent $PSScriptRoot
$jarvisElectron = Join-Path $jarvisRepoRoot 'desktop\node_modules\electron\dist\electron.exe'
$jarvisProcesses = @(Get-CimInstance Win32_Process -Filter "Name = 'electron.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -eq $jarvisElectron })
if (-not $jarvisProcesses) {
    Write-Host 'Jarvis läuft nicht.'
    exit 0
}
$jarvisProcesses | ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
Write-Host 'Jarvis wurde beendet.'
