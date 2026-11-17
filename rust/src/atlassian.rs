//! Jira tickets and Confluence pages through the user's installed `twg` CLI.
//! Strictly read-only: no reply, comment, create, update or delete exists.

use crate::host::{self, Res, fs};
use crate::{config, pc_control};
use serde_json::{Value, json};

fn twg_binary() -> Option<String> {
    pc_control::which("twg.exe").or_else(|| {
        let path = fs::join(&config::paths().local_app_data, r"Programs\twg\bin\twg.exe");
        fs::stat(&path).is_some_and(|s| s.file).then_some(path)
    })
}

pub fn ready() -> bool {
    twg_binary().is_some()
}

fn authenticated() -> bool {
    let conf = fs::join(&config::paths().app_data, r"twg\auth.conf");
    fs::stat(&conf).is_some_and(|s| s.file && s.size > 0)
}

async fn twg(args: &[&str]) -> Option<String> {
    let binary = twg_binary()?;
    let out = host::run(&binary, args, json!({ "timeoutMs": 15_000 })).await;
    let stdout = out.stdout.trim().to_string();
    (out.code == 0 && !stdout.is_empty()).then_some(stdout)
}

/// Reads the first command that succeeds; the second is the fallback query.
async fn query(primary: &[&str], fallback: &[&str]) -> Option<String> {
    match twg(primary).await {
        Some(out) => Some(out),
        None => twg(fallback).await,
    }
}

fn field(item: &Value, keys: &[&str], default: &str) -> String {
    for key in keys {
        match &item[*key] {
            Value::String(s) => return s.clone(),
            Value::Object(o) => {
                if let Some(name) = o.get("name").or_else(|| o.get("displayName")).and_then(Value::as_str) {
                    return name.to_string();
                }
            }
            Value::Null => continue,
            other => return other.to_string(),
        }
    }
    default.to_string()
}

/// JSON items when the CLI returns JSON, otherwise one entry per text line.
fn items(stdout: &str, list_keys: &[&str], limit: usize) -> Result<Vec<Value>, Vec<String>> {
    match serde_json::from_str::<Value>(stdout) {
        Ok(data) => {
            let list = if data.is_array() { Some(&data) } else { list_keys.iter().map(|k| &data[*k]).find(|v| v.is_array()) };
            Ok(list.and_then(Value::as_array).into_iter().flatten().take(limit).filter(|i| i.is_object()).cloned().collect())
        }
        Err(_) => Err(stdout
            .lines()
            .map(str::trim)
            .filter(|l| !l.is_empty() && !l.starts_with('#') && !l.starts_with("---") && !l.starts_with("==="))
            .take(limit)
            .map(str::to_string)
            .collect()),
    }
}

struct Ticket {
    id: String,
    title: String,
    status: String,
    priority: String,
}

struct Page {
    title: String,
    space: String,
}

async fn recent_tickets(limit: usize) -> Vec<Ticket> {
    let limit_text = limit.to_string();
    let Some(out) = query(&["context", "jira", "workitem"], &["jira", "query", "--limit", &limit_text]).await else { return Vec::new() };
    match items(&out, &["items", "issues", "workitems"], limit) {
        Ok(rows) => rows
            .iter()
            .map(|i| Ticket {
                id: field(i, &["key", "id"], "Ticket"),
                title: field(i, &["summary", "title"], "Untitled Ticket"),
                status: field(i, &["status", "state"], "Open"),
                priority: field(i, &["priority"], "Normal"),
            })
            .collect(),
        Err(lines) => lines
            .into_iter()
            .map(|line| Ticket {
                id: if line.contains(' ') { line.split_whitespace().next().unwrap_or("Ticket").to_string() } else { "Ticket".into() },
                title: line,
                status: "Active".into(),
                priority: "Normal".into(),
            })
            .collect(),
    }
}

async fn confluence_updates(limit: usize) -> Vec<Page> {
    let limit_text = limit.to_string();
    let Some(out) = query(&["context", "confluence", "page"], &["confluence", "query", "--limit", &limit_text]).await else { return Vec::new() };
    match items(&out, &["items", "pages"], limit) {
        Ok(rows) => rows.iter().map(|i| Page { title: field(i, &["title"], "Untitled Page"), space: field(i, &["space", "spaceKey"], "General") }).collect(),
        Err(lines) => lines.into_iter().map(|title| Page { title, space: "Confluence".into() }).collect(),
    }
}

fn for_voice(tickets: &[Ticket], pages: &[Page]) -> String {
    if !ready() {
        return "The Atlassian Teamwork Graph tool is not installed on this system, sir.".into();
    }
    if !authenticated() && tickets.is_empty() {
        return "Atlassian is installed, sir, but you are not logged in yet. Please run 'twg login' to connect your Confluence and Jira account.".into();
    }
    let mut parts = Vec::new();
    match tickets {
        [] => parts.push("There are no active or new tickets on record at the moment, sir.".to_string()),
        [t] => parts.push(format!("You have one active ticket, sir: {}, '{}' in {}.", t.id, t.title, t.status)),
        _ => {
            let joined: Vec<String> = tickets.iter().take(3).map(|t| format!("{}, '{}' in {}", t.id, t.title, t.status)).collect();
            parts.push(format!("You have {} active tickets, sir: {}.", tickets.len(), joined.join("; ")));
            if tickets.len() > 3 {
                parts.push(format!("Plus {} additional tickets.", tickets.len() - 3));
            }
        }
    }
    if !pages.is_empty() {
        let titles: Vec<String> = pages.iter().take(2).map(|p| format!("'{}'", p.title)).collect();
        let plural = if pages.len() != 1 { "s" } else { "" };
        parts.push(format!("In Confluence, {} page{plural} were recently updated, including {}.", pages.len(), titles.join(" and ")));
    }
    parts.join(" ")
}

fn for_context(tickets: &[Ticket], pages: &[Page]) -> String {
    let mut lines = vec!["ACTIVE JIRA TICKETS:".to_string()];
    if tickets.is_empty() {
        lines.push("  No active tickets found.".into());
    }
    for t in tickets {
        lines.push(format!("  - [{}] {} (Status: {}, Priority: {})", t.id, t.title, t.status, t.priority));
    }
    if !pages.is_empty() {
        lines.push("\nRECENT CONFLUENCE PAGES:".into());
        for p in pages {
            lines.push(format!("  - [{}] {}", p.space, p.title));
        }
    }
    lines.push("\nNOTE: Ticket interaction is STRICTLY READ-ONLY. You cannot reply to, comment on, edit, or close tickets.".into());
    lines.join("\n")
}

/// (spoken summary, prompt context)
pub async fn recent_updates() -> Res<(String, String)> {
    if !ready() {
        return Ok((for_voice(&[], &[]), for_context(&[], &[])));
    }
    let tickets = recent_tickets(5).await;
    let pages = confluence_updates(3).await;
    Ok((for_voice(&tickets, &pages), for_context(&tickets, &pages)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_json_and_text_listings() {
        let rows = items(r#"{"issues":[{"key":"JV-1","summary":"Fix","status":{"name":"Done"}}]}"#, &["items", "issues"], 5).unwrap();
        assert_eq!(field(&rows[0], &["status"], "Open"), "Done");
        assert_eq!(items("# head\nJV-2 Do it\n\n", &["items"], 5).unwrap_err(), vec!["JV-2 Do it"]);
    }
}
