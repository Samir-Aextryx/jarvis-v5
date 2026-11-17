//! Jarvis's own notes (`data/jarvis_notes.db`, SQLite with FTS5).

use crate::config;
use crate::host::{self, Db, Res};
use crate::util::{LocalTime, s, take, uuid_hex};
use serde_json::{Value, json};
use std::cell::RefCell;

thread_local! {
    static DB: RefCell<Option<Db>> = const { RefCell::new(None) };
}

fn db() -> Res<Db> {
    if let Some(db) = DB.with(|d| *d.borrow()) {
        return Ok(db);
    }
    let db = Db::open(&config::paths().data_file("data\\jarvis_notes.db"))?;
    db.exec("PRAGMA busy_timeout=10000; PRAGMA journal_mode=WAL;")?;
    db.exec(
        "CREATE TABLE IF NOT EXISTS notes (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL,
            folder TEXT NOT NULL DEFAULT 'Notes', tags TEXT NOT NULL DEFAULT '[]',
            created_at REAL NOT NULL, updated_at REAL NOT NULL);
         CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated_at DESC);
         CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(title, body, folder, content='notes', content_rowid='rowid');",
    )?;
    DB.with(|d| *d.borrow_mut() = Some(db));
    Ok(db)
}

fn public(mut row: Value) -> Value {
    let created = row["created_at"].as_f64().unwrap_or_else(host::now_secs);
    let t = LocalTime::from_ms(created * 1000.0);
    row["date"] = json!(format!("{} {:02}:{:02}", t.date(), t.hour, t.minute));
    let tags = serde_json::from_str::<Value>(s(&row, "tags")).ok().filter(Value::is_array).unwrap_or(json!([]));
    row["tags"] = tags;
    row
}

fn rows(sql: &str, params: Value) -> Vec<Value> {
    db().and_then(|d| d.query(sql, params)).unwrap_or_default().into_iter().map(public).collect()
}

pub fn create(title: &str, body: &str, folder: &str, tags: Option<&Value>) -> Res<Value> {
    let db = db()?;
    let id = uuid_hex();
    let title = take(if title.trim().is_empty() { "Untitled Note" } else { title.trim() }, 300);
    let body = body.trim();
    let folder = take(if folder.trim().is_empty() { "Notes" } else { folder.trim() }, 100);
    let tags = tags.filter(|t| t.is_array()).cloned().unwrap_or(json!([])).to_string();
    let now = host::now_secs();
    let (_, rowid) = db.run(
        "INSERT INTO notes (id, title, body, folder, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        json!([id, title, body, folder, tags, now, now]),
    )?;
    let _ = db.run("INSERT INTO notes_fts (rowid, title, body, folder) VALUES (?, ?, ?, ?)", json!([rowid, title, body, folder]));
    crate::info!("Created local note '{title}' (id={id})");
    rows("SELECT * FROM notes WHERE id=?", json!([id])).into_iter().next().ok_or_else(|| "Note was not saved.".into())
}

pub fn recent(count: usize) -> Vec<Value> {
    rows("SELECT * FROM notes ORDER BY updated_at DESC, rowid DESC LIMIT ?", json!([count.max(1)]))
}

pub fn list() -> Vec<Value> {
    rows("SELECT * FROM notes ORDER BY updated_at DESC, rowid DESC", json!([]))
}

/// By id, exact title, partial title, then partial body.
pub fn read(title_match: &str) -> Option<Value> {
    let target = title_match.trim();
    if target.is_empty() {
        return None;
    }
    let like = format!("%{target}%");
    [
        ("SELECT * FROM notes WHERE id=?", json!([target])),
        ("SELECT * FROM notes WHERE LOWER(title) = LOWER(?) ORDER BY updated_at DESC, rowid DESC LIMIT 1", json!([target])),
        ("SELECT * FROM notes WHERE LOWER(title) LIKE LOWER(?) ORDER BY updated_at DESC, rowid DESC LIMIT 1", json!([like])),
        ("SELECT * FROM notes WHERE LOWER(body) LIKE LOWER(?) ORDER BY updated_at DESC, rowid DESC LIMIT 1", json!([like])),
    ]
    .into_iter()
    .find_map(|(sql, params)| rows(sql, params).into_iter().next())
}

pub fn search(text: &str, count: usize) -> Vec<Value> {
    let cleaned = text.trim();
    if cleaned.is_empty() {
        return Vec::new();
    }
    let plain = cleaned.replace(['\'', '"'], "");
    let words: Vec<&str> = plain.split_whitespace().filter(|w| w.chars().count() > 1).take(5).collect();
    if !words.is_empty() {
        let found = db().and_then(|d| {
            d.query(
                "SELECT n.* FROM notes_fts f JOIN notes n ON f.rowid = n.rowid WHERE notes_fts MATCH ? ORDER BY rank LIMIT ?",
                json!([words.join(" OR "), count]),
            )
        });
        if let Ok(found) = found
            && !found.is_empty()
        {
            return found.into_iter().map(public).collect();
        }
    }
    let like = format!("%{cleaned}%");
    rows(
        "SELECT * FROM notes WHERE LOWER(title) LIKE LOWER(?) OR LOWER(body) LIKE LOWER(?) ORDER BY updated_at DESC, rowid DESC LIMIT ?",
        json!([like, like, count]),
    )
}

pub fn delete(id: &str) -> bool {
    let Ok(db) = db() else { return false };
    let Some(row) = db.query_one("SELECT rowid FROM notes WHERE id=?", json!([id])).ok().flatten() else { return false };
    if db.run("DELETE FROM notes WHERE id=?", json!([id])).is_err() {
        return false;
    }
    let _ = db.run("DELETE FROM notes_fts WHERE rowid=?", json!([row["rowid"]]));
    crate::info!("Deleted local note {id}");
    true
}

/// Short context of matching notes for the model (data, not instructions).
pub fn relevant_context(text: &str) -> String {
    const STOP: &[&str] = &[
        "about", "after", "all", "and", "are", "but", "can", "did", "for", "from", "have", "how", "into", "is", "its", "just", "mit",
        "nicht", "oder", "the", "their", "there", "this", "that", "was", "what", "when", "where", "which", "who", "why", "will", "with",
        "you", "your", "der", "die", "das", "ein", "eine", "einen", "ich", "mein", "meine", "mir", "mich", "und", "von", "wie", "wo",
        "wann", "wer", "warum",
    ];
    let folded = text.to_lowercase();
    let terms: Vec<&str> = crate::re!(r"\w{3,}").find_iter(&folded).map(|m| m.as_str()).filter(|w| !STOP.contains(w)).take(5).collect();
    let q = if terms.is_empty() { text.to_string() } else { terms.join(" ") };
    let lines: Vec<String> = search(&q, 3)
        .iter()
        .filter_map(|n| {
            let title = take(&crate::personal::safe_text(s(n, "title")), 100);
            let body = take(&crate::personal::safe_text(s(n, "body")), 320);
            match (title.is_empty(), body.is_empty()) {
                (true, true) => None,
                (false, _) => Some(format!("- {title}: {body}")),
                (true, false) => Some(format!("- {body}")),
            }
        })
        .collect();
    take(&lines.join("\n"), 1100)
}
