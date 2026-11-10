$jarvisRepoRoot = Split-Path -Parent $PSScriptRoot
$ErrorActionPreference = 'Stop'
$jarvisPidPath = Join-Path $jarvisRepoRoot 'server.pid'
if (-not (Test-Path -LiteralPath $jarvisPidPath)) {
    Write-Host 'Jarvis läuft nicht (keine server.pid).'
    exit 0
}
$jarvisProcessId = [int](Get-Content -LiteralPath $jarvisPidPath)
$jarvisProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $jarvisProcessId" -ErrorAction SilentlyContinue
$jarvisPythonPath = Join-Path $jarvisRepoRoot '.venv\Scripts\python.exe'
# start-windows.py starts the backend as "python -m jarvis"; the desktop shell
# uses scripts/desktop-server.py. Older servers used "python -m jarvis.server".
$jarvisCommandPattern = '(?i)(-m\s+jarvis(\s|$)|jarvis\.server|server\.py)'
if (-not $jarvisProcess) {
    Remove-Item -LiteralPath $jarvisPidPath -ErrorAction SilentlyContinue
    Write-Host 'Jarvis läuft nicht mehr (veraltete server.pid entfernt).'
    exit 0
}
if ($jarvisProcess.ExecutablePath -ne $jarvisPythonPath -or $jarvisProcess.CommandLine -notmatch $jarvisCommandPattern) {
    # The PID was reused by an unrelated process; never kill it.
    Remove-Item -LiteralPath $jarvisPidPath -ErrorAction SilentlyContinue
    Write-Warning 'server.pid gehört nicht mehr zu Jarvis; Datei entfernt, kein Prozess beendet.'
    exit 0
}
Stop-Process -Id $jarvisProcessId -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $jarvisPidPath -ErrorAction SilentlyContinue
Write-Host 'Jarvis wurde beendet.'
