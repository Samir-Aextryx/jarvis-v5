//! Resolves spoken app names against Windows's installed Start-menu catalog,
//! focuses running apps and launches verified catalog entries only.

use crate::config;
use crate::desktop;
use crate::host::{self, fs};
use crate::personal;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::cell::{Cell, RefCell};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct App {
    pub name: String,
    pub id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub executable: Option<String>,
}

thread_local! {
    static CACHE: RefCell<Vec<App>> = const { RefCell::new(Vec::new()) };
    static EXPIRES: Cell<f64> = const { Cell::new(0.0) };
    static REFRESHING: Cell<bool> = const { Cell::new(false) };
}

pub const ALIASES: &[(&str, &[&str])] = &[
    ("teams", &["microsoft teams", "teams"]),
    ("chat gpt", &["chatgpt"]),
    ("claude ai", &["claude"]),
    ("claude", &["claude"]),
    ("outlook", &["outlook"]),
    ("outlook classic", &["outlook classic"]),
    ("klassisches outlook", &["outlook classic"]),
    ("whatsapp", &["whatsapp"]),
    ("whats app", &["whatsapp"]),
    ("whats up", &["whatsapp"]),
    ("snapchat", &["snapchat"]),
    ("snap chat", &["snapchat"]),
    ("chrome", &["google chrome"]),
    ("google chrome", &["google chrome"]),
    ("krom", &["google chrome"]),
    ("vpn", &["proton vpn", "mullvad vpn", "forticlient vpn", "nordvpn", "surfshark", "expressvpn"]),
    ("v p n", &["proton vpn", "mullvad vpn", "forticlient vpn", "nordvpn", "surfshark", "expressvpn"]),
    ("proton", &["proton vpn"]),
    ("mullvad", &["mullvad vpn"]),
    ("forti", &["forticlient vpn"]),
    ("forticlient", &["forticlient vpn"]),
    ("calculator", &["rechner", "calculator"]),
    ("rechner", &["rechner", "calculator"]),
    ("notepad", &["editor", "notepad"]),
    ("edge", &["microsoft edge"]),
    ("word", &["word"]),
    ("excel", &["excel"]),
    ("browser", &["google chrome", "microsoft edge", "firefox", "brave"]),
    ("mein browser", &["google chrome", "microsoft edge", "firefox", "brave"]),
];

pub const WEB_FALLBACKS: &[(&str, &str)] = &[
    ("chatgpt", "https://chatgpt.com/"),
    ("chat gpt", "https://chatgpt.com/"),
    ("claude", "https://claude.ai/"),
    ("claude ai", "https://claude.ai/"),
    ("snapchat", "https://web.snapchat.com/"),
    ("snap chat", "https://web.snapchat.com/"),
    ("whatsapp", "https://web.whatsapp.com/"),
    ("whats app", "https://web.whatsapp.com/"),
    ("whats up", "https://web.whatsapp.com/"),
];

const PROCESSES: &[(&str, &[&str])] = &[
    ("outlook", &["olk.exe", "outlook.exe"]),
    ("outlook classic", &["outlook.exe"]),
    ("microsoft teams", &["ms-teams.exe", "teams.exe"]),
    ("teams", &["ms-teams.exe", "teams.exe"]),
    ("whatsapp", &["whatsapp.root.exe"]),
    ("whatsapp beta", &["whatsapp.root.exe"]),
    ("google chrome", &["chrome.exe"]),
    ("chatgpt", &["chatgpt.exe"]),
    ("spotify", &["spotify.exe"]),
    ("paint", &["mspaint.exe"]),
    ("rechner", &["calculatorapp.exe"]),
    ("editor", &["notepad.exe"]),
];

#[cfg(target_arch = "wasm32")]
fn nfkd(text: &str) -> String {
    String::from(js_sys::JsString::from(text).normalize("NFKD"))
}

/// Native unit tests have no JavaScript engine; fold the common Latin accents.
#[cfg(not(target_arch = "wasm32"))]
fn nfkd(text: &str) -> String {
    text.chars()
        .map(|c| match c {
            'à' | 'á' | 'â' | 'ã' | 'ä' | 'å' => 'a',
            'ç' => 'c',
            'è' | 'é' | 'ê' | 'ë' => 'e',
            'ì' | 'í' | 'î' | 'ï' => 'i',
            'ñ' => 'n',
            'ò' | 'ó' | 'ô' | 'õ' | 'ö' => 'o',
            'ù' | 'ú' | 'û' | 'ü' => 'u',
            'ý' | 'ÿ' => 'y',
            other => other,
        })
        .collect()
}

/// Case-, accent- and punctuation-insensitive app name.
pub fn normalize(text: &str) -> String {
    let lowered = text.to_lowercase().replace('ß', "ss");
    let stripped: String = nfkd(&lowered).chars().filter(|c| !is_combining_mark(*c)).collect();
    crate::re!(r"[^\w ]").replace_all(&stripped, " ").split_whitespace().collect::<Vec<_>>().join(" ")
}

fn aliases(query: &str) -> Vec<String> {
    ALIASES
        .iter()
        .find(|(alias, _)| *alias == query)
        .map(|(_, choices)| choices.iter().map(|c| c.to_string()).collect())
        .unwrap_or_else(|| vec![query.to_string()])
}

fn cache_path() -> String {
    config::paths().data_file("data\\installed-apps.json")
}

fn known_folder(marker: &str) -> Option<String> {
    match marker {
        "{6D809377-6AF0-444B-8957-A3773F02200E}" => config::get("PROGRAMW6432").or_else(|| config::get("PROGRAMFILES")),
        "{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}" => config::get("PROGRAMFILES(X86)"),
        _ => None,
    }
}

/// Verified installed executable, rather than starting Explorer for Win32 apps.
async fn direct_executable(app: &App) -> Option<String> {
    for marker in ["{6D809377-6AF0-444B-8957-A3773F02200E}", "{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}"] {
        let prefix = format!("{}\\", marker.to_lowercase());
        if app.id.to_lowercase().starts_with(&prefix)
            && let Some(dir) = known_folder(marker).filter(|d| !d.is_empty())
        {
            let path = fs::join(&dir, &app.id[prefix.len()..]);
            if path.to_lowercase().ends_with(".exe") && fs::stat(&path).is_some_and(|s| s.file) {
                return Some(path);
            }
        }
    }
    let exe = match normalize(&app.name).as_str() {
        "google chrome" => "chrome.exe",
        "outlook classic" => "OUTLOOK.EXE",
        _ => return None,
    };
    desktop::app_path(exe).await
}

async fn catalog_entries(entries: Value) -> Vec<App> {
    let entries = match entries {
        Value::Array(items) => items,
        Value::Object(_) => vec![entries],
        _ => return Vec::new(),
    };
    let mut apps = Vec::new();
    for entry in entries {
        let (Some(name), Some(id)) = (entry["Name"].as_str(), entry["AppID"].as_str()) else { continue };
        if name.trim().is_empty() || id.trim().is_empty() || name.chars().count() > 200 || id.chars().count() > 500
            || name.chars().chain(id.chars()).any(|c| (c as u32) < 32)
        {
            continue;
        }
        let mut app = App { name: name.to_string(), id: id.to_string(), executable: None };
        app.executable = direct_executable(&app).await;
        apps.push(app);
    }
    apps.sort_by_key(|a| a.name.to_lowercase());
    apps
}

async fn read_catalog() -> Vec<App> {
    let path = cache_path();
    match fs::stat(&path) {
        Some(stat) if host::now_ms() - stat.mtime <= 30.0 * 86400.0 * 1000.0 => {}
        _ => return Vec::new(),
    }
    match fs::read_json(&path) {
        Some(v) => catalog_entries(v).await,
        None => Vec::new(),
    }
}

async fn query_catalog() -> Result<Vec<App>, String> {
    let raw = desktop::run_powershell("Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress", 15000).await?;
    let entries: Value = serde_json::from_str(if raw.trim().is_empty() { "[]" } else { raw.trim() }).map_err(|e| e.to_string())?;
    let apps = catalog_entries(entries).await;
    if !apps.is_empty() {
        let list: Vec<Value> = apps.iter().map(|a| json!({ "Name": a.name, "AppID": a.id })).collect();
        // A read-only data directory must not prevent launching apps.
        let _ = fs::write_text(&cache_path(), &Value::Array(list).to_string());
    }
    Ok(apps)
}

/// A fresh catalog scan, bypassing the cache.
pub(crate) async fn refreshed_apps() -> Vec<App> {
    refresh().await.unwrap_or_default()
}

async fn refresh() -> Result<Vec<App>, String> {
    REFRESHING.with(|r| r.set(true));
    let result = query_catalog().await;
    REFRESHING.with(|r| r.set(false));
    match &result {
        Ok(apps) => {
            CACHE.with(|c| *c.borrow_mut() = apps.clone());
            EXPIRES.with(|e| e.set(host::monotonic() + 120_000.0));
        }
        Err(_) => EXPIRES.with(|e| e.set(host::monotonic() + 30_000.0)),
    }
    result
}

/// The installed-app catalog; refreshed in the background every two minutes.
pub async fn installed_apps() -> Vec<App> {
    if CACHE.with(|c| c.borrow().is_empty()) {
        let cached = read_catalog().await;
        CACHE.with(|c| *c.borrow_mut() = cached);
    }
    let cached = CACHE.with(|c| c.borrow().clone());
    if !cached.is_empty() {
        if host::monotonic() >= EXPIRES.with(|e| e.get()) && !REFRESHING.with(|r| r.get()) {
            wasm_bindgen_futures::spawn_local(async {
                let _ = refresh().await;
            });
        }
        return cached;
    }
    if REFRESHING.with(|r| r.get()) {
        for _ in 0..300 {
            host::sleep(50.0).await;
            if !REFRESHING.with(|r| r.get()) {
                break;
            }
        }
        return CACHE.with(|c| c.borrow().clone());
    }
    refresh().await.unwrap_or_default()
}

pub fn resolve_app(target: &str, apps: &[App]) -> Vec<App> {
    let query = normalize(target);
    let choices = aliases(&query);
    let exact: Vec<App> = apps.iter().filter(|a| choices.contains(&normalize(&a.name))).cloned().collect();
    if !exact.is_empty() {
        return exact;
    }
    // Full words only; never launch a different app from an arbitrary substring.
    let matches: Vec<App> = apps
        .iter()
        .filter(|a| {
            let name = format!(" {} ", normalize(&a.name));
            choices.iter().any(|q| !q.is_empty() && name.contains(&format!(" {q} ")))
        })
        .cloned()
        .collect();
    if !matches.is_empty() {
        return matches;
    }
    // Drop a spoken article only after the full phrase matched nothing.
    let bare = crate::re!(r"^(?:the|my|der|die|das|den|dem|mein(?:e[nmrs]?)?)\s+(\S.*)$").replace(&query, "$1").to_string();
    if bare != query { resolve_app(&bare, apps) } else { Vec::new() }
}

/// One spoken app (or several) to open, or None.
pub fn parse_open_request(text: &str) -> Option<Vec<String>> {
    let text = text.trim().trim_matches(['.', '!', '?']);
    let text = crate::re!(r"(?i)^(?:hey\s+)?jarvis[, ]+").replace(text, "");
    let text = crate::re!(r"(?i)^(?:(?:kannst|konntest|könntest|würdest) du|can you|could you)\s+").replace(&text, "");
    let text = crate::re!(r"(?i)^bitte\s+|^please\s+").replace(&text, "").to_string();
    let target = crate::re!(r"(?i)^(?:öffne|offne|oeffne|starte|start|open|launch|öffnen)\s+(.+)$")
        .captures(&text)
        .or_else(|| crate::re!(r"(?i)^(.+?)\s+(?:öffnen|offnen|oeffnen|starten|aufmachen)$").captures(&text))
        .or_else(|| crate::re!(r"(?i)^mach(?:e)?\s+(.+?)\s+auf$").captures(&text))?[1]
        .to_string();
    let target = crate::re!(r"(?i)\b(?:bitte|please|für mich|for me|die app|das programm)\b").replace_all(&target, "");
    let target = crate::re!(r"(?i)^(?:(?:mir|uns|mal|doch|kurz|einmal)\s+)+").replace(target.trim(), "").to_string();
    let target = if crate::re!(r"(?i)^(?:(?:the|my|mein(?:e[nr]?)?|das|die|microsoft)\s+)*outlook(?:[\s-]+(?:mail|email|e-mail|app|application|programm))?$").is_match(&target) {
        "Outlook".to_string()
    } else {
        target
    };
    if target.is_empty() || target.chars().count() > 100 {
        return None;
    }
    if crate::re!(r"(?i)\b(?:write|send|prompt|tell|read|check|search|find|review|draft|compose|reply|summari[sz]e|schreibe|schreib|sende|lies|lese|suche|prüfe|pruefe|verfasse|antworte|zusammenfasse)\b").is_match(&target) {
        return None;
    }
    if crate::re!(r"(?i)https?://|www\.|[\w-]+\.(?:com|de|ch|org|net)\b|\b(?:datei|ordner|projekt\w*|website|webseite|file|folder|project)\b").is_match(&target) {
        return None;
    }
    let targets: Vec<String> = crate::re!(r"(?i)\s+and\s+|\s+und\s+|\s+then\s+|\s+danach\s+|,")
        .split(&target)
        .map(str::trim)
        .filter(|t| !t.is_empty())
        .map(|t| crate::re!(r"(?i)^(?:öffne|offne|oeffne|starte|start|open|launch)\s+").replace(t, "").to_string())
        .collect();
    if targets.is_empty() { None } else { Some(targets) }
}

pub fn parse_app_preference(text: &str) -> Option<(String, String)> {
    let text = text.trim();
    [
        crate::re!(r"(?i)^(?:remember(?: that)?[:, ]+)?(.{1,60}?) means (.{1,80}?)[.!?]*$"),
        crate::re!(r"(?i)^when i say (.{1,60}?)[, ]+(?:please )?open (.{1,80}?)[.!?]*$"),
        crate::re!(r"(?i)^(?:merke? dir[:, ]+)?mit (.{1,60}?) meine ich (.{1,80}?)[.!?]*$"),
    ]
    .iter()
    .find_map(|re| re.captures(text))
    .map(|m| (m[1].trim_matches([' ', '"']).to_string(), m[2].trim_matches([' ', '"']).to_string()))
}

/// difflib.SequenceMatcher(None, a, b).ratio() for short strings.
pub fn similarity(a: &str, b: &str) -> f64 {
    fn matches(a: &[char], b: &[char]) -> usize {
        let (mut best, mut ai, mut bj) = (0usize, 0usize, 0usize);
        let mut prev = vec![0usize; b.len() + 1];
        for i in 0..a.len() {
            let mut cur = vec![0usize; b.len() + 1];
            for j in 0..b.len() {
                if a[i] == b[j] {
                    cur[j + 1] = prev[j] + 1;
                    if cur[j + 1] > best {
                        best = cur[j + 1];
                        ai = i + 1 - best;
                        bj = j + 1 - best;
                    }
                }
            }
            prev = cur;
        }
        if best == 0 {
            return 0;
        }
        best + matches(&a[..ai], &b[..bj]) + matches(&a[ai + best..], &b[bj + best..])
    }
    let (a, b): (Vec<char>, Vec<char>) = (a.chars().collect(), b.chars().collect());
    if a.is_empty() && b.is_empty() {
        return 1.0;
    }
    2.0 * matches(&a, &b) as f64 / (a.len() + b.len()) as f64
}

pub fn suggested_apps(target: &str, apps: &[App]) -> Vec<App> {
    let query = normalize(target).replace(' ', "");
    if query.chars().count() < 4 || !crate::re!(r"^[\w .-]{1,100}$").is_match(target) {
        return Vec::new();
    }
    let mut ranked: Vec<(f64, App)> = apps
        .iter()
        .filter_map(|app| {
            let normalized = normalize(&app.name);
            let mut names = vec![app.name.clone()];
            names.extend(ALIASES.iter().filter(|(_, c)| c.contains(&normalized.as_str())).map(|(a, _)| a.to_string()));
            let score = names.iter().map(|n| similarity(&query, &normalize(n).replace(' ', ""))).fold(0.0, f64::max);
            (score >= 0.72).then(|| (score, app.clone()))
        })
        .collect();
    ranked.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
    ranked.into_iter().take(3).map(|(_, a)| a).collect()
}

pub async fn save_app_preference(alias: &str, target: &str) -> String {
    let apps = installed_apps().await;
    let matches = resolve_app(target, &apps);
    if matches.len() != 1 {
        return "Please give the exact installed app name for this preference.".into();
    }
    let app = json!({ "id": matches[0].id, "name": matches[0].name });
    match personal::remember_app(&normalize(alias), &app) {
        Ok(()) => format!("Remembered: {alias} means {}.", matches[0].name),
        Err(e) => e,
    }
}

#[derive(Debug, Clone, Default)]
pub struct OpenResult {
    pub success: bool,
    pub state: String,
    pub app: Option<String>,
    pub confirmation: String,
    pub candidates: Vec<App>,
    pub preference_key: Option<String>,
}

impl OpenResult {
    fn fail(confirmation: impl Into<String>) -> Self {
        Self { confirmation: confirmation.into(), ..Default::default() }
    }
}

fn allowed_processes(app: &App) -> Vec<String> {
    let mut allowed: Vec<String> = PROCESSES
        .iter()
        .find(|(name, _)| *name == normalize(&app.name))
        .map(|(_, p)| p.iter().map(|s| s.to_string()).collect())
        .unwrap_or_default();
    if let Some(exe) = &app.executable {
        allowed.push(fs::file_name(exe).to_lowercase());
    }
    allowed
}

/// Distinguishes Store editions even when their process names are identical.
fn window_matches(window: &desktop::Window, app: &App, allowed: &[String]) -> bool {
    let Some(image) = window.image_name() else { return false };
    if !allowed.contains(&image) {
        return false;
    }
    if ["whatsapp", "whatsapp beta"].contains(&normalize(&app.name).as_str()) {
        let package = app.id.split('_').next().unwrap_or("").to_lowercase();
        let path = window.path.as_deref().unwrap_or("").replace('/', "\\").to_lowercase();
        return !package.is_empty() && path.contains(&format!("\\{package}_"));
    }
    true
}

pub async fn app_windows(app: &App) -> Vec<desktop::Window> {
    let allowed = allowed_processes(app);
    if allowed.is_empty() {
        return Vec::new();
    }
    desktop::windows(false).await.unwrap_or_default().into_iter().filter(|w| window_matches(w, app, &allowed)).collect()
}

pub(crate) async fn focus_existing(app: &App) -> Option<OpenResult> {
    let found = app_windows(app).await;
    if let Some(fg) = found.iter().find(|w| w.foreground) {
        let _ = fg;
        return Some(OpenResult { success: true, state: "focused".into(), confirmation: format!("Focused {}.", app.name), ..Default::default() });
    }
    let window = found.first()?;
    let focused = desktop::focus(window.hwnd).await;
    Some(OpenResult {
        success: focused,
        state: if focused { "focused" } else { "already_running" }.into(),
        confirmation: format!("{}{}.", if focused { "Focused " } else { "Already running, but Windows did not allow me to focus " }, app.name),
        ..Default::default()
    })
}

pub async fn verify_started(app: &App, timeout_ms: f64) -> bool {
    let deadline = host::monotonic() + timeout_ms;
    while host::monotonic() < deadline {
        if !app_windows(app).await.is_empty() {
            return true;
        }
        host::sleep(25.0).await;
    }
    false
}

fn launch(app: &App) -> bool {
    if let Some(exe) = &app.executable {
        return host::spawn_detached(exe, &[], json!({}));
    }
    // Only a catalog-derived ID reaches the shell, never the user's raw text.
    let explorer = format!("{}\\explorer.exe", config::get_or("SYSTEMROOT", "C:\\Windows"));
    host::spawn_detached(&explorer, &[&format!("shell:AppsFolder\\{}", app.id)], json!({}))
}

pub struct OpenOptions<'a> {
    pub candidates: Option<&'a [App]>,
    pub remember_as: Option<&'a str>,
    pub wait_until_ready: bool,
}

impl Default for OpenOptions<'_> {
    fn default() -> Self {
        Self { candidates: None, remember_as: None, wait_until_ready: false }
    }
}

/// Opens several apps concurrently.
pub async fn open_apps(targets: &[String], options: OpenOptions<'_>) -> OpenResult {
    if targets.len() == 1 {
        return open_app(&targets[0], options).await;
    }
    let results = futures::future::join_all(targets.iter().map(|t| {
        open_app(t, OpenOptions { candidates: options.candidates, remember_as: options.remember_as, wait_until_ready: options.wait_until_ready })
    }))
    .await;
    let successes: Vec<String> = results.iter().filter(|r| r.success).filter_map(|r| r.app.clone()).collect();
    let failures: Vec<&str> = targets.iter().zip(&results).filter(|(_, r)| !r.success).map(|(t, _)| t.as_str()).collect();
    if successes.is_empty() {
        return OpenResult::fail("None of the apps could be started.");
    }
    let mut confirmation = format!("Opening {}.", successes.join(" and "));
    if !failures.is_empty() {
        confirmation.push_str(&format!(" I couldn't find {}.", failures.join(", ")));
    }
    OpenResult { success: failures.is_empty(), app: Some(successes.join(", ")), confirmation, ..Default::default() }
}

pub async fn open_app(target: &str, options: OpenOptions<'_>) -> OpenResult {
    let apps = match options.candidates {
        Some(c) => c.to_vec(),
        None => installed_apps().await,
    };
    if apps.is_empty() && options.candidates.is_none() {
        return OpenResult::fail("I couldn't read the Windows app list. Please try again.");
    }
    let mut matches = resolve_app(target, &apps);
    if options.candidates.is_none()
        && let Some(saved) = personal::app_choice(&normalize(target))
    {
        let chosen: Vec<App> = apps.iter().filter(|a| a.id == saved["app_id"].as_str().unwrap_or("")).cloned().collect();
        if chosen.len() == 1 {
            matches = chosen;
        }
    }
    if matches.is_empty() {
        let suggestions = suggested_apps(target, &apps);
        if !suggestions.is_empty() {
            let names: Vec<&str> = suggestions.iter().map(|a| a.name.as_str()).collect();
            return OpenResult {
                confirmation: format!("Which app did you mean: {}? Please say the app name.", names.join(", ")),
                candidates: suggestions,
                preference_key: Some(target.to_string()),
                ..Default::default()
            };
        }
        let web = if options.candidates.is_none() {
            WEB_FALLBACKS.iter().find(|(k, _)| *k == normalize(target)).map(|(_, u)| *u)
        } else {
            None
        };
        if let Some(url) = web {
            let name = [("chatgpt.com", "ChatGPT"), ("claude.ai", "Claude"), ("snapchat", "Snapchat"), ("whatsapp", "WhatsApp")]
                .iter()
                .find(|(f, _)| url.contains(f))
                .map(|(_, l)| l.to_string())
                .unwrap_or_else(|| target.to_string());
            if crate::websites::open_in_chrome(url).await.is_err() {
                return OpenResult::fail(format!("I couldn't find {name} installed or open its web version because Chrome isn't available."));
            }
            return OpenResult {
                success: true,
                state: "launching".into(),
                confirmation: format!("Opening {name} in Chrome (web version)."),
                app: Some(name),
                ..Default::default()
            };
        }
        return OpenResult::fail(format!("I can't find an installed app called {target}."));
    }
    if matches.len() > 1 {
        let names: Vec<&str> = matches.iter().take(8).map(|a| a.name.as_str()).collect();
        return OpenResult {
            confirmation: format!("Which app do you mean: {}?", names.join(", ")),
            candidates: matches,
            preference_key: Some(target.to_string()),
            ..Default::default()
        };
    }
    let app = &matches[0];
    let remember = |alias: Option<&str>| {
        if let Some(alias) = alias {
            let _ = personal::remember_app(&normalize(alias), &json!({ "id": app.id, "name": app.name }));
        }
    };
    if let Some(mut existing) = focus_existing(app).await {
        if existing.success {
            remember(options.remember_as);
        }
        existing.app = Some(app.name.clone());
        return existing;
    }
    if !launch(app) {
        return OpenResult::fail("The app could not be started. Please try again.");
    }
    if options.wait_until_ready && !verify_started(app, 2000.0).await {
        return OpenResult {
            state: "unverified".into(),
            app: Some(app.name.clone()),
            confirmation: format!("Launch requested for {}, but no app window was verified. I did not launch it again.", app.name),
            ..Default::default()
        };
    }
    remember(options.remember_as);
    OpenResult {
        success: true,
        state: if options.wait_until_ready { "ready" } else { "launching" }.into(),
        confirmation: if options.wait_until_ready { format!("Opened {}.", app.name) } else { format!("Opening {}.", app.name) },
        app: Some(app.name.clone()),
        ..Default::default()
    }
}

/// Warm the catalog at startup so the first "open" is fast.
pub fn warm() {
    wasm_bindgen_futures::spawn_local(async {
        if installed_apps().await.is_empty() {
            crate::warn!("The Windows app list will be loaded again when an app is first opened.");
        }
    });
}

fn is_combining_mark(c: char) -> bool {
    matches!(c as u32, 0x0300..=0x036F | 0x1AB0..=0x1AFF | 0x1DC0..=0x1DFF | 0x20D0..=0x20FF | 0xFE20..=0xFE2F)
}
