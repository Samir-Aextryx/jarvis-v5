import asyncio
import unittest
from unittest.mock import patch, AsyncMock
from jarvis.automation.app_launcher import parse_open_request, resolve_app, open_app

APPS = [
    {"name": "Google Chrome", "id": "Chrome"},
    {"name": "Outlook", "id": "Outlook.New!App"},
    {"name": "Outlook (classic)", "id": "Outlook.Classic"},
    {"name": "WhatsApp", "id": "WhatsApp!App"},
    {"name": "Snapchat", "id": "Snapchat!App"},
    {"name": "Proton VPN", "id": "Proton"},
    {"name": "Mullvad VPN", "id": "Mullvad"},
    {"name": "FortiClient VPN", "id": "Forti"},
    {"name": "Rechner", "id": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"},
    {"name": "Editor", "id": "Microsoft.WindowsNotepad_8wekyb3d8bbwe!App"},
    {"name": "Registrierungs-Editor", "id": r"C:\Windows\regedit.exe"},
    {"name": "Calculator Tools 10.0", "id": r"C:\Users\Samir\KiCad\pcb_calculator.exe"},
]


class AppLauncherTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # A voice routing test must not start the real background inbox watcher
        # or launch Outlook on the user's desktop during the app startup.
        monitor = patch('jarvis.integrations.urgent_mail.urgent_mail_monitor.run', new=AsyncMock())
        monitor.start(); self.addCleanup(monitor.stop)
        for target, result in [('jarvis.automation.app_windows.focus_existing', None), ('jarvis.automation.app_windows.verify_started', True)]:
            mock = patch(target, return_value=result)
            mock.start(); self.addCleanup(mock.stop)
    def test_spoken_commands(self):
        for phrase, expected in [("Öffne Chrome", "Chrome"), ("Jarvis, öffne bitte Chrome!", "Chrome"),
                                 ("Kannst du bitte Chrome öffnen?", "Chrome"), ("Mach Chrome auf", "Chrome"),
                                 ("Please open Chrome", "Chrome"), ("Outlook öffnen", "Outlook"),
                                 ("Open Outlook", "Outlook"), ("Open my Outlook", "Outlook"),
                                 ("Open Outlook mail", "Outlook"), ("Open the Outlook app", "Outlook"),
                                 ("Open Microsoft Outlook", "Outlook"), ("Öffne mein Outlook", "Outlook"),
                                 ("Mach Outlook auf", "Outlook"), ("Öffne das Outlook-Programm", "Outlook"),
                                 ("Öffne mir Excel", "Excel"), ("Mach mir mal Chrome auf", "Chrome"),
                                 ("Öffne mir Chrome und Outlook", ["Chrome", "Outlook"])]:
            self.assertEqual(parse_open_request(phrase), expected)
        self.assertIsNone(parse_open_request("Öffne https://example.com"))
        self.assertIsNone(parse_open_request("Verbinde mein VPN"))
        self.assertIsNone(parse_open_request("Öffne den Projektordner"))

    def test_aliases_and_exact_outlook_preference(self):
        self.assertEqual(resolve_app("Chrome", APPS)[0]["id"], "Chrome")
        self.assertEqual(resolve_app("Outlook", APPS)[0]["id"], "Outlook.New!App")
        self.assertEqual(resolve_app("Whats App", APPS)[0]["name"], "WhatsApp")
        self.assertEqual(resolve_app("Snap Chat", APPS)[0]["name"], "Snapchat")
        self.assertEqual(resolve_app("Calculator", APPS)[0]["name"], "Rechner")
        self.assertEqual(resolve_app("Notepad", APPS)[0]["name"], "Editor")
        self.assertEqual(resolve_app("Calculator Tools 10.0", APPS)[0]["name"], "Calculator Tools 10.0")
        self.assertEqual(len(resolve_app("VPN", APPS)), 3)

    def test_spoken_article_is_dropped_only_when_the_full_phrase_names_no_app(self):
        self.assertEqual(resolve_app("den Rechner", APPS)[0]["name"], "Rechner")
        self.assertEqual(resolve_app("the calculator", APPS)[0]["name"], "Rechner")
        self.assertEqual(resolve_app("den Editor", APPS)[0]["name"], "Editor")
        self.assertEqual(resolve_app("mein Chrome", APPS)[0]["id"], "Chrome")
        titled = APPS + [{"name": "Die Siedler", "id": "Siedler"}, {"name": "Siedler Tools", "id": "Tools"}]
        self.assertEqual([app["id"] for app in resolve_app("Die Siedler", titled)], ["Siedler"])
        self.assertEqual(resolve_app("den Taschenrechner Pro", APPS), [])

    async def test_launch_only_catalog_entry(self):
        with patch("jarvis.automation.app_launcher._launch") as launch:
            result = await open_app("Chrome", APPS)
            self.assertTrue(result["success"])
            launch.assert_called_once_with(APPS[0])

    async def test_multiple_requested_apps_start_concurrently(self):
        focus_calls = 0
        both_focusing = asyncio.Event()
        launches = []

        async def run_thread_task(function, *args, **kwargs):
            nonlocal focus_calls
            operation = getattr(function, "_mock_name", None) or getattr(function, "__name__", "")
            if operation == "focus_existing":
                focus_calls += 1
                if focus_calls == 2:
                    both_focusing.set()
                await asyncio.wait_for(both_focusing.wait(), timeout=0.5)
                return None
            if operation == "_launch":
                launches.append(args[0]["id"])
                return None
            raise AssertionError(f"Unexpected worker operation: {operation}")

        with patch("jarvis.automation.app_launcher.asyncio.to_thread", new=run_thread_task):
            result = await asyncio.wait_for(open_app(["Chrome", "WhatsApp"], APPS), timeout=0.75)

        self.assertTrue(result["success"])
        self.assertEqual(result["app"], "Google Chrome, WhatsApp")
        self.assertCountEqual(launches, ["Chrome", "WhatsApp!App"])

    async def test_unknown_or_command_injection_does_not_launch(self):
        with patch("jarvis.automation.app_launcher._launch") as launch:
            for query in ["", "Unknown app", "Chrome & powershell", "Chrome --remote-debugging-port=9222", "C:\\Windows\\cmd.exe"]:
                result = await open_app(query, APPS)
                self.assertFalse(result["success"])
            launch.assert_not_called()

    async def test_chatgpt_and_claude_have_safe_chrome_fallbacks(self):
        import tempfile
        from jarvis.core.personal_memory import PersonalMemory
        with tempfile.TemporaryDirectory() as root, \
             patch('jarvis.automation.app_launcher.installed_apps',return_value=[]), \
             patch('jarvis.automation.app_launcher.open_in_chrome') as browser:
            for target, url in [('ChatGPT','https://chatgpt.com/'),('Claude','https://claude.ai/')]:
                result=await open_app(target,memory=PersonalMemory(root))
                self.assertTrue(result['success'])
                self.assertEqual(result['state'],'launching')
                browser.assert_called_with(url)

    def test_claude_alias_resolves_exactly(self):
        self.assertEqual(resolve_app('Claude AI',[{'name':'Claude','id':'Claude.App'}])[0]['id'],'Claude.App')

    async def test_vpn_ambiguity_then_named_selection(self):
        with patch("jarvis.automation.app_launcher._launch") as launch:
            result = await open_app("VPN", APPS)
            self.assertFalse(result["success"])
            launch.assert_not_called()
            selected = await open_app("Proton", result["candidates"])
            self.assertTrue(selected["success"])
            launch.assert_called_once_with(APPS[5])

    def test_voice_routing_and_vpn_followup(self):
        import jarvis.server as server
        import tempfile
        from jarvis.core.personal_memory import PersonalMemory
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory() as root, patch.object(server, "personal_memory", PersonalMemory(root)), patch("jarvis.automation.app_launcher.installed_apps", return_value=APPS), patch("jarvis.automation.app_launcher._launch") as launch, patch.object(server, "synthesize_speech", new=AsyncMock(return_value=None)), patch.object(server, "cached_projects", [{"name": "test", "path": "."}]):
            with TestClient(server.app) as client:
                with client.websocket_connect('/ws/voice', subprotocols=['jarvis', 'jarvis.auth.' + server.JARVIS_AUTH_TOKEN]) as ws:
                    for phrase, expected in [("Öffne VPN", "Which app"), ("Proton", "Opening Proton VPN"), ("Öffne Chrome", "Opening Google Chrome"), ("Öffne VPN", "Opening Proton VPN")]:
                        ws.send_json({"type": "transcript", "text": phrase, "isFinal": True})
                        for _ in range(8):
                            message = ws.receive_json()
                            if message.get("type") == "text" and not message.get("text", "").startswith("[JEV_KEY_MISSING]"):
                                self.assertIn(expected, message["text"])
                                break
                        else:
                            self.fail("No app-launch voice response")
            self.assertEqual(launch.call_count, 3, launch.call_args_list)

    def test_plain_app_launch_skips_remote_router(self):
        import jarvis.server as server
        from fastapi.testclient import TestClient
        with patch('jarvis.automation.app_launcher.installed_apps', return_value=APPS), \
             patch('jarvis.automation.app_launcher._launch') as launch, \
             patch.object(server.jev, 'configured', return_value=True), \
             patch.object(server.agent_router, 'route', new=AsyncMock()) as route, \
             patch.object(server, 'synthesize_speech', new=AsyncMock(return_value=None)):
            with TestClient(server.app) as client:
                with client.websocket_connect('/ws/voice', subprotocols=['jarvis', 'jarvis.auth.' + server.JARVIS_AUTH_TOKEN]) as ws:
                    for phrase, expected in [('Open Chrome', 'Opening Google Chrome'),
                                             ('Mach Outlook auf', 'Opening Outlook')]:
                        ws.send_json({'type': 'transcript', 'text': phrase, 'isFinal': True})
                        stages = set()
                        for _ in range(8):
                            message = ws.receive_json()
                            if message.get('type') == 'latency':
                                stages.add(message.get('stage'))
                            if message.get('type') == 'text':
                                self.assertIn(expected, message['text'])
                                break
                        else:
                            self.fail('No app-launch response')
                        self.assertTrue({'automation_start', 'automation_complete'} <= stages)
            self.assertEqual(launch.call_count, 2)
            route.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
