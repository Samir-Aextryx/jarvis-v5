# Sets Jarvis up from source: Python venv, frontend build, stock Electron and a
# desktop shortcut. Nothing is compiled into an own .exe, so Smart App Control
# can stay on. Running it again updates dependencies and repairs the shortcut.
param([switch]$NoShortcut)
$ErrorActionPreference = 'Stop'
$jarvisRepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $jarvisRepoRoot
try {
    $jarvisPython = Join-Path $jarvisRepoRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $jarvisPython)) {
        if (Get-Command py -ErrorAction SilentlyContinue) { & py -3.12 -m venv .venv } else { & python -m venv .venv }
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 fehlt. Bitte von python.org installieren und das Skript erneut starten.' }
    }
    & $jarvisPython -m pip install --disable-pip-version-check --quiet -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python-Abhängigkeiten konnten nicht installiert werden.' }

    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw 'Node.js 22 oder neuer fehlt. Bitte von nodejs.org installieren.' }
    & npm ci --prefix frontend --no-fund --no-audit
    if ($LASTEXITCODE -ne 0) { throw 'Frontend-Abhängigkeiten konnten nicht installiert werden.' }
    & npm run build --prefix frontend
    if ($LASTEXITCODE -ne 0) { throw 'Frontend-Build fehlgeschlagen.' }
    & npm ci --prefix desktop --no-fund --no-audit
    if ($LASTEXITCODE -ne 0) { throw 'Electron konnte nicht installiert werden.' }
    # Electron 43 fetches its checksum-verified binary on demand; do it now, not on first start.
    & node (Join-Path $jarvisRepoRoot 'desktop\node_modules\electron\install.js')
    if ($LASTEXITCODE -ne 0) { throw 'Electron-Programmdateien konnten nicht geladen werden.' }
    $jarvisElectron = Join-Path $jarvisRepoRoot 'desktop\node_modules\electron\dist\electron.exe'
    if (-not (Test-Path -LiteralPath $jarvisElectron)) { throw 'electron.exe fehlt nach der Installation.' }

    if (-not $NoShortcut) {
        $jarvisShortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Jarvis v5.lnk'
        $jarvisShortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($jarvisShortcutPath)
        $jarvisShortcut.TargetPath = $jarvisElectron
        $jarvisShortcut.Arguments = '"' + (Join-Path $jarvisRepoRoot 'desktop') + '"'
        $jarvisShortcut.WorkingDirectory = $jarvisRepoRoot
        $jarvisShortcut.IconLocation = Join-Path $jarvisRepoRoot 'desktop\icon.ico'
        $jarvisShortcut.Description = 'Jarvis v5 aus dem Quellcode'
        $jarvisShortcut.Save()
        Write-Output "Desktop-Verknüpfung: $jarvisShortcutPath"
    }
    Write-Output 'Jarvis ist eingerichtet. Start über die Desktop-Verknüpfung; API-Schlüssel in Settings eintragen.'
} finally { Pop-Location }
