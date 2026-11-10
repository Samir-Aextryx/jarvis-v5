"""Bounded overlapping LLM phrase / Fish PCM / playback pipeline."""
import asyncio
import base64
import re
import time
import uuid
from jarvis.integrations.http_clients import http_client
from jarvis.voice.speech_language import is_banned_confirmation


class PhraseBuffer:
    def __init__(self):
        self.text=''
        self.in_action=False
        self.visible=''

    def push(self, delta, final=False):
        if self.in_action:
            return []
        self.text += delta
        phrases=[]
        while self.text:
            bracket=self.text.find('[')
            if bracket>=0 and ']' in self.text[bracket:] and not self.text[bracket:].upper().startswith('[ACTION:'):
                # Ordinary bracketed prose isn't a control tag.
                end=self.text.index(']',bracket)
                self.text=self.text[:bracket]+self.text[bracket+1:end]+self.text[end+1:]
                continue
            if bracket>=0 and self.text[bracket:].upper().startswith('[ACTION:'):
                self.text=self.text[:bracket]
                self.in_action=True
                final=True
                if is_banned_confirmation(self.text):
                    self.text = ''
            # Don't pronounce partial control tags, code blocks or unfinished words.
            safe=self.text if '[' not in self.text else self.text[:self.text.index('[')]
            punctuation=re.search(r'[.!?;](?:\s|$)',safe)
            words=list(re.finditer(r'\S+\s+',safe))
            # Start promptly, then use longer phrases to preserve natural cadence.
            limit=8 if not self.visible else 16
            word_cut=words[limit-1].end() if len(words)>=limit else 0
            choices=[end for end in (punctuation.end() if punctuation else 0,word_cut) if end]
            cut=min(choices) if choices else 0
            if not cut and final:
                cut=len(safe)
            if not cut:
                break
            phrase=self.text[:cut].strip()
            self.text=self.text[cut:]
            phrase=re.sub(r'[`*_#]','',phrase).strip()
            if phrase and not is_banned_confirmation(phrase):
                self.visible += (' ' if self.visible else '')+phrase
                phrases.append(phrase)
        return phrases


class VoiceMetrics:
    def __init__(self, ws):
        self.ws=ws
        self.started=time.perf_counter()
        self.seen=set()

    async def mark(self, stage):
        if stage in self.seen:
            return
        self.seen.add(stage)
        await self.ws.send_json({'type':'latency','stage':stage,'server_ms':round((time.perf_counter()-self.started)*1000,2)})


class StreamingSpeech:
    def __init__(self, ws, *, api_key, voice_id, model, latency='balanced', metrics=None, usage=None, source=None):
        self.ws=ws
        self.api_key=api_key
        self.voice_id=voice_id
        self.model=model
        self.latency=latency
        self.metrics=metrics or VoiceMetrics(ws)
        self.usage=usage
        self.source=source or self._fish
        self.buffer=PhraseBuffer()
        self.jobs=asyncio.Queue(maxsize=4)
        self.gate=asyncio.Semaphore(2)
        self.tasks=set()
        self.id=uuid.uuid4().hex
        self.player=None
        self.sent=False
        self.started_playback = False
        self.ended_playback = False
        self.raw=''

    async def _fish(self, text):
        async with http_client(timeout=15) as client:
            async with client.stream('POST','https://api.fish.audio/v1/tts',
                    headers={'Authorization':'Bearer '+self.api_key,'model':self.model},
                    json={'text':text,'reference_id':self.voice_id,'format':'pcm','sample_rate':44100,
                          'latency':self.latency,'chunk_length':100}) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    yield chunk
        if self.usage:
            self.usage()

    async def feed(self, delta):
        if delta:
            await self.metrics.mark('llm_first_token')
        self.raw += delta
        for phrase in self.buffer.push(delta):
            await self.enqueue(phrase)

    async def enqueue(self, phrase):
        if not phrase or not self.api_key or is_banned_confirmation(phrase):
            return
        if self.player is None:
            self.player=asyncio.create_task(self._play())
        queue=asyncio.Queue(maxsize=16)
        async def generate():
            try:
                async with self.gate:
                    async for chunk in self.source(phrase):
                        for start in range(0,len(chunk),4096):
                            await queue.put(chunk[start:start+4096])
                await queue.put(None)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await queue.put(exc)
        put=asyncio.create_task(self.jobs.put(queue))
        try:
            await asyncio.wait([put,self.player],return_when=asyncio.FIRST_COMPLETED)
            if self.player.done():
                await self.player
            await put
        finally:
            put.cancel()
            await asyncio.gather(put,return_exceptions=True)
        task=asyncio.create_task(generate())
        self.tasks.add(task)

    async def _play(self):
        self.started_playback = True
        await self.ws.send_json({'type':'pcm_start','id':self.id})
        while True:
            queue=await self.jobs.get()
            if queue is None:
                break
            pending=b''
            while True:
                chunk=await queue.get()
                if isinstance(chunk,Exception):
                    raise chunk
                if chunk is None:
                    if pending:
                        raise RuntimeError('Fish returned an incomplete PCM sample.')
                    break
                pending+=chunk
                size=len(pending)//2*2
                if size:
                    block,pending=pending[:size],pending[size:]
                    await self.metrics.mark('first_tts_chunk')
                    await self.ws.send_json({'type':'pcm_chunk','id':self.id,'data':base64.b64encode(block).decode()})
                    self.sent=True
        await self.ws.send_json({'type':'pcm_end','id':self.id})
        self.ended_playback = True

    async def finish(self):
        for phrase in self.buffer.push('',final=True):
            await self.enqueue(phrase)
        if self.player:
            # Avoid waiting on a full queue when playback has already failed.
            put=asyncio.create_task(self.jobs.put(None))
            try:
                await asyncio.wait([put,self.player],return_when=asyncio.FIRST_COMPLETED)
                if self.player.done():
                    await self.player
                await put
                await self.player
            finally:
                put.cancel()
                await asyncio.gather(put,return_exceptions=True)
        return self.sent

    async def close(self):
        pending=[*self.tasks]+([self.player] if self.player else [])
        for task in pending:
            if not task.done():task.cancel()
        await asyncio.gather(*pending,return_exceptions=True)

    async def abort(self):
        """Immediately cancel any in-flight generation and playback, sending pcm_end if needed."""
        await self.close()
        if self.started_playback and not self.ended_playback:
            try:
                await self.ws.send_json({'type': 'pcm_end', 'id': self.id})
                self.ended_playback = True
            except Exception:
                pass
