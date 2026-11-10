import unittest
from unittest.mock import patch
from jarvis.automation.website_launcher import parse_website_request, validate_url, open_website

class WebsiteTests(unittest.IsolatedAsyncioTestCase):
    def test_domains_and_spoken_urls(self):
        for phrase in ['Öffne youtube.com', 'Open youtube.com', 'Jarvis, öffne bitte youtube punkt com']:
            self.assertEqual(validate_url(parse_website_request(phrase)), 'https://youtube.com')
        self.assertEqual(validate_url('http://localhost:5173/test'), 'http://localhost:5173/test')
        self.assertIsNone(parse_website_request('Öffne Outlook'))
        self.assertIsNone(parse_website_request('Öffne Ordner C:\\Users'))

    async def test_unsafe_schemes_or_embedded_logins_never_open(self):
        with patch('jarvis.automation.website_launcher.open_in_chrome') as launch:
            for target in ['javascript:alert(1)', 'file:///C:/Windows', 'https://user:pass@example.com', 'https://example.com\ncmd', r'C:\Windows\cmd.exe']:
                self.assertIn("couldn't",await open_website(target))
            launch.assert_not_called()

    async def test_direct_open(self):
        with patch('jarvis.automation.website_launcher.open_in_chrome') as launch:
            self.assertEqual(await open_website('example.com'), 'Opening example.com in Chrome.')
            launch.assert_called_once_with('https://example.com')

    def test_named_sites_and_speech_punctuation(self):
        for phrase in ['Open dashboard', 'Open the dashboard.', 'Öffne das Dashboard', 'Open Jarvis dashboard in Chrome']:
            self.assertEqual(parse_website_request(phrase), 'jarvis:dashboard')
        for phrase in ['Open YouTube', 'Open YouTube.', 'Open YouTube in Chrome']:
            self.assertEqual(parse_website_request(phrase), 'https://www.youtube.com')
        for phrase in ['Open Gmail', 'Open Gmail.', 'Open Gmail in Chrome']:
            self.assertEqual(parse_website_request(phrase), 'https://mail.google.com/')

    def test_chrome_launch_uses_separate_arguments(self):
        from jarvis.automation.website_launcher import open_in_chrome
        with patch('jarvis.automation.website_launcher.chrome_executable', return_value=r'C:\Program Files\Google\Chrome\Application\chrome.exe'), patch('jarvis.automation.website_launcher.subprocess.Popen') as launch:
            open_in_chrome('https://example.com/?a=1&b=2')
            self.assertEqual(launch.call_args.args[0], [r'C:\Program Files\Google\Chrome\Application\chrome.exe', '--new-tab', 'https://example.com/?a=1&b=2'])
            self.assertFalse(launch.call_args.kwargs['shell'])
