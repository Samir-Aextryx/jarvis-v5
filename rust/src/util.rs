//! Small shared helpers: encoding, randomness, time and text.

use base64::Engine;
use base64::engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD};
use serde_json::Value;
use sha2::{Digest, Sha256};

/// A lazily compiled, cached regular expression.
#[macro_export]
macro_rules! re {
    ($pattern:expr) => {{
        static RE: std::sync::OnceLock<regex::Regex> = std::sync::OnceLock::new();
        RE.get_or_init(|| regex::Regex::new($pattern).expect("valid regex"))
    }};
}

pub fn b64(data: &[u8]) -> String {
    STANDARD.encode(data)
}
pub fn b64_decode(text: &str) -> Option<Vec<u8>> {
    STANDARD.decode(text.trim()).ok()
}
pub fn b64url(data: &[u8]) -> String {
    URL_SAFE_NO_PAD.encode(data)
}
pub fn b64url_decode(text: &str) -> Option<Vec<u8>> {
    URL_SAFE_NO_PAD.decode(text.trim().trim_end_matches('=')).ok()
}

/// Same shape as Python's `secrets.token_urlsafe(n)`.
pub fn token_urlsafe(bytes: u32) -> String {
    b64url(&crate::host::random_bytes(bytes))
}
pub fn uuid_hex() -> String {
    hex(&crate::host::random_bytes(16))
}
pub fn hex(data: &[u8]) -> String {
    data.iter().map(|b| format!("{b:02x}")).collect()
}
pub fn sha256_hex(data: &[u8]) -> String {
    hex(&Sha256::digest(data))
}

/// Constant-time comparison for secrets.
pub fn ct_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

/// First `n` characters (Python slicing semantics).
pub fn take(text: &str, n: usize) -> String {
    text.chars().take(n).collect()
}
/// Last `n` characters.
pub fn tail(text: &str, n: usize) -> String {
    let count = text.chars().count();
    text.chars().skip(count.saturating_sub(n)).collect()
}
pub fn fold(text: &str) -> String {
    text.to_lowercase()
}
pub fn collapse_ws(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

pub fn s<'a>(value: &'a Value, key: &str) -> &'a str {
    value.get(key).and_then(Value::as_str).unwrap_or("")
}

// ---- local time (the JS Date object knows the Windows time zone) -------------

pub struct LocalTime {
    pub year: i32,
    pub month: u32,
    pub day: u32,
    pub hour: u32,
    pub minute: u32,
    pub second: u32,
    pub millis: u32,
    pub weekday: u32, // 0 = Sunday
}

const WEEKDAYS: [&str; 7] = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS: [&str; 12] = [
    "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December",
];

impl LocalTime {
    pub fn now() -> Self {
        Self::from_ms(js_sys::Date::now())
    }
    pub fn from_ms(ms: f64) -> Self {
        let d = js_sys::Date::new(&wasm_bindgen::JsValue::from_f64(ms));
        Self {
            year: d.get_full_year() as i32,
            month: d.get_month() + 1,
            day: d.get_date(),
            hour: d.get_hours(),
            minute: d.get_minutes(),
            second: d.get_seconds(),
            millis: d.get_milliseconds(),
            weekday: d.get_day(),
        }
    }
    pub fn date(&self) -> String {
        format!("{:04}-{:02}-{:02}", self.year, self.month, self.day)
    }
    pub fn iso(&self) -> String {
        format!("{}T{:02}:{:02}:{:02}", self.date(), self.hour, self.minute, self.second)
    }
    pub fn weekday_name(&self) -> &'static str {
        WEEKDAYS[self.weekday as usize % 7]
    }
    pub fn month_name(&self) -> &'static str {
        MONTHS[(self.month as usize + 11) % 12]
    }
    /// `%A, %B %d, %Y at %I:%M %p`
    pub fn spoken(&self) -> String {
        let hour12 = if self.hour % 12 == 0 { 12 } else { self.hour % 12 };
        let ampm = if self.hour < 12 { "AM" } else { "PM" };
        format!(
            "{}, {} {:02}, {} at {:02}:{:02} {}",
            self.weekday_name(),
            self.month_name(),
            self.day,
            self.year,
            hour12,
            self.minute,
            ampm
        )
    }
    /// `%Y%m%d-%H%M%S-%f`
    pub fn stamp(&self) -> String {
        format!(
            "{:04}{:02}{:02}-{:02}{:02}{:02}-{:06}",
            self.year, self.month, self.day, self.hour, self.minute, self.second, self.millis * 1000
        )
    }
}

/// UTC ISO-8601 timestamp with offset, like `datetime.now(timezone.utc).isoformat()`.
pub fn utc_iso() -> String {
    let d = js_sys::Date::new_0();
    let iso = String::from(d.to_iso_string()); // 2026-11-10T12:00:00.000Z
    format!("{}+00:00", iso.trim_end_matches('Z'))
}
