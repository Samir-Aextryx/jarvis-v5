//! Stops desktop microphone capture before a private phone conversation.

use crate::host::Res;
use crate::speech::with_timeout;
use crate::ws::WebSocket;
use futures::channel::oneshot;
use serde_json::json;
use std::cell::RefCell;
use std::rc::Rc;

thread_local! {
    static SESSION: RefCell<Option<String>> = const { RefCell::new(None) };
    static ACKS: RefCell<Vec<(*const WebSocket, Option<oneshot::Sender<()>>)>> = const { RefCell::new(Vec::new()) };
}

pub fn active() -> bool {
    SESSION.with(|s| s.borrow().is_some())
}
pub fn session() -> Option<String> {
    SESSION.with(|s| s.borrow().clone())
}

/// Requires every connected Jarvis window to release its microphone.
pub async fn begin(clients: &[Rc<WebSocket>], timeout_ms: f64) -> Res<String> {
    if active() {
        return Err("Another phone call already owns microphone privacy.".into());
    }
    let session = crate::util::uuid_hex();
    SESSION.with(|s| *s.borrow_mut() = Some(session.clone()));
    let mut waits = Vec::new();
    ACKS.with(|a| {
        let mut a = a.borrow_mut();
        a.clear();
        for c in clients {
            let (tx, rx) = oneshot::channel();
            a.push((Rc::as_ptr(c), Some(tx)));
            waits.push(rx);
        }
    });
    for c in clients {
        c.send_json(&json!({ "type": "phone_call_privacy", "active": true, "session": session }));
    }
    let acknowledged = with_timeout(timeout_ms, futures::future::join_all(waits)).await;
    let ok = matches!(acknowledged, Ok(ref r) if r.iter().all(Result::is_ok));
    if !ok || self::session().as_deref() != Some(session.as_str()) {
        end(&session, clients);
        return Err("Phone privacy session ended before dialing.".into());
    }
    Ok(session)
}

pub fn acknowledge(client: &Rc<WebSocket>, session: &str) -> bool {
    if self::session().as_deref() != Some(session) {
        return false;
    }
    ACKS.with(|a| {
        let mut a = a.borrow_mut();
        match a.iter_mut().find(|(p, _)| *p == Rc::as_ptr(client)) {
            Some((_, tx)) => {
                if let Some(tx) = tx.take() {
                    let _ = tx.send(());
                }
                true
            }
            None => false,
        }
    })
}

pub fn end(session: &str, clients: &[Rc<WebSocket>]) -> bool {
    if self::session().as_deref() != Some(session) {
        return false;
    }
    SESSION.with(|s| *s.borrow_mut() = None);
    ACKS.with(|a| a.borrow_mut().clear());
    for c in clients {
        c.send_json(&json!({ "type": "phone_call_privacy", "active": false, "session": session }));
    }
    true
}
