from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import jarvis.server as server


def test_local_website_and_screenshot_skip_remote_router():
    with patch.object(server.jev, 'configured', return_value=True), \
         patch.object(server.agent_router, 'route', new=AsyncMock()) as route, \
         patch.object(server, 'open_website', new=AsyncMock(return_value='Opening youtube.com in Chrome.')) as website, \
         patch.object(server, 'take_screenshot', new=AsyncMock(return_value=None)) as screenshot, \
         patch.object(server, 'synthesize_speech', new=AsyncMock(return_value=None)):
        with TestClient(server.app) as client:
            with client.websocket_connect('/ws/voice', subprotocols=['jarvis', 'jarvis.auth.' + server.JARVIS_AUTH_TOKEN]) as ws:
                for phrase, expected in [('Open YouTube', 'Opening youtube.com'),
                                         ('Take a screenshot', 'could not capture')]:
                    ws.send_json({'type': 'transcript', 'text': phrase, 'isFinal': True})
                    for _ in range(10):
                        message = ws.receive_json()
                        if message.get('type') == 'text' and expected in message['text']:
                            break
                    else:
                        raise AssertionError('Local command response missing')
    route.assert_not_awaited()
    website.assert_awaited_once()
    screenshot.assert_awaited_once()


def test_german_screenshot_requests_capture_locally_instead_of_running_a_routine():
    phrases = ['Mach einen Screenshot', 'Jarvis, mache bitte ein Bildschirmfoto.', 'Screenshot machen', 'Bildschirmfoto']
    with patch.object(server.jev, 'configured', return_value=True), \
         patch.object(server.agent_router, 'route', new=AsyncMock()) as route, \
         patch.object(server, 'take_screenshot', new=AsyncMock(return_value=None)) as screenshot, \
         patch.object(server, 'synthesize_speech', new=AsyncMock(return_value=None)):
        with TestClient(server.app) as client:
            with client.websocket_connect('/ws/voice', subprotocols=['jarvis', 'jarvis.auth.' + server.JARVIS_AUTH_TOKEN]) as ws:
                for phrase in phrases:
                    ws.send_json({'type': 'transcript', 'text': phrase, 'isFinal': True})
                    for _ in range(10):
                        message = ws.receive_json()
                        if message.get('type') == 'text' and 'could not capture' in message['text']:
                            break
                    else:
                        raise AssertionError('Screenshot response missing for ' + phrase)
    route.assert_not_awaited()
    assert screenshot.await_count == len(phrases)
