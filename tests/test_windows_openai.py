import asyncio
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import httpx
from jarvis.integrations.llm_client import LLMClient
import jarvis.server as server
import jarvis.automation.windows_support as windows_support


class OpenAITests(unittest.IsolatedAsyncioTestCase):
    async def test_luna_low_is_sent_for_text_and_streaming(self):
        seen = []
        def respond(request):
            payload = json.loads(request.content)
            seen.append(payload)
            self.assertEqual(payload['model'], 'gpt-6-luna')
            self.assertEqual(payload['reasoning'], {'effort':'low'})
            if payload.get('stream'):
                return httpx.Response(200, text='data: {"type":"response.output_text.delta","delta":"Hello"}\n\ndata: {"type":"response.completed","response":{"usage":{}}}\n\n',
                                      headers={'content-type':'text/event-stream'})
            return httpx.Response(200, json={'output':[{'type':'message','content':[{'type':'output_text','text':'Hello'}]}]})
        with patch.dict(os.environ, {'OPENAI_MODEL':'gpt-6-luna','OPENAI_REASONING_EFFORT':'low'}):
            client = LLMClient('test-key', transport=httpx.MockTransport(respond))
            self.assertEqual((await client.create(messages=[{'role':'user','content':'Hi'}])).content[0].text, 'Hello')
            self.assertEqual(''.join([part async for part in client.stream_text(messages=[{'role':'user','content':'Hi'}])]), 'Hello')
        self.assertEqual(len(seen), 2)

    async def test_text_image_usage_and_configured_model(self):
        def respond(request):
            self.assertEqual(request.url.path, "/v1/responses")
            self.assertEqual(request.headers["authorization"], "Bearer test-key")
            body = json.loads(request.content)
            self.assertEqual(body["model"], "test-model")
            self.assertFalse(body["store"])
            self.assertEqual(body["input"][0]["content"][0]["image_url"], "data:image/png;base64,YQ==")
            return httpx.Response(200, json={"output": [{"type": "message", "content": [{"type": "output_text", "text": "Hallo"}]}], "usage": {"input_tokens": 10, "output_tokens": 2}})
        with patch.dict(os.environ, {"OPENAI_MODEL": "test-model"}):
            client = LLMClient("test-key", transport=httpx.MockTransport(respond))
            result = await client.messages.create(messages=[{"role": "user", "content": [{"type": "image", "source": {"media_type": "image/png", "data": "YQ=="}}]}])
        self.assertEqual(result.content[0].text, "Hallo")
        self.assertEqual(result.usage.input_tokens, 10)

    async def test_error_does_not_expose_key(self):
        client = LLMClient("secret", transport=httpx.MockTransport(lambda r: httpx.Response(401)))
        with self.assertRaisesRegex(RuntimeError, "HTTP 401") as caught:
            await client.messages.create(messages=[{"role": "user", "content": "Hi"}])
        self.assertNotIn("secret", str(caught.exception))

    async def test_auth_and_settings(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://localhost:8340") as client:
            self.assertEqual((await client.get("/api/health")).status_code, 200)
            self.assertEqual((await client.get("/api/settings/status")).status_code, 401)
            client.headers["Authorization"] = "Bearer " + server.JARVIS_AUTH_TOKEN
            status = await client.get("/api/settings/status")
            self.assertEqual(status.status_code, 200)
            self.assertIn("openai", status.json()["env_keys_set"])
            self.assertTrue(status.json()["calendar_accessible"])
            invalid = await client.post("/api/settings/keys", json={"key_name": "OPENAI_API_KEY", "key_value": "x\nJARVIS_AUTH_TOKEN=x"})
            self.assertEqual(invalid.status_code, 400)
            with patch.object(server, "_write_env_key"), patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), patch.object(server, "llm_client", None):
                saved = await client.post("/api/settings/keys", json={"key_name": "OPENAI_API_KEY", "key_value": "test"})
                self.assertEqual(saved.status_code, 200)
                self.assertIsInstance(server.llm_client, LLMClient)

    async def test_mail_status_reports_each_provider_separately(self):
        from jarvis.routers import system as system_router
        status = {'outlook_accessible': True, 'google_mail_accessible': False, 'mail_accessible': True}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://localhost:8340") as client:
            client.headers["Authorization"] = "Bearer " + server.JARVIS_AUTH_TOKEN
            with patch.object(system_router, 'mail_provider_status', new=AsyncMock(return_value=status)):
                response = await client.get('/api/settings/status')
        self.assertEqual(response.status_code, 200)
        self.assertEqual({key: response.json()[key] for key in status}, status)

    async def test_windows_unavailable_integrations_are_honest(self):
        with patch.object(server.local_calendar, "upcoming", return_value=[]):
            self.assertIn("Jarvis calendar is clear", await server._do_calendar_lookup())
        self.assertIn("Tell me whether to read Outlook or Gmail", await server._do_mail_lookup())
        result = await windows_support.open_browser("javascript:alert(1)")
        self.assertFalse(result["success"])
        with patch("jarvis.automation.windows_support.shutil.which", return_value=None):
            result = await windows_support.open_terminal()
            self.assertFalse(result["success"])

    async def test_windows_window_enumeration(self):
        windows = await windows_support.get_active_windows()
        self.assertIsInstance(windows, list)
        for window in windows:
            self.assertIn("title", window)
            self.assertIn("frontmost", window)

    async def test_transcription_requires_auth_and_valid_audio(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://localhost:8340") as client:
            self.assertEqual((await client.post("/api/transcribe", content=b"test")).status_code, 401)
            client.headers["Authorization"] = "Bearer " + server.JARVIS_AUTH_TOKEN
            with patch.object(server, "OPENAI_API_KEY", "test-key"):
                response = await client.post("/api/transcribe", content=b"text", headers={"Content-Type": "text/plain"})
                self.assertEqual(response.status_code, 415)
                response = await client.post("/api/transcribe", content=b"", headers={"Content-Type": "audio/webm"})
                self.assertEqual(response.status_code, 400)

    async def test_phone_call_privacy_blocks_desktop_transcription(self):
        from jarvis.voice.call_privacy import phone_call_privacy
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://localhost:8340") as client:
            client.headers["Authorization"] = "Bearer " + server.JARVIS_AUTH_TOKEN
            self.assertEqual((await client.get('/api/agent/phone-privacy/status')).json(), {'active': False})
            with patch.object(phone_call_privacy, '_session', 'test-call'):
                self.assertEqual((await client.get('/api/agent/phone-privacy/status')).json(), {'active': True})
                response = await client.post('/api/transcribe', content=b'audio',
                                             headers={'Content-Type': 'audio/webm'})
                self.assertEqual(response.status_code, 423)


if __name__ == "__main__":
    unittest.main()
