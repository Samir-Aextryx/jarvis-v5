//! Jarvis v5 backend. Compiled to WebAssembly and run inside stock Electron,
//! so Jarvis has no executable of its own (Smart App Control stays on).

pub mod agent_router;
pub mod apps;
pub mod atlassian;
pub mod auth;
pub mod autonomous;
pub mod brain;
pub mod calendar;
pub mod config;
pub mod desktop;
pub mod desktop_agent;
pub mod email;
pub mod google;
pub mod host;
pub mod http;
pub mod intents;
pub mod llm;
pub mod local_ai;
pub mod local_pc;
pub mod memory;
pub mod notes;
pub mod outlook;
pub mod pc_control;
pub mod personal;
pub mod privacy;
pub mod routes;
pub mod server;
pub mod settings;
pub mod speech;
pub mod stt;
pub mod tasks;
pub mod timezone;
pub mod uia;
pub mod urgent_mail;
#[cfg(test)]
mod regression_tests;
pub mod util;
pub mod vault;
pub mod voice;
pub mod websites;
pub mod whatsapp;
pub mod winapi;
pub mod work;
pub mod ws;

use serde_json::Value;
use wasm_bindgen::prelude::*;

pub const VERSION: &str = "5.2.0";

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
    google::init().await;
    vault::migrate_plaintext_secrets().await;
    settings::startup().await;
    personal::init();
    let token = auth::load_token().await.map_err(|e| JsValue::from_str(&e))?;
    let port = options["port"].as_u64().map(|p| p as u16).unwrap_or_else(config::port);
    config::set("JARVIS_PORT", &port.to_string());
    server::serve("127.0.0.1", port).await.map_err(|e| JsValue::from_str(&format!("Port {port}: {e}")))?;
    info!("JARVIS server starting on 127.0.0.1:{port}");
    apps::warm();
    brain::warm_projects();
    brain::refresh_context();
    urgent_mail::start();
    wasm_bindgen_futures::spawn_local(async {
        brain::openai_key_rejected().await;
    });
    Ok(token)
}
