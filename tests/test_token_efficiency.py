import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from jarvis.core.personal_memory import PersonalMemory
from jarvis.voice.voice_context import recent_turns


class TokenEfficiencyTests(unittest.IsolatedAsyncioTestCase):
    def test_history_budget_preserves_current_request_and_original_history(self):
        history = [{'role': 'user' if index % 2 == 0 else 'assistant',
                    'content': str(index) * 2400} for index in range(6)]
        selected = recent_turns(history, 'Continue')
        self.assertLessEqual(sum(len(row['content']) for row in selected), 3800)
        self.assertEqual([row['role'] for row in selected[:-1]], [row['role'] for row in history[-4:]])
        self.assertTrue(all(len(row['content']) <= 800 for row in selected[:-1]))
        self.assertTrue(all(row['content'].endswith(history[-4 + i]['content'][-800:]) for i, row in enumerate(selected[:-1])))
        self.assertEqual(selected[-1], {'role': 'user', 'content': 'Continue'})
        self.assertEqual(len(history), 6)

    def test_long_current_request_is_never_truncated_or_duplicated(self):
        request = 'detail ' * 1200
        current = {'role': 'user', 'content': request}
        self.assertEqual(recent_turns([current], request), [current])

    def test_assistant_text_does_not_replace_current_user_request(self):
        selected = recent_turns([{'role': 'assistant', 'content': 'Hello'}], 'Hello')
        self.assertEqual([row['role'] for row in selected], ['assistant', 'user'])

    async def test_general_questions_skip_memory_api_but_personal_statements_do_not(self):
        client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(
            return_value=SimpleNamespace(content=[SimpleNamespace(text='[]')]))))
        with tempfile.TemporaryDirectory() as root:
            memory = PersonalMemory(root)
            for text in ['Wie funktioniert ein Elektromotor?', 'What is the capital of France?',
                         'Explain Python generators.']:
                await memory.learn(text, client, time.time())
            client.messages.create.assert_not_awaited()
            for text in ['Ich wohne jetzt in Bern.', 'My favourite drink is tea.',
                         'Merke dir: Geburtstag am 12. Mai.']:
                await memory.learn(text, client, time.time())
            self.assertEqual(client.messages.create.await_count, 3)

    async def test_memory_learning_skips_ephemeral_commands_and_learns_durable_routines(self):
        client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(
            return_value=SimpleNamespace(content=[SimpleNamespace(text='[]')]))))
        with tempfile.TemporaryDirectory() as root:
            memory = PersonalMemory(root)
            for text in ['I need to open Outlook because I have a call.',
                         'Ich muss später noch eine E-Mail beantworten.',
                         'I have to finish this task today.']:
                await memory.learn(text, client, time.time())
            client.messages.create.assert_not_awaited()
            await memory.learn('Ich trinke morgens Tee.', client, time.time())
            client.messages.create.assert_awaited_once()

    def test_memory_context_does_not_send_irrelevant_facts_and_limits_full_recall(self):
        with tempfile.TemporaryDirectory() as root:
            memory = PersonalMemory(root)
            memory.upsert('city', 'fact', 'Lives in Bern.', 'user', 10)
            memory.upsert('drink', 'preference', 'Prefers tea.', 'user', 20)
            self.assertNotIn('Bern', memory.context('How do I open Outlook?'))
            self.assertIn('tea', memory.context('What tea do I prefer?'))
            self.assertLessEqual(len(memory.context('What do you remember about me?')), 3800)
