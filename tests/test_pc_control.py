import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from jarvis.automation.pc_control import PCControl, local_path


class PCTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_does_not_treat_questions_as_actions(self):
        for text in ['Was sind Viren?', 'Kann Codex Apps programmieren?', 'Lösche C:\\Windows', 'Öffne Chrome']:
            self.assertIsNone(PCControl.parse(text))
        for text, action in [('Scanne meinen ganzen PC', 'scan'), ('Starte Schnellscan', 'scan'), ('Programmiere mir eine App', 'code'), ('Öffne Ordner C:\\Users', 'open_path')]:
            self.assertEqual(PCControl.parse(text)[0], action)

    def test_paths_reject_shell_and_devices(self):
        for path in ['cmd /c echo hi', '\\\\server\\file', r'C:\test.txt:stream']:
            with self.assertRaises(ValueError):
                local_path(path)

    async def test_removal_requires_matching_fresh_findings(self):
        control = PCControl()
        with patch('jarvis.automation.pc_control.powershell') as run, patch('jarvis.automation.pc_control.defender_status', return_value={'threats': [{'ThreatID': 1, 'ThreatName': 'Test'}]}) as status:
            self.assertIn('Keine aktuelle', await control.execute(('remove_confirm', '')))
            await control.execute(('remove_prepare', ''))
            status.return_value = {'threats': [{'ThreatID': 2, 'ThreatName': 'Changed'}]}
            self.assertIn('geändert', await control.execute(('remove_confirm', '')))
            run.assert_not_called()
            await control.execute(('remove_prepare', ''))
            await control.execute(('remove_confirm', ''))
            run.assert_called_once_with('Remove-MpThreat', 120)

    async def test_file_limits_and_no_execution(self):
        with tempfile.TemporaryDirectory() as root:
            control = PCControl(root)
            path = Path(root, 'test.txt')
            path.write_text('sk-secretkey ' + 'a' * 5000)
            response = await control.execute(('read_path', str(path)))
            self.assertNotIn('sk-secretkey', response)
            self.assertLess(len(response), 4050)
            exe = Path(root, 'test.cmd')
            exe.write_text('echo no')
            with patch('jarvis.automation.pc_control.os.startfile') as launch:
                await control.execute(('open_path', str(exe)))
                launch.assert_not_called()

    def test_codex_stdin_and_thread_link(self):
        with tempfile.TemporaryDirectory() as root, patch('jarvis.automation.pc_control.desktop', return_value=Path(root)), patch('jarvis.automation.pc_control.codex_executable', return_value='codex.exe'), patch('jarvis.automation.pc_control.os.startfile') as launch, patch('jarvis.automation.pc_control.subprocess.Popen') as popen:
            process = MagicMock()
            process.stdout = io.StringIO('{"type":"thread.started","thread_id":"abc-123"}\n{"type":"turn.completed"}\n')
            process.wait.return_value = 0
            popen.return_value.__enter__.return_value = process
            control = PCControl(root)
            prompt = 'Erstelle eine App; $(echo injected)'
            control._code({'id': 'a123456', 'kind': 'code'}, prompt)
            args = popen.call_args.args[0]
            self.assertNotIn(prompt, args)
            self.assertIn('workspace-write', args)
            process.stdin.write.assert_called_once_with(prompt)
            launch.assert_called_once_with('codex://threads/abc-123')

    async def test_failed_scan_not_success(self):
        with tempfile.TemporaryDirectory() as root:
            control = PCControl(root)
            with patch('jarvis.automation.pc_control.powershell', side_effect=RuntimeError('Windows verweigert')):
                await control.execute(('scan', 'QuickScan'))
                await asyncio.gather(*control.tasks)
            job = list(control.jobs.values())[0]
            self.assertEqual(job['state'], 'error')
            self.assertIn('verweigert', job['message'])

    def test_api_requires_auth(self):
        import jarvis.server as server
        from fastapi.testclient import TestClient
        with TestClient(server.app) as client:
            self.assertEqual(client.post('/api/pc/command', json={'text': 'Zeige Laufwerke'}).status_code, 401)
            response = client.post('/api/pc/command', headers={'Authorization': 'Bearer ' + server.JARVIS_AUTH_TOKEN}, json={'text': 'Zeige Laufwerke'})
            self.assertEqual(response.status_code, 200)
            self.assertIn('Laufwerke', response.json()['text'])
