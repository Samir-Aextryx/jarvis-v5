import asyncio
import unittest

from jarvis.integrations.whatsapp_call_session import WhatsAppCallSession


class Privacy:
    def __init__(self, events):
        self.events = events
        self.session = None

    async def begin(self, clients):
        self.events.append('privacy_on')
        self.session = 'private-call'
        return self.session

    async def end(self, session, clients):
        self.events.append('privacy_off')
        self.session = None


class Silence:
    def __init__(self, events):
        self.events = events
        self.active = False

    def __enter__(self):
        self.events.append('silent_on')
        self.active = True
        return self

    def __exit__(self, *_):
        self.events.append('silent_off')
        self.active = False

    def keep_muted(self):
        self.events.append('keep_muted')


class Dialer:
    def __init__(self, events, *, answer=True, fail_at=None, wait_delay=0):
        self.events = events
        self.answer = answer
        self.fail_at = fail_at
        self.wait_delay = wait_delay

    async def prepare(self, expected_number, devices):
        self.events.append('prepare')
        if self.fail_at == 'prepare':
            raise RuntimeError('No verified WhatsApp audio route')

    async def dial(self):
        self.events.append('dial')
        if self.fail_at == 'dial':
            raise RuntimeError('Dial outcome unknown')

    async def wait_answered(self, *, stop):
        self.events.append('wait_answered')
        if self.wait_delay:
            await asyncio.sleep(self.wait_delay)
        return self.answer

    async def hangup(self):
        self.events.append('hangup')
        return self.fail_at != 'hangup'

    async def is_connected(self):
        return True


class Conversation:
    def __init__(self, events):
        self.events = events
        self.spoken = True

    async def run(self, **kwargs):
        self.events.append('conversation')
        self.events.append('guards_active:' + str(kwargs['silence_session'].active))
        return 'user_stopped'


class CallSessionTests(unittest.IsolatedAsyncioTestCase):
    def make_session(self, events, *, answer_timeout=.2, **kwargs):
        privacy = Privacy(events)
        return WhatsAppCallSession(
            dialer=Dialer(events, **kwargs),
            bridge=type('Bridge', (), {'devices': object()})(),
            expected_number='+41790000000', privacy=privacy,
            silence_factory=lambda: Silence(events),
            conversation_factory=lambda *_args, **_kwargs: Conversation(events),
            answer_timeout=answer_timeout)

    async def test_entire_call_keeps_guards_active_until_hangup(self):
        events = []
        result = await self.make_session(events).run(source='gmail', subject='Urgent')
        self.assertEqual(result['state'], 'connected')
        self.assertTrue(result['spoken'])
        self.assertEqual(events, ['privacy_on', 'silent_on', 'prepare', 'dial',
                                  'wait_answered', 'conversation', 'guards_active:True',
                                  'hangup', 'silent_off', 'privacy_off'])

    async def test_failed_preflight_never_dials_and_restores_guards(self):
        events = []
        with self.assertRaisesRegex(RuntimeError, 'No verified'):
            await self.make_session(events, fail_at='prepare').run(source='outlook')
        self.assertEqual(events, ['privacy_on', 'silent_on', 'prepare',
                                  'silent_off', 'privacy_off'])

    async def test_uncertain_dial_still_attempts_hangup(self):
        events = []
        with self.assertRaisesRegex(RuntimeError, 'Dial outcome unknown'):
            await self.make_session(events, fail_at='dial').run(source='outlook')
        self.assertEqual(events[-3:], ['hangup', 'silent_off', 'privacy_off'])

    async def test_no_answer_hangs_up_without_starting_conversation(self):
        events = []
        result = await self.make_session(events, answer=False).run(source='gmail')
        self.assertEqual(result['state'], 'no_answer')
        self.assertNotIn('conversation', events)
        self.assertEqual(events[-3:], ['hangup', 'silent_off', 'privacy_off'])

    async def test_cancel_before_dial(self):
        events = []
        stop = asyncio.Event()
        stop.set()
        result = await self.make_session(events).run(source='gmail', stop=stop)
        self.assertEqual(result['state'], 'cancelled')
        self.assertNotIn('dial', events)
        self.assertEqual(events[-2:], ['silent_off', 'privacy_off'])

    async def test_ringing_timeout_hangs_up_before_unmuting(self):
        events = []
        result = await self.make_session(events, answer_timeout=.01,
                                         wait_delay=1).run(source='outlook')
        self.assertEqual(result['state'], 'no_answer')
        self.assertEqual(events[-3:], ['hangup', 'silent_off', 'privacy_off'])

    async def test_uncertain_hangup_keeps_hardware_muted_and_desktop_capture_paused(self):
        events = []
        session = self.make_session(events, fail_at='hangup')
        with self.assertRaisesRegex(RuntimeError, 'termination was not verified'):
            await session.run(source='gmail')
        self.assertIn('keep_muted', events)
        self.assertNotIn('privacy_off', events)
        self.assertIsNotNone(session.privacy.session)


if __name__ == '__main__':
    unittest.main()
