import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import jarvis.server as server


class MeetingContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_meeting_question_gets_fresh_calendar_details_and_matching_notes(self):
        calendar = SimpleNamespace(upcoming=lambda days: [{
            'start':'2026-09-25T10:00:00+02:00', 'title':'Project check-in',
            'location':'Room 4', 'description':'Review the launch plan and open questions.'}])
        notes = SimpleNamespace(search_notes=lambda query, count: [{
            'title':'Project check-in', 'body':'Samir agreed to review the Windows voice flow.'}])
        memory = SimpleNamespace(context=lambda query: '')
        response = SimpleNamespace(content=[SimpleNamespace(text='Your check-in is at ten in Room 4.')],
                                   usage=SimpleNamespace(input_tokens=0, output_tokens=0))
        client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=response)))
        task_manager = SimpleNamespace(get_active_tasks_summary=lambda: 'No active tasks.')
        with patch.object(server, 'local_calendar', calendar), \
             patch.object(server, 'local_notes', notes), \
             patch.object(server, 'personal_memory', memory), \
             patch.object(server, 'build_memory_context', return_value=''), \
             patch.object(server, '_append_usage_entry'):
            await server.generate_response('What is the next project meeting about?', client, task_manager, [], [])
        system = client.messages.create.call_args.kwargs['system']
        self.assertIn('2026-09-25T10:00:00+02:00: Project check-in', system)
        self.assertIn('Location: Room 4', system)
        self.assertIn('Review the launch plan', system)
        self.assertIn('RELEVANT LOCAL NOTES', system)
        self.assertIn('review the Windows voice flow', system)

    async def test_non_calendar_question_does_not_read_calendar(self):
        calendar = SimpleNamespace(upcoming=AsyncMock(side_effect=AssertionError('Should not query calendar')))
        response = SimpleNamespace(content=[SimpleNamespace(text='Hello.')],
                                   usage=SimpleNamespace(input_tokens=0, output_tokens=0))
        client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=response)))
        task_manager = SimpleNamespace(get_active_tasks_summary=lambda: '')
        with patch.object(server, 'local_calendar', calendar), \
             patch.object(server, 'local_notes', SimpleNamespace(search_notes=lambda query, count: [])), \
             patch.object(server, 'personal_memory', SimpleNamespace(context=lambda query: '')), \
             patch.object(server, 'build_memory_context', return_value=''), \
             patch.object(server, '_append_usage_entry'):
            await server.generate_response('Tell me a quick joke.', client, task_manager, [], [])
        calendar.upcoming.assert_not_awaited()

