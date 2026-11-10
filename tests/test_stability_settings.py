import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from jarvis.core.agent_settings import AgentSettings, DEFAULTS
from jarvis.integrations.calendar_workflows import is_calendar_request

class StabilityTests(unittest.TestCase):
    def test_corrupt_settings_recover_valid_fields(self):
        with tempfile.TemporaryDirectory() as root:
            settings = AgentSettings(root)
            for data in [[], None, 'wrong', {'work_apps': None, 'automation': 'false', 'large_model': 7, 'default_email': [], 'fallback': False}]:
                settings.path.write_text(json.dumps(data), encoding='utf-8')
                result = settings.get()
                self.assertEqual(result['work_apps'], DEFAULTS['work_apps'])
                self.assertIs(result['automation'], True)
                self.assertIsInstance(result['large_model'], str)
                if isinstance(data, dict): self.assertIs(result['fallback'], False)
            result['work_apps'].clear()
            self.assertTrue(settings.get()['work_apps'])
            for data in [{'large_model': 7}, {'default_email': []}]:
                with self.assertRaises(ValueError): settings.save(data)

    def test_corrupt_logs_and_concurrent_writes(self):
        with tempfile.TemporaryDirectory() as root:
            settings = AgentSettings(root)
            settings.log_path.parent.mkdir()
            for raw in ['{', '{}', 'null', '[null, {"secret":"not an activity"}]']:
                settings.log_path.write_text(raw, encoding='utf-8')
                self.assertEqual(settings.logs(), [])
                settings.activity('apps.open', True, 1)
                self.assertEqual(len(settings.logs()), 1)
            settings.clear_logs()
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda _: settings.activity('apps.open', True, 1), range(80)))
            self.assertEqual(len(settings.logs()), 80)

    def test_availability_is_not_free_software(self):
        for request in ['What is free software?', 'Find free apps', 'Show free games']:
            self.assertFalse(is_calendar_request(request), request)
        for request in ['Am I free tomorrow?', 'When am I available?', 'Bin ich morgen frei?', 'Show my calendar', 'Create a meeting tomorrow']:
            self.assertTrue(is_calendar_request(request), request)
        for request in [r'Read the file "C:\Users\Samir\Documents\meeting notes.txt"',
                        r'Read files "C:\Users\Samir\meeting.txt" and "C:\Users\Samir\notes.md"']:
            self.assertFalse(is_calendar_request(request), request)
