"""Local authentication; credentials never travel in request URLs."""
import secrets
import threading
import time
from jarvis.integrations.credentials_vault import get_vault, _service_name

# One-time codes let the browser dashboard bootstrap its token without putting
# the long-lived token into Chrome's command line (readable by other processes).
_DASHBOARD_CODES: dict[str, float] = {}
_DASHBOARD_LOCK = threading.Lock()
DASHBOARD_CODE_TTL = 60

# The browser dashboard gets its own credential instead of the long-lived
# vault token. It expires on its own and is useless on other origins.
_SESSION_TOKENS: dict[str, float] = {}
_SESSION_LOCK = threading.Lock()
SESSION_TTL = 12 * 60 * 60
MAX_SESSIONS = 32


def create_session_token(ttl: float = SESSION_TTL) -> str:
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _SESSION_LOCK:
        for key, expiry in list(_SESSION_TOKENS.items()):
            if expiry <= now:
                _SESSION_TOKENS.pop(key, None)
        while len(_SESSION_TOKENS) >= MAX_SESSIONS:
            _SESSION_TOKENS.pop(next(iter(_SESSION_TOKENS)), None)
        _SESSION_TOKENS[token] = now + ttl
    return token


def verify_auth_token(supplied, expected) -> bool:
    """Accept the long-lived app token or an unexpired dashboard session."""
    if token_matches(supplied, expected):
        return True
    if not isinstance(supplied, str) or not supplied:
        return False
    now = time.monotonic()
    with _SESSION_LOCK:
        expiry = _SESSION_TOKENS.get(supplied)
        if expiry is not None and expiry <= now:
            _SESSION_TOKENS.pop(supplied, None)
            expiry = None
    return expiry is not None and expiry > now


def create_dashboard_code(ttl: float = DASHBOARD_CODE_TTL) -> str:
    code = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _DASHBOARD_LOCK:
        for key, expiry in list(_DASHBOARD_CODES.items()):
            if expiry <= now:
                _DASHBOARD_CODES.pop(key, None)
        _DASHBOARD_CODES[code] = now + ttl
    return code


def redeem_dashboard_code(code: str) -> bool:
    """Consume a dashboard code; each code is valid once and only briefly."""
    if not isinstance(code, str) or not code:
        return False
    now = time.monotonic()
    with _DASHBOARD_LOCK:
        expiry = _DASHBOARD_CODES.pop(code, None)
    return expiry is not None and expiry > now

def auth_token():
    vault = get_vault()
    if vault is None:
        raise RuntimeError("Windows Credential Manager is unavailable.")
    token = vault.get_password(_service_name(), "JARVIS_AUTH_TOKEN")
    if not token:
        token = secrets.token_urlsafe(32)
        vault.set_password(_service_name(), "JARVIS_AUTH_TOKEN", token)
    return token

def token_matches(supplied, expected):
    """Constant-time token check that also tolerates non-ASCII header values."""
    if not isinstance(supplied, str) or not isinstance(expected, str) or not supplied or not expected:
        return False
    return secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))

async def authenticate_websocket(ws, token):
    protocols = [part.strip() for part in ws.headers.get("sec-websocket-protocol", "").split(",")]
    supplied = next((part[12:] for part in protocols if part.startswith("jarvis.auth.")), "")
    if "jarvis" not in protocols or not verify_auth_token(supplied, token):
        # Accept first so the browser receives the 4001 close code. Rejecting the
        # handshake instead surfaces only a generic 1006 and hides the cause.
        await ws.accept(subprotocol="jarvis" if "jarvis" in protocols else None)
        await ws.close(code=4001, reason="Unauthorized")
        return False
    await ws.accept(subprotocol="jarvis")
    return True
