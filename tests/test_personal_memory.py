import json
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from jarvis.core.personal_memory import PersonalMemory


class PersonalMemoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.memory = PersonalMemory(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_markdown_and_restart_context(self):
        self.memory.upsert("work_start", "routine", "Beginnt jeden Morgen um acht mit der Arbeit.", "Ich beginne jeden Morgen um acht.")
        self.memory.record_turn("Wie ist mein Tagesplan?")
        self.memory.record_turn("Wie ist mein Tagesplan?")
        text = self.memory.path.read_text(encoding="utf-8")
        self.assertIn("2×: Wie ist mein Tagesplan?", text)
        self.assertIn("Beginnt jeden Morgen", text)
        loaded = PersonalMemory(self.temp.name)
        self.assertIn("Beginnt jeden Morgen", loaded.context("Arbeit"))
        self.assertIn("Wiederkehrende Frage", loaded.context("Tagesplan"))
        self.assertIn("Wie ist mein Tagesplan?", loaded.context("Was habe ich zuletzt gefragt?"))

    def test_new_correction_wins_even_if_older_request_finishes_later(self):
        self.memory.upsert("home", "fact", "Wohnt in Zürich", "Zürich", timestamp=100)
        self.memory.upsert("home", "fact", "Wohnt in Bern", "Bern", timestamp=200)
        self.memory.upsert("home", "fact", "Wohnt in Zürich", "Zürich", timestamp=150)
        self.assertEqual(len(self.memory.facts()), 1)
        self.assertEqual(self.memory.facts()[0]["content"], "Wohnt in Bern")

    def test_keys_are_not_written_to_markdown(self):
        self.memory.record_turn("Mein API key ist sk-proj-abcdefghijklmnop12345")
        self.memory.record_turn("Mein Passwort ist very-secret")
        text = self.memory.path.read_text(encoding="utf-8")
        self.assertNotIn("abcdefghijklmnop", text)
        self.assertNotIn("very-secret", text)

    def test_routine_observations_need_three_distinct_days(self):
        now = datetime.now().replace(hour=9)
        for _ in range(4): self.memory.record_turn("Öffne Outlook", "Outlook", now.timestamp())
        self.assertNotIn("Unbestätigte Beobachtung", self.memory.context("Outlook"))
        for days in [1,2]: self.memory.record_turn("Öffne Outlook", "Outlook", (now-timedelta(days=days)).timestamp())
        self.assertIn("Unbestätigte Beobachtung", self.memory.context("Outlook"))
        self.assertEqual(self.memory.facts(), [])

    async def test_learning_requires_evidence_and_persists_routine(self):
        response = SimpleNamespace(content=[SimpleNamespace(text=json.dumps([
            {"key":"morning", "kind":"routine", "content":"Trinkt morgens Tee", "evidence":"Ich trinke morgens Tee"},
            {"key":"job", "kind":"fact", "content":"Ist Arzt", "evidence":"Ich bin Arzt"},
        ]))])
        client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=response)))
        await self.memory.learn("Ich trinke morgens Tee.", client, time.time())
        self.assertEqual(len(self.memory.facts()),1)
        self.assertEqual(self.memory.facts()[0]["kind"],"routine")
        self.assertNotIn("Ist Arzt",self.memory.path.read_text(encoding="utf-8"))
