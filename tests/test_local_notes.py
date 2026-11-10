import tempfile
import unittest
from unittest.mock import patch
from jarvis.core.local_notes import LocalNotes
import jarvis.integrations.notes_access as notes_access
import jarvis.server as server
from fastapi.testclient import TestClient


class LocalNotesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.notes = LocalNotes(self.temp.name)

    def test_create_read_and_search_notes(self):
        n1 = self.notes.create_note(title="Project Alpha Idea", body="Use FastAPI and SQLite for local storage.", folder="Work")
        self.assertEqual(n1["title"], "Project Alpha Idea")
        self.assertEqual(n1["folder"], "Work")
        self.assertIn("date", n1)

        # Read by exact title
        read_exact = self.notes.read_note("Project Alpha Idea")
        self.assertIsNotNone(read_exact)
        self.assertEqual(read_exact["id"], n1["id"])

        # Read by case-insensitive partial title
        read_partial = self.notes.read_note("alpha idea")
        self.assertIsNotNone(read_partial)
        self.assertEqual(read_partial["id"], n1["id"])

        # Read by body content
        read_body = self.notes.read_note("SQLite for local")
        self.assertIsNotNone(read_body)
        self.assertEqual(read_body["id"], n1["id"])

        # Search notes
        search_res = self.notes.search_notes("FastAPI")
        self.assertEqual(len(search_res), 1)
        self.assertEqual(search_res[0]["id"], n1["id"])

    def test_update_and_delete_note(self):
        n = self.notes.create_note(title="Shopping List", body="Milk, Eggs, Bread")
        updated = self.notes.update_note(n["id"], body="Milk, Eggs, Bread, Butter")
        self.assertIsNotNone(updated)
        self.assertEqual(updated["body"], "Milk, Eggs, Bread, Butter")

        # Delete
        success = self.notes.delete_note(n["id"])
        self.assertTrue(success)
        self.assertIsNone(self.notes.read_note("Shopping List"))
        self.assertEqual(len(self.notes.list_notes()), 0)

    def test_recent_notes_ordering(self):
        self.notes.create_note(title="Note 1", body="Body 1")
        self.notes.create_note(title="Note 2", body="Body 2")
        self.notes.create_note(title="Note 3", body="Body 3")

        recent = self.notes.get_recent_notes(count=2)
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0]["title"], "Note 3")
        self.assertEqual(recent[1]["title"], "Note 2")

    def test_notes_access_fallback_integration(self):
        import asyncio
        with patch.object(notes_access, "local_notes", self.notes):
            # Create via notes_access
            created = asyncio.run(notes_access.create_local_note("Meeting Notes", "Discuss Q3 goals"))
            self.assertTrue(created)

            # Read via notes_access
            note = asyncio.run(notes_access.read_note("Meeting Notes"))
            self.assertIsNotNone(note)
            self.assertIn("Discuss Q3 goals", note["body"])

            # Recent notes via notes_access
            recent = asyncio.run(notes_access.get_recent_notes(count=5))
            self.assertTrue(any(n["title"] == "Meeting Notes" for n in recent))


class NotesAPITests(unittest.TestCase):
    def test_notes_api_endpoints(self):
        with tempfile.TemporaryDirectory() as root, \
             patch.object(server, "local_notes", LocalNotes(root)), \
             TestClient(server.app) as client:
            headers = {"Authorization": "Bearer " + server.JARVIS_AUTH_TOKEN}

            # Unauthorized
            res = client.post("/api/notes", json={"title": "Unauthorized", "body": "test"})
            self.assertEqual(res.status_code, 401)

            # Create note
            res = client.post("/api/notes", headers=headers, json={"title": "Client Meeting", "body": "Prepare pitch deck"})
            self.assertEqual(res.status_code, 200)
            note_data = res.json()["note"]
            self.assertEqual(note_data["title"], "Client Meeting")

            # List notes
            res = client.get("/api/notes", headers=headers)
            self.assertEqual(res.status_code, 200)
            notes_list = res.json()["notes"]
            self.assertEqual(len(notes_list), 1)

            # Search notes
            res = client.get("/api/notes?query=pitch", headers=headers)
            self.assertEqual(res.status_code, 200)
            search_list = res.json()["notes"]
            self.assertEqual(len(search_list), 1)

            # Delete note
            res = client.delete(f"/api/notes/{note_data['id']}", headers=headers)
            self.assertEqual(res.status_code, 200)

            # Confirm empty
            res = client.get("/api/notes", headers=headers)
            self.assertEqual(len(res.json()["notes"]), 0)


if __name__ == "__main__":
    unittest.main()
