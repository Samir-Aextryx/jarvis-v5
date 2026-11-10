import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
"""Start the local JARVIS service and open its authenticated setup page."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
URL = "http://localhost:8340"


def online():
    try:
        with urllib.request.urlopen(URL + "/api/health", timeout=2) as response:
            data = json.load(response)
            return data.get("name") == "JARVIS" and data.get("status") == "online"
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not (ROOT / "frontend/dist/index.html").exists():
        raise SystemExit("Frontend fehlt. Bitte zuerst das Frontend bauen.")
    if not online():
        env = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1")
        with (ROOT / "server.log").open("a", encoding="utf-8") as output:
            process = subprocess.Popen([sys.executable, "-m", "jarvis"], cwd=ROOT, env=env,
                stdout=output, stderr=output, creationflags=subprocess.CREATE_NO_WINDOW)
        (ROOT / "server.pid").write_text(str(process.pid))
        for _ in range(40):
            if online(): break
            if process.poll() is not None: break
            time.sleep(0.25)
        if not online():
            raise SystemExit("Start fehlgeschlagen. Details stehen in server.log.")
    from jarvis.core.auth import auth_token
    if not args.no_browser:
        # Exchange the bearer token for a one-time link so it never appears in
        # the browser's URL history or command line.
        request = urllib.request.Request(
            URL + "/api/dashboard/session", method="POST",
            headers={"Authorization": "Bearer " + auth_token()})
        with urllib.request.urlopen(request, timeout=5) as response:
            webbrowser.open(json.load(response)["url"])
    print("JARVIS bereit: " + URL + " — API-Schlüssel in Settings eintragen.")


if __name__ == "__main__":
    main()
