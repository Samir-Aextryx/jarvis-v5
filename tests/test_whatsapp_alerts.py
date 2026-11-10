import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from jarvis.integrations.urgent_mail import UrgentMailMonitor, is_urgent_header
from jarvis.automation.app_windows import _window_matches_app
from jarvis.integrations.whatsapp_call import (
    attempt_urgent_call, boss_number_configured, call_readiness,
    normalize_swiss_mobile, parse_call_request, prepare_call_to_boss,
    save_boss_number, whatsapp_beta_microphone_allowed,
)
from jarvis.automation.whatsapp_beta_ui import (
    ContactNotVerified, _copy_visible_number, _type_search_number, contact_layout,
    verify_boss_contact,
)


class Vault:
    def __init__(self):
        self.data = {}

    def set_password(self, service, key, value):
        self.data[(service, key)] = value

    def get_password(self, service, key):
        return self.data.get((service, key))


class CallTests(unittest.TestCase):
    def test_contact_search_uses_saved_number_instead_of_ambiguous_name(self):
        with patch('win32api.keybd_event') as press:
            _type_search_number('+41 79 123 45 67')
        self.assertEqual(''.join(chr(call.args[0]) for call in press.call_args_list[::2]),
                         '0791234567')
        with patch('win32api.keybd_event') as press:
            with self.assertRaises(ValueError):
                _type_search_number('Boss')
            press.assert_not_called()

    def test_whatsapp_beta_microphone_permission_is_read_from_its_own_package(self):
        with patch('winreg.OpenKey') as open_key, \
             patch('winreg.QueryValueEx', return_value=('Allow', 1)):
            self.assertTrue(whatsapp_beta_microphone_allowed())
        self.assertIn('5319275A.51895FA4EA97F_cv1g1gvanyjgm', open_key.call_args.args[1])
        with patch('winreg.OpenKey', side_effect=FileNotFoundError):
            self.assertFalse(whatsapp_beta_microphone_allowed())

    def test_contact_check_layout_rejects_unfamiliar_window(self):
        layout = contact_layout(896, 594)
        self.assertLess(layout.search[0], layout.contact_header[0])
        self.assertEqual(layout.number_start[1], layout.number_end[1])
        maximized = contact_layout(1536, 912)
        self.assertTrue(1200 <= maximized.number_start[0] < maximized.number_end[0] <= 1400)
        with self.assertRaises(ContactNotVerified):
            contact_layout(700, 500)

    def test_contact_copy_requires_fresh_clipboard_and_restores_previous_data(self):
        class ClipboardSequence:
            def __init__(self, values):
                self.values = iter(values)
            def GetClipboardSequenceNumber(self):
                return next(self.values)

        def check(sequence, should_match):
            with patch('jarvis.automation.whatsapp_beta_ui.ctypes.windll.user32',
                       ClipboardSequence(sequence)), \
                 patch('win32gui.GetForegroundWindow', return_value=1), \
                 patch('pythoncom.OleInitialize'), \
                 patch('pythoncom.OleGetClipboard', return_value=object()), \
                 patch('pythoncom.OleSetClipboard') as restore, \
                 patch('pythoncom.CoUninitialize'), \
                 patch('win32clipboard.OpenClipboard'), \
                 patch('win32clipboard.CloseClipboard'), \
                 patch('win32clipboard.GetClipboardData', return_value='+41 79 123 45 67'), \
                 patch('jarvis.automation.whatsapp_beta_ui._mouse_drag'), \
                 patch('jarvis.automation.whatsapp_beta_ui._key_chord'), \
                 patch('jarvis.automation.whatsapp_beta_ui.time.sleep'):
                if should_match:
                    self.assertEqual(_copy_visible_number(1, contact_layout(896, 594), 0, 0),
                                     '+41 79 123 45 67')
                else:
                    with self.assertRaises(ContactNotVerified):
                        _copy_visible_number(1, contact_layout(896, 594), 0, 0)
                restore.assert_called_once()
        check([1, 2, 2], True)
        check([1] * 12, False)

    def test_contact_number_must_match_vault_value_before_call(self):
        beta = {'name': 'WhatsApp Beta', 'id': 'beta'}
        with patch('jarvis.automation.app_launcher.installed_apps', return_value=[beta]), \
             patch('jarvis.automation.app_launcher.resolve_app', return_value=[beta]), \
             patch('jarvis.automation.app_windows.windows', return_value=[42]), \
             patch('jarvis.automation.app_windows.focus_existing',
                   return_value={'success': True}), \
             patch('win32gui.GetForegroundWindow', return_value=42), \
             patch('jarvis.automation.whatsapp_beta_ui._visible_window_rect',
                   return_value=(0, 0, 896, 594)), \
             patch('jarvis.automation.whatsapp_beta_ui._mouse_click'), \
             patch('jarvis.automation.whatsapp_beta_ui._key_chord'), \
             patch('jarvis.automation.whatsapp_beta_ui._type_search_number'), \
             patch('jarvis.automation.whatsapp_beta_ui._copy_visible_number',
                   return_value='+41 79 123 45 67'), \
             patch('jarvis.automation.whatsapp_beta_ui.time.sleep'):
            self.assertTrue(verify_boss_contact('+41791234567'))
            self.assertFalse(verify_boss_contact('+41761234567'))

    def test_contact_is_saved_only_in_vault(self):
        vault = Vault()
        with patch('jarvis.integrations.whatsapp_call.get_vault', return_value=vault):
            save_boss_number('0791234567')
            self.assertTrue(boss_number_configured())
        self.assertEqual(len(vault.data), 1)
        self.assertEqual(next(iter(vault.data.values())), '+41791234567')

    def test_only_swiss_mobile_and_explicit_call(self):
        self.assertEqual(normalize_swiss_mobile('+41 79 123 45 67'), '+41791234567')
        for bad in ('123', '+44 79 123 45 67', '0791234567;echo unsafe'):
            with self.assertRaises(ValueError):
                normalize_swiss_mobile(bad)
        self.assertTrue(parse_call_request('ruf mich an'))
        self.assertTrue(parse_call_request('call boss on WhatsApp Beta'))
        self.assertFalse(parse_call_request('do not call boss'))
        self.assertFalse(parse_call_request('call someone else'))

    def test_beta_window_cannot_be_confused_with_standard_whatsapp(self):
        beta = {'name': 'WhatsApp Beta', 'id': '5319275A.51895FA4EA97F_cv1g1gvanyjgm!App'}
        standard_path = r'c:\program files\windowsapps\5319275a.whatsappdesktop_1.0_x64__cv1g1gvanyjgm\whatsapp.root.exe'
        beta_path = r'c:\program files\windowsapps\5319275a.51895fa4ea97f_1.0_x64__cv1g1gvanyjgm\whatsapp.root.exe'
        with patch('jarvis.automation.app_windows._process_image_path', return_value=standard_path):
            self.assertFalse(_window_matches_app(1, beta))
        with patch('jarvis.automation.app_windows._process_image_path', return_value=beta_path):
            self.assertTrue(_window_matches_app(1, beta))


class AlertTests(unittest.IsolatedAsyncioTestCase):
    def monitor(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return UrgentMailMonitor(directory.name)

    async def test_beta_discovery_refreshes_stale_catalog(self):
        standard = {'name': 'WhatsApp', 'id': 'standard'}
        beta = {'name': 'WhatsApp Beta', 'id': 'beta'}
        with patch('jarvis.automation.app_launcher.installed_apps', side_effect=[[standard], [standard, beta]]) as catalog, \
             patch('jarvis.integrations.whatsapp_call.boss_number_configured', return_value=True):
            state = await call_readiness()
        self.assertTrue(state['whatsapp_beta_installed'])
        self.assertFalse(state['automatic_call_ready'])
        self.assertEqual(catalog.call_count, 2)

    async def test_first_scan_baselines_and_only_new_urgent_unread_alerts(self):
        monitor = self.monitor()
        notify = AsyncMock()
        old = {'id': '1', 'subject': 'Urgent old mail', 'unread': True}
        await monitor.scan('gmail', AsyncMock(return_value=[old]), notify)
        notify.assert_not_awaited()
        new = {'id': '2', 'subject': 'Dringend: Meeting', 'unread': True,
               'sender': 'Alice'}
        ordinary = {'id': '3', 'subject': 'News', 'unread': True}
        await monitor.scan('gmail', AsyncMock(return_value=[old, new, ordinary]), notify)
        self.assertEqual(notify.await_count, 1)
        await monitor.scan('gmail', AsyncMock(return_value=[old, new, ordinary]), notify)
        self.assertEqual(notify.await_count, 1)
        self.assertTrue(monitor.status()['state_encrypted'])
        self.assertNotIn(b'Dringend', monitor.path.read_bytes())
        restarted = UrgentMailMonitor(monitor.path.parent.parent)
        self.assertEqual(restarted.status()['alerts'][0]['subject'], 'Dringend: Meeting')
        await restarted.scan('gmail', AsyncMock(return_value=[old, new, ordinary]), notify)
        self.assertEqual(notify.await_count, 1)
        after_restart = {'id':'4', 'subject':'Emergency now', 'unread':True}
        await restarted.scan('gmail', AsyncMock(return_value=[after_restart]), notify)
        self.assertEqual(notify.await_count, 2)

    async def test_urgent_call_is_durable_deduplicated_and_never_claimed_on_preflight(self):
        monitor = self.monitor()
        notify = AsyncMock()
        await monitor.scan('outlook', AsyncMock(return_value=[]), notify)
        await monitor.scan('outlook', AsyncMock(return_value=[{
            'id': 'm1', 'subject': 'Notfall', 'sender': 'A', 'unread': True,
        }]), notify)
        self.assertEqual(monitor.status()['alerts'][0]['call_state'], 'pending')
        blocked = AsyncMock(return_value={'state': 'not_ready'})
        await monitor.process_calls(blocked, notify)
        self.assertEqual(blocked.await_count, 1)
        self.assertEqual(monitor.status()['alerts'][0]['call_state'], 'blocked')
        await monitor.process_calls(blocked, notify)
        self.assertEqual(blocked.await_count, 1)
        restarted = UrgentMailMonitor(monitor.path.parent.parent)
        self.assertEqual(restarted.status()['alerts'][0]['call_state'], 'blocked')
        future = restarted.alerts[0]['next_attempt'] + 1
        with patch('jarvis.integrations.urgent_mail.time.time', return_value=future):
            connected = AsyncMock(return_value={'state': 'connected', 'spoken': True})
            await restarted.process_calls(connected, notify)
        self.assertEqual(connected.await_count, 1)
        self.assertEqual(restarted.status()['alerts'][0]['call_state'], 'connected')
        self.assertNotIn('id', restarted.status()['alerts'][0])

    async def test_uncertain_call_is_not_retried_after_restart(self):
        monitor = self.monitor()
        notify = AsyncMock()
        await monitor.scan('gmail', AsyncMock(return_value=[]), notify)
        await monitor.scan('gmail', AsyncMock(return_value=[{
            'id': 'm2', 'subject': 'Urgent', 'unread': True,
        }]), notify)
        uncertain = AsyncMock(side_effect=TimeoutError('unknown call result'))
        await monitor.process_calls(uncertain, notify)
        restarted = UrgentMailMonitor(monitor.path.parent.parent)
        self.assertEqual(restarted.status()['alerts'][0]['call_state'], 'uncertain')
        await restarted.process_calls(uncertain, notify)
        self.assertEqual(uncertain.await_count, 1)

    async def test_storage_failure_does_not_drop_a_new_mail(self):
        monitor = self.monitor()
        notify = AsyncMock()
        fetch = AsyncMock(return_value=[])
        await monitor.scan('outlook', fetch, notify)
        fetch.return_value = [{'id': 'm3', 'subject': 'Urgent now', 'unread': True}]
        original_save = monitor._save
        with patch.object(monitor, '_save', side_effect=OSError('disk full')):
            await monitor.scan('outlook', fetch, notify)
        self.assertEqual(monitor.status()['alerts'], [])
        self.assertEqual(notify.await_count, 0)
        monitor._save = original_save
        await monitor.scan('outlook', fetch, notify)
        self.assertEqual(notify.await_count, 1)
        self.assertEqual(monitor.status()['alerts'][0]['call_state'], 'pending')

    async def test_open_calls_are_never_evicted_by_display_history_limit(self):
        monitor = self.monitor()
        notify = AsyncMock()
        await monitor.scan('outlook', AsyncMock(return_value=[]), notify)
        rows = [{'id': str(index), 'subject': 'Emergency', 'unread': True}
                for index in range(51)]
        await monitor.scan('outlook', AsyncMock(return_value=rows), notify)
        self.assertEqual(len(monitor.status()['alerts']), 51)
        restarted = UrgentMailMonitor(monitor.path.parent.parent)
        self.assertEqual(len(restarted.status()['alerts']), 51)

    async def test_outlook_is_checked_three_times_as_often_as_gmail(self):
        monitor = self.monitor()
        ticks = iter((0.0, 30.0, 60.0, 90.0))
        stop_after_four = AsyncMock(side_effect=[None, None, None, asyncio.CancelledError()])
        with patch.object(monitor, 'scan', new=AsyncMock()) as scan, \
             patch.object(monitor, 'process_calls', new=AsyncMock()) as calls, \
             patch('jarvis.integrations.urgent_mail.google_access.status',
                   return_value={'connected': True, 'services': ['gmail']}) as google:
            with self.assertRaises(asyncio.CancelledError):
                await monitor.run(AsyncMock(), clock=lambda: next(ticks), sleep=stop_after_four)
        self.assertEqual([call.args[0] for call in scan.await_args_list],
                         ['outlook', 'gmail', 'outlook', 'outlook', 'outlook', 'gmail'])
        self.assertEqual(google.call_count, 2)
        self.assertEqual(calls.await_count, 4)
        self.assertEqual([call.args[0] for call in stop_after_four.await_args_list],
                         [30, 30, 30, 30])

    async def test_outlook_failure_is_reported_and_backed_off(self):
        monitor = self.monitor()
        ticks = iter((0.0, 0.0, 30.0, 60.0, 90.0, 120.0))
        attempted = []
        notify = AsyncMock()
        async def scan(source, fetch, callback):
            attempted.append(source)
            if len(attempted) == 1:
                raise RuntimeError('Outlook unavailable')
            monitor.errors.pop(source, None)
        stop_after_five = AsyncMock(side_effect=[None] * 4 + [asyncio.CancelledError()])
        with patch.object(monitor, 'scan', side_effect=scan), \
             patch('jarvis.integrations.urgent_mail.google_access.status',
                   return_value={'connected': False, 'services': []}):
            with self.assertRaises(asyncio.CancelledError):
                await monitor.run(notify, clock=lambda: next(ticks), sleep=stop_after_five)
        self.assertEqual(attempted, ['outlook', 'outlook'])
        self.assertEqual([call.args[0]['available'] for call in notify.await_args_list],
                         [False, True])
        self.assertEqual(monitor.status()['errors'], {})

    async def test_notification_failure_does_not_stop_mail_detection(self):
        monitor = self.monitor()
        await monitor.scan('outlook', AsyncMock(return_value=[]), AsyncMock())
        broken_notify = AsyncMock(side_effect=OSError('socket down'))
        await monitor.scan('outlook', AsyncMock(return_value=[{
            'id': 'm4', 'subject': 'Urgent now', 'unread': True,
        }]), broken_notify)
        self.assertEqual(monitor.status()['alerts'][0]['call_state'], 'pending')
        restarted = UrgentMailMonitor(monitor.path.parent.parent)
        self.assertEqual(len(restarted.status()['alerts']), 1)

    async def test_without_verified_call_path_never_dials(self):
        with patch('jarvis.integrations.whatsapp_call.call_readiness', new=AsyncMock(
                return_value={'contact_saved':True,'whatsapp_beta_installed':True,
                              'audio_bridge_ready':True,'automatic_call_ready':False})):
            result = await attempt_urgent_call({'source':'outlook','id':'x'})
        self.assertEqual(result['state'], 'not_ready')

    async def test_explicit_call_preparation_requires_exact_verified_boss_contact(self):
        vault = Vault()
        vault.set_password('test', 'WHATSAPP_BOSS_NUMBER', '+41791234567')
        with patch('jarvis.integrations.whatsapp_call.call_readiness', new=AsyncMock(
                return_value={'contact_saved': True, 'whatsapp_beta_installed': True})), \
             patch('jarvis.automation.app_launcher.open_app', new=AsyncMock(
                 return_value={'success': True})), \
             patch('jarvis.integrations.whatsapp_call.get_vault', return_value=vault), \
             patch('jarvis.integrations.whatsapp_call._service_name', return_value='test'), \
             patch('jarvis.automation.whatsapp_beta_ui.verify_boss_contact',
                   return_value=False) as verify:
            result = await prepare_call_to_boss()
        self.assertIn('could not verify', result)
        self.assertIn('did not place a call', result)
        verify.assert_called_once_with('+41791234567')

    def test_flags_and_subjects(self):
        self.assertTrue(is_urgent_header({'unread': True, 'important': True}))
        self.assertTrue(is_urgent_header({'unread': True, 'subject': 'Notfall heute'}))
        self.assertFalse(is_urgent_header({'unread': False, 'important': True}))
        self.assertFalse(is_urgent_header({'unread': True, 'subject': 'Ordinary meeting'}))


if __name__ == '__main__':
    unittest.main()
