//! Live speech recognition relay (filled in below).
use crate::ws::WebSocket;
use std::rc::Rc;
pub async fn serve(socket: Rc<WebSocket>) { socket.close(1011, ""); }
