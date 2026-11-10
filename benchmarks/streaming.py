import asyncio,base64,json,os,time,wave,audioop
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path.home()/'Documents/Jarvis v5/config/.env',override=True)
import jarvis.server as server
from jarvis.integrations.llm_client import LLMClient
from jarvis.voice.streaming_voice import StreamingSpeech,VoiceMetrics
from jarvis.voice.realtime_stt import transcription_session
from websockets.asyncio.client import connect
from jarvis.integrations.http_clients import close_http_clients
class Sink:
    def __init__(self):self.first=None;self.events={}
    async def send_json(self,m):
        if m['type']=='pcm_chunk' and self.first is None:self.first=time.perf_counter()
        if m['type']=='latency':self.events.setdefault(m['stage'],time.perf_counter())
async def run():
    with wave.open('benchmarks/input.wav','rb') as f:pcm=audioop.ratecv(f.readframes(f.getnframes()),2,1,f.getframerate(),24000,None)[0]
    frames=[pcm[i:i+960] for i in range(0,len(pcm),960)]
    last=max(i for i,f in enumerate(frames) if audioop.rms(f,2)>393)
    frames=frames[:last+1]+[b'\x00'*960]*9
    async with connect('wss://api.openai.com/v1/realtime?intent=transcription',additional_headers={'Authorization':'Bearer '+server.OPENAI_API_KEY},open_timeout=12) as ws:
        await ws.send(json.dumps(transcription_session()))
        while True:
            event=json.loads(await ws.recv())
            if event.get('type')=='error':raise RuntimeError(event['error']['message'])
            if event.get('type')=='session.updated':break
        speech_end=None;partial=None;final=None
        async def upload():
            nonlocal speech_end
            start=time.perf_counter()
            for i,frame in enumerate(frames):
                await ws.send(json.dumps({'type':'input_audio_buffer.append','audio':base64.b64encode(frame).decode()}))
                await asyncio.sleep(max(0,start+(i+1)*.02-time.perf_counter()))
                if i==last:speech_end=time.perf_counter()
            await ws.send(json.dumps({'type':'input_audio_buffer.commit'}))
        task=asyncio.create_task(upload())
        try:
            async with asyncio.timeout(45):
                async for raw in ws:
                    event=json.loads(raw)
                    if event['type']=='error':raise RuntimeError(event['error']['message'])
                    if event['type'].endswith('transcription.delta') and partial is None:partial=time.perf_counter()
                    if event['type'].endswith('transcription.completed'):
                        text=event['transcript'];final=time.perf_counter();break
            await task
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
        sink=Sink();pipeline=StreamingSpeech(sink,api_key=server.FISH_API_KEY,voice_id=server.FISH_VOICE_ID,model=os.getenv('FISH_MODEL','s2.1-pro-free'))
        try:
            response=await server.generate_response(text,LLMClient(),server.task_manager,[],[],on_delta=pipeline.feed)
            await pipeline.finish()
            complete=time.perf_counter()
            def ms(t):return round((t-speech_end)*1000) if t else None
            return {'method':'paced synthetic microphone PCM; measured to first server PCM, not acoustic playback','speech_end':0,'stt_final':ms(final),'llm_first_token':ms(sink.events.get('llm_first_token')),'first_tts_chunk':ms(sink.first),'response_complete':ms(complete),'partial_before_speech_end':bool(partial and partial<speech_end),'estimated_browser_first_audio':ms(sink.first)+15 if sink.first else None}
        finally:await pipeline.close()
async def main():
    try:
        rows=[]
        for _ in range(3):
            result=await run();rows.append(result);print(json.dumps(result),flush=True)
        Path(os.getenv('JARVIS_BENCHMARK_OUTPUT','benchmarks/after.json')).write_text(json.dumps(rows,indent=2),encoding='utf-8')
    finally:await close_http_clients()
asyncio.run(main())
