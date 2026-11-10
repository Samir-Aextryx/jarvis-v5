import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from jarvis.automation.autonomous_tasks import (
    AUTONOMOUS_EMAIL_TIMEOUT_SECONDS,
    AUTONOMOUS_TASK_TIMEOUT_SECONDS,
    AutonomousTasks,
)


class AutonomousDeadlineTests(unittest.IsolatedAsyncioTestCase):
    def test_multi_step_jobs_keep_the_documented_five_minute_ceiling(self):
        self.assertEqual(AUTONOMOUS_TASK_TIMEOUT_SECONDS, 300)
        self.assertEqual(AUTONOMOUS_EMAIL_TIMEOUT_SECONDS, 300)

    async def test_generic_timeout_marks_active_step_interrupted(self):
        with tempfile.TemporaryDirectory() as root:
            runner = AutonomousTasks(root)
            runner.planner.plan_next = AsyncMock(return_value={
                'complete': False,
                'message': '',
                'steps': [{'action': 'use_app', 'target': 'Example', 'content': '',
                           'recipient': '', 'subject': ''}],
            })

            async def slow_execute(*_args, **_kwargs):
                await asyncio.sleep(1)

            runner.planner.execute = slow_execute
            with patch('jarvis.automation.autonomous_tasks.AUTONOMOUS_TASK_TIMEOUT_SECONDS', .01):
                result = await runner.run('Do a slow app task')

            self.assertIn('time limit', result)
            self.assertEqual(runner.job['state'], 'needs_attention')
            self.assertEqual(runner.job['steps'][0]['state'], 'interrupted')

    async def test_email_task_uses_longer_deadline_and_clear_timeout_message(self):
        with tempfile.TemporaryDirectory() as root:
            runner = AutonomousTasks(root)

            async def slow_plan(*_args, **_kwargs):
                await asyncio.sleep(1)

            runner.planner.plan_next = slow_plan
            with patch('jarvis.automation.autonomous_tasks.AUTONOMOUS_EMAIL_TIMEOUT_SECONDS', .01):
                result = await runner.run('Read my Gmail messages and summarize them')

            self.assertIn('email task took too long', result.lower())
            self.assertEqual(runner.job['state'], 'needs_attention')


if __name__ == '__main__':
    unittest.main()
