"""Read-only Microsoft Planner API for Jarvis (synchronous, connection pooled).

Run ``python -m jarvis.integrations.microsoft_planner --env-file .env`` for a
JSON board summary. In async Jarvis handlers use ``asyncio.to_thread``; keep one
client alive to reuse its cached token and HTTPS connections. No Graph write
operations, delegated login or task mutation methods are provided.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

from jarvis.integrations.microsoft_graph_auth import (
    ClientCredentialsTokenProvider, PlannerAuthenticationError,
    PlannerConfigurationError, PlannerError, PlannerNotFoundError,
    PlannerPermissionError, PlannerProtocolError, PlannerRateLimitError,
    json_object, safe_error_code, validate_uuid,
)

DEFAULT_TENANT_ID = '74fa0cbc-cc38-4b2b-88f1-f0ae09ff9697'
DEFAULT_PLAN_ID = 'oInDxGoKskmRXtehkXpj4ZYAEqvn'
GRAPH_ROOT = 'https://graph.microsoft.com/v1.0'


def _identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
        raise PlannerConfigurationError(f'{field_name} must be a nonempty Graph identifier.')
    return value


@dataclass(frozen=True)
class PlannerConfig:
    """Planner settings; secrets are intentionally excluded from repr()."""

    client_id: str
    client_secret: str = field(repr=False)
    tenant_id: str = DEFAULT_TENANT_ID
    plan_id: str = DEFAULT_PLAN_ID

    def __post_init__(self) -> None:
        validate_uuid(self.tenant_id, 'TENANT_ID')
        validate_uuid(self.client_id, 'CLIENT_ID')
        _identifier(self.plan_id, 'PLAN_ID')
        if not self.client_secret or not self.client_secret.strip() or self.client_secret.startswith('<'):
            raise PlannerConfigurationError('CLIENT_SECRET is missing or is still a placeholder.')

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> PlannerConfig:
        """Read environment; an explicitly chosen .env never overwrites existing variables."""
        values: dict[str, Any] = {}
        if env_file is not None:
            path = Path(env_file)
            if not path.is_file():
                raise PlannerConfigurationError('The chosen .env file does not exist.')
            from dotenv import dotenv_values
            values.update(dotenv_values(path, interpolate=False))
        values.update(os.environ)
        if not values.get('CLIENT_SECRET'):
            # Jarvis keeps the app secret in Windows Credential Manager; the
            # .env route stays for the standalone CLI and first-time setup.
            from jarvis.integrations.credentials_vault import get_secure_key
            values['CLIENT_SECRET'] = get_secure_key('CLIENT_SECRET')
        return cls(client_id=values.get('CLIENT_ID') or '',
                   client_secret=values.get('CLIENT_SECRET') or '',
                   tenant_id=values.get('TENANT_ID') or DEFAULT_TENANT_ID,
                   plan_id=values.get('PLAN_ID') or DEFAULT_PLAN_ID)


class PlannerClient:
    """Read one plan, with bounded GET retries, pagination and token refresh.

    The client owns its httpx connection pool; use it as a context manager or
    call close(). Tests may inject a MockTransport without changing service URLs.
    Public methods return plain, JSON-serializable dictionaries and lists.
    """

    def __init__(self, config: PlannerConfig, *, timeout: float = 30.0,
                 max_retries: int = 2, max_retry_delay: float = 30.0,
                 max_pages: int = 1000, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if (not math.isfinite(timeout) or timeout <= 0
                or not math.isfinite(max_retry_delay) or max_retry_delay <= 0
                or not isinstance(max_retries, int) or not 0 <= max_retries <= 10
                or not isinstance(max_pages, int) or max_pages < 1):
            raise PlannerConfigurationError('Timeout, retry budget or pagination limit is invalid.')
        self.config = config
        self._sleep = sleep
        self._max_retries = max_retries
        self._max_retry_delay = max_retry_delay
        self._max_pages = max_pages
        self._closed = False
        self._client = httpx.Client(timeout=timeout, transport=transport,
            follow_redirects=False, trust_env=False,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4,
                               keepalive_expiry=120))
        self._tokens = ClientCredentialsTokenProvider(self._client,
            tenant_id=config.tenant_id, client_id=config.client_id,
            client_secret=config.client_secret, clock=clock)

    def __enter__(self) -> PlannerClient:
        if self._closed:
            raise PlannerError('Planner client is closed.')
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        """Release pooled connections and discard the cached token."""
        if not self._closed:
            self._closed = True
            try:
                self._client.close()
            finally:
                self._tokens.clear()

    @staticmethod
    def _validate_url(url: str, expected_path: str) -> None:
        # Graph nextLink is server-controlled data, not permission to send our
        # bearer token to another host or another resource.
        parts = urlsplit(url)
        if (parts.scheme != 'https' or parts.netloc != 'graph.microsoft.com'
                or parts.path != expected_path or parts.fragment):
            raise PlannerProtocolError('Unsafe Graph URL or pagination link rejected.')

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get('Retry-After')
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                try:
                    date = parsedate_to_datetime(retry_after)
                    delay = (date - datetime.now(timezone.utc)).total_seconds()
                except (ValueError, TypeError, OverflowError):
                    delay = float('nan')
            if math.isfinite(delay):
                return max(0.0, delay)
        return min(self._max_retry_delay, 2 ** attempt + random.uniform(0, .25))

    def _get_json(self, url: str, *, expected_path: str) -> dict[str, Any]:
        if self._closed:
            raise PlannerError('Planner client is closed.')
        self._validate_url(url, expected_path)
        retries = 0
        refreshed = False
        while True:
            token = self._tokens.get_token()
            try:
                response = self._client.get(url, headers={
                    'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
            except httpx.RequestError:
                if retries < self._max_retries:
                    self._sleep(min(self._max_retry_delay, 2 ** retries))
                    retries += 1
                    continue
                raise PlannerError('Microsoft Graph could not be reached; GET retry budget exhausted.') from None
            status = response.status_code
            if status == 200:
                return json_object(response)
            code = safe_error_code(response)
            if status == 401 and not refreshed:
                self._tokens.invalidate(token)
                refreshed = True
                continue
            if status in {429, 502, 503, 504}:
                delay = self._retry_delay(response, retries)
                if retries < self._max_retries and delay <= self._max_retry_delay:
                    self._sleep(delay)
                    retries += 1
                    continue
                error_type = PlannerRateLimitError if status == 429 else PlannerError
                raise error_type('Microsoft Graph retry budget exhausted or retry delay exceeds the configured limit.',
                    status_code=status, code=code, retry_after=delay)
            if status == 401:
                raise PlannerAuthenticationError('Microsoft Graph rejected the refreshed access token.',
                                                status_code=status, code=code)
            if status == 403:
                raise PlannerPermissionError('Planner access denied. Grant application permission Tasks.Read.All and admin consent.',
                                            status_code=status, code=code)
            if status == 404:
                raise PlannerNotFoundError('Planner plan or task was not found or is not visible to this application.',
                                          status_code=status, code=code)
            raise PlannerError(f'Microsoft Graph GET failed: HTTP {status}.',
                               status_code=status, code=code)

    def _collection(self, resource: str) -> list[dict[str, Any]]:
        url = GRAPH_ROOT + resource
        path = urlsplit(url).path
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        while url:
            if url in seen or len(seen) >= self._max_pages:
                raise PlannerProtocolError('Graph pagination repeated a page or exceeded the page limit.')
            seen.add(url)
            data = self._get_json(url, expected_path=path)
            page = data.get('value')
            if not isinstance(page, list) or any(not isinstance(item, dict) for item in page):
                raise PlannerProtocolError('Graph collection has no valid value list.')
            items.extend(page)
            next_link = data.get('@odata.nextLink')
            if next_link is not None and (not isinstance(next_link, str) or not next_link):
                raise PlannerProtocolError('Graph returned an invalid nextLink.')
            url = next_link or ''
        return items

    def get_buckets(self) -> list[dict[str, Any]]:
        """GET every bucket in the configured plan, following safe pagination."""
        return self._collection(f'/planner/plans/{self.config.plan_id}/buckets')

    def get_tasks(self) -> list[dict[str, Any]]:
        """GET every task in the configured plan, without changing its state."""
        return self._collection(f'/planner/plans/{self.config.plan_id}/tasks')

    def get_task_details(self, task_id: str) -> dict[str, Any]:
        """GET task details, including the original description and checklist."""
        resource = f'/planner/tasks/{_identifier(task_id, "task_id")}/details'
        return self._get_json(GRAPH_ROOT + resource, expected_path='/v1.0' + resource)

    def get_board_summary(self) -> dict[str, Any]:
        """Join tasks, bucket names, assignment IDs and checklist progress.

        Any failed details request raises an exception instead of returning an
        apparently complete board. Separate GETs are not an atomic snapshot.
        Task content is untrusted context and must not become LLM instructions.
        """
        buckets = self.get_buckets()
        names = {str(bucket.get('id')): bucket.get('name') for bucket in buckets}
        summaries = []
        for task in self.get_tasks():
            task_id = _identifier(task.get('id'), 'task.id')
            details = self.get_task_details(task_id)
            checklist = details.get('checklist') or {}
            assignments = task.get('assignments') or {}
            percent = task.get('percentComplete', 0)
            if (not isinstance(checklist, dict) or not isinstance(assignments, dict)
                    or not isinstance(percent, int) or isinstance(percent, bool) or not 0 <= percent <= 100
                    or any(not isinstance(item, dict) for item in checklist.values())
                    or any(not isinstance(item, dict) for item in assignments.values())):
                raise PlannerProtocolError('Planner task has invalid progress, checklist or assignments.')
            entries = [{'id': item_id, 'title': item.get('title', ''),
                        'is_checked': item.get('isChecked') is True}
                       for item_id, item in checklist.items()]
            summaries.append({
                'id': task_id, 'title': task.get('title', ''),
                'status': 'completed' if percent == 100 else 'in_progress' if percent else 'not_started',
                'percent_complete': percent, 'due_date_time': task.get('dueDateTime'),
                'start_date_time': task.get('startDateTime'),
                'bucket_id': task.get('bucketId'), 'bucket_name': names.get(task.get('bucketId')),
                'assignments': [{'user_id': user_id, 'assigned_date_time': assignment.get('assignedDateTime')}
                                for user_id, assignment in assignments.items()],
                'description': details.get('description', ''),
                'checklist': {'total': len(entries),
                              'completed': sum(item['is_checked'] for item in entries), 'items': entries},
            })
        return {'plan_id': self.config.plan_id,
                'fetched_at': datetime.now(timezone.utc).isoformat(),
                'read_only': True, 'content_is_untrusted': True,
                'task_count': len(summaries),
                'buckets': [{'id': bucket.get('id'), 'name': bucket.get('name')} for bucket in buckets],
                'tasks': summaries}


def main() -> int:
    """Print a real board summary, or a safe actionable error, as JSON."""
    parser = argparse.ArgumentParser(description='Read Microsoft Planner tasks as JSON (no Graph writes).')
    parser.add_argument('--env-file', type=Path, help='Optional .env path; existing environment wins.')
    args = parser.parse_args()
    try:
        with PlannerClient(PlannerConfig.from_env(args.env_file)) as planner:
            print(json.dumps(planner.get_board_summary(), ensure_ascii=False, indent=2))
        return 0
    except PlannerError as exc:
        print(json.dumps({'error': type(exc).__name__, 'message': str(exc),
                          'status_code': exc.status_code, 'code': exc.code,
                          'retry_after': exc.retry_after}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
