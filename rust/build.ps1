# Builds rust/ to desktop/backend/ (WebAssembly + JS glue) inside Docker.
# Needs Docker Desktop. Users who only run Jarvis never need this: the built
# backend is committed, and CI checks that it matches the source.
param([switch]$Check)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
docker build -q -t jarvis-rust-build "$PSScriptRoot" | Out-Null
if ($LASTEXITCODE) { throw 'Docker image build failed.' }
$out = if ($Check) { '/tmp/backend-check' } else { '/src/desktop/backend' }
$script = "cargo build --release --locked --target wasm32-unknown-unknown && " +
  "wasm-bindgen --target nodejs --no-typescript --out-dir $out target/wasm32-unknown-unknown/release/jarvis.wasm"
if ($Check) { $script += " && cmp $out/jarvis_bg.wasm /src/desktop/backend/jarvis_bg.wasm && cmp $out/jarvis.js /src/desktop/backend/jarvis.js" }
docker run --rm -v "${repo}:/src" -v jarvis-cargo-registry:/usr/local/cargo/registry `
  -v jarvis-cargo-target:/src/rust/target jarvis-rust-build sh -c $script
if ($LASTEXITCODE) { throw 'Rust build failed.' }
