//! The local HTTP/1.1 + WebSocket server (127.0.0.1 only).

use crate::auth;
use crate::host::{self, Res};
use crate::http::{Request, Response};
use crate::ws::WebSocket;
use std::rc::Rc;
use wasm_bindgen_futures::spawn_local;

const MAX_HEADER: usize = 64 * 1024;
const MAX_BODY: usize = 21 * 1024 * 1024;

const ALLOWED_ORIGINS: [&str; 6] = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://localhost:5173",
    "https://127.0.0.1:5173",
    "http://localhost:8340",
    "https://localhost:8340",
];

// The renderer holds a bearer token, so restrict what a stray script could
// load or contact. The launch page bootstraps with an inline script.
const CSP: &str = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; \
media-src 'self' blob: data:; connect-src 'self' http://127.0.0.1:* http://localhost:* ws://127.0.0.1:* ws://localhost:*; \
font-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'";

pub async fn serve(address: &str, port: u16) -> Res<()> {
    let listener = host::listen(address, port).await?;
    spawn_local(async move {
        while let Some(conn) = host::accept(listener).await {
            spawn_local(connection(conn));
        }
    });
    Ok(())
}

enum Parsed {
    Request(Request, usize),
    Incomplete,
    Invalid(u16),
}

fn parse(buf: &[u8]) -> Parsed {
    let mut headers = [httparse::EMPTY_HEADER; 64];
    let mut req = httparse::Request::new(&mut headers);
    let header_len = match req.parse(buf) {
        Ok(httparse::Status::Complete(n)) => n,
        Ok(httparse::Status::Partial) => {
            return if buf.len() > MAX_HEADER { Parsed::Invalid(431) } else { Parsed::Incomplete };
        }
        Err(_) => return Parsed::Invalid(400),
    };
    let target = req.path.unwrap_or("/");
    let (path, query) = target.split_once('?').unwrap_or((target, ""));
    let headers: Vec<(String, String)> = req
        .headers
        .iter()
        .map(|h| (h.name.to_ascii_lowercase(), String::from_utf8_lossy(h.value).into_owned()))
        .collect();
    if headers.iter().any(|(k, v)| k == "transfer-encoding" && !v.eq_ignore_ascii_case("identity")) {
        return Parsed::Invalid(411);
    }
    let length = headers
        .iter()
        .find(|(k, _)| k == "content-length")
        .map(|(_, v)| v.trim().parse::<usize>().ok())
        .unwrap_or(Some(0));
    let Some(length) = length else { return Parsed::Invalid(400) };
    if length > MAX_BODY {
        return Parsed::Invalid(413);
    }
    if buf.len() < header_len + length {
        return Parsed::Incomplete;
    }
    Parsed::Request(
        Request {
            method: req.method.unwrap_or("GET").to_string(),
            path: crate::http::url_decode(&path.replace('+', "%2B")),
            query: query.to_string(),
            headers,
            body: buf[header_len..header_len + length].to_vec(),
        },
        header_len + length,
    )
}

async fn connection(conn: u32) {
    let mut buf: Vec<u8> = Vec::new();
    loop {
        let (request, used) = loop {
            match parse(&buf) {
                Parsed::Request(r, used) => break (r, used),
                Parsed::Incomplete => match host::sock_read(conn).await {
                    Some(chunk) => buf.extend_from_slice(&chunk),
                    None => {
                        host::sock_close(conn);
                        return;
                    }
                },
                Parsed::Invalid(status) => {
                    let response = Response::detail(status, crate::http::reason(status));
                    host::sock_write(conn, &response.serialize(false, false));
                    host::sock_close(conn);
                    return;
                }
            }
        };
        buf.drain(..used);
        let upgrade = request.header("upgrade").is_some_and(|u| u.eq_ignore_ascii_case("websocket"));
        if upgrade {
            websocket(conn, request, std::mem::take(&mut buf)).await;
            return;
        }
        let keep_alive = !request.header("connection").is_some_and(|c| c.eq_ignore_ascii_case("close"));
        let head = request.method == "HEAD";
        let response = handle(request).await;
        host::sock_write(conn, &response.serialize(keep_alive, head));
        if !keep_alive {
            host::sock_close(conn);
            return;
        }
    }
}

fn is_exempt(path: &str) -> bool {
    matches!(path, "/api/health" | "/" | "/pcm-capture.js")
        || path == "/assets"
        || path.starts_with("/assets/")
        || path.starts_with("/launch/")
}

async fn handle(request: Request) -> Response {
    let origin = request.header("origin").map(str::to_string);
    let allowed_origin = origin.as_deref().filter(|o| ALLOWED_ORIGINS.contains(o)).map(str::to_string);
    let path = request.path.clone();
    let mut response = if request.method == "OPTIONS" && allowed_origin.is_some() {
        // CORS preflights cannot carry the Authorization header.
        Response::new(200, "text/plain", b"OK".to_vec())
            .with_header("Access-Control-Allow-Methods", "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT")
            .with_header(
                "Access-Control-Allow-Headers",
                request.header("access-control-request-headers").unwrap_or("authorization, content-type"),
            )
            .with_header("Access-Control-Max-Age", "600")
    } else if !is_exempt(&path) && !bearer_ok(&request) {
        Response::error(401, "Unauthorized — pass 'Authorization: Bearer <token>'")
    } else {
        crate::routes::route(request).await
    };
    if let Some(o) = allowed_origin {
        response.set_header("Access-Control-Allow-Origin", &o);
        response.set_header("Access-Control-Allow-Credentials", "true");
        response.set_header("Vary", "Origin");
    }
    response.set_default_header("X-Content-Type-Options", "nosniff");
    response.set_default_header("X-Frame-Options", "DENY");
    if path.starts_with("/launch/") {
        response.set_default_header("Content-Security-Policy", "frame-ancestors 'none'");
    } else {
        response.set_default_header("Content-Security-Policy", CSP);
    }
    response.set_default_header("Referrer-Policy", "no-referrer");
    response
}

fn bearer_ok(request: &Request) -> bool {
    let header = request.header("authorization").unwrap_or("");
    let token = header.strip_prefix("Bearer ").unwrap_or("");
    auth::verify(token)
}

async fn websocket(conn: u32, request: Request, leftover: Vec<u8>) {
    let Some(key) = request.header("sec-websocket-key").map(str::to_string) else {
        host::sock_write(conn, &Response::detail(400, "Bad Request").serialize(false, false));
        host::sock_close(conn);
        return;
    };
    let protocols: Vec<String> = request
        .header("sec-websocket-protocol")
        .unwrap_or("")
        .split(',')
        .map(|p| p.trim().to_string())
        .filter(|p| !p.is_empty())
        .collect();
    let route_known = matches!(request.path.as_str(), "/ws/voice" | "/ws/stt");
    if !route_known {
        host::sock_write(conn, &Response::not_found().serialize(false, false));
        host::sock_close(conn);
        return;
    }
    let jarvis = protocols.iter().any(|p| p == "jarvis");
    let authorized = auth::websocket_token_ok(&protocols);
    let socket = Rc::new(WebSocket::accept(conn, &key, protocols, jarvis.then_some("jarvis"), leftover));
    if !authorized {
        // Accept first so the browser receives 4001; a rejected handshake only shows 1006.
        socket.close(4001, "Unauthorized");
        return;
    }
    match request.path.as_str() {
        "/ws/voice" => crate::voice::serve(socket).await,
        "/ws/stt" => crate::stt::serve(socket).await,
        _ => socket.close(1008, ""),
    }
}
