//! Local authentication; credentials never travel in request URLs.

use crate::host::{self, Res};
use crate::util::{ct_eq, token_urlsafe};
use crate::vault;
use std::cell::RefCell;

const DASHBOARD_CODE_TTL: f64 = 60_000.0;
const SESSION_TTL: f64 = 12.0 * 60.0 * 60.0 * 1000.0;
const MAX_SESSIONS: usize = 32;

thread_local! {
    static TOKEN: RefCell<String> = const { RefCell::new(String::new()) };
    // One-time codes let the browser dashboard bootstrap its own token without
    // putting the long-lived token into Chrome's command line.
    static CODES: RefCell<Vec<(String, f64)>> = const { RefCell::new(Vec::new()) };
    // The browser dashboard gets its own expiring credential.
    static SESSIONS: RefCell<Vec<(String, f64)>> = const { RefCell::new(Vec::new()) };
}

/// Reads the long-lived app token, creating it on first run.
pub async fn load_token() -> Res<String> {
    if !vault::available() {
        return Err("Windows Credential Manager is unavailable.".into());
    }
    let service = vault::service_name();
    let token = match vault::get_password(&service, "JARVIS_AUTH_TOKEN").await? {
        Some(t) if !t.is_empty() => t,
        _ => {
            let t = token_urlsafe(32);
            vault::set_password(&service, "JARVIS_AUTH_TOKEN", &t).await?;
            t
        }
    };
    TOKEN.with(|s| *s.borrow_mut() = token.clone());
    Ok(token)
}

pub fn token() -> String {
    TOKEN.with(|s| s.borrow().clone())
}

pub fn token_matches(supplied: &str, expected: &str) -> bool {
    !supplied.is_empty() && !expected.is_empty() && ct_eq(supplied.as_bytes(), expected.as_bytes())
}

/// Accepts the app token or an unexpired dashboard session.
pub fn verify(supplied: &str) -> bool {
    if token_matches(supplied, &token()) {
        return true;
    }
    if supplied.is_empty() {
        return false;
    }
    let now = host::monotonic();
    SESSIONS.with(|s| {
        let mut s = s.borrow_mut();
        s.retain(|(_, expiry)| *expiry > now);
        s.iter().any(|(t, _)| ct_eq(t.as_bytes(), supplied.as_bytes()))
    })
}

pub fn create_session_token() -> String {
    let token = token_urlsafe(32);
    let now = host::monotonic();
    SESSIONS.with(|s| {
        let mut s = s.borrow_mut();
        s.retain(|(_, expiry)| *expiry > now);
        while s.len() >= MAX_SESSIONS {
            s.remove(0);
        }
        s.push((token.clone(), now + SESSION_TTL));
    });
    token
}

pub fn create_dashboard_code() -> String {
    let code = token_urlsafe(32);
    let now = host::monotonic();
    CODES.with(|c| {
        let mut c = c.borrow_mut();
        c.retain(|(_, expiry)| *expiry > now);
        c.push((code.clone(), now + DASHBOARD_CODE_TTL));
    });
    code
}

/// Consumes a dashboard code; each code is valid once and only briefly.
pub fn redeem_dashboard_code(code: &str) -> bool {
    if code.is_empty() {
        return false;
    }
    let now = host::monotonic();
    CODES.with(|c| {
        let mut c = c.borrow_mut();
        match c.iter().position(|(k, _)| ct_eq(k.as_bytes(), code.as_bytes())) {
            Some(i) => c.remove(i).1 > now,
            None => false,
        }
    })
}

/// WebSocket auth via subprotocols `jarvis` + `jarvis.auth.<token>`.
pub fn websocket_token_ok(protocols: &[String]) -> bool {
    let supplied = protocols.iter().find_map(|p| p.strip_prefix("jarvis.auth.")).unwrap_or("");
    protocols.iter().any(|p| p == "jarvis") && verify(supplied)
}
