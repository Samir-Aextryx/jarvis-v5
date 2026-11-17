//! Calendar time zone (`JARVIS_TIMEZONE`, default Europe/Zurich), civil date
//! arithmetic and ISO-8601 parsing. WebAssembly has no zone database, so
//! offsets come from Electron's ICU through `Intl.DateTimeFormat`.

use crate::config;
use crate::host::Res;
use js_sys::{Array, Intl, Object, Reflect};
use std::cell::RefCell;
use wasm_bindgen::JsValue;

pub fn zone() -> String {
    config::get("JARVIS_TIMEZONE").filter(|z| !z.trim().is_empty()).unwrap_or_else(|| "Europe/Zurich".into())
}

thread_local! {
    static FORMAT: RefCell<Option<(String, Intl::DateTimeFormat)>> = const { RefCell::new(None) };
}

fn formatter(zone: &str) -> Intl::DateTimeFormat {
    FORMAT.with(|f| {
        if let Some((z, fmt)) = &*f.borrow()
            && z == zone
        {
            return fmt.clone();
        }
        let options = Object::new();
        let set = |k: &str, v: &str| {
            let _ = Reflect::set(&options, &k.into(), &v.into());
        };
        set("timeZone", zone);
        set("hourCycle", "h23");
        for k in ["year", "month", "day", "hour", "minute", "second"] {
            set(k, "numeric");
        }
        let fmt = Intl::DateTimeFormat::new(&Array::of1(&"en-US".into()), &options);
        *f.borrow_mut() = Some((zone.to_string(), fmt.clone()));
        fmt
    })
}

/// Offset of `zone` from UTC in seconds at the UTC instant `utc_secs`.
pub fn offset_at(zone: &str, utc_secs: i64) -> i64 {
    let date = js_sys::Date::new(&JsValue::from_f64(utc_secs as f64 * 1000.0));
    let parts = formatter(zone).format_to_parts(&date);
    let mut v = [0i64; 6];
    for part in parts.iter() {
        let kind = Reflect::get(&part, &"type".into()).ok().and_then(|t| t.as_string()).unwrap_or_default();
        let value: i64 = Reflect::get(&part, &"value".into()).ok().and_then(|t| t.as_string()).and_then(|t| t.parse().ok()).unwrap_or(0);
        let slot = match kind.as_str() {
            "year" => 0,
            "month" => 1,
            "day" => 2,
            "hour" => 3,
            "minute" => 4,
            "second" => 5,
            _ => continue,
        };
        v[slot] = value;
    }
    let wall = days_from_civil(v[0], v[1], v[2]) * 86400 + (v[3] % 24) * 3600 + v[4] * 60 + v[5];
    wall - utc_secs
}

// ---- civil dates ---------------------------------------------------------------------

/// Days since 1970-01-01 (proleptic Gregorian).
pub fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let mp = (m + 9) % 12;
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

pub fn civil_from_days(z: i64) -> (i64, i64, i64) {
    let z = z + 719468;
    let era = z.div_euclid(146097);
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (yoe + era * 400 + i64::from(m <= 2), m, d)
}

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug)]
pub struct Date {
    pub days: i64,
}

impl Date {
    pub fn parse(text: &str) -> Res<Self> {
        let bad = || format!("Invalid isoformat string: '{text}'");
        let b = text.as_bytes();
        if b.len() != 10 || b[4] != b'-' || b[7] != b'-' {
            return Err(bad());
        }
        let num = |r: std::ops::Range<usize>| text[r].parse::<i64>().map_err(|_| bad());
        let (y, m, d) = (num(0..4)?, num(5..7)?, num(8..10)?);
        if !(1..=12).contains(&m) || d < 1 || d > month_days(y, m) {
            return Err(bad());
        }
        Ok(Self { days: days_from_civil(y, m, d) })
    }
    pub fn iso(&self) -> String {
        let (y, m, d) = civil_from_days(self.days);
        format!("{y:04}-{m:02}-{d:02}")
    }
    pub fn add(&self, days: i64) -> Self {
        Self { days: self.days + days }
    }
    /// Monday = 0, like Python's `weekday()`.
    pub fn weekday(&self) -> i64 {
        (self.days + 3).rem_euclid(7)
    }
    /// Midnight of this date in `zone`, as UTC seconds.
    pub fn midnight(&self, zone: &str) -> Res<i64> {
        local_to_utc(zone, self.days * 86400)
    }
}

fn month_days(y: i64, m: i64) -> i64 {
    match m {
        2 if (y % 4 == 0 && y % 100 != 0) || y % 400 == 0 => 29,
        2 => 28,
        4 | 6 | 9 | 11 => 30,
        _ => 31,
    }
}

/// Converts a wall-clock time (seconds since the epoch, as if UTC) in `zone`
/// to a UTC instant. Fails for times skipped or repeated by a clock change.
pub fn local_to_utc(zone: &str, wall: i64) -> Res<i64> {
    let mut found: Vec<i64> = Vec::new();
    for probe in [wall - 86400, wall + 86400] {
        let off = offset_at(zone, probe);
        let utc = wall - off;
        if offset_at(zone, utc) == off && !found.contains(&utc) {
            found.push(utc);
        }
    }
    match found.len() {
        1 => Ok(found[0]),
        0 => Err("That local time does not exist due to a clock change.".into()),
        _ => Err("This time crosses a clock change. Please give an explicit UTC offset.".into()),
    }
}

/// A point in time shown in the calendar zone.
#[derive(Clone, Debug)]
pub struct Moment {
    pub utc: i64,
    pub micros: i64,
}

impl Moment {
    pub fn now() -> Self {
        let ms = js_sys::Date::now();
        Self { utc: (ms / 1000.0).floor() as i64, micros: ((ms % 1000.0) * 1000.0) as i64 }
    }
    pub fn from_utc(utc: i64) -> Self {
        Self { utc, micros: 0 }
    }
    pub fn timestamp(&self) -> f64 {
        self.utc as f64 + self.micros as f64 / 1e6
    }
    pub fn add_days(&self, days: i64) -> Self {
        Self { utc: self.utc + days * 86400, micros: self.micros }
    }
    /// Local calendar date in `zone`.
    pub fn date(&self, zone: &str) -> Date {
        Date { days: (self.utc + offset_at(zone, self.utc)).div_euclid(86400) }
    }
    /// Python's `isoformat()` of the aware datetime in `zone`.
    pub fn iso(&self, zone: &str) -> String {
        let off = offset_at(zone, self.utc);
        let wall = self.utc + off;
        let (y, m, d) = civil_from_days(wall.div_euclid(86400));
        let sec = wall.rem_euclid(86400);
        let mut out = format!("{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}", sec / 3600, sec % 3600 / 60, sec % 60);
        if self.micros != 0 {
            out += &format!(".{:06}", self.micros);
        }
        let sign = if off < 0 { '-' } else { '+' };
        let a = off.abs();
        out += &format!("{sign}{:02}:{:02}", a / 3600, a % 3600 / 60);
        out
    }
}

/// Parses `YYYY-MM-DD[T ]HH:MM[:SS[.ffffff]][Z|±HH:MM]`; naive times are in `zone`.
pub fn parse_moment(text: &str, zone: &str) -> Res<Moment> {
    let caps = crate::re!(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?(Z|[+-]\d{2}:?\d{2})?$")
        .captures(text.trim())
        .ok_or_else(|| "Please give both the date and time.".to_string())?;
    let date = Date::parse(&caps[1])?;
    let num = |i: usize| caps.get(i).map(|m| m.as_str().parse::<i64>().unwrap_or(0)).unwrap_or(0);
    let (h, mi, se) = (num(2), num(3), num(4));
    if h > 23 || mi > 59 || se > 59 {
        return Err(format!("Invalid isoformat string: '{text}'"));
    }
    let micros = caps.get(5).map(|f| format!("{:0<6}", f.as_str()).parse::<i64>().unwrap_or(0)).unwrap_or(0);
    let wall = date.days * 86400 + h * 3600 + mi * 60 + se;
    let utc = match caps.get(6).map(|m| m.as_str()) {
        Some("Z") => wall,
        Some(off) => {
            let digits: String = off[1..].chars().filter(char::is_ascii_digit).collect();
            let secs = digits[..2].parse::<i64>().unwrap_or(0) * 3600 + digits[2..].parse::<i64>().unwrap_or(0) * 60;
            wall - if off.starts_with('-') { -secs } else { secs }
        }
        None => local_to_utc(zone, wall)?,
    };
    Ok(Moment { utc, micros })
}
