import asyncio
import unittest
from unittest.mock import patch, AsyncMock
import jarvis.integrations.atlassian_access as atlassian_access
import jarvis.server as server


class AtlassianAccessSecurityTests(unittest.TestCase):
    def test_strict_read_only_safety_policy(self):
        """Verify that replying to or modifying tickets is impossible and strictly forbidden."""
        self.assertFalse(atlassian_access.can_reply_to_tickets())

        with self.assertRaises(PermissionError):
            atlassian_access.reply_to_ticket("PROJ-101", "Fixed in main")

        with self.assertRaises(PermissionError):
            atlassian_access.comment_on_ticket("PROJ-101", "Working on this")

        with self.assertRaises(PermissionError):
            atlassian_access.update_ticket("PROJ-101", status="Closed")


class AtlassianAccessFormattingTests(unittest.TestCase):
    def test_format_tickets_for_voice_single(self):
        tickets = [{
            "id": "ENG-42",
            "title": "Fix memory leak in websocket stream",
            "status": "In Progress",
            "priority": "High",
        }]
        with patch.object(atlassian_access, "is_twg_available", return_value=True), \
             patch.object(atlassian_access, "is_authenticated", return_value=True):
            speech = atlassian_access.format_tickets_for_voice(tickets)
            self.assertIn("one active ticket", speech)
            self.assertIn("ENG-42", speech)
            self.assertIn("Fix memory leak", speech)
            self.assertIn("In Progress", speech)

    def test_format_tickets_for_voice_multiple_and_confluence(self):
        tickets = [
            {"id": "ENG-101", "title": "Upgrade LLM backend", "status": "In Review"},
            {"id": "ENG-102", "title": "Add calendar sync", "status": "Done"},
            {"id": "ENG-103", "title": "Prepare v5 release", "status": "To Do"},
        ]
        pages = [
            {"id": "p1", "title": "Release Notes 5.0", "space": "Product"},
            {"id": "p2", "title": "Architecture Blueprint", "space": "Engineering"},
        ]
        with patch.object(atlassian_access, "is_twg_available", return_value=True), \
             patch.object(atlassian_access, "is_authenticated", return_value=True):
            speech = atlassian_access.format_tickets_for_voice(tickets, pages)
            self.assertIn("3 active tickets", speech)
            self.assertIn("ENG-101", speech)
            self.assertIn("Release Notes 5.0", speech)

    def test_format_tickets_for_voice_unauthenticated(self):
        with patch.object(atlassian_access, "is_twg_available", return_value=True), \
             patch.object(atlassian_access, "is_authenticated", return_value=False):
            speech = atlassian_access.format_tickets_for_voice([])
            self.assertIn("twg login", speech)

    def test_format_tickets_for_context(self):
        tickets = [{"id": "PROJ-1", "title": "Implement feature", "status": "Open", "priority": "High"}]
        pages = [{"title": "Spec Document", "space": "Design"}]
        context = atlassian_access.format_tickets_for_context(tickets, pages)
        self.assertIn("PROJ-1", context)
        self.assertIn("Spec Document", context)
        self.assertIn("STRICTLY READ-ONLY", context)


class WhatsNewVoiceDetectionTests(unittest.TestCase):
    def test_detect_action_fast_whats_new(self):
        triggers = [
            "what's new",
            "whats new",
            "what is new",
            "any updates",
            "was gibt's neues",
            "was gibts neues",
            "check tickets",
            "show tickets",
            "my tickets",
        ]
        for phrase in triggers:
            res = server.detect_action_fast(phrase)
            self.assertIsNotNone(res, f"Failed to match: {phrase}")
            self.assertEqual(res.get("action"), "check_tickets", f"Wrong action for: {phrase}")


class ServerTicketsLookupTests(unittest.IsolatedAsyncioTestCase):
    async def test_do_tickets_lookup(self):
        mock_tickets = [{"id": "ENG-500", "title": "Setup CI pipeline", "status": "In Progress"}]
        mock_pages = [{"title": "CI/CD Guidelines", "space": "DevOps"}]

        with patch("jarvis.integrations.atlassian_access.get_recent_tickets", new=AsyncMock(return_value=mock_tickets)), \
             patch("jarvis.integrations.atlassian_access.get_confluence_updates", new=AsyncMock(return_value=mock_pages)), \
             patch("jarvis.integrations.atlassian_access.is_twg_available", return_value=True), \
             patch("jarvis.integrations.atlassian_access.is_authenticated", return_value=True):
            res = await server._do_tickets_lookup()
            self.assertIn("ENG-500", res)
            self.assertIn("CI/CD Guidelines", res)
            self.assertIn("ENG-500", server._ctx_cache.get("tickets", ""))


if __name__ == "__main__":
    unittest.main()
