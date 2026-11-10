"""Bounded background development jobs, with isolated QA and task tracking."""
import asyncio
import logging
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
from fastapi import WebSocket
from jarvis.automation.work_mode import WorkSession
from jarvis.core.qa import QAAgent
from jarvis.core.tracking import SuccessTracker
from jarvis.core.suggestions import suggest_followup
from jarvis.core.diagnostics import report_failure
log = logging.getLogger("jarvis.tasks")
DESKTOP_PATH = Path.home() / "Desktop"

@dataclass
class ClaudeTask:
    id: str
    prompt: str
    status: str = "pending"  # pending, running, completed, failed, cancelled
    working_dir: str = "."
    pid: Optional[int] = None
    result: str = ""
    error: str = ""
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["started_at"] = self.started_at.isoformat() if self.started_at else None
        d["completed_at"] = self.completed_at.isoformat() if self.completed_at else None
        d["elapsed_seconds"] = self.elapsed_seconds
        return d

    @property
    def elapsed_seconds(self) -> float:
        if not self.started_at:
            return 0
        end = self.completed_at or datetime.now()
        return (end - self.started_at).total_seconds()


class ClaudeTaskManager:
    """Manages background Codex tasks."""

    def __init__(self, max_concurrent: int = 3):
        self._tasks: dict[str, ClaudeTask] = {}
        self._spawn_lock = asyncio.Lock()
        self._qa = QAAgent()
        self._tracker = SuccessTracker()
        self._max_concurrent = max_concurrent
        self._sessions: dict[str, WorkSession] = {}
        self._spawned: set[asyncio.Task] = set()
        self._websockets: list[WebSocket] = []  # for push notifications

    def _track(self, task: asyncio.Task) -> None:
        self._spawned.add(task)
        task.add_done_callback(self._spawned.discard)

    def _prune_tasks(self, keep: int = 100) -> None:
        """Bound retained task records; finished entries are only history."""
        if len(self._tasks) <= keep:
            return
        finished = sorted(
            (task for task in self._tasks.values()
             if task.status not in {"pending", "running"}),
            key=lambda task: task.completed_at or datetime.min,
        )
        for task in finished[:max(0, len(self._tasks) - keep)]:
            self._tasks.pop(task.id, None)

    async def shutdown(self) -> None:
        """Cancel background work and stop the Codex processes it owns."""
        for run in tuple(self._spawned):
            run.cancel()
        if self._spawned:
            await asyncio.gather(*tuple(self._spawned), return_exceptions=True)
        for session in tuple(self._sessions.values()):
            try:
                await session.stop()
            except Exception:
                pass
        self._sessions.clear()

    def register_websocket(self, ws: WebSocket):
        if ws not in self._websockets:
            self._websockets.append(ws)

    def unregister_websocket(self, ws: WebSocket):
        if ws in self._websockets:
            self._websockets.remove(ws)

    def connected_websockets(self) -> tuple[WebSocket, ...]:
        return tuple(self._websockets)

    async def _notify(self, message: dict):
        """Push a message to all connected WebSocket clients.

        A client that stops reading must not stall task creation or alerts, so
        every send is bounded and timed-out clients are dropped.
        """
        dead = []
        for ws in tuple(self._websockets):
            try:
                await asyncio.wait_for(ws.send_json(message), timeout=2)
            except Exception:
                report_failure('server:218')
                dead.append(ws)
        for ws in dead:
            self.unregister_websocket(ws)

    async def spawn(self, prompt: str, working_dir: str = ".") -> str:
        """Start a Codex task. Returns task_id without blocking."""
        async with self._spawn_lock:
            active = sum(t.status in {"pending", "running"} for t in self._tasks.values())
            if active >= self._max_concurrent:
                raise RuntimeError(
                    f"Max concurrent tasks ({self._max_concurrent}) reached. "
                    f"Wait for a task to complete or cancel one."
                )

            task_id = str(uuid.uuid4())[:8]
            task = ClaudeTask(
                id=task_id,
                prompt=prompt,
                working_dir=working_dir,
                status="pending",
            )
            self._tasks[task_id] = task
            self._prune_tasks()

        # Fire and forget — the background coroutine updates the task. Keep a
        # reference so shutdown can cancel it and stop its Codex process.
        self._track(asyncio.create_task(self._run_task(task)))
        log.info(f"Spawned task {task_id}: {prompt[:80]}...")

        await self._notify({
            "type": "task_spawned",
            "task_id": task_id,
            "prompt": prompt,
        })

        return task_id

    def _generate_project_name(self, prompt: str) -> str:
        """Generate a kebab-case project folder name from the prompt."""
        import re
        # Extract key words
        words = re.sub(r'[^a-zA-Z0-9\s]', '', prompt.lower()).split()
        # Take first 3-4 meaningful words
        skip = {"a", "the", "an", "me", "build", "create", "make", "for", "with", "and", "to", "of"}
        meaningful = [w for w in words if w not in skip][:4]
        name = "-".join(meaningful) if meaningful else "jarvis-project"
        return name

    async def _run_task(self, task: ClaudeTask):
        """Run a project task through the configured Windows Codex session."""
        if task.status == "cancelled":
            return
        task.status = "running"
        task.started_at = datetime.now()
        session = WorkSession()
        self._sessions[task.id] = session
        try:
            directory = Path(task.working_dir) if task.working_dir and task.working_dir != "." else DESKTOP_PATH / self._generate_project_name(task.prompt)
            directory.mkdir(parents=True, exist_ok=True)
            task.working_dir = str(directory)
            await session.start(str(directory))
            if task.status == "cancelled":
                await session.stop()
            else:
                task.result = await session.send(task.prompt)
                if task.status == "cancelled" or session.status == "cancelled":
                    task.status = "cancelled"
                    task.result = ""
                else:
                    task.status = "completed" if session.status == "done" else "failed"
                    if task.status == "failed":
                        task.error = task.result
        except asyncio.CancelledError:
            task.status = "cancelled"
            task.completed_at = datetime.now()
            raise
        except Exception as exc:
            report_failure('server:278')
            if task.status != "cancelled":
                task.status = "failed"
                task.error = str(exc)
        finally:
            # A finished task must not leave its Codex process editing files.
            try:
                await session.stop()
            except Exception:
                pass
            self._sessions.pop(task.id, None)
        task.completed_at = datetime.now()
        await self._notify({
            "type": "task_complete",
            "task_id": task.id,
            "status": task.status,
            "summary": task.result[:200] if task.result else task.error,
        })
        if task.status == "completed":
            self._track(asyncio.create_task(self._run_qa(task)))

    async def _run_qa(self, task: ClaudeTask, attempt: int = 1):
        """Run QA verification on a completed task, auto-retry on failure."""
        try:
            qa_result = await self._qa.verify(task.prompt, task.result, task.working_dir)
            duration = task.elapsed_seconds

            if qa_result.passed:
                log.info(f"Task {task.id} passed QA: {qa_result.summary}")
                self._tracker.log_task("dev", task.prompt, True, attempt - 1, duration)
                await self._notify({
                    "type": "qa_result",
                    "task_id": task.id,
                    "passed": True,
                    "summary": qa_result.summary,
                })

                # Proactive suggestion after successful task
                suggestion = suggest_followup(
                    task_type="dev",
                    task_description=task.prompt,
                    working_dir=task.working_dir,
                    qa_result=qa_result,
                )
                if suggestion:
                    self._tracker.log_suggestion(task.id, suggestion.text)
                    await self._notify({
                        "type": "suggestion",
                        "task_id": task.id,
                        "text": suggestion.text,
                        "action_type": suggestion.action_type,
                        "action_details": suggestion.action_details,
                    })
            else:
                log.warning(f"Task {task.id} failed QA: {qa_result.issues}")
                if attempt < 3:
                    log.info(f"Auto-retrying task {task.id} (attempt {attempt + 1}/3)")
                    retry_result = await self._qa.auto_retry(
                        task.prompt, qa_result.issues, task.working_dir, attempt,
                    )
                    if retry_result["status"] == "completed":
                        task.result = retry_result["result"]
                        # Re-verify
                        await self._run_qa(task, attempt + 1)
                    else:
                        self._tracker.log_task("dev", task.prompt, False, attempt, duration)
                        await self._notify({
                            "type": "qa_result",
                            "task_id": task.id,
                            "passed": False,
                            "summary": f"Failed after {attempt + 1} attempts: {qa_result.issues}",
                        })
                else:
                    self._tracker.log_task("dev", task.prompt, False, attempt, duration)
                    await self._notify({
                        "type": "qa_result",
                        "task_id": task.id,
                        "passed": False,
                        "summary": f"Failed QA after {attempt} attempts: {qa_result.issues}",
                    })
        except Exception as e:
            report_failure('server:413')
            log.error(f"QA error for task {task.id}: {e}")

    async def get_status(self, task_id: str) -> Optional[ClaudeTask]:
        return self._tasks.get(task_id)

    async def list_tasks(self) -> list[ClaudeTask]:
        return list(self._tasks.values())

    async def get_active_count(self) -> int:
        return sum(1 for t in self._tasks.values() if t.status in ("pending", "running"))

    async def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task or task.status not in ("pending", "running"):
            return False

        # A WorkSession owns the Codex child process; signal it so "stop"
        # actually stops file edits instead of only relabelling the task.
        session = self._sessions.get(task_id)
        if session:
            await session.stop()

        task.status = "cancelled"
        task.completed_at = datetime.now()
        log.info(f"Cancelled task {task_id}")
        await self._notify({
            "type": "task_complete",
            "task_id": task_id,
            "status": "cancelled",
            "summary": "Task cancelled.",
        })
        return True

    def get_active_tasks_summary(self) -> str:
        """Format active tasks for injection into the system prompt."""
        active = [t for t in self._tasks.values() if t.status in ("pending", "running")]
        completed_recent = [
            t for t in self._tasks.values()
            if t.status == "completed"
            and t.completed_at
            and (datetime.now() - t.completed_at).total_seconds() < 300
        ]

        if not active and not completed_recent:
            return "No active or recent tasks."

        lines = []
        for t in active:
            elapsed = f"{t.elapsed_seconds:.0f}s" if t.started_at else "queued"
            lines.append(f"- [{t.id}] RUNNING ({elapsed}): {t.prompt[:100]}")
        for t in completed_recent:
            lines.append(f"- [{t.id}] COMPLETED: {t.prompt[:60]} -> {t.result[:80]}")
        return "\n".join(lines)
