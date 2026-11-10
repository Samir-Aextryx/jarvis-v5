"""Jarvis's own calendar. Local persistence; no Google connection required."""
from contextlib import closing
from datetime import date, datetime, time, timedelta
import sqlite3
import threading
import uuid
from zoneinfo import ZoneInfo
from jarvis.integrations.calendar_workflows import ZONE, event_fields, moment
from jarvis.core.runtime_paths import DATA_ROOT


class LocalCalendar:
    def __init__(self, root=DATA_ROOT):
        from pathlib import Path
        self.path = Path(root) / 'data/jarvis_calendar.db'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with closing(self.connect()) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
                all_day INTEGER NOT NULL, description TEXT NOT NULL, location TEXT NOT NULL,
                starts REAL NOT NULL, ends REAL NOT NULL, version INTEGER NOT NULL DEFAULT 1)''')
            conn.execute('CREATE INDEX IF NOT EXISTS events_dates ON events(starts,ends)')
            conn.commit()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        return conn

    @staticmethod
    def public(row):
        result = dict(row)
        result.pop('starts', None)
        result.pop('ends', None)
        result['all_day'] = bool(result['all_day'])
        return result

    @staticmethod
    def boundary(value):
        if isinstance(value, str) and len(value) == 10:
            return datetime.combine(date.fromisoformat(value), time(), ZoneInfo(ZONE))
        return moment(value)

    def list_events(self, start, end):
        left, right = self.boundary(start), self.boundary(end)
        if right <= left or (right - left).days > 366:
            raise ValueError('Choose a calendar range of at most one year, with the end after the start.')
        with self.lock, closing(self.connect()) as conn:
            rows = conn.execute('SELECT * FROM events WHERE starts < ? AND ends > ? ORDER BY starts,title',
                                (right.timestamp(), left.timestamp()))
            return [self.public(row) for row in rows]

    def save(self, data, event_id=None, expected_version=None):
        fields = event_fields(dict(data, operation='create'))
        if len(fields['summary']) > 200:
            raise ValueError('Use an event title of at most 200 characters.')
        all_day = bool(data.get('all_day'))
        key = 'date' if all_day else 'dateTime'
        start, end = fields['start'][key], fields['end'][key]
        starts, ends = self.boundary(start).timestamp(), self.boundary(end).timestamp()
        if ends <= starts:
            raise ValueError('The event must end after it starts, including across clock changes.')
        with self.lock, closing(self.connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            version = 1
            if event_id:
                row = conn.execute('SELECT version FROM events WHERE id=?', (event_id,)).fetchone()
                if not row or expected_version != row['version']:
                    raise ValueError('This event changed or was removed. Refresh before editing it.')
                version = row['version'] + 1
            else:
                event_id = uuid.uuid4().hex
            conn.execute('''INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,start=excluded.start,end=excluded.end,all_day=excluded.all_day,
                description=excluded.description,location=excluded.location,starts=excluded.starts,
                ends=excluded.ends,version=excluded.version''',
                (event_id, fields['summary'], start, end, all_day, fields.get('description',''), fields.get('location',''),
                 starts, ends, version))
            conn.commit()
            return self.public(conn.execute('SELECT * FROM events WHERE id=?', (event_id,)).fetchone())

    def delete(self, event_id, expected_version):
        with self.lock, closing(self.connect()) as conn:
            if conn.execute('DELETE FROM events WHERE id=? AND version=?', (event_id, expected_version)).rowcount != 1:
                raise ValueError('This event changed or was removed. Refresh before deleting it.')
            conn.commit()

    def upcoming(self, days=7):
        now = datetime.now(ZoneInfo(ZONE))
        return self.list_events(now.isoformat(), (now + timedelta(days=days)).isoformat())


local_calendar = LocalCalendar()
