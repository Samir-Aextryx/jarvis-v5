//! HTTP routes. Everything except health, the page and its assets needs the
//! bearer token (checked in `server`).

use crate::config;
use crate::host::{self, Http, Res, fs};
use crate::http::{Request, Response, content_type_for, url_decode};
use crate::llm::{Llm, Request as LlmRequest};
use crate::timezone::{self, Moment};
use crate::util::{b64, s};
use crate::{VERSION, apps, auth, autonomous, brain, calendar, google, local_ai, memory, notes, pc_control, personal, privacy, settings, speech, stt, tasks, urgent_mail, vault, whatsapp};
use serde_json::{Map, Value, json};

pub async fn route(req: Request) -> Response {
    dispatch(req).await.unwrap_or_else(|r| r)
}

async fn dispatch(req: Request) -> Result<Response, Response> {
    let method = req.method.clone();
    let path = req.path.clone();
    match (method.as_str(), path.as_str()) {
        ("GET", "/api/health") => Ok(Response::ok(json!({ "status": "online", "name": "JARVIS", "version": VERSION }))),
        ("POST", "/api/dashboard/session") => {
            let code = auth::create_dashboard_code();
            let port = config::port();
            Ok(Response::ok(json!({ "code": code, "url": format!("http://127.0.0.1:{port}/launch/{code}"), "expires_in": 60 })))
        }
        ("GET", p) if p.starts_with("/launch/") => Ok(launch(&p["/launch/".len()..])),
        ("GET" | "HEAD", "/") => Ok(static_file("index.html")),
        ("GET" | "HEAD", "/pcm-capture.js") => Ok(static_file("pcm-capture.js")),
        ("GET" | "HEAD", p) if p.starts_with("/assets/") => Ok(static_file(&p[1..])),

        // System and settings
        ("GET", "/api/settings/llm") => Ok(Response::ok(settings::provider_status())),
        ("POST", "/api/settings/test-llm") => test_llm(&req).await,
        ("GET", "/api/usage") => Ok(Response::ok(settings::usage_json())),

        // Local AI (Ollama, models from Hugging Face)
        ("GET", "/api/local-ai/status") => Ok(Response::ok(local_ai::status().await)),
        ("POST", "/api/local-ai/install") => Ok(bad_request(local_ai::start_install())),
        ("POST", "/api/local-ai/start") => Ok(bad_request(local_ai::ensure_running().await.map(|()| json!({ "running": true })))),
        ("GET", "/api/local-ai/search") => Ok(bad_request(local_ai::search(&req.query_param("q").unwrap_or_default()).await)),
        ("GET", "/api/local-ai/files") => Ok(bad_request(local_ai::files(&req.query_param("repo").unwrap_or_default()).await)),
        ("POST", "/api/local-ai/pull") => {
            let body = body(&req)?;
            Ok(bad_request(local_ai::start_pull(s(&body, "model"))))
        }
        ("POST", "/api/local-ai/select") => {
            let body = body(&req)?;
            Ok(bad_request(local_ai::select(s(&body, "model")).await))
        }
        ("POST", "/api/local-ai/delete") => {
            let body = body(&req)?;
            Ok(bad_request(local_ai::delete(s(&body, "model")).await))
        }
        ("POST", "/api/settings/keys") => save_key(&req).await,
        ("POST", "/api/settings/test-openai") => test_openai(&req).await,
        ("POST", "/api/settings/test-fish") => test_fish(&req).await,
        ("GET", "/api/settings/status") => Ok(Response::ok(settings_status().await)),
        ("GET", "/api/settings/preferences") => {
            let (_, env) = settings::read_env();
            let get = |k: &str, d: &str| env.get(k).and_then(Value::as_str).unwrap_or(d).to_string();
            Ok(Response::ok(json!({
                "user_name": Some(get("USER_NAME", "")).filter(|n| n != "your-name").unwrap_or_default(), "honorific": get("HONORIFIC", "sir"), "stt_keywords": get("JARVIS_STT_KEYWORDS", ""),
            })))
        }
        ("POST", "/api/settings/preferences") => save_preferences(&req).await,
        ("POST", "/api/restart") => {
            crate::info!("Restart requested — shutting down in 2 seconds");
            wasm_bindgen_futures::spawn_local(async {
                host::sleep(2000.0).await;
                host::restart();
            });
            Ok(Response::ok(json!({ "status": "restarting" })))
        }
        ("POST", "/api/fix-self") => {
            let dir = config::paths().resources;
            let (ok, message) = match pc_control::start_code("Inspect this project and help me improve it.", Some(&dir)) {
                Ok(m) => (true, m),
                Err(e) => (false, e),
            };
            Ok(Response::ok(json!({ "status": if ok { "work_mode_active" } else { "unavailable" }, "path": dir, "message": message })))
        }

        // Voice
        ("GET", "/api/voice/metrics") => Ok(Response::ok(json!({ "measurements": brain::recent_metrics() }))),
        ("POST", "/api/transcribe") => Ok(stt::transcribe(req).await),
        ("GET", "/api/tts-test") => Ok(Response::ok(match speech::synthesize("Testing audio, sir.").await {
            Some(audio) => json!({ "audio": b64(&audio) }),
            None => json!({ "audio": null, "error": "TTS failed" }),
        })),

        // Personal memory, calendar and notes
        ("GET", "/api/memory/profile") => {
            Ok(Response::ok(json!({ "markdown": fs::read_text(&personal::path()).unwrap_or_default(), "facts": personal::facts() })))
        }
        ("POST", "/api/memory/open") => {
            crate::voice::open_memory();
            Ok(Response::ok(json!({ "success": true })))
        }
        ("POST", "/api/memory/custom") => {
            let body = body(&req)?;
            let expected = body.get("expected_updated").and_then(Value::as_f64);
            let kind = body.get("kind").and_then(Value::as_str).unwrap_or("fact");
            Ok(match personal::edit_fact(s(&body, "content"), kind, body.get("key").and_then(Value::as_str), expected, false) {
                Ok(fact) => Response::ok(json!({ "fact": fact })),
                Err(e) => Response::json(conflict_or_bad(&e), &json!({ "error": e })),
            })
        }
        ("POST", "/api/memory/delete") => {
            let body = body(&req)?;
            Ok(match personal::delete_fact(s(&body, "key"), body.get("expected_updated").and_then(Value::as_f64)) {
                Ok(()) => Response::ok(json!({ "success": true })),
                Err(e) => Response::json(409, &json!({ "error": e })),
            })
        }
        ("GET", "/api/local-calendar/events") => {
            let zone = timezone::zone();
            let today = Moment::now().date(&zone);
            let start = req.query_param("start").filter(|v| !v.is_empty()).unwrap_or_else(|| today.iso());
            let end = req.query_param("end").filter(|v| !v.is_empty()).unwrap_or_else(|| today.add(30).iso());
            Ok(match calendar::list_events(&start, &end) {
                Ok(events) => Response::ok(json!({ "events": events, "timezone": zone })),
                Err(e) => Response::json(400, &json!({ "error": e })),
            })
        }
        ("POST", "/api/local-calendar/events") => {
            let body = body(&req)?;
            Ok(match calendar::save(&body, body.get("id").and_then(Value::as_str), body.get("version")) {
                Ok(event) => Response::ok(json!({ "event": event })),
                Err(e) => Response::json(conflict_or_bad(&e), &json!({ "error": e })),
            })
        }
        ("POST", "/api/local-calendar/delete") => {
            let body = body(&req)?;
            Ok(match calendar::delete(s(&body, "id"), body.get("version")) {
                Ok(()) => Response::ok(json!({ "success": true })),
                Err(e) => Response::json(409, &json!({ "error": e })),
            })
        }
        ("GET", "/api/notes") => Ok(Response::ok(json!({
            "notes": match req.query_param("query").filter(|q| !q.is_empty()) {
                Some(q) => notes::search(&q, 10),
                None => notes::list(),
            }
        }))),
        ("POST", "/api/notes") => {
            let body = body(&req)?;
            let folder = body.get("folder").and_then(Value::as_str).unwrap_or("Notes");
            Ok(match notes::create(s(&body, "title"), s(&body, "body"), folder, body.get("tags")) {
                Ok(note) => Response::ok(json!({ "note": note })),
                Err(e) => Response::json(400, &json!({ "error": e })),
            })
        }
        ("DELETE", p) if p.starts_with("/api/notes/") => Ok(if notes::delete(&url_decode(&p["/api/notes/".len()..])) {
            Response::ok(json!({ "success": true }))
        } else {
            Response::json(404, &json!({ "error": "Note not found" }))
        }),

        // Automation
        ("GET", "/api/apps") => {
            let names: Vec<String> = apps::installed_apps().await.into_iter().map(|a| a.name).collect();
            Ok(Response::ok(json!({ "apps": names })))
        }
        ("POST", "/api/pc/command") => pc_command(&req).await,
        ("GET", "/api/pc/jobs") => Ok(Response::ok(json!({ "jobs": pc_control::jobs() }))),
        ("GET", "/api/local-pc/status") => {
            let mut status = settings::provider_status();
            status["scope"] = "Explicit PC commands and autonomous tasks".into();
            Ok(Response::ok(status))
        }
        ("GET", "/api/autonomy/jobs") => Ok(Response::ok(json!({ "jobs": autonomous::recent_jobs() }))),
        ("POST", "/api/apps/open") => {
            if !settings::automation_enabled() {
                return Err(Response::json(409, &json!({ "error": "Command execution is paused in AI Settings." })));
            }
            let body = body(&req)?;
            let Some(name) = body.get("name").and_then(Value::as_str) else { return Err(missing("name")) };
            let r = apps::open_app(name, apps::OpenOptions::default()).await;
            Ok(Response::ok(json!({ "success": r.success, "state": r.state, "app": r.app, "confirmation": r.confirmation, "preference_key": r.preference_key })))
        }
        ("GET", "/api/tasks") => Ok(Response::ok(json!({ "tasks": tasks::list() }))),
        ("GET", p) if p.starts_with("/api/tasks/") => Ok(match tasks::status(&url_decode(&p["/api/tasks/".len()..])) {
            Some(task) => Response::ok(json!({ "task": task })),
            None => Response::json(404, &json!({ "error": "Task not found" })),
        }),
        ("POST", "/api/tasks") => {
            let body = body(&req)?;
            let Some(prompt) = body.get("prompt").and_then(Value::as_str) else { return Err(missing("prompt")) };
            let dir = body.get("working_dir").and_then(Value::as_str).unwrap_or(".");
            Ok(match tasks::spawn(prompt, dir) {
                Ok(id) => Response::ok(json!({ "task_id": id, "status": "spawned" })),
                Err(e) => Response::json(429, &json!({ "error": e })),
            })
        }
        ("DELETE", p) if p.starts_with("/api/tasks/") => {
            let id = url_decode(&p["/api/tasks/".len()..]);
            Ok(if tasks::cancel(&id) {
                Response::ok(json!({ "task_id": id, "status": "cancelled" }))
            } else {
                Response::json(404, &json!({ "error": "Task not found or not cancellable" }))
            })
        }
        ("GET", "/api/projects") => Ok(Response::ok(json!({ "projects": brain::scan_projects() }))),

        // Google
        ("POST", "/api/google/api-key") => {
            let body = body(&req)?;
            let Some(key) = body.get("key").and_then(Value::as_str) else { return Err(missing("key")) };
            Ok(bad_request(google::save_api_key(key).await))
        }
        ("POST", "/api/google/test-api-key") => Ok(bad_request(google::public_youtube(1).await.map(|_| {
            json!({ "valid": true, "message": "YouTube Data API access verified. Private Gmail and Calendar still require Google sign-in." })
        }))),
        ("GET", "/api/google/status") => Ok(Response::ok(google::status())),
        ("POST", "/api/google/config") => {
            let body = body(&req)?;
            let (Some(cfg), Some(services)) = (body.get("config").filter(|c| c.is_object()), string_list(&body["services"])) else {
                return Err(missing("config"));
            };
            if cfg.to_string().len() > 16000 {
                return Err(Response::json(400, &json!({ "error": "OAuth JSON is too large." })));
            }
            Ok(bad_request(google::configure(cfg, &services).await))
        }
        ("POST", "/api/google/connect") => {
            let body = body(&req)?;
            Ok(bad_request(google::connect(string_list(&body["services"])).await))
        }
        ("POST", "/api/google/disconnect") => Ok(bad_request(google::disconnect().await)),
        ("GET", p) if p.starts_with("/api/google/read/") => {
            let service = url_decode(&p["/api/google/read/".len()..]);
            if !google::SCOPES.iter().any(|(k, _)| *k == service) {
                return Err(Response::json(400, &json!({ "error": "Unsupported Google service." })));
            }
            Ok(bad_request(google::read(&service).await))
        }

        // Agent settings and integrations
        ("GET", "/api/agent/phone-privacy/status") => Ok(Response::ok(json!({ "active": privacy::active() }))),
        ("GET", "/api/agent/whatsapp-call/status") => Ok(Response::ok(whatsapp::call_readiness().await)),
        ("POST", "/api/agent/whatsapp-call/contact") => {
            let body = body(&req)?;
            let Some(number) = body.get("number").and_then(Value::as_str) else { return Err(missing("number")) };
            Ok(bad_request(whatsapp::save_boss_number(number).await.map(|()| json!({ "saved": true }))))
        }
        ("GET", "/api/agent/urgent-mail/status") => Ok(Response::ok(urgent_mail::status())),
        ("GET", "/api/agent/settings") => {
            let mut out: Map<String, Value> = settings::get();
            out.remove("fallback");
            out.insert(
                "capabilities".into(),
                json!({ "gmail": "Configure in Google settings", "outlook_graph": "Not connected / unavailable",
                        "teams_notifications": "Unavailable", "local_calendar": "Available" }),
            );
            Ok(Response::ok(Value::Object(out)))
        }
        ("POST", "/api/agent/settings") => {
            let body = body(&req)?;
            Ok(match settings::save(&body) {
                Ok(result) => {
                    let result = Value::Object(result);
                    settings::apply_provider_settings(&result);
                    Response::ok(result)
                }
                Err(e) => Response::json(400, &json!({ "error": e })),
            })
        }
        ("GET", "/api/agent/activity") => Ok(Response::ok(json!({ "items": settings::activity_logs() }))),
        ("POST", "/api/agent/activity/clear") => {
            settings::clear_activity();
            Ok(Response::ok(json!({ "ok": true })))
        }
        _ => Ok(Response::not_found()),
    }
}

/// JSON object body; anything else becomes FastAPI's 422.
fn body(req: &Request) -> Result<Value, Response> {
    let value = req.json_value()?;
    if value.is_object() {
        Ok(value)
    } else {
        Err(Response::json(422, &json!({ "detail": [{ "msg": "Input should be a valid dictionary", "type": "dict_type" }] })))
    }
}

fn missing(field: &str) -> Response {
    Response::json(422, &json!({ "detail": [{ "loc": ["body", field], "msg": "Field required", "type": "missing" }] }))
}

fn string_list(value: &Value) -> Option<Vec<String>> {
    value.as_array().map(|a| a.iter().filter_map(Value::as_str).map(str::to_string).collect())
}

fn conflict_or_bad(error: &str) -> u16 {
    if error.contains("changed or was removed") { 409 } else { 400 }
}

fn bad_request(result: Res<Value>) -> Response {
    match result {
        Ok(v) => Response::ok(v),
        Err(e) => Response::json(400, &json!({ "error": e })),
    }
}

fn secret(body: &Value, field: &str) -> Option<String> {
    body.get(field).and_then(Value::as_str).map(|v| v.trim().to_string()).filter(|v| !v.is_empty())
}

fn bad_key(key: &str) -> bool {
    key.len() > 2048 || key.chars().any(char::is_whitespace)
}

async fn test_llm(req: &Request) -> Result<Response, Response> {
    let body = body(req)?;
    let provider = s(&body, "provider").to_string();
    if !["openai", "gemini", "grok", "ollama", "local"].contains(&provider.as_str()) {
        return Ok(Response::json(422, &json!({ "detail": [{ "loc": ["body", "provider"], "msg": "Input should be 'openai', 'gemini', 'grok', 'ollama' or 'local'", "type": "literal_error" }] })));
    }
    let key = secret(&body, "key_value");
    if key.as_deref().is_some_and(bad_key) {
        return Ok(Response::json(400, &json!({ "valid": false, "error": "Invalid API key value" })));
    }
    let ok = match Llm::new(Some(&provider), key) {
        Ok(llm) => llm.create(&LlmRequest::user("", "Reply only with OK.", 256)).await.is_ok(),
        Err(_) => false,
    };
    Ok(Response::ok(if ok {
        json!({ "valid": true, "provider": provider })
    } else {
        json!({ "valid": false, "provider": provider, "error": if provider == "local" {
            "Local AI did not answer. Check that Ollama runs and the chosen model is downloaded."
        } else {
            "Connection failed. Check the API key, model availability and API credit."
        } })
    }))
}

const SETTABLE_KEYS: [&str; 10] =
    ["OPENAI_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY", "OLLAMA_API_KEY", "FISH_API_KEY", "FISH_VOICE_ID", "USER_NAME", "HONORIFIC", "OPENAI_MODEL", "FISH_MODEL"];

async fn save_key(req: &Request) -> Result<Response, Response> {
    let body = match body(req) {
        Ok(b) => b,
        Err(r) => return Err(r),
    };
    let (Some(name), Some(value)) = (body.get("key_name").and_then(Value::as_str), body.get("key_value").and_then(Value::as_str)) else {
        return Err(missing("key_name"));
    };
    if !SETTABLE_KEYS.contains(&name) {
        return Ok(Response::json(400, &json!({ "success": false, "error": "Invalid key name" })));
    }
    if value.contains(['\r', '\n', '\0']) {
        return Ok(Response::json(400, &json!({ "success": false, "error": "Invalid multiline value" })));
    }
    if ["GEMINI_API_KEY", "XAI_API_KEY", "OLLAMA_API_KEY"].contains(&name) && bad_key(value) {
        return Ok(Response::json(400, &json!({ "success": false, "error": "Invalid API key value" })));
    }
    Ok(match settings::write_env_key(name, value).await {
        Ok(()) => Response::ok(json!({ "success": true })),
        Err(_) => Response::json(503, &json!({ "success": false, "error": "The key could not be saved securely. Check Windows Credential Manager." })),
    })
}

async fn test_openai(req: &Request) -> Result<Response, Response> {
    let body = body(req).unwrap_or_default();
    let key = secret(&body, "key_value").unwrap_or_else(|| vault::get("OPENAI_API_KEY"));
    if key.is_empty() {
        return Ok(Response::ok(json!({ "valid": false, "error": "No key provided" })));
    }
    let result = match Llm::new(Some("openai"), Some(key)) {
        Ok(llm) => llm.create(&LlmRequest::user("", "Reply only with OK.", 10)).await.map(|_| ()),
        Err(e) => Err(e),
    };
    Ok(Response::ok(match result {
        Ok(()) => json!({ "valid": true }),
        Err(e) => json!({ "valid": false, "error": crate::util::take(&e, 200) }),
    }))
}

async fn test_fish(req: &Request) -> Result<Response, Response> {
    let body = body(req).unwrap_or_default();
    let key = secret(&body, "key_value").unwrap_or_else(|| vault::get("FISH_API_KEY"));
    if key.is_empty() {
        return Ok(Response::ok(json!({ "valid": false, "error": "No key provided" })));
    }
    let sent = Http::post("https://api.fish.audio/v1/tts")
        .bearer(&key)
        .header("model", &settings::fish_model())
        .timeout(10.0)
        .json(&json!({ "text": "test", "reference_id": settings::fish_voice_id() }))
        .send()
        .await;
    Ok(Response::ok(match sent {
        Ok(r) if matches!(r.status, 200 | 201) => json!({ "valid": true }),
        Ok(r) if r.status == 401 => json!({ "valid": false, "error": "Invalid API key" }),
        Ok(r) => json!({ "valid": false, "error": format!("HTTP {}", r.status) }),
        Err(e) => json!({ "valid": false, "error": crate::util::take(&e, 200) }),
    }))
}

async fn settings_status() -> Value {
    let (_, env) = settings::read_env();
    let google = google::status();
    let google_mail = google["connected"].as_bool().unwrap_or(false)
        && google["services"].as_array().is_some_and(|a| a.iter().any(|s| matches!(s.as_str(), Some("gmail" | "gmail_drafts" | "gmail_send"))));
    let outlook = crate::outlook::account_accessible().await;
    let openai = vault::get("OPENAI_API_KEY");
    let fish = vault::get("FISH_API_KEY");
    let env_str = |k: &str| env.get(k).and_then(Value::as_str).unwrap_or("").to_string();
    json!({
        "platform": "Windows",
        "openai_model": config::get_or("OPENAI_MODEL", "gpt-6-luna"),
        "codex_installed": pc_control::codex_executable().is_ok(),
        "calendar_accessible": calendar::upcoming(1).is_ok(),
        "outlook_accessible": outlook,
        "google_mail_accessible": google_mail,
        "mail_accessible": outlook || google_mail,
        "notes_accessible": true,
        "atlassian_accessible": crate::atlassian::ready(),
        "memory_count": memory::important_memories(9999).len(),
        "task_count": memory::open_tasks().len(),
        "server_port": config::port(),
        "uptime_seconds": crate::uptime() as u64,
        "env_keys_set": {
            "openai": !openai.trim().is_empty(),
            "fish_audio": !fish.trim().is_empty() && fish != "your-fish-audio-api-key-here",
            "fish_voice_id": !env_str("FISH_VOICE_ID").trim().is_empty() && !env_str("FISH_VOICE_ID").starts_with("your-"),
            "user_name": env_str("USER_NAME"),
        },
    })
}

async fn save_preferences(req: &Request) -> Result<Response, Response> {
    let body = match body(req) {
        Ok(b) => b,
        Err(r) => return Err(r),
    };
    let text = |k: &str, d: &str| body.get(k).and_then(Value::as_str).unwrap_or(d).to_string();
    let raw = text("stt_keywords", "");
    let keywords: Vec<&str> = raw.split(',').map(str::trim).filter(|t| !t.is_empty()).collect();
    let invalid = raw.chars().count() > 800
        || keywords.len() > 12
        || keywords.iter().any(|t| t.chars().count() > 64 || t.contains(['<', '>', '\r', '\n', '\0']));
    if invalid {
        return Ok(Response::json(400, &json!({ "error": "Use at most 12 comma-separated recognition terms, each 64 characters or less." })));
    }
    let joined = keywords.join(", ");
    for (key, value) in [("USER_NAME", text("user_name", "")), ("HONORIFIC", text("honorific", "sir")), ("JARVIS_STT_KEYWORDS", joined)] {
        if let Err(e) = settings::write_env_key(key, &value).await {
            return Ok(Response::json(500, &json!({ "error": e })));
        }
    }
    Ok(Response::ok(json!({ "success": true })))
}

async fn pc_command(req: &Request) -> Result<Response, Response> {
    if !settings::automation_enabled() {
        return Ok(Response::json(409, &json!({ "error": "Command execution is paused in AI Settings." })));
    }
    let body = match body(req) {
        Ok(b) => b,
        Err(r) => return Err(r),
    };
    let Some(text) = body.get("text").and_then(Value::as_str) else { return Err(missing("text")) };
    if text.chars().count() > 16000 {
        return Ok(Response::json(400, &json!({ "error": "Befehl zu lang." })));
    }
    Ok(match pc_control::parse(text) {
        Some(command) => Response::ok(json!({ "text": pc_control::execute(command).await })),
        None => Response::json(400, &json!({ "error": "Kein unterstützter PC-Befehl." })),
    })
}

fn launch(code: &str) -> Response {
    if !auth::redeem_dashboard_code(code) {
        return Response::html(410, "<!doctype html><meta charset=\"utf-8\"><title>Jarvis</title>\
<p>This dashboard link is invalid or has expired. Ask Jarvis to open the dashboard again.</p>".into())
            .with_header("Cache-Control", "no-store");
    }
    let token = serde_json::to_string(&auth::create_session_token()).unwrap_or_default();
    let page = format!("<!doctype html><meta charset=\"utf-8\"><title>Jarvis</title><script>localStorage.setItem(\"jarvis_auth_token\", {token});location.replace(\"/?dashboard=1\");</script>");
    Response::html(200, page).with_header("Cache-Control", "no-store").with_header("Referrer-Policy", "no-referrer")
}

fn static_file(relative: &str) -> Response {
    let safe = !relative.is_empty()
        && !relative.contains("..")
        && relative.chars().all(|c| c.is_ascii_alphanumeric() || "-_./".contains(c));
    if !safe {
        return Response::not_found();
    }
    let path = fs::join(&config::paths().frontend_dist(), relative);
    match fs::read(&path) {
        Some(body) => Response::new(200, content_type_for(relative), body),
        None => Response::not_found(),
    }
}
