import tempfile
from unittest.mock import patch
import unittest
from jarvis.automation.app_launcher import open_app, save_app_preference, parse_app_preference
from jarvis.core.personal_memory import PersonalMemory
from jarvis.server import apply_speech_corrections
from tests.test_app_launcher import APPS


class AppLearningTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for target, result in [('jarvis.automation.app_windows.focus_existing', None), ('jarvis.automation.app_windows.verify_started', True)]:
            mock = patch(target, return_value=result)
            mock.start(); self.addCleanup(mock.stop)
    async def test_confirmed_choice_survives_restart(self):
        with tempfile.TemporaryDirectory() as root:
            memory=PersonalMemory(root)
            with patch('jarvis.automation.app_launcher.installed_apps',return_value=APPS),patch('jarvis.automation.app_launcher._launch') as launch:
                options=await open_app('VPN',memory=memory)
                self.assertFalse(options['success']);launch.assert_not_called()
                chosen=await open_app('Proton',options['candidates'],memory=memory,remember_as=options['preference_key'])
                self.assertTrue(chosen['success'])
                result=await open_app('VPN',memory=PersonalMemory(root))
                self.assertEqual(result['app'],'Proton VPN')
                self.assertIn('vpn → Proton VPN',memory.path.read_text(encoding='utf-8'))

    async def test_typo_requires_confirmation_and_missing_app_is_not_launched(self):
        with tempfile.TemporaryDirectory() as root:
            memory=PersonalMemory(root)
            with patch('jarvis.automation.app_launcher.installed_apps',return_value=APPS),patch('jarvis.automation.app_launcher._launch') as launch:
                result=await open_app('Snapshat',memory=memory)
                self.assertFalse(result['success']);launch.assert_not_called()
                self.assertEqual(result['candidates'][0]['name'],'Snapchat')
                memory.remember_app('vpn',{'id':'removed','name':'Removed app'})
                result=await open_app('VPN',memory=memory)
                self.assertFalse(result['success']);launch.assert_not_called()

    async def test_explicit_mapping_saves_but_does_not_launch(self):
        with tempfile.TemporaryDirectory() as root:
            memory=PersonalMemory(root)
            with patch('jarvis.automation.app_launcher.installed_apps',return_value=APPS),patch('jarvis.automation.app_launcher._launch') as launch:
                self.assertEqual(parse_app_preference('Remember that browser means Google Chrome'),('browser','Google Chrome'))
                self.assertEqual(parse_app_preference('Merke dir: Mit VPN meine ich Proton VPN'),('VPN','Proton VPN'))
                await save_app_preference('browser','Google Chrome',memory)
                launch.assert_not_called()
                result=await open_app('browser',memory=memory)
                self.assertEqual(result['app'],'Google Chrome')

    async def test_failed_launch_does_not_teach_a_preference(self):
        with tempfile.TemporaryDirectory() as root:
            memory=PersonalMemory(root)
            with patch('jarvis.automation.app_launcher._launch',side_effect=OSError('failed')):
                result=await open_app('Proton',APPS,memory=memory,remember_as='vpn')
            self.assertFalse(result['success']);self.assertIsNone(memory.app_choice('vpn'))

    def test_dictated_content_is_not_rewritten(self):
        for text in ['What is cloud storage?', 'Send an email to Travis saying cloud code is ready', 'Write a message saying Jarves uses a quad bike']:
            self.assertEqual(apply_speech_corrections(text),text)
        self.assertEqual(apply_speech_corrections('Travis, open Chrome'),'JARVIS, open Chrome')
        self.assertEqual(apply_speech_corrections('open cloud code'),'open Codex')
        self.assertEqual(apply_speech_corrections('Schicke eine E-Mail an Herrn Haener mit dem Text Hallo Herr Haener'),
                         'Schicke eine E-Mail an Herrn Häner mit dem Text Hallo Herr Haener')
