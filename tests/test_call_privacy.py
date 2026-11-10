import unittest

from jarvis.voice.call_privacy import CallPrivacy


class PrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def test_call_waits_for_every_desktop_to_release_its_microphone(self):
        privacy = CallPrivacy()
        class Desktop:
            def __init__(self):
                self.messages = []
            async def send_json(self, message):
                self.messages.append(message)
                if message['active']:
                    privacy.acknowledge(self, message['session'])
        clients = [Desktop(), Desktop()]
        session = await privacy.begin(clients, timeout=.2)
        self.assertTrue(privacy.active)
        self.assertTrue(all(client.messages[0]['active'] for client in clients))
        self.assertFalse(privacy.acknowledge(clients[0], 'wrong-session'))
        self.assertTrue(await privacy.end(session, clients))
        self.assertFalse(privacy.active)
        self.assertTrue(all(client.messages[-1]['active'] is False for client in clients))

    async def test_unacknowledged_microphone_stops_the_call_before_dialing(self):
        privacy = CallPrivacy()
        class Desktop:
            def __init__(self):
                self.messages = []
            async def send_json(self, message):
                self.messages.append(message)
        client = Desktop()
        with self.assertRaises(TimeoutError):
            await privacy.begin([client], timeout=.01)
        self.assertFalse(privacy.active)
        self.assertEqual([item['active'] for item in client.messages], [True, False])

    async def test_single_owner_and_stale_ack(self):
        privacy = CallPrivacy()
        session = await privacy.begin(())
        with self.assertRaises(RuntimeError):
            await privacy.begin(())
        self.assertFalse(privacy.acknowledge(object(), session))
        self.assertFalse(await privacy.end('wrong'))
        self.assertTrue(privacy.active)
        self.assertTrue(await privacy.end(session))
        self.assertFalse(privacy.active)


if __name__ == '__main__':
    unittest.main()
