"""Stop desktop microphone capture before a private phone conversation starts."""

import asyncio
import logging
import uuid

log = logging.getLogger('jarvis.call_privacy')


class CallPrivacy:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._session: str | None = None
        self._acks: dict[int, asyncio.Future] = {}

    @property
    def active(self) -> bool:
        return self._session is not None

    @property
    def session(self) -> str | None:
        return self._session

    async def begin(self, clients=(), *, timeout=3) -> str:
        """Require every connected Jarvis UI to release its physical mic."""
        clients = tuple(clients)
        async with self._lock:
            if self._session is not None:
                raise RuntimeError('Another phone call already owns microphone privacy.')
            session = uuid.uuid4().hex
            loop = asyncio.get_running_loop()
            self._session = session
            self._acks = {id(client): loop.create_future() for client in clients}
            acknowledgements = tuple(self._acks.values())
        try:
            for client in clients:
                await client.send_json({'type': 'phone_call_privacy', 'active': True,
                                        'session': session})
            if acknowledgements:
                await asyncio.wait_for(asyncio.gather(*acknowledgements), timeout)
            if self._session != session:
                raise RuntimeError('Phone privacy session ended before dialing.')
        except BaseException:
            await self.end(session, clients)
            raise
        return session

    def acknowledge(self, client, session: str) -> bool:
        if session != self._session:
            return False
        future = self._acks.get(id(client))
        if future is None:
            return False
        if not future.done():
            future.set_result(None)
        return True

    async def end(self, session: str, clients=()) -> bool:
        clients = tuple(clients)
        async with self._lock:
            if session != self._session:
                return False
            self._session = None
            self._acks = {}
        for client in clients:
            try:
                await client.send_json({'type': 'phone_call_privacy', 'active': False,
                                        'session': session})
            except Exception:
                # A disconnected page no longer has a live microphone stream.
                log.warning('Could not notify a disconnected desktop after a phone call.')
        return True


phone_call_privacy = CallPrivacy()
