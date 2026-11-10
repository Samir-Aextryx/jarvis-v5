"""Order and clean up a verified private WhatsApp call.

The desktop dialer must verify the saved recipient and both WhatsApp audio
endpoints in ``prepare``. No call may be placed before the privacy and silence
guards are active. The dialer is deliberately separate from this state machine
so an unverified UI layout cannot accidentally become a valid call path.
"""

import asyncio

from jarvis.voice.call_conversation import CallConversation
from jarvis.voice.call_privacy import phone_call_privacy
from jarvis.voice.silent_call_audio import SilentCallAudio


class WhatsAppCallSession:
    def __init__(self, *, dialer, bridge, expected_number, clients=(),
                 privacy=None, silence_factory=None, conversation_factory=None,
                 answer_timeout=45):
        self.dialer = dialer
        self.bridge = bridge
        self.expected_number = expected_number
        self.clients = tuple(clients)
        self.privacy = privacy or phone_call_privacy
        self.silence_factory = silence_factory or SilentCallAudio
        self.conversation_factory = conversation_factory or CallConversation
        self.answer_timeout = answer_timeout

    async def _watch_call(self, silent_session, stop):
        while not stop.is_set():
            if not silent_session.active:
                stop.set()
                raise RuntimeError('Call audio privacy could not be maintained.')
            if not await asyncio.wait_for(self.dialer.is_connected(), timeout=2):
                stop.set()
                return
            await asyncio.sleep(.1)

    async def _converse(self, conversation, silent_session, privacy_session, source, subject, stop):
        dialogue = asyncio.create_task(conversation.run(
            alert_source=source, alert_subject=subject, stop=stop,
            privacy_session=privacy_session, silence_session=silent_session))
        watching = asyncio.create_task(self._watch_call(silent_session, stop))
        try:
            await asyncio.wait((dialogue, watching), return_when=asyncio.FIRST_COMPLETED)
            if watching.done():
                await watching
            return await dialogue
        finally:
            for task in (dialogue, watching):
                if not task.done():
                    task.cancel()
            await asyncio.gather(dialogue, watching, return_exceptions=True)

    async def run(self, *, source, subject='', stop=None) -> dict:
        if source not in {'gmail', 'outlook'}:
            raise ValueError('Unknown urgent mail source.')
        if not self.expected_number:
            raise ValueError('A verified owner number is required.')
        stop = stop or asyncio.Event()
        privacy_session = await self.privacy.begin(self.clients)
        may_restore_privacy = True
        try:
            with self.silence_factory() as silent_session:
                dial_attempted = False
                try:
                    # prepare must fail if the contact number, cable microphone
                    # or private speaker route cannot be verified in WhatsApp.
                    await asyncio.wait_for(
                        self.dialer.prepare(self.expected_number, self.bridge.devices),
                        timeout=15)
                    if stop.is_set():
                        return {'state': 'cancelled'}
                    # Once dialing is attempted, its outcome is uncertain until
                    # the UI proves otherwise. Always try to hang up on exit.
                    dial_attempted = True
                    await asyncio.wait_for(self.dialer.dial(), timeout=10)
                    try:
                        answered = await asyncio.wait_for(
                            self.dialer.wait_answered(stop=stop), timeout=self.answer_timeout)
                    except TimeoutError:
                        answered = False
                    if not answered:
                        return {'state': 'no_answer'}
                    conversation = self.conversation_factory(
                        self.bridge, privacy=self.privacy, clients=self.clients)
                    outcome = await self._converse(conversation, silent_session,
                        privacy_session, source, subject, stop)
                    if not conversation.spoken:
                        return {'state': 'cancelled'}
                    return {'state': 'connected', 'spoken': True, 'outcome': outcome}
                finally:
                    if dial_attempted:
                        try:
                            ended = await asyncio.wait_for(self.dialer.hangup(), timeout=8)
                            if ended is not True:
                                raise RuntimeError('WhatsApp call termination was not verified.')
                        except BaseException:
                            # Restoring speakers/microphone while the call may
                            # still exist could expose audio. Leave both muted
                            # and desktop capture paused until verified recovery.
                            silent_session.keep_muted()
                            may_restore_privacy = False
                            raise
        finally:
            if may_restore_privacy:
                await self.privacy.end(privacy_session, self.clients)
