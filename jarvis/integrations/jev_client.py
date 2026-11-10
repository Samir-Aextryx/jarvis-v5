"""TypeSafe's official typed-decision endpoint; no generative API emulation."""
import asyncio
import math
import os
import time
import httpx
from jarvis.integrations.credentials_vault import get_secure_key, get_vault, _service_name
from jarvis.integrations.http_clients import http_client

ENDPOINT = 'https://api.typesafe.ai/v1/systemone'
KEY_NAME = 'JEV_API_KEY'
MISSING_KEY_CODE = 'JEV_KEY_MISSING'
MISSING_KEY_MESSAGE = 'Add your Jev API key in Settings > AI Settings > Jev.'


def get_jev_key():
    vault = get_vault()
    if vault:
        try:
            return vault.get_password(_service_name(), KEY_NAME) or ''
        except Exception:
            return ''
    return ''


class JevError(RuntimeError):
    def __init__(self, message, code="JEV_CONNECTION_ERROR"):
        super().__init__(message)
        self.code = code


def save_jev_key(value):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 33 for c in value):
        raise ValueError('Enter a valid Jev API key without whitespace.')
    vault = get_vault()
    if vault is None:
        raise JevError('Windows Credential Manager is unavailable. The key was not saved.')
    try:
        if value:
            vault.set_password(_service_name(), KEY_NAME, value)
        elif vault.get_password(_service_name(), KEY_NAME):
            vault.delete_password(_service_name(), KEY_NAME)
    except Exception:
        raise JevError('Credential Manager could not save this change.') from None
    os.environ.pop(KEY_NAME, None)


def choice(answer, options, threshold=.8):
    if not isinstance(answer, dict):
        return None
    confidence = answer.get('confidence')
    if answer.get('type') != 'choice' or answer.get('choice') not in options:
        return None
    if type(confidence) not in (float, int) or not math.isfinite(confidence) or not threshold <= confidence <= 1:
        return None
    return answer['choice']


class JevClient:
    def __init__(self, key=None, transport=None):
        self.key = key
        self.transport = transport
        self.connection = 'Not Connected'
        self.last_error = ''
        self.cooldown = 0

    def configured(self):
        return bool(self.key if self.key is not None else get_jev_key())

    async def decide(self, state, questions, *, test=False):
        key = self.key if self.key is not None else get_jev_key()
        if not key:
            raise JevError(MISSING_KEY_MESSAGE, MISSING_KEY_CODE)
        if not test and time.monotonic() < self.cooldown:
            raise JevError(self.last_error or 'Jev is temporarily unavailable.')
        try:
            # Persisted connection, fixed HTTPS host, redirects never followed.
            async with asyncio.timeout(4.5):
                async with http_client(timeout=2, transport=self.transport) as client:
                    for attempt in range(2):
                        response = await client.post(ENDPOINT, headers={'Authorization': 'Bearer ' + key},
                            json={'model': 'jev-latest', 'state': state, 'questions': questions}, follow_redirects=False)
                        if response.status_code in {429, 502, 503, 529} and attempt == 0:
                            await asyncio.sleep(.25)
                            continue
                        if response.status_code != 200:
                            raise JevError(f'Jev connection error (HTTP {response.status_code}). Check your key and TypeSafe access.')
                        data = response.json()
                        answers = data.get('answers')
                        if not isinstance(answers, dict) or any(q not in answers for q in questions):
                            raise JevError('Jev returned an incomplete decision.')
                        self.connection, self.last_error, self.cooldown = 'Connected', '', 0
                        return answers
        except (httpx.HTTPError, TimeoutError, ValueError, AttributeError):
            error = 'Could not connect to Jev or read its decision. Please try again.'
        except JevError as exc:
            error = str(exc)
        self.connection, self.last_error = 'Connection Error', error
        self.cooldown = time.monotonic() + 15
        raise JevError(error) from None

    async def test(self):
        result = await self.decide({'connection_test': True}, {'test': {'type': 'noul',
            'instructions': 'Is connection_test true?'}}, test=True)
        if not isinstance(result['test'], dict) or result['test'].get('type') != 'noul':
            self.connection = 'Connection Error'
            raise JevError('Jev returned an invalid test response.')
        return {'status': self.connection}


jev = JevClient()
