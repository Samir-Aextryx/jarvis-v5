# Sets Jarvis up: frontend, stock Electron and a desktop shortcut. The backend
# is Rust compiled to WebAssembly and committed in desktop\backend, so no
# Python, Rust or own .exe is needed and Smart App Control can stay on.
#
# A source checkout builds the frontend with Node.js and installs Electron with
# npm. The download package (GitHub release) already contains the built
# frontend; it needs no Node.js and fetches the official Electron build, checked
# against a pinned SHA-256. Running it again updates Electron and repairs the shortcut.
param([switch]$NoShortcut)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$jarvisRepoRoot = Split-Path -Parent $PSScriptRoot
$electronVersion = '43.3.0'
# From electron@43.3.0 checksums.json; a download that does not match is discarded.
$electronHashes = @{
    'x64'   = '18528bedc6a9b04bdc5efb7b803cbc3cb0e5ea6415d54046e23d464d89a00da9'
    'arm64' = 'b315ea6feef1ee8bedc01c28ae2f89c0631f4521f888dcbecb9bdb28281c37e7'
}

function Install-Electron([string]$Destination) {
    $versionFile = Join-Path $Destination 'version'
    if ((Test-Path -LiteralPath (Join-Path $Destination 'electron.exe')) -and
        (Test-Path -LiteralPath $versionFile) -and
        ((Get-Content -LiteralPath $versionFile -Raw).Trim() -eq $electronVersion)) { return }
    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'x64' }
    $name = "electron-v$electronVersion-win32-$arch.zip"
    $zip = Join-Path ([IO.Path]::GetTempPath()) $name
    Write-Output "Lade Electron $electronVersion ($arch) ..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/electron/electron/releases/download/v$electronVersion/$name" -OutFile $zip
    try {
        if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $electronHashes[$arch]) {
            throw 'Die Electron-Datei hat eine falsche Prüfsumme und wurde verworfen.'
        }
        if (Test-Path -LiteralPath $Destination) { Remove-Item -LiteralPath $Destination -Recurse -Force }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::ExtractToDirectory($zip, $Destination)
    } finally { Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue }
}

Push-Location $jarvisRepoRoot
try {
    if (-not (Test-Path -LiteralPath (Join-Path $jarvisRepoRoot 'desktop\backend\jarvis_bg.wasm'))) { throw 'Das Backend (desktop\backend) fehlt.' }
    $jarvisElectronDir = Join-Path $jarvisRepoRoot 'desktop\node_modules\electron\dist'
    if (Test-Path -LiteralPath (Join-Path $jarvisRepoRoot 'frontend\dist\.prebuilt')) {
        # Download package: remove the browser's download mark from the extracted files.
        Get-ChildItem -LiteralPath $jarvisRepoRoot -Recurse -File | Unblock-File
        Install-Electron $jarvisElectronDir
    } else {
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
    }
    $jarvisElectron = Join-Path $jarvisElectronDir 'electron.exe'
    if (-not (Test-Path -LiteralPath $jarvisElectron)) { throw 'electron.exe fehlt nach der Installation.' }

    if (-not $NoShortcut) {
        $jarvisShortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Jarvis v5.lnk'
        $jarvisShortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($jarvisShortcutPath)
        $jarvisShortcut.TargetPath = $jarvisElectron
        $jarvisShortcut.Arguments = '"' + (Join-Path $jarvisRepoRoot 'desktop') + '"'
        $jarvisShortcut.WorkingDirectory = $jarvisRepoRoot
        $jarvisShortcut.IconLocation = Join-Path $jarvisRepoRoot 'desktop\icon.ico'
        $jarvisShortcut.Description = 'Jarvis v5'
        $jarvisShortcut.Save()
        Write-Output "Desktop-Verknüpfung: $jarvisShortcutPath"
    }
    Write-Output 'Jarvis ist eingerichtet. Start über die Desktop-Verknüpfung; API-Schlüssel in Settings eintragen.'
} finally { Pop-Location }
