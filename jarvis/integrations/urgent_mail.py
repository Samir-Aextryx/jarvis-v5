"""Low-cost, read-only urgent mail alerts; mail content is never an instruction."""

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pywintypes
from jarvis.core.runtime_paths import DATA_ROOT
from jarvis.integrations.google_access import google_access
from jarvis.integrations.outlook_com import recent_unread_outlook_headers

log = logging.getLogger("jarvis.urgent_mail")
_URGENT_SUBJECT = re.compile(
    r"(?i)(?:\b(?:urgent|emergency|notfall|dringend|sofort|asap)\b|"
    r"(?:action\s+required|handlungsbedarf|bitte\s+sofort))"
)
_CALL_EXPIRY_SECONDS = 30 * 60
_CALL_RETRY_SECONDS = 5 * 60
_OUTLOOK_POLL_SECONDS = 30
_GMAIL_POLL_SECONDS = 90
_OUTLOOK_FAILURE_RETRY_SECONDS = 120


def is_urgent_header(row: dict) -> bool:
    """Only trusted mailbox flags and a small subject vocabulary trigger alerts."""
    return bool(row.get('unread') and
                (row.get('important') or _URGENT_SUBJECT.search(str(row.get('subject', '')))))


class UrgentMailMonitor:
    def __init__(self, root=DATA_ROOT):
        self.path = Path(root) / 'data' / 'urgent-mail-state.dpapi'
        self.seen: dict[str, list[str]] = {}
        self.alerts = deque()
        self.errors: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._load()

    @staticmethod
    def _fingerprint(source: str, message_id: str) -> str:
        return hashlib.sha256((source + ':' + message_id).encode('utf-8')).hexdigest()

    def _load(self):
        if not self.path.exists():
            return
        try:
            import win32crypt
            raw = win32crypt.CryptUnprotectData(self.path.read_bytes(), None, None, None, 0)[1]
            data = json.loads(raw)
            if data.get('version') not in {1, 2} or not isinstance(data.get('seen'), dict):
                raise ValueError('Unsupported urgent mail state.')
            valid = re.compile(r'[0-9a-f]{64}')
            for source, rows in data['seen'].items():
                if source in {'outlook', 'gmail'} and isinstance(rows, list):
                    self.seen[source] = [row for row in rows[-2000:]
                                         if isinstance(row, str) and valid.fullmatch(row)]
            for alert in data.get('alerts', []):
                if (isinstance(alert, dict) and alert.get('source') in {'gmail', 'outlook'}
                        and all(isinstance(alert.get(key), str) for key in ('subject', 'sender', 'time'))):
                    saved = {key: alert[key][:limit] for key, limit in
                             (('source', 10), ('subject', 200), ('sender', 160), ('time', 50))}
                    if data['version'] == 2 and re.fullmatch(r'[0-9a-f]{64}', str(alert.get('id', ''))):
                        saved['id'] = alert['id']
                        state = alert.get('call_state', 'expired')
                        saved['call_state'] = 'uncertain' if state == 'dialing' else state
                        if saved['call_state'] not in {'pending', 'blocked', 'connected', 'uncertain', 'expired'}:
                            saved['call_state'] = 'uncertain'
                        saved['created_at'] = float(alert.get('created_at', 0) or 0)
                        saved['next_attempt'] = float(alert.get('next_attempt', 0) or 0)
                        saved['attempts'] = min(max(int(alert.get('attempts', 0) or 0), 0), 3)
                    else:
                        # A v1 alert predates the call outbox; do not place a late call.
                        saved['call_state'] = 'expired'
                    self.alerts.append(saved)
            self._trim_alerts()
        except (OSError, ValueError, TypeError, KeyError, pywintypes.error) as exc:
            self.errors['storage'] = type(exc).__name__
            log.warning('Urgent mail state could not be loaded: %s', type(exc).__name__)

    def _save(self):
        import win32crypt
        state = {'version': 2, 'seen': self.seen, 'alerts': list(self.alerts)}
        sealed = win32crypt.CryptProtectData(json.dumps(state).encode('utf-8'),
                                              'Jarvis urgent mail state', None, None, None, 0)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_bytes(sealed)
        os.replace(temporary, self.path)

    def _trim_alerts(self):
        """Keep every open call; bound only historical, resolved alerts."""
        resolved = [alert for alert in self.alerts
                    if alert.get('call_state') in {'connected', 'uncertain', 'expired'}]
        if len(resolved) > 50:
            retain = {id(alert) for alert in resolved[-50:]}
            self.alerts = deque(alert for alert in self.alerts
                                if alert.get('call_state') not in {'connected', 'uncertain', 'expired'}
                                or id(alert) in retain)

    @staticmethod
    async def _emit(notify, payload):
        try:
            await notify(payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning('Urgent mail notification failed: %s', type(exc).__name__)

    async def scan(self, source: str, fetch, notify):
        rows = await fetch()
        if not isinstance(rows, list):
            raise ValueError('Mail provider did not return a list of headers.')
        notifications = []
        async with self._lock:
            prior_seen = self.seen.get(source)
            prior_alerts = deque(self.alerts)
            current = [self._fingerprint(source, str(row['id'])) for row in rows if row.get('id')]
            previous = prior_seen
            previous_set = set(previous or [])
            self.seen[source] = list(dict.fromkeys((previous or []) + current))[-2000:]
            self.errors.pop(source, None)
            if previous is None:
                try:
                    await asyncio.to_thread(self._save)
                    self.errors.pop('storage', None)
                except (OSError, RuntimeError, ValueError, pywintypes.error) as exc:
                    self.seen.pop(source, None)
                    self.errors['storage'] = type(exc).__name__
                return  # First scan is a baseline, never an old-mail alarm.
            fresh = []
            for row in rows:
                if not row.get('id') or not is_urgent_header(row):
                    continue
                fingerprint = self._fingerprint(source, str(row['id']))
                if fingerprint not in previous_set:
                    fresh.append(row)
                    previous_set.add(fingerprint)
            for row in fresh:
                now = time.time()
                alert = {'id': self._fingerprint(source, str(row['id'])),
                         'source': source, 'subject': str(row.get('subject', ''))[:200],
                         'sender': str(row.get('sender', ''))[:160],
                         'time': datetime.now(timezone.utc).isoformat(),
                         'created_at': now, 'next_attempt': now,
                         'attempts': 0, 'call_state': 'pending'}
                self.alerts.append(alert)
                notifications.append(self._public_alert(alert))
            self._trim_alerts()
            if self.seen[source] != previous or fresh:
                try:
                    await asyncio.to_thread(self._save)
                    self.errors.pop('storage', None)
                except (OSError, RuntimeError, ValueError, pywintypes.error) as exc:
                    self.seen[source] = prior_seen
                    self.alerts = prior_alerts
                    self.errors['storage'] = type(exc).__name__
                    log.warning('Urgent mail state could not be saved: %s', type(exc).__name__)
                    return
        for alert in notifications:
            await self._emit(notify, {'type': 'urgent_mail', **alert})

    @staticmethod
    def _public_alert(alert):
        return {key: alert[key] for key in ('source', 'subject', 'sender', 'time', 'call_state')
                if key in alert}

    async def process_calls(self, call_handler, notify):
        """Persist a claim before dialing; never retry an uncertain call."""
        if call_handler is None:
            return
        now = time.time()
        async with self._lock:
            if any(alert.get('call_state') == 'dialing' for alert in self.alerts):
                return
            expired = False
            for alert in self.alerts:
                if (alert.get('call_state') in {'pending', 'blocked'}
                        and now - float(alert.get('created_at', 0)) > _CALL_EXPIRY_SECONDS):
                    alert['call_state'] = 'expired'
                    expired = True
            candidate = next((alert for alert in reversed(self.alerts)
                              if alert.get('call_state') in {'pending', 'blocked'}
                              and float(alert.get('next_attempt', 0)) <= now), None)
            if candidate is None:
                if expired:
                    await asyncio.to_thread(self._save)
                return
            candidate['call_state'] = 'dialing'
            candidate['attempts'] = int(candidate.get('attempts', 0)) + 1
            try:
                await asyncio.to_thread(self._save)
            except (OSError, RuntimeError, ValueError, pywintypes.error) as exc:
                candidate['call_state'] = 'blocked'
                self.errors['storage'] = type(exc).__name__
                return  # A call without a durable claim could be duplicated.
            selected = dict(candidate)
        try:
            result = await call_handler(selected)
        except asyncio.CancelledError:
            # The on-disk 'dialing' state becomes uncertain on restart.
            raise
        except Exception as exc:
            log.warning('Urgent call outcome is uncertain: %s', type(exc).__name__)
            result = {'state': 'uncertain'}
        if not isinstance(result, dict):
            result = {'state': 'uncertain'}
        async with self._lock:
            if result.get('state') == 'connected' and result.get('spoken') is True:
                candidate['call_state'] = 'connected'
            elif result.get('state') == 'not_ready':
                candidate['call_state'] = 'blocked'
                candidate['next_attempt'] = time.time() + _CALL_RETRY_SECONDS
            else:
                candidate['call_state'] = 'uncertain'
            self._trim_alerts()
            try:
                await asyncio.to_thread(self._save)
                self.errors.pop('storage', None)
            except (OSError, RuntimeError, ValueError, pywintypes.error) as exc:
                self.errors['storage'] = type(exc).__name__
                return
            status = self._public_alert(candidate)
        await self._emit(notify, {'type': 'urgent_call_status', **status})

    async def run(self, notify, call_handler=None, *, clock=None, sleep=None):
        clock = clock or time.monotonic
        sleep = sleep or asyncio.sleep
        next_gmail_scan = 0.0
        next_outlook_scan = 0.0
        while True:
            providers = []
            now = clock()
            if now >= next_outlook_scan:
                providers.append(('outlook', recent_unread_outlook_headers))
                next_outlook_scan = now + _OUTLOOK_POLL_SECONDS
            if now >= next_gmail_scan:
                next_gmail_scan = now + _GMAIL_POLL_SECONDS
                try:
                    status = await asyncio.to_thread(google_access.status)
                    if status.get('connected') and 'gmail' in status.get('services', []):
                        providers.append(('gmail', google_access.recent_unread_headers))
                except (OSError, ValueError, RuntimeError) as exc:
                    self.errors['gmail'] = str(exc)[:120]
            for source, fetch in providers:
                old_error = self.errors.get(source)
                try:
                    await self.scan(source, fetch, notify)
                    if old_error and source not in self.errors:
                        await self._emit(notify, {'type': 'urgent_mail_source_status',
                                                  'source': source, 'available': True})
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    error = type(exc).__name__
                    self.errors[source] = error
                    if source == 'outlook':
                        next_outlook_scan = clock() + _OUTLOOK_FAILURE_RETRY_SECONDS
                    log.warning('Urgent mail scan failed for %s: %s', source, error,
                                exc_info=True)
                    if old_error != error:
                        await self._emit(notify, {'type': 'urgent_mail_source_status',
                                                  'source': source, 'available': False,
                                                  'error': error})
            try:
                await self.process_calls(call_handler, notify)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning('Urgent call dispatch failed: %s', type(exc).__name__)
            await sleep(_OUTLOOK_POLL_SECONDS)

    def status(self) -> dict:
        return {'alerts': [self._public_alert(alert) for alert in self.alerts],
                'errors': dict(self.errors),
                'sources_initialized': sorted(self.seen),
                'state_encrypted': self.path.exists() and 'storage' not in self.errors}


urgent_mail_monitor = UrgentMailMonitor()
