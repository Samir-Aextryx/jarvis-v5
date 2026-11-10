# Build toolchain for the Rust backend. It runs in a Linux container, so no
# native Windows executable is ever built: the output is WebAssembly that
# stock Electron runs. Versions are pinned for reproducible builds.
FROM rust:1.99.1-slim
RUN rustup target add wasm32-unknown-unknown \
 && cargo install wasm-bindgen-cli --version 0.2.130 --locked \
 && rm -rf /usr/local/cargo/registry
WORKDIR /src/rust
