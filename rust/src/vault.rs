//! API keys in Windows Credential Manager, stored exactly like the previous
//! Python backend (python-keyring's WinVaultKeyring), so existing keys keep
//! working: target `<service>` or `<name>@<service>`, UTF-16LE blob.

use crate::config;
use crate::host::{self, Res};
use crate::util::sha256_hex;
use serde_json::{Value, json};
use std::cell::RefCell;
use std::collections::HashMap;

pub const SECURE_KEY_NAMES: [&str; 7] =
    ["OPENAI_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY", "OLLAMA_API_KEY", "FISH_API_KEY", "JARVIS_AUTH_TOKEN", "CLIENT_SECRET"];

thread_local! {
    static CACHE: RefCell<HashMap<String, String>> = RefCell::new(HashMap::new());
    static AVAILABLE: RefCell<bool> = const { RefCell::new(false) };
}

pub fn service_name() -> String {
    let data = config::paths().data;
    format!("Jarvis-v5-Keys-{}", &sha256_hex(data.as_bytes())[..16])
}

pub fn google_service_name() -> String {
    let data = config::paths().data;
    format!("Jarvis-v5-Google-{}", &sha256_hex(data.as_bytes())[..16])
}

struct Credential {
    user: String,
    secret: String,
}

async fn read_target(target: &str) -> Res<Option<Credential>> {
    let v = host::ps("cred.read", json!({ "target": target })).await?;
    if v.is_null() {
        return Ok(None);
    }
    Ok(Some(Credential {
        user: v["user"].as_str().unwrap_or_default().to_string(),
        secret: v["secret"].as_str().unwrap_or_default().to_string(),
    }))
}

async fn write_target(target: &str, user: &str, secret: &str) -> Res<()> {
    host::ps("cred.write", json!({ "target": target, "user": user, "secret": secret })).await.map(|_| ())
}

/// keyring.get_password(service, username)
pub async fn get_password(service: &str, username: &str) -> Res<Option<String>> {
    if let Some(c) = read_target(service).await?
        && c.user == username
    {
        return Ok(Some(c.secret));
    }
    Ok(read_target(&format!("{username}@{service}")).await?.map(|c| c.secret))
}

/// keyring.set_password(service, username, password)
pub async fn set_password(service: &str, username: &str, password: &str) -> Res<()> {
    if let Some(existing) = read_target(service).await? {
        write_target(&format!("{}@{service}", existing.user), &existing.user, &existing.secret).await?;
    }
    write_target(service, username, password).await
}

/// keyring.delete_password(service, username)
pub async fn delete_password(service: &str, username: &str) -> Res<()> {
    let mut deleted = false;
    for target in [service.to_string(), format!("{username}@{service}")] {
        if let Some(c) = read_target(&target).await?
            && c.user == username
        {
            host::ps("cred.delete", json!({ "target": target })).await?;
            deleted = true;
        }
    }
    if deleted { Ok(()) } else { Err("credential not found".into()) }
}

pub fn available() -> bool {
    AVAILABLE.with(|a| *a.borrow())
}

/// Loads every secure key once at startup; later reads come from memory.
pub async fn load() {
    let service = service_name();
    let mut ok = true;
    for name in SECURE_KEY_NAMES.iter() {
        match get_password(&service, name).await {
            Ok(Some(value)) if !value.trim().is_empty() => {
                CACHE.with(|c| c.borrow_mut().insert(name.to_string(), value.trim().to_string()));
            }
            Ok(_) => {}
            Err(e) => {
                ok = false;
                crate::warn!("Windows Vault unavailable: {e}");
                break;
            }
        }
    }
    AVAILABLE.with(|a| *a.borrow_mut() = ok);
}

/// Secure key from the vault, falling back to the environment.
pub fn get(name: &str) -> String {
    CACHE
        .with(|c| c.borrow().get(name).cloned())
        .unwrap_or_else(|| config::get(name).unwrap_or_default().trim().to_string())
}

/// Saves (or with an empty value deletes) a secure key.
pub async fn set(name: &str, value: &str, require_persistence: bool) -> Res<()> {
    if require_persistence && !available() {
        return Err("Windows Credential Manager is unavailable; the API key was not saved.".into());
    }
    let service = service_name();
    let mut stored = false;
    if available() {
        let result: Res<()> = async {
            if value.is_empty() {
                if delete_password(&service, name).await.is_err() && get_password(&service, name).await?.is_some() {
                    return Err("delete failed".into());
                }
            } else {
                set_password(&service, name, value).await?;
            }
            if require_persistence && get_password(&service, name).await?.unwrap_or_default() != value {
                return Err("Credential persistence could not be verified.".into());
            }
            Ok(())
        }
        .await;
        match result {
            Ok(()) => stored = true,
            Err(e) => {
                if require_persistence {
                    return Err("Windows Credential Manager could not save the API key.".into());
                }
                crate::warn!("Vault write failed for {name}: {e}");
            }
        }
    }
    if stored {
        config::unset(name);
        CACHE.with(|c| {
            let mut c = c.borrow_mut();
            if value.is_empty() { c.remove(name) } else { c.insert(name.to_string(), value.to_string()) }
        });
    } else {
        config::set(name, value);
    }
    Ok(())
}

/// Moves plaintext secrets from `.env` into the vault and strips them.
pub async fn migrate_plaintext_secrets() {
    let path = config::paths().data_file(".env");
    let Some(content) = host::fs::read_text(&path) else { return };
    if !available() {
        return;
    }
    let service = service_name();
    let mut migrated = false;
    let mut lines = Vec::new();
    for line in content.lines() {
        let stripped = line.trim();
        if !stripped.is_empty() && !stripped.starts_with('#')
            && let Some((k, v)) = stripped.split_once('=')
        {
            let key = k.trim();
            let val = v.trim().trim_matches('"').trim_matches('\'');
            if SECURE_KEY_NAMES.contains(&key) && !val.is_empty() {
                let existing = get_password(&service, key).await;
                let saved = match existing {
                    Ok(Some(_)) => true,
                    Ok(None) => set_password(&service, key, val).await.is_ok(),
                    Err(_) => false,
                };
                if !saved {
                    crate::warn!("Credential migration failed for {key}; original retained");
                    lines.push(line.to_string());
                    continue;
                }
                crate::info!("Migrated {key} from .env to Windows Credential Manager");
                config::unset(key);
                if CACHE.with(|c| !c.borrow().contains_key(key)) {
                    CACHE.with(|c| c.borrow_mut().insert(key.to_string(), val.to_string()));
                }
                migrated = true;
                lines.push(format!("# {key} is securely stored in Windows Credential Manager"));
                continue;
            }
        }
        lines.push(line.to_string());
    }
    if migrated {
        let _ = host::fs::write_text(&path, &(lines.join("\n") + "\n"));
    }
}

/// Generic JSON secret under its own service (Google OAuth client and tokens).
pub async fn get_json(service: &str, username: &str) -> Option<Value> {
    let raw = get_password(service, username).await.ok().flatten()?;
    serde_json::from_str(&raw).ok()
}
