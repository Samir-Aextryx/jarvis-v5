/**
 * WebSocket client for JARVIS server communication.
 */

export type MessageHandler = (msg: Record<string, unknown>) => void;
export type ConnectionState = "connected" | "disconnected" | "auth-error";

export interface JarvisSocket {
  /** Returns false when the socket is not open and the message was dropped. */
  send(data: Record<string, unknown>): boolean;
  onMessage(handler: MessageHandler): void;
  onState(handler: (state: ConnectionState) => void): void;
  close(): void;
  isConnected(): boolean;
  reconnect(): void;
}

export function createSocket(
  urlOrFactory: string | (() => string),
  onState?: (state: ConnectionState) => void,
): JarvisSocket {
  let ws: WebSocket | null = null;
  let handlers: MessageHandler[] = [];
  let stateHandlers: Array<(state: ConnectionState) => void> = [];
  let reconnectDelay = 1000;
  let closed = false;
  let connected = false;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  function emitState(state: ConnectionState) {
    onState?.(state);
    for (const handler of stateHandlers) handler(state);
  }

  function getUrl(): string {
    return typeof urlOrFactory === "function" ? urlOrFactory() : urlOrFactory;
  }

  function authToken(): string {
    try {
      return (localStorage.getItem("jarvis_auth_token") || "").trim();
    } catch {
      return "";
    }
  }

  function connect() {
    if (closed) return;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }

    const targetUrl = getUrl();
    const token = authToken();
    if (!token) {
      console.warn("[ws] No auth token available; deferring WebSocket connection");
      connected = false;
      emitState("auth-error");
      return;
    }

    try {
      ws = new WebSocket(targetUrl, ["jarvis", "jarvis.auth." + token]);
    } catch (e) {
      console.error("[ws] Failed to initialize WebSocket:", e);
      return;
    }

    ws.onopen = () => {
      connected = true;
      reconnectDelay = 1000;
      emitState("connected");
      console.log("[ws] connected");
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        for (const h of handlers) h(msg);
      } catch {
        console.warn("[ws] bad message", event.data);
      }
    };

    ws.onclose = (event) => {
      connected = false;
      if (closed) return;

      // Stop the reconnect loop on authentication rejection (4001 Unauthorized,
      // 1008 Policy Violation). The server accepts the handshake before closing,
      // so these codes reach the browser instead of a generic 1006.
      if (event.code === 4001 || event.code === 1008) {
        console.warn(`[ws] Authentication failed (code ${event.code}); stopping reconnect loop.`);
        emitState("auth-error");
        return;
      }

      // Also don't reconnect if the token disappeared.
      if (!authToken()) {
        console.warn("[ws] Token missing on close; deferring reconnect.");
        emitState("auth-error");
        return;
      }

      emitState("disconnected");
      console.log(`[ws] reconnecting in ${reconnectDelay}ms`);
      reconnectTimer = setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 30000);
    };

    ws.onerror = () => {
      // onclose follows and owns reconnect/backoff. Closing here aborts the
      // handshake early and would turn every network error into code 1006.
      console.warn("[ws] connection error");
    };
  }

  connect();

  return {
    send(data) {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(data));
        return true;
      }
      return false;
    },
    onMessage(handler) {
      handlers.push(handler);
    },
    onState(handler) {
      stateHandlers.push(handler);
    },
    close() {
      closed = true;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      ws?.close();
    },
    isConnected() {
      return connected;
    },
    reconnect() {
      closed = false;
      connect();
    },
  };
}
