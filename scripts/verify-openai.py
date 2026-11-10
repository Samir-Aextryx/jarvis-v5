import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
"""Opt-in live OpenAI + Fish integration check, without logging credentials."""
import asyncio
import base64
import json
import time
from pathlib import Path
import httpx
from websockets.asyncio.client import connect

root = Path(__file__).resolve().parents[1]
from jarvis.core.auth import auth_token
jarvis_token = auth_token()


async def main():
    async with httpx.AsyncClient(base_url="http://localhost:8340", timeout=90,
                                headers={"Authorization": "Bearer " + jarvis_token}) as client:
        # The server reads the keys from Credential Manager itself; re-posting
        # them would only move the secret around and could fail on write.
        test = (await client.post("/api/settings/test-openai", json={})).json()
        print("OpenAI API test:", test)
        if not test.get("valid"):
            raise RuntimeError("OpenAI validation failed")
    async with connect("ws://localhost:8340/ws/voice", subprotocols=["jarvis", "jarvis.auth." + jarvis_token]) as socket:
        await socket.send(json.dumps({"type": "transcript", "isFinal": True,
                                      "text": "Antworte exakt mit: Windows und OpenAI sind bereit."}))
        async with asyncio.timeout(90):
            while True:
                message = json.loads(await socket.recv())
                if message.get("type") in {"audio", "text"} and "Windows" in message.get("text", ""):
                    print("End-to-end response:", message["text"])
                    if message.get("type") != "audio" or not message.get("data"):
                        raise RuntimeError("No Fish audio returned")
                    data = base64.b64decode(message["data"])
                    # Keep earlier samples instead of overwriting them.
                    path = root / f"openai-fish-test-{time.strftime('%Y%m%d-%H%M%S')}.mp3"
                    counter = 1
                    while path.exists():
                        path = root / f"openai-fish-test-{time.strftime('%Y%m%d-%H%M%S')}-{counter}.mp3"
                        counter += 1
                    path.write_bytes(data)
                    print("OpenAI + WebSocket + Fish audio OK:", len(data), "bytes ->", path.name)
                    return

try:
    asyncio.run(main())
except Exception as exc:
    print("Live verification failed:", type(exc).__name__)
    raise SystemExit(1)
