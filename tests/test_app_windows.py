from unittest.mock import patch

import win32gui

from jarvis.automation import app_windows


def test_foreground_app_skips_full_desktop_window_scan():
    app = {'name': 'Google Chrome'}
    with patch.object(win32gui, 'GetForegroundWindow', return_value=42), \
         patch.object(win32gui, 'IsWindowVisible', return_value=True), \
         patch.object(app_windows, '_process_image_name', return_value='chrome.exe'), \
         patch.object(app_windows, 'windows') as scan:
        result = app_windows.focus_existing(app)

    assert result == {
        'success': True,
        'state': 'focused',
        'confirmation': 'Focused Google Chrome.',
    }
    scan.assert_not_called()
