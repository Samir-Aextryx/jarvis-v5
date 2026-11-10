import base64
from contextlib import asynccontextmanager
from email import policy
from email.parser import BytesParser
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch, AsyncMock
import httpx
from jarvis.integrations.google_access import GoogleAccess
from jarvis.integrations.email_workflows import send_requested, blocked_email_recipient
from jarvis.integrations.email_planner import plan_mail, direct_mail_plan
from jarvis.automation.local_pc import LocalPC
from jarvis.automation.desktop_agent import run_app, check_action, UIBlocked
from tests.test_email_workflows import FIELDS, MailUI, actions
from tests.test_desktop_agent import model_with, node
from tests.test_google_access import Vault


class SendUI(MailUI):
    def __init__(self,*args): super().__init__(*args); self.sent=False
    def snapshot(self):
        return {'elements':[node(9,'Message sent','Text')]} if self.sent else super().snapshot()
    def apply(self,action,options):
        if action['action']=='click':
            check_action(action,self.snapshot()['elements'],**options); self.sent=True; return 'clicked'
        return super().apply(action,options)


class EmailSendTests(unittest.IsolatedAsyncioTestCase):
    def test_herr_haener_name_variants_are_blocked_without_matching_literal_body(self):
        for recipient, request in [
            ('Herr Häner', 'Send an email to Herr Häner'),
            ('herr.haener@example.com', 'Send an email to Herr Haener'),
            ('hener@example.com', 'Send an email to Herrn Hener'),
            ('someone@example.com', 'Reply to the latest message from Herr Haenner'),
        ]:
            self.assertTrue(blocked_email_recipient(recipient, request), (recipient, request))
        self.assertFalse(blocked_email_recipient('alex@example.com', 'Send an email to Alex saying please thank Herr Haener'))

    async def test_gmail_herr_haener_block_runs_before_network(self):
        google = GoogleAccess('blocked-recipient-test', Vault())
        with patch.object(google, '_token') as token, patch('jarvis.integrations.google_access.http_client') as network:
            with self.assertRaisesRegex(ValueError, 'Herr Häner'):
                await google.send_gmail(FIELDS, 'Send an email to Herrn Haener at alex@example.com', resolved_recipient=FIELDS['recipient'])
        token.assert_not_called()
        network.assert_not_called()

    async def test_outlook_herr_haener_block_runs_before_send(self):
        from jarvis.integrations.outlook_com import send_outlook
        with patch('jarvis.integrations.outlook_com._send_outlook') as send:
            with self.assertRaisesRegex(ValueError, 'Herr Häner'):
                await send_outlook(FIELDS, 'Send an email to Herr Haener at alex@example.com')
        send.assert_not_called()

    def test_outlook_contact_resolution_requires_exact_single_match(self):
        from jarvis.integrations.outlook_com import resolve_outlook_contact
        entry=SimpleNamespace(Name='John Smith',Type='SMTP',Address=FIELDS['recipient'])
        recipient=SimpleNamespace(Resolve=lambda: True,Resolved=True,AddressEntry=entry)
        outlook=SimpleNamespace(Session=SimpleNamespace(
            Accounts=SimpleNamespace(Count=1),CreateRecipient=lambda name:recipient))
        request='Draft an email to John Smith'
        with patch('pythoncom.CoInitialize'), patch('pythoncom.CoUninitialize'), \
             patch('win32com.client.Dispatch',return_value=outlook):
            self.assertEqual(resolve_outlook_contact('John Smith',request),FIELDS['recipient'])

        entry.Name='John Smith (old)'
        with patch('pythoncom.CoInitialize'), patch('pythoncom.CoUninitialize'), \
             patch('win32com.client.Dispatch',return_value=outlook):
            with self.assertRaisesRegex(ValueError,'exact Outlook contact'):
                resolve_outlook_contact('John Smith',request)

    def test_outlook_contact_resolution_searches_local_contacts_and_rejects_ambiguity(self):
        from jarvis.integrations.outlook_com import resolve_outlook_contact
        request="Draft an email to O'Brien"
        recipient=SimpleNamespace(Resolve=lambda:False,Resolved=False)
        contacts=[SimpleNamespace(FullName="O'Brien",Email1Address=FIELDS['recipient'],
                                  Email2Address='',Email3Address='')]
        def outlook_with(rows):
            items=SimpleNamespace(Count=len(rows),Item=lambda index:rows[index-1])
            items.Restrict=lambda filter_text:items
            session=SimpleNamespace(Accounts=SimpleNamespace(Count=1),
                CreateRecipient=lambda name:recipient,
                GetDefaultFolder=lambda folder:SimpleNamespace(Items=items))
            return SimpleNamespace(Session=session)
        with patch('pythoncom.CoInitialize'), patch('pythoncom.CoUninitialize'), \
             patch('win32com.client.Dispatch',return_value=outlook_with(contacts)):
            self.assertEqual(resolve_outlook_contact("O'Brien",request),FIELDS['recipient'])

        ambiguous=contacts+[SimpleNamespace(FullName="O'Brien",Email1Address='other@example.com',
                                              Email2Address='',Email3Address='')]
        with patch('pythoncom.CoInitialize'), patch('pythoncom.CoUninitialize'), \
             patch('win32com.client.Dispatch',return_value=outlook_with(ambiguous)):
            with self.assertRaisesRegex(ValueError,'multiple email addresses'):
                resolve_outlook_contact("O'Brien",request)

    async def test_outlook_name_draft_resolves_contact_then_uses_direct_unsent_writer(self):
        pc=LocalPC()
        step={'action':'draft_email','target':'Outlook','recipient':'John Smith',
              'subject':FIELDS['subject'],'content':FIELDS['body']}
        request='Write an email to John Smith in Outlook with subject Meeting saying Hello Alex'
        response={'ok':True,'message':'Saved an unsent Outlook draft.'}
        with patch('jarvis.integrations.outlook_com.resolve_outlook_contact',
                   return_value=FIELDS['recipient']) as resolve, \
             patch('jarvis.integrations.outlook_com.draft_outlook',new=AsyncMock(return_value=response)) as draft, \
             patch('jarvis.automation.local_pc.run_app',new=AsyncMock()) as ui:
            result=await pc.execute(request,planned_steps=[step])
        self.assertTrue(pc.last_action_ok)
        self.assertIn('unsent Outlook draft',result)
        resolve.assert_called_once_with('John Smith',request)
        draft.assert_awaited_once_with(FIELDS)
        ui.assert_not_awaited()

    async def test_gmail_draft_uses_only_one_exact_google_contact_match(self):
        pc = LocalPC()
        step = {'action':'draft_email','target':'Gmail','recipient':'John Smith',
                'subject':FIELDS['subject'],'content':FIELDS['body']}
        contact = {'names':[{'displayName':'John Smith'}],
                   'emailAddresses':[{'value':FIELDS['recipient']}]}
        saved = {'id':'draft-id','message_id':'message-id','saved':True}
        request = 'Draft an email to John Smith in Gmail with subject Meeting saying Hello Alex'
        with patch('jarvis.automation.local_pc.google_access.status',
                   return_value={'connected':True,'services':['contacts','gmail_drafts']}), \
             patch('jarvis.automation.local_pc.google_access.search_contacts',
                   new=AsyncMock(return_value=[contact])) as search, \
             patch('jarvis.automation.local_pc.google_access.create_gmail_draft',
                   new=AsyncMock(return_value=saved)) as draft, \
             patch('jarvis.automation.local_pc.run_app', new=AsyncMock()) as ui:
            result = await pc.execute(request, planned_steps=[step])
        self.assertTrue(pc.last_action_ok)
        self.assertIn('Saved a Gmail draft', result)
        search.assert_awaited_once_with('John Smith', use_cache=True)
        draft.assert_awaited_once_with(FIELDS, request, resolved_recipient=FIELDS['recipient'])
        ui.assert_not_awaited()

    async def test_ambiguous_google_contact_never_creates_a_gmail_draft(self):
        pc = LocalPC()
        step = {'action':'draft_email','target':'Gmail','recipient':'John Smith',
                'subject':FIELDS['subject'],'content':FIELDS['body']}
        contact = {'names':[{'displayName':'John Smith'}],
                   'emailAddresses':[{'value':'one@example.com'}]}
        other = {'names':[{'displayName':'John Smith'}],
                 'emailAddresses':[{'value':'two@example.com'}]}
        with patch('jarvis.automation.local_pc.google_access.status',
                   return_value={'connected':True,'services':['contacts','gmail_drafts']}), \
             patch('jarvis.automation.local_pc.google_access.search_contacts',
                   new=AsyncMock(return_value=[contact,other])), \
             patch('jarvis.automation.local_pc.google_access.create_gmail_draft',
                   new=AsyncMock()) as draft, \
             patch('jarvis.automation.local_pc.run_app', new=AsyncMock()) as ui:
            result = await pc.execute('Draft an email to John Smith in Gmail', planned_steps=[step])
        self.assertTrue(pc.needs_input)
        self.assertIn('one exact contact address', result)
        draft.assert_not_awaited()
        ui.assert_not_awaited()

    async def test_gmail_sending_resolves_contact_without_the_draft_cache(self):
        pc = LocalPC()
        step = {'action':'send_email','target':'Gmail','recipient':'John Smith',
                'subject':FIELDS['subject'],'content':FIELDS['body']}
        contact = {'names':[{'displayName':'John Smith'}],
                   'emailAddresses':[{'value':FIELDS['recipient']}]}
        request = 'Send an email to John Smith in Gmail with subject Meeting saying Hello Alex'
        with patch('jarvis.automation.local_pc.google_access.status',
                   return_value={'connected':True,'services':['contacts','gmail_send']}), \
             patch('jarvis.automation.local_pc.google_access.search_contacts',
                   new=AsyncMock(return_value=[contact])) as search, \
             patch('jarvis.automation.local_pc.google_access.send_gmail',
                   new=AsyncMock(return_value={'id':'sent-id','accepted':True})):
            await pc.execute(request, planned_steps=[step])
        search.assert_awaited_once_with('John Smith')

    async def test_blank_ui_composer_uses_local_verified_draft_fast_path(self):
        class ComposerUI:
            def __init__(self, app, cancel):
                self.app = app
                self.opened = False
                self.values = {'recipient': '', 'subject': '', 'body': ''}
                self.actions = []
            def snapshot(self):
                if not self.opened:
                    return {'elements': [node(3, 'New mail')]}
                return {'elements': [node(0, 'To', 'Edit', self.values['recipient']),
                                     node(1, 'Subject', 'Edit', self.values['subject']),
                                     node(2, 'Message body', 'Edit', self.values['body']),
                                     node(3, 'Send')]}
            def apply(self, action, options):
                self.actions.append(action.copy())
                check_action(action, self.snapshot()['elements'], **options)
                if action['action'] == 'click':
                    self.opened = True
                else:
                    kind = {0: 'recipient', 1: 'subject', 2: 'body'}[action['element']]
                    self.values[kind] = action['text']
                return 'Verified'
            def close(self): pass
        model = AsyncMock()
        with patch('jarvis.automation.desktop_agent.WindowsUI', ComposerUI), \
             patch('jarvis.automation.desktop_agent.open_app', new=AsyncMock(return_value={'success': True, 'app': 'Outlook'})):
            result = await run_app('Outlook', 'Write an email',
                                   mail=dict(FIELDS, submit_allowed=False),
                                   backend_factory=ComposerUI, model=model)
        self.assertTrue(result['ok'], result)
        self.assertIn('not been sent', result['message'])
        model.create.assert_not_awaited()

    def test_compound_mail_does_not_take_single_step_path(self):
        self.assertIsNone(direct_mail_plan(
            'Read Gmail and then send an email to alex@example.com with subject Meeting saying Hello', 'Gmail'))
        self.assertIsNone(direct_mail_plan(
            'Send an email to alex@example.com with subject Meeting then open Chrome saying Hello', 'Gmail'))
        self.assertIsNone(direct_mail_plan(
            'Send an email to alex@example.com in Gmail with subject Meeting saying Hello Alex, and then open Chrome', 'Gmail'))

    def test_voice_complete_mail_skips_autonomous_planner(self):
        import jarvis.server as server
        from fastapi.testclient import TestClient
        local = SimpleNamespace(pending='', last_action_silent=False,
                                execute=AsyncMock(return_value='Mail prepared.'))
        with patch.object(server, 'LocalPC', return_value=local), \
             patch.object(server.jev, 'configured', return_value=True), \
             patch.object(server.agent_router, 'route', new=AsyncMock()) as route, \
             patch.object(server.AutonomousTasks, 'start', return_value='') as autonomous, \
             patch.object(server, 'synthesize_speech', new=AsyncMock(return_value=None)):
            with TestClient(server.app) as client:
                with client.websocket_connect('/ws/voice', subprotocols=['jarvis', 'jarvis.auth.' + server.JARVIS_AUTH_TOKEN]) as ws:
                    ws.send_json({'type': 'transcript', 'text':
                                  'Write an email to alex@example.com in Gmail with subject Meeting saying Hello Alex',
                                  'isFinal': True})
                    for _ in range(8):
                        message = ws.receive_json()
                        if message.get('type') == 'text':
                            self.assertIn('Mail prepared.', message['text'])
                            break
                    else:
                        self.fail('No direct mail response')
        local.execute.assert_awaited_once()
        autonomous.assert_not_called()
        route.assert_not_awaited()

    async def test_complete_mail_skips_model_but_preserves_send_intent(self):
        with patch('jarvis.integrations.email_planner.LLMClient.create', new=AsyncMock()) as model:
            sent = await plan_mail('Send an email to alex@example.com in Gmail with subject Meeting saying Hello Alex')
            draft = await plan_mail('Write an email to alex@example.com in Gmail with subject Meeting saying Hello Alex')
            negated = await plan_mail('Send an email to alex@example.com in Gmail with subject Meeting saying Hello Alex but do not send it yet')
        self.assertEqual(sent, [{'action': 'send_email', 'target': 'Gmail', 'recipient': 'alex@example.com', 'subject': 'Meeting', 'content': 'Hello Alex'}])
        self.assertEqual(draft[0]['action'], 'draft_email')
        self.assertEqual(negated[0]['action'], 'draft_email')
        model.assert_not_awaited()

    async def test_mail_topic_without_body_still_uses_model(self):
        value = dict(task='draft', provider='Gmail', recipient='alex@example.com',
                     subject='Project update', body='Here is the project update.')
        with patch('jarvis.integrations.email_planner.LLMClient.create',
                   new=AsyncMock(return_value=SimpleNamespace(content=[SimpleNamespace(text=json.dumps(value))]))) as model:
            plan = await plan_mail('Write an email to alex@example.com in Gmail about the project update')
        self.assertEqual(plan[0]['content'], 'Here is the project update.')
        model.assert_awaited_once()

    def test_send_authority(self):
        for text in ['Send an email to alex@example.com','Open Gmail and send an email','Bitte sende eine E-Mail','Write an email and send it',
                     'Sende eine E-Mail an alex@example.com mit dem Betreff Termin und dem Text Hallo Alex']:
            self.assertTrue(send_requested(text),text)
        for text in ['Write an email about how to send money','Send an email but do not send it yet','Sende die E-Mail nicht','Write an email saying "send money"',
                     'Schreibe eine E-Mail an alex@example.com mit dem Betreff Unterlagen und dem Text Hallo Alex und sende mir bitte die Unterlagen',
                     'Schreibe eine E-Mail an alex@example.com mit dem Betreff Bitte sende die Unterlagen und dem Text Hallo Alex',
                     'Write an email to alex@example.com with the subject Please send the files with the text Hello Alex and send them today']:
            self.assertFalse(send_requested(text),text)

    def test_complete_german_mail_is_planned_locally(self):
        for request, provider, action in [
            ('Schreibe eine E-Mail an alex@example.com mit dem Betreff Termin und dem Text Hallo Alex, passt morgen um zehn?', 'Outlook', 'draft_email'),
            ('Sende eine E-Mail an alex@example.com mit dem Betreff Termin und dem Text Hallo Alex, passt morgen um zehn?', 'Outlook', 'send_email'),
            ('Schicke in Gmail eine Mail an alex@example.com mit Betreff Termin mit dem Inhalt Hallo Alex, passt morgen um zehn?', 'Gmail', 'send_email'),
        ]:
            with self.subTest(request=request):
                self.assertEqual(direct_mail_plan(request, 'Outlook'), {
                    'action': action, 'target': provider, 'recipient': 'alex@example.com',
                    'subject': 'Termin', 'content': 'Hallo Alex, passt morgen um zehn?'})
        # A dictated body that mentions sending stays an unsent draft.
        draft = direct_mail_plan('Schreibe eine E-Mail an alex@example.com mit dem Betreff Unterlagen '
                                 'und dem Text Hallo Alex und sende mir bitte die Unterlagen', 'Outlook')
        self.assertEqual(draft['action'], 'draft_email')
        self.assertEqual(draft['content'], 'Hallo Alex und sende mir bitte die Unterlagen')

    async def test_planner_cannot_upgrade_draft_to_send(self):
        value=dict(task='send',provider='Gmail',recipient=FIELDS['recipient'],subject=FIELDS['subject'],body=FIELDS['body'])
        with patch('jarvis.integrations.email_planner.LLMClient.create',new=AsyncMock(return_value=SimpleNamespace(content=[SimpleNamespace(text=json.dumps(value))]))):
            self.assertEqual((await plan_mail('Write an email to alex@example.com in Gmail about the meeting'))[0]['action'],'draft_email')
            self.assertEqual((await plan_mail('Send an email to alex@example.com in Gmail'))[0]['action'],'ask')
            self.assertEqual((await plan_mail('Send an email to alex@example.com in Gmail with subject Meeting saying Hello'))[0]['action'],'send_email')

    async def test_api_mime_and_no_retry_on_uncertain_send(self):
        google=GoogleAccess('send-test',Vault()); calls=[]
        def handler(request):
            calls.append(request)
            if len(calls)>1: raise httpx.ReadTimeout('timeout')
            mime=BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(json.loads(request.content)['raw']))
            self.assertEqual(mime['To'],FIELDS['recipient']);self.assertEqual(mime['Subject'],FIELDS['subject'])
            self.assertEqual(mime.get_content().strip(),FIELDS['body'])
            self.assertIsNone(mime['Bcc'])
            return httpx.Response(200,json={'id':'test-message'})
        @asynccontextmanager
        async def client(**kwargs):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:yield c
        with patch.object(google,'_token',return_value='test'),patch('jarvis.integrations.google_access.http_client',client):
            self.assertTrue((await google.send_gmail(FIELDS,'Send an email to alex@example.com'))['accepted'])
            with self.assertRaisesRegex(ValueError,'uncertain'):
                await google.send_gmail(FIELDS,'Send an email to alex@example.com')
            self.assertEqual(len(calls),2)
            with self.assertRaises(ValueError):await google.send_gmail(FIELDS,'Write a draft to alex@example.com')
            with self.assertRaises(ValueError):await google.send_gmail(FIELDS,'Send an email to other@example.com')
            self.assertEqual(len(calls),2)

    async def test_outlook_send_verified_fields_and_success_notice(self):
        sequence=actions()[:-1]+[{'action':'click','element':3,'text':'','message':''},actions()[-1]]
        result=await run_app('Outlook','Send an email to alex@example.com',mail=dict(FIELDS,submit_allowed=True),backend_factory=SendUI,model=model_with(sequence))
        self.assertTrue(result['ok'],result)
        self.assertIn('Delivery has not been confirmed',result['message'])

    async def test_ui_model_cannot_claim_send_without_click(self):
        result=await run_app('Outlook','Send an email',mail=dict(FIELDS,submit_allowed=True),backend_factory=MailUI,model=model_with(actions()))
        self.assertFalse(result['ok'])

    def test_changed_recipient_or_extra_cc_blocks_send(self):
        nodes=[node(0,'To','Edit',FIELDS['recipient']),node(1,'Subject','Edit',FIELDS['subject']),node(2,'Message body','Edit',FIELDS['body']),node(3,'Send')]
        fields=dict(FIELDS,submit_allowed=True,entered={'recipient':0,'subject':1,'body':2})
        check_action({'action':'click','element':3},nodes,mail=fields)
        with self.assertRaises(UIBlocked):check_action({'action':'click','element':3},nodes+[node(4,'Cc','Edit','other@example.com')],mail=fields)
        nodes[0]['value']='other@example.com'
        with self.assertRaises(UIBlocked):check_action({'action':'click','element':3},nodes,mail=fields)

    async def test_executor_requires_sending_scope_before_any_send(self):
        pc=LocalPC()
        step={'action':'send_email','target':'Gmail','recipient':FIELDS['recipient'],'subject':FIELDS['subject'],'content':FIELDS['body']}
        with patch('jarvis.automation.local_pc.google_access.status',return_value={'connected':True,'services':['gmail']}),patch('jarvis.automation.local_pc.google_access.send_gmail',new=AsyncMock()) as send,patch('jarvis.automation.local_pc.run_app',new=AsyncMock()) as ui:
            result=await pc.execute('Send an email to alex@example.com in Gmail',planned_steps=[step])
            self.assertIn('reconnect',result);self.assertTrue(pc.needs_input)
            send.assert_not_awaited();ui.assert_not_awaited()

    async def test_outlook_send_uses_single_account_integration(self):
        pc=LocalPC()
        step={'action':'send_email','target':'Outlook','recipient':FIELDS['recipient'],
              'subject':FIELDS['subject'],'content':FIELDS['body']}
        response={'ok':True,'message':'Outlook accepted the email. Delivery has not been confirmed.'}
        with patch('jarvis.integrations.outlook_com.send_outlook',new=AsyncMock(return_value=response)) as send, \
             patch('jarvis.automation.local_pc.run_app',new=AsyncMock()) as ui:
            result=await pc.execute('Send an email to alex@example.com in Outlook',planned_steps=[step])
        self.assertIn('Outlook accepted',result)
        send.assert_awaited_once()
        ui.assert_not_awaited()

    async def test_outlook_complete_draft_uses_direct_unsent_composer(self):
        pc=LocalPC()
        step={'action':'draft_email','target':'Outlook','recipient':FIELDS['recipient'],
              'subject':FIELDS['subject'],'content':FIELDS['body']}
        response={'ok':True,'message':'Saved an unsent Outlook draft.'}
        with patch('jarvis.integrations.outlook_com.draft_outlook',new=AsyncMock(return_value=response)) as draft, \
             patch('jarvis.automation.local_pc.run_app',new=AsyncMock()) as ui:
            result=await pc.execute('Write an email to alex@example.com in Outlook',planned_steps=[step])
        self.assertIn('unsent Outlook draft',result)
        draft.assert_awaited_once_with(FIELDS)
        ui.assert_not_awaited()

    async def test_outlook_without_classic_com_falls_back_to_verified_ui(self):
        pc=LocalPC()
        step={'action':'draft_email','target':'Outlook','recipient':FIELDS['recipient'],
              'subject':FIELDS['subject'],'content':FIELDS['body']}
        response={'ok':True,'message':'Verified draft in Outlook.'}
        from jarvis.integrations.outlook_com import OutlookUnavailable
        with patch('jarvis.integrations.outlook_com.draft_outlook',new=AsyncMock(side_effect=OutlookUnavailable())), \
             patch('jarvis.automation.local_pc.run_app',new=AsyncMock(return_value=response)) as ui:
            result=await pc.execute('Write an email to alex@example.com in Outlook',planned_steps=[step])
        self.assertIn('Verified draft',result)
        ui.assert_awaited_once_with('Outlook','Write an email to alex@example.com in Outlook',mail=dict(FIELDS,submit_allowed=False))

    async def test_outlook_com_draft_preserves_signature_and_never_sends(self):
        from jarvis.integrations.outlook_com import draft_outlook
        from types import SimpleNamespace
        class Message:
            def __init__(self):
                self.To=''; self.Subject=''; self.HTMLBody='<html><body><b>Regards, Samir</b></body></html>'; self.CC=''; self.BCC=''
                self.Recipients=SimpleNamespace(Count=1); self.displayed=False; self.saved=False
            @property
            def Body(self):
                import html, re
                text=re.sub(r'<br\s*/?>','\n',self.HTMLBody,flags=re.I)
                return html.unescape(re.sub(r'<[^>]+>','',text))
            def Display(self, modal): self.displayed=True; self.assertion = modal
            def Save(self): self.saved=True
            def Send(self): raise AssertionError('A draft must never be sent.')
        message=Message()
        accounts=SimpleNamespace(Count=1,Item=lambda index:'default-account')
        outlook=SimpleNamespace(Session=SimpleNamespace(Accounts=accounts),CreateItem=lambda kind:message)
        with patch('pythoncom.CoInitialize'), patch('pythoncom.CoUninitialize'), \
             patch('win32com.client.Dispatch',return_value=outlook):
            result=await draft_outlook(FIELDS)
        self.assertTrue(result['ok'])
        self.assertTrue(message.displayed and message.saved)
        self.assertEqual(message.To,FIELDS['recipient'])
        self.assertEqual(message.Subject,FIELDS['subject'])
        self.assertIn(FIELDS['body'],message.Body)
        self.assertIn('<b>Regards, Samir</b>',message.HTMLBody)

    async def test_outlook_com_draft_refuses_ambiguous_account_before_creating_item(self):
        from jarvis.integrations.outlook_com import OutlookUnavailable, draft_outlook
        from unittest.mock import Mock
        accounts=SimpleNamespace(Count=2)
        outlook=SimpleNamespace(Session=SimpleNamespace(Accounts=accounts),CreateItem=Mock())
        with patch('pythoncom.CoInitialize'), patch('pythoncom.CoUninitialize'), \
             patch('win32com.client.Dispatch',return_value=outlook):
            with self.assertRaises(OutlookUnavailable):
                await draft_outlook(FIELDS)
        outlook.CreateItem.assert_not_called()
