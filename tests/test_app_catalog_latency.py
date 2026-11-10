import json
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

from jarvis.automation import app_launcher


def test_persisted_catalog_is_usable_before_refresh():
    with tempfile.TemporaryDirectory() as root:
        path = Path(root) / 'installed-apps.json'
        path.write_text(json.dumps([{'Name': 'Google Chrome', 'AppID': 'Chrome'}]), encoding='utf-8')
        with patch.object(app_launcher, '_cache_path', path), \
             patch.object(app_launcher, '_cache', []), \
             patch.object(app_launcher, '_expires', 0), \
             patch.object(app_launcher, '_refreshing', False), \
             patch.object(app_launcher.threading, 'Thread') as worker:
            assert app_launcher.installed_apps()[0]['name'] == 'Google Chrome'
            worker.return_value.start.assert_called_once()


def test_background_refresh_does_not_block_cached_lookup():
    started = threading.Event()
    release = threading.Event()
    completed = threading.Event()

    def slow_refresh():
        started.set()
        release.wait(2)
        completed.set()
        return [{'name': 'Google Chrome', 'id': 'Chrome'}]

    with patch.object(app_launcher, '_cache', [{'name': 'Google Chrome', 'id': 'Chrome'}]), \
         patch.object(app_launcher, '_expires', 0), \
         patch.object(app_launcher, '_refreshing', False), \
         patch.object(app_launcher, '_query_catalog', side_effect=slow_refresh):
        try:
            assert app_launcher.installed_apps()[0]['name'] == 'Google Chrome'
            assert started.wait(1)
            start = time.perf_counter()
            assert app_launcher.installed_apps()[0]['name'] == 'Google Chrome'
            assert (time.perf_counter() - start) < .05
        finally:
            release.set()
            assert completed.wait(1)
            deadline = time.monotonic() + 1
            while app_launcher._refreshing and time.monotonic() < deadline:
                time.sleep(.001)
            assert not app_launcher._refreshing
