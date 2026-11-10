import asyncio
import os
import re
import sys
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, os.getcwd())

from jarvis.voice.speech_language import is_banned_confirmation, english_speech
from jarvis.automation.local_pc import LocalPC
import jarvis.server as server


class BannedConfirmationsFilterTests(unittest.TestCase):
    def test_banned_confirmation_phrases(self):
        banned_samples = [
            "I am working on your task",
            "I am working on your task.",
            "I'm working on your task, sir.",
            "Working on your task, sir.",
            "Working on your task",
            "On it",
            "On it, sir.",
            "On it!",
            "I'm on it, sir.",
            "I am on it.",
            "Building it now, sir.",
            "Building it now.",
            "Building that now, sir.",
            "Understood, sir.",
            "Understood.",
            "Right away, sir.",
            "Right away.",
            "Looking into that now, sir.",
            "Looking into that now.",
            "Looking into it now, sir.",
            "Connecting to project now, sir.",
            "Connecting now, sir.",
            "Claude Code is working in project.",
            "Codex is working in project.",
            "Consider it done, sir.",
            "Consider it done.",
            "Will do, sir.",
            "Will do.",
            "Certainly, sir.",
            "Certainly.",
            "Still working on it, sir.",
            "Working on it, sir.",
            "Getting right on that, sir.",
            "I will get right on that, sir.",
            "Starting now, sir.",
            "Opened Gmail composer for alex@example.com.",
            "Opened Outlook composer for alex@example.com.",
            "Opened Gmail composer.",
            "Opened Outlook composer.",
            "Ich bin dran.",
            "Ich bin dran, Sir.",
            "Wird erledigt, Sir.",
            "Verstanden, Sir.",
            "Verstanden.",
            "Ich arbeite an Ihrer Aufgabe.",
            "On it, sir. Building it now, sir.",
            "Understood, sir. Right away, sir."
        ]
        for phrase in banned_samples:
            with self.subTest(phrase=phrase):
                self.assertTrue(is_banned_confirmation(phrase), f"Expected '{phrase}' to be recognized as banned confirmation.")

    def test_non_banned_legitimate_speech(self):
        valid_samples = [
            "Testing audio, sir.",
            "Something went wrong, sir.",
            "Opening Google Chrome.",
            "Opening Notepad.",
            "Saved notes.txt to your Desktop.",
            "Here is the summary of your emails.",
            "The weather in Paris is sunny and 22 degrees.",
            "Which app do you mean: Chrome or Firefox?",
            "Who is the message for, and what should it say?",
            "Understood, sir. Here is the answer you requested: 42.",
            "I found 3 emails from Alex in your inbox.",
            "Available drives: drive C, drive D.",
            "The app could not be started. Please try again."
        ]
        for utterance in valid_samples:
            with self.subTest(utterance=utterance):
                self.assertFalse(is_banned_confirmation(utterance), f"Expected '{utterance}' NOT to be recognized as banned confirmation.")


class TTSPipelineSuppressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_synthesize_speech_drops_banned_phrases(self):
        mock_http = MagicMock()
        with patch.object(server, 'http_client', return_value=mock_http), \
             patch.object(server, 'FISH_API_KEY', 'test-key'):
            res = await server.synthesize_speech("I am working on your task")
            self.assertIsNone(res)
            res2 = await server.synthesize_speech("On it, sir.")
            self.assertIsNone(res2)
            mock_http.assert_not_called()

    async def test_stream_speech_drops_banned_phrases(self):
        ws = AsyncMock()
        with patch.object(server, 'FISH_API_KEY', 'test-key'):
            res = await server.stream_speech(ws, "I am working on your task")
            self.assertFalse(res)
            res2 = await server.stream_speech(ws, "Building it now, sir.")
            self.assertFalse(res2)
            ws.send_json.assert_not_awaited()

    async def test_english_speech_drops_banned_phrases(self):
        import jarvis.voice.speech_language as speech_language
        with patch.object(speech_language.LLMClient, 'create', new=AsyncMock(side_effect=AssertionError("Should not call LLM"))):
            self.assertEqual(await speech_language.english_speech("I am working on your task", "key"), "")
            self.assertEqual(await speech_language.english_speech("On it, sir.", "key"), "")
            self.assertEqual(await speech_language.english_speech("Understood, sir.", "key"), "")
            self.assertEqual(await speech_language.english_speech("Building it now, sir.", "key"), "")


class SilentEmailDraftActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_drafts_are_silent_for_both_providers(self):
        for provider in ('Gmail', 'Outlook'):
            for recipient in ('', 'alex@example.com'):
                local = LocalPC()
                step = dict(action='draft_email', target=provider, recipient=recipient, subject='Test', content='Hello')
                request = f'Draft an email in {provider} to {recipient}'
                with patch('jarvis.automation.local_pc.google_access.status', return_value={}), \
                     patch('jarvis.automation.local_pc.run_app', new=AsyncMock(return_value={'ok':True, 'message':'Verified composer.'})) as ui, \
                     patch('jarvis.integrations.outlook_com.draft_outlook', new=AsyncMock(return_value={'ok':True, 'message':'Verified unsent draft.'})) as outlook_draft:
                    await local.execute(request, planned_steps=[step])
                    self.assertTrue(local.last_action_ok)
                    self.assertTrue(local.last_action_silent)
                    if provider == 'Outlook' and recipient:
                        outlook_draft.assert_awaited_once()
                        ui.assert_not_awaited()
                    else:
                        self.assertFalse(ui.call_args.kwargs['mail']['submit_allowed'])
                        outlook_draft.assert_not_awaited()
                    with patch.object(local, 'plan', new=AsyncMock(return_value=[step])):
                        self.assertEqual(await local.execute(request), '')

    async def test_unverified_composer_is_not_silently_successful(self):
        for provider in ('Gmail', 'Outlook'):
            local=LocalPC()
            step=dict(action='draft_email',target=provider,recipient='',subject='',content='')
            with patch('jarvis.automation.local_pc.google_access.status',return_value={}), patch('jarvis.automation.local_pc.run_app',new=AsyncMock(return_value={'ok':False,'message':'Composer could not be verified.'})), patch.object(local,'plan',new=AsyncMock(return_value=[step])):
                result=await local.execute('Draft an email')
                self.assertFalse(local.last_action_ok)
                self.assertFalse(local.last_action_silent)
                self.assertIn('could not be verified',result)

    async def test_recipient_cannot_come_from_untrusted_observations(self):
        local=LocalPC()
        step=dict(action='draft_email',target='Outlook',recipient='unexpected@example.com',subject='Test',content='Hello')
        with patch('jarvis.automation.local_pc.run_app',new=AsyncMock()) as ui:
            await local.execute('Draft an email',planned_steps=[step])
            self.assertTrue(local.needs_input)
            self.assertFalse(local.last_action_ok)
            ui.assert_not_awaited()

    async def test_explicit_send_is_allowed_but_draft_is_not_send(self):
        from jarvis.integrations.email_workflows import send_requested
        self.assertTrue(send_requested('Send an email now please'))
        self.assertFalse(send_requested('Draft an email, do not send'))
        for provider in ('Gmail','Outlook'):
            for explicit in (True,False):
                local=LocalPC()
                step=dict(action='send_email',target=provider,recipient='alex@example.com',subject='Test',content='Hello')
                request=('Send' if explicit else 'Draft')+f' an email to alex@example.com in {provider}'
                with patch('jarvis.automation.local_pc.google_access.status',return_value={}), \
                     patch('jarvis.automation.local_pc.run_app',new=AsyncMock(return_value={'ok':True,'message':'Verified send.'})) as ui, \
                     patch('jarvis.integrations.outlook_com.send_outlook',new=AsyncMock(return_value={'ok':True,'message':'Verified send.'})) as outlook:
                    await local.execute(request,planned_steps=[step])
                    if explicit:
                        if provider == 'Outlook':
                            outlook.assert_awaited_once()
                            ui.assert_not_awaited()
                        else:
                            self.assertTrue(ui.call_args.kwargs['mail']['submit_allowed'])
                        self.assertTrue(local.last_action_ok)
                    else:
                        ui.assert_not_awaited()
                        outlook.assert_not_awaited()
                        self.assertTrue(local.needs_input)

    async def test_missing_recipient_never_executes(self):
        local=LocalPC()
        with patch('jarvis.automation.local_pc.run_app',new=AsyncMock()) as ui:
            await local.execute('Send email',planned_steps=[dict(action='send_email',target='Gmail',recipient='',subject='Test',content='Hello')])
            self.assertTrue(local.needs_input)
            self.assertFalse(local.last_action_ok)
            ui.assert_not_awaited()

    def test_open_outlook_composer_three_tier_fallback(self):
        """Test open_outlook_composer CLI, os.startfile, and webbrowser.open fallbacks."""
        from jarvis.automation.local_pc import open_outlook_composer

        # Strategy 1: Popen succeeds
        with patch('jarvis.automation.local_pc.find_outlook_executable', return_value='C:\\mock\\outlook.exe'), \
             patch('subprocess.Popen') as mock_popen:
            ok = open_outlook_composer('alex@example.com', 'Meeting', 'Hello')
            self.assertTrue(ok)
            mock_popen.assert_called_once()
            cmd = mock_popen.call_args[0][0]
            self.assertEqual(cmd[0], 'C:\\mock\\outlook.exe')
            self.assertEqual(cmd[1:4], ['/c', 'ipm.note', '/mailto'])
            self.assertIn('mailto:alex@example.com?subject=Meeting&body=Hello', cmd[4])

        # Strategy 2: Popen raises OSError, os.startfile succeeds
        with patch('jarvis.automation.local_pc.find_outlook_executable', return_value='C:\\mock\\outlook.exe'), \
             patch('subprocess.Popen', side_effect=OSError("Popen failed")), \
             patch('os.startfile', create=True) as mock_startfile:
            ok = open_outlook_composer('alex@example.com', 'Meeting', 'Hello')
            self.assertTrue(ok)
            mock_startfile.assert_called_once_with('mailto:alex@example.com?subject=Meeting&body=Hello')

        # Strategy 3: Popen raises, startfile raises, webbrowser succeeds
        with patch('jarvis.automation.local_pc.find_outlook_executable', return_value=None), \
             patch('os.startfile', side_effect=OSError("No association"), create=True), \
             patch('webbrowser.open', return_value=True) as mock_wb:
            ok = open_outlook_composer('alex@example.com', 'Meeting', 'Hello')
            self.assertTrue(ok)
            mock_wb.assert_called_once_with('mailto:alex@example.com?subject=Meeting&body=Hello')

        # Strategy 4: All strategies fail
        with patch('jarvis.automation.local_pc.find_outlook_executable', return_value=None), \
             patch('os.startfile', side_effect=OSError("No association"), create=True), \
             patch('webbrowser.open', return_value=False):
            ok = open_outlook_composer('alex@example.com', 'Meeting', 'Hello')
            self.assertFalse(ok)


if __name__ == '__main__':
    unittest.main()
