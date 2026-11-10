import asyncio,base64,json,time,wave,os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path.home()/'Documents/Jarvis v5/config/.env',override=True)
import jarvis.server as server
from jarvis.integrations.llm_client import LLMClient
from jarvis.integrations.http_clients import http_client,close_http_clients
class Sink:
    def __init__(self):self.first=None;self.pcm=bytearray()
    async def send_json(self,m):
        if m['type']=='pcm_chunk':
            self.first=self.first or time.perf_counter()
            self.pcm.extend(base64.b64decode(m['data']))
async def main():
    try:
        source=Sink()
        server.remember_english('Explain in one short sentence what an API does.')
        await server.stream_speech(source,'Explain in one short sentence what an API does.')
        sample=Path('benchmarks/input.wav')
        with wave.open(str(sample),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(44100);f.writeframes(source.pcm)
        start=time.perf_counter()
        async with http_client(30) as client:
            r=await client.post('https://api.openai.com/v1/audio/transcriptions',headers={'Authorization':'Bearer '+server.OPENAI_API_KEY},data={'model':os.getenv('OPENAI_TRANSCRIBE_MODEL','gpt-4o-mini-transcribe')},files={'file':('sample.wav',sample.read_bytes(),'audio/wav')})
            r.raise_for_status();text=r.json()['text']
        stt=time.perf_counter()
        response=await server.generate_response(text,LLMClient(),server.task_manager,[],[])
        llm=time.perf_counter()
        sink=Sink();await server.stream_speech(sink,server.strip_markdown_for_tts(response))
        end=time.perf_counter()
        result={'method':'synthetic audio; server arrival of first PCM, not acoustic playback','stt_ms':round((stt-start)*1000),'llm_complete_ms':round((llm-stt)*1000),'tts_first_pcm_ms':round((sink.first-llm)*1000) if sink.first else None,'estimated_old_speech_end_to_pcm_ms':round(2000+(sink.first-start)*1000) if sink.first else None,'processing_complete_ms':round((end-start)*1000)}
        Path('benchmarks/before.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
    finally:await close_http_clients()
asyncio.run(main())
