import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
"""Backend entry point for the Electron desktop shell."""
import os
import uvicorn
if "--print-auth-token" in sys.argv:
    from jarvis.core.auth import auth_token
    print(auth_token())
    raise SystemExit(0)
import jarvis.server as server

if __name__ == "__main__":
    uvicorn.run(server.app, host="127.0.0.1", port=int(os.getenv("JARVIS_PORT", "8345")),
                log_level="info", access_log=False)
