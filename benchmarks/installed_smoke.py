"""Live integration check of the installed server, without UI actions or sending mail."""
import asyncio
import audioop
import json
import time
import uuid
import wave
from pathlib import Path
from urllib.parse import quote
import httpx
import os
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["JARVIS_DATA_DIR"] = str(Path.home()/"Documents/Jarvis v5/config")
from jarvis.core.auth import auth_token
from websockets.asyncio.client import connect


async def main():
    token=auth_token()
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8345',headers={'Authorization':'Bearer '+token}) as client:
        (await client.get('/api/health')).raise_for_status()
        worklet=await client.get('/pcm-capture.js');worklet.raise_for_status()
        assert 'registerProcessor' in worklet.text
        (await client.get('/api/voice/metrics')).raise_for_status()
    with wave.open('benchmarks/input.wav','rb') as f:
        pcm=audioop.ratecv(f.readframes(f.getnframes()),2,1,f.getframerate(),24000,None)[0]
    frames=[pcm[i:i+960] for i in range(0,len(pcm),960)]
    last=max(i for i,frame in enumerate(frames) if audioop.rms(frame,2)>393)
    frames=frames[:last+1]+[b'\0'*960]*9
    turn=uuid.uuid4().hex; partial=False; speech_end=None
    async with connect('ws://127.0.0.1:8345/ws/stt',subprotocols=['jarvis','jarvis.auth.'+token],close_timeout=1) as stt:
        ready=json.loads(await asyncio.wait_for(stt.recv(),25))
        assert ready['type']=='ready', 'Installed STT could not initialize'
        async def upload():
            nonlocal speech_end
            await stt.send(json.dumps({'type':'start','id':turn}))
            start=time.perf_counter()
            for i,frame in enumerate(frames):
                await stt.send(frame)
                await asyncio.sleep(max(0,start+(i+1)*.02-time.perf_counter()))
                if i==last:speech_end=time.perf_counter()
            await stt.send(json.dumps({'type':'commit','id':turn}))
        upload_task=asyncio.create_task(upload())
        try:
            async with asyncio.timeout(40):
                async for raw in stt:
                    event=json.loads(raw)
                    assert event['type']!='error', 'Installed STT disconnected'
                    if event['type']=='partial':partial=True
                    if event['type']=='final':
                        assert event['id']==turn and event['text']
                        final=time.perf_counter();transcript=event['text'];break
            await upload_task
            async with connect('ws://127.0.0.1:8345/ws/voice',subprotocols=['jarvis','jarvis.auth.'+token],close_timeout=1) as voice:
                await voice.send(json.dumps({'type':'transcript','text':transcript,'isFinal':True,'streamAudio':True,'turn_id':turn}))
                first=None; stages={}; packets=0
                async with asyncio.timeout(45):
                    async for raw in voice:
                        event=json.loads(raw)
                        if event.get('turn_id')!=turn:continue
                        if event['type']=='latency':stages.setdefault(event['stage'],round((time.perf_counter()-speech_end)*1000))
                        if event['type']=='pcm_chunk':
                            first=first or time.perf_counter(); packets+=1
                        if event['type']=='pcm_end':break
                assert first and packets>0, 'Installed server did not stream PCM'
                result={'health':'passed','worklet':'passed','live_partial':partial,'live_final':'passed',
                        'streamed_pcm_packets':packets,'stt_final_ms':round((final-speech_end)*1000),
                        'first_server_pcm_ms':round((first-speech_end)*1000),'stages':stages,
                        'method':'installed backend; synthetic paced input; no acoustic playback'}
                output=Path(os.getenv('JARVIS_INSTALLED_SMOKE_OUTPUT','benchmarks/installed.json'))
                output.parent.mkdir(parents=True,exist_ok=True)
                output.write_text(json.dumps(result,indent=2),encoding='utf-8')
                print(json.dumps(result))
        finally:
            upload_task.cancel();await asyncio.gather(upload_task,return_exceptions=True)


asyncio.run(main())
