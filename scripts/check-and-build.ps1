$ErrorActionPreference = 'Stop'
$jarvisRepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $jarvisRepoRoot
try {
    & '.\.venv\Scripts\python.exe' -X utf8 -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Python regression checks failed.' }
    & node frontend/node_modules/typescript/bin/tsc -p frontend/tsconfig.json
    if ($LASTEXITCODE -ne 0) { throw 'TypeScript checks failed.' }
    & node --check desktop/main.cjs
    if ($LASTEXITCODE -ne 0) { throw 'Electron main process syntax check failed.' }
    foreach ($jarvisNodeTest in (Get-ChildItem -LiteralPath 'tests' -Filter '*.cjs')) {
        & node $jarvisNodeTest.FullName
        if ($LASTEXITCODE -ne 0) { throw "Frontend check failed: $($jarvisNodeTest.Name)" }
    }
    & node frontend/node_modules/vite/bin/vite.js build frontend
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    & '.\.venv\Scripts\python.exe' -X utf8 'scripts\verify-source.py'
    if ($LASTEXITCODE -ne 0) { throw 'Backend smoke check failed.' }
} finally { Pop-Location }
