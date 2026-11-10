"""A rejected OpenAI key must be announced instead of leaving Jarvis silently deaf."""
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

import jarvis.server as server
from jarvis.integrations.llm_providers import PROVIDERS
from jarvis.server import openai_key_rejected as probe_openai_key  # conftest replaces the module attribute


def connection(reply):
    calls = []

    @asynccontextmanager
    async def connect(**kwargs):
        def handle(request):
            calls.append(request)
            return reply(request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            yield client
    return connect, calls


class OpenAIKeyProbeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        server._openai_key_verdict.clear()
        self.addCleanup(server._openai_key_verdict.clear)

    async def test_only_an_explicit_401_counts_and_is_remembered_per_key(self):
        rejected, calls = connection(lambda request: httpx.Response(401))
        with patch.object(server, 'http_client', rejected), patch.object(server, 'OPENAI_API_KEY', 'sk-old'):
            self.assertTrue(await probe_openai_key())
            self.assertTrue(await probe_openai_key())
        self.assertEqual(len(calls), 1)
        self.assertEqual(str(calls[0].url), 'https://api.openai.com/v1/models')
        self.assertEqual(calls[0].headers['authorization'], 'Bearer sk-old')
        accepted, calls = connection(lambda request: httpx.Response(200, json={'data': []}))
        with patch.object(server, 'http_client', accepted), patch.object(server, 'OPENAI_API_KEY', 'sk-new'):
            self.assertFalse(await probe_openai_key())
        self.assertEqual(len(calls), 1)

    async def test_offline_restricted_or_missing_key_is_not_reported_as_rejected(self):
        def offline(request):
            raise httpx.ConnectError('offline')
        for reply in (offline, lambda request: httpx.Response(403), lambda request: httpx.Response(500)):
            server._openai_key_verdict.clear()
            connect, _ = connection(reply)
            with patch.object(server, 'http_client', connect), patch.object(server, 'OPENAI_API_KEY', 'sk-test'):
                self.assertFalse(await probe_openai_key())
        connect, calls = connection(lambda request: httpx.Response(401))
        with patch.object(server, 'http_client', connect), patch.object(server, 'OPENAI_API_KEY', ''):
            self.assertFalse(await probe_openai_key())
        self.assertEqual(calls, [])


def _first_spoken_line(rejected, audio, provider='openai'):
    with patch('jarvis.integrations.urgent_mail.urgent_mail_monitor.run', new=AsyncMock()),          patch.object(server, 'provider_config', return_value=PROVIDERS[provider]), \
         patch.object(server, 'openai_key_rejected', new=AsyncMock(return_value=rejected)), \
         patch.object(server, '_last_greeting_time', 0), \
         patch.object(server, 'synthesize_speech', new=AsyncMock(return_value=audio)) as speech:
        with TestClient(server.app) as client:
            with client.websocket_connect('/ws/voice', subprotocols=['jarvis', 'jarvis.auth.' + server.JARVIS_AUTH_TOKEN]) as ws:
                for _ in range(6):
                    message = ws.receive_json()
                    if message.get('type') in {'text', 'audio'}:
                        return message, speech
    raise AssertionError('Jarvis said nothing after connecting')


def test_rejected_key_is_announced_instead_of_the_greeting():
    message, speech = _first_spoken_line(rejected=True, audio=b'mp3')
    assert message['type'] == 'audio' and message['text'] == server.OPENAI_KEY_REJECTED_NOTICE
    speech.assert_awaited_once_with(server.OPENAI_KEY_REJECTED_NOTICE)


def test_rejected_key_is_still_shown_when_speech_is_unavailable():
    message, _ = _first_spoken_line(rejected=True, audio=None)
    assert message == {'type': 'text', 'text': server.OPENAI_KEY_REJECTED_NOTICE}


def test_accepted_key_keeps_the_normal_greeting():
    message, _ = _first_spoken_line(rejected=False, audio=b'mp3')
    assert message['type'] == 'audio' and message['text'].startswith('Good ')


def test_other_provider_only_reports_that_listening_needs_the_openai_key():
    message, speech = _first_spoken_line(rejected=True, audio=b'mp3', provider='ollama')
    assert message['text'] == server.OPENAI_STT_KEY_REJECTED_NOTICE
    assert 'answer' not in message['text']
    speech.assert_awaited_once_with(server.OPENAI_STT_KEY_REJECTED_NOTICE)
