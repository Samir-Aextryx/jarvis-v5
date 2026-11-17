//! Google desktop OAuth (PKCE, loopback redirect to the Jarvis server) and
//! explicit Gmail, Calendar, Drive, Tasks and Contacts commands. The OAuth
//! client and tokens stay in Windows Credential Manager under the same
//! service and format as the Python version, so existing sign-ins keep working.

use crate::calendar::{self, Outcome, event_fields, moment, operation_allowed};
use crate::email::{draft_fields, ensure_email_recipient_allowed, recipient_authorized, send_requested};
use crate::host::{self, Http, Res, url_encode};
use crate::timezone::{civil_from_days, parse_moment, zone};
use crate::util::{b64, b64url, sha256_hex, take, token_urlsafe, uuid_hex};
use crate::vault;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::cell::RefCell;
use std::collections::HashMap;

pub const SCOPES: &[(&str, &str)] = &[
    ("calendar_write", "https://www.googleapis.com/auth/calendar.events"),
    ("gmail_send", "https://www.googleapis.com/auth/gmail.send"),
    ("gmail_drafts", "https://www.googleapis.com/auth/gmail.compose"),
    ("gmail", "https://www.googleapis.com/auth/gmail.readonly"),
    ("calendar", "https://www.googleapis.com/auth/calendar.readonly"),
    ("drive", "https://www.googleapis.com/auth/drive.readonly"),
    ("tasks", "https://www.googleapis.com/auth/tasks.readonly"),
    ("contacts", "https://www.googleapis.com/auth/contacts.readonly"),
];

const WEB_APPS: &[(&str, &str)] = &[
    ("gmail", "https://mail.google.com/"),
    ("google calendar", "https://calendar.google.com/"),
    ("google kalender", "https://calendar.google.com/"),
    ("google drive", "https://drive.google.com/"),
    ("google docs", "https://docs.google.com/"),
    ("google sheets", "https://sheets.google.com/"),
    ("google slides", "https://slides.google.com/"),
    ("google keep", "https://keep.google.com/"),
    ("google maps", "https://maps.google.com/"),
    ("google photos", "https://photos.google.com/"),
    ("google kontakte", "https://contacts.google.com/"),
    ("google contacts", "https://contacts.google.com/"),
    ("youtube", "https://www.youtube.com/"),
];

const AUTH_URI: &str = "https://accounts.google.com/o/oauth2/auth";
const TOKEN_URI: &str = "https://oauth2.googleapis.com/token";
const GMAIL: &str = "https://gmail.googleapis.com/gmail/v1/users/me";
const LOGIN_TIMEOUT_SECS: f64 = 300.0;
const SIGN_IN_FAILED: &str = "Google sign-in did not complete. Check the OAuth client, enabled APIs, test users and selected permissions, then retry.";

fn scope(service: &str) -> Option<&'static str> {
    SCOPES.iter().find(|(k, _)| *k == service).map(|(_, v)| *v)
}

struct Login {
    state: String,
    verifier: String,
    redirect: String,
    started: f64,
}

#[derive(Default)]
struct Store {
    client: Option<Value>,
    tokens: Option<Value>,
    api_key: Option<String>,
    login: Option<Login>,
    error: String,
    contacts: HashMap<(String, String), (f64, Vec<Value>)>,
}

thread_local! {
    static STORE: RefCell<Store> = RefCell::new(Store::default());
}

fn with<T>(f: impl FnOnce(&mut Store) -> T) -> T {
    STORE.with(|s| f(&mut s.borrow_mut()))
}

fn service_name() -> String {
    vault::google_service_name()
}

/// Loads the stored client, tokens and API key once at startup.
pub async fn init() {
    let service = service_name();
    let client = vault::get_json(&service, "client").await.filter(Value::is_object);
    let tokens = vault::get_json(&service, "tokens").await.filter(Value::is_object);
    let api_key = vault::get_json(&service, "api-key").await.and_then(|v| v.as_str().map(str::to_string)).filter(|k| !k.is_empty());
    with(|s| {
        s.client = client;
        s.tokens = tokens;
        s.api_key = api_key;
    });
}

/// keyring stores Python's `json.dumps(value)`; `None` becomes `null`.
async fn persist(name: &str, value: &Value) -> Res<()> {
    vault::set_password(&service_name(), name, &value.to_string()).await
}

fn login_active(s: &Store) -> bool {
    s.login.as_ref().is_some_and(|l| host::now_secs() - l.started < LOGIN_TIMEOUT_SECS)
}

pub fn status() -> Value {
    with(|s| {
        let services = s.client.as_ref().map(|c| c["services"].clone()).filter(Value::is_array).unwrap_or(json!([]));
        json!({
            "configured": s.client.is_some(), "connected": s.tokens.is_some(), "connecting": login_active(s),
            "services": services, "error": s.error, "api_key_set": s.api_key.is_some(),
        })
    })
}

fn services_of(s: &Store) -> Vec<String> {
    s.client.as_ref().and_then(|c| c["services"].as_array()).map(|a| a.iter().filter_map(Value::as_str).map(str::to_string).collect()).unwrap_or_default()
}

pub async fn configure(config: &Value, services: &[String]) -> Res<Value> {
    if with(|s| login_active(s)) {
        return Err("Finish the current Google sign-in first.".into());
    }
    let installed = &config["installed"];
    let client_id = installed["client_id"].as_str().unwrap_or("");
    let secret = installed["client_secret"].as_str();
    if !crate::re!(r"^[A-Za-z0-9_-]+\.apps\.googleusercontent\.com$").is_match(client_id) || !secret.is_some_and(|s| (1..=500).contains(&s.chars().count())) {
        return Err("Import a Google OAuth client JSON for a Desktop app. An API key is not sufficient.".into());
    }
    if services.is_empty() || services.iter().any(|s| scope(s).is_none()) {
        return Err("Select supported Google services.".into());
    }
    let mut chosen: Vec<String> = services.to_vec();
    chosen.sort();
    chosen.dedup();
    // Imported JSON cannot redirect credentials to arbitrary endpoints.
    let trusted = json!({ "installed": { "client_id": client_id, "client_secret": secret, "auth_uri": AUTH_URI,
        "token_uri": TOKEN_URI, "redirect_uris": ["http://localhost"] }, "services": chosen });
    persist("client", &trusted).await?;
    persist("tokens", &Value::Null).await?;
    with(|s| {
        s.client = Some(trusted);
        s.tokens = None;
        s.contacts.clear();
        s.error.clear();
    });
    Ok(status())
}

pub async fn save_api_key(key: &str) -> Res<Value> {
    let key = key.trim();
    if !key.is_empty() && !crate::re!(r"^AIza[A-Za-z0-9_-]{35}$").is_match(key) {
        return Err("Enter a Google API key beginning with AIza (39 characters).".into());
    }
    persist("api-key", &if key.is_empty() { Value::Null } else { json!(key) }).await?;
    with(|s| s.api_key = (!key.is_empty()).then(|| key.to_string()));
    Ok(json!({ "api_key_set": !key.is_empty() }))
}

pub async fn public_youtube(limit: u32) -> Res<Value> {
    let Some(key) = with(|s| s.api_key.clone()) else { return Err("Add a Google API key in Settings > Google first.".into()) };
    let url = format!(
        "https://www.googleapis.com/youtube/v3/videos?key={}&part=snippet&chart=mostPopular&maxResults={limit}",
        url_encode(&key)
    );
    let mut response = Http::get(&url).timeout(15.0).send().await.map_err(|_| "Google could not be reached. Please try again.".to_string())?;
    if response.status != 200 {
        return Err("YouTube API access failed. Check the key, its restrictions, quota and whether YouTube Data API v3 is enabled.".into());
    }
    let data = response.json().await.map_err(|_| "Google could not be reached. Please try again.".to_string())?;
    let items: Vec<Value> = data["items"]
        .as_array()
        .into_iter()
        .flatten()
        .map(|i| json!({ "title": i["snippet"]["title"].as_str().unwrap_or(""), "url": format!("https://www.youtube.com/watch?v={}", i["id"].as_str().unwrap_or("")) }))
        .collect();
    Ok(Value::Array(items))
}

/// Starts the browser sign-in; Google redirects back to this server.
pub async fn connect(services: Option<Vec<String>>) -> Res<Value> {
    let Some(config) = with(|s| s.client.clone()) else { return Err("Import your Desktop OAuth client JSON first.".into()) };
    if with(|s| login_active(s)) {
        return Ok(status());
    }
    if let Some(mut wanted) = services {
        wanted.sort();
        wanted.dedup();
        if wanted != with(|s| services_of(s)) {
            configure(&config, &wanted).await?;
        }
    }
    let (client_id, scopes) = with(|s| {
        let id = s.client.as_ref().map(|c| c["installed"]["client_id"].as_str().unwrap_or("").to_string()).unwrap_or_default();
        (id, services_of(s).iter().filter_map(|x| scope(x)).collect::<Vec<_>>().join(" "))
    });
    let state = token_urlsafe(32);
    let verifier = token_urlsafe(48);
    let challenge = b64url(&Sha256::digest(verifier.as_bytes()));
    let redirect = format!("http://127.0.0.1:{}/", crate::config::port());
    let url = format!(
        "{AUTH_URI}?response_type=code&client_id={}&redirect_uri={}&scope={}&state={}&code_challenge={}&code_challenge_method=S256&access_type=offline&prompt=consent",
        url_encode(&client_id),
        url_encode(&redirect),
        url_encode(&scopes),
        url_encode(&state),
        url_encode(&challenge)
    );
    with(|s| {
        s.login = Some(Login { state, verifier, redirect, started: host::now_secs() });
        s.error.clear();
    });
    if !crate::websites::open_browser(&url) {
        with(|s| {
            s.login = None;
            s.error = SIGN_IN_FAILED.into();
        });
    }
    Ok(status())
}

/// True when `query` is the OAuth redirect of the sign-in in progress.
pub fn is_callback(state: Option<&str>) -> bool {
    let Some(state) = state else { return false };
    with(|s| login_active(s) && s.login.as_ref().is_some_and(|l| crate::util::ct_eq(l.state.as_bytes(), state.as_bytes())))
}

/// Finishes the sign-in from the redirect; returns the page shown in the browser.
pub async fn finish_login(code: Option<String>, error: Option<String>) -> String {
    let Some(login) = with(|s| s.login.take()) else { return callback_page(false) };
    let result = async {
        if error.is_some() {
            return Err(String::new());
        }
        let code = code.filter(|c| !c.is_empty() && c.len() < 2000).ok_or_else(String::new)?;
        let config = with(|s| s.client.clone()).ok_or_else(String::new)?;
        let installed = &config["installed"];
        let (client_id, secret) = (installed["client_id"].as_str().unwrap_or(""), installed["client_secret"].as_str().unwrap_or(""));
        let mut response = Http::post(TOKEN_URI)
            .timeout(20.0)
            .form(&[
                ("grant_type", "authorization_code"),
                ("code", &code),
                ("client_id", client_id),
                ("client_secret", secret),
                ("redirect_uri", &login.redirect),
                ("code_verifier", &login.verifier),
            ])
            .send()
            .await?;
        if response.status != 200 {
            return Err(String::new());
        }
        let data = response.json().await?;
        let access = data["access_token"].as_str().filter(|t| !t.is_empty()).ok_or_else(String::new)?;
        let granted: Vec<String> = data["scope"].as_str().unwrap_or("").split_whitespace().map(str::to_string).collect();
        let wanted: Vec<&str> = with(|s| services_of(s)).iter().filter_map(|x| scope(x)).collect();
        if !wanted.iter().all(|w| granted.iter().any(|g| g == w)) {
            return Err("Missing permissions".to_string());
        }
        let tokens = json!({
            "token": access, "refresh_token": data["refresh_token"], "token_uri": TOKEN_URI,
            "client_id": client_id, "client_secret": secret, "scopes": granted,
            "universe_domain": "googleapis.com", "account": "",
            "expiry": expiry_text(host::now_secs() + data["expires_in"].as_f64().unwrap_or(3600.0)),
        });
        persist("tokens", &tokens).await?;
        with(|s| {
            s.tokens = Some(tokens);
            s.contacts.clear();
        });
        Ok(())
    }
    .await;
    let ok = result.is_ok();
    if !ok {
        with(|s| s.error = SIGN_IN_FAILED.into());
    }
    callback_page(ok)
}

fn callback_page(ok: bool) -> String {
    let message = if ok { "Google is connected. You can close this tab and return to Jarvis." } else { "Return to Jarvis to check whether Google sign-in completed." };
    format!("<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>Jarvis</title></head><body style=\"font:16px system-ui;padding:40px\">{message}</body></html>")
}

pub async fn disconnect() -> Res<Value> {
    if with(|s| login_active(s)) {
        return Err("Finish or cancel Google sign-in first, then disconnect.".into());
    }
    let saved = with(|s| s.tokens.clone());
    persist("tokens", &Value::Null).await?;
    with(|s| {
        s.tokens = None;
        s.contacts.clear();
        s.error.clear();
    });
    if let Some(saved) = saved {
        let token = saved["refresh_token"].as_str().or(saved["token"].as_str()).unwrap_or("").to_string();
        let revoked = match Http::post("https://oauth2.googleapis.com/revoke").timeout(15.0).form(&[("token", &token)]).send().await {
            Ok(r) => r.status == 200 || r.status == 400,
            Err(_) => false,
        };
        if !revoked {
            with(|s| s.error = "Local connection removed. Revoke remaining access in your Google account permissions if needed.".into());
        }
    }
    Ok(status())
}

/// `datetime.isoformat() + "Z"` as google-auth writes it.
fn expiry_text(utc_secs: f64) -> String {
    let secs = utc_secs.floor() as i64;
    let (y, m, d) = civil_from_days(secs.div_euclid(86400));
    let t = secs.rem_euclid(86400);
    format!("{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}Z", t / 3600, t % 3600 / 60, t % 60)
}

fn utc_now_iso() -> String {
    expiry_text(host::now_secs())
}

/// A valid access token for `service`, refreshed when it is about to expire.
async fn token(service: &str) -> Res<String> {
    let (saved, client) = with(|s| (s.tokens.clone(), s.client.clone()));
    let enabled = with(|s| services_of(s)).iter().any(|x| x == service);
    let (Some(mut saved), Some(client)) = (saved, client) else { return Err(format!("Connect {service} in Settings > Google first.")) };
    if !enabled {
        return Err(format!("Connect {service} in Settings > Google first."));
    }
    let expiry = saved["expiry"].as_str().and_then(|e| parse_moment(e, "UTC").ok()).map(|m| m.timestamp());
    let current = saved["token"].as_str().unwrap_or("").to_string();
    // google-auth refreshes 3 min 45 s before expiry.
    if !current.is_empty() && expiry.is_some_and(|e| host::now_secs() < e - 225.0) {
        return Ok(current);
    }
    let expired = || "Google authorization expired or was revoked. Reconnect in Settings > Google.".to_string();
    let refresh = saved["refresh_token"].as_str().filter(|r| !r.is_empty()).ok_or_else(expired)?.to_string();
    let installed = &client["installed"];
    let client_id = saved["client_id"].as_str().or(installed["client_id"].as_str()).unwrap_or("").to_string();
    let secret = saved["client_secret"].as_str().or(installed["client_secret"].as_str()).unwrap_or("").to_string();
    let mut response = Http::post(TOKEN_URI)
        .timeout(20.0)
        .form(&[("grant_type", "refresh_token"), ("refresh_token", &refresh), ("client_id", &client_id), ("client_secret", &secret)])
        .send()
        .await
        .map_err(|_| expired())?;
    if response.status != 200 {
        return Err(expired());
    }
    let data = response.json().await.map_err(|_| expired())?;
    let access = data["access_token"].as_str().filter(|t| !t.is_empty()).ok_or_else(expired)?.to_string();
    saved["token"] = json!(access);
    saved["expiry"] = json!(expiry_text(host::now_secs() + data["expires_in"].as_f64().unwrap_or(3600.0)));
    if let Some(new_refresh) = data["refresh_token"].as_str() {
        saved["refresh_token"] = json!(new_refresh);
    }
    persist("tokens", &saved).await?;
    with(|s| s.tokens = Some(saved));
    Ok(access)
}

fn query_string(params: &[(&str, &str)]) -> String {
    params.iter().map(|(k, v)| format!("{}={}", url_encode(k), url_encode(v))).collect::<Vec<_>>().join("&")
}

async fn get_json(url: &str, token: &str, params: &[(&str, &str)], timeout: f64) -> Res<(u16, Value)> {
    let full = if params.is_empty() { url.to_string() } else { format!("{url}?{}", query_string(params)) };
    let mut response = Http::get(&full).bearer(token).timeout(timeout).send().await?;
    let status = response.status;
    let body = if status == 200 { response.json().await? } else { Value::Null };
    Ok((status, body))
}

// ---- mail -------------------------------------------------------------------------

/// RFC 2047 encoded header value when it is not plain ASCII.
/// One header line: control characters can never start another header.
fn header_value(text: &str) -> String {
    let text: String = text.chars().map(|c| if c.is_control() { ' ' } else { c }).collect();
    if text.is_ascii() { text } else { format!("=?utf-8?b?{}?=", b64(text.as_bytes())) }
}

fn raw_message(fields: &Map<String, Value>, extra: &[(&str, &str)]) -> String {
    let field = |k: &str| fields.get(k).and_then(Value::as_str).unwrap_or("").to_string();
    let mut message = format!("To: {}\r\nSubject: {}\r\n", header_value(&field("recipient")), header_value(&field("subject")));
    for (name, value) in extra {
        message += &format!("{name}: {}\r\n", header_value(value));
    }
    let body = b64(field("body").replace("\r\n", "\n").replace('\n', "\r\n").as_bytes());
    let wrapped: Vec<&str> = body.as_bytes().chunks(76).map(|c| std::str::from_utf8(c).unwrap_or("")).collect();
    message += "MIME-Version: 1.0\r\nContent-Type: text/plain; charset=\"utf-8\"\r\nContent-Transfer-Encoding: base64\r\n\r\n";
    message += &wrapped.join("\r\n");
    message += "\r\n";
    b64url(message.as_bytes())
}

fn valid_id(value: &Value, max: usize) -> bool {
    value.as_str().is_some_and(|v| !v.is_empty() && v.len() <= max && v.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-'))
}

/// Persists a new draft; uncertain writes are never replayed.
pub async fn create_gmail_draft(fields: &Map<String, Value>, request: &str, resolved: Option<&str>) -> Res<Value> {
    let get = |k: &str| fields.get(k).and_then(Value::as_str).unwrap_or("");
    let fields = draft_fields(get("recipient"), get("subject"), get("body"))?;
    let recipient = fields.get("recipient").and_then(Value::as_str).unwrap_or("").to_string();
    if !(recipient_authorized(&recipient, request) || resolved == Some(recipient.as_str())) {
        return Err("Preparing a draft requires an exact recipient address or one verified Google Contact.".into());
    }
    let token = token("gmail_drafts").await?;
    let raw = raw_message(&fields, &[]);
    let mut response = Http::post(&format!("{GMAIL}/drafts"))
        .bearer(&token)
        .timeout(20.0)
        .json(&json!({ "message": { "raw": raw } }))
        .send()
        .await
        .map_err(|_| "The Gmail draft result is uncertain. Check Drafts before retrying; I will not create it twice.".to_string())?;
    if response.status != 200 {
        return Err(format!("Gmail returned HTTP {} while saving the draft. Check Drafts and permissions before retrying; no automatic retry was made.", response.status));
    }
    let unclear = || "Gmail did not confirm the saved draft. Check Drafts before retrying; no automatic retry was made.".to_string();
    let result = response.json().await.map_err(|_| unclear())?;
    if !valid_id(&result["id"], 200) || !valid_id(&result["message"]["id"], 200) {
        return Err(unclear());
    }
    Ok(json!({ "id": result["id"], "message_id": result["message"]["id"], "saved": true }))
}

pub async fn send_gmail(fields: &Map<String, Value>, request: &str, resolved: Option<&str>, reply_to: Option<&Value>) -> Res<Value> {
    let get = |k: &str| fields.get(k).and_then(Value::as_str).unwrap_or("");
    let fields = draft_fields(get("recipient"), get("subject"), get("body"))?;
    let recipient = fields.get("recipient").and_then(Value::as_str).unwrap_or("").to_string();
    ensure_email_recipient_allowed(&recipient, request, reply_to)?;
    if !send_requested(request) || !(recipient_authorized(&recipient, request) || resolved == Some(recipient.as_str())) {
        return Err("Sending requires an explicit request and an exact recipient address supplied by you.".into());
    }
    let token = token("gmail_send").await?;
    let mut payload = Map::new();
    let mut extra: Vec<(&str, String)> = Vec::new();
    if let Some(reply) = reply_to {
        let thread = reply["thread_id"].as_str().unwrap_or("");
        let message_id = reply["message_id"].as_str().unwrap_or("");
        if !valid_id(&reply["thread_id"], 100) || !crate::re!(r"^<[^<>\r\n ]+>$").is_match(message_id) {
            return Err("The original email has no valid reply identifiers. No reply was sent.".into());
        }
        extra.push(("In-Reply-To", message_id.to_string()));
        extra.push(("References", message_id.to_string()));
        payload.insert("threadId".into(), json!(thread));
    }
    let extra_refs: Vec<(&str, &str)> = extra.iter().map(|(k, v)| (*k, v.as_str())).collect();
    payload.insert("raw".into(), json!(raw_message(&fields, &extra_refs)));
    // Never retry a send: a timeout may occur after Gmail accepted it.
    let mut response = Http::post(&format!("{GMAIL}/messages/send"))
        .bearer(&token)
        .timeout(20.0)
        .json(&Value::Object(payload))
        .send()
        .await
        .map_err(|_| "The Gmail send result is uncertain. Check Sent mail before retrying; I will not send it twice.".to_string())?;
    if response.status != 200 {
        return Err(format!("Gmail returned HTTP {} while sending. Check Sent mail and permissions before retrying; no automatic retry was made.", response.status));
    }
    let result = response.json().await.map_err(|_| "Gmail returned an unclear send result. Check Sent mail; no automatic retry was made.".to_string())?;
    if result["id"].as_str().is_none_or(str::is_empty) {
        return Err("Gmail did not return a message identifier. Check Sent mail before retrying.".into());
    }
    Ok(json!({ "id": result["id"], "accepted": true }))
}

/// Minimal HTML-to-text: drops script/style, keeps line breaks of block tags.
fn html_text(html: &str) -> String {
    let mut out = String::new();
    let mut hidden = 0usize;
    let mut rest = html;
    while let Some(lt) = rest.find('<') {
        if hidden == 0 {
            out += &unescape(&rest[..lt]);
        }
        let Some(gt) = rest[lt..].find('>') else { break };
        let tag = rest[lt + 1..lt + gt].trim().to_ascii_lowercase();
        let closing = tag.starts_with('/');
        let name: String = tag.trim_start_matches('/').chars().take_while(|c| c.is_ascii_alphanumeric()).collect();
        if name == "script" || name == "style" {
            if closing { hidden = hidden.saturating_sub(1) } else if !tag.ends_with('/') { hidden += 1 }
        }
        if !closing && ["br", "p", "div", "li"].contains(&name.as_str()) {
            out.push('\n');
        }
        rest = &rest[lt + gt + 1..];
    }
    if hidden == 0 {
        out += &unescape(rest);
    }
    out
}

fn unescape(text: &str) -> String {
    if !text.contains('&') {
        return text.to_string();
    }
    crate::re!(r"&(#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6}|[a-zA-Z]{2,8});")
        .replace_all(text, |c: &regex::Captures| {
            let e = &c[1];
            let decoded = if let Some(hex) = e.strip_prefix("#x").or_else(|| e.strip_prefix("#X")) {
                u32::from_str_radix(hex, 16).ok().and_then(char::from_u32)
            } else if let Some(dec) = e.strip_prefix('#') {
                dec.parse().ok().and_then(char::from_u32)
            } else {
                match e {
                    "amp" => Some('&'),
                    "lt" => Some('<'),
                    "gt" => Some('>'),
                    "quot" => Some('"'),
                    "apos" => Some('\''),
                    "nbsp" => Some('\u{a0}'),
                    "auml" => Some('ä'),
                    "ouml" => Some('ö'),
                    "uuml" => Some('ü'),
                    "Auml" => Some('Ä'),
                    "Ouml" => Some('Ö'),
                    "Uuml" => Some('Ü'),
                    "szlig" => Some('ß'),
                    "eacute" => Some('é'),
                    "egrave" => Some('è'),
                    "agrave" => Some('à'),
                    "ndash" => Some('–'),
                    "mdash" => Some('—'),
                    "hellip" => Some('…'),
                    "rsquo" => Some('’'),
                    "lsquo" => Some('‘'),
                    "rdquo" => Some('”'),
                    "ldquo" => Some('“'),
                    "euro" => Some('€'),
                    "copy" => Some('©'),
                    _ => None,
                }
            };
            decoded.map(String::from).unwrap_or_else(|| c[0].to_string())
        })
        .into_owned()
}

/// Inline text parts only; attachments and remote resources are never fetched.
fn mail_body(payload: &Value) -> String {
    fn visit(part: &Value, depth: usize, plain: &mut Vec<String>, html: &mut Vec<String>) {
        if depth > 15 || part["filename"].as_str().is_some_and(|f| !f.is_empty()) {
            return;
        }
        let data = part["body"]["data"].as_str().unwrap_or("");
        let mime = part["mimeType"].as_str().unwrap_or("");
        if !data.is_empty() && data.len() <= 500_000 && (mime == "text/plain" || mime == "text/html")
            && let Some(bytes) = crate::util::b64url_decode(data)
        {
            let text = String::from_utf8_lossy(&bytes).into_owned();
            if mime == "text/plain" { plain.push(text) } else { html.push(text) }
        }
        for child in part["parts"].as_array().into_iter().flatten().take(30) {
            visit(child, depth + 1, plain, html);
        }
    }
    let (mut plain, mut html) = (Vec::new(), Vec::new());
    visit(payload, 0, &mut plain, &mut html);
    let text = if plain.is_empty() { html_text(&html.join("\n")) } else { plain.join("\n") };
    take(text.trim(), 10000)
}

fn mail_headers(payload: &Value) -> HashMap<String, String> {
    payload["headers"]
        .as_array()
        .into_iter()
        .flatten()
        .map(|h| (h["name"].as_str().unwrap_or("").to_lowercase(), h["value"].as_str().unwrap_or("").to_string()))
        .collect()
}

/// Runs `jobs` with at most three requests in flight, keeping order.
async fn limited<F: std::future::Future<Output = T>, T>(jobs: Vec<F>) -> Vec<T> {
    let mut out = Vec::with_capacity(jobs.len());
    let mut jobs = jobs.into_iter();
    loop {
        let batch: Vec<F> = jobs.by_ref().take(3).collect();
        if batch.is_empty() {
            return out;
        }
        out.extend(futures::future::join_all(batch).await);
    }
}

/// Matching older or recent mail with the readonly permission.
pub async fn search_gmail(query: &str, count: u32) -> Res<Value> {
    if query.chars().count() > 500 || query.chars().any(|c| (c as u32) < 32) {
        return Err("Please use a short mail search, such as from:person@example.com before:2026/09/01.".into());
    }
    let token = token("gmail").await?;
    let limit = count.clamp(1, 20);
    let base = format!("{GMAIL}/messages");
    let fail = |status: u16| format!("Gmail returned HTTP {status}. Check the Google connection in Settings.");
    let (status, listing) = get_json(&base, &token, &[("q", query), ("maxResults", &limit.to_string())], 20.0).await?;
    if status != 200 {
        return Err(fail(status));
    }
    let rows: Vec<Value> = listing["messages"].as_array().cloned().unwrap_or_default().into_iter().take(limit as usize).collect();
    if rows.iter().any(|r| !valid_id(&r["id"], 100)) {
        return Err("Gmail returned an invalid message identifier.".into());
    }
    let reads = rows.iter().map(|row| {
        let (base, token) = (base.clone(), token.clone());
        let id = row["id"].as_str().unwrap_or("").to_string();
        async move {
            let (status, result) = get_json(&format!("{base}/{id}"), &token, &[("format", "full")], 20.0).await?;
            if status != 200 {
                return Err(fail(status));
            }
            let payload = &result["payload"];
            let h = mail_headers(payload);
            let header = |k: &str| h.get(k).cloned().unwrap_or_default();
            Ok(json!({
                "id": id, "from": header("from"), "to": header("to"), "thread_id": result["threadId"].as_str().unwrap_or(""),
                "message_id": header("message-id"), "reply_to": header("reply-to"),
                "internal_date": result["internalDate"].as_str().unwrap_or("0"), "subject": header("subject"),
                "date": header("date"), "body": mail_body(payload), "snippet": result["snippet"].as_str().unwrap_or(""),
            }))
        }
    });
    let mut messages = limited(reads.collect()).await.into_iter().collect::<Res<Vec<Value>>>()?;
    messages.sort_by_key(|m| std::cmp::Reverse(m["internal_date"].as_str().and_then(|d| d.parse::<i64>().ok()).unwrap_or(0)));
    Ok(json!({ "service": "gmail", "query": query, "items": messages, "has_more": listing["nextPageToken"].is_string(), "max_body_characters": 10000 }))
}

/// IDs and headers of recent unread mail, for local alert classification.
pub async fn recent_unread_headers(count: u32) -> Res<Vec<Value>> {
    let token = token("gmail").await?;
    let base = format!("{GMAIL}/messages");
    let (status, listing) = get_json(&base, &token, &[("q", "is:unread newer_than:2d"), ("maxResults", &count.clamp(1, 20).to_string())], 15.0).await?;
    if status != 200 {
        return Err(format!("Gmail returned HTTP {status}."));
    }
    let rows: Vec<String> = listing["messages"].as_array().into_iter().flatten().filter(|r| valid_id(&r["id"], 100)).filter_map(|r| r["id"].as_str().map(str::to_string)).collect();
    let reads = rows.into_iter().map(|id| {
        let (base, token) = (base.clone(), token.clone());
        async move {
            let url = format!("{base}/{id}?format=metadata&metadataHeaders=Subject&metadataHeaders=From");
            let (status, data) = get_json(&url, &token, &[], 15.0).await?;
            if status != 200 {
                return Err(format!("Gmail returned HTTP {status}."));
            }
            let h = mail_headers(&data["payload"]);
            let labels: Vec<&str> = data["labelIds"].as_array().into_iter().flatten().filter_map(Value::as_str).collect();
            Ok(json!({
                "source": "gmail", "id": id, "subject": take(h.get("subject").map(String::as_str).unwrap_or(""), 300),
                "sender": take(h.get("from").map(String::as_str).unwrap_or(""), 240),
                "unread": labels.contains(&"UNREAD"), "important": labels.contains(&"IMPORTANT"),
            }))
        }
    });
    limited(reads.collect()).await.into_iter().collect()
}

/// Contacts search; the opt-in 30-second cache serves repeated draft lookups.
pub async fn search_contacts(name: &str, use_cache: bool) -> Res<Vec<Value>> {
    if !(1..=100).contains(&name.chars().count()) || name.chars().any(|c| (c as u32) < 32) {
        return Err("Please give a contact name.".into());
    }
    let token = token("contacts").await?;
    let key = (sha256_hex(token.as_bytes()), name.trim().to_lowercase());
    let now = host::monotonic();
    if use_cache && let Some(hit) = with(|s| s.contacts.get(&key).filter(|(until, _)| *until > now).map(|(_, v)| v.clone())) {
        return Ok(hit);
    }
    let base = "https://people.googleapis.com/v1/people:searchContacts";
    let mut result = Vec::new();
    // The empty query warms Google's contact search cache, as Google recommends.
    for query in ["", name] {
        let (status, data) = get_json(base, &token, &[("query", query), ("readMask", "names,emailAddresses"), ("pageSize", "30")], 15.0).await?;
        if status != 200 {
            return Err("Could not search Google Contacts. Check the Contacts permission in Settings.".into());
        }
        result = data["results"].as_array().into_iter().flatten().map(|r| r["person"].clone()).filter(|p| !p.is_null()).collect();
    }
    if use_cache {
        with(|s| {
            s.contacts.insert(key, (host::monotonic() + 30.0, result.clone()));
            if s.contacts.len() > 64
                && let Some(oldest) = s.contacts.iter().min_by(|a, b| a.1.0.total_cmp(&b.1.0)).map(|(k, _)| k.clone())
            {
                s.contacts.remove(&oldest);
            }
        });
    }
    Ok(result)
}

pub async fn read(service: &str) -> Res<Value> {
    if !["gmail", "calendar", "drive", "tasks", "contacts"].contains(&service) {
        return Err("This permission is not a Google reading service.".into());
    }
    let token = token(service).await?;
    let get = |url: String, params: Vec<(&'static str, String)>| {
        let token = token.clone();
        async move {
            let refs: Vec<(&str, &str)> = params.iter().map(|(k, v)| (*k, v.as_str())).collect();
            let (status, body) = get_json(&url, &token, &refs, 20.0).await?;
            if status != 200 {
                return Err(format!("Google API returned HTTP {status}. Check enabled APIs and account permissions in Google Cloud."));
            }
            Ok(body)
        }
    };
    let items: Vec<Value> = match service {
        "gmail" => {
            let rows = get(format!("{GMAIL}/messages"), vec![("maxResults", "5".into()), ("q", "is:unread".into())]).await?;
            let mut out = Vec::new();
            for row in rows["messages"].as_array().into_iter().flatten() {
                if !valid_id(&row["id"], 100) {
                    continue;
                }
                let message = get(format!("{GMAIL}/messages/{}", row["id"].as_str().unwrap_or("")), vec![("format", "metadata".into())]).await?;
                let h = mail_headers(&message["payload"]);
                out.push(json!({ "from": h.get("from").cloned().unwrap_or_default(), "subject": h.get("subject").cloned().unwrap_or_default(), "snippet": message["snippet"].as_str().unwrap_or("") }));
            }
            out
        }
        "calendar" => {
            let result = get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events".into(),
                vec![("maxResults", "10".into()), ("singleEvents", "true".into()), ("orderBy", "startTime".into()), ("timeMin", utc_now_iso())],
            )
            .await?;
            result["items"].as_array().into_iter().flatten().map(|r| json!({ "title": r["summary"].as_str().unwrap_or("Untitled"), "start": r.get("start").cloned().unwrap_or(json!({})) })).collect()
        }
        "drive" => {
            let result = get(
                "https://www.googleapis.com/drive/v3/files".into(),
                vec![("pageSize", "20".into()), ("q", "trashed = false".into()), ("orderBy", "modifiedTime desc".into()), ("fields", "files(id,name,mimeType,webViewLink)".into())],
            )
            .await?;
            result["files"].as_array().cloned().unwrap_or_default()
        }
        "tasks" => {
            let result = get("https://tasks.googleapis.com/tasks/v1/lists/@default/tasks".into(), vec![("maxResults", "20".into()), ("showCompleted", "false".into())]).await?;
            result["items"].as_array().into_iter().flatten().map(|r| json!({ "title": r["title"].as_str().unwrap_or(""), "due": r["due"].as_str().unwrap_or("") })).collect()
        }
        _ => {
            let result = get("https://people.googleapis.com/v1/people/me/connections".into(), vec![("personFields", "names,emailAddresses".into()), ("pageSize", "20".into())]).await?;
            result["connections"]
                .as_array()
                .into_iter()
                .flatten()
                .map(|r| json!({ "names": r.get("names").cloned().unwrap_or(json!([])), "emails": r.get("emailAddresses").cloned().unwrap_or(json!([])) }))
                .collect()
        }
    };
    Ok(json!({ "service": service, "items": items }))
}

// ---- voice commands -----------------------------------------------------------------

pub fn parse(text: &str) -> Option<Value> {
    let text = crate::re!(r"(?i)^(?:hey\s+)?jarvis[,\s]+").replace(text, "");
    let text = text.trim().trim_end_matches(['!', '?', '.']);
    if crate::re!(r"(?i)^(?:show popular youtube videos|zeige beliebte youtube videos)$").is_match(text) {
        return Some(json!({ "action": "public", "service": "youtube" }));
    }
    if let Some(c) = crate::re!(r"(?i)^(?:open|öffne|starte)\s+(.+)$").captures(text) {
        let target = c[1].to_lowercase();
        if WEB_APPS.iter().any(|(k, _)| *k == target) {
            return Some(json!({ "action": "open", "service": target }));
        }
    }
    let patterns: [(&str, &regex::Regex); 5] = [
        ("gmail", crate::re!(r"(?i)^(?:read|show|lies|zeige) (?:my |meine |die )?(?:unread |ungelesenen )?(?:gmail|gmail mails|gmail emails|gmail nachrichten)$")),
        ("calendar", crate::re!(r"(?i)^(?:show|read|zeige|lies) (?:my |meinen |meine |den )?google (?:calendar|kalender|termine)$")),
        ("drive", crate::re!(r"(?i)^(?:show|list|zeige) (?:my |meine )?google drive(?: files| dateien)?$")),
        ("tasks", crate::re!(r"(?i)^(?:show|read|zeige|lies) (?:my |meine )?google (?:tasks|aufgaben)$")),
        ("contacts", crate::re!(r"(?i)^(?:show|list|zeige) (?:my |meine )?google (?:contacts|kontakte)$")),
    ];
    patterns.iter().find(|(_, re)| re.is_match(text)).map(|(service, _)| json!({ "action": "read", "service": service }))
}

pub async fn execute(command: &Value) -> String {
    let service = command["service"].as_str().unwrap_or("");
    match command["action"].as_str().unwrap_or("") {
        "public" => match public_youtube(5).await {
            Ok(items) => format!("Popular YouTube videos: {}", calendar::py_json(&items)),
            Err(e) => e,
        },
        "open" => match WEB_APPS.iter().find(|(k, _)| *k == service) {
            Some((_, url)) => crate::websites::open_website(url).await,
            None => "Google could not be reached. Check your connection in Settings.".into(),
        },
        _ => match read(service).await {
            Ok(result) => {
                let items = &result["items"];
                format!("Your {service}: {}", if items.as_array().is_some_and(|a| !a.is_empty()) { calendar::py_json(items) } else { "No items found.".into() })
            }
            Err(e) => e,
        },
    }
}

// ---- Google Calendar workflow ----------------------------------------------------------

/// Read, create or update one event on the primary calendar; never delete.
pub async fn run_calendar(request: &str) -> Outcome {
    let mut attempted = false;
    match calendar_step(request, &mut attempted).await {
        Ok(outcome) => outcome,
        Err(CalendarError::Uncertain) => Outcome {
            ok: false,
            needs_input: false,
            message: "The Calendar result is uncertain. Check Google Calendar before retrying; no automatic retry was made.".into(),
        },
        Err(CalendarError::Message(m)) => Outcome {
            ok: false,
            needs_input: !attempted,
            message: if m.is_empty() { "Please clarify the calendar task.".into() } else { take(&m, 400) },
        },
    }
}

enum CalendarError {
    Uncertain,
    Message(String),
}

impl From<String> for CalendarError {
    fn from(m: String) -> Self {
        Self::Message(m)
    }
}

async fn calendar_step(request: &str, attempted: &mut bool) -> Result<Outcome, CalendarError> {
    let plan = calendar::plan_with_model(request, calendar::SYSTEM, calendar::schema(None)).await?;
    let text = |k: &str| plan[k].as_str().unwrap_or("").to_string();
    let operation = text("operation");
    if operation == "ask" {
        let q = text("question");
        return Ok(Outcome { ok: false, needs_input: true, message: if q.is_empty() { "Which calendar task should I perform?".into() } else { q } });
    }
    if !["read", "create", "update"].contains(&operation.as_str()) {
        return Err("Unsupported calendar operation.".to_string().into());
    }
    if operation != "read" && !operation_allowed(request, &operation) {
        return Err("Please explicitly ask me to create or change the event.".to_string().into());
    }
    let service = if operation == "read" { "calendar" } else { "calendar_write" };
    let st = status();
    if st["connected"] != true || !st["services"].as_array().is_some_and(|a| a.iter().any(|s| s == service)) {
        let what = if operation == "read" { "Calendar reading" } else { "Calendar editing" };
        return Ok(Outcome { ok: false, needs_input: true, message: format!("Enable {what} in Settings > Google and reconnect Google, then ask me to continue.") });
    }
    let token = token(service).await?;
    let base = "https://www.googleapis.com/calendar/v3/calendars/primary/events";
    let mut body = if operation == "read" { Map::new() } else { event_fields(&plan)? };
    let response = if operation == "read" || operation == "update" {
        let (start, end) = (moment(&plan["window_start"])?, moment(&plan["window_end"])?);
        if end.timestamp() <= start.timestamp() || end.timestamp() - start.timestamp() >= 367.0 * 86400.0 {
            return Err("Please specify a calendar period of at most one year.".to_string().into());
        }
        let z = zone();
        let query = text("query").trim().to_string();
        let mut params = vec![
            ("timeMin", start.iso(&z)),
            ("timeMax", end.iso(&z)),
            ("singleEvents", "true".to_string()),
            ("orderBy", "startTime".to_string()),
            ("maxResults", "50".to_string()),
        ];
        if !query.is_empty() {
            params.push(("q", query.clone()));
        }
        let refs: Vec<(&str, &str)> = params.iter().map(|(k, v)| (*k, v.as_str())).collect();
        let (status, data) = get_json(base, &token, &refs, 20.0).await.map_err(|_| CalendarError::Uncertain)?;
        if status != 200 {
            return Err(format!("Calendar search failed (HTTP {status}). Check your Google connection.").into());
        }
        let rows: Vec<Value> = data["items"].as_array().cloned().unwrap_or_default();
        if operation == "read" {
            let observed: Vec<Value> = rows
                .iter()
                .map(|r| {
                    json!({ "title": r["summary"].as_str().unwrap_or("Untitled"), "start": r.get("start").cloned().unwrap_or(json!({})),
                        "end": r.get("end").cloned().unwrap_or(json!({})), "location": r["location"].as_str().unwrap_or(""),
                        "description": take(r["description"].as_str().unwrap_or(""), 2000) })
                })
                .collect();
            let more = if data["nextPageToken"].is_string() { " (more results available)" } else { "" };
            return Ok(Outcome { ok: true, needs_input: false, message: format!("Calendar results{more}: {}", calendar::py_json(&Value::Array(observed))) });
        }
        let wanted = query.to_lowercase();
        let matches: Vec<&Value> = rows.iter().filter(|r| r["summary"].as_str().unwrap_or("").to_lowercase() == wanted && r["status"] != "cancelled").collect();
        if query.is_empty() || matches.len() != 1 || data["nextPageToken"].is_string() {
            return Err("I could not identify exactly one event. Please give its exact title and original date.".to_string().into());
        }
        let selected = matches[0];
        let event_id = selected["id"].as_str().unwrap_or("");
        if !valid_id(&selected["id"], 1024) {
            return Err("Invalid calendar event identifier.".to_string().into());
        }
        let (status, current) = get_json(&format!("{base}/{event_id}"), &token, &[], 20.0).await.map_err(|_| CalendarError::Uncertain)?;
        if status != 200 {
            return Err("The event is no longer available. Nothing was changed.".to_string().into());
        }
        let etag = current["etag"].as_str().unwrap_or("");
        if etag.is_empty() || current["etag"] != selected["etag"] {
            return Err("The event changed during planning. Please retry with its current details.".to_string().into());
        }
        if current["attendees"].as_array().is_some_and(|a| !a.is_empty())
            || current["recurrence"].as_array().is_some_and(|a| !a.is_empty())
            || current["recurringEventId"].as_str().is_some_and(|r| !r.is_empty())
        {
            return Err("Editing guest meetings or recurring events is not supported yet. Please change this event in Google Calendar.".to_string().into());
        }
        *attempted = true;
        Http::new("PATCH", &format!("{base}/{event_id}?sendUpdates=none"))
            .bearer(&token)
            .header("If-Match", etag)
            .timeout(20.0)
            .json(&Value::Object(body.clone()))
            .send()
            .await
    } else {
        // A caller-generated id identifies the event after an uncertain result.
        body.insert("id".into(), json!(uuid_hex()));
        *attempted = true;
        Http::post(&format!("{base}?sendUpdates=none")).bearer(&token).timeout(20.0).json(&Value::Object(body.clone())).send().await
    };
    let mut response = response.map_err(|_| CalendarError::Uncertain)?;
    if response.status != 200 && response.status != 201 {
        return Err(format!("Calendar write returned HTTP {}. Check Calendar before retrying; no automatic retry was made.", response.status).into());
    }
    let saved = response.json().await.map_err(|_| CalendarError::Uncertain)?;
    if saved["id"].as_str().is_none_or(str::is_empty) {
        return Err("Calendar returned an unclear result. Check Calendar before retrying.".to_string().into());
    }
    let title = saved["summary"].as_str().or(body.get("summary").and_then(Value::as_str)).map(str::to_string).unwrap_or_else(|| text("query"));
    let start = if saved["start"].is_null() { body.get("start").cloned().unwrap_or(Value::Null) } else { saved["start"].clone() };
    let end = if saved["end"].is_null() { body.get("end").cloned().unwrap_or(Value::Null) } else { saved["end"].clone() };
    Ok(Outcome {
        ok: true,
        needs_input: false,
        message: format!(
            "Calendar event {}: {title}. Start: {}. End: {}.",
            if operation == "create" { "created" } else { "updated" },
            calendar::py_json(&start),
            calendar::py_json(&end)
        ),
    })
}

#[cfg(test)]
mod tests {
    //! Ported from tests/test_email_workflows.py and test_google_access.py.
    use super::*;
    use base64::Engine;
    use base64::engine::general_purpose::{STANDARD, URL_SAFE};

    fn part(mime: &str, text: &str, filename: Option<&str>) -> Value {
        let mut p = json!({ "mimeType": mime, "body": { "data": URL_SAFE.encode(text) } });
        if let Some(name) = filename {
            p["filename"] = json!(name);
        }
        p
    }

    #[test]
    fn html_mail_is_text_only_and_attachments_are_not_read() {
        let mut payload = json!({ "parts": [
            part("text/html", "<script>bad()</script><p>Hello <b>Alex</b></p><img src=\"https://tracking.invalid\">", None),
            part("text/plain", "Private attachment", Some("secret.txt")),
        ]});
        assert_eq!(mail_body(&payload), "Hello Alex");
        payload["parts"].as_array_mut().unwrap().push(part("text/plain", "Preferred plain text", None));
        assert_eq!(mail_body(&payload), "Preferred plain text");
    }

    #[test]
    fn mime_headers_cannot_be_injected() {
        let mut fields = Map::new();
        fields.insert("recipient".into(), json!("alex@example.com"));
        fields.insert("subject".into(), json!("Meeting\r\nBcc: evil@example.com"));
        fields.insert("body".into(), json!("Hello"));
        let raw = String::from_utf8(crate::util::b64url_decode(&raw_message(&fields, &[])).unwrap()).unwrap();
        let headers: Vec<&str> = raw.split("\r\n\r\n").next().unwrap().split("\r\n").collect();
        assert!(!headers.iter().any(|h| h.to_ascii_lowercase().starts_with("bcc:")), "{headers:?}");
        assert_eq!(headers[0], "To: alex@example.com");
        let body = raw.split("\r\n\r\n").nth(1).unwrap().replace("\r\n", "");
        assert_eq!(STANDARD.decode(body).unwrap(), b"Hello");
    }

    #[test]
    fn message_ids_are_plain_tokens() {
        assert!(valid_id(&json!("18c2f0a_b-1"), 100));
        for bad in [json!(""), json!("../drafts"), json!("a b"), json!(5)] {
            assert!(!valid_id(&bad, 100), "{bad}");
        }
        assert!(!valid_id(&json!("a".repeat(101)), 100));
    }
}
