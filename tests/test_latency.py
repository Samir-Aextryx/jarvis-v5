import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace
import httpx
import jarvis.server as server
import jarvis.voice.speech_language as speech_language
from jarvis.integrations.http_clients import http_client, close_http_clients


class LatencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await close_http_clients()

    async def test_connection_reuse_and_close(self):
        async with http_client(15) as first:
            async with http_client(15) as second:
                self.assertIs(first, second)
        self.assertFalse(first.is_closed)
        await close_http_clients()
        self.assertTrue(first.is_closed)

    async def test_english_output_skips_translation_but_unknown_text_does_not(self):
        speech_language._cache.clear()
        speech_language.remember_english('Your next meeting starts at ten.')
        with patch.object(speech_language.LLMClient, 'create', new=AsyncMock(return_value=SimpleNamespace(content=[SimpleNamespace(text='Your next meeting starts at eleven.')])) ) as translate:
            self.assertEqual(await speech_language.english_speech('Your next meeting starts at ten.', 'test'), 'Your next meeting starts at ten.')
            translate.assert_not_called()
            await speech_language.english_speech('Dein nächster Termin beginnt um elf.', 'test')
            translate.assert_awaited_once()

    async def test_app_status_speech_skips_remote_translation(self):
        speech_language._cache.clear()
        phrases = ['Opening Google Chrome.', 'Focused Microsoft Outlook.',
                   'Already running, but Windows did not allow me to focus Paint.']
        with patch.object(speech_language.LLMClient, 'create', new=AsyncMock()) as translate:
            for phrase in phrases:
                self.assertEqual(await speech_language.english_speech(phrase, 'test'), phrase)
            translate.assert_not_awaited()

    async def test_plain_english_is_spoken_without_a_model_but_other_text_is_translated(self):
        speech_language._cache.clear()
        english = ['Good evening, sir.', 'Shutting down, sir.',
                   'Which app do you mean: Outlook, Outlook (classic)?',
                   'Your prompt is ready in a new Claude chat. Review it and press Enter to send it.',
                   server.OPENAI_KEY_REJECTED_NOTICE]
        other = ['Eine Datei wurde gespeichert.', 'Rechner und Editor sind offen', 'Die Datei ist leer',
                 'Saved a draft. Subject: Treffen mit Anna', 'Bildschirmfoto gespeichert', 'C’est prêt']
        translated = SimpleNamespace(content=[SimpleNamespace(text='Translated for speech.')])
        with patch.object(speech_language.LLMClient, 'create', new=AsyncMock(return_value=translated)) as translate:
            for phrase in english:
                self.assertEqual(await speech_language.english_speech(phrase, 'test'), phrase)
            translate.assert_not_awaited()
            for phrase in other:
                self.assertEqual(await speech_language.english_speech(phrase, 'test'), 'Translated for speech.', phrase)
            self.assertEqual(translate.await_count, len(other))
        speech_language._cache.clear()

    async def test_pcm_stream_frames_and_completion(self):
        import base64
        class Chunks(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'\x00'
                yield b'\x01\x02\x03\x04\x05'
                self_test.assertTrue(any(m['type']=='pcm_chunk' for m in socket.messages), 'Forward audio before waiting for the next network chunk')
        class Socket:
            def __init__(self): self.messages=[]
            async def send_json(self, message): self.messages.append(message)
        @asynccontextmanager
        async def connection(**kwargs):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Chunks()))) as client:
                yield client
        self_test=self
        socket=Socket()
        with patch.object(server, 'http_client', connection), patch.object(server, 'english_speech', new=AsyncMock(return_value='PCM unit test')), patch.object(server, 'FISH_API_KEY', 'pcm-test'), patch.object(server, '_append_usage_entry'):
            self.assertTrue(await server.stream_speech(socket,'test'))
        self.assertEqual(socket.messages[0]['type'],'pcm_start')
        self.assertEqual(socket.messages[-1]['type'],'pcm_end')
        audio=b''.join(base64.b64decode(m['data']) for m in socket.messages if m['type']=='pcm_chunk')
        self.assertEqual(audio,b'\x00\x01\x02\x03\x04\x05')

    async def test_audio_cache_reuses_audio_but_not_across_voice_or_key_changes(self):
        server._speech_audio_cache.clear()
        server._speech_audio_cache_size = 0

        calls = []
        def reply(request):
            calls.append(request)
            return httpx.Response(200, content=b'fake-mp3')
        @asynccontextmanager
        async def connection(**kwargs):
            async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
                yield client
        with patch.object(server, 'http_client', connection), patch.object(server, 'english_speech', new=AsyncMock(side_effect=lambda text,key: text)), patch.object(server, 'FISH_API_KEY', 'test-key'), patch.object(server, '_append_usage_entry'):
            self.assertEqual(await server.synthesize_speech('Opening Chrome.'), b'fake-mp3')
            await server.synthesize_speech('Opening Chrome.')
            self.assertEqual(len(calls), 1)
            with patch.object(server, 'FISH_VOICE_ID', 'different-voice'):
                await server.synthesize_speech('Opening Chrome.')
            with patch.object(server, 'FISH_API_KEY', 'different-key'):
                await server.synthesize_speech('Opening Chrome.')
            self.assertEqual(len(calls), 3)
        server._speech_audio_cache.clear()
        server._speech_audio_cache_size = 0

    def test_voice_latency_records_direct_automation_duration_without_command_text(self):
        import tempfile
        from collections import deque
        from pathlib import Path
        from jarvis.voice import voice_metrics
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(voice_metrics, 'DATA_ROOT', Path(directory)), \
                patch.object(voice_metrics, 'recent', deque(maxlen=100)):
            voice_metrics.record({'timings': {'speech_end': 10, 'automation_start': 11.5,
                                               'automation_complete': 19.25, 'response_complete': 22},
                                  'command': 'private command'})
            row = voice_metrics.recent[-1]
            self.assertEqual(row['automation_ms'], 7.75)
            self.assertEqual(row['milliseconds']['automation_complete'], 9.25)
            self.assertNotIn('command', row)
