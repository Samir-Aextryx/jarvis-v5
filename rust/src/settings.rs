//! AI providers, agent preferences, `.env` values, keys and usage tracking.

use crate::config;
use crate::host::{self, Res, fs};
use crate::util::{LocalTime, utc_iso};
use crate::vault;
use serde_json::{Map, Value, json};
use std::cell::RefCell;

// ---- providers -----------------------------------------------------------------

pub struct Provider {
    pub id: &'static str,
    pub label: &'static str,
    pub key_name: &'static str,
    pub model_variable: &'static str,
    pub default_model: &'static str,
    pub endpoint: &'static str,
}

pub const PROVIDERS: [Provider; 4] = [
    Provider { id: "openai", label: "OpenAI", key_name: "OPENAI_API_KEY", model_variable: "OPENAI_MODEL", default_model: "gpt-6-luna", endpoint: "https://api.openai.com/v1/responses" },
    Provider { id: "gemini", label: "Gemini", key_name: "GEMINI_API_KEY", model_variable: "GEMINI_MODEL", default_model: "gemini-3.8-flash", endpoint: "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions" },
    Provider { id: "grok", label: "Grok", key_name: "XAI_API_KEY", model_variable: "GROK_MODEL", default_model: "grok-4.7", endpoint: "https://api.x.ai/v1/chat/completions" },
    Provider { id: "ollama", label: "Ollama Cloud", key_name: "OLLAMA_API_KEY", model_variable: "OLLAMA_MODEL", default_model: "gpt-oss:120b", endpoint: "https://ollama.com/v1/chat/completions" },
];
pub const PROVIDER_CHOICE_ERROR: &str = "Choose OpenAI, Gemini, Grok or Ollama Cloud as the AI provider.";

/// Resolves a supported provider; never silently falls back or changes destination.
pub fn provider_config(name: Option<&str>) -> Res<&'static Provider> {
    let name = name.map(str::to_string).unwrap_or_else(|| config::get_or("LLM_PROVIDER", "openai")).trim().to_lowercase();
    PROVIDERS.iter().find(|p| p.id == name).ok_or_else(|| PROVIDER_CHOICE_ERROR.to_string())
}
pub fn active_provider() -> &'static Provider {
    provider_config(None).unwrap_or(&PROVIDERS[0])
}

pub fn validate_model(model: &str) -> Res<String> {
    // Ollama names a model version with a tag, e.g. deepseek-v4.1-flash:1017.
    if crate::re!(r"^[A-Za-z0-9._-]{1,100}(?::[A-Za-z0-9._-]{1,50})?$").is_match(model) {
        Ok(model.to_string())
    } else {
        Err("Enter a valid model identifier.".into())
    }
}

pub fn provider_model(provider: &Provider) -> Res<String> {
    validate_model(&config::get_or(provider.model_variable, provider.default_model))
}

pub fn apply_provider_settings(settings: &Value) {
    config::set("LLM_PROVIDER", settings["llm_provider"].as_str().unwrap_or("openai"));
    config::set("OPENAI_MODEL", settings["large_model"].as_str().unwrap_or("gpt-6-luna"));
    config::set("GEMINI_MODEL", settings["gemini_model"].as_str().unwrap_or(PROVIDERS[1].default_model));
    config::set("GROK_MODEL", settings["grok_model"].as_str().unwrap_or(PROVIDERS[2].default_model));
    config::set("OLLAMA_MODEL", settings["ollama_model"].as_str().unwrap_or(PROVIDERS[3].default_model));
    config::set("OPENAI_REASONING_EFFORT", settings["reasoning_effort"].as_str().unwrap_or("low"));
}

/// Public model/key-presence metadata, never API keys.
pub fn provider_status() -> Value {
    let active = active_provider().id;
    let choices: Vec<Value> = PROVIDERS
        .iter()
        .map(|p| {
            json!({ "id": p.id, "name": p.label, "model": provider_model(p).unwrap_or_else(|_| p.default_model.into()),
                    "configured": !vault::get(p.key_name).is_empty() })
        })
        .collect();
    let selected = choices.iter().find(|c| c["id"] == active).cloned().unwrap_or(Value::Null);
    json!({ "provider": active, "model": selected["model"], "available": selected["configured"], "providers": choices })
}

// ---- agent settings (agent-settings.json) ------------------------------------------

pub const ACTIVITY_TOOLS: [&str; 3] = ["apps.open", "personal.update", "workflow"];

pub fn defaults() -> Map<String, Value> {
    let mut m = Map::new();
    m.insert("work_apps".into(), json!(["Outlook", "Microsoft Teams", "Google Chrome", "ChatGPT"]));
    m.insert("automation".into(), json!(true));
    m.insert("activity_log".into(), json!(true));
    m.insert("large_model".into(), json!(config::get_or("OPENAI_MODEL", "gpt-6-luna")));
    m.insert("llm_provider".into(), json!(config::get_or("LLM_PROVIDER", "openai")));
    m.insert("gemini_model".into(), json!(config::get_or("GEMINI_MODEL", PROVIDERS[1].default_model)));
    m.insert("grok_model".into(), json!(config::get_or("GROK_MODEL", PROVIDERS[2].default_model)));
    m.insert("ollama_model".into(), json!(config::get_or("OLLAMA_MODEL", PROVIDERS[3].default_model)));
    m.insert("reasoning_effort".into(), json!(config::get_or("OPENAI_REASONING_EFFORT", "low")));
    m.insert("default_email".into(), json!("Gmail"));
    m
}

thread_local! {
    // The startup defaults, captured before settings are applied to the environment.
    static DEFAULTS: RefCell<Option<Map<String, Value>>> = const { RefCell::new(None) };
}

fn base_defaults() -> Map<String, Value> {
    DEFAULTS.with(|d| d.borrow_mut().get_or_insert_with(defaults).clone())
}

fn settings_path() -> String {
    config::paths().data_file("agent-settings.json")
}
fn activity_path() -> String {
    config::paths().data_file("data\\agent-activity.json")
}

pub fn validated(data: &Map<String, Value>) -> Res<Map<String, Value>> {
    let known = base_defaults();
    if data.keys().any(|k| !known.contains_key(k)) {
        return Err("Unknown agent setting.".into());
    }
    let mut data = data.clone();
    if let Some(apps) = data.get("work_apps") {
        let list = apps.as_array().ok_or("Enter up to 20 installed app names, one per line.")?;
        let re = crate::re!(r"^[\w .()+-]{1,80}$");
        if list.len() > 20 || list.iter().any(|a| !a.as_str().is_some_and(|s| re.is_match(s.trim()))) {
            return Err("Enter up to 20 installed app names, one per line.".into());
        }
        let mut unique: Vec<String> = Vec::new();
        for a in list {
            let a = a.as_str().unwrap_or_default().trim().to_string();
            if !unique.contains(&a) {
                unique.push(a);
            }
        }
        data.insert("work_apps".into(), json!(unique));
    }
    for name in ["automation", "activity_log"] {
        if data.get(name).is_some_and(|v| !v.is_boolean()) {
            return Err("Use a checkbox for this setting.".into());
        }
    }
    if let Some(m) = data.get("large_model")
        && !m.as_str().is_some_and(|s| crate::re!(r"^[a-zA-Z0-9._-]{1,80}$").is_match(s))
    {
        return Err("Enter a valid model identifier.".into());
    }
    if let Some(p) = data.get("llm_provider")
        && !p.as_str().is_some_and(|s| PROVIDERS.iter().any(|x| x.id == s))
    {
        return Err(PROVIDER_CHOICE_ERROR.into());
    }
    for name in ["gemini_model", "grok_model", "ollama_model"] {
        if let Some(m) = data.get(name) {
            validate_model(m.as_str().ok_or("Enter a valid model identifier.")?)?;
        }
    }
    if let Some(e) = data.get("reasoning_effort")
        && !e.as_str().is_some_and(|s| ["none", "low", "medium", "high", "xhigh", "max"].contains(&s))
    {
        return Err("Choose a supported reasoning effort.".into());
    }
    if let Some(e) = data.get("default_email")
        && !e.as_str().is_some_and(|s| s == "Gmail" || s == "Outlook")
    {
        return Err("Choose Gmail or Outlook.".into());
    }
    Ok(data)
}

pub fn get() -> Map<String, Value> {
    let mut values = base_defaults();
    if let Some(Value::Object(stored)) = fs::read_json(&settings_path()) {
        for (k, v) in stored {
            let mut one = Map::new();
            one.insert(k, v);
            if let Ok(ok) = validated(&one) {
                values.extend(ok);
            }
        }
    }
    values
}

pub fn automation_enabled() -> bool {
    get().get("automation").and_then(Value::as_bool).unwrap_or(true)
}
pub fn default_email() -> String {
    get().get("default_email").and_then(Value::as_str).unwrap_or("Gmail").to_string()
}

pub fn save(data: &Value) -> Res<Map<String, Value>> {
    let data = data.as_object().ok_or("Unknown agent setting.")?;
    let mut values = get();
    values.extend(validated(data)?);
    fs::write_text(&settings_path(), &serde_json::to_string_pretty(&values).unwrap_or_default())?;
    Ok(values)
}

pub fn activity_logs() -> Vec<Value> {
    let Some(Value::Array(rows)) = fs::read_json(&activity_path()) else { return Vec::new() };
    let start = rows.len().saturating_sub(200);
    rows[start..]
        .iter()
        .filter(|r| {
            r.as_object().is_some_and(|o| {
                o.len() == 4
                    && o.get("time").is_some_and(Value::is_string)
                    && o.get("tool").and_then(Value::as_str).is_some_and(|t| ACTIVITY_TOOLS.contains(&t))
                    && o.get("success").is_some_and(Value::is_boolean)
                    && o.get("count").is_some_and(Value::is_i64)
            })
        })
        .cloned()
        .collect()
}

/// Records fixed tool names and counts only, never requests or results.
pub fn activity(tool: &str, success: bool, count: i64) {
    if !ACTIVITY_TOOLS.contains(&tool) || !get().get("activity_log").and_then(Value::as_bool).unwrap_or(true) {
        return;
    }
    let mut rows = activity_logs();
    rows.push(json!({ "time": utc_iso(), "tool": tool, "success": success, "count": count }));
    let start = rows.len().saturating_sub(200);
    let _ = fs::write_text(&activity_path(), &Value::Array(rows[start..].to_vec()).to_string());
}

pub fn clear_activity() {
    let _ = fs::write_text(&activity_path(), "[]");
}

pub async fn startup() {
    let _ = base_defaults();
    apply_provider_settings(&Value::Object(get()));
}

// ---- .env ------------------------------------------------------------------------------

fn env_path() -> String {
    config::paths().data_file(".env")
}

/// Reads `.env` (created from `.env.example` when missing).
pub fn read_env() -> (Vec<String>, Map<String, Value>) {
    let path = env_path();
    if !fs::exists(&path) {
        let example = fs::read(&fs::join(&config::paths().resources, ".env.example")).unwrap_or_default();
        let _ = fs::write(&path, &example);
    }
    let text = fs::read_text(&path).unwrap_or_default();
    let lines: Vec<String> = text.lines().map(str::to_string).collect();
    let mut parsed = Map::new();
    for (k, v) in config::parse_env(&text) {
        parsed.insert(k, Value::String(v));
    }
    (lines, parsed)
}

fn write_env_lines(lines: &[String]) -> Res<()> {
    fs::write_text(&env_path(), &(lines.join("\n") + "\n"))
}

fn line_key(line: &str) -> Option<String> {
    let stripped = line.trim();
    if stripped.is_empty() || stripped.starts_with('#') {
        return None;
    }
    stripped.split_once('=').map(|(k, _)| k.trim().to_string())
}

/// Updates one key in the vault or `.env`, preserving comments and order.
pub async fn write_env_key(key: &str, value: &str) -> Res<()> {
    if value.contains(['\r', '\n', '\0']) {
        return Err("Configuration values must be single-line".into());
    }
    if vault::SECURE_KEY_NAMES.contains(&key) {
        vault::set(key, value, matches!(key, "GEMINI_API_KEY" | "XAI_API_KEY" | "OLLAMA_API_KEY")).await?;
        let (lines, _) = read_env();
        let lines: Vec<String> = lines
            .into_iter()
            .map(|l| if line_key(&l).as_deref() == Some(key) { format!("# {key} is securely stored in Windows Credential Manager") } else { l })
            .collect();
        return write_env_lines(&lines);
    }
    let (lines, _) = read_env();
    let mut found = false;
    let mut out: Vec<String> = lines
        .into_iter()
        .map(|l| {
            if line_key(&l).as_deref() == Some(key) {
                found = true;
                format!("{key}={value}")
            } else {
                l
            }
        })
        .collect();
    if !found {
        out.push(format!("{key}={value}"));
    }
    write_env_lines(&out)?;
    config::set(key, value);
    Ok(())
}

// ---- usage ------------------------------------------------------------------------------

thread_local! {
    static SESSION: RefCell<[u64; 4]> = const { RefCell::new([0; 4]) }; // input, output, api_calls, tts_calls
}

fn usage_path() -> String {
    config::paths().data_file("data\\usage_log.jsonl")
}

fn append_usage(input: u64, output: u64, kind: &str) {
    let path = usage_path();
    if fs::stat(&path).is_some_and(|s| s.size > 5_000_000) {
        let rotated = format!("{path}.1");
        fs::remove(&rotated);
        let _ = fs::rename(&path, &rotated);
    }
    let entry = json!({ "ts": host::now_secs(), "date": LocalTime::now().date(), "type": kind,
                        "input_tokens": input, "output_tokens": output });
    let _ = fs::append(&path, format!("{entry}\n").as_bytes());
}

pub fn track_usage(input: u64, output: u64) {
    SESSION.with(|s| {
        let mut s = s.borrow_mut();
        s[0] += input;
        s[1] += output;
        s[2] += 1;
    });
    append_usage(input, output, "api");
}

pub fn track_tts() {
    SESSION.with(|s| s.borrow_mut()[3] += 1);
    append_usage(0, 0, "tts");
}

fn cost(input: u64, output: u64) -> f64 {
    let price = |name: &str, default: f64| config::get(name).and_then(|v| v.trim().parse().ok()).unwrap_or(default);
    input as f64 / 1e6 * price("OPENAI_INPUT_PRICE", 0.40) + output as f64 / 1e6 * price("OPENAI_OUTPUT_PRICE", 1.60)
}

/// Sums usage for several periods in one pass over the log.
fn usage_periods(periods: &[(&str, Option<f64>)]) -> Vec<[u64; 4]> {
    let now = host::now_secs();
    let mut totals = vec![[0u64; 4]; periods.len()];
    let text = fs::read_text(&usage_path()).unwrap_or_default();
    for line in text.lines().filter(|l| !l.trim().is_empty()) {
        let Ok(entry) = serde_json::from_str::<Value>(line) else { continue };
        let ts = entry["ts"].as_f64().unwrap_or(0.0);
        for (i, (_, seconds)) in periods.iter().enumerate() {
            if ts < seconds.map(|s| now - s).unwrap_or(0.0) {
                continue;
            }
            totals[i][0] += entry["input_tokens"].as_u64().unwrap_or(0);
            totals[i][1] += entry["output_tokens"].as_u64().unwrap_or(0);
            if entry["type"] == "tts" {
                totals[i][3] += 1;
            } else {
                totals[i][2] += 1;
            }
        }
    }
    totals
}

pub fn usage_json() -> Value {
    let periods = [("today", Some(86400.0)), ("week", Some(86400.0 * 7.0)), ("month", Some(86400.0 * 30.0)), ("all_time", None)];
    let totals = usage_periods(&periods);
    let s = SESSION.with(|s| *s.borrow());
    let mut result = Map::new();
    result.insert(
        "session".into(),
        json!({ "input": s[0], "output": s[1], "api_calls": s[2], "tts_calls": s[3], "uptime_seconds": crate::uptime() as u64 }),
    );
    for (i, (name, _)) in periods.iter().enumerate() {
        let t = totals[i];
        result.insert(
            (*name).into(),
            json!({ "input_tokens": t[0], "output_tokens": t[1], "api_calls": t[2], "tts_calls": t[3],
                    "cost_usd": (cost(t[0], t[1]) * 10000.0).round() / 10000.0 }),
        );
    }
    Value::Object(result)
}

/// Voice-friendly usage summary.
pub fn usage_summary() -> String {
    let uptime_min = (crate::uptime() / 60.0) as u64;
    let s = SESSION.with(|s| *s.borrow());
    let t = usage_periods(&[("today", Some(86400.0)), ("all", None)]);
    let (today, all) = (t[0], t[1]);
    let mut parts = vec![format!("This session: {uptime_min} minutes, {} calls, ${:.2}.", s[2], cost(s[0], s[1]))];
    if today[2] > s[2] {
        parts.push(format!("Today total: {} calls, ${:.2}.", today[2], cost(today[0], today[1])));
    }
    if all[2] > today[2] {
        parts.push(format!("All time: {} calls, ${:.2}.", all[2], cost(all[0], all[1])));
    }
    parts.join(" ")
}

// ---- Fish voice --------------------------------------------------------------------------

pub const DEFAULT_FISH_VOICE_ID: &str = "612b878b113047d9a770c069c8b4fdfe";

pub fn fish_voice_id() -> String {
    config::get_or("FISH_VOICE_ID", DEFAULT_FISH_VOICE_ID)
}
pub fn fish_model() -> String {
    config::get_or("FISH_MODEL", "s2.1-pro-free")
}
pub fn fish_latency() -> String {
    let latency = config::get_or("FISH_LATENCY", "balanced");
    if ["normal", "balanced", "low"].contains(&latency.as_str()) { latency } else { "balanced".into() }
}
