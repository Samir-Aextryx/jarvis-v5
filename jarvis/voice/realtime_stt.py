"""Authenticated PCM relay; API credentials never leave the backend."""
import asyncio
import base64
from collections import deque
import json
import os
import re
from websockets.asyncio.client import connect
from jarvis.voice.transcript_guard import clean_transcript
from jarvis.voice.call_privacy import phone_call_privacy
from jarvis.voice.transcription_config import transcription_keywords


def transcription_session(delay=None):
    allowed_delays = {'minimal', 'low', 'medium', 'high', 'xhigh'}
    delay = delay if delay in allowed_delays else os.getenv('JARVIS_STT_DELAY', 'minimal')
    if delay not in allowed_delays:
        delay = 'minimal'
    clean_keywords = transcription_keywords()
    return {'type':'session.update','session':{'type':'transcription','audio':{'input':{
        'format':{'type':'audio/pcm','rate':24000},
        'transcription':{'model':os.getenv('OPENAI_REALTIME_TRANSCRIBE_MODEL','gpt-live-transcribe'),
                         'prompt':'Live voice commands and everyday conversations with JARVIS about meetings, routines, apps and email. Recognize natural German and English commands to open Outlook, including "Outlook öffnen", "mach Outlook auf", "open my Outlook" and "open the Outlook app". Treat "schreib/verfasse eine E-Mail in Outlook" and "write/draft an email in Outlook" as email-draft requests. Preserve recipient names, subject lines and dictated message text exactly; do not translate or paraphrase them.',
                         'keywords':clean_keywords, 'languages':['en','de'],'delay':delay},
        'turn_detection':None}}}}


async def serve_stt(ws, auth_token, api_key):
    from jarvis.core.auth import authenticate_websocket
    if not await authenticate_websocket(ws, auth_token):
        return
    if phone_call_privacy.active:
        await ws.close(code=4004)
        return
    protocols = [part.strip() for part in ws.headers.get('sec-websocket-protocol', '').split(',')]
    requested_delay = next((part.rsplit('.', 1)[-1] for part in protocols
                            if part.startswith('jarvis.stt.delay.')), None)
    jobs=[]
    try:
        async with connect('wss://api.openai.com/v1/realtime?intent=transcription',
                additional_headers={'Authorization':'Bearer '+api_key}, open_timeout=12,
                ping_interval=20, ping_timeout=20, max_queue=16, max_size=1024*1024) as upstream:
            await upstream.send(json.dumps(transcription_session(requested_delay)))
            async with asyncio.timeout(15):
                while True:
                    event=json.loads(await upstream.recv())
                    if event.get('type')=='error':
                        raise RuntimeError('Realtime transcription configuration was rejected.')
                    if event.get('type')=='session.updated':
                        break
            await ws.send_json({'type':'ready'})
            current=None
            pending=deque()
            items={}
            completed=set()
            audio_bytes=0
            async def upload():
                nonlocal current,audio_bytes
                while True:
                    packet=await ws.receive()
                    if packet['type']=='websocket.disconnect':
                        return
                    if phone_call_privacy.active:
                        await ws.close(code=4004)
                        return
                    if packet.get('bytes') is not None:
                        frame=packet['bytes']
                        if current is None or not frame or len(frame)>4800 or len(frame)%2:
                            raise ValueError('Invalid audio frame')
                        audio_bytes+=len(frame)
                        if audio_bytes>24000*2*125:
                            raise ValueError('Audio turn exceeded its limit')
                        if phone_call_privacy.active:
                            await ws.close(code=4004)
                            return
                        await upstream.send(json.dumps({'type':'input_audio_buffer.append','audio':base64.b64encode(frame).decode()}))
                    else:
                        message=json.loads(packet.get('text') or '{}')
                        if message.get('type')=='start':
                            if current is not None or len(pending)>=8 or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',str(message.get('id',''))):
                                raise ValueError('Invalid audio turn')
                            current=message['id']
                            audio_bytes=0
                        elif message.get('type')=='commit':
                            if current is None or message.get('id') != current or audio_bytes<4800:
                                raise ValueError('Audio turn is too short')
                            pending.append(current)
                            await upstream.send(json.dumps({'type':'input_audio_buffer.commit'}))
                            current=None
                        else:
                            raise ValueError('Unknown audio command')
            async def download():
                async for raw in upstream:
                    event=json.loads(raw)
                    kind=event.get('type','')
                    item=event.get('item_id')
                    if kind=='error' or kind.endswith('transcription.failed'):
                        raise RuntimeError('Live transcription failed. Please repeat the request.')
                    if kind=='input_audio_buffer.committed':
                        if not pending:
                            raise RuntimeError('Unexpected committed transcript')
                        items[item]=pending.popleft()
                    if kind.endswith('input_audio_transcription.delta'):
                        turn=items.get(item) or (pending[0] if pending else current)
                        if turn:
                            await ws.send_json({'type':'partial','id':turn,'text':event.get('delta','')})
                    if kind.endswith('input_audio_transcription.completed') and item not in completed:
                        turn=items.pop(item,None)
                        if not turn:
                            raise RuntimeError('Transcript order could not be verified')
                        completed.add(item)
                        if len(completed)>256:
                            completed.clear()
                            completed.add(item)
                        await ws.send_json({'type':'final','id':turn,'text':clean_transcript(event.get('transcript',''))})
            jobs=[asyncio.create_task(upload()),asyncio.create_task(download())]
            done,_=await asyncio.wait(jobs,return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                await task
    except asyncio.CancelledError:
        raise
    except Exception:
        try:
            await ws.send_json({'type':'error','message':'Live speech recognition disconnected. Switching to fallback; please repeat the last request.'})
        except Exception:
            pass
    finally:
        for task in jobs:
            task.cancel()
        await asyncio.gather(*jobs,return_exceptions=True)
        try:
            await ws.close()
        except Exception:
            pass
