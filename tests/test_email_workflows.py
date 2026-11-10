import base64
from contextlib import asynccontextmanager
import json
import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from jarvis.automation.desktop_agent import check_action, run_app, UIBlocked
from jarvis.integrations.email_workflows import draft_fields, visual_draft_fields, verify_draft, recipient_authorized, is_email_request
from jarvis.automation.autonomous_tasks import AutonomousTasks
from jarvis.integrations.email_planner import OUTLOOK_RECENT_INBOX_QUERY, plan_mail, extract_draft_components
from jarvis.integrations.google_access import GoogleAccess, mail_body
from jarvis.automation.local_pc import LocalPC, is_pc_request
from tests.test_google_access import Vault
from tests.test_desktop_agent import node, model_with


FIELDS = draft_fields('alex@example.com', 'Meeting', 'Hello Alex,\nCan we meet tomorrow?')


class MailUI:
    def __init__(self, app, cancel):
        self.values = {'recipient': '', 'subject': '', 'body': ''}
        self.closed = False

    def snapshot(self):
        return {'elements': [node(0, 'To', 'Edit', self.values['recipient']),
                             node(1, 'Subject', 'Edit', self.values['subject']),
                             node(2, 'Message body', 'Edit', self.values['body']), node(3, 'Send')]}

    def apply(self, action, options):
        check_action(action, self.snapshot()['elements'], **options)
        self.values[{0: 'recipient', 1: 'subject', 2: 'body'}[action['element']]] = action['text']
        return 'Exact text verified'

    def close(self):
        self.closed = True


def actions():
    return [{'action': 'type', 'element': n, 'text': FIELDS[k], 'message': ''}
            for n, k in [(1, 'subject'), (2, 'body'), (0, 'recipient')]] + [
                {'action': 'done', 'element': -1, 'text': '', 'message': 'Sent!'}]


class MailTests(unittest.IsolatedAsyncioTestCase):
    def test_new_outlook_thema_is_subject_field(self):
        from jarvis.integrations.email_workflows import field_kind
        self.assertEqual(field_kind(node(1, 'Thema', 'Edit')), 'subject')

    async def test_mail_planner_builds_exact_filters(self):
        value = {'task':'read','provider':'Gmail','sender':'alex@example.com','before':'2026-09-01',
                 'after':'','keywords':'','unread':False}
        response = SimpleNamespace(content=[SimpleNamespace(text=json.dumps(value))])
        with patch('jarvis.integrations.email_planner.LLMClient.create',new=AsyncMock(return_value=response)):
            steps = await plan_mail('Read Gmail from alex@example.com before September 2026')
        self.assertEqual(steps[0]['content'],'from:alex@example.com before:2026/09/01')
        self.assertNotIn('unread',steps[0]['content'])

    async def test_simple_read_mail_filters_skip_llm_planning(self):
        requests = [
            ('Read unread Gmail emails about delivery from alex@example.com',
             'Gmail', 'from:alex@example.com is:unread "delivery"'),
            ('Lies ungelesene Gmail-Mails zum Thema Zustellung',
             'Gmail', 'is:unread "Zustellung"'),
            ('Read my Outlook emails before 2026-09-01',
             'Outlook', 'received:<2026-09-01'),
            ('Read my latest emails in Outlook', 'Outlook', OUTLOOK_RECENT_INBOX_QUERY),
            ('Read my Gmail emails', 'Gmail', 'in:anywhere -in:spam -in:trash'),
            ('Read the latest Gmail emails', 'Gmail', 'in:inbox'),
        ]
        with patch('jarvis.integrations.email_planner.LLMClient.create', new=AsyncMock(
                side_effect=AssertionError('Unambiguous mail reads should be planned locally'))):
            for request, provider, query in requests:
                with self.subTest(request=request):
                    steps = await plan_mail(request)
                    self.assertEqual(steps, [{'action':'read_email','target':provider,
                                              'content':query,'recipient':'','subject':''}])

    async def test_inbox_and_new_mail_checks_use_the_fast_local_path(self):
        requests = [
            ('Check my email', 'Gmail', 'in:inbox'),
            ('Check my Outlook inbox', 'Outlook', OUTLOOK_RECENT_INBOX_QUERY),
            ('Any new Gmail emails?', 'Gmail', 'in:inbox is:unread'),
            ("What's in my Gmail inbox?", 'Gmail', 'in:inbox'),
            ('Prüfe meinen Outlook-Posteingang', 'Outlook', OUTLOOK_RECENT_INBOX_QUERY),
        ]
        with patch('jarvis.integrations.email_planner.agent_settings.get',
                   return_value={'default_email':'Gmail'}), \
             patch('jarvis.integrations.email_planner.LLMClient.create', new=AsyncMock(
                 side_effect=AssertionError('A simple inbox check must not call the planner'))):
            for request, provider, query in requests:
                with self.subTest(request=request):
                    steps = await plan_mail(request)
                    self.assertEqual(steps, [{'action':'read_email','target':provider,
                                              'content':query,'recipient':'','subject':''}])

    async def test_explicit_gmail_open_is_preserved_with_a_direct_mail_read(self):
        with patch('jarvis.integrations.email_planner.LLMClient.create',new=AsyncMock(
                side_effect=AssertionError('An explicit Gmail open and latest-mail read are deterministic'))):
            steps=await plan_mail('Open Gmail and read my latest emails')
        self.assertEqual([step['action'] for step in steps],['open_url','read_email'])
        self.assertEqual(steps[0]['target'],'https://mail.google.com/')
        self.assertEqual(steps[1]['target'],'Gmail')
        self.assertEqual(steps[1]['content'],'in:inbox')

    async def test_ambiguous_old_mail_still_uses_llm(self):
        ask = {'task':'ask','provider':'Outlook','recipient':'','subject':'','body':'','sender':'',
               'keywords':'','before':'','after':'','unread':False,'question':'Which period?'}
        response = SimpleNamespace(content=[SimpleNamespace(text=json.dumps(ask))])
        with patch('jarvis.integrations.email_planner.LLMClient.create', new=AsyncMock(
                return_value=response)) as model:
            steps = await plan_mail('Read old emails in Outlook')
        self.assertEqual(steps[0]['action'], 'ask')
        model.assert_awaited_once()

    async def test_sender_email_domain_does_not_select_mail_provider(self):
        with patch('jarvis.integrations.email_planner.agent_settings.get',
                   return_value={'default_email':'Outlook'}), \
             patch('jarvis.integrations.email_planner.LLMClient.create', new=AsyncMock(
                     side_effect=AssertionError('The configured default provider should be preserved'))):
            steps = await plan_mail('Read my emails from alex@gmail.com')
        self.assertEqual(steps[0]['target'], 'Outlook')
        self.assertEqual(steps[0]['content'], 'from:alex@gmail.com')

        with patch('jarvis.integrations.email_planner.agent_settings.get',
                   return_value={'default_email':'Gmail'}), \
             patch('jarvis.integrations.email_planner.LLMClient.create', new=AsyncMock(
                     side_effect=AssertionError('An Outlook email domain is not an app choice'))):
            steps = await plan_mail('Read my emails from alex@outlook.com')
        self.assertEqual(steps[0]['target'], 'Gmail')
        self.assertEqual(steps[0]['content'], 'from:alex@outlook.com')

    async def test_generated_mail_and_replies_default_to_german(self):
        value = {'task':'reply','provider':'Gmail','sender':'','subject':'','body':'Guten Tag, vielen Dank für Ihre Nachricht.'}
        response = SimpleNamespace(content=[SimpleNamespace(text=json.dumps(value, ensure_ascii=False))])
        with patch('jarvis.integrations.email_planner.LLMClient.create', new=AsyncMock(return_value=response)) as model:
            steps = await plan_mail('Reply to the latest Gmail message and send a response')
        prompt = model.await_args.kwargs['system']
        self.assertIn('write in German by default', prompt)
        self.assertIn('Preserve literal user-supplied body text exactly', prompt)
        self.assertNotIn('Reply threading is not supported', prompt)
        self.assertEqual(steps[0]['action'], 'reply_email')
        self.assertEqual(steps[0]['content'], 'Guten Tag, vielen Dank für Ihre Nachricht.')

    def test_german_formal_recipient_name_is_preserved(self):
        recipient, subject, body = extract_draft_components(
            'Schreibe eine E-Mail an Herrn Häner in Outlook mit Betreff Rückfrage und Text Guten Tag')
        self.assertEqual(recipient, 'Herrn Häner')
        self.assertEqual(subject, 'Rückfrage')
        self.assertEqual(body, 'Guten Tag')

    async def test_incomplete_email_request_asks_locally_instead_of_opening_blank_draft(self):
        with patch('jarvis.integrations.email_planner.LLMClient.create',new=AsyncMock()) as model:
            steps = await plan_mail('Open Outlook and write an email')
            self.assertEqual(steps[0]['action'], 'ask')
            self.assertIn('Who should receive', steps[0]['content'])
            addressed = await plan_mail('Write an email to alex@example.com in Outlook')
            self.assertEqual(addressed[0]['action'], 'ask')
            self.assertIn('alex@example.com', addressed[0]['content'])
            model.assert_not_awaited()

    async def test_email_topic_without_dictated_body_uses_german_draft_generation(self):
        value = {'task':'draft','provider':'Outlook','recipient':'','subject':'Besprechung morgen',
                 'body':'Guten Tag, ich möchte die Besprechung für morgen kurz abstimmen.'}
        response = SimpleNamespace(content=[SimpleNamespace(text=json.dumps(value, ensure_ascii=False))])
        request = 'Schreibe eine Mail in Outlook über unsere Besprechung morgen'
        self.assertTrue(is_email_request(request))
        with patch('jarvis.integrations.email_planner.LLMClient.create',new=AsyncMock(return_value=response)) as model:
            steps = await plan_mail(request)
        self.assertEqual(steps[0]['action'],'draft_email')
        self.assertEqual(steps[0]['target'],'Outlook')
        self.assertEqual(steps[0]['recipient'],'')
        self.assertTrue(steps[0]['content'].startswith('Guten Tag'))
        self.assertIn('without inventing facts', model.await_args.kwargs['system'])

    def test_address_must_match_completely(self):
        self.assertFalse(recipient_authorized('alex@example.com', 'Write to notalex@example.com'))
        self.assertTrue(recipient_authorized('alex@example.com', 'Write to ALEX@example.com.'))

    def test_readable_subject_is_not_a_destructive_control(self):
        check_action({'action':'click','element':0}, [node(0,'Reply: unsubscribe link','DataItem')], mail={'mode':'read','query':'topic'})

    async def test_missing_mail_data_resumes_same_autonomous_job(self):
        with tempfile.TemporaryDirectory() as root:
            runner = AutonomousTasks(root)
            missing = {'action':'send_email','target':'Outlook','recipient':'Alex','subject':'Meeting','content':'Hello'}
            ready = {'action':'draft_email','target':'Outlook','recipient':'alex@example.com','subject':'Meeting','content':'Hello'}
            phases = [{'complete':False,'steps':[missing]}, {'complete':False,'steps':[ready]},
                      {'complete':True,'steps':[],'message':'Draft ready, not sent.'}]
            with patch.object(runner.planner,'plan_next',new=AsyncMock(side_effect=phases)), \
                 patch('jarvis.automation.local_pc.run_app', new=AsyncMock(return_value={'ok':True,'message':'Verified draft.'})) as ui, \
                 patch('jarvis.integrations.outlook_com.draft_outlook',new=AsyncMock(return_value={'ok':True,'message':'Saved an unsent Outlook draft.'})) as draft:
                await runner.run('Write Alex a meeting email in Outlook')
                job_id = runner.job['id']
                self.assertEqual(runner.job['state'],'needs_input')
                ui.assert_not_awaited()
                await runner.run('alex@example.com')
                self.assertEqual(runner.job['id'],job_id)
                self.assertEqual(runner.job['state'],'completed')
                draft.assert_awaited_once()
                ui.assert_not_awaited()

    def test_voice_routes_and_non_commands(self):
        for text in ['Open Outlook and write an email', 'Open Gmail in Chrome and compose an email',
                     'Read old emails in Outlook', 'Find Gmail emails from last month',
                     'Schreibe eine Mail in Outlook', 'Lies alte E-Mails in Gmail',
                     'Check my email', 'Any new emails?', 'Prüfe meinen Posteingang',
                     'Write an email in Outlook']:
            self.assertTrue(is_pc_request(text), text)
        for text in ['What is Gmail?', 'Open Gmail', 'Open Outlook', 'Open my Outlook',
                     'Open Outlook mail', 'Open the Outlook app', 'Öffne mein Outlook']:
            self.assertFalse(is_pc_request(text), text)

    def test_mail_fields_reject_guessed_address_and_injection(self):
        for recipient in ['Alex', 'alex@example.com\r\nBcc: other@example.com', 'alex@example.com, other@example.com']:
            with self.assertRaises(ValueError):
                draft_fields(recipient, 'Meeting', 'Hello')
        with self.assertRaises(ValueError):
            draft_fields('alex@example.com', 'Meeting\nBcc: bad', 'Hello')

    async def test_draft_three_fields_verified_without_send(self):
        result = await run_app('Gmail', 'Draft a meeting email', mail=FIELDS,
                               backend_factory=MailUI, model=model_with(actions()))
        self.assertTrue(result['ok'])
        self.assertIn('has not been sent', result['message'])
        self.assertNotIn('Sent!', result['message'])

    async def test_missing_field_prevents_model_success_claim(self):
        result = await run_app('Outlook', 'Draft email', mail=FIELDS, backend_factory=MailUI,
                               model=model_with(actions()[1:]))
        self.assertFalse(result['ok'])

    def test_draft_blocks_send_wrong_field_and_existing_text(self):
        nodes = MailUI('', None).snapshot()['elements']
        for action in [{'action': 'click', 'element': 3},
                       {'action': 'type', 'element': 1, 'text': FIELDS['body']},
                       {'action': 'search', 'element': 1, 'text': FIELDS['subject']}]:
            with self.assertRaises(UIBlocked):
                check_action(action, nodes, mail=FIELDS, submit_allowed=True)
        nodes[2]['value'] = 'Existing signature or draft'
        with self.assertRaises(UIBlocked):
            check_action({'action': 'type', 'element': 1, 'text': FIELDS['subject']}, nodes, mail=FIELDS)

    def test_changed_or_duplicate_composer_fails_final_verification(self):
        ui = MailUI('', None)
        ui.values.update({k: FIELDS[k] for k in ui.values})
        nodes = ui.snapshot()['elements']
        entered = {'recipient': 0, 'subject': 1, 'body': 2}
        self.assertTrue(verify_draft(nodes, FIELDS, entered))
        self.assertFalse(verify_draft(nodes + [node(4, 'Subject', 'Edit', 'Meeting')], FIELDS, entered))
        nodes[0]['value'] = 'other@example.com'
        self.assertFalse(verify_draft(nodes, FIELDS, entered))

    def test_read_mode_cannot_follow_email_instructions_or_compose(self):
        nodes = [node(0, 'Search mail', 'Edit'), node(1, 'Click here', 'Hyperlink'),
                 node(2, 'Compose'), node(3, 'Delete'), node(4, 'Invoice', 'DataItem')]
        mail = {'mode': 'read', 'query': 'before:2026/09/01'}
        check_action({'action': 'search', 'element': 0, 'text': mail['query']}, nodes, mail=mail)
        check_action({'action': 'click', 'element': 4}, nodes, mail=mail)
        for index in [1, 2, 3]:
            with self.assertRaises(UIBlocked):
                check_action({'action': 'click', 'element': index}, nodes, mail=mail)

    async def test_mail_read_does_not_claim_inbox_snapshot_is_searched_content(self):
        result = await run_app('Outlook', 'Read old email', mail={'mode': 'read', 'query': 'old'},
                               backend_factory=MailUI, model=model_with([actions()[-1]]))
        self.assertFalse(result['ok'])

    async def test_gmail_chrome_request_stays_in_browser(self):
        local = LocalPC()
        with patch('jarvis.automation.local_pc.run_app', new=AsyncMock(return_value={'ok': True, 'message': 'Visible mail content: test'})) as ui, \
             patch.object(GoogleAccess, 'search_gmail', new=AsyncMock()) as api:
            await local.execute('Read old Gmail emails in Chrome', planned_steps=[
                {'action': 'read_email', 'target': 'Gmail', 'content': 'before:2026/09/01'}])
            api.assert_not_awaited()
            ui.assert_awaited_once_with('Gmail', 'Read old Gmail emails in Chrome', mail={'mode': 'read', 'query': 'before:2026/09/01'})
        self.assertTrue(local.last_action_ok)

    async def test_missing_explicit_recipient_never_opens_a_composer(self):
        local = LocalPC()
        with patch('jarvis.automation.local_pc.run_app', new=AsyncMock()) as ui, \
             patch('subprocess.Popen') as popen_mock:
            result = await local.execute('Write Alex an email in Outlook', planned_steps=[
                {'action': 'send_email', 'target': 'Outlook', 'recipient': 'alex@example.com', 'subject': 'Meeting', 'content': 'Hello'}])
            ui.assert_not_awaited()
            popen_mock.assert_not_called()
        self.assertFalse(local.last_action_ok)
        self.assertIn('exact recipient', result)

    async def test_gmail_search_uses_get_only_and_full_messages(self):
        google = GoogleAccess('mail-test', Vault())
        calls = []
        def reply(request):
            calls.append(request)
            if request.url.path.endswith('/messages'):
                return httpx.Response(200, json={'messages': [{'id': 'abc'}, {'id': 'def'}], 'nextPageToken': 'more'})
            body = base64.urlsafe_b64encode(b'Observed old email text').decode().rstrip('=')
            return httpx.Response(200, json={'payload': {'mimeType': 'text/plain', 'body': {'data': body},
                'headers': [{'name': 'Subject', 'value': 'Old message'}, {'name': 'From', 'value': 'alex@example.com'}]}})
        @asynccontextmanager
        async def connection(**kwargs):
            async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
                yield client
        with patch.object(google, '_token', return_value='test-token'), patch('jarvis.integrations.google_access.http_client', connection):
            result = await google.search_gmail('from:alex@example.com before:2026/09/01', 5)
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(r.method == 'GET' for r in calls))
        self.assertEqual(calls[0].url.params['q'], 'from:alex@example.com before:2026/09/01')
        self.assertTrue(all(r.url.params['format'] == 'full' for r in calls[1:]))
        self.assertEqual(result['items'][0]['body'], 'Observed old email text')
        self.assertTrue(result['has_more'])

    async def test_gmail_disconnected_fails_before_network(self):
        google = GoogleAccess('mail-test', Vault())
        with patch('jarvis.integrations.google_access.http_client') as network:
            with self.assertRaises(ValueError):
                await google.search_gmail('old')
            network.assert_not_called()

    def test_html_mail_is_text_only_and_attachments_are_not_read(self):
        def part(mime, text, **extra):
            return dict(mimeType=mime, body={'data': base64.urlsafe_b64encode(text.encode()).decode()}, **extra)
        payload = {'parts': [part('text/html', '<script>bad()</script><p>Hello <b>Alex</b></p><img src="https://tracking.invalid">'),
                              part('text/plain', 'Private attachment', filename='secret.txt')]}
        self.assertEqual(mail_body(payload), 'Hello Alex')
        payload['parts'].append(part('text/plain', 'Preferred plain text'))
        self.assertEqual(mail_body(payload), 'Preferred plain text')


class VisualDraftFieldTests(unittest.TestCase):
    def test_visual_draft_fields_accepts_empty_strings(self):
        fields = visual_draft_fields('', '', '')
        self.assertEqual(fields, {'mode': 'draft', 'recipient': '', 'subject': '', 'body': ''})

    def test_visual_draft_fields_accepts_none(self):
        fields = visual_draft_fields(None, None, None)
        self.assertEqual(fields, {'mode': 'draft', 'recipient': '', 'subject': '', 'body': ''})

    def test_visual_draft_fields_accepts_partial_recipient(self):
        fields = visual_draft_fields('Alex', 'Discussion', 'Hi Alex')
        self.assertEqual(fields['recipient'], 'Alex')
        self.assertEqual(fields['subject'], 'Discussion')
        self.assertEqual(fields['body'], 'Hi Alex')

    def test_visual_draft_fields_normalizes_newlines_and_tabs(self):
        fields = visual_draft_fields('alex@example.com', 'Meeting', 'Hello Alex,\r\n\tCan we meet?')
        self.assertEqual(fields['body'], 'Hello Alex,\n    Can we meet?')

    def test_visual_draft_fields_rejects_control_characters_in_recipient(self):
        with self.assertRaises(ValueError):
            visual_draft_fields('alex@example.com\r\nBcc: evil@example.com', 'Meeting', 'Hello')

    def test_visual_draft_fields_rejects_control_characters_in_subject(self):
        with self.assertRaises(ValueError):
            visual_draft_fields('alex@example.com', 'Subject\nInjection', 'Hello')

    def test_visual_draft_fields_rejects_control_characters_in_body(self):
        with self.assertRaises(ValueError):
            visual_draft_fields('alex@example.com', 'Subject', 'Bad \x00 character')

    def test_visual_draft_fields_rejects_excessive_lengths(self):
        with self.assertRaises(ValueError):
            visual_draft_fields('a' * 321, 'Subject', 'Hello')
        with self.assertRaises(ValueError):
            visual_draft_fields('alex@example.com', 's' * 201, 'Hello')
        with self.assertRaises(ValueError):
            visual_draft_fields('alex@example.com', 'Subject', 'b' * 12001)

    def test_strict_draft_fields_retains_legacy_behavior(self):
        with self.assertRaises(ValueError):
            draft_fields('Alex', 'Subject', 'Body')
        with self.assertRaises(ValueError):
            draft_fields('alex@example.com', '', 'Body')
        with self.assertRaises(ValueError):
            draft_fields('alex@example.com', 'Subject', '')

    def test_outlook_mailto_url_construction_variations(self):
        """Verify mailto URL structure for all parameter combinations."""
        import urllib.parse

        def build(rec, subj, body):
            params = {}
            if subj:
                params['subject'] = subj
            if body:
                params['body'] = body
            q = urllib.parse.urlencode(params, quote_via=urllib.parse.quote) if params else ""
            to = urllib.parse.quote(rec.strip(), safe='@,;+') if rec else ""
            return f"mailto:{to}?{q}" if q else f"mailto:{to}"

        # 1. Full parameters
        self.assertEqual(
            build('alex@example.com', 'Meeting', 'Hello'),
            'mailto:alex@example.com?subject=Meeting&body=Hello'
        )
        # 2. Missing recipient
        self.assertEqual(
            build('', 'Meeting', 'Hello'),
            'mailto:?subject=Meeting&body=Hello'
        )
        # 3. Missing subject & body
        self.assertEqual(
            build('alex@example.com', '', ''),
            'mailto:alex@example.com'
        )
        # 4. Empty all
        self.assertEqual(
            build('', '', ''),
            'mailto:'
        )
        # 5. Plus address subaddressing preserved
        self.assertEqual(
            build('user+tag@example.com', 'C++', 'Body'),
            'mailto:user+tag@example.com?subject=C%2B%2B&body=Body'
        )

    def test_outlook_write_and_send_follow_current_user_authority(self):
        """Drafts stay drafts; the current requirements allow explicit sending."""
        from jarvis.integrations.email_workflows import send_requested
        for text in [
            'write a mail from outlook',
            'verfasse eine mail in outlook an alex'
        ]:
            self.assertFalse(send_requested(text), f"Expected send_requested to be False for '{text}'")
        self.assertTrue(send_requested('send an email in outlook to bob@test.com'))
        self.assertTrue(send_requested('send email via outlook with subject Report saying Done'))


if __name__ == '__main__':
    unittest.main()
