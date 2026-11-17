//! Deterministic routing for "open everything" and "what's new"; everything
//! else stays with the existing planners. No external routing service.

use crate::{apps, calendar, google, settings};
use serde_json::{Value, json};

fn direct_intent(text: &str) -> Option<&'static str> {
    let text = text.to_lowercase().replace('’', "'");
    let text = text.trim().trim_matches([' ', '.', '!', '?']);
    if ["open everything", "start everything", "open my work apps", "start my apps", "launch everything", "öffne alles", "starte meine apps"].contains(&text) {
        return Some("work_apps");
    }
    if ["what's new", "anything important", "anything new", "check my emails", "did i receive anything important", "what happened today", "give me an update", "was gibt es neues"]
        .contains(&text)
    {
        return Some("personal_update");
    }
    None
}

pub async fn route(text: &str) -> Value {
    json!({ "intent": direct_intent(text), "notice": "" })
}

pub async fn execute(decision: &Value) -> String {
    let intent = decision["intent"].as_str().unwrap_or("");
    if intent == "error" {
        return decision["message"].as_str().unwrap_or("").to_string();
    }
    if !settings::automation_enabled() {
        return "Automatic tool execution is disabled in AI Settings.".into();
    }
    if intent == "personal_update" {
        let result = personal_update().await;
        settings::activity("personal.update", true, 1);
        return result;
    }
    let targets: Vec<String> = if intent == "work_apps" {
        settings::get().get("work_apps").and_then(Value::as_array).map(|a| a.iter().filter_map(Value::as_str).map(str::to_string).collect()).unwrap_or_default()
    } else {
        decision["app"].as_str().map(|a| vec![a.to_string()]).unwrap_or_default()
    };
    if targets.is_empty() {
        return "Your Open Everything Apps list is empty. Add apps in Settings.".into();
    }
    // Window focus is shared desktop state, so launches stay serial.
    let mut lines = Vec::new();
    let mut all_ok = true;
    for app in &targets {
        let result = apps::open_app(app, apps::OpenOptions::default()).await;
        all_ok &= result.success;
        lines.push(result.confirmation);
    }
    settings::activity("apps.open", all_ok, lines.len() as i64);
    lines.join("\n")
}

fn text(v: &Value, key: &str, max: usize) -> String {
    crate::util::take(v[key].as_str().unwrap_or(""), max)
}

/// Reads independent sources concurrently; no writes.
async fn personal_update() -> String {
    let status = google::status();
    let services: Vec<&str> = status["services"].as_array().map(|a| a.iter().filter_map(Value::as_str).collect()).unwrap_or_default();
    let connected = status["connected"] == true;
    let gmail_on = connected && services.contains(&"gmail");
    let calendar_on = connected && services.contains(&"calendar");
    let (gmail, google_calendar) = futures::join!(
        async {
            if gmail_on { Some(google::search_gmail("newer_than:7d (is:unread OR is:important) -in:spam -in:trash", 20).await) } else { None }
        },
        async { if calendar_on { Some(google::read("calendar").await) } else { None } },
    );
    let mut unavailable = Vec::new();
    let mut events: Vec<Value> = Vec::new();
    match calendar::upcoming(2) {
        Ok(items) => events.extend(items),
        Err(_) => unavailable.push("Jarvis calendar"),
    }
    let mut mail: Vec<Value> = Vec::new();
    match gmail {
        Some(Ok(v)) => mail = v["items"].as_array().cloned().unwrap_or_default(),
        Some(Err(_)) => unavailable.push("Gmail"),
        None => {}
    }
    match google_calendar {
        Some(Ok(v)) => events.extend(v["items"].as_array().cloned().unwrap_or_default()),
        Some(Err(_)) => unavailable.push("Google calendar"),
        None => {}
    }
    let mut lines = Vec::new();
    if !mail.is_empty() {
        lines.push(format!("{} recent unread or important messages:", mail.len()));
        for m in mail.iter().take(5) {
            let subject = text(m, "subject", 180);
            lines.push(format!("• {}: {}. {}", text(m, "from", 80), if subject.is_empty() { "(no subject)".into() } else { subject }, text(m, "snippet", 200)));
        }
        if mail.len() > 5 {
            lines.push(format!("{} more messages are available.", mail.len() - 5));
        }
    } else if gmail_on && !unavailable.contains(&"Gmail") {
        lines.push("No matching recent unread or important Gmail messages were found.".into());
    } else {
        lines.push("Gmail is not available. Connect Gmail reading in Settings to include it.".into());
    }
    for event in events.iter().take(4) {
        let start = match &event["start"] {
            Value::Object(o) => o.get("dateTime").or_else(|| o.get("date")).and_then(Value::as_str).unwrap_or("").to_string(),
            other => other.as_str().unwrap_or("").to_string(),
        };
        lines.push(format!("• Calendar: {} — {start}", event["title"].as_str().unwrap_or("")));
    }
    if !unavailable.is_empty() {
        lines.push(format!("Could not check: {}.", unavailable.join(", ")));
    }
    lines.push("Outlook and Teams notifications were not checked.".into());
    lines.join("\n")
}
