//! Bindings to `desktop/host.cjs`, the I/O shim. WebAssembly cannot reach the
//! operating system, so every socket, file, process and Windows call goes
//! through these few primitives. All decisions stay on the Rust side.

use js_sys::{Promise, Uint8Array};
use serde_json::{Value, json};
use wasm_bindgen::prelude::*;
use wasm_bindgen_futures::JsFuture;

#[wasm_bindgen]
extern "C" {
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = log)]
    fn h_log(level: &str, message: &str);
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = envJson)]
    fn h_env_json() -> String;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = pathsJson)]
    fn h_paths_json() -> String;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = setChildEnvBlocklist)]
    fn h_set_child_env_blocklist(json: &str);
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = randomBytes)]
    fn h_random_bytes(count: u32) -> Vec<u8>;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = monotonic)]
    fn h_monotonic() -> f64;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = sleep)]
    fn h_sleep(ms: f64) -> Promise;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = restart)]
    fn h_restart();
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = exit)]
    fn h_exit(code: i32);

    #[wasm_bindgen(js_namespace = jarvisHost, js_name = listen)]
    fn h_listen(address: &str, port: u16) -> Promise;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = accept)]
    fn h_accept(id: u32) -> Promise;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = read)]
    fn h_read(id: u32) -> Promise;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = write)]
    fn h_write(id: u32, data: &[u8]);
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = close)]
    fn h_close(id: u32);

    #[wasm_bindgen(js_namespace = jarvisHost, js_name = fetchStart)]
    fn h_fetch_start(url: &str, method: &str, headers: &str, body: &[u8], idle_ms: f64) -> Promise;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = bodyRead)]
    fn h_body_read(id: u32) -> Promise;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = bodyClose)]
    fn h_body_close(id: u32);

    #[wasm_bindgen(js_namespace = jarvisHost, js_name = wsConnect)]
    fn h_ws_connect(url: &str, protocols: &str, headers: &str, timeout_ms: f64) -> Promise;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = wsRecv)]
    fn h_ws_recv(id: u32) -> Promise;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = wsSendText)]
    fn h_ws_send_text(id: u32, text: &str);
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = wsSendBinary)]
    fn h_ws_send_binary(id: u32, data: &[u8]);
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = wsClose)]
    fn h_ws_close(id: u32);

    #[wasm_bindgen(js_namespace = jarvisHost, js_name = readFile)]
    fn h_read_file(path: &str) -> Option<Vec<u8>>;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = writeFile, catch)]
    fn h_write_file(path: &str, data: &[u8]) -> Result<(), JsValue>;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = createFile)]
    fn h_create_file(path: &str, data: &[u8]) -> String;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = appendFile, catch)]
    fn h_append_file(path: &str, data: &[u8]) -> Result<(), JsValue>;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = remove)]
    fn h_remove(path: &str) -> bool;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = rename, catch)]
    fn h_rename(from: &str, to: &str) -> Result<(), JsValue>;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = mkdirp, catch)]
    fn h_mkdirp(path: &str) -> Result<(), JsValue>;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = stat)]
    fn h_stat(path: &str) -> Option<String>;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = listDir)]
    fn h_list_dir(path: &str) -> Option<String>;

    #[wasm_bindgen(js_namespace = jarvisHost, js_name = run)]
    fn h_run(file: &str, args: &str, options: &str) -> Promise;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = spawnDetached)]
    fn h_spawn_detached(file: &str, args: &str, options: &str) -> u32;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = procStart, catch)]
    fn h_proc_start(file: &str, args: &str, options: &str) -> Result<u32, JsValue>;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = procRead)]
    fn h_proc_read(id: u32) -> Promise;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = procWait)]
    fn h_proc_wait(id: u32) -> Promise;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = procKill)]
    fn h_proc_kill(id: u32);

    #[wasm_bindgen(js_namespace = jarvisHost, js_name = psSetScript)]
    fn h_ps_set_script(script: &str);
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = psCall)]
    fn h_ps_call(request: &str) -> Promise;

    #[wasm_bindgen(js_namespace = jarvisHost, js_name = sqlOpen, catch)]
    fn h_sql_open(path: &str) -> Result<u32, JsValue>;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = sqlExec, catch)]
    fn h_sql_exec(id: u32, sql: &str) -> Result<(), JsValue>;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = sqlQuery, catch)]
    fn h_sql_query(id: u32, sql: &str, params: &str) -> Result<String, JsValue>;
    #[wasm_bindgen(js_namespace = jarvisHost, js_name = sqlRun, catch)]
    fn h_sql_run(id: u32, sql: &str, params: &str) -> Result<String, JsValue>;
}

pub type Res<T> = Result<T, String>;

pub fn js_error(value: JsValue) -> String {
    if let Some(error) = value.dyn_ref::<js_sys::Error>() {
        return String::from(error.message());
    }
    value.as_string().unwrap_or_else(|| "host error".into())
}

async fn wait(promise: Promise) -> Res<JsValue> {
    JsFuture::from(promise).await.map_err(js_error)
}

fn opt_bytes(value: JsValue) -> Option<Vec<u8>> {
    if value.is_null() || value.is_undefined() {
        None
    } else {
        Some(Uint8Array::new(&value).to_vec())
    }
}

// ---- logging, time, randomness ------------------------------------------

pub fn log(level: &str, message: &str) {
    h_log(level, message);
}
#[macro_export]
macro_rules! info { ($($t:tt)*) => { $crate::host::log("info", &format!($($t)*)) } }
#[macro_export]
macro_rules! warn { ($($t:tt)*) => { $crate::host::log("warning", &format!($($t)*)) } }
#[macro_export]
macro_rules! error { ($($t:tt)*) => { $crate::host::log("error", &format!($($t)*)) } }

pub fn env_json() -> String {
    h_env_json()
}
pub fn paths_json() -> String {
    h_paths_json()
}
pub fn set_child_env_blocklist(names: &[&str]) {
    h_set_child_env_blocklist(&serde_json::to_string(names).unwrap_or_default());
}
pub fn random_bytes(count: u32) -> Vec<u8> {
    h_random_bytes(count)
}
/// Milliseconds since an arbitrary start; never jumps with the wall clock.
pub fn monotonic() -> f64 {
    h_monotonic()
}
/// Wall-clock milliseconds since the Unix epoch.
pub fn now_ms() -> f64 {
    js_sys::Date::now()
}
pub fn now_secs() -> f64 {
    now_ms() / 1000.0
}
pub async fn sleep(ms: f64) {
    let _ = wait(h_sleep(ms)).await;
}
pub fn restart() {
    h_restart();
}
pub fn exit(code: i32) {
    h_exit(code);
}

// ---- TCP server ------------------------------------------------------------

pub async fn listen(address: &str, port: u16) -> Res<u32> {
    let id = wait(h_listen(address, port)).await?;
    Ok(id.as_f64().unwrap_or(0.0) as u32)
}
pub async fn accept(listener: u32) -> Option<u32> {
    let id = wait(h_accept(listener)).await.ok()?;
    id.as_f64().map(|v| v as u32)
}
pub async fn sock_read(id: u32) -> Option<Vec<u8>> {
    opt_bytes(wait(h_read(id)).await.ok()?)
}
pub fn sock_write(id: u32, data: &[u8]) {
    h_write(id, data);
}
pub fn sock_close(id: u32) {
    h_close(id);
}

// ---- outbound HTTP -----------------------------------------------------------

pub struct HttpResponse {
    pub status: u16,
    pub headers: serde_json::Map<String, Value>,
    id: u32,
    done: bool,
}

impl HttpResponse {
    pub fn header(&self, name: &str) -> Option<&str> {
        self.headers.get(&name.to_ascii_lowercase()).and_then(Value::as_str)
    }
    pub async fn chunk(&mut self) -> Res<Option<Vec<u8>>> {
        if self.done {
            return Ok(None);
        }
        let value = wait(h_body_read(self.id)).await?;
        let chunk = opt_bytes(value);
        if chunk.is_none() {
            self.done = true;
        }
        Ok(chunk)
    }
    pub async fn bytes_limited(&mut self, limit: usize) -> Res<Vec<u8>> {
        let mut body = Vec::new();
        while let Some(chunk) = self.chunk().await? {
            body.extend_from_slice(&chunk);
            if body.len() > limit {
                return Err("response too large".into());
            }
        }
        Ok(body)
    }
    pub async fn bytes(&mut self) -> Res<Vec<u8>> {
        self.bytes_limited(64 * 1024 * 1024).await
    }
    pub async fn text(&mut self) -> Res<String> {
        Ok(String::from_utf8_lossy(&self.bytes().await?).into_owned())
    }
    pub async fn json(&mut self) -> Res<Value> {
        serde_json::from_slice(&self.bytes().await?).map_err(|e| e.to_string())
    }
    pub fn ok(&self) -> bool {
        (200..300).contains(&self.status)
    }
}

impl Drop for HttpResponse {
    fn drop(&mut self) {
        // Dropping an unread response (e.g. a cancelled turn) aborts the request.
        h_body_close(self.id);
    }
}

pub struct Http {
    url: String,
    method: String,
    headers: Vec<(String, String)>,
    body: Vec<u8>,
    idle_ms: f64,
}

impl Http {
    pub fn new(method: &str, url: &str) -> Self {
        Self { url: url.into(), method: method.into(), headers: Vec::new(), body: Vec::new(), idle_ms: 30_000.0 }
    }
    pub fn get(url: &str) -> Self {
        Self::new("GET", url)
    }
    pub fn post(url: &str) -> Self {
        Self::new("POST", url)
    }
    pub fn header(mut self, name: &str, value: &str) -> Self {
        self.headers.push((name.into(), value.into()));
        self
    }
    pub fn bearer(self, token: &str) -> Self {
        self.header("Authorization", &format!("Bearer {token}"))
    }
    pub fn timeout(mut self, seconds: f64) -> Self {
        self.idle_ms = seconds * 1000.0;
        self
    }
    pub fn json(mut self, body: &Value) -> Self {
        self.body = serde_json::to_vec(body).unwrap_or_default();
        self.header("Content-Type", "application/json")
    }
    pub fn body(mut self, content_type: &str, body: Vec<u8>) -> Self {
        self.body = body;
        self.header("Content-Type", content_type)
    }
    pub fn form(self, fields: &[(&str, &str)]) -> Self {
        let body = fields.iter().map(|(k, v)| format!("{}={}", url_encode(k), url_encode(v))).collect::<Vec<_>>().join("&");
        self.body("application/x-www-form-urlencoded", body.into_bytes())
    }
    pub async fn send(self) -> Res<HttpResponse> {
        let mut headers = serde_json::Map::new();
        for (name, value) in &self.headers {
            headers.insert(name.clone(), Value::String(value.clone()));
        }
        let headers = Value::Object(headers).to_string();
        let raw = wait(h_fetch_start(&self.url, &self.method, &headers, &self.body, self.idle_ms)).await?;
        let meta: Value = serde_json::from_str(&raw.as_string().unwrap_or_default()).map_err(|e| e.to_string())?;
        Ok(HttpResponse {
            status: meta["status"].as_u64().unwrap_or(0) as u16,
            headers: meta["headers"].as_object().cloned().unwrap_or_default(),
            id: meta["id"].as_u64().unwrap_or(0) as u32,
            done: false,
        })
    }
}

pub fn url_encode(text: &str) -> String {
    let mut out = String::new();
    for byte in text.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => out.push(byte as char),
            _ => out.push_str(&format!("%{byte:02X}")),
        }
    }
    out
}

// ---- outbound WebSocket -------------------------------------------------------

pub enum WsMessage {
    Text(String),
    Binary(Vec<u8>),
}

pub struct WsClient(u32);

impl WsClient {
    pub async fn connect(url: &str, protocols: &[&str], headers: &[(&str, &str)], timeout_ms: f64) -> Res<Self> {
        let mut map = serde_json::Map::new();
        for (k, v) in headers {
            map.insert((*k).into(), Value::String((*v).into()));
        }
        let protocols = serde_json::to_string(protocols).unwrap_or_default();
        let id = wait(h_ws_connect(url, &protocols, &Value::Object(map).to_string(), timeout_ms)).await?;
        Ok(Self(id.as_f64().unwrap_or(0.0) as u32))
    }
    pub async fn recv(&self) -> Res<Option<WsMessage>> {
        let value = wait(h_ws_recv(self.0)).await?;
        if value.is_null() || value.is_undefined() {
            return Ok(None);
        }
        if let Some(text) = value.as_string() {
            return Ok(Some(WsMessage::Text(text)));
        }
        Ok(Some(WsMessage::Binary(Uint8Array::new(&value).to_vec())))
    }
    pub fn send_text(&self, text: &str) {
        h_ws_send_text(self.0, text);
    }
    pub fn send_json(&self, value: &Value) {
        self.send_text(&value.to_string());
    }
    pub fn send_binary(&self, data: &[u8]) {
        h_ws_send_binary(self.0, data);
    }
}

impl Drop for WsClient {
    fn drop(&mut self) {
        h_ws_close(self.0);
    }
}

// ---- files ----------------------------------------------------------------------

pub mod fs {
    use super::*;

    pub fn read(path: &str) -> Option<Vec<u8>> {
        h_read_file(path)
    }
    pub fn read_text(path: &str) -> Option<String> {
        read(path).map(|b| String::from_utf8_lossy(&b).into_owned())
    }
    pub fn read_json(path: &str) -> Option<Value> {
        serde_json::from_slice(&read(path)?).ok()
    }
    /// Atomic replace: written to a temporary file, then renamed.
    pub fn write(path: &str, data: &[u8]) -> Res<()> {
        h_write_file(path, data).map_err(js_error)
    }
    /// Creates a new file; Err("EEXIST") when it already exists.
    pub fn create_new(path: &str, data: &[u8]) -> Res<()> {
        let error = h_create_file(path, data);
        if error.is_empty() { Ok(()) } else { Err(error) }
    }
    pub fn write_text(path: &str, text: &str) -> Res<()> {
        write(path, text.as_bytes())
    }
    pub fn append(path: &str, data: &[u8]) -> Res<()> {
        h_append_file(path, data).map_err(js_error)
    }
    pub fn remove(path: &str) -> bool {
        h_remove(path)
    }
    pub fn rename(from: &str, to: &str) -> Res<()> {
        h_rename(from, to).map_err(js_error)
    }
    pub fn mkdirp(path: &str) -> Res<()> {
        h_mkdirp(path).map_err(js_error)
    }
    pub struct Stat {
        pub dir: bool,
        pub file: bool,
        pub size: u64,
        pub mtime: f64,
    }
    pub fn stat(path: &str) -> Option<Stat> {
        let v: Value = serde_json::from_str(&h_stat(path)?).ok()?;
        Some(Stat {
            dir: v["dir"].as_bool().unwrap_or(false),
            file: v["file"].as_bool().unwrap_or(false),
            size: v["size"].as_u64().unwrap_or(0),
            mtime: v["mtime"].as_f64().unwrap_or(0.0),
        })
    }
    pub fn exists(path: &str) -> bool {
        stat(path).is_some()
    }
    pub struct Entry {
        pub name: String,
        pub dir: bool,
        pub file: bool,
        pub link: bool,
    }
    pub fn list_dir(path: &str) -> Vec<Entry> {
        let Some(raw) = h_list_dir(path) else { return Vec::new() };
        let Ok(Value::Array(rows)) = serde_json::from_str::<Value>(&raw) else { return Vec::new() };
        rows.iter()
            .map(|r| Entry {
                name: r["name"].as_str().unwrap_or_default().to_string(),
                dir: r["dir"].as_bool().unwrap_or(false),
                file: r["file"].as_bool().unwrap_or(false) || r["link"].as_bool().unwrap_or(false),
                link: r["link"].as_bool().unwrap_or(false),
            })
            .collect()
    }
    /// Join Windows path segments.
    pub fn join(base: &str, part: &str) -> String {
        if base.is_empty() {
            return part.to_string();
        }
        let base = base.trim_end_matches(['\\', '/']);
        format!("{base}\\{}", part.trim_start_matches(['\\', '/']).replace('/', "\\"))
    }
    pub fn file_name(path: &str) -> &str {
        path.rsplit(['\\', '/']).next().unwrap_or(path)
    }
    pub fn parent(path: &str) -> &str {
        match path.trim_end_matches(['\\', '/']).rfind(['\\', '/']) {
            Some(i) => &path[..i],
            None => "",
        }
    }
}

// ---- processes ------------------------------------------------------------------

pub struct RunOutput {
    pub code: i32,
    pub stdout: String,
    pub stderr: String,
}

pub async fn run(file: &str, args: &[&str], options: Value) -> RunOutput {
    let args = serde_json::to_string(args).unwrap_or_default();
    let raw = match wait(h_run(file, &args, &options.to_string())).await {
        Ok(v) => v.as_string().unwrap_or_default(),
        Err(e) => return RunOutput { code: -1, stdout: String::new(), stderr: e },
    };
    let v: Value = serde_json::from_str(&raw).unwrap_or(Value::Null);
    RunOutput {
        code: v["code"].as_i64().unwrap_or(-1) as i32,
        stdout: v["stdout"].as_str().unwrap_or_default().to_string(),
        stderr: v["stderr"].as_str().unwrap_or_default().to_string(),
    }
}

pub fn spawn_detached(file: &str, args: &[&str], options: Value) -> bool {
    let args = serde_json::to_string(args).unwrap_or_default();
    h_spawn_detached(file, &args, &options.to_string()) != 0
}

/// A running child process whose stdout is read as it arrives.
pub struct Proc(u32);

impl Proc {
    pub fn start(file: &str, args: &[&str], options: Value) -> Res<Self> {
        let args = serde_json::to_string(args).unwrap_or_default();
        h_proc_start(file, &args, &options.to_string()).map(Proc).map_err(js_error)
    }
    /// Next stdout chunk; None at the end of the output.
    pub async fn read(&self) -> Option<String> {
        wait(h_proc_read(self.0)).await.ok().and_then(|v| v.as_string())
    }
    pub async fn wait(&self) -> i32 {
        wait(h_proc_wait(self.0)).await.ok().and_then(|v| v.as_f64()).unwrap_or(-1.0) as i32
    }
    /// Ends the whole process tree.
    pub fn kill(&self) {
        h_proc_kill(self.0);
    }
}

/// Starts a document, folder or URL with its Windows default handler.
pub fn shell_open(target: &str) -> bool {
    spawn_detached("explorer.exe", &[target], json!({}))
}

// ---- PowerShell bridge ---------------------------------------------------------------

pub fn ps_set_script(script: &str) {
    h_ps_set_script(script);
}

/// Calls a command of the long-lived PowerShell bridge (see `winapi.rs`).
pub async fn ps(cmd: &str, args: Value) -> Res<Value> {
    let request = json!({ "cmd": cmd, "args": args }).to_string();
    let raw = wait(h_ps_call(&request)).await?;
    let reply: Value = serde_json::from_str(&raw.as_string().unwrap_or_default()).map_err(|e| e.to_string())?;
    if reply["ok"].as_bool() == Some(true) {
        Ok(reply.get("result").cloned().unwrap_or(Value::Null))
    } else {
        Err(reply["error"].as_str().unwrap_or("PowerShell bridge error").to_string())
    }
}

// ---- SQLite ---------------------------------------------------------------------------

#[derive(Clone, Copy)]
pub struct Db(u32);

impl Db {
    pub fn open(path: &str) -> Res<Self> {
        h_sql_open(path).map(Db).map_err(js_error)
    }
    pub fn exec(&self, sql: &str) -> Res<()> {
        h_sql_exec(self.0, sql).map_err(js_error)
    }
    pub fn query(&self, sql: &str, params: Value) -> Res<Vec<Value>> {
        let raw = h_sql_query(self.0, sql, &params.to_string()).map_err(js_error)?;
        match serde_json::from_str(&raw) {
            Ok(Value::Array(rows)) => Ok(rows),
            _ => Ok(Vec::new()),
        }
    }
    pub fn query_one(&self, sql: &str, params: Value) -> Res<Option<Value>> {
        Ok(self.query(sql, params)?.into_iter().next())
    }
    /// Returns (changes, last insert row id).
    pub fn run(&self, sql: &str, params: Value) -> Res<(i64, i64)> {
        let raw = h_sql_run(self.0, sql, &params.to_string()).map_err(js_error)?;
        let v: Value = serde_json::from_str(&raw).unwrap_or(Value::Null);
        Ok((v["changes"].as_i64().unwrap_or(0), v["lastId"].as_i64().unwrap_or(0)))
    }
}
