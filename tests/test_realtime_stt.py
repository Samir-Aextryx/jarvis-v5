import asyncio
import json
import unittest
from unittest.mock import patch
from jarvis.voice.realtime_stt import serve_stt, transcription_session


class Browser:
    def __init__(self, token='valid', delay='low'):
        self.headers={'sec-websocket-protocol':f'jarvis, jarvis.auth.{token}, jarvis.stt.delay.{delay}'}; self.incoming=asyncio.Queue(); self.sent=[]; self.closed=None
    async def accept(self, **kwargs): self.accepted=True
    async def close(self, code=1000, reason=None): self.closed=code
    async def receive(self): return await self.incoming.get()
    async def send_json(self,message): self.sent.append(message)


class Upstream:
    def __init__(self): self.events=asyncio.Queue(); self.sent=[]; self.number=0
    async def __aenter__(self): return self
    async def __aexit__(self,*args): pass
    async def recv(self): return json.dumps(await self.events.get())
    def __aiter__(self): return self
    async def __anext__(self): return await self.recv()
    async def send(self,raw):
        message=json.loads(raw); self.sent.append(message)
        if message['type']=='session.update': await self.events.put({'type':'session.updated'})
        if message['type']=='input_audio_buffer.commit':
            self.number+=1; item=str(self.number)
            await self.events.put({'type':'input_audio_buffer.committed','item_id':item})
            await self.events.put({'type':'conversation.item.input_audio_transcription.delta','item_id':item,'delta':'Open'})
            final={'type':'conversation.item.input_audio_transcription.completed','item_id':item,'transcript':'Open Chrome'}
            await self.events.put(final); await self.events.put(final)


class RelayTests(unittest.IsolatedAsyncioTestCase):
    def test_transcription_is_bilingual_has_domain_terms_and_uses_configured_accuracy(self):
        with patch.dict('os.environ', {'JARVIS_STT_KEYWORDS':'Häner, Branko, invalid<term>', 'USER_NAME':'Samir'}):
            session=transcription_session('high')['session']['audio']['input']['transcription']
        self.assertEqual(session['model'],'gpt-live-transcribe')
        self.assertEqual(session['languages'],['en','de'])
        self.assertEqual(session['delay'],'high')
        self.assertIn('Branko',session['keywords'])
        self.assertIn('Samir',session['keywords'])
        self.assertNotIn('invalid<term>',session['keywords'])
        self.assertIn('meetings',session['prompt'])
        self.assertIn('Outlook',session['prompt'])
        self.assertIn('recipient names',session['prompt'])
        self.assertIn('mach Outlook auf',session['prompt'])
        self.assertIn('schreib/verfasse eine E-Mail',session['prompt'])
        self.assertIn('E-Mail',session['keywords'])

    def test_unrecognized_accuracy_setting_falls_back_to_fast(self):
        with patch.dict('os.environ', {'JARVIS_STT_DELAY':'low'}):
            self.assertEqual(transcription_session('broken')['session']['audio']['input']['transcription']['delay'],'low')

    def test_fastest_latency_mode_is_used_when_no_preference_exists(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(transcription_session()['session']['audio']['input']['transcription']['delay'],'minimal')

    def test_default_accuracy_is_fast_unless_user_configures_a_different_level(self):
        with patch.dict('os.environ', {'JARVIS_STT_DELAY':'low'}):
            self.assertEqual(transcription_session()['session']['audio']['input']['transcription']['delay'],'low')
        with patch.dict('os.environ', {'JARVIS_STT_DELAY':'medium'}):
            self.assertEqual(transcription_session()['session']['audio']['input']['transcription']['delay'],'medium')

    def test_custom_names_keep_priority_over_common_keywords(self):
        names = [f'Contact {number}' for number in range(12)]
        with patch.dict('os.environ', {'USER_NAME':'Samir', 'JARVIS_STT_KEYWORDS':','.join(names)}):
            keywords = transcription_session()['session']['audio']['input']['transcription']['keywords']
        self.assertLessEqual(len(keywords),24)
        self.assertTrue(all(name in keywords for name in names))
        self.assertIn('Outlook', keywords)

    async def test_unauthorized_never_connects(self):
        browser=Browser('wrong')
        with patch('jarvis.voice.realtime_stt.connect') as connect:
            await serve_stt(browser,'valid','secret')
            connect.assert_not_called()
        self.assertEqual(browser.closed,4001)

    async def test_ordered_final_dedup_and_frame_forwarding(self):
        browser=Browser(); upstream=Upstream()
        with patch('jarvis.voice.realtime_stt.connect',return_value=upstream):
            task=asyncio.create_task(serve_stt(browser,'valid','secret'))
            try:
                for turn in ['first','second']:
                    await browser.incoming.put({'type':'websocket.receive','text':json.dumps({'type':'start','id':turn})})
                    await browser.incoming.put({'type':'websocket.receive','bytes':b'\x01\x00'*2400})
                    await browser.incoming.put({'type':'websocket.receive','text':json.dumps({'type':'commit','id':turn})})
                async with asyncio.timeout(1):
                    while len([m for m in browser.sent if m['type']=='final'])<2: await asyncio.sleep(.001)
                await browser.incoming.put({'type':'websocket.disconnect'})
                await asyncio.wait_for(task,1)
                self.assertEqual([m['id'] for m in browser.sent if m['type']=='final'],['first','second'])
                self.assertEqual(sum(m['type']=='input_audio_buffer.append' for m in upstream.sent),2)
                self.assertTrue(any(m['type']=='partial' for m in browser.sent))
                session = next(m for m in upstream.sent if m['type']=='session.update')
                self.assertEqual(session['session']['audio']['input']['transcription']['delay'],'low')
                self.assertNotIn('secret',json.dumps(browser.sent))
            finally:
                task.cancel(); await asyncio.gather(task,return_exceptions=True)
