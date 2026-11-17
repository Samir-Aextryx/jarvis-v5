//! Local AI through Ollama: one-click install of the official, signed package
//! (winget), start, Hugging Face GGUF search, downloads with progress and the
//! model choice. Ollama listens only on 127.0.0.1; Jarvis never runs model
//! output, and no own executable is involved, so Smart App Control stays on.

use crate::config;
use crate::host::{self, Http, Res, fs};
use crate::settings;
use serde_json::{Value, json};
use std::cell::RefCell;
use std::collections::HashMap;

const OLLAMA: &str = "http://127.0.0.1:11434";
const HF: &str = "https://huggingface.co";

/// Tested picks for voice replies, from small to large.
const RECOMMENDED: [(&str, &str, &str, f64, &str); 4] = [
    ("lmstudio-community/Qwen3-4B-Instruct-2507-GGUF", "Q4_K_M", "Qwen3 4B Instruct", 2.5, "Fast spoken replies. Needs about 6 GB of RAM."),
    ("Qwen/Qwen3-8B-GGUF", "Q4_K_M", "Qwen3 8B", 5.0, "Smarter, a little slower. Needs about 10 GB of RAM."),
    ("ggml-org/gpt-oss-20b-GGUF", "MXFP4", "GPT-OSS 20B", 12.1, "Strongest choice. Needs 16 GB of RAM or a large graphics card."),
    ("Qwen/Qwen2.5-1.5B-Instruct-GGUF", "Q4_K_M", "Qwen2.5 1.5B Instruct", 1.1, "Smallest and quickest, for older PCs."),
];

struct State {
    install: Value,
    pull: Value,
    thinking: HashMap<String, bool>,
}

thread_local! {
    static STATE: RefCell<State> = RefCell::new(State {
        install: json!({ "state": "idle" }),
        pull: json!({ "state": "idle" }),
        thinking: HashMap::new(),
    });
}

fn set_install(state: &str, message: &str) {
    STATE.with(|s| s.borrow_mut().install = json!({ "state": state, "message": message }));
}
fn set_pull(value: Value) {
    STATE.with(|s| s.borrow_mut().pull = value);
}
fn pull_state() -> Value {
    STATE.with(|s| s.borrow().pull.clone())
}

// ---- names -----------------------------------------------------------------------

/// An Ollama model name: `name[:tag]` or `hf.co/owner/repo[:quant]`.
pub fn validate_model(model: &str) -> Res<String> {
    let model = model.trim();
    if crate::re!(r"^(?:hf\.co/[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}|[A-Za-z0-9][A-Za-z0-9._-]{0,99}(?:/[A-Za-z0-9][A-Za-z0-9._-]{0,99})?)(?::[A-Za-z0-9][A-Za-z0-9._-]{0,59})?$").is_match(model) {
        Ok(model.to_string())
    } else {
        Err("Choose a valid local model.".into())
    }
}

fn valid_repo(repo: &str) -> bool {
    crate::re!(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$").is_match(repo)
}

/// The quantization tag in a GGUF file name, e.g. `Q4_K_M`, `IQ3_M`, `MXFP4`.
pub fn quant_of(file: &str) -> Option<String> {
    let name = fs::file_name(&file.replace('/', "\\")).to_string();
    let lower = name.to_ascii_lowercase();
    if !lower.ends_with(".gguf") || ["mmproj", "eagle", "draft", "imatrix"].iter().any(|w| lower.contains(w)) {
        return None;
    }
    if crate::re!(r"(?i)-\d{5}-of-\d{5}\.gguf$").is_match(&name) {
        return None; // split files are not supported by Ollama's Hugging Face pulls
    }
    crate::re!(r"(?i)[-._]((?:I?Q\d(?:_[A-Z0-9]+)*)|MXFP4|BF16|F16|F32)\.gguf$")
        .captures(&name)
        .map(|c| c[1].to_ascii_uppercase())
}

fn same_model(a: &str, b: &str) -> bool {
    let norm = |m: &str| {
        let m = m.trim().to_ascii_lowercase();
        if m.contains(':') { m } else { format!("{m}:latest") }
    };
    norm(a) == norm(b)
}

// ---- Ollama process ------------------------------------------------------------------

fn install_dir() -> String {
    fs::join(&config::paths().local_app_data, "Programs\\Ollama")
}

fn executable() -> Option<String> {
    crate::pc_control::which("ollama.exe").or_else(|| {
        let exe = fs::join(&install_dir(), "ollama.exe");
        fs::stat(&exe).filter(|s| s.file).map(|_| exe)
    })
}

fn winget() -> Option<String> {
    // winget.exe is an app execution alias: a reparse point that cannot be
    // stat'ed, so look for it in the folder listing instead.
    let dir = fs::join(&config::paths().local_app_data, "Microsoft\\WindowsApps");
    fs::list_dir(&dir)
        .iter()
        .any(|e| e.name.eq_ignore_ascii_case("winget.exe"))
        .then(|| fs::join(&dir, "winget.exe"))
        .or_else(|| crate::pc_control::which("winget.exe"))
}

async fn version() -> Option<String> {
    let mut response = Http::get(&format!("{OLLAMA}/api/version")).timeout(2.0).send().await.ok()?;
    if response.status != 200 {
        return None;
    }
    response.json().await.ok()?["version"].as_str().map(str::to_string)
}

/// Starts Ollama when it is installed but not running.
pub async fn ensure_running() -> Res<()> {
    if version().await.is_some() {
        return Ok(());
    }
    let Some(exe) = executable() else {
        return Err("Local AI is not installed yet. Install it in Settings, AI.".into());
    };
    let tray = fs::join(fs::parent(&exe), "ollama app.exe");
    let started = if fs::exists(&tray) {
        host::spawn_detached(&tray, &[], json!({ "cwd": fs::parent(&exe) }))
    } else {
        host::spawn_detached(&exe, &["serve"], json!({ "cwd": fs::parent(&exe) }))
    };
    if !started {
        return Err("Local AI could not be started.".into());
    }
    for _ in 0..40 {
        host::sleep(500.0).await;
        if version().await.is_some() {
            return Ok(());
        }
    }
    Err("Local AI did not start in time. Open Ollama once, then try again.".into())
}

pub async fn installed_models() -> Res<Vec<Value>> {
    let mut response = Http::get(&format!("{OLLAMA}/api/tags")).timeout(5.0).send().await?;
    if response.status != 200 {
        return Err("Local AI did not list its models.".into());
    }
    let data = response.json().await?;
    Ok(data["models"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|m| {
            let name = m["name"].as_str().or_else(|| m["model"].as_str())?;
            Some(json!({
                "name": name,
                "size": m["size"].as_u64().unwrap_or(0),
                "parameters": m["details"]["parameter_size"].as_str().unwrap_or(""),
                "quantization": m["details"]["quantization_level"].as_str().unwrap_or(""),
            }))
        })
        .collect())
}

/// Whether the model has a thinking mode; asked once per model.
async fn learn_thinking(model: &str) {
    if thinks(model).is_some() {
        return;
    }
    let Ok(mut response) = Http::post(&format!("{OLLAMA}/api/show")).timeout(10.0).json(&json!({ "model": model })).send().await else { return };
    if response.status != 200 {
        return;
    }
    let Ok(data) = response.json().await else { return };
    let thinking = data["capabilities"].as_array().is_some_and(|c| c.iter().any(|v| v == "thinking"));
    STATE.with(|s| s.borrow_mut().thinking.insert(model.to_ascii_lowercase(), thinking));
}

pub fn thinks(model: &str) -> Option<bool> {
    STATE.with(|s| s.borrow().thinking.get(&model.to_ascii_lowercase()).copied())
}

/// Runs before every local request: Ollama is up and the model's mode is known.
pub async fn prepare(model: &str) -> Res<()> {
    ensure_running().await?;
    learn_thinking(model).await;
    Ok(())
}

pub fn selected_model() -> String {
    config::get_or("LOCAL_MODEL", "")
}

// ---- status --------------------------------------------------------------------------

pub async fn status() -> Value {
    let running = version().await;
    let models = if running.is_some() { installed_models().await.unwrap_or_default() } else { Vec::new() };
    let selected = selected_model();
    let recommended: Vec<Value> = RECOMMENDED
        .iter()
        .map(|(repo, quant, label, gb, note)| {
            let model = format!("hf.co/{repo}:{quant}");
            json!({ "repo": repo, "quant": quant, "label": label, "size_gb": gb, "note": note,
                    "model": model, "installed": models.iter().any(|m| same_model(m["name"].as_str().unwrap_or(""), &model)) })
        })
        .collect();
    json!({
        "installed": running.is_some() || executable().is_some(),
        "running": running.is_some(),
        "version": running,
        "winget": winget().is_some(),
        "install": STATE.with(|s| s.borrow().install.clone()),
        "pull": pull_state(),
        "models": models,
        "selected": selected,
        "active": settings::active_provider().id == "local",
        "recommended": recommended,
    })
}

// ---- install ---------------------------------------------------------------------

/// Installs the official Ollama package for this user with winget, in the background.
pub fn start_install() -> Res<Value> {
    if executable().is_some() {
        return Ok(json!({ "state": "done", "message": "Local AI is already installed." }));
    }
    if STATE.with(|s| s.borrow().install["state"] == "installing") {
        return Ok(json!({ "state": "installing" }));
    }
    let Some(winget) = winget() else {
        return Err("Windows Package Manager (winget) is missing. Install Ollama from ollama.com/download, then come back.".into());
    };
    set_install("installing", "Installing Ollama. This can take a few minutes.");
    wasm_bindgen_futures::spawn_local(async move {
        let args = ["install", "--id", "Ollama.Ollama", "--exact", "--silent", "--scope", "user",
                    "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"];
        let out = host::run(&winget, &args, json!({ "timeoutMs": 1_200_000 })).await;
        if executable().is_none() {
            host::log("warning", &format!("Ollama install via winget ended with code {}", out.code));
            set_install("failed", "Ollama could not be installed. Install it from ollama.com/download, then come back.");
            return;
        }
        set_install("starting", "Ollama is installed. Starting it.");
        match ensure_running().await {
            Ok(()) => set_install("done", "Local AI is installed and running."),
            Err(e) => set_install("failed", &e),
        }
    });
    Ok(json!({ "state": "installing" }))
}

// ---- Hugging Face ------------------------------------------------------------------

fn clean_query(query: &str) -> Res<String> {
    let query = query.trim();
    if query.chars().count() > 80 || !query.chars().all(|c| c.is_alphanumeric() || " ._-/".contains(c)) {
        return Err("Search with letters, numbers, spaces, dots, dashes or slashes.".into());
    }
    Ok(query.to_string())
}

/// GGUF text-generation models on Hugging Face, most downloaded first.
pub async fn search(query: &str) -> Res<Value> {
    let query = clean_query(query)?;
    let mut url = format!("{HF}/api/models?filter=gguf&pipeline_tag=text-generation&sort=downloads&direction=-1&limit=24");
    if !query.is_empty() {
        url.push_str("&search=");
        url.push_str(&host::url_encode(&query));
    }
    let mut response = Http::get(&url).timeout(15.0).send().await.map_err(|_| "Hugging Face is not reachable.".to_string())?;
    if response.status != 200 {
        return Err(format!("Hugging Face answered HTTP {}.", response.status));
    }
    let data = response.json().await?;
    let results: Vec<Value> = data
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|m| {
            let id = m["id"].as_str().filter(|id| valid_repo(id))?;
            Some(json!({ "repo": id, "downloads": m["downloads"].as_u64().unwrap_or(0), "likes": m["likes"].as_u64().unwrap_or(0) }))
        })
        .collect();
    Ok(json!({ "results": results }))
}

/// The downloadable quantizations of one repository, smallest first.
pub async fn files(repo: &str) -> Res<Value> {
    if !valid_repo(repo) {
        return Err("Choose a Hugging Face repository like owner/name.".into());
    }
    let url = format!("{HF}/api/models/{repo}/tree/main?recursive=true");
    let mut response = Http::get(&url).timeout(15.0).send().await.map_err(|_| "Hugging Face is not reachable.".to_string())?;
    if response.status != 200 {
        return Err(format!("Hugging Face answered HTTP {} for this model.", response.status));
    }
    let data = response.json().await?;
    let mut by_quant: Vec<(String, u64, usize)> = Vec::new();
    for f in data.as_array().into_iter().flatten() {
        if f["type"] != "file" {
            continue;
        }
        let path = f["path"].as_str().unwrap_or("");
        let Some(quant) = quant_of(path) else { continue };
        let size = f["lfs"]["size"].as_u64().or_else(|| f["size"].as_u64()).unwrap_or(0);
        match by_quant.iter_mut().find(|(q, _, _)| *q == quant) {
            Some(entry) => entry.2 += 1,
            None => by_quant.push((quant, size, 1)),
        }
    }
    // Two files with the same tag would make the download ambiguous.
    let mut quants: Vec<(String, u64)> = by_quant.into_iter().filter(|(_, _, n)| *n == 1).map(|(q, s, _)| (q, s)).collect();
    quants.sort_by_key(|(_, size)| *size);
    let list: Vec<Value> = quants
        .into_iter()
        .map(|(quant, size)| json!({ "quant": quant, "size": size, "model": format!("hf.co/{repo}:{quant}") }))
        .collect();
    Ok(json!({ "repo": repo, "files": list }))
}

// ---- downloads -----------------------------------------------------------------------

fn apply_progress(line: &str, model: &str) -> Option<Result<bool, String>> {
    let event: Value = serde_json::from_str(line.trim()).ok()?;
    if let Some(error) = event["error"].as_str() {
        return Some(Err(error.chars().take(200).collect()));
    }
    let status = event["status"].as_str().unwrap_or("");
    let mut pull = pull_state();
    pull["status"] = json!(status);
    if let (Some(total), Some(done)) = (event["total"].as_u64(), event["completed"].as_u64()) {
        pull["total"] = json!(total);
        pull["completed"] = json!(done);
    }
    pull["model"] = json!(model);
    set_pull(pull);
    Some(Ok(status == "success"))
}

/// Downloads a model into Ollama in the background; progress is in `status()`.
pub fn start_pull(model: &str) -> Res<Value> {
    let model = validate_model(model)?;
    if pull_state()["state"] == "downloading" {
        return Err("Another model is downloading. Wait until it finishes.".into());
    }
    set_pull(json!({ "state": "downloading", "model": model, "status": "starting", "completed": 0, "total": 0 }));
    wasm_bindgen_futures::spawn_local(async move {
        let result = pull(&model).await;
        let mut state = pull_state();
        match result {
            Ok(()) => {
                state["state"] = json!("done");
                state["status"] = json!("success");
                learn_thinking(&model).await;
                if selected_model().is_empty() {
                    let _ = select(&model).await;
                }
            }
            Err(e) => {
                state["state"] = json!("failed");
                state["error"] = json!(e);
            }
        }
        set_pull(state);
    });
    Ok(pull_state())
}

async fn pull(model: &str) -> Res<()> {
    ensure_running().await?;
    let mut response = Http::post(&format!("{OLLAMA}/api/pull"))
        .timeout(300.0)
        .json(&json!({ "model": model, "stream": true }))
        .send()
        .await
        .map_err(|_| "Local AI stopped responding during the download.".to_string())?;
    if response.status != 200 {
        let text = response.text().await.unwrap_or_default();
        let error = serde_json::from_str::<Value>(&text).ok().and_then(|v| v["error"].as_str().map(str::to_string));
        return Err(error.unwrap_or_else(|| format!("Download failed with HTTP {}.", response.status)));
    }
    let mut buffer = String::new();
    let mut success = false;
    while let Some(chunk) = response.chunk().await.map_err(|_| "The download was interrupted.".to_string())? {
        buffer.push_str(&String::from_utf8_lossy(&chunk));
        while let Some(end) = buffer.find('\n') {
            let line: String = buffer.drain(..=end).collect();
            match apply_progress(&line, model) {
                Some(Err(e)) => return Err(e),
                Some(Ok(true)) => success = true,
                _ => {}
            }
        }
    }
    if let Some(Ok(true)) = apply_progress(&buffer, model) {
        success = true;
    }
    if success { Ok(()) } else { Err("The download ended before it was complete.".into()) }
}

// ---- choice ------------------------------------------------------------------------

/// Makes an installed model Jarvis's AI.
pub async fn select(model: &str) -> Res<Value> {
    let model = validate_model(model)?;
    ensure_running().await?;
    let installed = installed_models().await?;
    let Some(name) = installed.iter().filter_map(|m| m["name"].as_str()).find(|n| same_model(n, &model)) else {
        return Err("Download this model first.".into());
    };
    let name = name.to_string();
    let saved = settings::save(&json!({ "llm_provider": "local", "local_model": name }))?;
    settings::apply_provider_settings(&Value::Object(saved));
    learn_thinking(&name).await;
    Ok(json!({ "selected": name, "active": true }))
}

pub async fn delete(model: &str) -> Res<Value> {
    let model = validate_model(model)?;
    ensure_running().await?;
    let response = Http::new("DELETE", &format!("{OLLAMA}/api/delete")).timeout(30.0).json(&json!({ "model": model })).send().await?;
    if response.status != 200 {
        return Err("The model could not be removed.".into());
    }
    if same_model(&selected_model(), &model) {
        let saved = settings::save(&json!({ "local_model": "" }))?;
        settings::apply_provider_settings(&Value::Object(saved));
    }
    Ok(json!({ "removed": model }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quantization_tags_come_from_file_names() {
        assert_eq!(quant_of("Qwen3-8B-Q4_K_M.gguf").as_deref(), Some("Q4_K_M"));
        assert_eq!(quant_of("sub/qwen2.5-1.5b-instruct-q4_k_m.gguf").as_deref(), Some("Q4_K_M"));
        assert_eq!(quant_of("gpt-oss-20b-MXFP4.gguf").as_deref(), Some("MXFP4"));
        assert_eq!(quant_of("Model-IQ3_M.gguf").as_deref(), Some("IQ3_M"));
        assert_eq!(quant_of("qwen2.5-1.5b-instruct-fp16.gguf"), None);
        assert_eq!(quant_of("Model-F16.gguf").as_deref(), Some("F16"));
        for skipped in ["eagle3-gpt-oss-20b-Q8_0.gguf", "mmproj-Model-F16.gguf", "Big-Q4_K_M-00001-of-00002.gguf", "README.md"] {
            assert_eq!(quant_of(skipped), None, "{skipped}");
        }
    }

    #[test]
    fn model_names_are_plain_ollama_or_hugging_face_names() {
        for good in ["hf.co/Qwen/Qwen3-8B-GGUF:Q4_K_M", "llama3.2", "qwen3:8b", "library/qwen3:4b"] {
            assert!(validate_model(good).is_ok(), "{good}");
        }
        for bad in ["", "hf.co/../etc:x", "a b", "hf.co/owner/repo:Q4;rm", "http://evil/x", "hf.co/a/b/c:Q4"] {
            assert!(validate_model(bad).is_err(), "{bad}");
        }
        assert!(valid_repo("Qwen/Qwen3-8B-GGUF"));
        assert!(!valid_repo("Qwen/../x"));
        assert!(!valid_repo("onlyname"));
    }

    #[test]
    fn installed_names_match_without_latest_or_case() {
        assert!(same_model("hf.co/Qwen/Qwen3-8B-GGUF:Q4_K_M", "hf.co/qwen/qwen3-8b-gguf:q4_k_m"));
        assert!(same_model("llama3.2:latest", "llama3.2"));
        assert!(!same_model("qwen3:8b", "qwen3:4b"));
    }

    #[test]
    fn local_requests_only_name_a_thinking_level_the_model_supports() {
        use crate::llm::local_reasoning;
        // Unknown or non-thinking models always get "none", which every model accepts.
        assert_eq!(local_reasoning("hf.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF:Q4_K_M", "high", Some(false)), ("none", false));
        assert_eq!(local_reasoning("llama3.2", "high", None), ("none", false));
        // Thinking models answer quickly at low effort and think at higher levels.
        assert_eq!(local_reasoning("hf.co/Qwen/Qwen3-8B-GGUF:Q4_K_M", "low", Some(true)), ("none", false));
        assert_eq!(local_reasoning("hf.co/Qwen/Qwen3-8B-GGUF:Q4_K_M", "max", Some(true)), ("high", true));
        // GPT-OSS cannot turn thinking off.
        assert_eq!(local_reasoning("hf.co/ggml-org/gpt-oss-20b-GGUF:MXFP4", "none", Some(true)), ("low", true));
    }

    #[test]
    fn download_progress_lines_update_the_state() {
        assert_eq!(apply_progress(r#"{"status":"pulling abc","total":100,"completed":40}"#, "m"), Some(Ok(false)));
        assert_eq!(pull_state()["completed"], 40);
        assert_eq!(apply_progress(r#"{"status":"success"}"#, "m"), Some(Ok(true)));
        assert!(matches!(apply_progress(r#"{"error":"pull model manifest: file does not exist"}"#, "m"), Some(Err(_))));
        assert_eq!(apply_progress("not json", "m"), None);
    }
}
