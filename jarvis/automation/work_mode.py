"""Persistent Codex sessions tied to a local project directory."""

import asyncio
import json
import logging
import threading
import uuid
import time
from pathlib import Path
from jarvis.core.runtime_paths import DATA_ROOT

log = logging.getLogger("jarvis.work_mode")

SESSION_FILE = DATA_ROOT / "data" / "active_session.json"


class WorkSession:
    """A Codex session tied to a project directory.

    Each project gets its own session. JARVIS can switch between projects
    and --continue picks up where the last message left off.
    """

    def __init__(self):
        self._active = False
        self._working_dir: str | None = None
        self._project_name: str | None = None
        self._message_count = 0  # Track if this is first message (no --continue)
        self._status = "idle"  # idle, working, done, error, cancelled
        self._cancel = threading.Event()

    @property
    def active(self) -> bool:
        return self._active

    @property
    def project_name(self) -> str | None:
        return self._project_name

    @property
    def status(self) -> str:
        return self._status

    async def start(self, working_dir: str, project_name: str = None):
        """Start or switch to a project session."""
        self._working_dir = working_dir
        self._project_name = project_name or Path(working_dir).name
        self._active = True
        self._message_count = 0
        self._status = "idle"
        self._cancel.clear()
        log.info(f"Work mode started: {self._project_name} ({working_dir})")

    async def send(self, user_text: str) -> str:
        """Send the current task to the installed Codex integration."""
        from jarvis.automation.pc_control import controller
        # A previous Stop may have set the event; a new task starts fresh.
        self._cancel.clear()
        job = {"id": uuid.uuid4().hex, "kind": "code", "state": "running", "started": time.time()}
        controller.jobs[job["id"]] = job
        # Register the event so Stop finds it through pc_control.cancel_code().
        controller._cancels[job["id"]] = self._cancel
        self._status = "working"
        try:
            await asyncio.to_thread(controller._code, job, user_text, self._working_dir, self._cancel)
            if self._cancel.is_set():
                job.update(state="cancelled", message="Coding task stopped; existing file changes were preserved.")
                self._status = "cancelled"
                return job["message"]
            job["state"] = "done"
            self._message_count += 1
            self._status = "done"
            return job.get("message", "Codex finished the task.")
        except asyncio.CancelledError:
            # The turn was interrupted. Signal the worker so the Codex process
            # tree is killed instead of continuing to edit files in the dark.
            self._cancel.set()
            job.update(state="cancelled", message="Coding task stopped; existing file changes were preserved.")
            self._status = "cancelled"
            raise
        except Exception:
            # Callers use this prefix to report failure; a swallowed exception
            # used to be summarized as a successful run.
            if self._cancel.is_set():
                job.update(state="cancelled", message="Coding task stopped; existing file changes were preserved.")
                self._status = "cancelled"
                return job["message"]
            job.update(state="error", message="Hit a problem: Codex did not finish the task. Check the task in Codex and your sign-in.")
            self._status = "error"
            return job["message"]
        finally:
            controller._cancels.pop(job["id"], None)
            controller._persist(job)

    async def cancel(self) -> bool:
        """Stop the current Codex run but keep the open project session."""
        if self._status != "working":
            return False
        self._cancel.set()
        return True

    async def stop(self):
        """End the work session and stop any Codex process it owns."""
        self._cancel.set()
        project = self._project_name
        self._active = False
        self._working_dir = None
        self._project_name = None
        self._message_count = 0
        if self._status != "cancelled":
            self._status = "idle"
        log.info(f"Work mode ended for {project}")

    def _save_session(self):
        """Persist session state so it survives restarts."""
        try:
            SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            SESSION_FILE.write_text(json.dumps({
                "project_name": self._project_name,
                "working_dir": self._working_dir,
                "message_count": self._message_count,
            }))
        except Exception as e:
            log.debug(f"Failed to save session: {e}")

    def _clear_session(self):
        """Remove persisted session."""
        try:
            SESSION_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    async def restore(self) -> bool:
        """Restore session from disk after restart. Returns True if restored."""
        try:
            if SESSION_FILE.exists():
                data = json.loads(SESSION_FILE.read_text())
                self._working_dir = data["working_dir"]
                self._project_name = data["project_name"]
                self._message_count = data.get("message_count", 1)  # Assume at least 1 so --continue is used
                self._active = True
                self._status = "idle"
                log.info(f"Restored work session: {self._project_name} ({self._working_dir})")
                return True
        except Exception as e:
            log.debug(f"No session to restore: {e}")
        return False


def is_casual_question(text: str) -> bool:
    """Detect if a message is casual chat vs work-related.

    Casual questions use the configured fast model. Work goes to Codex in the project.
    """
    t = text.lower().strip()

    casual_patterns = [
        "what time", "what's the time", "what day",
        "what's the weather", "weather",
        "how are you", "are you there", "hey jarvis",
        "good morning", "good evening", "good night",
        "thank you", "thanks", "never mind", "nevermind",
        "stop", "cancel", "quit work mode", "exit work mode",
        "go back to chat", "regular mode",
        "how's it going", "what's up",
        "are you still there", "you there", "jarvis",
        "are you doing it", "is it working", "what happened",
        "did you hear me", "hello", "hey",
        "how's that coming", "hows that coming",
        "any update", "status update",
    ]

    # Short greetings/acknowledgments
    if len(t.split()) <= 3 and any(w in t for w in ["ok", "okay", "sure", "yes", "no", "yeah", "nah", "cool"]):
        return True

    return any(p in t for p in casual_patterns)
