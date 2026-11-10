"""Windows desktop actions used by voice commands and autonomous tasks."""
import asyncio
import base64
import logging
import re
import time
from pathlib import Path
from urllib.parse import quote

from jarvis.automation.windows_support import (
    get_chrome_tab_info, open_browser, open_codex_in_project, open_terminal,
    prompt_existing_terminal,
)

log = logging.getLogger("jarvis.actions")
DESKTOP_PATH = Path.home() / "Desktop"


async def open_chrome(url: str) -> dict:
    return await open_browser(url, "chrome")


async def monitor_build(project_dir: str, ws=None, synthesize_fn=None) -> None:
    """Watch a project's completion marker and notify voice clients once."""
    output_file = Path(project_dir) / ".jarvis_output.txt"
    start = time.monotonic()
    while time.monotonic() - start < 600:
        await asyncio.sleep(1)
        try:
            content = await asyncio.to_thread(output_file.read_text, encoding="utf-8")
        except OSError:
            continue
        if "--- JARVIS TASK COMPLETE ---" not in content:
            continue
        log.info("Build complete in %s", project_dir)
        if ws and synthesize_fn:
            try:
                audio_bytes = await synthesize_fn("The build is complete.")
                if audio_bytes:
                    await ws.send_json({"type": "status", "state": "speaking"})
                    await ws.send_json({"type": "audio", "data": base64.b64encode(audio_bytes).decode(),
                                        "text": "The build is complete."})
                    await ws.send_json({"type": "status", "state": "idle"})
            except Exception:
                log.warning("Could not send the build completion notice.")
        return
    log.warning("Build timed out in %s", project_dir)


async def execute_action(intent: dict, projects: list = None) -> dict:
    """Run a supported local action selected by the voice intent router."""
    action = intent.get("action", "chat")
    target = intent.get("target", "")
    if action == "open_terminal":
        result = await open_terminal()
        return dict(result, project_dir=None)
    if action == "browse":
        url = target if target.startswith(("http://", "https://")) else (
            "https://www.google.com/search?q=" + quote(target))
        browser = "firefox" if "firefox" in target.casefold() else "chrome"
        return dict(await open_browser(url, browser), project_dir=None)
    if action == "build":
        name = _generate_project_name(target)
        project_dir = str(DESKTOP_PATH / name)
        Path(project_dir).mkdir(parents=True, exist_ok=True)
        return dict(await open_codex_in_project(project_dir, target), project_dir=project_dir)
    return {"success": False, "confirmation": "", "project_dir": None}


def _generate_project_name(prompt: str) -> str:
    quoted = re.search(r'"([^"<>|]+)"', prompt)
    if quoted:
        words = re.sub(r"[^a-zA-Z0-9\s-]", "", quoted.group(1)).split()
        if words:
            return "-".join(words).lower()
    called = re.search(r'(?:called|named)\s+([\w-]{4,80})', prompt, re.IGNORECASE)
    if called:
        return called.group(1).lower()
    words = re.sub(r"[^a-zA-Z0-9\s]", "", prompt.lower()).split()
    skip = {"a", "the", "an", "me", "build", "create", "make", "for", "with", "and",
            "to", "of", "i", "want", "need", "new", "project", "directory", "called",
            "on", "desktop", "that", "application", "app", "full", "stack", "simple",
            "web", "page", "site", "named"}
    meaningful = [word for word in words if word not in skip and len(word) > 2][:4]
    return "-".join(meaningful) if meaningful else "jarvis-project"
