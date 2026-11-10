//! Paths and configuration values. Process environment first, then the
//! user's `.env` in the data folder (it never overrides the environment).

use crate::host::fs;
use serde_json::Value;
use std::cell::RefCell;
use std::collections::HashMap;

#[derive(Clone, Default)]
pub struct Paths {
    /// `Documents\Jarvis v5\config` unless `JARVIS_DATA_DIR` says otherwise.
    pub data: String,
    /// Repository root (source checkout).
    pub resources: String,
    pub home: String,
    pub desktop: String,
    pub documents: String,
    pub app_data: String,
    pub local_app_data: String,
    pub temp: String,
}

impl Paths {
    pub fn data_file(&self, name: &str) -> String {
        fs::join(&self.data, name)
    }
    pub fn frontend_dist(&self) -> String {
        fs::join(&self.resources, "frontend\\dist")
    }
}

thread_local! {
    static PATHS: RefCell<Paths> = RefCell::new(Paths::default());
    static ENV: RefCell<HashMap<String, String>> = RefCell::new(HashMap::new());
}

pub fn paths() -> Paths {
    PATHS.with(|p| p.borrow().clone())
}

fn normalize(path: &str) -> String {
    let path = path.replace('/', "\\");
    let trimmed = path.trim_end_matches('\\');
    if trimmed.ends_with(':') { format!("{trimmed}\\") } else { trimmed.to_string() }
}

pub fn init(options: &Value) {
    let host: Value = serde_json::from_str(&crate::host::paths_json()).unwrap_or(Value::Null);
    let env: HashMap<String, String> = serde_json::from_str(&crate::host::env_json()).unwrap_or_default();
    ENV.with(|e| {
        let mut e = e.borrow_mut();
        for (k, v) in env {
            e.insert(k.to_ascii_uppercase(), v);
        }
    });
    let pick = |key: &str| normalize(options[key].as_str().or(host[key].as_str()).unwrap_or_default());
    let mut paths = Paths {
        data: pick("data"),
        resources: pick("resources"),
        home: pick("home"),
        desktop: pick("desktop"),
        documents: pick("documents"),
        app_data: pick("appData"),
        local_app_data: pick("localAppData"),
        temp: pick("temp"),
    };
    if let Some(dir) = get("JARVIS_DATA_DIR").filter(|d| !d.trim().is_empty()) {
        paths.data = normalize(&dir);
    }
    if paths.desktop.is_empty() {
        paths.desktop = fs::join(&paths.home, "Desktop");
    }
    let _ = fs::mkdirp(&fs::join(&paths.data, "data"));
    let env_path = fs::join(&paths.data, ".env");
    PATHS.with(|p| *p.borrow_mut() = paths);
    if let Some(text) = fs::read_text(&env_path) {
        for (key, value) in parse_env(&text) {
            if get(&key).is_none() {
                set(&key, &value);
            }
        }
    }
}

pub fn parse_env(text: &str) -> Vec<(String, String)> {
    text.lines()
        .filter_map(|line| {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                return None;
            }
            let (k, v) = line.split_once('=')?;
            Some((k.trim().to_string(), v.trim().trim_matches('"').trim_matches('\'').to_string()))
        })
        .collect()
}

pub fn get(name: &str) -> Option<String> {
    ENV.with(|e| e.borrow().get(&name.to_ascii_uppercase()).cloned())
}
pub fn get_or(name: &str, default: &str) -> String {
    get(name).unwrap_or_else(|| default.to_string())
}
pub fn set(name: &str, value: &str) {
    ENV.with(|e| e.borrow_mut().insert(name.to_ascii_uppercase(), value.to_string()));
}
pub fn unset(name: &str) {
    ENV.with(|e| e.borrow_mut().remove(&name.to_ascii_uppercase()));
}

pub fn port() -> u16 {
    get("JARVIS_PORT").and_then(|p| p.trim().parse().ok()).unwrap_or(8340)
}
pub fn user_name() -> String {
    get_or("USER_NAME", "sir")
}
