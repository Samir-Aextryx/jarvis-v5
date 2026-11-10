import asyncio

"""Suppress messages from cancelled turns, including their background tasks."""
class TurnSocket:
    def __init__(self, socket, active, turn_id=None):
        self.socket = socket
        self.active = active
        self.turn_id = turn_id

    async def send_json(self, data, *args, **kwargs):
        if self.active():
            if self.turn_id:
                data=dict(data,turn_id=self.turn_id)
            if isinstance(self.socket, SerializedSocket):
                await self.socket.send_if_active(self.active, data, *args, **kwargs)
            else:
                await self.socket.send_json(data, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.socket, name)


class SerializedSocket:
    def __init__(self, socket):
        self.socket = socket
        self._send_lock = asyncio.Lock()
    async def send_json(self, data, *args, **kwargs):
        async with self._send_lock:
            await self.socket.send_json(data, *args, **kwargs)
    def __getattr__(self, name):
        return getattr(self.socket, name)

    async def send_if_active(self, active, data, *args, **kwargs):
        async with self._send_lock:
            if active():
                await self.socket.send_json(data, *args, **kwargs)
