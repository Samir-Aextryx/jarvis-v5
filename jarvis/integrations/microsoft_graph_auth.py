"""Client-credentials authentication shared by the read-only Planner client.

Only the fixed Microsoft identity token endpoint receives POST requests.
Access tokens and secrets stay in memory and are never included in errors.
"""

from __future__ import annotations

import math
import re
import threading
import time
from typing import Any, Callable
from uuid import UUID

import httpx


class PlannerError(RuntimeError):
    """Safe service error; does not contain request bodies, tokens or secrets."""

    def __init__(self, message: str, *, status_code: int | None = None,
                 code: str | None = None, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.retry_after = retry_after


class PlannerConfigurationError(PlannerError):
    """Missing or invalid local configuration."""


class PlannerAuthenticationError(PlannerError):
    """Expired secret, invalid credentials or rejected access token."""


class PlannerPermissionError(PlannerError):
    """Missing application permission or administrator consent."""


class PlannerRateLimitError(PlannerError):
    """Retry budget exhausted or Microsoft requested a longer delay."""


class PlannerNotFoundError(PlannerError):
    """Plan or task does not exist or is not visible to the application."""


class PlannerProtocolError(PlannerError):
    """Malformed response or unsafe pagination URL."""


def json_object(response: httpx.Response) -> dict[str, Any]:
    """Decode an object without echoing potentially sensitive response data."""
    try:
        data = response.json()
    except (ValueError, UnicodeError):
        raise PlannerProtocolError('Microsoft returned invalid JSON.') from None
    if not isinstance(data, dict):
        raise PlannerProtocolError('Microsoft returned a JSON value instead of an object.')
    return data


def safe_error_code(response: httpx.Response) -> str | None:
    """Extract an error identifier only; never expose OAuth error descriptions."""
    try:
        error = response.json().get('error')
        code = error.get('code') if isinstance(error, dict) else error
    except (ValueError, AttributeError, UnicodeError):
        return None
    return code if isinstance(code, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', code) else None


def validate_uuid(value: str, field: str) -> str:
    """Accept a concrete tenant/client UUID, never a placeholder or URL path."""
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise PlannerConfigurationError(f'{field} must be a valid UUID.') from None


class ClientCredentialsTokenProvider:
    """Thread-safe in-memory token cache with early expiry and one refresh at a time."""

    def __init__(self, client: httpx.Client, *, tenant_id: str, client_id: str,
                 client_secret: str, clock: Callable[[], float] = time.monotonic) -> None:
        self._client = client
        self._tenant_id = validate_uuid(tenant_id, 'TENANT_ID')
        self._client_id = validate_uuid(client_id, 'CLIENT_ID')
        if not isinstance(client_secret, str) or not client_secret.strip() or client_secret.startswith('<'):
            raise PlannerConfigurationError('CLIENT_SECRET is missing or is still a placeholder.')
        self._client_secret = client_secret
        self._clock = clock
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at = 0.0

    def invalidate(self, rejected_token: str) -> None:
        """Evict a rejected token without discarding a newer concurrent refresh."""
        with self._lock:
            if self._token == rejected_token:
                self._token = None
                self._expires_at = 0.0

    def get_token(self) -> str:
        """Reuse a valid token; request a new one using the .default scope otherwise."""
        with self._lock:
            if self._token is not None and self._clock() < self._expires_at:
                return self._token
            started = self._clock()
            try:
                response = self._client.post(
                    f'https://login.microsoftonline.com/{self._tenant_id}/oauth2/v2.0/token',
                    data={'grant_type': 'client_credentials',
                          'client_id': self._client_id, 'client_secret': self._client_secret,
                          'scope': 'https://graph.microsoft.com/.default'},
                    headers={'Accept': 'application/json'})
            except httpx.RequestError:
                raise PlannerAuthenticationError('Microsoft token service could not be reached.') from None
            if response.status_code != 200:
                raise PlannerAuthenticationError(
                    'Microsoft token request failed. Check tenant, client ID, secret expiry and admin consent.',
                    status_code=response.status_code, code=safe_error_code(response))
            data = json_object(response)
            token = data.get('access_token')
            try:
                lifetime = float(data['expires_in'])
            except (KeyError, TypeError, ValueError, OverflowError):
                raise PlannerProtocolError('Token response has no valid expiry.') from None
            if (not isinstance(token, str) or not token.strip()
                    or any(char.isspace() for char in token)
                    or str(data.get('token_type', '')).lower() != 'bearer'
                    or not math.isfinite(lifetime) or lifetime <= 0):
                raise PlannerProtocolError('Token response has invalid token metadata.')
            # Use monotonic time and subtract network time plus a small safety
            # margin. Short-lived tokens retain 90% of their reported lifetime.
            expires_at = started + lifetime - min(60.0, lifetime * .1)
            if expires_at <= self._clock():
                raise PlannerAuthenticationError('Microsoft returned an already expired access token.')
            self._token = token
            self._expires_at = expires_at
            return token

    def clear(self) -> None:
        """Forget cached credentials when the owning client closes."""
        with self._lock:
            self._token = None
            self._expires_at = 0.0
            self._client_secret = ''
