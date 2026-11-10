import unittest
from unittest.mock import AsyncMock,patch
from jarvis.automation.website_launcher import parse_website_request,open_website
from jarvis.automation.gods_eye import SWITZERLAND_URL, USA_URL

class MapTests(unittest.IsolatedAsyncioTestCase):
    def test_spoken_places(self):
        for text in ['Open Switzerland','Open Switzerland.','Öffne die Schweiz','Open Switzerland in Chrome']:
            self.assertEqual(parse_website_request(text),'jarvis:switzerland')
        self.assertEqual(parse_website_request("Open God's Eye View"),'jarvis:gods-eye')
        for phrase in ['Open USA','Open the USA.','Open United States','Öffne die USA','Open U S A']:
            self.assertEqual(parse_website_request(phrase),'jarvis:usa')

    def test_voice_map_uses_native_event_not_chrome(self):
        import jarvis.server as server; import time
        from fastapi.testclient import TestClient
        with patch.object(server,'_last_greeting_time',time.time()),patch('jarvis.automation.gods_eye.ensure_running',new=AsyncMock()),patch('jarvis.automation.website_launcher.open_in_chrome') as chrome:
            with TestClient(server.app) as client:
                with client.websocket_connect('/ws/voice', subprotocols=['jarvis', 'jarvis.auth.' + server.JARVIS_AUTH_TOKEN]) as ws:
                    ws.receive_json()
                    ws.send_json({'type':'transcript','isFinal':True,'text':'Open USA'})
                    for _ in range(10):
                        event=ws.receive_json()
                        if event['type']=='open_map':
                            self.assertEqual(event['url'],USA_URL)
                            break
                    else:self.fail('Native map event missing')
                    ws.send_json({'type':'stop','cancelTasks':True})
            chrome.assert_not_called()

    async def test_launch_uses_verified_local_view(self):
        with patch('jarvis.automation.gods_eye.ensure_running',new=AsyncMock()),patch('jarvis.automation.website_launcher.open_in_chrome') as launch:
            self.assertIn('Switzerland',await open_website('jarvis:switzerland'))
            launch.assert_called_once_with(SWITZERLAND_URL)

    async def test_server_failure_does_not_open_another_service(self):
        with patch('jarvis.automation.gods_eye.ensure_running',new=AsyncMock(side_effect=RuntimeError('Port occupied'))),patch('jarvis.automation.website_launcher.open_in_chrome') as launch:
            self.assertIn('could not',await open_website('jarvis:switzerland'))
            launch.assert_not_called()
