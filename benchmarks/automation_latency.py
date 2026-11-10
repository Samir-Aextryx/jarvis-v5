"""Measure deterministic mail planning and installed app-opening latency.

This benchmark never sends an email. App-opening flags focus or start only the
explicitly named app; voice mode supplies a transcript without microphone audio.
"""
import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx
import websockets
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def measure_voice_app_open(name):
    """Measure from final transcript to action, then observe the actual app window."""
    from jarvis.core.auth import auth_token
    from jarvis.automation.app_launcher import installed_apps, resolve_app
    from jarvis.automation.app_windows import windows
    matches = resolve_app(name, installed_apps())
    if len(matches) != 1:
        return {'voice_app':name, 'error':'App name is missing or ambiguous in the Windows Start catalog.'}
    app = matches[0]
    was_running = bool(await asyncio.to_thread(windows, app))
    token = auth_token()
    turn_id = 'automation-benchmark-' + uuid.uuid4().hex
    last_error = 'Jarvis backend unavailable'
    for port in (8345, 8340):
        sent = False
        try:
            async with websockets.connect(
                    f'ws://127.0.0.1:{port}/ws/voice',
                    subprotocols=['jarvis', 'jarvis.auth.' + token],
                    open_timeout=5, close_timeout=1) as ws:
                await ws.send(json.dumps({'type':'transcript', 'text':'Open ' + name,
                                          'isFinal':True, 'turn_id':turn_id}))
                sent = True
                transcript_sent = time.perf_counter()
                while True:
                    event = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                    if event.get('turn_id') != turn_id:
                        continue
                    if event.get('type') == 'latency' and event.get('stage') == 'automation_complete':
                        action_ms = round((time.perf_counter()-transcript_sent)*1000,2)
                        deadline = time.perf_counter() + (5 if not was_running else .2)
                        appeared = False
                        while time.perf_counter() < deadline:
                            if await asyncio.to_thread(windows, app):
                                appeared = True
                                break
                            await asyncio.sleep(.025)
                        return {'voice_app':name, 'was_running_before':was_running,
                                'transcript_to_action_ms':action_ms,
                                'transcript_to_window_ms':round((time.perf_counter()-transcript_sent)*1000,2) if appeared else None,
                                'window_observed':appeared, 'server_action_ms':event.get('server_ms'),
                                'method':'authenticated voice websocket; transcript supplied directly'}
        except (OSError, TimeoutError, websockets.WebSocketException) as exc:
            last_error = type(exc).__name__
            if sent:
                return {'voice_app':name, 'error':last_error,
                        'note':'The action may have completed; it was not retried.'}
            if port == 8340:
                break
    return {'voice_app':name, 'error':last_error}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--open-chrome', action='store_true')
    parser.add_argument('--voice-open-app', metavar='NAME',
                        help='open/focus an app through the voice route and measure action latency')
    args = parser.parse_args()
    os.environ['JARVIS_DATA_DIR'] = str(Path.home() / 'Documents' / 'Jarvis v5' / 'config')

    from jarvis.integrations.email_planner import plan_mail
    start = time.perf_counter()
    plan = asyncio.run(plan_mail(
        'Draft an email to alex@example.com in Gmail with subject Meeting saying Hello Alex'))
    result = {'mail_plan_ms': round((time.perf_counter() - start) * 1000, 2),
              'mail_action': plan[0]['action'], 'mail_sent': False}

    if args.open_chrome:
        from jarvis.core.auth import auth_token
        token = auth_token()
        for port in (8345, 8340):
            try:
                with httpx.Client(base_url=f'http://127.0.0.1:{port}',
                                  headers={'Authorization': 'Bearer ' + token}, timeout=8) as client:
                    if client.get('/api/health').status_code != 200:
                        continue
                    start = time.perf_counter()
                    response = client.post('/api/apps/open', json={'name': 'Chrome'})
                    result.update(installed_port=port, open_status=response.status_code,
                                  open_ms=round((time.perf_counter() - start) * 1000, 1),
                                  open_success=response.json().get('success'),
                                  open_state=response.json().get('state'))
                    break
            except httpx.HTTPError:
                continue
        else:
            result['installed_error'] = 'Jarvis backend unavailable'
    if args.voice_open_app:
        result['voice_action'] = asyncio.run(measure_voice_app_open(args.voice_open_app))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
