"""Reuse TLS connections per event loop; keep test transports isolated."""
import asyncio
from contextlib import asynccontextmanager
from weakref import WeakKeyDictionary
import httpx

_clients = WeakKeyDictionary()


@asynccontextmanager
async def http_client(timeout=60, transport=None):
    if transport is not None:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            yield client
        return
    loop = asyncio.get_running_loop()
    clients = _clients.setdefault(loop, {})
    client = clients.get(timeout)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(timeout=timeout, limits=httpx.Limits(max_connections=12, max_keepalive_connections=6, keepalive_expiry=120))
        clients[timeout] = client
    yield client


async def close_http_clients():
    clients = _clients.pop(asyncio.get_running_loop(), {})
    await asyncio.gather(*(client.aclose() for client in clients.values()))
