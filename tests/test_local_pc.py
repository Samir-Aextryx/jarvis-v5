import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
from jarvis.automation.local_pc import LocalPC, is_pc_request, write_desktop
from jarvis.automation.pc_fastpath import fast_plan, unsupported_action_plan
from jarvis.voice.voice_turn import TurnSocket


class LocalPCTests(unittest.IsolatedAsyncioTestCase):
    async def test_open_outlook_and_compose_opens_locally_before_asking_for_details(self):
        local = LocalPC()
        with patch('jarvis.automation.local_pc.open_app', new=AsyncMock(return_value={
                'success': True, 'confirmation': 'Opening Outlook.'})) as open_app, \
             patch('jarvis.integrations.email_planner.LLMClient.create', new=AsyncMock(
                 side_effect=AssertionError('Missing mail details should be handled locally'))):
            result = await local.execute('Öffne mein Outlook und schreibe eine E-Mail')
        self.assertIn('Who should receive the email', result)
        open_app.assert_awaited_once_with('Outlook')

    async def test_slow_general_planning_stops_before_any_pc_action(self):
        local = LocalPC()

        async def slow_create(_client, **_kwargs):
            await asyncio.sleep(1)

        with patch('jarvis.automation.local_pc.PC_PLANNING_TIMEOUT_SECONDS', .01), \
             patch('jarvis.automation.local_pc.LLMClient.create', new=slow_create), \
             patch('jarvis.automation.local_pc.open_app', new=AsyncMock()) as open_app:
            result = await local.execute('Organize my downloads folder')

        self.assertIn('within a few seconds', result)
        open_app.assert_not_awaited()

    async def test_complex_plan_uses_openai_schema(self):
        import json
        from types import SimpleNamespace
        from jarvis.automation.local_pc import SCHEMA
        steps = [{'action':'open_app','target':'Chrome','content':'','recipient':''}]
        response = SimpleNamespace(content=[SimpleNamespace(text=json.dumps({'steps':steps}))])
        with patch('jarvis.automation.local_pc.LLMClient.create',new=AsyncMock(return_value=response)) as create:
            self.assertEqual(await LocalPC().plan('Open Chrome and open Notepad'), steps)
            self.assertEqual(create.call_args.kwargs['json_schema'], SCHEMA)

    async def test_complete_outlook_email_skips_llm_and_preserves_provider(self):
        request = ('Write an email to alex@example.com in Outlook with subject Meeting '
                   'saying Hello Alex')
        with patch('jarvis.automation.local_pc.plan_mail', new=AsyncMock(
                side_effect=AssertionError('A complete email draft is deterministic'))):
            steps = await LocalPC().plan(request)
        self.assertEqual(steps, [{'action':'draft_email','target':'Outlook',
                                 'recipient':'alex@example.com','subject':'Meeting',
                                 'content':'Hello Alex'}])

    async def test_autonomous_follow_up_skips_redundant_serial_jev_hint(self):
        import json
        from types import SimpleNamespace
        phase = {'complete': False, 'message': '', 'steps': [{
            'action': 'open_app', 'target': 'Notepad', 'content': '',
            'recipient': '', 'subject': ''}]}
        response = SimpleNamespace(content=[SimpleNamespace(text=json.dumps(phase))])
        with patch('jarvis.core.agent_router.next_tool_hint',
                   new=AsyncMock(side_effect=AssertionError('Redundant JEV hop must be skipped'))) as hint, \
             patch('jarvis.automation.local_pc.LLMClient.create',
                   new=AsyncMock(return_value=response)) as create:
            result = await LocalPC().plan_next(
                'Read my notes and open Notepad',
                observations=[{'step': {'action': 'read_file'}, 'success': True,
                               'result': 'The note contents were read.'}])

        self.assertEqual(result, phase)
        hint.assert_not_awaited()
        create.assert_awaited_once()
        schema_actions = create.call_args.kwargs['json_schema']['properties']['steps']['items']['properties']['action']['enum']
        self.assertIn('open_app', schema_actions)
        self.assertNotIn('send_email', schema_actions)
        planner_system = create.call_args.kwargs['system']
        self.assertIn('untrusted data', planner_system)
        self.assertNotIn('send_email DIRECTLY', planner_system)
        self.assertLess(len(planner_system), 2500)

    async def test_email_follow_up_keeps_mail_actions_available(self):
        import json
        from types import SimpleNamespace
        phase = {'complete': False, 'message': '', 'steps': [{
            'action': 'send_email', 'target': 'Gmail', 'content': 'The meeting starts at ten.',
            'recipient': 'alex@example.com', 'subject': 'Meeting'}]}
        response = SimpleNamespace(content=[SimpleNamespace(text=json.dumps(phase))])
        observation = [{'step': {'action': 'read_email'}, 'success': True,
                        'result': 'The meeting starts at ten.'}]
        with patch('jarvis.automation.local_pc.LLMClient.create',
                   new=AsyncMock(return_value=response)) as create:
            result = await LocalPC().plan_next(
                'Read Gmail and send the meeting time to alex@example.com',
                observations=observation)

        self.assertEqual(result, phase)
        schema_actions = create.call_args.kwargs['json_schema']['properties']['steps']['items']['properties']['action']['enum']
        self.assertIn('send_email', schema_actions)
        self.assertIn('read_email', schema_actions)
        planner_system = create.call_args.kwargs['system']
        self.assertIn('send_email DIRECTLY', planner_system)
        self.assertIn('untrusted data', planner_system)
        self.assertIn('German', planner_system)
        self.assertIn("Write requested mail from the user's stated topic", planner_system)
        self.assertIn('Never send to Herr Häner', planner_system)
        self.assertIn('Outlook threaded replies are unsupported', planner_system)
        self.assertIn('older_than:', planner_system)
        self.assertIn('set complete=false when steps are returned', planner_system)
        self.assertIn('Leave message empty for ordinary pending phases', planner_system)
        self.assertLess(len(planner_system), 4300)

    async def test_initial_email_planning_has_a_short_network_deadline(self):
        async def slow_mail(_goal):
            await asyncio.sleep(1)

        with patch('jarvis.automation.local_pc.MAIL_PLANNING_TIMEOUT_SECONDS', .01), \
             patch('jarvis.automation.local_pc.plan_mail', new=slow_mail):
            with self.assertRaises(TimeoutError):
                await LocalPC().plan_next('Read my Gmail and send a summary to alex@example.com')

    async def test_follow_up_planning_compacts_old_results_and_caps_recent_context(self):
        import json
        from types import SimpleNamespace
        phase = {'complete': False, 'message': '', 'steps': [{
            'action': 'open_app', 'target': 'Notepad', 'content': '',
            'recipient': '', 'subject': ''}]}
        response = SimpleNamespace(content=[SimpleNamespace(text=json.dumps(phase))])
        observations = []
        for index in range(8):
            observations.append({
                'step': {'action': 'read_email' if index < 5 else 'read_file',
                         'target': 'Mailbox', 'content': 'C' * 10000,
                         'recipient': 'samir@example.com', 'subject': 'S' * 500},
                'success': True, 'result': 'R' * 8000})
        with patch('jarvis.automation.local_pc.LLMClient.create',
                   new=AsyncMock(return_value=response)) as create:
            result = await LocalPC().plan_next('Summarize my sources and open Notepad',
                                               observations=observations)

        self.assertEqual(result, phase)
        payload_text = create.call_args.kwargs['messages'][0]['content']
        payload = json.loads(payload_text)
        planned_observations = payload['observations']
        self.assertEqual(len(planned_observations), len(observations))
        self.assertNotIn('content', planned_observations[0]['step'])
        self.assertEqual(len(planned_observations[0]['result']), 500)
        self.assertEqual(len(planned_observations[-1]['result']), 4000)
        self.assertLess(len(payload_text), 20000)

    async def test_unrelated_previous_reply_is_not_sent_to_pc_planner(self):
        import json
        from types import SimpleNamespace
        response = SimpleNamespace(content=[SimpleNamespace(text=json.dumps({'steps':[
            {'action':'ask','target':'','content':'Which folder?','recipient':'','subject':''}]}))])
        with patch('jarvis.automation.local_pc.LLMClient.create', new=AsyncMock(return_value=response)) as create:
            await LocalPC().plan('Organize my downloads folder', previous='x' * 4000)
        payload = json.loads(create.call_args.kwargs['messages'][0]['content'])
        self.assertEqual(payload['previous_answer'], '')

    async def test_referenced_previous_reply_is_kept_but_capped(self):
        import json
        from types import SimpleNamespace
        response = SimpleNamespace(content=[SimpleNamespace(text=json.dumps({'steps':[
            {'action':'ask','target':'','content':'Which folder?','recipient':'','subject':''}]}))])
        previous = 'x' * 4000
        with patch('jarvis.automation.local_pc.LLMClient.create', new=AsyncMock(return_value=response)) as create:
            await LocalPC().plan('Do that now', previous=previous)
        payload = json.loads(create.call_args.kwargs['messages'][0]['content'])
        self.assertEqual(payload['previous_answer'], previous[-1600:])

    async def test_clear_commands_work_without_network(self):
        with patch('jarvis.automation.local_pc.LLMClient.create', new=AsyncMock(side_effect=AssertionError('No inference needed'))):
            plan = await LocalPC().plan('Jarvis, can you please open ChatGPT and prompt it to improve Jarvis v5')
            self.assertEqual(plan[0]['action'], 'chatgpt_prompt')
            self.assertEqual(plan[0]['content'], 'improve Jarvis v5')
            plan = await LocalPC().plan('Save a file called test.txt to Desktop with the content Hello, Samir!')
            self.assertEqual(plan[0]['content'], 'Hello, Samir!')

    def test_explicit_local_reads_have_exact_fast_plans(self):
        file_plan=fast_plan('Read the file "C:\\Users\\Samir\\Documents\\notes for Jarvis.txt".')
        self.assertEqual(file_plan[0]['action'],'read_file')
        self.assertEqual(file_plan[0]['target'],r'C:\Users\Samir\Documents\notes for Jarvis.txt')
        batch=fast_plan(r'Read files "C:\Users\Samir\a.txt" and "C:\Users\Samir\b.md"')
        self.assertEqual([step['target'] for step in batch],
                         [r'C:\Users\Samir\a.txt',r'C:\Users\Samir\b.md'])
        self.assertTrue(all(step['action']=='read_file' for step in batch))
        german_request=r'Lies die Dateien "C:\Users\Samir\a.txt" und "C:\Users\Samir\b.md"'
        german_batch=fast_plan(german_request)
        self.assertEqual([step['target'] for step in german_batch],
                         [r'C:\Users\Samir\a.txt',r'C:\Users\Samir\b.md'])
        self.assertTrue(is_pc_request(german_request))
        self.assertIsNone(fast_plan(r'Read files "C:\Users\Samir\a.txt" and "C:\Users\Samir\b.md" and summarize them'))
        folder_plan=fast_plan('List the folder C:\\Users\\Samir\\Documents')
        self.assertEqual(folder_plan[0]['action'],'list_folder')
        self.assertEqual(folder_plan[0]['target'],r'C:\Users\Samir\Documents')
        self.assertIsNone(fast_plan(r'Read the file C:\Users\Samir\note.txt and open Chrome'))

    async def test_explicit_file_read_then_app_open_is_decomposed_locally(self):
        expected = [
            {'action':'read_file','target':r'C:\Users\Samir\Documents\notes.txt','content':'','recipient':'','subject':''},
            {'action':'open_app','target':'Outlook','content':'','recipient':'','subject':''},
        ]
        requests = [
            r'Read the file "C:\Users\Samir\Documents\notes.txt" and open Outlook',
            r'Lies die Datei "C:\Users\Samir\Documents\notes.txt" und öffne Outlook',
        ]
        with patch('jarvis.automation.local_pc.LLMClient.create', new=AsyncMock(
                side_effect=AssertionError('A named local read and app open are deterministic'))):
            for request in requests:
                with self.subTest(request=request):
                    planned = await LocalPC().plan_next(request)
                    direct = await LocalPC().plan(request)
                    self.assertTrue(planned['terminal'])
                    self.assertEqual(planned['steps'], expected)
                    self.assertEqual(direct, expected)

    async def test_autonomous_app_and_website_open_skip_network_planning(self):
        for request, action, expected in [
            ('Open Chrome', 'open_app', 'Chrome'),
            ('Open YouTube', 'open_url', 'https://www.youtube.com'),
        ]:
            with self.subTest(request=request), patch(
                'jarvis.automation.local_pc.LLMClient.create',
                new=AsyncMock(side_effect=AssertionError('Direct opens must not call the planner')),
            ):
                phase = await LocalPC().plan_next(request)

            self.assertTrue(phase['terminal'])
            self.assertEqual(len(phase['steps']), 1)
            self.assertEqual(phase['steps'][0]['action'], action)
            self.assertEqual(phase['steps'][0]['target'], expected)

    async def test_chatgpt_and_claude_prompt_commands_are_fast_and_distinct(self):
        for phrase, action, content in [
            ('Open ChatGPT and prompt it to improve Jarvis v5', 'chatgpt_prompt', 'improve Jarvis v5'),
            ('Open Claude and tell it to change the Jarvis meeting memory', 'claude_prompt', 'change the Jarvis meeting memory'),
            ('Tell Claude to improve the German name recognition', 'claude_prompt', 'improve the German name recognition'),
            ('Öffne Claude und sage ihm verbessere Jarvis v5', 'claude_prompt', 'verbessere Jarvis v5'),
            ('Frag Claude, wie hoch der Eiffelturm ist', 'claude_prompt', 'wie hoch der Eiffelturm ist'),
            ('Sag Claude er soll Jarvis verbessern', 'claude_prompt', 'Jarvis verbessern'),
            ('Schreib Claude dass die Tests fehlschlagen', 'claude_prompt', 'die Tests fehlschlagen'),
            ('Frage ChatGPT was ein Transformer ist', 'chatgpt_prompt', 'was ein Transformer ist'),
        ]:
            with self.subTest(phrase=phrase), patch('jarvis.automation.local_pc.LLMClient.create', new=AsyncMock(side_effect=AssertionError('No planning request needed'))):
                self.assertTrue(is_pc_request(phrase))
                plan=await LocalPC().plan(phrase)
                self.assertEqual(plan[0]['action'],action)
                self.assertEqual(plan[0]['content'],content)

    async def test_claude_prompt_opens_the_documented_desktop_link_without_a_model(self):
        for phrase, link, place in [
            ('Tell Claude to improve Jarvis v5 & more?', 'claude://claude.ai/new?q=improve%20Jarvis%20v5%20%26%20more%3F', 'Claude chat'),
            ('Sag Claude Code er soll die Tests reparieren', 'claude://code/new?q=die%20Tests%20reparieren', 'Claude Code session'),
        ]:
            local=LocalPC()
            with self.subTest(phrase=phrase), \
                 patch('jarvis.automation.claude_desktop.claude_link_available',return_value=True), \
                 patch('jarvis.automation.claude_desktop.os.startfile') as startfile, \
                 patch('jarvis.automation.local_pc.LLMClient.create',new=AsyncMock(side_effect=AssertionError('No planning request needed'))), \
                 patch('jarvis.automation.local_pc.run_app',new=AsyncMock()) as run_app, \
                 patch('jarvis.automation.local_pc.open_app',new=AsyncMock()) as open_app:
                result=await local.execute(phrase)
                startfile.assert_called_once_with(link)
                self.assertIn(place,result)
                self.assertIn('press Enter',result)
                self.assertTrue(local.last_action_ok)
                run_app.assert_not_awaited()
                open_app.assert_not_awaited()

    async def test_claude_prompt_uses_the_app_when_no_link_handler_is_registered(self):
        local=LocalPC()
        with patch('jarvis.automation.claude_desktop.claude_link_available',return_value=False), \
             patch('jarvis.automation.claude_desktop.os.startfile') as startfile, \
             patch('jarvis.automation.local_pc.run_app',new=AsyncMock(return_value={'ok':True,'message':'Your prompt was submitted in Claude.'})) as send, \
             patch('jarvis.automation.local_pc.open_app',new=AsyncMock()) as open_app:
            result=await local.execute('Tell Claude to improve Jarvis v5')
        self.assertIn('submitted in Claude',result)
        self.assertEqual(send.call_args.args[0],'Claude')
        self.assertTrue(send.call_args.kwargs['submit_allowed'])
        startfile.assert_not_called()
        open_app.assert_not_awaited()

    def test_claude_link_rejects_empty_oversized_and_control_text(self):
        from jarvis.automation.claude_desktop import claude_prompt_link
        self.assertEqual(claude_prompt_link('Zeile 1\nZeile 2 ä&q=x'), 'claude://claude.ai/new?q=Zeile%201%0AZeile%202%20%C3%A4%26q%3Dx')
        for prompt in ['', '   ', 'x' * 14001, 'bad\x00text', None]:
            with self.subTest(prompt=prompt), self.assertRaises(ValueError):
                claude_prompt_link(prompt)

    async def test_known_unsupported_desktop_actions_fail_without_model_latency(self):
        local = LocalPC()
        with patch('jarvis.automation.local_pc.LLMClient.create', new=AsyncMock(side_effect=AssertionError('No planning request needed'))), \
             patch('jarvis.automation.local_pc.run_app', new=AsyncMock()) as run_app:
            for command in ('Open Snapchat and delete an old message',
                            'Lösche diese Datei',
                            'Upload this photo to Instagram',
                            'Change my account password in Chrome',
                            'Ändere das Passwort',
                            'Delete an email in Outlook'):
                self.assertTrue(is_pc_request(command), command)
                plan = await local.plan(command)
                self.assertEqual(plan[0]['action'], 'ask', command)
                self.assertIn("haven't been trained", plan[0]['content'], command)
            response = await local.execute('Open Snapchat and delete an old message')
        self.assertIn("haven't been trained", response)
        run_app.assert_not_awaited()

    def test_unsupported_preflight_preserves_calendar_edits_and_literal_message_text(self):
        self.assertIsNone(unsupported_action_plan('Delete my Jarvis calendar event'))
        self.assertIsNone(unsupported_action_plan('Open Snapchat and write a message to Franco saying delete the old photo'))
        self.assertIsNone(unsupported_action_plan('Open ChatGPT and prompt it to remove an unused import'))
        self.assertEqual(fast_plan('Open Snapchat and delete an old message')[0]['action'], 'ask')
        self.assertIsNone(unsupported_action_plan("Don't delete the email; only write a reply"))

    def test_voice_unsupported_action_is_answered_without_planner_or_app_access(self):
        from fastapi.testclient import TestClient
        import jarvis.server as server
        local = SimpleNamespace(pending='', last_action_silent=False,
            execute=AsyncMock(return_value="I can't do that yet because I haven't been trained for that action."))
        with patch.object(server, 'LocalPC', return_value=local), \
             patch.object(server.jev, 'configured', return_value=True), \
             patch.object(server.agent_router, 'route', new=AsyncMock()) as route, \
             patch.object(server.AutonomousTasks, 'start', return_value='') as autonomous, \
             patch.object(server, 'synthesize_speech', new=AsyncMock(return_value=None)):
            with TestClient(server.app) as client:
                with client.websocket_connect('/ws/voice', subprotocols=['jarvis', 'jarvis.auth.' + server.JARVIS_AUTH_TOKEN]) as ws:
                    ws.send_json({'type': 'transcript', 'text': 'Open Snapchat and delete an old message', 'isFinal': True})
                    for _ in range(8):
                        event = ws.receive_json()
                        if event.get('type') == 'text':
                            self.assertIn("haven't been trained", event['text'])
                            break
                    else:
                        self.fail('No fast unsupported-action response')
        local.execute.assert_awaited_once_with('Open Snapchat and delete an old message', '', planned_steps=[{
            'action': 'ask', 'target': '',
            'content': "I can't do that yet because I haven't been trained for that action."}])
        route.assert_not_awaited()
        autonomous.assert_not_called()

    async def test_new_request_replaces_old_clarification(self):
        local = LocalPC()
        local.pending = 'Save a file to desktop'
        with patch.object(local, 'plan', new=AsyncMock(return_value=[{'action':'ask','target':'','content':'What message?'}])) as planner:
            await local.execute('Open Snapchat and write a message to Branko')
            self.assertNotIn('clarification', planner.call_args.args[0])

    def test_routing(self):
        for text in ['Open Snapchat and write a message to Branko', 'Open Snapchat write a messag to Branko', 'Open ChatGPT and prompt it to improve Jarvis v5', 'Save a file to desktp', 'Write notes.txt on Desktop', 'Tell Codex to debug my code', 'Open Snapchat and delete an old message']:
            self.assertTrue(is_pc_request(text), text)
        for text in ['What is ChatGPT?', 'Open YouTube', 'What file should I save?', 'Good morning']:
            self.assertFalse(is_pc_request(text), text)

    async def test_snapchat_asks_for_actual_message(self):
        plan = await LocalPC().plan('Open Snapchat and write a message to Branko')
        self.assertEqual(plan[0]['action'], 'ask')
        self.assertEqual(plan[0]['content'], 'What would you like to tell Branko?')

    def test_real_file_creation_and_no_overwrites(self):
        with tempfile.TemporaryDirectory() as root, patch('jarvis.automation.local_pc.desktop', return_value=Path(root)):
            write_desktop('notes.txt', 'Hello from Jarvis')
            self.assertEqual(Path(root, 'notes.txt').read_text(), 'Hello from Jarvis')
            with self.assertRaises(FileExistsError):
                write_desktop('notes.txt', 'replacement')
            for name in ['../escape.txt', r'C:\escape.txt', 'test.txt:stream', 'test.cmd', 'CON.txt']:
                with self.assertRaises(ValueError):
                    write_desktop(name, 'text')

    async def test_clarification_does_not_act(self):
        local = LocalPC()
        with patch.object(local, 'plan', new=AsyncMock(return_value=[{'action':'ask','target':'','content':'What filename and content?'}])), patch('jarvis.automation.local_pc.write_desktop') as write:
            self.assertIn('filename', await local.execute('Save a file to Desktop'))
            self.assertTrue(local.pending)
            write.assert_not_called()

    async def test_chatgpt_is_not_an_app_name_or_codex(self):
        local = LocalPC()
        steps = [{'action':'chatgpt_prompt','target':'','content':'Improve Jarvis v5'}]
        with patch.object(local, 'plan', new=AsyncMock(return_value=steps)), patch('jarvis.automation.local_pc.run_app', new=AsyncMock(return_value={'ok':True,'message':'Your prompt was submitted in ChatGPT.'})) as send, patch('jarvis.automation.local_pc.open_app') as app:
            self.assertIn('submitted',await local.execute('Open ChatGPT and prompt it to improve Jarvis v5'))
            self.assertEqual(send.call_args.args[0],'ChatGPT')
            self.assertEqual(send.call_args.kwargs['literal'],'Improve Jarvis v5')
            app.assert_not_called()

    async def test_cancelled_turn_cannot_emit_late_audio(self):
        active = True
        raw = AsyncMock()
        wrapped = TurnSocket(raw, lambda: active)
        await wrapped.send_json({'type':'pcm_start'})
        active = False
        await wrapped.send_json({'type':'audio','data':'stale'})
        self.assertEqual(raw.send_json.await_count,1)

    def test_stop_interrupts_active_server_turn(self):
        import jarvis.server as server
        from fastapi.testclient import TestClient
        started, cancelled = threading.Event(), threading.Event()
        async def slow(*args, **kwargs):
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise
        with patch.object(server,'_last_greeting_time',time.time()), patch.object(LocalPC,'execute',new=slow), patch.object(LocalPC,'plan_next',new=AsyncMock(return_value={'complete':False,'steps':[{'action':'open_app','target':'Chrome','content':'','recipient':''}]})):
            with TestClient(server.app) as client:
                with client.websocket_connect('/ws/voice', subprotocols=['jarvis', 'jarvis.auth.' + server.JARVIS_AUTH_TOKEN]) as ws:
                    ws.receive_json()
                    ws.send_json({'type':'transcript','isFinal':True,'text':'Open Chrome and open Notepad'})
                    self.assertTrue(started.wait(3))
                    ws.send_json({'type':'stop','cancelTasks':True})
                    for _ in range(12):
                        if ws.receive_json()['type']=='stopped': break
                    else: self.fail('No stop acknowledgement')
                    self.assertTrue(cancelled.wait(1))
