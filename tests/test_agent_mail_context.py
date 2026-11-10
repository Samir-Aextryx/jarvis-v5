import base64
from contextlib import asynccontextmanager
from email import policy
from email.parser import BytesParser
import json
import time
import unittest
from unittest.mock import AsyncMock, patch
import httpx
from jarvis.integrations.email_context import MailContext, resolve_contact
from jarvis.integrations.google_access import GoogleAccess
from tests.test_google_access import Vault

ROW={'id':'m1','thread_id':'t1','message_id':'<original@example.com>','from':'John Smith <john@example.com>', 'subject':'Thursday','body':'Untrusted contents'}


class ContextTests(unittest.IsolatedAsyncioTestCase):
    def test_selection_expiry_ambiguity_and_recipient_mismatch(self):
        context=MailContext();context.record([ROW], 'Find email')
        self.assertEqual(context.reply_target('Reply and tell him yes')[0],'john@example.com')
        with self.assertRaises(ValueError):context.reply_target('Reply to Jane and say yes')
        context.expires=time.monotonic()-1
        with self.assertRaises(ValueError):context.reply_target('Reply saying yes')
        context.record([ROW,dict(ROW,id='m2')],'Find emails')
        with self.assertRaises(ValueError):context.reply_target('Reply saying yes')

    async def test_unique_exact_contact_only(self):
        google=AsyncMock()
        google.search_contacts.return_value=[{'names':[{'displayName':'John Smith'}], 'emailAddresses':[{'value':'john@example.com'}]}]
        self.assertEqual(await resolve_contact('John Smith','Send John Smith an email',google),'john@example.com')
        with self.assertRaises(ValueError):await resolve_contact('John','Send John an email',google)
        google.search_contacts.return_value*=2
        google.search_contacts.return_value[1]=dict(names=[{'displayName':'John Smith'}],emailAddresses=[{'value':'other@example.com'}])
        with self.assertRaises(ValueError):await resolve_contact('John Smith','Send John Smith an email',google)

    async def test_gmail_reply_uses_thread_and_headers_once(self):
        google=GoogleAccess('thread-test',Vault());calls=[]
        def handle(request):
            calls.append(request);data=json.loads(request.content)
            self.assertEqual(data['threadId'],'t1')
            mail=BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(data['raw']))
            self.assertEqual(mail['In-Reply-To'],'<original@example.com>')
            self.assertEqual(mail['To'],'john@example.com')
            self.assertEqual(mail['Subject'],'Thursday')
            return httpx.Response(200,json={'id':'sent1'})
        @asynccontextmanager
        async def client(**kwargs):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as c:yield c
        with patch.object(google,'_token',return_value='test'),patch('jarvis.integrations.google_access.http_client',client):
            result=await google.send_gmail({'recipient':'john@example.com','subject':'Thursday','body':'Yes.'},'Reply and tell him yes',resolved_recipient='john@example.com',reply_to=ROW)
            self.assertTrue(result['accepted']);self.assertEqual(len(calls),1)

    async def test_update_keeps_uncertain_mail_and_reports_failed_sources(self):
        from jarvis.core.personal_update import personal_update
        messages=[{'from':'A','subject':'Assignment'}, {'from':'B','subject':'Advertisement'}]
        answers={'0':{'type':'choice','choice':'uncertain','confidence':.9},'1':{'type':'choice','choice':'promotion','confidence':.98}}
        with patch('jarvis.core.personal_update.google_access.status',return_value={'connected':True,'services':['gmail']}), \
             patch('jarvis.core.personal_update.google_access.search_gmail',new=AsyncMock(return_value={'items':messages})), \
             patch('jarvis.core.personal_update.local_calendar.upcoming',side_effect=RuntimeError()), \
             patch('jarvis.core.personal_update.jev.configured',return_value=True), \
             patch('jarvis.core.personal_update.jev.decide',new=AsyncMock(return_value=answers)):
            text=await personal_update()
            self.assertIn('Assignment',text);self.assertNotIn('Advertisement',text)
            self.assertIn('Ignored 1',text);self.assertIn('Could not check: Jarvis calendar',text)


if __name__=='__main__':unittest.main()
