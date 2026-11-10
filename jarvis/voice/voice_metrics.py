"""Content-free bounded voice latency history. Playback time is client scheduled."""
from collections import deque
import json
import math
import time
from jarvis.core.runtime_paths import DATA_ROOT

recent=deque(maxlen=100)
STAGES={'speech_end','stt_final','llm_first_token','first_tts_chunk','first_audio',
        'automation_start','automation_complete','response_complete'}


def record(message):
    values=message.get('timings',{})
    if not isinstance(values,dict) or 'speech_end' not in values:
        return
    if any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in values.values()):
        return
    base=values['speech_end']
    row={'timestamp':time.time(),'cancelled':bool(message.get('cancelled')),
         'measurement':'browser scheduled playback; not acoustic loopback',
         'milliseconds':{key:round(value-base,2) for key,value in values.items() if key in STAGES and 0<=value-base<600000}}
    action_start=values.get('automation_start')
    action_end=values.get('automation_complete')
    if isinstance(action_start,(int,float)) and isinstance(action_end,(int,float)) and action_end>=action_start:
        row['automation_ms']=round(action_end-action_start,2)
    recent.append(row)
    path=DATA_ROOT/'data/voice-latency.jsonl'
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.stat().st_size>1024*1024:
        path.write_text('',encoding='utf-8')
    with path.open('a',encoding='utf-8') as stream:
        stream.write(json.dumps(row)+'\n')
