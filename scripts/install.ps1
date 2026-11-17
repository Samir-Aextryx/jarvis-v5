# Sets Jarvis up from source: frontend build, stock Electron and a desktop
# shortcut. The backend is Rust compiled to WebAssembly and committed in
# desktop\backend, so no Python, Rust or own .exe is needed and Smart App
# Control can stay on. Running it again updates dependencies and repairs the shortcut.
param([switch]$NoShortcut)
$ErrorActionPreference = 'Stop'
$jarvisRepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $jarvisRepoRoot
try {
    if (-not (Test-Path -LiteralPath (Join-Path $jarvisRepoRoot 'desktop\backend\jarvis_bg.wasm'))) { throw 'Das Backend (desktop\backend) fehlt im Checkout.' }
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
