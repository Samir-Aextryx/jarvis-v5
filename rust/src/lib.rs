//! Jarvis v5 backend. Compiled to WebAssembly and run inside stock Electron,
//! so Jarvis has no executable of its own (Smart App Control stays on).

pub mod auth;
pub mod config;
pub mod desktop;
pub mod host;
pub mod http;
pub mod routes;
pub mod server;
pub mod stt;
pub mod util;
pub mod vault;
pub mod voice;
pub mod winapi;
pub mod ws;

use serde_json::Value;
use wasm_bindgen::prelude::*;

pub const VERSION: &str = "5.0.0";

thread_local! {
    static STARTED: std::cell::Cell<f64> = const { std::cell::Cell::new(0.0) };
}

/// Seconds since the backend started.
pub fn uptime() -> f64 {
    host::now_secs() - STARTED.with(|s| s.get())
}

/// Starts the backend and resolves to the local auth token for the window.
#[wasm_bindgen]
pub async fn start(options_json: String) -> Result<String, JsValue> {
    let options: Value = serde_json::from_str(&options_json).unwrap_or(Value::Null);
    STARTED.with(|s| s.set(host::now_secs()));
    config::init(&options);
    host::set_child_env_blocklist(&vault::SECURE_KEY_NAMES);
    host::ps_set_script(&winapi::script());
    vault::load().await;
    vault::migrate_plaintext_secrets().await;
    let token = auth::load_token().await.map_err(|e| JsValue::from_str(&e))?;
    let port = options["port"].as_u64().map(|p| p as u16).unwrap_or_else(config::port);
    config::set("JARVIS_PORT", &port.to_string());
    server::serve("127.0.0.1", port).await.map_err(|e| JsValue::from_str(&format!("Port {port}: {e}")))?;
    info!("JARVIS server starting on 127.0.0.1:{port}");
    Ok(token)
}
