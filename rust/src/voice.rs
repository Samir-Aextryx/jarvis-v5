//! `/ws/voice`: one voice conversation. Each final transcript starts a turn;
//! a newer turn or "stop" cancels the running one (barge-in).
//!
//! Client -> server: {"type":"transcript","text":"...","isFinal":true,"turn_id":"..."},
//! {"type":"stop"}, {"type":"fix_self"}, {"type":"playback_metrics",...}.
//! Server -> client: status, text, audio, pcm_*, latency, turn_start, stopped,
//! open_personal, task_* and phone_call_privacy messages.

use crate::apps::{self, App, OpenOptions};
use crate::autonomous::{self, Autonomous};
use crate::brain::{self, History, VoiceState};
use crate::host::{self, fs};
use crate::intents::{self, normalize_request};
use crate::llm::{Llm, Request, user_msg};
use crate::local_pc::{self, LocalPc};
use crate::memory::{self, dispatch};
use crate::speech::{self, Metrics, Out, StreamingSpeech, extract_action, is_banned_confirmation, remember_english, strip_markdown_for_tts};
use crate::util::{LocalTime, b64, b64_decode, s, take};
use crate::work::WorkSession;
use crate::ws::{Message, WebSocket};
use crate::{auth, calendar, config, notes, personal, privacy, settings, stt, tasks, websites};
use futures::future::{AbortHandle, abortable};
use serde_json::{Value, json};
use std::cell::{Cell, RefCell};
use std::rc::Rc;
use wasm_bindgen_futures::spawn_local;

thread_local! {
    static LAST_GREETING: Cell<f64> = const { Cell::new(0.0) };
}

/// State that outlives single turns.
struct Session {
    ws: Rc<WebSocket>,
    epoch: Rc<Cell<u64>>,
    history: History,
    state: Rc<VoiceState>,
    work: Rc<WorkSession>,
    local_pc: Rc<LocalPc>,
    autonomous: Rc<Autonomous>,
    last_response: RefCell<String>,
    summary: Rc<RefCell<String>>,
    summary_pending: Rc<Cell<bool>>,
    since_summary: Cell<u32>,
    summarized: Rc<Cell<usize>>,
    app_choices: RefCell<Vec<App>>,
    app_key: RefCell<Option<String>>,
}

pub async fn serve(ws: Rc<WebSocket>) {
    tasks::register(&ws);
    if privacy::active() {
        ws.send_json(&json!({ "type": "phone_call_privacy", "active": true, "session": privacy::session() }));
    }
    crate::info!("Voice WebSocket connected");
    let session = Rc::new(Session {
        ws: ws.clone(),
        epoch: Rc::new(Cell::new(0)),
        history: Rc::new(RefCell::new(Vec::new())),
        state: Rc::new(VoiceState::default()),
        work: WorkSession::new(),
        local_pc: LocalPc::new(),
        autonomous: Autonomous::new(),
        last_response: RefCell::new(String::new()),
        summary: Rc::new(RefCell::new(String::new())),
        summary_pending: Rc::new(Cell::new(false)),
        since_summary: Cell::new(0),
        summarized: Rc::new(Cell::new(0)),
        app_choices: RefCell::new(Vec::new()),
        app_key: RefCell::new(None),
    });
    let mut greeting: Option<AbortHandle> = None;
    if host::now_secs() - LAST_GREETING.with(Cell::get) > 60.0 && !privacy::active() {
        LAST_GREETING.with(|g| g.set(host::now_secs()));
        let (job, handle) = abortable(greet(session.clone()));
        spawn_local(async move {
            let _ = job.await;
        });
        greeting = Some(handle);
    }
    ws.send_json(&json!({ "type": "status", "state": "idle" }));
    let mut active: Option<AbortHandle> = None;
    let mut seen: Vec<String> = Vec::new();
    while let Some(message) = ws.recv().await {
        let Message::Text(raw) = message else { continue };
        let Ok(msg) = serde_json::from_str::<Value>(&raw) else { continue };
        if !msg.is_object() {
            continue;
        }
        let kind = s(&msg, "type");
        if kind == "phone_call_privacy_ready" {
            privacy::acknowledge(&ws, &msg["session"].as_str().map(str::to_string).unwrap_or_else(|| msg["session"].to_string()));
            continue;
        }
        if privacy::active() && kind == "transcript" {
            continue;
        }
        if kind == "playback_metrics" {
            brain::record_metrics(&msg);
            continue;
        }
        let is_final = kind == "transcript" && msg["isFinal"].as_bool().unwrap_or(false);
        if let Some(turn_id) = msg.get("turn_id").filter(|t| !t.is_null() && *t != false && *t != "")
            && kind == "transcript"
        {
            let Some(id) = turn_id.as_str().filter(|t| t.chars().count() <= 80) else { continue };
            if seen.iter().any(|x| x == id) {
                continue;
            }
            seen.push(id.to_string());
            if seen.len() > 256 {
                seen = vec![id.to_string()];
            }
        }
        let stop = kind == "stop"
            || (kind == "transcript"
                && crate::re!(r"(?i)^\s*(?:(?:jarvis|please)[, ]+)?(?:stop|stopp|stop talking|be quiet|quiet|halt)(?:[,.! ]+please)?[.!? ]*$").is_match(s(&msg, "text")));
        if !stop && kind != "fix_self" && !is_final {
            continue;
        }
        session.epoch.set(session.epoch.get() + 1);
        if let Some(g) = greeting.take() {
            g.abort();
        }
        if stop {
            session.local_pc.pending.borrow_mut().clear();
            if msg["cancelTasks"].as_bool().unwrap_or(false) || kind == "transcript" {
                // Signal Codex before dropping the turn that awaits it.
                session.autonomous.cancel().await;
                session.work.cancel();
                crate::pc_control::cancel_code();
            }
        }
        if let Some(a) = active.take() {
            a.abort();
        }
        if stop {
            ws.send_json(&json!({ "type": "stopped" }));
            continue;
        }
        let (job, handle) = abortable(turn(session.clone(), msg, session.epoch.get()));
        spawn_local(async move {
            let _ = job.await;
        });
        active = Some(handle);
    }
    crate::info!("Voice WebSocket disconnected");
    session.autonomous.cancel().await;
    if let Some(a) = active {
        a.abort();
    }
    if let Some(g) = greeting {
        g.abort();
    }
    tasks::unregister(&ws);
}

async fn greet(session: Rc<Session>) {
    let hour = LocalTime::now().hour;
    let greeting = if hour < 12 {
        "Good morning, sir."
    } else if hour < 17 {
        "Good afternoon, sir."
    } else {
        "Good evening, sir."
    };
    let mut spoken = greeting;
    if brain::openai_key_rejected().await {
        // Listening (and answering, with OpenAI selected) needs this key.
        spoken = if settings::active_provider().id == "openai" { brain::OPENAI_KEY_REJECTED_NOTICE } else { brain::OPENAI_STT_KEY_REJECTED_NOTICE };
    }
    let out = Out::always(session.ws.clone());
    match speech::synthesize(spoken).await {
        Some(audio) => {
            out.status("speaking");
            out.send(json!({ "type": "audio", "data": b64(&audio), "text": spoken }));
            session.history.borrow_mut().push(json!({ "role": "assistant", "content": spoken }));
            crate::info!("JARVIS: {spoken}");
            out.status("idle");
        }
        None if spoken != greeting => out.text(spoken),
        None => {}
    }
}

const SCREENSHOT: &str = r"(?i)^(?:screenshot|bildschirmfoto|(?:take|make)\s+a\s+screenshot|(?:mache?|nimm|erstelle)\s+(?:bitte\s+)?(?:einen\s+screenshot|ein\s+bildschirmfoto)(?:\s+auf)?|(?:screenshot|bildschirmfoto)\s+(?:machen|aufnehmen|erstellen))$";

/// What the turn decided to do, computed before any action runs.
struct Route {
    app_preference: Option<(String, String)>,
    explicit_memory: Option<String>,
    personal_panel: Option<&'static str>,
    autonomous_goal: Option<String>,
    autonomous_status: bool,
    local_command: bool,
    memory_open: bool,
    google_command: Option<Value>,
    website: Option<String>,
    pc_command: Option<crate::pc_control::Command>,
    direct_mail: Option<Value>,
    direct_message: Option<Value>,
    direct_pc_steps: Option<Vec<Value>>,
    screenshot: bool,
    call_boss: bool,
    routine_match: Option<(String, String)>,
    routine_execute: Option<String>,
    quit: bool,
    quick_app: Option<Vec<String>>,
    quick_app_choice: bool,
}

fn route(session: &Session, text: &str) -> Route {
    let normalized = normalize_request(text);
    let pending_local = !session.local_pc.pending.borrow().is_empty();
    let pending_auto = !session.autonomous.pending.borrow().is_empty();
    let autonomous_goal = autonomous::goal_request(text);
    let autonomous_status = ["task status", "autonomous status", "aufgabenstatus"].contains(&text.to_lowercase().trim_matches(['.', '!', '?', ' ']));
    let pc_request = local_pc::is_pc_request(text);
    let local_command = pending_local || pc_request || autonomous_goal.is_some() || pending_auto || autonomous_status;
    let memory_open = crate::re!(r"(?i)(?:öffne|zeige|open|show).*(?:gedächtnis|gedaechtnis|memory\.md|deine erinnerungen)").is_match(text);
    let google_command = crate::google::parse(text);
    let website = websites::parse_website_request(text);
    let pc_command = crate::pc_control::parse(text);
    let busy = pending_auto || pending_local;
    let direct_mail = if busy { None } else { crate::email::direct_mail_plan(text, &settings::default_email()) };
    let direct_message = if busy { None } else { intents::direct_message_plan(text) };
    let direct_pc_steps =
        if pc_request && !local_pc::is_email_request(text) && !(autonomous_goal.is_some() || busy) { intents::fast_plan(text) } else { None };
    let screenshot = regex_full(SCREENSHOT, normalized.trim_matches(['.', '!', '?', ' ']));
    let call_boss = crate::whatsapp::parse_call_request(text);
    let routine_match = crate::re!(r"(?is)^(?:train|learn|trainiere|lerne|merke(?:\s+dir)?)\s+(?:a\s+)?(?:routine|task|aufgabe)(?:\s+(?:called|named|namens))?\s+(.+?)\s*[:,]\s*(.+)$")
        .captures(&normalized)
        .map(|c| (c[1].to_string(), c[2].to_string()));
    let mut routine_execute = crate::re!(r"(?is)^(?:run|execute|starte|führe(?:\s+aus)?|mach(?:e)?|do)\s+(?:the\s+)?(?:routine|task|aufgabe|my)?\s*(.+)$")
        .captures(&normalized)
        .map(|c| c[1].to_string());
    // "Mach Outlook auf" opens an app and "Mach einen Screenshot" captures, never a routine.
    if routine_execute.is_some() && (screenshot || apps::parse_open_request(text).is_some()) {
        routine_execute = None;
    }
    let quit = crate::re!(r"(?i)^(?:close|quit|exit|beende)\s+(?:yourself|jarvis|dich)$").is_match(text.trim_matches(['.', '!', '?', ' ']));
    let quick_app = if !memory_open
        && pc_command.is_none()
        && google_command.is_none()
        && website.is_none()
        && !local_command
        && routine_execute.is_none()
        && routine_match.is_none()
    {
        apps::parse_open_request(text)
    } else {
        None
    };
    let choices = session.app_choices.borrow();
    let quick_app_choice = !choices.is_empty() && !apps::resolve_app(text, &choices).is_empty();
    Route {
        app_preference: apps::parse_app_preference(text),
        explicit_memory: personal::explicit_content(text),
        personal_panel: calendar::personal_panel_request(text),
        autonomous_goal,
        autonomous_status,
        local_command,
        memory_open,
        google_command,
        website,
        pc_command,
        direct_mail,
        direct_message,
        direct_pc_steps,
        screenshot,
        call_boss,
        routine_match,
        routine_execute,
        quit,
        quick_app,
        quick_app_choice,
    }
}

fn regex_full(pattern: &str, text: &str) -> bool {
    regex::Regex::new(pattern).map(|r| r.is_match(text)).unwrap_or(false)
}

async fn turn(session: Rc<Session>, msg: Value, epoch: u64) {
    let turn_id = msg["turn_id"].as_str().map(str::to_string);
    let out = Out::for_turn(session.ws.clone(), session.epoch.clone(), epoch, turn_id);
    let metrics = Metrics::new(out.clone());
    out.send(json!({ "type": "turn_start" }));
    if s(&msg, "type") == "fix_self" {
        session.work.start(&config::paths().resources, None);
        let reply = "Work mode active in my own repo, sir. Tell me what needs fixing.";
        out.status("speaking");
        match speech::synthesize(&strip_markdown_for_tts(reply)).await {
            Some(audio) => out.send(json!({ "type": "audio", "data": b64(&audio), "text": reply })),
            None => out.text(reply),
        }
        return;
    }
    let mut text = intents::apply_speech_corrections(&stt::clean_transcript(s(&msg, "text")));
    if privacy::active() || text.is_empty() {
        return;
    }
    if !settings::automation_enabled() && calendar::personal_panel_request(&text).is_none() {
        out.text("Command execution is paused in AI Settings. Stop and the personal views remain available.");
        out.status("idle");
        return;
    }
    metrics.mark("stt_final");
    let r = route(&session, &text);
    if !session.app_choices.borrow().is_empty() && !r.quick_app_choice && r.quick_app.is_none() {
        session.app_choices.borrow_mut().clear();
        *session.app_key.borrow_mut() = None;
    }
    session.state.last_user_time.set(host::now_secs());
    crate::info!("Command received ({} characters)", text.chars().count());
    out.status("thinking");

    let mut speech_stream: Option<StreamingSpeech> = None;
    let result = run_turn(&session, &out, &metrics, &msg, &mut text, &r, &mut speech_stream).await;
    match result {
        Ok((reply, llm_original, opened_app)) => {
            finish_turn(&session, &out, &metrics, &msg, &text, &r, reply, llm_original, opened_app, &mut speech_stream).await;
        }
        Err(e) => {
            crate::error!("Error: {e}");
            if let Some(stream) = speech_stream.as_mut()
                && stream.sent()
            {
                stream.close();
                out.send(json!({ "type": "pcm_end", "id": stream.id }));
                out.text("The response was interrupted by a connection error. Please try again.");
                return;
            }
            let fallback = "Something went wrong, sir.";
            let audio = speech::synthesize(fallback).await;
            out.send(json!({ "type": "audio", "data": audio.map(|a| b64(&a)).unwrap_or_default(), "text": fallback }));
        }
    }
    if let Some(stream) = speech_stream.as_mut() {
        stream.close();
    }
}

type TurnResult = Result<(String, Option<String>, Option<String>), String>;

#[allow(clippy::too_many_arguments)]
async fn run_turn(
    session: &Rc<Session>,
    out: &Out,
    metrics: &Rc<Metrics>,
    msg: &Value,
    text: &mut String,
    r: &Route,
    speech_stream: &mut Option<StreamingSpeech>,
) -> TurnResult {
    let t_lower = text.to_lowercase();
    let mut opened_app: Option<String> = None;
    let mut llm_original: Option<String> = None;
    let mut app_target = r.quick_app.clone();
    let mut selected_choices: Option<Vec<App>> = None;
    {
        let choices = session.app_choices.borrow();
        let probe = app_target.as_ref().map(|t| t.join(" ")).unwrap_or_else(|| text.clone());
        if !choices.is_empty() && !apps::resolve_app(&probe, &choices).is_empty() {
            if app_target.is_none() {
                app_target = Some(vec![text.clone()]);
            }
            selected_choices = Some(choices.clone());
        }
    }
    let pending_local = !session.local_pc.pending.borrow().is_empty();
    let pending_auto = !session.autonomous.pending.borrow().is_empty();
    let direct_action =
        app_target.is_some() || r.local_command || r.website.is_some() || r.google_command.is_some() || r.pc_command.is_some() || r.screenshot || r.call_boss;
    let measure = app_target.is_some()
        || r.website.is_some()
        || r.google_command.is_some()
        || r.pc_command.is_some()
        || r.screenshot
        || r.call_boss
        || r.direct_mail.is_some()
        || r.direct_message.is_some()
        || (pending_local && r.local_command);
    if measure {
        metrics.mark("automation_start");
    }
    let mut routed = json!({ "intent": null });
    let has_choices = !session.app_choices.borrow().is_empty();
    if !(r.quit
        || r.routine_match.is_some()
        || r.routine_execute.is_some()
        || r.app_preference.is_some()
        || r.explicit_memory.is_some()
        || r.personal_panel.is_some()
        || has_choices
        || pending_auto
        || pending_local
        || direct_action)
    {
        routed = crate::agent_router::route(text).await;
        if let Some(notice) = routed["notice"].as_str().filter(|n| !n.is_empty()) {
            out.text(notice);
        }
    }
    let intent = s(&routed, "intent").to_string();
    let previous = session.last_response.borrow().clone();
    let notify = session.ws.clone();
    let reply: String = if !settings::automation_enabled()
        && (r.local_command
            || app_target.is_some()
            || r.website.is_some()
            || r.pc_command.is_some()
            || r.google_command.is_some()
            || r.call_boss
            || r.routine_execute.is_some()
            || ["open_apps", "work_apps", "personal_update", "workflow"].contains(&intent.as_str()))
    {
        "Automatic tool execution is disabled in AI Settings.".into()
    } else if r.call_boss {
        crate::whatsapp::prepare_call_to_boss().await
    } else if ["error", "work_apps", "personal_update", "open_apps"].contains(&intent.as_str()) {
        crate::agent_router::execute(&routed).await
    } else if intent == "workflow" && !(r.local_command || app_target.is_some() || r.website.is_some() || r.pc_command.is_some() || r.google_command.is_some()) {
        session.autonomous.start(text, &previous, notify)
    } else if r.quit {
        let reply = "Shutting down, sir.";
        out.status("speaking");
        if let Some(audio) = speech::synthesize(reply).await {
            out.send(json!({ "type": "audio", "data": b64(&audio), "text": reply }));
        }
        host::sleep(300.0).await;
        host::exit(0);
        reply.into()
    } else if let Some((name, content)) = &r.routine_match {
        let _ = personal::save_routine(name, content.trim());
        format!("I have saved the routine: {}.", name.trim())
    } else if let Some(name) = &r.routine_execute {
        let wanted = name.trim().to_lowercase().replace('_', " ");
        let facts = personal::facts();
        let key_name = |f: &Value| s(f, "key").replace("routine_", "").replace('_', " ");
        let found = facts
            .iter()
            .find(|f| s(f, "kind") == "routine" && key_name(f) == wanted)
            .or_else(|| facts.iter().find(|f| s(f, "kind") == "routine" && s(f, "key").replace('_', " ").contains(&name.trim().to_lowercase())))
            .cloned();
        match found {
            Some(f) => {
                *text = s(&f, "content").to_string();
                match apps::parse_open_request(text) {
                    Some(targets) => apps::open_apps(&targets, OpenOptions { candidates: selected_choices.as_deref(), ..Default::default() }).await.confirmation,
                    None => session.autonomous.start(text, &previous, notify),
                }
            }
            None => format!("I could not find a routine named {}.", name.trim().to_lowercase()),
        }
    } else if let Some((alias, target)) = &r.app_preference {
        remember_english(&apps::save_app_preference(alias, target).await)
    } else if let Some(content) = &r.explicit_memory {
        let saved = personal::remember_explicit(content);
        remember_english(if saved {
            "Saved in my long-term memory."
        } else {
            "I did not save this. Please leave out passwords, keys and tokens and keep the note under 4000 characters."
        })
    } else if let Some(view) = r.personal_panel {
        out.send(json!({ "type": "open_personal", "view": view }));
        String::new()
    } else if r.screenshot {
        match crate::desktop::screenshot(false).await.and_then(|shot| b64_decode(&shot)) {
            Some(png) => {
                let path = fs::join(&crate::pc_control::desktop(), &format!("Jarvis-Screenshot-{}.png", LocalTime::now().stamp()));
                match fs::write(&path, &png) {
                    Ok(()) => remember_english("Screenshot saved to your Desktop."),
                    Err(_) => remember_english("I could not capture the screenshot."),
                }
            }
            None => remember_english("I could not capture the screenshot."),
        }
    } else if r.local_command {
        if r.autonomous_status {
            session.autonomous.status()
        } else if r.autonomous_goal.is_some()
            || pending_auto
            || (local_pc::is_pc_request(text) && !pending_local && !(r.direct_mail.is_some() || r.direct_message.is_some() || r.direct_pc_steps.is_some()))
        {
            if r.autonomous_goal.is_some() {
                session.autonomous.pending.borrow_mut().clear();
            }
            let goal = r.autonomous_goal.clone().unwrap_or_else(|| text.clone());
            session.autonomous.start(&goal, &previous, notify)
        } else {
            let reply = session.local_pc.execute(text, &previous, r.direct_pc_steps.clone()).await;
            if session.local_pc.last_action_silent.get() { String::new() } else { reply }
        }
    } else if let Some(target) = &r.website {
        if target == "jarvis:dashboard" {
            // Chrome's command line is readable by other processes; hand it a single-use code.
            let url = format!("http://127.0.0.1:{}/launch/{}", config::port(), auth::create_dashboard_code());
            let reply = websites::open_website(&url).await;
            if reply.starts_with("Opening ") { remember_english("Opening your Jarvis dashboard in Chrome.") } else { reply }
        } else {
            websites::open_website(target).await
        }
    } else if let Some(command) = &r.google_command {
        crate::google::execute(command).await
    } else if let Some(command) = &r.pc_command {
        crate::pc_control::execute(command.clone()).await
    } else if r.memory_open {
        open_memory();
        "Ich öffne meine MEMORY.md mit deinen gespeicherten Infos.".into()
    } else if let Some(targets) = &app_target {
        let remember_as = if selected_choices.is_some() { session.app_key.borrow().clone() } else { None };
        let result = apps::open_apps(
            targets,
            OpenOptions { candidates: selected_choices.as_deref(), remember_as: remember_as.as_deref(), wait_until_ready: false },
        )
        .await;
        *session.app_key.borrow_mut() = result.preference_key.clone();
        if result.success {
            opened_app = result.app.clone();
        }
        *session.app_choices.borrow_mut() = result.candidates.clone();
        result.confirmation
    } else if ["quit work mode", "exit work mode", "go back to chat", "regular mode", "stop working"].iter().any(|w| t_lower.contains(w)) {
        if session.work.active() {
            session.work.stop();
            "Back to conversation mode, sir.".into()
        } else {
            "Already in conversation mode, sir.".into()
        }
    } else if session.work.active() {
        work_mode_reply(session, out, text).await?
    } else if let Some(action) = intents::detect_action_fast(text) {
        fast_action(session, out, action).await
    } else {
        let Some(llm) = Llm::active() else { return Ok(("API key not configured.".into(), None, None)) };
        if msg["streamAudio"].as_bool().unwrap_or(false) && !crate::vault::get("FISH_API_KEY").is_empty() {
            *speech_stream = Some(StreamingSpeech::new(out.clone(), metrics.clone()));
        }
        let history = session.history.borrow().clone();
        let summary = session.summary.borrow().clone();
        let reply = brain::generate_response(&llm, text, &history, &previous, &summary, speech_stream.as_mut()).await?;
        let (clean, action) = extract_action(&reply);
        llm_original = Some(clean.clone());
        match action {
            None => reply,
            Some((action, target)) => {
                crate::info!("LLM embedded action: {action}");
                if let Some(mut stream) = speech_stream.take() {
                    stream.abort();
                }
                let mut reply = if clean.trim().is_empty() || is_banned_confirmation(&clean) { String::new() } else { clean };
                if let Some(r2) = embedded_action(session, out, &action, &target, &mut opened_app).await {
                    reply = r2;
                }
                reply
            }
        }
    };
    if measure {
        metrics.mark("automation_complete");
    }
    Ok((reply, llm_original, opened_app))
}

async fn work_mode_reply(session: &Rc<Session>, out: &Out, text: &str) -> Result<String, String> {
    if intents::is_casual_question(text) {
        let Some(llm) = Llm::active() else { return Ok("API key not configured.".into()) };
        let history = session.history.borrow().clone();
        let previous = session.last_response.borrow().clone();
        let summary = session.summary.borrow().clone();
        return brain::generate_response(&llm, text, &history, &previous, &summary, None).await;
    }
    out.status("working");
    crate::info!("Work mode → Codex project task: {}", take(text, 80));
    let mut full = session.work.send(text).await;
    let llm = Llm::active();
    if !full.is_empty() && llm.is_some() {
        const STALL: &[&str] = &[
            "which option", "would you prefer", "would you like me to", "before I proceed", "before proceeding", "should I", "do you want me to",
            "let me know", "please confirm", "which approach", "what would you",
        ];
        let lower = full.to_lowercase();
        if STALL.iter().any(|w| lower.contains(w)) && session.work.message_count.get() >= 2 {
            crate::info!("Codex stalling — pushing to build");
            let push = session
                .work
                .send("Stop asking questions. Use your best judgment and start building now. Write the actual code files. Go with the simplest reasonable approach.")
                .await;
            if !push.is_empty() {
                full = push;
            }
        }
    }
    if let Some(m) = crate::re!(r"https?://localhost:\d+").find(&full) {
        websites::browse(m.as_str());
        crate::info!("Auto-opening {}", m.as_str());
    }
    match llm {
        Some(llm) if !full.is_empty() => {
            let system = format!(
                "You are JARVIS reporting to the user ({}). Summarize what happened in 1-2 sentences. Speak in first person — 'I built', 'I found', 'I set up'. You are talking TO THE USER, not to a coding tool. NEVER give instructions like 'go ahead and build' or 'set up the frontend' — those are NOT for the user. NEVER say 'Codex'. NEVER output [ACTION:...] tags. NEVER read out URLs. No markdown. British precision.",
                config::user_name()
            );
            Ok(llm
                .create(&Request::new(&system, vec![user_msg(&format!("Codex reported:\n{}", take(&full, 2000)))], 100))
                .await
                .unwrap_or_else(|_| take(&full, 200)))
        }
        _ => Ok(full),
    }
}

async fn fast_action(session: &Rc<Session>, out: &Out, action: &str) -> String {
    let bg = |kind: &'static str, fut: std::pin::Pin<Box<dyn std::future::Future<Output = String>>>| {
        spawn_local(brain::lookup_and_report(kind, fut, out.clone(), session.history.clone(), session.state.clone()));
        String::new()
    };
    match action {
        "open_terminal" => websites::open_terminal(),
        "show_recent" => brain::show_recent(),
        "describe_screen" => bg("screen", Box::pin(brain::screen_lookup())),
        "check_calendar" => bg("calendar", Box::pin(brain::calendar_lookup())),
        "check_mail" => bg("mail", Box::pin(brain::mail_lookup())),
        "check_notes" => bg("notes", Box::pin(brain::notes_lookup())),
        "check_tickets" => bg("tickets", Box::pin(brain::tickets_lookup())),
        "check_dispatch" => match dispatch::most_recent() {
            None => "No recent builds on record, sir.".into(),
            Some(recent) => {
                let name = s(&recent, "project_name");
                match s(&recent, "status") {
                    "building" | "pending" => {
                        let elapsed = (host::now_secs() - recent["updated_at"].as_f64().unwrap_or(0.0)) as i64;
                        format!("Still working on {name}, sir. Been at it for {elapsed} seconds.")
                    }
                    "completed" => {
                        let summary = s(&recent, "summary");
                        if summary.is_empty() { format!("{name} is complete, sir.") } else { summary.to_string() }
                    }
                    "failed" | "timeout" => format!("{name} ran into problems, sir."),
                    other => format!("{name} is {other}, sir."),
                }
            }
        },
        "check_tasks" => memory::format_tasks_for_voice(&memory::open_tasks()),
        "check_usage" => settings::usage_summary(),
        _ => String::new(),
    }
}

/// Runs an `[ACTION:X]` tag from the model; Some(text) replaces the reply.
async fn embedded_action(session: &Rc<Session>, out: &Out, action: &str, target: &str, opened_app: &mut Option<String>) -> Option<String> {
    let (history, state) = (session.history.clone(), session.state.clone());
    match action {
        "build" => {
            let (name, path) = brain::create_build_project(target, None);
            brain::remember_built(&name, &path);
            brain::spawn_build(name, path, target.to_string(), target, out.clone(), history, state);
        }
        "open_app" => {
            let result = apps::open_app(target, OpenOptions::default()).await;
            if result.success {
                *opened_app = result.app.clone();
            }
            *session.app_choices.borrow_mut() = result.candidates.clone();
            return Some(result.confirmation);
        }
        "browse" => websites::browse(target),
        "research" => {
            let name = websites::generate_project_name(target);
            let path = fs::join(&config::paths().desktop, &name);
            let _ = fs::mkdirp(&path);
            session.work.start(&path, None);
            spawn_local(brain::self_work_and_notify(session.work.clone(), target.to_string(), out.clone()));
        }
        "open_terminal" => {
            websites::open_terminal();
        }
        "prompt_project" => match target.split_once("|||") {
            Some((project, prompt)) => {
                let (project, prompt) = (project.trim().to_string(), prompt.trim().to_string());
                if let Some(recent) = dispatch::recent_for_project(&project, 300.0).filter(|r| !s(r, "summary").is_empty()) {
                    crate::info!("Using recent dispatch result for {project} instead of re-dispatching");
                    history.borrow_mut().push(json!({ "role": "assistant", "content": format!("[Previous dispatch result for {project}]: {}", s(&recent, "summary")) }));
                    return Some(s(&recent, "summary").to_string());
                }
                spawn_local(brain::execute_prompt_project(project, prompt, out.clone(), None, history, state));
            }
            None => crate::warn!("PROMPT_PROJECT missing ||| delimiter: {target}"),
        },
        "add_task" => {
            let parts: Vec<&str> = target.split("|||").collect();
            if parts.len() >= 2 {
                let priority = if parts[0].trim().is_empty() { "medium" } else { parts[0].trim() };
                let title = parts[1].trim();
                let _ = memory::create_task(title, parts.get(2).map(|p| p.trim()).unwrap_or(""), priority, parts.get(3).map(|p| p.trim()).unwrap_or(""));
                crate::info!("Task created: {title}");
            }
        }
        "add_note" => {
            match target.split_once("|||") {
                Some((topic, content)) => {
                    let _ = memory::create_note(content.trim(), "", topic.trim());
                    let _ = notes::create(topic.trim(), content.trim(), "Notes", None);
                }
                None => {
                    let _ = memory::create_note(target, "", "");
                    let _ = notes::create("Note", target.trim(), "Notes", None);
                }
            }
            crate::info!("Note created");
        }
        "complete_task" => {
            if let Ok(id) = target.trim().parse::<i64>() {
                memory::complete_task(id);
                crate::info!("Task {id} completed");
            }
        }
        "remember" => {
            let _ = memory::remember(target.trim(), "fact", "", 7);
        }
        "create_note" => {
            let (title, body) = target.split_once("|||").map(|(t, b)| (t.trim(), b.trim())).unwrap_or(("JARVIS Note", target));
            let _ = notes::create(title, body, "Notes", None);
            crate::info!("Local note created: {title}");
        }
        "screen" => {
            spawn_local(brain::lookup_and_report("screen", brain::screen_lookup(), out.clone(), history, state));
        }
        "read_note" => {
            let term = target.trim().to_string();
            let out = out.clone();
            spawn_local(async move {
                let msg = match notes::read(&term) {
                    Some(note) => format!("Sir, your note '{}' says: {}", s(&note, "title"), take(s(&note, "body"), 200)),
                    None => format!("Couldn't find a note matching '{term}', sir."),
                };
                if let Some(audio) = speech::synthesize(&strip_markdown_for_tts(&msg)).await {
                    out.status("speaking");
                    out.send(json!({ "type": "audio", "data": b64(&audio), "text": msg }));
                }
            });
        }
        _ => {}
    }
    None
}

#[allow(clippy::too_many_arguments)]
async fn finish_turn(
    session: &Rc<Session>,
    out: &Out,
    metrics: &Rc<Metrics>,
    msg: &Value,
    text: &str,
    r: &Route,
    reply: String,
    llm_original: Option<String>,
    opened_app: Option<String>,
    speech_stream: &mut Option<StreamingSpeech>,
) {
    {
        let mut history = session.history.borrow_mut();
        history.push(json!({ "role": "user", "content": text }));
        history.push(json!({ "role": "assistant", "content": reply }));
        // An always-on socket must not retain the whole session; the summary keeps older context.
        if history.len() > 100 {
            let removed = history.len() - 100;
            history.drain(..removed);
            session.summarized.set(session.summarized.get().saturating_sub(removed));
        }
    }
    session.since_summary.set(session.since_summary.get() + 1);
    let len = session.history.borrow().len();
    if session.since_summary.get() >= 5 && len > 20 && !session.summary_pending.get() && !r.local_command {
        session.summary_pending.set(true);
        session.since_summary.set(0);
        let end = (len - 20).min(session.summarized.get() + 20);
        let rotated: Vec<Value> = session.history.borrow()[session.summarized.get().min(end)..end].to_vec();
        match Llm::active().filter(|_| !rotated.is_empty()) {
            Some(llm) => {
                let (summary, pending, summarized) = (session.summary.clone(), session.summary_pending.clone(), session.summarized.clone());
                spawn_local(async move {
                    let old = summary.borrow().clone();
                    if let Ok(updated) = brain::update_session_summary(&llm, &old, &rotated).await {
                        *summary.borrow_mut() = updated;
                        summarized.set(end);
                    }
                    pending.set(false);
                });
            }
            None => session.summary_pending.set(false),
        }
    }
    let learn = !(r.quick_app.is_some() || r.quick_app_choice || r.memory_open || r.pc_command.is_some() || r.google_command.is_some() || r.website.is_some() || r.local_command);
    spawn_local(brain::save_personal_turn(text.to_string(), opened_app, session.state.last_user_time.get(), learn));
    let tts = strip_markdown_for_tts(&reply);
    if tts.trim().is_empty() || is_banned_confirmation(&tts) {
        if let Some(stream) = speech_stream.as_mut() {
            stream.close();
        }
        out.status("idle");
        crate::info!("Response completed (audio suppressed)");
        *session.last_response.borrow_mut() = reply;
        return;
    }
    out.status("speaking");
    let streamed = match speech_stream.as_mut() {
        Some(stream) => {
            if let Some(original) = &llm_original
                && strip_markdown_for_tts(original).trim() != tts.trim()
            {
                for phrase in stream.buffer.push("", true) {
                    stream.enqueue(phrase);
                }
                stream.enqueue(tts.clone());
            }
            match stream.finish().await {
                Ok(sent) => sent,
                Err(e) => {
                    crate::error!("Error: {e}");
                    if stream.sent() {
                        stream.close();
                        out.send(json!({ "type": "pcm_end", "id": stream.id }));
                        out.text("The response was interrupted by a connection error. Please try again.");
                        return;
                    }
                    false
                }
            }
        }
        None if msg["streamAudio"].as_bool().unwrap_or(false) => speech::stream_speech(out, &tts, Some(metrics)).await,
        None => false,
    };
    if !streamed {
        match speech::synthesize(&tts).await {
            Some(audio) => out.send(json!({ "type": "audio", "data": b64(&audio), "text": reply })),
            None => {
                out.text(&reply);
                out.status("idle");
            }
        }
    }
    crate::info!("Response completed");
    *session.last_response.borrow_mut() = reply;
}

/// Opens MEMORY.md in its default editor (Notepad as fallback).
pub fn open_memory() {
    let path = personal::path();
    let _ = personal::export();
    if !host::shell_open(&path) {
        let notepad = format!("{}\\notepad.exe", config::get_or("SYSTEMROOT", "C:\\Windows"));
        host::spawn_detached(&notepad, &[&path], json!({ "hide": false }));
    }
}
