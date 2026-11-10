import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, os.getcwd())

from jarvis.voice.speech_language import english_speech, is_banned_confirmation
from jarvis.voice.streaming_voice import PhraseBuffer, StreamingSpeech
from jarvis.automation.autonomous_tasks import AutonomousTasks
import jarvis.server as server


class TestAudioSuppression(unittest.IsolatedAsyncioTestCase):
    async def test_english_speech_empty_text_guard(self):
        self.assertEqual(await english_speech("", "key"), "")
        self.assertEqual(await english_speech("   ", "key"), "")
        self.assertEqual(await english_speech(None, "key"), "")

    def test_banned_confirmation_phrases(self):
        self.assertTrue(is_banned_confirmation("On it, sir."))
        self.assertTrue(is_banned_confirmation("on it"))
        self.assertTrue(is_banned_confirmation("Building it now, sir."))
        self.assertTrue(is_banned_confirmation("I am working on your task"))
        self.assertTrue(is_banned_confirmation("Working on your task."))
        self.assertTrue(is_banned_confirmation("Right away, sir."))
        self.assertTrue(is_banned_confirmation("Understood, sir."))
        self.assertTrue(is_banned_confirmation("Checking your inbox now, sir."))
        self.assertTrue(is_banned_confirmation(""))
        self.assertFalse(is_banned_confirmation("Here is the weather in Berlin today."))

    async def test_synthesize_speech_suppression(self):
        self.assertIsNone(await server.synthesize_speech(""))
        self.assertIsNone(await server.synthesize_speech("   "))
        self.assertIsNone(await server.synthesize_speech("On it, sir."))
        self.assertIsNone(await server.synthesize_speech("I am working on your task"))

    async def test_stream_speech_suppression(self):
        mock_ws = AsyncMock()
        self.assertFalse(await server.stream_speech(mock_ws, ""))
        self.assertFalse(await server.stream_speech(mock_ws, "On it, sir."))
        self.assertFalse(await server.stream_speech(mock_ws, "I am working on your task"))
        mock_ws.send_json.assert_not_called()

    async def test_autonomous_tasks_start_no_unbound_local(self):
        runner = AutonomousTasks()
        res = runner.start("Take care of updating the documentation")
        self.assertEqual(res, "")
        if runner.task and not runner.task.done():
            runner.task.cancel()

    def test_phrase_buffer_suppresses_banned_confirmations(self):
        buf = PhraseBuffer()
        self.assertEqual(buf.push("On it, sir. "), [])
        self.assertEqual(buf.push("I am working on your task. "), [])
        self.assertEqual(buf.push("Building it now, sir. "), [])
        self.assertEqual(buf.push("Understood, sir. "), [])

    def test_phrase_buffer_suppresses_pre_action_confirmation(self):
        buf = PhraseBuffer()
        phrases = buf.push("I am working on your task. [ACTION:BUILD:app]", final=True)
        self.assertEqual(phrases, [])

    def test_phrase_buffer_allows_legitimate_speech(self):
        buf = PhraseBuffer()
        phrases = buf.push("Zurich is sunny today. ", final=True)
        self.assertEqual(phrases, ["Zurich is sunny today."])

    async def test_streaming_speech_suppresses_banned_feed(self):
        class Sink:
            def __init__(self):
                self.messages = []
            async def send_json(self, msg):
                self.messages.append(msg)

        sink = Sink()
        async def dummy_source(text):
            yield b"\x01\x00"

        pipeline = StreamingSpeech(sink, api_key="test", voice_id="", model="", source=dummy_source)
        try:
            await pipeline.feed("On it, sir. ")
            sent = await pipeline.finish()
            self.assertFalse(sent)
            self.assertFalse(any(m["type"] == "pcm_chunk" for m in sink.messages))
        finally:
            await pipeline.close()

    async def test_streaming_speech_abort_cancels_playback(self):
        class Sink:
            def __init__(self):
                self.messages = []
            async def send_json(self, msg):
                self.messages.append(msg)

        sink = Sink()
        async def dummy_source(text):
            yield b"\x01\x00"

        pipeline = StreamingSpeech(sink, api_key="test", voice_id="", model="", source=dummy_source)
        await pipeline.feed("Here is some speech. ")
        await asyncio.sleep(0.01)
        await pipeline.abort()
        has_start = any(m["type"] == "pcm_start" for m in sink.messages)
        if has_start:
            self.assertTrue(any(m["type"] == "pcm_end" for m in sink.messages))


if __name__ == "__main__":
    unittest.main()
