import json
import hashlib
import time
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from jarvis.integrations.google_access import GoogleAccess


class Vault:
    def __init__(self): self.data = {}
    def get_password(self, service, name): return self.data.get((service, name))
    def set_password(self, service, name, value): self.data[service, name] = value


CONFIG = {"installed": {"client_id": "test123.apps.googleusercontent.com", "client_secret": "test-only", "auth_uri": "https://attacker.invalid", "token_uri": "https://attacker.invalid"}}


class GoogleTests(unittest.TestCase):
    def setUp(self): self.google = GoogleAccess("unit-test", Vault())

    def test_api_key_stays_private_and_can_be_removed(self):
        key = 'AIza' + 'x' * 35
        result = self.google.save_api_key(key)
        self.assertTrue(result['api_key_set'])
        self.assertNotIn(key, json.dumps(self.google.status()))
        with self.assertRaises(ValueError): self.google.save_api_key('not-a-google-key')
        self.google.save_api_key('')
        self.assertFalse(self.google.status()['api_key_set'])
        with patch('jarvis.integrations.google_access.requests.get') as network:
            with self.assertRaises(ValueError): self.google.public_youtube()
            network.assert_not_called()

    def test_reject_api_key_and_unknown_services(self):
        for config, services in [({"api_key": "key"}, ["gmail"]), (CONFIG, ["arbitrary"]), (CONFIG, [])]:
            with self.assertRaises(ValueError): self.google.configure(config, services)

    def test_import_uses_trusted_endpoints_without_leaking_secret(self):
        status = self.google.configure(CONFIG, ["gmail", "calendar"])
        self.assertTrue(status["configured"])
        self.assertFalse(status["connected"])
        self.assertNotIn("test-only", json.dumps(status))
        stored = self.google._load("client")["installed"]
        self.assertEqual(stored["token_uri"], "https://oauth2.googleapis.com/token")
        self.assertNotIn("attacker", json.dumps(stored))

    def test_read_requires_connection_before_network(self):
        with patch("jarvis.integrations.google_access.httpx.Client") as client:
            with self.assertRaises(ValueError): self.google.read("gmail")
            client.assert_not_called()

    def test_service_scopes_and_reconfiguration_clear_saved_tokens(self):
        self.google.configure(CONFIG, ["gmail"])
        self.google._save("tokens", {"token": "test-token"})
        with self.assertRaises(ValueError): self.google._token("drive")
        self.google.configure(CONFIG, ["calendar"])
        self.assertFalse(self.google.status()["connected"])

    def test_explicit_voice_routes(self):
        for phrase in ["Read my Gmail", "Lies meine Gmail Nachrichten"]:
            self.assertEqual(self.google.parse(phrase), ("read", "gmail"))
        self.assertEqual(self.google.parse("Zeige meinen Google Kalender"), ("read", "calendar"))
        self.assertEqual(self.google.parse("Open Google Keep"), ("open", "google keep"))
        self.assertIsNone(self.google.parse("Send all my Gmail to someone"))

    def test_endpoints_require_auth_and_reject_api_key(self):
        import jarvis.server as server
        from fastapi.testclient import TestClient
        with patch.object(server, "google_access", self.google), TestClient(server.app) as client:
            self.assertEqual(client.get('/api/google/status').status_code, 401)
            headers = {"Authorization": "Bearer " + server.JARVIS_AUTH_TOKEN}
            self.assertEqual(client.post('/api/google/config', headers=headers, json={"config": {"api_key": "key"}, "services": ["gmail"]}).status_code, 400)
            result = client.post('/api/google/config', headers=headers, json={"config": CONFIG, "services": ["gmail"]})
            self.assertEqual(result.status_code, 200)
            self.assertNotIn("test-only", result.text)


class GoogleContactCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_cache_is_opt_in_ttl_limited_and_scoped_to_token(self):
        google = GoogleAccess('contact-cache-test', Vault())
        person = {'names':[{'displayName':'Taylor Morgan'}],
                  'emailAddresses':[{'value':'taylor@example.com'}]}
        calls = []

        class Response:
            status_code = 200
            def __init__(self, params): self.params = params
            def json(self): return {'results':[{'person':person}]} if self.params['query'] else {'results':[]}

        class Client:
            async def get(self, url, *, headers, params):
                calls.append((headers['Authorization'], params['query']))
                return Response(params)

        @asynccontextmanager
        async def client_context(**_kwargs):
            yield Client()

        token = ['account-a', 'account-a', 'account-a', 'account-b', 'account-b']
        with patch.object(google, '_token', side_effect=token), \
             patch('jarvis.integrations.google_access.http_client', new=client_context):
            await google.search_contacts('Taylor Morgan', use_cache=True)
            await google.search_contacts('Taylor Morgan', use_cache=True)
            # Sending and other searches remain fresh even after a draft lookup.
            await google.search_contacts('Taylor Morgan')
            await google.search_contacts('Taylor Morgan', use_cache=True)

            self.assertEqual([query for _, query in calls], ['', 'Taylor Morgan', '', 'Taylor Morgan', '', 'Taylor Morgan'])
            self.assertEqual([account for account, _ in calls][-2:], ['Bearer account-b'] * 2)

            cache_key = (hashlib.sha256(b'account-b').digest(), 'taylor morgan')
            google._contact_cache[cache_key] = (time.monotonic() - 1, [person])
            await google.search_contacts('Taylor Morgan', use_cache=True)
            self.assertEqual(len(calls), 8)

    async def test_reconfigure_and_disconnect_clear_cached_contacts(self):
        google = GoogleAccess('contact-cache-clear-test', Vault())
        google._contact_cache[(b'test', 'name')] = (time.monotonic() + 30, [])
        google.configure(CONFIG, ['contacts'])
        self.assertEqual(google._contact_cache, {})
        google._contact_cache[(b'test', 'name')] = (time.monotonic() + 30, [])
        google.disconnect()
        self.assertEqual(google._contact_cache, {})
