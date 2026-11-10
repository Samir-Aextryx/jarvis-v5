import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from jarvis.core.auth import authenticate_websocket, auth_token
from jarvis.integrations import credentials_vault
from jarvis.voice.voice_turn import SerializedSocket
from jarvis.core.state import SharedCache

class SecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_handshake_accepts_header_and_rejects_query(self):
        for headers, expected in [({},False),({'sec-websocket-protocol':'jarvis, jarvis.auth.wrong'},False),({'sec-websocket-protocol':'jarvis, jarvis.auth.valid'},True)]:
            ws=Mock();ws.headers=headers;ws.query_params={'token':'valid'};ws.accept=AsyncMock();ws.close=AsyncMock()
            self.assertEqual(await authenticate_websocket(ws,'valid'),expected)
            # Rejections accept first so the browser can observe close code 4001.
            ws.accept.assert_awaited_once_with(subprotocol='jarvis' if 'jarvis' in headers.get('sec-websocket-protocol','') else None)
            if expected:
                ws.close.assert_not_called()
            else:
                ws.close.assert_awaited_once_with(code=4001, reason='Unauthorized')

    async def test_non_ascii_token_is_rejected_without_crashing(self):
        ws=Mock();ws.headers={'sec-websocket-protocol':'jarvis, jarvis.auth.grüße'};ws.accept=AsyncMock();ws.close=AsyncMock()
        self.assertFalse(await authenticate_websocket(ws,'valid'))
        ws.close.assert_awaited_once_with(code=4001, reason='Unauthorized')

    def test_auth_is_read_from_vault_and_failure_does_not_write_plaintext(self):
        vault=Mock();vault.get_password.return_value='existing'
        with patch('jarvis.core.auth.get_vault',return_value=vault):
            self.assertEqual(auth_token(),'existing');vault.set_password.assert_not_called()
        with patch('jarvis.core.auth.get_vault',return_value=None):
            with self.assertRaises(RuntimeError):auth_token()

    def test_failed_migration_retains_original(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'.env';original='JARVIS_AUTH_TOKEN=example-test-token\n'
            path.write_text(original)
            vault=Mock();vault.get_password.return_value=None;vault.set_password.side_effect=RuntimeError('private value')
            with patch.object(credentials_vault,'DATA_ROOT',Path(root)),patch.object(credentials_vault,'get_vault',return_value=vault):
                credentials_vault.migrate_plaintext_secrets()
            self.assertEqual(path.read_text(),original)

    async def test_socket_serializes_concurrent_writes(self):
        active=0;maximum=0
        async def send(data):
            nonlocal active,maximum
            active+=1;maximum=max(maximum,active)
            await asyncio.sleep(.001);active-=1
        sink=Mock();sink.send_json=send;socket=SerializedSocket(sink)
        await asyncio.gather(*(socket.send_json({'i':i}) for i in range(30)))
        self.assertEqual(maximum,1)

    def test_context_snapshot_is_independent(self):
        state=SharedCache({'calendar':'old'})
        snapshot=state.snapshot();state['calendar']='new'
        self.assertEqual(snapshot['calendar'],'old')

    async def test_concurrent_task_limit_and_disconnect_during_notify(self):
        from jarvis.core.tasks import ClaudeTaskManager
        with patch('jarvis.core.tasks.SuccessTracker'):
            manager=ClaudeTaskManager(max_concurrent=1)
        gate=asyncio.Event()
        jobs=[]
        async def work(task):
            jobs.append(asyncio.current_task());await gate.wait()
        manager._run_task=work
        with patch.object(manager,'_notify',new=AsyncMock()):
            results=await asyncio.gather(manager.spawn('one'),manager.spawn('two'),return_exceptions=True)
            self.assertEqual(sum(isinstance(r,RuntimeError) for r in results),1)
        gate.set();await asyncio.gather(*jobs)
        socket=Mock()
        async def failed_send(data):
            manager.unregister_websocket(socket)
            raise ConnectionError('closed')
        socket.send_json=failed_send;manager.register_websocket(socket)
        await manager._notify({'type':'status'})
        self.assertEqual(manager._websockets,[])
