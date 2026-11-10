//! HTTP/1.1 request and response types for the local server.

use serde::de::DeserializeOwned;
use serde_json::{Value, json};

pub struct Request {
    pub method: String,
    pub path: String,
    pub query: String,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}

impl Request {
    pub fn header(&self, name: &str) -> Option<&str> {
        self.headers.iter().find(|(k, _)| k.eq_ignore_ascii_case(name)).map(|(_, v)| v.as_str())
    }
    pub fn query_param(&self, name: &str) -> Option<String> {
        self.query.split('&').find_map(|pair| {
            let (k, v) = pair.split_once('=').unwrap_or((pair, ""));
            (url_decode(k) == name).then(|| url_decode(v))
        })
    }
    pub fn content_type(&self) -> String {
        self.header("content-type").unwrap_or("").split(';').next().unwrap_or("").trim().to_ascii_lowercase()
    }
    /// Parses the JSON body; invalid input becomes FastAPI's 422 shape.
    pub fn json<T: DeserializeOwned>(&self) -> Result<T, Response> {
        serde_json::from_slice(&self.body).map_err(|e| {
            Response::json(422, &json!({ "detail": [{ "msg": e.to_string(), "type": "value_error" }] }))
        })
    }
    pub fn json_value(&self) -> Result<Value, Response> {
        self.json::<Value>()
    }
}

pub fn url_decode(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        match bytes[i] {
            b'+' => out.push(b' '),
            b'%' if i + 2 < bytes.len() => {
                let hex = std::str::from_utf8(&bytes[i + 1..i + 3]).ok().and_then(|h| u8::from_str_radix(h, 16).ok());
                match hex {
                    Some(b) => {
                        out.push(b);
                        i += 2;
                    }
                    None => out.push(b'%'),
                }
            }
            b => out.push(b),
        }
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

pub struct Response {
    pub status: u16,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}

impl Response {
    pub fn new(status: u16, content_type: &str, body: Vec<u8>) -> Self {
        Self { status, headers: vec![("Content-Type".into(), content_type.into())], body }
    }
    pub fn json(status: u16, value: &Value) -> Self {
        Self::new(status, "application/json", serde_json::to_vec(value).unwrap_or_default())
    }
    pub fn ok(value: Value) -> Self {
        Self::json(200, &value)
    }
    pub fn error(status: u16, message: &str) -> Self {
        Self::json(status, &json!({ "error": message }))
    }
    pub fn detail(status: u16, message: &str) -> Self {
        Self::json(status, &json!({ "detail": message }))
    }
    pub fn html(status: u16, html: String) -> Self {
        Self::new(status, "text/html; charset=utf-8", html.into_bytes())
    }
    pub fn not_found() -> Self {
        Self::detail(404, "Not Found")
    }
    pub fn with_header(mut self, name: &str, value: &str) -> Self {
        self.set_header(name, value);
        self
    }
    pub fn set_header(&mut self, name: &str, value: &str) {
        self.headers.retain(|(k, _)| !k.eq_ignore_ascii_case(name));
        self.headers.push((name.into(), value.into()));
    }
    pub fn set_default_header(&mut self, name: &str, value: &str) {
        if !self.headers.iter().any(|(k, _)| k.eq_ignore_ascii_case(name)) {
            self.headers.push((name.into(), value.into()));
        }
    }
    pub fn serialize(&self, keep_alive: bool, head_only: bool) -> Vec<u8> {
        let mut out = format!("HTTP/1.1 {} {}\r\n", self.status, reason(self.status));
        for (k, v) in &self.headers {
            out.push_str(&format!("{k}: {v}\r\n"));
        }
        out.push_str(&format!("Content-Length: {}\r\n", self.body.len()));
        out.push_str(if keep_alive { "Connection: keep-alive\r\n\r\n" } else { "Connection: close\r\n\r\n" });
        let mut bytes = out.into_bytes();
        if !head_only {
            bytes.extend_from_slice(&self.body);
        }
        bytes
    }
}

pub fn reason(status: u16) -> &'static str {
    match status {
        101 => "Switching Protocols",
        200 => "OK",
        204 => "No Content",
        400 => "Bad Request",
        401 => "Unauthorized",
        403 => "Forbidden",
        404 => "Not Found",
        405 => "Method Not Allowed",
        409 => "Conflict",
        410 => "Gone",
        413 => "Payload Too Large",
        415 => "Unsupported Media Type",
        422 => "Unprocessable Entity",
        423 => "Locked",
        429 => "Too Many Requests",
        500 => "Internal Server Error",
        502 => "Bad Gateway",
        503 => "Service Unavailable",
        _ => "OK",
    }
}

pub fn content_type_for(path: &str) -> &'static str {
    let ext = path.rsplit('.').next().unwrap_or("").to_ascii_lowercase();
    match ext.as_str() {
        "html" => "text/html; charset=utf-8",
        "js" | "mjs" => "text/javascript; charset=utf-8",
        "css" => "text/css; charset=utf-8",
        "json" => "application/json",
        "svg" => "image/svg+xml",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "webp" => "image/webp",
        "ico" => "image/x-icon",
        "woff" => "font/woff",
        "woff2" => "font/woff2",
        "ttf" => "font/ttf",
        "mp3" => "audio/mpeg",
        "wav" => "audio/wav",
        "map" => "application/json",
        "txt" => "text/plain; charset=utf-8",
        _ => "application/octet-stream",
    }
}
