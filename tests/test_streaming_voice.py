import asyncio
import base64
import json
import unittest
import httpx
from jarvis.integrations.llm_client import LLMClient
from jarvis.voice.streaming_voice import PhraseBuffer, StreamingSpeech
from jarvis.voice.voice_context import relevant_context, recent_turns


class Sink:
    def __init__(self): self.messages=[]; self.audio=asyncio.Event()
    async def send_json(self, message):
        self.messages.append(message)
        if message['type']=='pcm_chunk':self.audio.set()


class StreamTests(unittest.IsolatedAsyncioTestCase):
    def test_phrase_buffer_never_speaks_control_tags(self):
        buffer=PhraseBuffer()
        phrases=[]
        for delta in ['Here is the answer. ','[ACT','ION:OPEN_APP:Chrome]']:
            phrases.extend(buffer.push(delta))
        phrases.extend(buffer.push('',final=True))
        self.assertEqual(phrases,['Here is the answer.'])
        buffer=PhraseBuffer()
        self.assertEqual(buffer.push('Use [this] example.',final=True),['Use this example.'])

    def test_phrases_flush_before_complete_response(self):
        buffer=PhraseBuffer()
        chunks=buffer.push('one two three four five six seven eight nine ten eleven twelve thirteen ')
        self.assertEqual(len(chunks),1)
        self.assertEqual(len(chunks[0].split()),8)
        self.assertEqual(buffer.push('',final=True),['nine ten eleven twelve thirteen'])

    def test_long_delta_still_starts_after_eight_words(self):
        buffer=PhraseBuffer()
        text='one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty twentyone twentytwo twentythree twentyfour twentyfive.'
        chunks=buffer.push(text,final=True)
        self.assertEqual([len(chunk.split()) for chunk in chunks],[8,16,1])
        self.assertEqual(' '.join(chunks),text)

    def test_dynamic_time_follows_all_static_action_instructions(self):
        import jarvis.server as server
        prompt=server.JARVIS_SYSTEM_PROMPT
        self.assertGreater(prompt.index('{current_time}'),prompt.index('ACTION SYSTEM:'))
        self.assertIn('{weather_info}',prompt)
        self.assertIn('[ACTION:REMEMBER]',prompt)

    async def test_audio_flows_before_second_phrase_finishes_and_is_ordered(self):
        sink=Sink(); second_started=asyncio.Event(); release=asyncio.Event()
        async def source(text):
            if text=='First.':
                await second_started.wait()
                yield b'\x01\x00'
            else:
                second_started.set()
                await release.wait()
                yield b'\x02\x00'
        pipeline=StreamingSpeech(sink,api_key='test',voice_id='',model='',source=source)
        try:
            await pipeline.feed('First. Second. ')
            await asyncio.wait_for(sink.audio.wait(),1)
            self.assertFalse(release.is_set())
            release.set()
            self.assertTrue(await pipeline.finish())
            pcm=b''.join(base64.b64decode(m['data']) for m in sink.messages if m['type']=='pcm_chunk')
            self.assertEqual(pcm,b'\x01\x00\x02\x00')
            self.assertEqual(sum(m['type']=='pcm_start' for m in sink.messages),1)
            self.assertEqual(sum(m['type']=='pcm_end' for m in sink.messages),1)
        finally:await pipeline.close()

    async def test_barge_in_cancels_prefetch_and_no_late_audio(self):
        sink=Sink(); started=asyncio.Event(); cancelled=asyncio.Event()
        async def source(text):
            try:
                started.set()
                yield b'\x01\x00'
                await asyncio.sleep(30)
            finally:cancelled.set()
        pipeline=StreamingSpeech(sink,api_key='test',voice_id='',model='',source=source)
        await pipeline.feed('First. ')
        await started.wait()
        await pipeline.close()
        count=len(sink.messages)
        await asyncio.sleep(.01)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(len(sink.messages),count)

    async def test_failed_tts_does_not_deadlock_bounded_queues(self):
        async def broken(text):
            raise RuntimeError('Fish unavailable')
            yield b''
        pipeline=StreamingSpeech(Sink(),api_key='test',voice_id='',model='',source=broken)
        try:
            with self.assertRaises(RuntimeError):
                async with asyncio.timeout(1):
                    for _ in range(10):await pipeline.feed('A phrase. ')
                    await pipeline.finish()
        finally:await pipeline.close()

    async def test_sse_yields_without_waiting_for_completion(self):
        released=asyncio.Event()
        class SSE(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'data: {"type":"response.output_text.delta","delta":"Hello"}\n\n'
                await released.wait()
                yield b'data: {"type":"response.completed","response":{"usage":{"input_tokens":2,"output_tokens":1}}}\n\n'
        client=LLMClient('test',transport=httpx.MockTransport(lambda r:httpx.Response(200,stream=SSE())))
        usage=[]
        stream=client.stream_text(messages=[{'role':'user','content':'Hi'}],on_usage=usage.append)
        self.assertEqual(await asyncio.wait_for(anext(stream),1),'Hello')
        self.assertFalse(released.is_set())
        released.set()
        self.assertEqual([delta async for delta in stream],[])
        self.assertEqual(usage[0].usage.output_tokens,1)

    def test_context_is_relevant_and_bounded_without_deleting_history(self):
        memory='Favourite food: pizza\nProject Jarvis uses Python\nTravel: Italy'
        self.assertEqual(relevant_context(memory,'Improve the Jarvis project'),'Project Jarvis uses Python')
        history=[{'role':'user','content':str(i)} for i in range(20)]
        selected=recent_turns(history,'Hello')
        self.assertEqual(len(selected),5)
        self.assertEqual(len(history),20)
