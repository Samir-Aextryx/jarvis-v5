import json
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
import httpx
from jarvis.core.agent_settings import AgentSettings
from jarvis.integrations.jev_client import JevClient, JevError, choice, save_jev_key, ENDPOINT
from jarvis.core.agent_router import AgentRouter, direct_intent


class JevTests(unittest.IsolatedAsyncioTestCase):
    async def test_contract_and_fixed_endpoint(self):
        def respond(request):
            self.assertEqual(str(request.url), ENDPOINT)
            self.assertEqual(request.headers['authorization'], 'Bearer test-secret')
            self.assertEqual(json.loads(request.content)['model'], 'jev-latest')
            return httpx.Response(200, json={'answers':{'test':{'type':'noul','noul':1}}})
        client = JevClient('test-secret', httpx.MockTransport(respond))
        self.assertEqual((await client.test())['status'], 'Connected')

    async def test_redirect_is_not_followed_and_errors_do_not_echo_key(self):
        calls=[]
        def respond(request):
            calls.append(request)
            return httpx.Response(307, headers={'Location':'https://example.com/steal'}, text='test-secret')
        client=JevClient('test-secret', httpx.MockTransport(respond))
        with self.assertRaises(JevError) as error:
            await client.test()
        self.assertNotIn('test-secret',str(error.exception)); self.assertEqual(len(calls),1)

    async def test_transient_retried_once_auth_not_retried(self):
        for status, expected in [(529,2),(401,1)]:
            calls=[]
            def respond(request):
                calls.append(request);return httpx.Response(status,text='credential must never appear')
            with self.assertRaises(JevError):
                await JevClient('test',httpx.MockTransport(respond)).test()
            self.assertEqual(len(calls),expected)

    def test_untrusted_choices_rejected(self):
        for answer in [{}, {'type':'choice','choice':'delete','confidence':1}, {'type':'choice','choice':'read','confidence':float('nan')}, {'type':'choice','choice':'read','confidence':.2}]:
            self.assertIsNone(choice(answer, {'read':None}))

    def test_save_failure_does_not_claim_success(self):
        with patch('jarvis.integrations.jev_client.get_vault',return_value=None):
            with self.assertRaises(JevError): save_jev_key('test-secret')
        vault=Mock();vault.set_password.side_effect=RuntimeError('test-secret')
        with patch('jarvis.integrations.jev_client.get_vault',return_value=vault):
            with self.assertRaises(JevError) as error:save_jev_key('test-secret')
            self.assertNotIn('test-secret',str(error.exception))

    async def test_fallback_and_disabled_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            settings=AgentSettings(root)
            with patch('jarvis.core.agent_router.agent_settings',settings),patch('jarvis.core.agent_router.jev.configured',return_value=False):
                self.assertEqual((await AgentRouter().route('Open everything'))['intent'],'work_apps')
                settings.save({'fallback':False})
                self.assertEqual((await AgentRouter().route('Open everything'))['intent'],'error')

    async def test_work_apps_are_configurable_and_not_parallel_focus(self):
        with tempfile.TemporaryDirectory() as root:
            settings=AgentSettings(root);settings.save({'work_apps':['Chrome','Teams']})
            launch=AsyncMock(return_value={'success':True,'confirmation':'Verified.'})
            with patch('jarvis.core.agent_router.agent_settings',settings),patch('jarvis.core.agent_router.open_app',launch):
                await AgentRouter().execute({'intent':'work_apps'})
                self.assertEqual([c.args[0] for c in launch.await_args_list],['Chrome','Teams'])
                settings.save({'automation':False});launch.reset_mock()
                await AgentRouter().execute({'intent':'work_apps'});launch.assert_not_awaited()

    def test_settings_persist_and_activity_is_content_free(self):
        with tempfile.TemporaryDirectory() as root:
            settings=AgentSettings(root);settings.save({'work_apps':['Spotify']})
            self.assertEqual(AgentSettings(root).get()['work_apps'],['Spotify'])
            with self.assertRaises(ValueError): settings.save({'work_apps':['Chrome; shutdown']})
            settings.activity('apps.open',True,1)
            self.assertEqual(set(settings.logs()[0]),{'tool','time','success','count'})
            settings.clear_logs();self.assertEqual(settings.logs(),[])

    async def test_missing_key_has_code_even_when_fallback_is_enabled(self):
        with tempfile.TemporaryDirectory() as root:
            settings=AgentSettings(root)
            with patch('jarvis.core.agent_router.agent_settings',settings),patch('jarvis.core.agent_router.jev.configured',return_value=False):
                decision=await AgentRouter().route('Open everything')
                self.assertEqual(decision['code'],'JEV_KEY_MISSING')
                self.assertIn('JEV_KEY_MISSING',decision['notice'])
                settings.save({'fallback':False})
                decision=await AgentRouter().route('Hello')
                self.assertEqual(decision['intent'],'error')
                self.assertIn('JEV_KEY_MISSING',decision['message'])

    async def test_missing_key_api_status_and_connection_test(self):
        import jarvis.server as server
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),base_url='http://testserver',headers={'Authorization':'Bearer '+server.JARVIS_AUTH_TOKEN}) as client:
            with patch('jarvis.integrations.jev_client.get_jev_key',return_value=''):
                status=await client.get('/api/agent/settings')
                self.assertEqual(status.json()['jev_error_code'],'JEV_KEY_MISSING')
                result=await client.post('/api/agent/jev/test')
                self.assertEqual(result.status_code,409)
                self.assertEqual(result.json()['code'],'JEV_KEY_MISSING')

    def test_aliases(self):
        for request in ['Open everything','Launch everything','Start my apps']:
            self.assertEqual(direct_intent(request),'work_apps')
        self.assertEqual(direct_intent('What’s new?'),'personal_update')
        self.assertIsNone(direct_intent('Do not open everything'))

    async def test_focus_existing_does_not_launch(self):
        from jarvis.automation.app_launcher import open_app
        app={'name':'Example','id':'test'}
        with patch('jarvis.automation.app_windows.focus_existing',return_value={'success':True,'confirmation':'Focused.'}),patch('jarvis.automation.app_launcher._launch') as launch:
            result=await open_app('Example',[app])
            self.assertTrue(result['success']);launch.assert_not_called()

    async def test_unverified_launch_is_not_success(self):
        from jarvis.automation.app_launcher import open_app
        with patch('jarvis.automation.app_windows.focus_existing',return_value=None),patch('jarvis.automation.app_windows.verify_started',return_value=False),patch('jarvis.automation.app_launcher._launch'):
            result=await open_app('Example',[{'name':'Example','id':'test'}],wait_until_ready=True)
            self.assertFalse(result['success']);self.assertEqual(result['state'],'unverified')

    def test_api_requires_auth_and_never_returns_key(self):
        import jarvis.server as server
        from fastapi.testclient import TestClient
        with TestClient(server.app) as client:
            self.assertEqual(client.get('/api/agent/settings').status_code,401)
            response=client.get('/api/agent/settings',headers={'Authorization':'Bearer '+server.JARVIS_AUTH_TOKEN})
            self.assertEqual(response.status_code,200)
            self.assertNotIn('key',response.json())


if __name__=='__main__':unittest.main()
