import asyncio
import os
import math
import struct
import unittest
from contextlib import nullcontext
from unittest.mock import AsyncMock, patch

from jarvis.voice.call_conversation import CallConversation, _BridgeSocket, capture_utterance
from jarvis.voice.call_privacy import CallPrivacy


class FakeBridge:
    def __init__(self):
        self.started = False
        self.closed = False
        self.clears = 0
        self.interrupts = 0

    async def start(self):
        self.started = True

    async def close(self):
        self.closed = True

    def clear_captured_audio(self):
        self.clears += 1

    def interrupt_playback(self):
        self.interrupts += 1


class FakeLLM:
    def __init__(self):
        self.calls = []

    async def stream_text(self, **kwargs):
        self.calls.append(kwargs)
        yield 'I can tell '
        yield 'you about the alert.'


class ConversationTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_cancels_slow_transcription_and_restores_privacy(self):
        bridge = FakeBridge()
        privacy = CallPrivacy()
        entered = asyncio.Event()
        stop = asyncio.Event()
        async def transcribe(_audio):
            entered.set()
            await asyncio.Event().wait()
        async def capture(_bridge, **_kwargs):
            return b'\x01\x00' * 100
        with patch('jarvis.voice.call_conversation.capture_utterance', side_effect=capture):
            conversation = CallConversation(bridge, llm=FakeLLM(), transcriber=transcribe,
                speaker=AsyncMock(), privacy=privacy, clients=(), silence=nullcontext())
            running = asyncio.create_task(conversation.run(alert_source='gmail', stop=stop))
            await asyncio.wait_for(entered.wait(), 1)
            stop.set()
            self.assertEqual(await asyncio.wait_for(running, .5), 'cancelled')
        self.assertTrue(bridge.closed)
        self.assertFalse(privacy.active)

    async def test_caller_speech_interrupts_introduction_then_spoken_stop_ends_call(self):
        bridge = FakeBridge()
        speaking = asyncio.Event()
        cancelled = asyncio.Event()
        async def speaker(text):
            if 'How can I help?' in text:
                speaking.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
        async def capture(_bridge, *, speech_started):
            await speaking.wait()
            speech_started.set()
            return b'\x01\x00' * 100
        with patch('jarvis.voice.call_conversation.capture_utterance', side_effect=capture):
            result = await asyncio.wait_for(CallConversation(bridge, llm=FakeLLM(),
                transcriber=AsyncMock(return_value='Stop'), speaker=speaker,
                privacy=CallPrivacy(), clients=(), silence=nullcontext()).run(alert_source='gmail'), 1)
        self.assertEqual(result, 'user_stopped')
        self.assertTrue(cancelled.is_set())
        self.assertGreater(bridge.interrupts, 0)
        self.assertTrue(bridge.closed)

    async def test_call_uses_the_current_jarvis_voice_and_waits_for_playback(self):
        bridge = FakeBridge()
        bridge.drain = AsyncMock()
        with patch.dict(os.environ, {'FISH_VOICE_ID': 'selected-jarvis-voice',
                                     'FISH_MODEL': 'selected-model',
                                     'FISH_LATENCY': 'selected-latency'}), \
             patch('jarvis.voice.call_conversation.get_secure_key', return_value='test-key'):
            streamer = CallConversation(bridge, llm=FakeLLM())._make_streamer()
        self.assertEqual(streamer.voice_id, 'selected-jarvis-voice')
        self.assertEqual(streamer.model, 'selected-model')
        self.assertEqual(streamer.latency, 'selected-latency')
        await _BridgeSocket(bridge).send_json({'type': 'pcm_end'})
        bridge.drain.assert_awaited_once()

    async def test_private_call_talks_then_honors_spoken_stop(self):
        import jarvis.voice.call_conversation as module
        bridge = FakeBridge()
        llm = FakeLLM()
        spoken = []
        async def speaker(text):
            spoken.append(text)
        transcriber = AsyncMock(side_effect=['What happened?', 'Stop'])
        old = module.capture_utterance
        module.capture_utterance = AsyncMock(side_effect=[b'\x00\x00' * 1000] * 2)
        try:
            result = await CallConversation(bridge, llm=llm, transcriber=transcriber,
                                            speaker=speaker, privacy=CallPrivacy(), clients=(),
                                            silence=nullcontext()).run(
                alert_source='gmail', alert_subject='Urgent meeting')
        finally:
            module.capture_utterance = old
        self.assertEqual(result, 'user_stopped')
        self.assertTrue(bridge.started and bridge.closed)
        self.assertEqual(len(llm.calls), 1)
        self.assertIn('new urgent email', spoken[0])
        self.assertEqual(spoken[1], 'I can tell you about the alert.')
        self.assertEqual(spoken[2], 'Understood. Goodbye, Boss.')

    async def test_vad_waits_for_speech_and_ends_after_silence(self):
        class Audio:
            def __init__(self):
                loud = [int(math.sin(i / 10) * 10000) for i in range(480)]
                self.frames = ([b'\x00\x00' * 480] * 2 +
                               [struct.pack('<480h', *loud)] * 5 +
                               [b'\x00\x00' * 480] * 5)

            async def read_pcm(self):
                await asyncio.sleep(.02)
                return self.frames.pop(0) if self.frames else b'\x00\x00' * 480

        utterance = await capture_utterance(Audio(), wait_seconds=.4,
                                            max_speech_seconds=.6, silence_seconds=.06)
        self.assertIsNotNone(utterance)
        self.assertGreater(len(utterance), 480 * 2 * 5)


if __name__ == '__main__':
    unittest.main()
