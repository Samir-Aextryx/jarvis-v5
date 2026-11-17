# Full local check: Rust unit tests and a reproducible WebAssembly build
# (Docker), TypeScript, frontend tests and build, then a backend smoke test.
$ErrorActionPreference = 'Stop'
$jarvisRepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $jarvisRepoRoot
try {
    & (Join-Path $jarvisRepoRoot 'rust\build.ps1') -Test -Check
    & node frontend/node_modules/typescript/bin/tsc -p frontend/tsconfig.json
    if ($LASTEXITCODE -ne 0) { throw 'TypeScript checks failed.' }
    & node --check desktop/main.cjs
    if ($LASTEXITCODE -ne 0) { throw 'Electron main process syntax check failed.' }
    & node --check desktop/host.cjs
    if ($LASTEXITCODE -ne 0) { throw 'Backend host syntax check failed.' }
    foreach ($jarvisNodeTest in (Get-ChildItem -LiteralPath 'tests' -Filter '*.cjs')) {
        & node $jarvisNodeTest.FullName
        if ($LASTEXITCODE -ne 0) { throw "Frontend check failed: $($jarvisNodeTest.Name)" }
    }
    & node frontend/node_modules/vite/bin/vite.js build frontend
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    & node scripts/verify-source.cjs
    if ($LASTEXITCODE -ne 0) { throw 'Backend smoke check failed.' }
} finally { Pop-Location }
