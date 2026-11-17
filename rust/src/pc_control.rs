//! Explicit local PC commands (Defender, files, drives) and the Codex runner.
//! No speech text is ever evaluated by a shell.

use crate::config;
use crate::desktop::run_powershell;
use crate::host::{self, Proc, Res, fs};
use crate::util::{LocalTime, take, uuid_hex};
use serde_json::{Map, Value, json};
use std::cell::{Cell, RefCell};
use std::rc::Rc;
use wasm_bindgen_futures::spawn_local;

pub const STOPPED: &str = "Coding task stopped; existing file changes were preserved.";
const MAX_FINISHED_JOBS: usize = 50;

pub type Cancel = Rc<Cell<bool>>;

thread_local! {
    static JOBS: RefCell<Vec<Map<String, Value>>> = const { RefCell::new(Vec::new()) };
    static CANCELS: RefCell<Vec<(String, Cancel)>> = const { RefCell::new(Vec::new()) };
    static PENDING_REMOVAL: RefCell<Option<(f64, Vec<String>)>> = const { RefCell::new(None) };
}

// ---- paths ------------------------------------------------------------------------

pub fn desktop() -> String {
    config::paths().desktop
}

fn expand_vars(text: &str) -> String {
    crate::re!(r"%([^%]+)%").replace_all(text, |c: &regex::Captures| config::get(&c[1]).unwrap_or_else(|| c[0].to_string())).to_string()
}

/// Collapses `.` and `..` like `Path.resolve()`.
fn normalize(path: &str) -> String {
    let path = path.replace('/', "\\");
    let mut parts: Vec<&str> = Vec::new();
    for part in path.split('\\') {
        match part {
            "" | "." => {}
            ".." => {
                if parts.len() > 1 {
                    parts.pop();
                }
            }
            p => parts.push(p),
        }
    }
    if parts.len() == 1 { format!("{}\\", parts[0]) } else { parts.join("\\") }
}

/// A local absolute path that exists; aliases for Desktop, Downloads, Documents and home.
pub fn local_path(value: &str) -> Res<String> {
    let p = config::paths();
    let value = value.trim().trim_matches('"');
    let path = match value.to_lowercase().as_str() {
        "desktop" => desktop(),
        "downloads" => fs::join(&p.home, "Downloads"),
        "dokumente" => fs::join(&p.home, "Documents"),
        "benutzerordner" => p.home.clone(),
        _ => expand_vars(value),
    };
    let absolute = crate::re!(r"^[A-Za-z]:[\\/]").is_match(&path);
    if !absolute || path.starts_with("\\\\") || path.get(2..).is_some_and(|rest| rest.contains(':')) {
        return Err("Bitte einen lokalen absoluten Pfad wie C:\\Users\\Samir oder Desktop angeben.".into());
    }
    let resolved = normalize(&path);
    if !fs::exists(&resolved) {
        return Err(format!("[WinError 2] Das System kann die angegebene Datei nicht finden: '{path}'"));
    }
    Ok(resolved)
}

fn extension(path: &str) -> String {
    let name = fs::file_name(path);
    match name.rfind('.') {
        Some(i) if i > 0 => name[i..].to_lowercase(),
        _ => String::new(),
    }
}

// ---- command parsing ------------------------------------------------------------------

pub type Command = (&'static str, String);

pub fn parse(text: &str) -> Option<Command> {
    let text = crate::re!(r"(?i)^(?:hey\s+)?jarvis[,\s]+").replace(text, "").trim().trim_end_matches(['!', '?', '.']).to_string();
    let text = crate::re!(r"(?i)^(?:kannst du\s+)?bitte\s+").replace(&text, "").to_string();
    let lower = text.to_lowercase();
    if crate::re!(r"(?i)^(?:zeige |prüfe |wie ist (?:der )?)?(?:defender.status|sicherheitsstatus|virenstatus|scanstatus|scan.status)$").is_match(&text) {
        return Some(("security_status", String::new()));
    }
    if crate::re!(r"(?i)^(?:starte (?:einen |den )?)?(?:virenscan|schnellscan|vollscan|vollständigen virenscan|vollständiger virenscan)$").is_match(&text)
        || crate::re!(r"(?i)^(?:scanne|prüfe|untersuche) (?:meinen |den )?(?:ganzen |gesamten )?(?:pc|computer)(?: auf (?:viren|viruse|malware))?$").is_match(&text)
    {
        let full = crate::re!(r"(?i)voll|ganz|gesamt").is_match(&text);
        return Some(("scan", if full { "FullScan" } else { "QuickScan" }.into()));
    }
    if crate::re!(r"(?i)^(?:lösche|entferne|bereinige) (?:alle |die )?(?:erkannten |gefundenen )?(?:viren|viruse|bedrohungen|malware)$").is_match(&text) {
        return Some(("remove_prepare", String::new()));
    }
    if lower == "defender bereinigung bestätigen" {
        return Some(("remove_confirm", String::new()));
    }
    if lower == "codex status" || lower == "programmierstatus" {
        return Some(("coding_status", String::new()));
    }
    if crate::re!(r"(?i)^(?:programmiere|entwickle|code)\b|^(?:erstelle|baue|schreibe)\b.*\b(?:app|website|webseite|programm|skript|script|spiel|code)\b|^(?:sende|gib|schicke)\b.*\bcodex\b").is_match(&text) {
        return Some(("code", text));
    }
    if ["zeige laufwerke", "zeige meine laufwerke", "öffne diesen pc"].contains(&lower.as_str()) {
        return Some(("drives", String::new()));
    }
    let patterns: [(&regex::Regex, &str); 4] = [
        (crate::re!(r"(?i)^(?:öffne|zeige) (?:den |die |das )?(?:ordner|datei) (.+)$"), "open_path"),
        (crate::re!(r"(?i)^(?:zeige|liste) (?:den )?(?:inhalt von|dateien in) (.+)$"), "list_path"),
        (crate::re!(r"(?i)^(?:lies|lese) (?:die )?datei (.+)$"), "read_path"),
        (crate::re!(r"(?i)^(?:suche|finde) (?:die )?datei (.+)$"), "find_path"),
    ];
    for (re, action) in patterns {
        if let Some(c) = re.captures(&text) {
            return Some((action, c[1].to_string()));
        }
    }
    if ["öffne desktop", "öffne downloads", "öffne dokumente"].contains(&lower.as_str()) {
        return Some(("open_path", text.split_once(' ').map(|x| x.1.to_string()).unwrap_or_default()));
    }
    None
}

// ---- jobs -------------------------------------------------------------------------------

fn job_get(id: &str) -> Option<Map<String, Value>> {
    JOBS.with(|j| j.borrow().iter().find(|x| x["id"] == id).cloned())
}

pub fn job_update(id: &str, f: impl FnOnce(&mut Map<String, Value>)) {
    JOBS.with(|j| {
        if let Some(job) = j.borrow_mut().iter_mut().find(|x| x["id"] == id) {
            f(job);
        }
    });
}


pub fn persist(id: &str) {
    if let Some(job) = job_get(id) {
        let folder = config::paths().data_file("data\\pc-jobs");
        let text = serde_json::to_string_pretty(&Value::Object(job)).unwrap_or_default();
        let _ = fs::write_text(&fs::join(&folder, &format!("{id}.json")), &text);
    }
}

fn prune() {
    let removed: Vec<String> = JOBS.with(|j| {
        let mut jobs = j.borrow_mut();
        let mut finished: Vec<(f64, String)> = jobs
            .iter()
            .filter(|x| !matches!(x.get("state").and_then(Value::as_str), Some("running" | "stopping")))
            .map(|x| (x.get("started").and_then(Value::as_f64).unwrap_or(0.0), x["id"].as_str().unwrap_or("").to_string()))
            .collect();
        finished.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
        let excess = finished.len().saturating_sub(MAX_FINISHED_JOBS);
        let gone: Vec<String> = finished.into_iter().take(excess).map(|x| x.1).collect();
        jobs.retain(|x| !gone.iter().any(|g| x["id"] == g.as_str()));
        gone
    });
    let folder = config::paths().data_file("data\\pc-jobs");
    for id in removed {
        fs::remove(&fs::join(&folder, &format!("{id}.json")));
    }
}

pub fn new_job(kind: &str) -> String {
    let id = uuid_hex();
    let mut job = Map::new();
    job.insert("id".into(), json!(id));
    job.insert("kind".into(), json!(kind));
    job.insert("state".into(), json!("running"));
    job.insert("started".into(), json!(host::now_secs()));
    JOBS.with(|j| j.borrow_mut().push(job));
    id
}

pub fn register_cancel(id: &str, cancel: Cancel) {
    CANCELS.with(|c| c.borrow_mut().push((id.to_string(), cancel)));
}

pub fn drop_cancel(id: &str) {
    CANCELS.with(|c| c.borrow_mut().retain(|(k, _)| k != id));
}

fn running(kind: &str) -> bool {
    JOBS.with(|j| j.borrow().iter().any(|x| x["kind"] == kind && matches!(x.get("state").and_then(Value::as_str), Some("running" | "stopping"))))
}

pub fn jobs() -> Vec<Value> {
    JOBS.with(|j| j.borrow().iter().map(|x| Value::Object(x.clone())).collect())
}

/// Signals running Codex jobs to stop their process tree.
pub fn cancel_code() -> bool {
    let ids: Vec<String> = JOBS.with(|j| {
        j.borrow().iter().filter(|x| x["kind"] == "code" && x["state"] == "running").map(|x| x["id"].as_str().unwrap_or("").to_string()).collect()
    });
    let mut stopped = false;
    for id in ids {
        let cancel = CANCELS.with(|c| c.borrow().iter().find(|(k, _)| *k == id).map(|(_, v)| v.clone()));
        if let Some(cancel) = cancel {
            cancel.set(true);
            job_update(&id, |j| {
                j.insert("state".into(), json!("stopping"));
            });
            stopped = true;
        }
    }
    stopped
}

fn start(kind: &'static str, value: String, project: Option<String>) -> String {
    if running(kind) {
        return "Ein solcher Auftrag läuft bereits. Frage nach dem Scanstatus oder Codex Status.".into();
    }
    let id = new_job(kind);
    persist(&id);
    let cancel: Cancel = Rc::new(Cell::new(false));
    register_cancel(&id, cancel.clone());
    let job_id = id.clone();
    spawn_local(async move {
        let result = if kind == "code" { code(&job_id, &value, project.as_deref(), &cancel).await } else { scan(&job_id, &value).await };
        let cancelled = cancel.get();
        job_update(&job_id, |j| match (&result, cancelled) {
            (_, true) => {
                j.insert("state".into(), json!("cancelled"));
                j.insert("message".into(), json!(STOPPED));
            }
            (Ok(()), false) => {
                j.insert("state".into(), json!("done"));
            }
            (Err(e), false) => {
                j.insert("state".into(), json!("error"));
                j.insert("message".into(), json!(take(e, 400)));
            }
        });
        drop_cancel(&job_id);
        persist(&job_id);
        prune();
    });
    if kind == "scan" {
        "Defender-Prüfung beauftragt. Frage nach dem Scanstatus.".into()
    } else {
        "Ich übergebe deinen Auftrag an Codex und öffne die Aufgabe, sobald Codex sie angelegt hat. Frage nach Codex Status.".into()
    }
}

// ---- Defender ----------------------------------------------------------------------------

const DEFENDER_FAILED: &str =
    "Windows konnte den Defender-Befehl nicht ausführen. Eventuell fehlen Administratorrechte oder Defender ist nicht verfügbar.";

async fn powershell(script: &str, timeout_ms: u32) -> Res<String> {
    run_powershell(&format!("$ErrorActionPreference='Stop'; {script}"), timeout_ms).await.map(|s| s.trim().to_string()).map_err(|_| DEFENDER_FAILED.into())
}

async fn defender_status() -> Res<Value> {
    let raw = powershell(
        "$s=Get-MpComputerStatus; $t=@(Get-MpThreat | Where-Object IsActive | Select-Object ThreatID,ThreatName); @{enabled=$s.AntivirusEnabled; realtime=$s.RealTimeProtectionEnabled; quickEnd=[string]$s.QuickScanEndTime; fullEnd=[string]$s.FullScanEndTime; threats=$t} | ConvertTo-Json -Depth 5",
        30_000,
    )
    .await?;
    let mut v: Value = serde_json::from_str(&raw).map_err(|_| DEFENDER_FAILED.to_string())?;
    v["threats"] = match v["threats"].take() {
        Value::Array(a) => Value::Array(a),
        Value::Null => json!([]),
        one => json!([one]),
    };
    Ok(v)
}

fn threats(status: &Value) -> Vec<Value> {
    status["threats"].as_array().cloned().unwrap_or_default()
}

async fn scan(id: &str, scan_type: &str) -> Res<()> {
    powershell(&format!("Start-MpScan -ScanType {scan_type}"), 86_400_000).await?;
    let status = defender_status().await?;
    let message = format!("Defender-Prüfung abgeschlossen. Aktive erkannte Bedrohungen: {}.", threats(&status).len());
    job_update(id, |j| {
        j.insert("message".into(), json!(message));
    });
    Ok(())
}

// ---- Codex --------------------------------------------------------------------------------

pub(crate) fn which(name: &str) -> Option<String> {
    let path = config::get("PATH").unwrap_or_default();
    path.split(';').filter(|d| !d.trim().is_empty()).map(|d| fs::join(d.trim().trim_matches('"'), name)).find(|p| fs::stat(p).is_some_and(|s| s.file))
}

pub fn codex_executable() -> Res<String> {
    if let Some(found) = which("codex.exe") {
        return Ok(found);
    }
    let base = fs::join(&config::paths().local_app_data, "OpenAI\\Codex\\bin");
    fs::list_dir(&base)
        .into_iter()
        .filter(|e| e.dir)
        .filter_map(|e| {
            let exe = fs::join(&fs::join(&base, &e.name), "codex.exe");
            fs::stat(&exe).filter(|s| s.file).map(|s| (s.mtime, exe))
        })
        .max_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal))
        .map(|x| x.1)
        .ok_or_else(|| "Codex ist nicht installiert. Bitte Codex installieren und anmelden.".into())
}

/// Runs `codex exec` for one prompt; the prompt travels over stdin only.
pub async fn code(id: &str, prompt: &str, project: Option<&str>, cancel: &Cancel) -> Res<()> {
    if cancel.get() {
        return Err("Coding task cancelled before launch.".into());
    }
    let exe = codex_executable()?;
    let folder = match project {
        Some(p) => local_path(p)?,
        None => {
            let t = LocalTime::now();
            let stamp = format!("{:04}{:02}{:02}-{:02}{:02}{:02}", t.year, t.month, t.day, t.hour, t.minute, t.second);
            fs::join(&fs::join(&desktop(), "Jarvis Projekte"), &format!("Auftrag-{stamp}-{}", &id[..6]))
        }
    };
    fs::mkdirp(&folder)?;
    job_update(id, |j| {
        j.insert("folder".into(), json!(folder));
    });
    fs::write_text(&fs::join(&folder, &format!("JARVIS-AUFTRAG-{}.md", &id[..12])), prompt)?;
    if cancel.get() {
        return Err("Coding task cancelled before launch.".into());
    }
    let proc = Rc::new(Proc::start(
        &exe,
        &["exec", "--json", "--sandbox", "workspace-write", "--skip-git-repo-check", "-C", &folder, "-"],
        json!({ "stdin": prompt }),
    )?);
    let finished = Rc::new(Cell::new(false));
    {
        let (proc, finished, cancel) = (proc.clone(), finished.clone(), cancel.clone());
        spawn_local(async move {
            while !finished.get() {
                if cancel.get() {
                    proc.kill();
                    return;
                }
                host::sleep(100.0).await;
            }
        });
    }
    let mut pending = String::new();
    let mut failure = false;
    let mut completed = false;
    while let Some(chunk) = proc.read().await {
        pending.push_str(&chunk);
        while let Some(newline) = pending.find('\n') {
            let line: String = pending.drain(..=newline).collect();
            let Ok(event) = serde_json::from_str::<Value>(line.trim()) else { continue };
            let kind = event["type"].as_str().unwrap_or("");
            if kind == "thread.started" {
                let thread = event["thread_id"].as_str().unwrap_or("");
                if crate::re!(r"^[a-zA-Z0-9-]+$").is_match(thread) {
                    let opened = host::shell_open(&format!("codex://threads/{thread}"));
                    job_update(id, |j| {
                        j.insert("thread_id".into(), json!(thread));
                        j.insert("app_open_requested".into(), json!(opened));
                    });
                    persist(id);
                }
            }
            if kind == "error" || kind == "turn.failed" {
                failure = true;
            }
            if kind == "turn.completed" {
                completed = true;
            }
            if kind == "item.completed" && event["item"]["type"] == "agent_message" {
                let text = take(event["item"]["text"].as_str().unwrap_or(""), 8000);
                let report = crate::re!(r"sk-[A-Za-z0-9_-]+").replace_all(&text, "[redacted]").to_string();
                job_update(id, |j| {
                    j.insert("report".into(), json!(report));
                });
            }
        }
    }
    let status = proc.wait().await;
    finished.set(true);
    if status != 0 || failure || !completed {
        return Err("Codex konnte den Auftrag nicht abschließen. Prüfe die geöffnete Codex-Aufgabe und deine Anmeldung.".into());
    }
    let report = job_get(id).and_then(|j| j.get("report").and_then(Value::as_str).map(|r| r.trim().to_string())).unwrap_or_default();
    let message = if report.is_empty() {
        "Codex finished its run; no summary was returned.".to_string()
    } else {
        format!("Codex finished its run. {report}")
    } + " Project folder: "
        + &folder;
    job_update(id, |j| {
        j.insert("message".into(), json!(message));
    });
    Ok(())
}

/// Runs one owned Codex job to completion (autonomous tasks), honoring `cancel`.
pub async fn run_code(prompt: &str, project: Option<&str>, cancel: &Cancel) -> Res<String> {
    if running("code") {
        return Err("Another coding task is still running.".into());
    }
    let id = new_job("code");
    persist(&id);
    register_cancel(&id, cancel.clone());
    let result = code(&id, prompt, project, cancel).await;
    let out = match (&result, cancel.get()) {
        (_, true) => {
            job_update(&id, |j| {
                j.insert("state".into(), json!("cancelled"));
                j.insert("message".into(), json!(STOPPED));
            });
            Err(STOPPED.to_string())
        }
        (Ok(()), false) => {
            job_update(&id, |j| {
                j.insert("state".into(), json!("done"));
            });
            let job = job_get(&id).unwrap_or_default();
            let message = job.get("message").and_then(Value::as_str).unwrap_or("");
            let report = job.get("report").and_then(Value::as_str).unwrap_or("No final report was supplied.");
            Ok(format!("{message}\nCodex report (not independent verification): {report}"))
        }
        (Err(e), false) => {
            job_update(&id, |j| {
                j.insert("state".into(), json!("error"));
                j.insert("message".into(), json!(take(e, 400)));
            });
            Err(e.clone())
        }
    };
    drop_cancel(&id);
    persist(&id);
    prune();
    out
}

pub fn job_message(id: &str) -> Option<String> {
    job_get(id).and_then(|j| j.get("message").and_then(Value::as_str).map(str::to_string))
}

pub fn set_state(id: &str, state: &str, message: Option<&str>) {
    job_update(id, |j| {
        j.insert("state".into(), json!(state));
        if let Some(m) = message {
            j.insert("message".into(), json!(m));
        }
    });
}

// ---- execution ------------------------------------------------------------------------------

pub async fn execute(command: Command) -> String {
    match execute_inner(command).await {
        Ok(text) => text,
        Err(e) => format!("Aktion nicht abgeschlossen: {}", take(&e, 400)),
    }
}

async fn execute_inner((action, value): Command) -> Res<String> {
    match action {
        "security_status" => {
            let status = defender_status().await?;
            let scanning = JOBS.with(|j| j.borrow().iter().any(|x| x["kind"] == "scan" && x["state"] == "running"));
            let last = JOBS.with(|j| j.borrow().iter().rev().find(|x| x["kind"] == "scan").and_then(|x| x.get("message").and_then(Value::as_str).map(str::to_string)));
            let on = |k: &str| if status[k].as_bool().unwrap_or(false) { "aktiv" } else { "inaktiv" };
            let quick = status["quickEnd"].as_str().filter(|q| !q.is_empty()).unwrap_or("unbekannt");
            Ok(format!(
                "Defender: {}. Echtzeitschutz: {}. Aktive erkannte Bedrohungen: {}. {} Letzter Schnellscan: {quick}",
                on("enabled"),
                on("realtime"),
                threats(&status).len(),
                if scanning { "Scan läuft. ".to_string() } else { last.unwrap_or_default() }
            ))
        }
        "scan" => Ok(start("scan", value, None)),
        "remove_prepare" => {
            let found = threats(&defender_status().await?);
            if found.is_empty() {
                PENDING_REMOVAL.with(|p| *p.borrow_mut() = None);
                return Ok("Defender meldet keine aktiven erkannten Bedrohungen. Es wird nichts gelöscht.".into());
            }
            let ids: Vec<String> = found.iter().map(|t| t["ThreatID"].to_string()).collect();
            PENDING_REMOVAL.with(|p| *p.borrow_mut() = Some((host::monotonic(), ids)));
            let names: Vec<&str> = found.iter().map(|t| t["ThreatName"].as_str().unwrap_or("")).collect();
            Ok(format!(
                "Defender meldet: {}. Sage: Defender Bereinigung bestätigen. Defender übernimmt dann die Bereinigung dieser aktiven Funde.",
                names.join(", ")
            ))
        }
        "remove_confirm" => {
            let pending = PENDING_REMOVAL.with(|p| p.borrow_mut().take());
            let Some((at, mut ids)) = pending.filter(|(at, _)| host::monotonic() - at <= 90_000.0) else {
                return Ok("Keine aktuelle Bereinigung zur Bestätigung. Sage zuerst: Entferne erkannte Viren.".into());
            };
            let _ = at;
            let mut now: Vec<String> = threats(&defender_status().await?).iter().map(|t| t["ThreatID"].to_string()).collect();
            ids.sort();
            ids.dedup();
            now.sort();
            now.dedup();
            if now != ids {
                return Ok("Die Funde haben sich geändert. Sage erneut: Entferne erkannte Viren.".into());
            }
            powershell("Remove-MpThreat", 120_000).await?;
            let left = threats(&defender_status().await?).len();
            Ok(format!("Defender-Bereinigung ausgeführt. Noch aktive erkannte Bedrohungen: {left}."))
        }
        "code" => {
            codex_executable()?;
            Ok(start("code", value, None))
        }
        "coding_status" => {
            let last = JOBS.with(|j| j.borrow().iter().rev().find(|x| x["kind"] == "code").cloned());
            Ok(crate::speech::remember_english(&match last {
                None => "No Codex task has been started in this Jarvis session.".to_string(),
                Some(job) => {
                    job.get("message").and_then(Value::as_str).unwrap_or("Codex is still working.").to_string()
                        + if job.contains_key("thread_id") { " The Codex task has been created." } else { "" }
                }
            }))
        }
        _ => files(action, &value).await,
    }
}

async fn files(action: &str, value: &str) -> Res<String> {
    if action == "drives" {
        let drives: Vec<String> = ('A'..='Z').map(|c| format!("{c}:\\")).filter(|d| fs::exists(d)).collect();
        return Ok(format!("Verfügbare Laufwerke: {}", drives.join(", ")));
    }
    if action == "find_path" {
        if value.is_empty() || value.contains(['\\', '/', ':']) {
            return Ok("Nenne einen Dateinamen ohne Pfad.".into());
        }
        return Ok(find_file(value).await);
    }
    let path = local_path(value)?;
    let is_dir = fs::stat(&path).is_some_and(|s| s.dir);
    match action {
        "open_path" => {
            let ext = extension(&path);
            if !is_dir && ![".txt", ".md", ".pdf", ".png", ".jpg", ".jpeg", ".docx", ".xlsx", ".pptx", ".csv"].contains(&ext.as_str()) {
                return Ok("Diese Datei ist kein unterstütztes Dokument. Programme bitte über ihren App-Namen öffnen.".into());
            }
            host::shell_open(&path);
            Ok(format!("Ich öffne {path}"))
        }
        "list_path" => {
            if !is_dir {
                return Ok("Das ist kein Ordner.".into());
            }
            let entries: Vec<String> =
                fs::list_dir(&path).into_iter().take(50).map(|e| e.name.clone() + if e.dir { " (Ordner)" } else { "" }).collect();
            Ok(format!("Erste bis zu 50 Einträge: {}", entries.join("; ")))
        }
        "read_path" => {
            let ext = extension(&path);
            if ![".txt", ".md", ".csv", ".py", ".js", ".ts", ".html", ".css"].contains(&ext.as_str()) {
                return Ok("Ich kann hier Textdateien und Quellcode vorlesen.".into());
            }
            let bytes = fs::read(&path).ok_or("Die Datei konnte nicht gelesen werden.")?;
            let content = take(&String::from_utf8_lossy(&bytes), 4001);
            // Never read common API credentials aloud or pass them to speech synthesis.
            let content = crate::re!(r"sk-[A-Za-z0-9_-]+").replace_all(&content, "[API-Schlüssel ausgeblendet]").to_string();
            let long = content.chars().count() > 4000;
            Ok(take(&content, 4000) + if long { " … Datei gekürzt." } else { "" })
        }
        _ => Err("Unbekannter PC-Befehl.".into()),
    }
}

/// Bounded search over all drives (8 s, 100 000 folders, 20 hits).
async fn find_file(name: &str) -> String {
    let needle = name.to_lowercase();
    let deadline = host::monotonic() + 8000.0;
    let (mut found, mut count) = (Vec::new(), 0usize);
    for drive in ('A'..='Z').map(|c| format!("{c}:\\")) {
        if !fs::exists(&drive) {
            continue;
        }
        let mut stack = vec![drive];
        while let Some(folder) = stack.pop() {
            count += 1;
            for entry in fs::list_dir(&folder) {
                if entry.dir && !entry.link {
                    stack.push(fs::join(&folder, &entry.name));
                } else if entry.file && entry.name.to_lowercase().contains(&needle) {
                    found.push(fs::join(&folder, &entry.name));
                }
            }
            if host::monotonic() >= deadline || count > 100_000 || found.len() >= 20 {
                found.truncate(20);
                let hits = if found.is_empty() { "bisher keine. Versuche einen genaueren Ordner.".to_string() } else { found.join("; ") };
                return format!("Begrenzte Suche, erste Treffer: {hits}");
            }
            if count % 200 == 0 {
                host::sleep(0.0).await;
            }
        }
    }
    format!("Gefunden: {}", if found.is_empty() { "keine zugängliche Datei dieses Namens.".to_string() } else { found.join("; ") })
}

/// Starts a background Codex job in `project` (fix-self, dashboard).
pub fn start_code(prompt: &str, project: Option<&str>) -> Res<String> {
    codex_executable()?;
    let folder = project.map(local_path).transpose()?;
    Ok(start("code", prompt.to_string(), folder))
}
