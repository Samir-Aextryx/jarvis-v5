"""Local Jarvis notes, stored in the app's SQLite database."""
import asyncio
from jarvis.core.local_notes import local_notes


async def get_recent_notes(count: int = 10) -> list[dict]:
    return await asyncio.to_thread(local_notes.get_recent_notes, count)


async def read_note(title_match: str) -> dict | None:
    return await asyncio.to_thread(local_notes.read_note, title_match)


async def search_local_notes(query: str, count: int = 5) -> list[dict]:
    return await asyncio.to_thread(local_notes.search_notes, query, count)


async def create_local_note(title: str, body: str, folder: str = "Notes") -> bool:
    await asyncio.to_thread(local_notes.create_note, title, body, folder)
    return True


async def get_note_folders() -> list[str]:
    notes = await get_recent_notes(200)
    return sorted({note.get("folder", "Notes") for note in notes} | {"Notes"})
