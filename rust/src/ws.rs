//! Server side of RFC 6455 WebSockets on top of a raw host socket.

use crate::host;
use serde_json::Value;
use sha1::{Digest, Sha1};
use std::cell::{Cell, RefCell};

const GUID: &str = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
const MAX_MESSAGE: usize = 16 * 1024 * 1024;

pub enum Message {
    Text(String),
    Binary(Vec<u8>),
}

pub struct WebSocket {
    conn: u32,
    buffer: RefCell<Vec<u8>>,
    closed: Cell<bool>,
    pub protocols: Vec<String>,
    pub close_code: Cell<Option<u16>>,
}

pub fn accept_key(key: &str) -> String {
    let mut hasher = Sha1::new();
    hasher.update(key.trim().as_bytes());
    hasher.update(GUID.as_bytes());
    crate::util::b64(&hasher.finalize())
}

impl WebSocket {
    /// Completes the handshake. `leftover` holds bytes read past the request.
    pub fn accept(conn: u32, key: &str, protocols: Vec<String>, subprotocol: Option<&str>, leftover: Vec<u8>) -> Self {
        let mut response = format!(
            "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {}\r\n",
            accept_key(key)
        );
        if let Some(p) = subprotocol {
            response.push_str(&format!("Sec-WebSocket-Protocol: {p}\r\n"));
        }
        response.push_str("\r\n");
        host::sock_write(conn, response.as_bytes());
        Self { conn, buffer: RefCell::new(leftover), closed: Cell::new(false), protocols, close_code: Cell::new(None) }
    }

    pub fn is_closed(&self) -> bool {
        self.closed.get()
    }

    fn frame(&self, opcode: u8, payload: &[u8]) {
        if self.closed.get() {
            return;
        }
        let mut out = Vec::with_capacity(payload.len() + 10);
        out.push(0x80 | opcode);
        match payload.len() {
            n if n < 126 => out.push(n as u8),
            n if n < 65536 => {
                out.push(126);
                out.extend_from_slice(&(n as u16).to_be_bytes());
            }
            n => {
                out.push(127);
                out.extend_from_slice(&(n as u64).to_be_bytes());
            }
        }
        out.extend_from_slice(payload);
        host::sock_write(self.conn, &out);
    }

    pub fn send_text(&self, text: &str) {
        self.frame(0x1, text.as_bytes());
    }
    pub fn send_json(&self, value: &Value) {
        self.send_text(&value.to_string());
    }
    pub fn send_binary(&self, data: &[u8]) {
        self.frame(0x2, data);
    }
    pub fn close(&self, code: u16, reason: &str) {
        if self.closed.get() {
            return;
        }
        let mut payload = code.to_be_bytes().to_vec();
        payload.extend_from_slice(reason.as_bytes());
        self.frame(0x8, &payload);
        self.closed.set(true);
        host::sock_close(self.conn);
    }

    /// Next complete message, or None once the peer closed the connection.
    pub async fn recv(&self) -> Option<Message> {
        let mut partial: Option<(u8, Vec<u8>)> = None;
        loop {
            if self.closed.get() {
                return None;
            }
            let parsed = parse_frame(&self.buffer.borrow());
            match parsed {
                Err(()) => {
                    self.close(1002, "protocol error");
                    return None;
                }
                Ok(None) => {
                    let Some(chunk) = host::sock_read(self.conn).await else {
                        self.closed.set(true);
                        host::sock_close(self.conn);
                        return None;
                    };
                    let mut buffer = self.buffer.borrow_mut();
                    buffer.extend_from_slice(&chunk);
                    if buffer.len() > MAX_MESSAGE + 16 {
                        drop(buffer);
                        self.close(1009, "message too big");
                        return None;
                    }
                }
                Ok(Some((fin, opcode, payload, used))) => {
                    self.buffer.borrow_mut().drain(..used);
                    match opcode {
                        0x8 => {
                            let code = (payload.len() >= 2).then(|| u16::from_be_bytes([payload[0], payload[1]]));
                            self.close_code.set(code);
                            self.close(code.unwrap_or(1000), "");
                            return None;
                        }
                        0x9 => self.frame(0xA, &payload),
                        0xA => {}
                        0x0 => {
                            let Some((op, mut data)) = partial.take() else {
                                self.close(1002, "unexpected continuation");
                                return None;
                            };
                            data.extend_from_slice(&payload);
                            if data.len() > MAX_MESSAGE {
                                self.close(1009, "message too big");
                                return None;
                            }
                            if fin {
                                return self.finish(op, data);
                            }
                            partial = Some((op, data));
                        }
                        0x1 | 0x2 => {
                            if fin {
                                return self.finish(opcode, payload);
                            }
                            partial = Some((opcode, payload));
                        }
                        _ => {
                            self.close(1002, "unknown opcode");
                            return None;
                        }
                    }
                }
            }
        }
    }

    fn finish(&self, opcode: u8, data: Vec<u8>) -> Option<Message> {
        if opcode == 0x1 {
            match String::from_utf8(data) {
                Ok(text) => Some(Message::Text(text)),
                Err(_) => {
                    self.close(1007, "invalid utf-8");
                    None
                }
            }
        } else {
            Some(Message::Binary(data))
        }
    }
}

/// Parses one client frame: (fin, opcode, unmasked payload, bytes used).
fn parse_frame(buf: &[u8]) -> Result<Option<(bool, u8, Vec<u8>, usize)>, ()> {
    if buf.len() < 2 {
        return Ok(None);
    }
    let fin = buf[0] & 0x80 != 0;
    let opcode = buf[0] & 0x0f;
    let masked = buf[1] & 0x80 != 0;
    if !masked || buf[0] & 0x70 != 0 {
        return Err(()); // clients must mask; no extensions negotiated
    }
    let mut len = (buf[1] & 0x7f) as usize;
    let mut pos = 2;
    if len == 126 {
        if buf.len() < 4 {
            return Ok(None);
        }
        len = u16::from_be_bytes([buf[2], buf[3]]) as usize;
        pos = 4;
    } else if len == 127 {
        if buf.len() < 10 {
            return Ok(None);
        }
        let mut b = [0u8; 8];
        b.copy_from_slice(&buf[2..10]);
        let wide = u64::from_be_bytes(b);
        if wide > MAX_MESSAGE as u64 {
            return Err(());
        }
        len = wide as usize;
        pos = 10;
    }
    if opcode >= 0x8 && (len > 125 || !fin) {
        return Err(());
    }
    if buf.len() < pos + 4 + len {
        return Ok(None);
    }
    let mask = [buf[pos], buf[pos + 1], buf[pos + 2], buf[pos + 3]];
    pos += 4;
    let payload = buf[pos..pos + len].iter().enumerate().map(|(i, b)| b ^ mask[i % 4]).collect();
    Ok(Some((fin, opcode, payload, pos + len)))
}
