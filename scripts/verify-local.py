import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
"""Verify local authentication and generate a short Fish voice sample."""
import base64
from pathlib import Path
import time
import httpx

root = Path(__file__).resolve().parents[1]
from jarvis.core.auth import auth_token
jarvis_token = auth_token()

try:
    with httpx.Client(base_url="http://localhost:8340", timeout=60,
                      headers={"Authorization": "Bearer " + jarvis_token}) as client:
        # The server reads the keys from Credential Manager itself; re-posting
        # them would only move the secret around and could fail on write.
        result = client.post("/api/settings/test-fish", json={}).json()
        print("Fish voice test:", result)
        if result.get("valid"):
            response = client.get("/api/tts-test")
            response.raise_for_status()
            audio = response.json().get("audio")
            if audio:
                # Keep earlier samples: never overwrite a previous test result.
                path = root / f"voice-test-{time.strftime('%Y%m%d-%H%M%S')}.mp3"
                counter = 1
                while path.exists():
                    path = root / f"voice-test-{time.strftime('%Y%m%d-%H%M%S')}-{counter}.mp3"
                    counter += 1
                path.write_bytes(base64.b64decode(audio))
                print("Voice sample saved:", path.name, path.stat().st_size, "bytes")
        status = client.get("/api/settings/status").json()
        print("Configured:", {k: status["env_keys_set"][k] for k in ("openai", "fish_audio")})
except Exception as exc:
    print("Verification failed:", type(exc).__name__)
    raise SystemExit(1)
