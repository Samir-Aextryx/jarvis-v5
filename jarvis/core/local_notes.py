"""Jarvis's own local notes store, persisted in SQLite."""
import json
import logging
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path

from jarvis.core.runtime_paths import DATA_ROOT

log = logging.getLogger("jarvis.local_notes")


class LocalNotes:
    def __init__(self, root=DATA_ROOT):
        self.path = Path(root) / "data/jarvis_notes.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with closing(self.connect()) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    folder TEXT NOT NULL DEFAULT 'Notes',
                    tags TEXT NOT NULL DEFAULT '[]',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated_at DESC)")
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                    title, body, folder,
                    content='notes', content_rowid='rowid'
                )
            """)
            conn.commit()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @staticmethod
    def _format_date(ts: float) -> str:
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(ts)

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["date"] = self._format_date(d.get("created_at", time.time()))
        try:
            d["tags"] = json.loads(d.get("tags", "[]"))
        except Exception:
            d["tags"] = []
        return d

    def create_note(self, title: str, body: str, folder: str = "Notes", tags: list = None) -> dict:
        """Create a new note. Returns note dict."""
        note_id = uuid.uuid4().hex
        clean_title = (title or "Untitled Note").strip()[:300]
        clean_body = (body or "").strip()
        clean_folder = (folder or "Notes").strip()[:100]
        tags_json = json.dumps(tags or [])
        now = time.time()

        with self.lock, closing(self.connect()) as conn:
            cur = conn.execute(
                """INSERT INTO notes (id, title, body, folder, tags, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (note_id, clean_title, clean_body, clean_folder, tags_json, now, now),
            )
            rowid = cur.lastrowid
            try:
                conn.execute(
                    "INSERT INTO notes_fts (rowid, title, body, folder) VALUES (?, ?, ?, ?)",
                    (rowid, clean_title, clean_body, clean_folder),
                )
            except Exception as e:
                log.debug(f"FTS insert notice: {e}")
            conn.commit()
            row = conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
            log.info(f"Created local note '{clean_title}' (id={note_id})")
            return self._row_to_dict(row)

    def get_recent_notes(self, count: int = 10) -> list[dict]:
        """Get most recent notes ordered by update time."""
        with self.lock, closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM notes ORDER BY updated_at DESC, rowid DESC LIMIT ?",
                (max(1, count),),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def read_note(self, title_match: str) -> dict | None:
        """Read a note by title (case-insensitive partial match) or ID."""
        if not title_match or not title_match.strip():
            return None
        target = title_match.strip()

        with self.lock, closing(self.connect()) as conn:
            # 1. Exact ID match
            row = conn.execute("SELECT * FROM notes WHERE id=?", (target,)).fetchone()
            if row:
                return self._row_to_dict(row)

            # 2. Case-insensitive title match
            row = conn.execute(
                "SELECT * FROM notes WHERE LOWER(title) = LOWER(?) ORDER BY updated_at DESC, rowid DESC LIMIT 1",
                (target,),
            ).fetchone()
            if row:
                return self._row_to_dict(row)

            # 3. Partial title match
            row = conn.execute(
                "SELECT * FROM notes WHERE LOWER(title) LIKE LOWER(?) ORDER BY updated_at DESC, rowid DESC LIMIT 1",
                (f"%{target}%",),
            ).fetchone()
            if row:
                return self._row_to_dict(row)

            # 4. Partial body match
            row = conn.execute(
                "SELECT * FROM notes WHERE LOWER(body) LIKE LOWER(?) ORDER BY updated_at DESC, rowid DESC LIMIT 1",
                (f"%{target}%",),
            ).fetchone()
            if row:
                return self._row_to_dict(row)

            return None

    def search_notes(self, query: str, count: int = 10) -> list[dict]:
        """Search notes by query in title or body."""
        if not query or not query.strip():
            return []
        cleaned = query.strip()
        words = [w for w in cleaned.replace("'", "").replace('"', "").split() if len(w) > 1]
        fts_query = " OR ".join(words[:5]) if words else ""

        with self.lock, closing(self.connect()) as conn:
            if fts_query:
                try:
                    rows = conn.execute("""
                        SELECT n.* FROM notes_fts f
                        JOIN notes n ON f.rowid = n.rowid
                        WHERE notes_fts MATCH ?
                        ORDER BY rank LIMIT ?
                    """, (fts_query, count)).fetchall()
                    if rows:
                        return [self._row_to_dict(r) for r in rows]
                except Exception:
                    pass

            # Fallback to LIKE
            rows = conn.execute("""
                SELECT * FROM notes
                WHERE LOWER(title) LIKE LOWER(?) OR LOWER(body) LIKE LOWER(?)
                ORDER BY updated_at DESC, rowid DESC LIMIT ?
            """, (f"%{cleaned}%", f"%{cleaned}%", count)).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def update_note(self, note_id: str, title: str = None, body: str = None, folder: str = None) -> dict | None:
        """Update an existing note."""
        with self.lock, closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
            if not row:
                return None
            new_title = (title if title is not None else row["title"]).strip()[:300]
            new_body = (body if body is not None else row["body"]).strip()
            new_folder = (folder if folder is not None else row["folder"]).strip()[:100]
            now = time.time()
            conn.execute(
                """UPDATE notes SET title=?, body=?, folder=?, updated_at=? WHERE id=?""",
                (new_title, new_body, new_folder, now, note_id),
            )
            # Update FTS
            try:
                row_with_rowid = conn.execute("SELECT rowid FROM notes WHERE id=?", (note_id,)).fetchone()
                if row_with_rowid:
                    conn.execute(
                        "UPDATE notes_fts SET title=?, body=?, folder=? WHERE rowid=?",
                        (new_title, new_body, new_folder, row_with_rowid["rowid"]),
                    )
            except Exception:
                pass
            conn.commit()
            updated_row = conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
            return self._row_to_dict(updated_row)

    def delete_note(self, note_id: str) -> bool:
        """Delete note by ID."""
        with self.lock, closing(self.connect()) as conn:
            row = conn.execute("SELECT rowid FROM notes WHERE id=?", (note_id,)).fetchone()
            if not row:
                return False
            conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
            try:
                conn.execute("DELETE FROM notes_fts WHERE rowid=?", (row["rowid"],))
            except Exception:
                pass
            conn.commit()
            log.info(f"Deleted local note {note_id}")
            return True

    def list_notes(self) -> list[dict]:
        """List all notes ordered by updated_at DESC."""
        with self.lock, closing(self.connect()) as conn:
            rows = conn.execute("SELECT * FROM notes ORDER BY updated_at DESC, rowid DESC").fetchall()
            return [self._row_to_dict(r) for r in rows]


local_notes = LocalNotes()
