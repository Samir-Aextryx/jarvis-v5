//! Speech recognition: the authenticated live PCM relay to OpenAI Realtime
//! (the API key never leaves the backend) and the file fallback.

use crate::config;
use crate::host::{Http, Res, WsClient, WsMessage};
use crate::http::{Request, Response};
use crate::privacy;
use crate::speech::with_timeout;
use crate::util::b64;
use crate::vault;
use crate::ws::{Message, WebSocket};
use futures::future::{Either, select};
use serde_json::{Value, json};
use std::cell::RefCell;
use std::collections::{HashMap, HashSet, VecDeque};
use std::rc::Rc;

/// Rejects hallucinations on noise: foreign scripts, subtitle artifacts, prompt echoes.
pub fn clean_transcript(text: &str) -> String {
    let cleaned = text.trim();
    if cleaned.is_empty() {
        return String::new();
    }
    let foreign = crate::re!(
        r"[\x{0400}-\x{04ff}\x{0600}-\x{06ff}\x{0590}-\x{05ff}\x{0e00}-\x{0e7f}\x{3040}-\x{30ff}\x{3400}-\x{4dbf}\x{4e00}-\x{9fff}\x{ac00}-\x{d7af}\x{f900}-\x{faff}]"
    );
    if foreign.is_match(cleaned) {
        return String::new();
    }
    let subtitle = crate::re!(
        r"(?i)^\s*(?:thanks?\s+for\s+watching.*|subtitles\s+by.*|translated\s+by.*|like\s+and\s+subscribe.*|subscribe\s+to\s+my\s+channel.*)[\s.!]*$"
    );
    if subtitle.is_match(cleaned) {
        return String::new();
    }
    let normalized: String = cleaned.to_lowercase().chars().filter(|c| c.is_ascii_lowercase()).collect();
    if (normalized.starts_with("windowsappnamen") || normalized.starts_with("windowsappnames"))
        && ["outlook", "whatsapp", "snapchat", "mullvad", "forticlient"].iter().all(|n| normalized.contains(n))
    {
        return String::new();
    }
    cleaned.to_string()
}

/// Shared vocabulary hints for live, fallback and phone recognition.
pub fn transcription_keywords() -> Vec<String> {
    let common = [
        "JARVIS", "ChatGPT", "Claude", "Codex", "Outlook", "Gmail", "E-Mail", "email", "Betreff", "Google Calendar",
        "Microsoft Teams", "WhatsApp", "Snapchat", "Proton VPN", "Mullvad VPN", "FortiClient",
    ];
    let mut terms = vec![config::get_or("USER_NAME", "")];
    terms.extend(config::get_or("JARVIS_STT_KEYWORDS", "").split(',').map(str::to_string));
    terms.extend(common.iter().map(|s| s.to_string()));
    let mut cleaned: Vec<String> = Vec::new();
    let mut seen = HashSet::new();
    for term in terms {
        if term.contains(['<', '>', '\r', '\n']) {
            continue;
        }
        let term = crate::util::collapse_ws(&term);
        if !term.is_empty() && term.chars().count() <= 64 && seen.insert(term.to_lowercase()) {
            cleaned.push(term);
        }
        if cleaned.len() >= 24 {
            break;
        }
    }
    cleaned
}

fn session_update(delay: Option<&str>) -> Value {
    let allowed = ["minimal", "low", "medium", "high", "xhigh"];
    let configured = config::get_or("JARVIS_STT_DELAY", "minimal");
    let delay = delay.filter(|d| allowed.contains(d)).map(str::to_string).unwrap_or(configured);
    let delay = if allowed.contains(&delay.as_str()) { delay } else { "minimal".into() };
    json!({ "type": "session.update", "session": { "type": "transcription", "audio": { "input": {
        "format": { "type": "audio/pcm", "rate": 24000 },
        "transcription": {
            "model": config::get_or("OPENAI_REALTIME_TRANSCRIBE_MODEL", "gpt-live-transcribe"),
            "prompt": "Live voice commands and everyday conversations with JARVIS about meetings, routines, apps and email. Recognize natural German and English commands to open Outlook, including \"Outlook öffnen\", \"mach Outlook auf\", \"open my Outlook\" and \"open the Outlook app\". Treat \"schreib/verfasse eine E-Mail in Outlook\" and \"write/draft an email in Outlook\" as email-draft requests. Preserve recipient names, subject lines and dictated message text exactly; do not translate or paraphrase them.",
            "keywords": transcription_keywords(), "languages": ["en", "de"], "delay": delay
        },
        "turn_detection": null } } } })
}

#[derive(Default)]
struct Turns {
    current: Option<String>,
    pending: VecDeque<String>,
    items: HashMap<String, String>,
    completed: HashSet<String>,
    audio_bytes: usize,
}

pub async fn serve(ws: Rc<WebSocket>) {
    if privacy::active() {
        ws.close(4004, "");
        return;
    }
    let delay = ws.protocols.iter().find_map(|p| p.strip_prefix("jarvis.stt.delay.")).map(str::to_string);
    let result = relay(&ws, delay.as_deref()).await;
    if result.is_err() {
        ws.send_json(&json!({ "type": "error",
            "message": "Live speech recognition disconnected. Switching to fallback; please repeat the last request." }));
    }
    ws.close(1000, "");
}

async fn relay(ws: &Rc<WebSocket>, delay: Option<&str>) -> Res<()> {
    let key = vault::get("OPENAI_API_KEY");
    let auth = format!("Bearer {key}");
    let upstream = WsClient::connect("wss://api.openai.com/v1/realtime?intent=transcription", &[], &[("Authorization", &auth)], 12_000.0).await?;
    upstream.send_json(&session_update(delay));
    with_timeout(15_000.0, async {
        loop {
            let Some(WsMessage::Text(raw)) = upstream.recv().await? else { return Err("closed".to_string()) };
            let event: Value = serde_json::from_str(&raw).unwrap_or(Value::Null);
            match event["type"].as_str() {
                Some("error") => return Err("Realtime transcription configuration was rejected.".into()),
                Some("session.updated") => return Ok(()),
                _ => {}
            }
        }
    })
    .await??;
    ws.send_json(&json!({ "type": "ready" }));
    let turns = RefCell::new(Turns::default());
    let upload = async {
        loop {
            let Some(packet) = ws.recv().await else { return Ok(()) };
            if privacy::active() {
                ws.close(4004, "");
                return Ok(());
            }
            match packet {
                Message::Binary(frame) => {
                    let mut t = turns.borrow_mut();
                    if t.current.is_none() || frame.is_empty() || frame.len() > 4800 || frame.len() % 2 == 1 {
                        return Err("Invalid audio frame".to_string());
                    }
                    t.audio_bytes += frame.len();
                    if t.audio_bytes > 24000 * 2 * 125 {
                        return Err("Audio turn exceeded its limit".into());
                    }
                    drop(t);
                    upstream.send_json(&json!({ "type": "input_audio_buffer.append", "audio": b64(&frame) }));
                }
                Message::Text(text) => {
                    let message: Value = serde_json::from_str(&text).unwrap_or(Value::Null);
                    let id = message["id"].as_str().unwrap_or("").to_string();
                    let mut t = turns.borrow_mut();
                    match message["type"].as_str() {
                        Some("start") => {
                            if t.current.is_some() || t.pending.len() >= 8 || !crate::re!(r"^[A-Za-z0-9_-]{1,80}$").is_match(&id) {
                                return Err("Invalid audio turn".into());
                            }
                            t.current = Some(id);
                            t.audio_bytes = 0;
                        }
                        Some("commit") => {
                            if t.current.as_deref() != Some(id.as_str()) || t.audio_bytes < 4800 {
                                return Err("Audio turn is too short".into());
                            }
                            t.current = None;
                            t.pending.push_back(id);
                            drop(t);
                            upstream.send_json(&json!({ "type": "input_audio_buffer.commit" }));
                        }
                        _ => return Err("Unknown audio command".into()),
                    }
                }
            }
        }
    };
    let download = async {
        while let Some(message) = upstream.recv().await? {
            let WsMessage::Text(raw) = message else { continue };
            let event: Value = serde_json::from_str(&raw).unwrap_or(Value::Null);
            let kind = event["type"].as_str().unwrap_or("");
            let item = event["item_id"].as_str().unwrap_or("").to_string();
            if kind == "error" || kind.ends_with("transcription.failed") {
                return Err("Live transcription failed. Please repeat the request.".to_string());
            }
            let mut t = turns.borrow_mut();
            if kind == "input_audio_buffer.committed" {
                let turn = t.pending.pop_front().ok_or("Unexpected committed transcript")?;
                t.items.insert(item.clone(), turn);
            }
            if kind.ends_with("input_audio_transcription.delta") {
                let turn = t.items.get(&item).cloned().or_else(|| t.pending.front().cloned()).or_else(|| t.current.clone());
                if let Some(turn) = turn {
                    ws.send_json(&json!({ "type": "partial", "id": turn, "text": event["delta"].as_str().unwrap_or("") }));
                }
            }
            if kind.ends_with("input_audio_transcription.completed") && !t.completed.contains(&item) {
                let turn = t.items.remove(&item).ok_or("Transcript order could not be verified")?;
                t.completed.insert(item.clone());
                if t.completed.len() > 256 {
                    t.completed.clear();
                    t.completed.insert(item);
                }
                ws.send_json(&json!({ "type": "final", "id": turn,
                    "text": clean_transcript(event["transcript"].as_str().unwrap_or("")) }));
            }
        }
        Ok(())
    };
    match select(Box::pin(upload), Box::pin(download)).await {
        Either::Left((r, _)) | Either::Right((r, _)) => r,
    }
}

// ---- file transcription fallback -----------------------------------------------------------

fn file_transcription_fields() -> Vec<(String, String)> {
    let model = config::get_or("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe");
    let mut fields = vec![("model".to_string(), model.clone())];
    // Empty means detect the input language; English-only speech must never force English recognition.
    let language = config::get_or("OPENAI_TRANSCRIBE_LANGUAGE", "").trim().to_lowercase();
    let two_letter = crate::re!(r"^[a-z]{2}$").is_match(&language);
    if model == "gpt-transcribe" {
        let languages = if two_letter { vec![language.clone()] } else { vec!["en".into(), "de".into()] };
        fields.push(("prompt".into(), crate::util::take(&transcription_keywords().join(", "), 600)));
        fields.extend(languages.into_iter().map(|l| ("languages[]".to_string(), l)));
        fields.extend(transcription_keywords().into_iter().map(|k| ("keywords[]".to_string(), k)));
        return fields;
    }
    if two_letter {
        fields.push(("language".into(), language));
    }
    if model != "gpt-4o-transcribe-diarize" {
        fields.push(("prompt".into(), crate::util::take(&transcription_keywords().join(", "), 600)));
    }
    fields
}

pub fn multipart(fields: &[(String, String)], file: (&str, &str, &[u8])) -> (String, Vec<u8>) {
    let boundary = format!("----jarvis{}", crate::util::uuid_hex());
    let mut body = Vec::new();
    for (name, value) in fields {
        body.extend_from_slice(format!("--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n").as_bytes());
    }
    let (filename, content_type, data) = file;
    body.extend_from_slice(
        format!("--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: {content_type}\r\n\r\n").as_bytes(),
    );
    body.extend_from_slice(data);
    body.extend_from_slice(format!("\r\n--{boundary}--\r\n").as_bytes());
    (format!("multipart/form-data; boundary={boundary}"), body)
}

pub async fn transcribe(req: Request) -> Response {
    const PRIVATE: &str = "Desktop microphone is disabled during a phone call.";
    if privacy::active() {
        return Response::error(423, PRIVATE);
    }
    let key = vault::get("OPENAI_API_KEY");
    if key.is_empty() {
        return Response::error(503, "OpenAI API-Schlüssel fehlt.");
    }
    let content_type = req.content_type();
    let ext = match content_type.as_str() {
        "audio/webm" => "webm",
        "audio/mpeg" => "mp3",
        "audio/wav" => "wav",
        _ => return Response::error(415, "Audioformat nicht unterstützt."),
    };
    if req.body.len() > 20 * 1024 * 1024 {
        return Response::error(413, "Aufnahme zu groß.");
    }
    if req.body.is_empty() {
        return Response::error(400, "Aufnahme ist leer.");
    }
    let filename = format!("speech.{ext}");
    let (ct, body) = multipart(&file_transcription_fields(), (&filename, &content_type, &req.body));
    let result = Http::post("https://api.openai.com/v1/audio/transcriptions").bearer(&key).timeout(60.0).body(&ct, body).send().await;
    if privacy::active() {
        return Response::error(423, PRIVATE);
    }
    let mut response = match result {
        Ok(r) => r,
        Err(_) => return Response::error(502, "OpenAI-Spracherkennung: nicht erreichbar"),
    };
    if response.status == 401 {
        return Response::error(502, "OpenAI hat den API-Schlüssel abgelehnt. Bitte in Settings unter Voice & AI keys einen neuen Schlüssel speichern.");
    }
    if !response.ok() {
        return Response::error(502, &format!("OpenAI-Spracherkennung: HTTP {}", response.status));
    }
    let data = response.json().await.unwrap_or(Value::Null);
    Response::ok(json!({ "text": clean_transcript(data["text"].as_str().unwrap_or("")) }))
}
