# Builds the download package for a GitHub release: the committed source of
# HEAD plus the built frontend, so users need neither Git nor Node.js. The
# package contains no executable; "Install Jarvis.cmd" fetches stock Electron.
#
# Layout: only "Install Jarvis.cmd", README.md and LICENSE sit at the top of
# the folder; the app and its source code are in "app".
param([string]$OutDir)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $OutDir) { $OutDir = Join-Path $root 'release' }
$top = @('Install Jarvis.cmd', 'README.md', 'LICENSE')
Push-Location $root
try {
    if (git status --porcelain) { throw 'There are uncommitted changes. Commit first so the package matches a commit.' }
    $version = (Get-Content -LiteralPath 'desktop\package.json' -Raw | ConvertFrom-Json).version
    & npm run build --prefix frontend
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    # Marks the frontend as prebuilt, so install.ps1 skips Node.js.
    Set-Content -LiteralPath 'frontend\dist\.prebuilt' -Value $version -Encoding ascii

    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    $zip = Join-Path $OutDir "Jarvis-v$version-windows.zip"
    if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
    $exclude = $top | ForEach-Object { ":(exclude)$_" }
    & git archive --format=zip --prefix=Jarvis-v5/app/ -o $zip HEAD -- . @exclude
    if ($LASTEXITCODE -ne 0) { throw 'git archive failed.' }

    Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::Open($zip, [IO.Compression.ZipArchiveMode]::Update)
    try {
        foreach ($file in Get-ChildItem -LiteralPath 'frontend\dist' -Recurse -File -Force) {
            $entry = 'Jarvis-v5/app/' + $file.FullName.Substring($root.Length + 1).Replace('\', '/')
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $file.FullName, $entry, [IO.Compression.CompressionLevel]::Optimal) | Out-Null
        }
        foreach ($name in $top) {
            $text = [IO.File]::ReadAllText((Join-Path $root $name))
            # Links in the README point into the source tree, which is in "app" here.
            if ($name -eq 'README.md') { $text = [regex]::Replace($text, '\]\((?!https?:|#|app/)([^)]+)\)', '](app/$1)') }
            if ($name -like '*.cmd') { $text = $text -replace "(?<!`r)`n", "`r`n" }
            $entry = $archive.CreateEntry("Jarvis-v5/$name", [IO.Compression.CompressionLevel]::Optimal)
            $stream = $entry.Open()
            try { $bytes = (New-Object Text.UTF8Encoding($false)).GetBytes($text); $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
        }
    } finally { $archive.Dispose() }

    $hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Output "Package: $zip"
    Write-Output "SHA-256: $hash"
} finally { Pop-Location }
