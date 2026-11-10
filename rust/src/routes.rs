//! HTTP routes.

use crate::config;
use crate::host::fs;
use crate::http::{Request, Response, content_type_for};
use crate::{auth, VERSION};
use serde_json::json;

pub async fn route(req: Request) -> Response {
    let method = req.method.as_str();
    let path = req.path.as_str();
    match (method, path) {
        ("GET", "/api/health") => Response::ok(json!({ "status": "online", "name": "JARVIS", "version": VERSION })),
        ("POST", "/api/dashboard/session") => {
            let code = auth::create_dashboard_code();
            let port = config::port();
            Response::ok(json!({ "code": code, "url": format!("http://127.0.0.1:{port}/launch/{code}"), "expires_in": 60 }))
        }
        ("GET", p) if p.starts_with("/launch/") => launch(&p["/launch/".len()..]),
        ("GET" | "HEAD", "/") => static_file("index.html"),
        ("GET" | "HEAD", "/pcm-capture.js") => static_file("pcm-capture.js"),
        ("GET" | "HEAD", p) if p.starts_with("/assets/") => static_file(&p[1..]),
        _ => Response::not_found(),
    }
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
