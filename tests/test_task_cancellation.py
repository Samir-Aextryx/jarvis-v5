"""Stop must actually reach background coding work, not just relabel it."""
import asyncio
import tempfile
import threading
import unittest
from unittest.mock import patch

from jarvis.core.tasks import ClaudeTask, ClaudeTaskManager


class FakeSession:
    def __init__(self):
        self.status = "done"
        self.started = False
        self.cancelled = threading.Event()

    async def start(self, working_dir):
        self.started = True

    async def send(self, prompt):
        await asyncio.sleep(0.2)
        if self.cancelled.is_set():
            self.status = "cancelled"
            return "Coding task stopped; existing file changes were preserved."
        return "ok"

    async def stop(self):
        self.cancelled.set()


class TaskCancelTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_signals_the_codex_session_and_keeps_the_status(self):
        manager = ClaudeTaskManager()
        task = ClaudeTask(id="task-1", prompt="build something", working_dir=".")
        manager._tasks[task.id] = task
        session = FakeSession()
        with patch("jarvis.core.tasks.WorkSession", return_value=session):
            running = asyncio.create_task(manager._run_task(task))
            for _ in range(20):
                await asyncio.sleep(0.01)
                if session.started:
                    break
            self.assertTrue(await manager.cancel(task.id))
            await running
        self.assertTrue(session.cancelled.is_set())
        self.assertEqual(task.status, "cancelled")


class PcControlCancelTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_code_signals_the_worker_event(self):
        from jarvis.automation.pc_control import PCControl
        with tempfile.TemporaryDirectory() as folder:
            control = PCControl(root=folder)
            seen = {}

            def worker(job, prompt, cancel=None):
                seen["cancel"] = cancel
                cancel.wait(2)

            control._start("code", worker, "prompt")
            for _ in range(50):
                await asyncio.sleep(0.01)
                if "cancel" in seen:
                    break
            self.assertIsInstance(seen.get("cancel"), threading.Event)
            self.assertTrue(control.cancel_code())
            await asyncio.gather(*tuple(control.tasks), return_exceptions=True)
            self.assertEqual(control.jobs[next(iter(control.jobs))]["state"], "cancelled")


if __name__ == "__main__":
    unittest.main()
