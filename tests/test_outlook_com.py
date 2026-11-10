from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from jarvis.automation.local_pc import LocalPC
from jarvis.integrations.email_planner import OUTLOOK_RECENT_INBOX_QUERY
from jarvis.integrations.outlook_com import (
    OutlookUnavailable, _read_recent_outlook_inbox,
    _recent_unread_outlook_headers, recent_unread_outlook_headers,
)


class FakeItems:
    def __init__(self, rows):
        self.rows=list(rows)
        self.restriction=''
        self.sorting=None

    def Restrict(self, value):
        self.restriction=value
        return self

    def Sort(self, field, descending):
        self.sorting=(field,descending)
        self.rows.sort(key=lambda row: row.ReceivedTime,reverse=descending)

    @property
    def Count(self):
        return len(self.rows)

    def Item(self, index):
        return self.rows[index-1]


class FakeCom:
    def __init__(self):
        self.initialized=0
        self.uninitialized=0

    def CoInitialize(self):
        self.initialized+=1

    def CoUninitialize(self):
        self.uninitialized+=1


def outlook_with(items, accounts=1):
    folder=SimpleNamespace(Items=items)
    session=SimpleNamespace(Accounts=SimpleNamespace(Count=accounts),
                            GetDefaultFolder=lambda folder_id: folder)
    return SimpleNamespace(Session=session)


class OutlookComTests(unittest.IsolatedAsyncioTestCase):
    def test_urgent_scan_reads_fifty_headers_without_bodies(self):
        now = datetime(2026, 9, 25, 12)
        rows = [SimpleNamespace(ReceivedTime=now-timedelta(minutes=index),
                                EntryID=str(index), Subject='Urgent',
                                SenderName='Sender', Importance=2,
                                Body='private body') for index in range(60)]
        items = FakeItems(rows)
        result = _recent_unread_outlook_headers(outlook_with(items), FakeCom())
        self.assertEqual(len(result), 50)
        self.assertEqual(result[0]['id'], '0')
        self.assertNotIn('body', result[0])

    async def test_urgent_scan_opens_classic_outlook_before_com(self):
        with patch('jarvis.integrations.outlook_com._outlook_is_active',
                   side_effect=[False, True]), \
             patch('jarvis.automation.app_launcher.open_app', new=AsyncMock(
                 return_value={'success': True})) as open_app, \
             patch('jarvis.integrations.outlook_com._recent_unread_outlook_headers',
                   return_value=[{'id': 'new'}]):
            result = await recent_unread_outlook_headers()
        self.assertEqual(result, [{'id': 'new'}])
        open_app.assert_awaited_once_with('Outlook Classic', wait_until_ready=True)

    def test_recent_reader_is_read_only_bounded_and_sorted(self):
        now=datetime(2026,9,25,12)
        rows=[SimpleNamespace(Class=43,ReceivedTime=now-timedelta(days=day),
                              SenderName=f'Sender {day}',SenderEmailAddress=f's{day}@example.com',
                              Subject=f'Message {day}',Body='x'*2500)
              for day in range(8)]
        items=FakeItems(rows)
        com=FakeCom()
        result=_read_recent_outlook_inbox(outlook_with(items),com)

        self.assertTrue(result['ok'])
        self.assertEqual(items.restriction,"[MessageClass] = 'IPM.Note'")
        self.assertEqual(items.sorting,('[ReceivedTime]',True))
        self.assertTrue(result['message'].startswith('Recent Outlook inbox messages'))
        self.assertEqual(result['message'].count('"subject"'),5)
        self.assertIn('Message 0',result['message'])
        self.assertIn('Message 4',result['message'])
        self.assertNotIn('Message 5',result['message'])
        self.assertNotIn('x'*1801,result['message'])
        self.assertLessEqual(result['message'].count('x'*1800),5)
        self.assertEqual((com.initialized,com.uninitialized),(1,1))

    def test_recent_reader_rejects_ambiguous_outlook_account(self):
        com=FakeCom()
        with self.assertRaises(OutlookUnavailable):
            _read_recent_outlook_inbox(outlook_with(FakeItems([]),accounts=2),com)
        self.assertEqual((com.initialized,com.uninitialized),(1,1))

    async def test_latest_outlook_read_uses_com_without_ui_agent(self):
        step={'action':'read_email','target':'Outlook','content':OUTLOOK_RECENT_INBOX_QUERY,
              'recipient':'','subject':''}
        with patch('jarvis.integrations.outlook_com.read_recent_outlook_inbox',new=AsyncMock(
                return_value={'ok':True,'message':'Recent Outlook inbox messages: []'})) as read, \
             patch('jarvis.automation.local_pc.run_app',new=AsyncMock(
                     side_effect=AssertionError('Classic Outlook reads should not launch UI planning'))):
            planner=LocalPC()
            result=await planner.execute('Read my latest emails in Outlook',planned_steps=[step])
        self.assertIn('Recent Outlook inbox messages',result)
        self.assertTrue(planner.last_action_ok)
        read.assert_awaited_once()

    async def test_recent_outlook_read_falls_back_to_verified_ui_when_com_is_unavailable(self):
        step={'action':'read_email','target':'Outlook','content':OUTLOOK_RECENT_INBOX_QUERY,
              'recipient':'','subject':''}
        with patch('jarvis.integrations.outlook_com.read_recent_outlook_inbox',new=AsyncMock(
                side_effect=OutlookUnavailable('COM unavailable'))), \
             patch('jarvis.automation.local_pc.run_app',new=AsyncMock(
                     return_value={'ok':True,'message':'Visible Outlook mail content.'})) as run_app:
            planner=LocalPC()
            result=await planner.execute('Read my latest emails in Outlook',planned_steps=[step])
        self.assertIn('Visible Outlook mail content',result)
        self.assertTrue(planner.last_action_ok)
        self.assertEqual(run_app.await_args.kwargs['mail']['mode'],'read')
