from contextlib import asynccontextmanager
import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, Mock, AsyncMock
from zoneinfo import ZoneInfo
import httpx
from jarvis.integrations.calendar_workflows import run_calendar, event_fields, moment, is_calendar_request
from jarvis.core.local_calendar import LocalCalendar
from jarvis.core.local_calendar_workflows import run_local_calendar, _direct_calendar_read_plan
from jarvis.core.personal_memory import PersonalMemory
from jarvis.automation.local_pc import LocalPC, is_pc_request


PLAN={'operation':'create','all_day':False,'title':'Dentist','start':'2026-09-20T10:00:00','end':'2026-09-20T11:00:00','description':'','location':'','query':'','window_start':'','window_end':''}


class CalendarTests(unittest.IsolatedAsyncioTestCase):
    def test_timezones_and_dst(self):
        self.assertTrue(event_fields(PLAN)['start']['dateTime'].endswith('+02:00'))
        self.assertTrue(moment('2026-12-20T10:00').isoformat().endswith('+01:00'))
        for value in ['2026-03-29T02:30','2026-10-25T02:30','2026-09-20']:
            with self.assertRaises(ValueError):moment(value)
        self.assertEqual(moment('2026-10-25T02:30:00+01:00').hour,2)
        with self.assertRaises(ValueError):event_fields(dict(PLAN,end=PLAN['start']))
        self.assertEqual(event_fields(dict(PLAN,all_day=True,start='2026-09-20',end='2026-09-21'))['end'],{'date':'2026-09-21'})

    async def test_create_payload_no_guests_and_no_read_upgrade(self):
        requests=[]
        def handler(r):
            requests.append(r);body=json.loads(r.content)
            self.assertNotIn('attendees',body);self.assertNotIn('recurrence',body)
            self.assertEqual(body['summary'],'Dentist')
            self.assertTrue(body['start']['dateTime'].endswith('+02:00'))
            return httpx.Response(200,json=body)
        google=Mock();google.status.return_value={'connected':True,'services':['calendar_write']};google._token.return_value='test'
        @asynccontextmanager
        async def connection(**kwargs):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:yield client
        with patch('jarvis.integrations.calendar_workflows.http_client',connection):
            result=await run_calendar('Create a calendar event',google,PLAN)
            self.assertTrue(result['ok'],result)
            result=await run_calendar('Read my calendar',google,PLAN)
            self.assertFalse(result['ok']);self.assertEqual(len(requests),1)

    async def test_update_uniqueness_etag_and_conflict_no_retry(self):
        plan=dict(PLAN,operation='update',query='Dentist',window_start='2026-09-19T00:00',window_end='2026-09-20T00:00')
        row={'id':'abc123','etag':'"old"','summary':'Dentist','start':{'dateTime':'2026-09-19T10:00:00+02:00'}}
        calls=[];duplicate=False
        def handler(r):
            calls.append(r)
            if r.method=='PATCH':
                self.assertEqual(r.headers['If-Match'],'"old"')
                return httpx.Response(412,json={})
            if r.url.path.endswith('abc123'):return httpx.Response(200,json=row)
            return httpx.Response(200,json={'items':[row,row] if duplicate else [row]})
        google=Mock();google.status.return_value={'connected':True,'services':['calendar_write']};google._token.return_value='test'
        @asynccontextmanager
        async def connection(**kwargs):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:yield client
        with patch('jarvis.integrations.calendar_workflows.http_client',connection):
            result=await run_calendar('Move my calendar appointment',google,plan)
            self.assertFalse(result['ok']);self.assertFalse(result['needs_input'])
            self.assertEqual(sum(r.method=='PATCH' for r in calls),1)
            duplicate=True;calls.clear()
            result=await run_calendar('Move my calendar appointment',google,plan)
            self.assertFalse(result['ok']);self.assertTrue(result['needs_input'])
            self.assertFalse(any(r.method=='PATCH' for r in calls))

    async def test_new_permission_is_required(self):
        google=Mock();google.status.return_value={'connected':True,'services':['calendar']}
        result=await run_calendar('Create a calendar event',google,PLAN)
        self.assertFalse(result['ok']);self.assertTrue(result['needs_input'])
        google._token.assert_not_called()

    async def test_voice_routing(self):
        for request in ['Create a calendar event tomorrow','Move my dentist appointment','Zeige meine Termine','Liste meinen Kalender nächste Woche','Erstelle einen Termin morgen']:
            self.assertTrue(is_calendar_request(request));self.assertTrue(is_pc_request(request))
            self.assertEqual((await LocalPC().plan(request))[0]['action'],'calendar_task')
        self.assertFalse(is_calendar_request('What is a lunar cycle?'))

    def test_direct_local_calendar_read_uses_local_timezone_and_week_boundaries(self):
        now=datetime(2026,9,25,12,tzinfo=ZoneInfo('Europe/Zurich'))
        cases={
            'Show my calendar tomorrow':('2026-09-26','2026-09-27'),
            'Zeige meinen Kalender morgen':('2026-09-26','2026-09-27'),
            'What is on my calendar this week':('2026-09-21','2026-09-28'),
            'Liste meinen Kalender nächste Woche':('2026-09-28','2026-10-05'),
            'Read my calendar for the next 7 days':('2026-09-25','2026-10-02'),
        }
        for request,(start,end) in cases.items():
            with self.subTest(request=request):
                plan=_direct_calendar_read_plan(request,now)
                self.assertEqual((plan['window_start'],plan['window_end']),(start,end))
                self.assertEqual(plan['operation'],'read')
        self.assertIsNone(_direct_calendar_read_plan('Show my Google calendar tomorrow',now))
        self.assertIsNone(_direct_calendar_read_plan('Show my calendar sometime soon',now))
        self.assertIsNone(_direct_calendar_read_plan('Create a calendar event tomorrow',now))

    async def test_simple_local_calendar_read_skips_model_and_returns_matching_events(self):
        with tempfile.TemporaryDirectory() as root:
            store=LocalCalendar(root)
            tomorrow=(datetime.now(ZoneInfo('Europe/Zurich')).date()+timedelta(days=1))
            store.save({'operation':'create','all_day':True,'title':'School meeting',
                        'start':tomorrow.isoformat(),'end':(tomorrow+timedelta(days=1)).isoformat(),
                        'description':'','location':''})
            with patch('jarvis.core.local_calendar_workflows.LLMClient.create',new=AsyncMock(
                    side_effect=AssertionError('A clear local-calendar date range needs no model call'))):
                result=await run_local_calendar('Show my calendar tomorrow',store=store)
            self.assertTrue(result['ok'],result)
            self.assertIn('School meeting',result['message'])

    def test_explicit_memory_survives_restart_without_model(self):
        with tempfile.TemporaryDirectory() as root:
            memory=PersonalMemory(root)
            content=memory.explicit_content('Remember that I prefer morning meetings')
            self.assertEqual(content,'I prefer morning meetings')
            self.assertTrue(memory.remember_explicit(content))
            self.assertTrue(memory.remember_explicit(content))
            self.assertEqual(len(PersonalMemory(root).facts()),1)
            self.assertIn(content,(Path(root)/'MEMORY.md').read_text(encoding='utf-8'))
            self.assertFalse(memory.remember_explicit('My password is secret123'))
            self.assertEqual(len(memory.facts()),1)
            self.assertEqual(memory.explicit_content('Merke dir, dass ich morgens arbeite'),'ich morgens arbeite')
