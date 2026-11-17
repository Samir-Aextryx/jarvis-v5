//! Low-cost, read-only urgent mail alerts; mail content is never an instruction.
//! Outlook is watched only while the user has it open; Jarvis never starts it.

use crate::host::{self, Res, fs};
use crate::{config, google, outlook, tasks, util, whatsapp};
use base64::Engine;
use base64::engine::general_purpose::STANDARD as B64;
use serde::Serialize;
use serde_json::{Value, json};
use std::cell::RefCell;
use std::collections::{BTreeMap, HashSet};

const CALL_EXPIRY: f64 = 30.0 * 60.0;
const CALL_RETRY: f64 = 5.0 * 60.0;
const OUTLOOK_POLL: f64 = 30.0;
const GMAIL_POLL: f64 = 90.0;
const OUTLOOK_FAILURE_RETRY: f64 = 120.0;
const MAX_SEEN: usize = 2000;
const MAX_RESOLVED: usize = 50;
const SOURCES: [&str; 2] = ["outlook", "gmail"];

#[derive(Clone, Serialize, PartialEq)]
struct Alert {
    #[serde(skip_serializing_if = "Option::is_none")]
    id: Option<String>,
    source: String,
    subject: String,
    sender: String,
    time: String,
    call_state: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    created_at: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    next_attempt: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    attempts: Option<i64>,
}

impl Alert {
    fn public(&self) -> Value {
        json!({ "source": self.source, "subject": self.subject, "sender": self.sender, "time": self.time, "call_state": self.call_state })
    }
    fn resolved(&self) -> bool {
        matches!(self.call_state.as_str(), "connected" | "uncertain" | "expired")
    }
    fn open(&self) -> bool {
        matches!(self.call_state.as_str(), "pending" | "blocked")
    }
}

#[derive(Default)]
struct State {
    seen: BTreeMap<String, Vec<String>>,
    alerts: Vec<Alert>,
    errors: BTreeMap<String, String>,
}

thread_local! {
    static STATE: RefCell<State> = RefCell::new(State::default());
}

fn with<R>(f: impl FnOnce(&mut State) -> R) -> R {
    STATE.with(|s| f(&mut s.borrow_mut()))
}

fn path() -> String {
    config::paths().data_file("data\\urgent-mail-state.dpapi")
}

fn fingerprint(source: &str, id: &str) -> String {
    util::sha256_hex(format!("{source}:{id}").as_bytes())
}

fn is_hash(text: &str) -> bool {
    text.len() == 64 && text.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

/// Only trusted mailbox flags and a small subject vocabulary trigger alerts.
pub fn is_urgent_header(row: &Value) -> bool {
    let urgent_subject = crate::re!(
        r"(?i)(?:\b(?:urgent|emergency|notfall|dringend|sofort|asap)\b|(?:action\s+required|handlungsbedarf|bitte\s+sofort))"
    );
    row["unread"] == true && (row["important"] == true || urgent_subject.is_match(row["subject"].as_str().unwrap_or("")))
}

fn cut(text: &str, max: usize) -> String {
    util::take(text, max)
}

fn row_id(row: &Value) -> Option<String> {
    match &row["id"] {
        Value::String(s) if !s.is_empty() => Some(s.clone()),
        Value::Number(n) => Some(n.to_string()),
        _ => None,
    }
}

/// Keeps every open call; bounds only historical, resolved alerts.
fn trim_alerts(alerts: &mut Vec<Alert>) {
    let resolved = alerts.iter().filter(|a| a.resolved()).count();
    if resolved > MAX_RESOLVED {
        let mut drop = resolved - MAX_RESOLVED;
        alerts.retain(|a| {
            if drop > 0 && a.resolved() {
                drop -= 1;
                false
            } else {
                true
            }
        });
    }
}

// ---- encrypted state ---------------------------------------------------------------

fn parse_state(data: &Value) -> Result<(BTreeMap<String, Vec<String>>, Vec<Alert>), String> {
    let version = data["version"].as_i64().unwrap_or(0);
    let Some(seen_in) = data["seen"].as_object().filter(|_| version == 1 || version == 2) else {
        return Err("Unsupported urgent mail state.".into());
    };
    let mut seen = BTreeMap::new();
    for (source, rows) in seen_in {
        if let (true, Some(rows)) = (SOURCES.contains(&source.as_str()), rows.as_array()) {
            let start = rows.len().saturating_sub(MAX_SEEN);
            let valid = rows[start..].iter().filter_map(Value::as_str).filter(|r| is_hash(r)).map(str::to_string).collect();
            seen.insert(source.clone(), valid);
        }
    }
    let mut alerts = Vec::new();
    for alert in data["alerts"].as_array().into_iter().flatten() {
        let source = alert["source"].as_str().unwrap_or("");
        let fields = ["subject", "sender", "time"].map(|k| alert[k].as_str());
        let [Some(subject), Some(sender), Some(time)] = fields else { continue };
        if !SOURCES.contains(&source) {
            continue;
        }
        let mut saved = Alert {
            id: None,
            source: source.to_string(),
            subject: cut(subject, 200),
            sender: cut(sender, 160),
            time: cut(time, 50),
            // A v1 alert predates the call outbox; do not place a late call.
            call_state: "expired".into(),
            created_at: None,
            next_attempt: None,
            attempts: None,
        };
        if version == 2 && let Some(id) = alert["id"].as_str().filter(|i| is_hash(i)) {
            let state = alert["call_state"].as_str().unwrap_or("expired");
            let state = if state == "dialing" { "uncertain" } else { state };
            saved.id = Some(id.to_string());
            saved.call_state =
                if ["pending", "blocked", "connected", "uncertain", "expired"].contains(&state) { state } else { "uncertain" }.to_string();
            saved.created_at = Some(alert["created_at"].as_f64().unwrap_or(0.0));
            saved.next_attempt = Some(alert["next_attempt"].as_f64().unwrap_or(0.0));
            saved.attempts = Some(alert["attempts"].as_i64().unwrap_or(0).clamp(0, 3));
        }
        alerts.push(saved);
    }
    trim_alerts(&mut alerts);
    Ok((seen, alerts))
}

async fn load() {
    let file = path();
    let Some(sealed) = fs::read(&file) else { return };
    let result: Res<_> = async {
        let plain = host::ps("dpapi.unprotect", json!({ "data": B64.encode(&sealed) })).await?;
        let bytes = B64.decode(plain.as_str().unwrap_or("")).map_err(|e| e.to_string())?;
        let data: Value = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
        parse_state(&data)
    }
    .await;
    match result {
        Ok((seen, alerts)) => with(|s| {
            s.seen = seen;
            s.alerts = alerts;
        }),
        Err(_) => {
            with(|s| s.errors.insert("storage".into(), "StateUnreadable".into()));
            host::log("warn", "Urgent mail state could not be loaded.");
        }
    }
}

async fn save() -> Res<()> {
    let state = with(|s| json!({ "version": 2, "seen": s.seen, "alerts": s.alerts }));
    let sealed = host::ps("dpapi.protect", json!({ "data": B64.encode(state.to_string()) })).await?;
    let sealed = B64.decode(sealed.as_str().unwrap_or("")).map_err(|e| e.to_string())?;
    let file = path();
    fs::mkdirp(fs::parent(&file))?;
    let temporary = format!("{}.tmp", file.trim_end_matches(".dpapi"));
    fs::write(&temporary, &sealed)?;
    fs::rename(&temporary, &file)
}

fn storage_ok() {
    with(|s| s.errors.remove("storage"));
}

fn storage_failed() {
    with(|s| s.errors.insert("storage".into(), "StateNotSaved".into()));
}

// ---- scanning ----------------------------------------------------------------------

async fn fetch(source: &str) -> Res<Vec<Value>> {
    if source == "outlook" { outlook::recent_unread_headers().await } else { google::recent_unread_headers(20).await }
}

async fn scan(source: &str) -> Res<()> {
    let rows = fetch(source).await?;
    let (prior_seen, prior_alerts) = with(|s| (s.seen.get(source).cloned(), s.alerts.clone()));
    let current: Vec<String> = rows.iter().filter_map(row_id).map(|id| fingerprint(source, &id)).collect();
    let mut merged = prior_seen.clone().unwrap_or_default();
    let mut known: HashSet<String> = merged.iter().cloned().collect();
    for f in current {
        if known.insert(f.clone()) {
            merged.push(f);
        }
    }
    let merged = merged.split_off(merged.len().saturating_sub(MAX_SEEN));
    let changed = prior_seen.as_ref() != Some(&merged);
    with(|s| {
        s.seen.insert(source.to_string(), merged);
        s.errors.remove(source);
    });
    let Some(previous) = prior_seen.clone() else {
        // The first scan is a baseline, never an old-mail alarm.
        match save().await {
            Ok(()) => storage_ok(),
            Err(_) => {
                with(|s| s.seen.remove(source));
                storage_failed();
            }
        }
        return Ok(());
    };
    let mut previous: HashSet<String> = previous.into_iter().collect();
    let mut notifications = Vec::new();
    with(|s| {
        for row in &rows {
            let Some(id) = row_id(row) else { continue };
            if !is_urgent_header(row) {
                continue;
            }
            let print = fingerprint(source, &id);
            if !previous.insert(print.clone()) {
                continue;
            }
            let now = host::now_secs();
            let alert = Alert {
                id: Some(print),
                source: source.to_string(),
                subject: cut(row["subject"].as_str().unwrap_or(""), 200),
                sender: cut(row["sender"].as_str().unwrap_or(""), 160),
                time: String::from(js_sys::Date::new_0().to_iso_string()),
                call_state: "pending".into(),
                created_at: Some(now),
                next_attempt: Some(now),
                attempts: Some(0),
            };
            notifications.push(alert.public());
            s.alerts.push(alert);
        }
        trim_alerts(&mut s.alerts);
    });
    if changed || !notifications.is_empty() {
        match save().await {
            Ok(()) => storage_ok(),
            Err(_) => {
                with(|s| {
                    s.seen.insert(source.to_string(), prior_seen.unwrap_or_default());
                    s.alerts = prior_alerts;
                });
                storage_failed();
                host::log("warn", "Urgent mail state could not be saved.");
                return Ok(());
            }
        }
    }
    for mut alert in notifications {
        alert["type"] = json!("urgent_mail");
        tasks::notify(&alert);
    }
    Ok(())
}

// ---- calls -------------------------------------------------------------------------

/// Persists a claim before dialing; never retries an uncertain call.
async fn process_calls() {
    let now = host::now_secs();
    let (candidate, expired) = with(|s| {
        if s.alerts.iter().any(|a| a.call_state == "dialing") {
            return (None, false);
        }
        let mut expired = false;
        for alert in s.alerts.iter_mut() {
            if alert.open() && now - alert.created_at.unwrap_or(0.0) > CALL_EXPIRY {
                alert.call_state = "expired".into();
                expired = true;
            }
        }
        let index = s.alerts.iter().rposition(|a| a.open() && a.next_attempt.unwrap_or(0.0) <= now);
        if let Some(i) = index {
            let alert = &mut s.alerts[i];
            alert.call_state = "dialing".into();
            alert.attempts = Some(alert.attempts.unwrap_or(0) + 1);
        }
        (index.map(|i| (i, s.alerts[i].clone())), expired)
    });
    let Some((index, selected)) = candidate else {
        if expired && save().await.is_err() {
            storage_failed();
        }
        return;
    };
    if save().await.is_err() {
        // A call without a durable claim could be duplicated.
        with(|s| s.alerts[index].call_state = "blocked".into());
        storage_failed();
        return;
    }
    let result = whatsapp::attempt_urgent_call(&serde_json::to_value(&selected).unwrap_or(Value::Null)).await;
    let status = with(|s| {
        // Only this loop mutates alerts while a call is out, so the index is stable.
        let alert = &mut s.alerts[index];
        if result["state"] == "connected" && result["spoken"] == true {
            alert.call_state = "connected".into();
        } else if result["state"] == "not_ready" {
            alert.call_state = "blocked".into();
            alert.next_attempt = Some(host::now_secs() + CALL_RETRY);
        } else {
            alert.call_state = "uncertain".into();
        }
        let status = alert.public();
        trim_alerts(&mut s.alerts);
        status
    });
    if save().await.is_err() {
        storage_failed();
        return;
    }
    storage_ok();
    let mut status = status;
    status["type"] = json!("urgent_call_status");
    tasks::notify(&status);
}

// ---- monitor -----------------------------------------------------------------------

fn error_of(source: &str) -> Option<String> {
    with(|s| s.errors.get(source).cloned())
}

async fn run() {
    load().await;
    let clock = || host::monotonic() / 1000.0;
    let (mut next_outlook, mut next_gmail) = (0.0, 0.0);
    loop {
        let mut providers = Vec::new();
        let now = clock();
        if now >= next_outlook {
            next_outlook = now + OUTLOOK_POLL;
            if outlook::is_running().await {
                providers.push("outlook");
            }
        }
        if now >= next_gmail {
            next_gmail = now + GMAIL_POLL;
            let status = google::status();
            let gmail = status["services"].as_array().is_some_and(|a| a.iter().any(|v| v == "gmail"));
            if status["connected"] == true && gmail {
                providers.push("gmail");
            }
        }
        for source in providers {
            let old = error_of(source);
            match scan(source).await {
                Ok(()) => {
                    if old.is_some() && error_of(source).is_none() {
                        tasks::notify(&json!({ "type": "urgent_mail_source_status", "source": source, "available": true }));
                    }
                }
                Err(_) => {
                    let error = "ReadFailed".to_string();
                    with(|s| s.errors.insert(source.to_string(), error.clone()));
                    if source == "outlook" {
                        next_outlook = clock() + OUTLOOK_FAILURE_RETRY;
                    }
                    host::log("warn", &format!("Urgent mail scan failed for {source}."));
                    if old.as_deref() != Some(error.as_str()) {
                        tasks::notify(&json!({ "type": "urgent_mail_source_status", "source": source, "available": false, "error": error }));
                    }
                }
            }
        }
        process_calls().await;
        host::sleep(OUTLOOK_POLL * 1000.0).await;
    }
}

/// Starts the background monitor once at startup.
pub fn start() {
    wasm_bindgen_futures::spawn_local(run());
}

pub fn status() -> Value {
    let encrypted = fs::exists(&path());
    with(|s| {
        json!({
            "alerts": s.alerts.iter().map(Alert::public).collect::<Vec<_>>(),
            "errors": s.errors,
            "sources_initialized": s.seen.keys().collect::<Vec<_>>(),
            "state_encrypted": encrypted && !s.errors.contains_key("storage"),
        })
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn urgent_needs_unread_and_flag_or_word() {
        assert!(is_urgent_header(&json!({"unread": true, "important": true, "subject": "hi"})));
        assert!(is_urgent_header(&json!({"unread": true, "subject": "Bitte sofort prüfen"})));
        assert!(is_urgent_header(&json!({"unread": true, "subject": "ACTION  required"})));
        assert!(!is_urgent_header(&json!({"unread": false, "important": true, "subject": "urgent"})));
        assert!(!is_urgent_header(&json!({"unread": true, "subject": "urgently-ish"})));
    }

    #[test]
    fn v1_alerts_never_call_and_dialing_becomes_uncertain() {
        let h = "a".repeat(64);
        let v1 = json!({"version": 1, "seen": {"gmail": [h]}, "alerts": [{"source": "gmail", "subject": "s", "sender": "x", "time": "t", "id": h, "call_state": "pending"}]});
        let (_, alerts) = parse_state(&v1).unwrap();
        assert_eq!(alerts[0].call_state, "expired");
        let v2 = json!({"version": 2, "seen": {}, "alerts": [{"source": "gmail", "subject": "s", "sender": "x", "time": "t", "id": h, "call_state": "dialing"}]});
        let (_, alerts) = parse_state(&v2).unwrap();
        assert_eq!(alerts[0].call_state, "uncertain");
        assert!(parse_state(&json!({"version": 3, "seen": {}})).is_err());
    }
}
