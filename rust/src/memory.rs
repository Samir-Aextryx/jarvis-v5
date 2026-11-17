//! `data/jarvis.db`: learned memories, to-do tasks, topic notes and the
//! dispatch registry (Codex project builds). Same schema as before.

use crate::config;
use crate::host::{self, Db, Res};
use crate::util::{s, take};
use serde_json::{Value, json};
use std::cell::RefCell;

thread_local! {
    static DB: RefCell<Option<Db>> = const { RefCell::new(None) };
}

fn db() -> Res<Db> {
    if let Some(db) = DB.with(|d| *d.borrow()) {
        return Ok(db);
    }
    let db = Db::open(&config::paths().data_file("data\\jarvis.db"))?;
    db.exec("PRAGMA busy_timeout=10000; PRAGMA journal_mode=WAL;")?;
    db.exec(
        "CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, content TEXT NOT NULL,
            source TEXT DEFAULT '', importance INTEGER DEFAULT 5, created_at REAL NOT NULL,
            last_accessed REAL, access_count INTEGER DEFAULT 0);
         CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT DEFAULT '',
            priority TEXT DEFAULT 'medium', status TEXT DEFAULT 'open', due_date TEXT, due_time TEXT,
            project TEXT DEFAULT '', tags TEXT DEFAULT '[]', notes TEXT DEFAULT '',
            created_at REAL NOT NULL, completed_at REAL);
         CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT DEFAULT '', content TEXT NOT NULL,
            topic TEXT DEFAULT '', tags TEXT DEFAULT '[]', created_at REAL NOT NULL, updated_at REAL);
         CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(content, type, source, content='memories', content_rowid='id');
         CREATE VIRTUAL TABLE IF NOT EXISTS task_fts USING fts5(title, description, project, notes, content='tasks', content_rowid='id');
         CREATE VIRTUAL TABLE IF NOT EXISTS note_fts USING fts5(title, content, topic, content='notes', content_rowid='id');
         CREATE TABLE IF NOT EXISTS dispatches (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_name TEXT NOT NULL, project_path TEXT NOT NULL,
            original_prompt TEXT NOT NULL, refined_prompt TEXT DEFAULT '', status TEXT DEFAULT 'pending',
            claude_response TEXT DEFAULT '', summary TEXT DEFAULT '', created_at REAL NOT NULL,
            updated_at REAL NOT NULL, completed_at REAL);
         CREATE INDEX IF NOT EXISTS idx_dispatch_status ON dispatches(status);
         CREATE INDEX IF NOT EXISTS idx_dispatch_updated ON dispatches(updated_at DESC);",
    )?;
    DB.with(|d| *d.borrow_mut() = Some(db));
    Ok(db)
}

fn query(sql: &str, params: Value) -> Vec<Value> {
    db().and_then(|d| d.query(sql, params)).unwrap_or_default()
}

fn run(sql: &str, params: Value) -> Res<(i64, i64)> {
    db()?.run(sql, params)
}

/// Words joined with OR, without characters that break FTS5.
fn fts_query(text: &str) -> String {
    let cleaned = text.replace(['\'', '"', '*'], "").replace('-', " ");
    cleaned.split_whitespace().filter(|w| w.chars().count() > 2).take(5).collect::<Vec<_>>().join(" OR ")
}

// ---- memories ---------------------------------------------------------------------

pub fn remember(content: &str, kind: &str, source: &str, importance: i64) -> Res<i64> {
    let (_, id) = run(
        "INSERT INTO memories (type, content, source, importance, created_at) VALUES (?, ?, ?, ?, ?)",
        json!([kind, content, source, importance, host::now_secs()]),
    )?;
    run("INSERT INTO memory_fts (rowid, content, type, source) VALUES (?, ?, ?, ?)", json!([id, content, kind, source]))?;
    crate::info!("Stored memory [{kind}]: {}", take(content, 60));
    Ok(id)
}

pub fn recall(text: &str, limit: usize) -> Vec<Value> {
    let q = fts_query(text);
    if q.is_empty() {
        return Vec::new();
    }
    let rows = query(
        "SELECT m.id, m.type, m.content, m.importance, m.created_at, m.access_count FROM memory_fts f
         JOIN memories m ON f.rowid = m.id WHERE memory_fts MATCH ? ORDER BY rank LIMIT ?",
        json!([q, limit]),
    );
    for r in &rows {
        let _ = run(
            "UPDATE memories SET last_accessed = ?, access_count = access_count + 1 WHERE id = ?",
            json!([host::now_secs(), r["id"]]),
        );
    }
    rows
}

pub fn important_memories(limit: usize) -> Vec<Value> {
    query("SELECT * FROM memories ORDER BY importance DESC, access_count DESC LIMIT ?", json!([limit]))
}

// ---- tasks ------------------------------------------------------------------------

const PRIORITY_ORDER: &str = "CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END";

pub fn create_task(title: &str, description: &str, priority: &str, due_date: &str) -> Res<i64> {
    let (_, id) = run(
        "INSERT INTO tasks (title, description, priority, due_date, due_time, project, tags, created_at)
         VALUES (?, ?, ?, ?, '', '', '[]', ?)",
        json!([title, description, priority, due_date, host::now_secs()]),
    )?;
    run(
        "INSERT INTO task_fts (rowid, title, description, project, notes) VALUES (?, ?, ?, '', '')",
        json!([id, title, description]),
    )?;
    crate::info!("Created task [{priority}]: {title}");
    Ok(id)
}

pub fn open_tasks() -> Vec<Value> {
    query(&format!("SELECT * FROM tasks WHERE status IN ('open','in_progress') ORDER BY {PRIORITY_ORDER}, due_date"), json!([]))
}

pub fn complete_task(id: i64) {
    let _ = run("UPDATE tasks SET status = 'done', completed_at = ? WHERE id = ?", json!([host::now_secs(), id]));
}

pub fn format_tasks_for_voice(tasks: &[Value]) -> String {
    if tasks.is_empty() {
        return "No tasks on the list, sir.".into();
    }
    let due = |t: &Value| s(t, "due_date").to_string();
    if tasks.len() == 1 {
        let t = &tasks[0];
        let d = due(t);
        return format!("One task: {}.", s(t, "title")) + &if d.is_empty() { String::new() } else { format!(" Due {d}.") };
    }
    let high = tasks.iter().filter(|t| s(t, "priority") == "high").count();
    let mut out = format!("You have {} open tasks.", tasks.len());
    if high > 0 {
        out += &format!(" {high} are high priority.");
    }
    for t in tasks.iter().take(3) {
        out += &format!(" {}.", s(t, "title"));
    }
    if tasks.len() > 3 {
        out += &format!(" And {} more.", tasks.len() - 3);
    }
    out
}

// ---- topic notes ------------------------------------------------------------------

pub fn create_note(content: &str, title: &str, topic: &str) -> Res<i64> {
    let now = host::now_secs();
    let (_, id) = run(
        "INSERT INTO notes (title, content, topic, tags, created_at, updated_at) VALUES (?, ?, ?, '[]', ?, ?)",
        json!([title, content, topic, now, now]),
    )?;
    run("INSERT INTO note_fts (rowid, title, content, topic) VALUES (?, ?, ?, ?)", json!([id, title, content, topic]))?;
    Ok(id)
}

// ---- context for the model ----------------------------------------------------------

pub fn context(user_message: &str) -> String {
    let mut parts = Vec::new();
    let high: Vec<Value> = open_tasks().into_iter().filter(|t| s(t, "priority") == "high").collect();
    if !high.is_empty() {
        let lines: Vec<String> = high
            .iter()
            .take(5)
            .map(|t| {
                let d = s(t, "due_date");
                format!("  - [{}] {}{}", s(t, "priority"), s(t, "title"), if d.is_empty() { String::new() } else { format!(" (due {d})") })
            })
            .collect();
        parts.push(format!("HIGH PRIORITY TASKS:\n{}", lines.join("\n")));
    }
    let relevant = if user_message.chars().count() > 5 { recall(user_message, 3) } else { Vec::new() };
    if !relevant.is_empty() {
        let lines: Vec<String> = relevant.iter().map(|m| format!("  - [{}] {}", s(m, "type"), s(m, "content"))).collect();
        parts.push(format!("RELEVANT MEMORIES:\n{}", lines.join("\n")));
    }
    let lines: Vec<String> = important_memories(3)
        .iter()
        .filter(|m| !relevant.iter().any(|r| r["content"] == m["content"]))
        .map(|m| format!("  - {}", s(m, "content")))
        .take(3)
        .collect();
    if !lines.is_empty() {
        parts.push(format!("KEY FACTS:\n{}", lines.join("\n")));
    }
    parts.join("\n\n")
}

// ---- dispatch registry --------------------------------------------------------------

pub mod dispatch {
    use super::*;

    pub fn register(project_name: &str, project_path: &str, prompt: &str) -> i64 {
        let now = host::now_secs();
        let id = run(
            "INSERT INTO dispatches (project_name, project_path, original_prompt, status, created_at, updated_at)
             VALUES (?, ?, ?, 'pending', ?, ?)",
            json!([project_name, project_path, prompt, now, now]),
        )
        .map(|(_, id)| id)
        .unwrap_or(0);
        crate::info!("Registered dispatch #{id}: {project_name}");
        id
    }

    pub fn update(id: i64, status: &str, response: Option<&str>, summary: Option<&str>) {
        let now = host::now_secs();
        let _ = match response {
            Some(r) => {
                let done = ["completed", "failed", "timeout"].contains(&status);
                run(
                    "UPDATE dispatches SET status=?, claude_response=?, summary=?, updated_at=?, completed_at=? WHERE id=?",
                    json!([status, take(r, 5000), summary.unwrap_or(""), now, if done { json!(now) } else { Value::Null }, id]),
                )
            }
            None => run("UPDATE dispatches SET status=?, updated_at=? WHERE id=?", json!([status, now, id])),
        };
    }

    pub fn most_recent() -> Option<Value> {
        query("SELECT * FROM dispatches ORDER BY updated_at DESC LIMIT 1", json!([])).into_iter().next()
    }

    fn active() -> Vec<Value> {
        query("SELECT * FROM dispatches WHERE status IN ('pending','building','planning') ORDER BY updated_at DESC", json!([]))
    }

    pub fn recent_for_project(name: &str, max_age_seconds: f64) -> Option<Value> {
        query(
            "SELECT * FROM dispatches WHERE project_name LIKE ? AND status = 'completed'
             AND completed_at IS NOT NULL AND completed_at >= ? ORDER BY completed_at DESC LIMIT 1",
            json!([format!("%{name}%"), host::now_secs() - max_age_seconds]),
        )
        .into_iter()
        .next()
    }

    pub fn format_for_prompt() -> String {
        let active = active();
        let recent = query("SELECT * FROM dispatches ORDER BY updated_at DESC LIMIT 3", json!([]));
        let mut parts = Vec::new();
        if !active.is_empty() {
            let now = host::now_secs();
            let lines: Vec<String> = active
                .iter()
                .map(|d| {
                    let elapsed = (now - d["created_at"].as_f64().unwrap_or(now)) as i64;
                    format!("  - [{}] {} ({elapsed}s ago): {}", s(d, "status"), s(d, "project_name"), take(s(d, "original_prompt"), 80))
                })
                .collect();
            parts.push(format!("CURRENTLY WORKING ON:\n{}", lines.join("\n")));
        }
        let completed: Vec<String> = recent
            .iter()
            .filter(|d| s(d, "status") == "completed" && !active.iter().any(|a| a["id"] == d["id"]))
            .take(2)
            .map(|d| {
                let summary = s(d, "summary");
                if summary.is_empty() {
                    format!("  - {}: completed", s(d, "project_name"))
                } else {
                    format!("  - {}: {}", s(d, "project_name"), take(summary, 80))
                }
            })
            .collect();
        if !completed.is_empty() {
            parts.push(format!("RECENTLY COMPLETED:\n{}", completed.join("\n")));
        }
        if parts.is_empty() { "No active or recent dispatches.".into() } else { parts.join("\n") }
    }
}
