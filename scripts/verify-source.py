"""Offline smoke check of the backend as the desktop shell starts it, isolated from personal data and provider keys."""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import httpx

root = Path(__file__).resolve().parents[1]
backend = [sys.executable, str(root / 'scripts/desktop-server.py')]
with tempfile.TemporaryDirectory(prefix='jarvis-source-test-') as folder:
    env = dict(os.environ, JARVIS_DATA_DIR=folder, JARVIS_PORT='8346', PYTHONUTF8='1', OPENAI_API_KEY='', FISH_API_KEY='')
    with open(Path(folder)/'server.log', 'w', encoding='utf-8') as output:
        process = subprocess.Popen(backend, cwd=root, env=env, stdout=output, stderr=output, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        with httpx.Client(base_url='http://127.0.0.1:8346', timeout=5) as client:
            for _ in range(100):
                try:
                    response=client.get('/api/health')
                    if response.status_code==200:break
                except httpx.ConnectError:pass
                if process.poll() is not None:raise RuntimeError('Backend exited; see temporary log.')
                time.sleep(.2)
            else:raise RuntimeError('Backend did not become ready.')
            assert client.get('/api/agent/settings').status_code==401
            token=subprocess.check_output([*backend,'--print-auth-token'], env=env, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW).strip()
            client.headers['Authorization']='Bearer '+token
            for route in ('/api/agent/settings','/api/settings/status','/api/memory/profile','/api/local-calendar/events','/','/pcm-capture.js'):
                client.get(route).raise_for_status()
            assert not (Path(folder)/'.env').exists() or 'JARVIS_AUTH_TOKEN=' not in (Path(folder)/'.env').read_text()
            print('Backend, authentication, assets, settings, memory and calendar: passed.')
    finally:
        process.terminate();process.wait(timeout=15)
        # Remove the disposable test credential, never the installed app credential.
        import hashlib
        from keyring.backends.Windows import WinVaultKeyring
        service='Jarvis-v5-Keys-'+hashlib.sha256(str(Path(folder).resolve()).encode()).hexdigest()[:16]
        vault=WinVaultKeyring()
        if vault.get_password(service,'JARVIS_AUTH_TOKEN'):vault.delete_password(service,'JARVIS_AUTH_TOKEN')
