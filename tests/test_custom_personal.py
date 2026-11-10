import asyncio
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from jarvis.core.personal_memory import PersonalMemory
from jarvis.core.local_calendar import LocalCalendar
from jarvis.core.local_calendar_workflows import run_local_calendar, personal_panel_request
from jarvis.automation.local_pc import LocalPC, is_pc_request

EVENT = dict(title='Dentist',start='2026-09-20T10:00',end='2026-09-20T11:00',all_day=False,description='Bring documents',location='Zurich')


class CustomMemoryTests(unittest.TestCase):
    def test_named_routine_can_be_created_and_updated(self):
        first = self.memory.save_routine('Morning', 'Open Chrome')
        second = self.memory.save_routine('Morning', 'Open Outlook')
        self.assertEqual(first['key'], second['key'])
        self.assertTrue(second['manual'])
        self.assertEqual(len(self.memory.facts()), 1)
        self.assertEqual(self.memory.facts()[0]['content'], 'Open Outlook')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.memory=PersonalMemory(self.temp.name)

    def test_edit_reload_export_and_relevant_context(self):
        row=self.memory.edit_fact('I prefer morning meetings.','preference')
        edited=self.memory.edit_fact('I prefer afternoon meetings.','preference',row['key'],row['updated'])
        loaded=PersonalMemory(self.temp.name)
        self.assertTrue(loaded.facts()[0]['manual'])
        self.assertIn('afternoon', loaded.context('meetings'))
        self.assertNotIn('morning', loaded.path.read_text(encoding='utf-8'))
        self.assertGreater(edited['updated'],row['updated'])

    def test_manual_edits_protected_from_automatic_learning(self):
        self.memory.upsert('work','routine','Starts at nine','old')
        row=self.memory.facts()[0]
        self.memory.edit_fact('Starts at ten','routine',row['key'],row['updated'])
        self.memory.upsert('work','routine','Starts at nine','background extractor',time.time()+10)
        self.assertEqual(self.memory.facts()[0]['content'],'Starts at ten')

    def test_deletion_blocks_stale_learning_and_removes_export(self):
        self.memory.upsert('work','routine','Starts at nine','old')
        row=self.memory.facts()[0]
        self.memory.delete_fact('work',row['updated'])
        self.memory.upsert('work','routine','Starts at nine','stale',row['updated'])
        self.assertEqual(PersonalMemory(self.temp.name).facts(),[])
        self.assertNotIn('Starts at nine',self.memory.path.read_text(encoding='utf-8'))

    def test_conflicts_empty_invalid_and_secrets_rejected(self):
        row=self.memory.edit_fact('First')
        edited=self.memory.edit_fact('Second',key=row['key'],expected_updated=row['updated'])
        for fn in [lambda:self.memory.edit_fact('Stale',key=row['key'],expected_updated=row['updated']),
                   lambda:self.memory.delete_fact(row['key'],row['updated']),
                   lambda:self.memory.edit_fact(''),lambda:self.memory.edit_fact('x'*4001),
                   lambda:self.memory.edit_fact('API key is sk-proj-abcdefghijklmnop12345')]:
            with self.assertRaises(ValueError):fn()
        self.assertEqual(self.memory.facts()[0]['content'],edited['content'])

    def test_old_database_migration_preserves_facts(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'data').mkdir()
            with closing(sqlite3.connect(Path(root,'data/personal_memory.db'))) as conn:
                conn.execute('CREATE TABLE facts(key TEXT PRIMARY KEY,kind TEXT,content TEXT,source TEXT,updated REAL)')
                conn.execute('INSERT INTO facts VALUES(?,?,?,?,?)',('old','fact','Existing memory','user',10))
                conn.commit()
            loaded=PersonalMemory(root)
            self.assertEqual(loaded.facts()[0]['content'],'Existing memory')
            loaded.edit_fact('Edited memory',key='old',expected_updated=10)
            self.assertIn('Edited memory',loaded.path.read_text(encoding='utf-8'))


class LocalCalendarTests(unittest.IsolatedAsyncioTestCase):
    def test_clock_change_cannot_reverse_real_time(self):
        with self.assertRaises(ValueError):
            self.calendar.save(dict(EVENT,start='2026-10-25T02:15:00+01:00',end='2026-10-25T02:45:00+02:00'))

    async def test_negated_deletion_preserves_event(self):
        self.calendar.save(EVENT)
        result = await run_local_calendar('Delete the calendar event Dentist, do not delete it yet',self.calendar,
            dict(operation='delete',query='Dentist',window_start='2026-09-20',window_end='2026-09-21'))
        self.assertFalse(result['ok'])
        self.assertEqual(len(self.calendar.list_events('2026-09-20','2026-09-21')),1)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.calendar=LocalCalendar(self.temp.name)

    def test_create_edit_delete_reload_and_overlap(self):
        row=self.calendar.save(EVENT)
        loaded=LocalCalendar(self.temp.name)
        rows=loaded.list_events('2026-09-20T10:30','2026-09-20T10:45')
        self.assertEqual(rows[0]['id'],row['id'])
        edited=loaded.save(dict(EVENT,title='Dentist visit'),row['id'],row['version'])
        self.assertEqual(edited['version'],2)
        self.assertEqual(edited['start'],'2026-09-20T10:00:00+02:00')
        with self.assertRaises(ValueError):loaded.save(EVENT,row['id'],row['version'])
        with self.assertRaises(ValueError):loaded.delete(row['id'],row['version'])
        loaded.delete(edited['id'],edited['version'])
        self.assertEqual(self.calendar.list_events('2026-09-01','2026-10-01'),[])

    def test_all_day_exclusive_end_and_cross_month_event(self):
        self.calendar.save(dict(EVENT,all_day=True,start='2026-09-30',end='2026-10-02'))
        self.assertEqual(len(self.calendar.list_events('2026-10-01','2026-10-02')),1)
        self.assertEqual(len(self.calendar.list_events('2026-10-02','2026-10-03')),0)

    def test_bad_dates_dst_and_empty_title_do_not_write(self):
        for data in [dict(EVENT,end='2026-09-20T09:00'),dict(EVENT,title=''),
                     dict(EVENT,start='2026-03-29T02:30'),dict(EVENT,start='not-a-date'),
                     dict(EVENT,start='2026-10-25T02:30',end='2026-10-25T03:30')]:
            with self.assertRaises(ValueError):self.calendar.save(data)
        self.assertEqual(self.calendar.list_events('2026-01-01','2027-01-01'),[])

    async def test_voice_create_read_update_and_delete_without_google(self):
        created=await run_local_calendar('Create a calendar event Dentist',self.calendar,dict(EVENT,operation='create'))
        self.assertTrue(created['ok'],created)
        search=dict(operation='read',query='Dentist',window_start='2026-09-20',window_end='2026-09-21')
        read=await run_local_calendar('Read my calendar',self.calendar,search)
        self.assertIn('Bring documents',read['message'])
        updated=await run_local_calendar('Move the calendar event Dentist',self.calendar,dict(EVENT,**dict(search,operation='update'),title='',description='',location='',start='2026-09-21T10:00',end='2026-09-21T11:00'))
        self.assertTrue(updated['ok'],updated)
        row=self.calendar.list_events('2026-09-21','2026-09-22')[0]
        self.assertEqual(row['description'],'Bring documents')
        deleted=await run_local_calendar('Delete the calendar event Dentist',self.calendar,dict(search,operation='delete',window_start='2026-09-21',window_end='2026-09-22'))
        self.assertTrue(deleted['ok'],deleted)
        self.assertEqual(self.calendar.list_events('2026-09-01','2026-10-01'),[])

    async def test_ambiguous_voice_delete_and_read_to_write_rejected(self):
        self.calendar.save(EVENT);self.calendar.save(EVENT)
        result=await run_local_calendar('Delete the calendar event Dentist',self.calendar,dict(operation='delete',query='Dentist',window_start='2026-09-20',window_end='2026-09-21'))
        self.assertFalse(result['ok']);self.assertTrue(result['needs_input'])
        result=await run_local_calendar('Read my calendar',self.calendar,dict(EVENT,operation='create'))
        self.assertFalse(result['ok'])
        self.assertEqual(len(self.calendar.list_events('2026-09-01','2026-10-01')),2)

    async def test_google_explicit_and_local_default_remain_separate(self):
        step={'action':'calendar_task','target':'primary','content':'','recipient':'','subject':''}
        with patch('jarvis.automation.local_pc.run_calendar',new=AsyncMock(return_value={'ok':True,'message':'Google result'})) as google, \
             patch('jarvis.automation.local_pc.run_local_calendar',new=AsyncMock(return_value={'ok':True,'message':'Local result'})) as local:
            pc=LocalPC()
            await pc.execute('Show my calendar tomorrow',planned_steps=[step]);local.assert_awaited_once();google.assert_not_awaited()
            await pc.execute('Show my Google calendar tomorrow',planned_steps=[step]);google.assert_awaited_once()
        self.assertTrue(is_pc_request('Delete the calendar event Dentist tomorrow'))

    def test_open_views_preserve_google_and_memory_file(self):
        for text in ['Open my calendar','Open Jarvis calendar','Öffne meinen Kalender']:
            self.assertEqual(personal_panel_request(text),'calendar')
        for text in ['Open memory','Show my memories','Öffne dein Gedächtnis']:
            self.assertEqual(personal_panel_request(text),'memory')
        for text in ['Open Google Calendar','Open memory.md','Show my calendar tomorrow']:
            self.assertIsNone(personal_panel_request(text))


class CustomAPITests(unittest.TestCase):
    def test_voice_opens_personal_calendar(self):
        import jarvis.server as server
        from fastapi.testclient import TestClient
        with patch.object(server, '_last_greeting_time', time.time()), \
             patch.object(server, '_save_personal_turn', new=AsyncMock()), TestClient(server.app) as client:
            with client.websocket_connect('/ws/voice', subprotocols=['jarvis', 'jarvis.auth.' + server.JARVIS_AUTH_TOKEN]) as ws:
                ws.receive_json()
                ws.send_json({'type': 'transcript', 'isFinal': True, 'text': 'Open my calendar'})
                for _ in range(10):
                    event = ws.receive_json()
                    if event['type'] == 'open_personal':
                        self.assertEqual(event['view'], 'calendar')
                        break
                else:
                    self.fail('Personal calendar did not open')
                ws.send_json({'type': 'stop', 'cancelTasks': True})

    def test_authenticated_crud_and_revision_checks(self):
        import jarvis.server as server
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory() as root, patch.object(server,'personal_memory',PersonalMemory(root)), \
             patch.object(server,'local_calendar',LocalCalendar(root)), TestClient(server.app) as client:
            headers={'Authorization':'Bearer '+server.JARVIS_AUTH_TOKEN}
            self.assertEqual(client.post('/api/memory/custom',json={'content':'Hello'}).status_code,401)
            self.assertEqual(client.post('/api/local-calendar/events',json=EVENT).status_code,401)
            memory=client.post('/api/memory/custom',headers=headers,json={'content':'I prefer morning meetings.','kind':'preference'}).json()['fact']
            self.assertTrue(memory['manual'])
            self.assertEqual(client.get('/api/memory/profile',headers=headers).json()['facts'][0]['key'],memory['key'])
            self.assertEqual(client.post('/api/memory/delete',headers=headers,json={'key':memory['key'],'expected_updated':0}).status_code,409)
            self.assertEqual(client.post('/api/memory/delete',headers=headers,json={'key':memory['key'],'expected_updated':memory['updated']}).status_code,200)
            event=client.post('/api/local-calendar/events',headers=headers,json=EVENT).json()['event']
            listing=client.get('/api/local-calendar/events?start=2026-09-01&end=2026-10-01',headers=headers).json()
            self.assertEqual(listing['events'][0]['id'],event['id'])
            edited=client.post('/api/local-calendar/events',headers=headers,json=dict(EVENT,id=event['id'],version=event['version'],title='Updated')).json()['event']
            self.assertEqual(client.post('/api/local-calendar/delete',headers=headers,json={'id':event['id'],'version':1}).status_code,409)
            self.assertEqual(client.post('/api/local-calendar/delete',headers=headers,json={'id':edited['id'],'version':edited['version']}).status_code,200)


if __name__=='__main__':unittest.main()
