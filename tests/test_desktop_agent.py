import asyncio
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock,patch
from jarvis.automation.desktop_agent import _snapshot_for_model, check_action, failure_message, run_app, UIBlocked, WindowsUI


def node(index,name,role='Button',value='',**kwargs):
    return {'id':index,'name':name,'role':role,'value':value,**kwargs}


class FakeUI:
    def __init__(self,app,cancel):
        self.cancel=cancel
        self.value=''
        self.closed=False
        self.actions=[]

    def snapshot(self):
        return {'elements':[node(0,'Message','Edit',self.value),node(1,'Send')]}

    def apply(self,action,options):
        self.actions.append(action)
        if action['action']=='type':self.value=action['text']
        else:self.value=''
        return 'Verified'

    def close(self):self.closed=True


class FakeControl:
    def __init__(self, name, role, value='', runtime_id=(1,)):
        self.name=name
        self.value=value
        self.element_info=SimpleNamespace(runtime_id=runtime_id,control_type=role,
                                          CurrentIsPassword=False,automation_id='')
        self.invoked=False
        self.toggled=False

    def window_text(self):return self.name
    def is_visible(self):return True
    def is_enabled(self):return True
    @property
    def iface_value(self):return True
    def get_value(self):return self.value
    def set_edit_text(self,value):self.value=value
    def set_focus(self):pass
    def invoke(self):self.invoked=True


def model_with(actions):
    return SimpleNamespace(create=AsyncMock(side_effect=[SimpleNamespace(content=[SimpleNamespace(text=json.dumps(a))]) for a in actions]))


class DesktopTests(unittest.IsolatedAsyncioTestCase):
    def make_windows_ui(self, elements, controls, app='Example'):
        ui=WindowsUI.__new__(WindowsUI)
        ui.cancel=threading.Event()
        ui.app=app
        ui.window=Mock()
        ui.nodes=elements
        ui.items={node['id']:(controls[node['id']],tuple(node.get('identity',[])),node['name'])
                  for node in elements}
        return ui

    def test_model_snapshot_is_compact_but_preserves_controls_and_reports_truncation(self):
        state={'app':'Example','title':'Window','elements':[
            {'id':0,'identity':[1,2,3],'role':'Document','name':'Mail body',
             'value':'x'*30000,'value_known':True},
            {'id':1,'identity':[4,5,6],'role':'Edit','name':'Message',
             'value':'','value_known':True,'conversation_heading':True},
        ]}

        compact=_snapshot_for_model(state)
        compact_mail=_snapshot_for_model(state,{'mode':'read'})

        self.assertLessEqual(sum(len(node.get('value','')) for node in compact['elements']),18000)
        self.assertLessEqual(sum(len(node.get('value','')) for node in compact_mail['elements']),24000)
        self.assertEqual({node['id'] for node in compact['elements']},{0,1})
        self.assertTrue(all('identity' not in node for node in compact['elements']))
        document=next(node for node in compact_mail['elements'] if node['id']==0)
        self.assertEqual(len(document['value']),10000)
        self.assertFalse(document['value_known'])
        self.assertTrue(document['value_truncated'])
        self.assertTrue(next(node for node in compact['elements'] if node['id']==1)['conversation_heading'])

    async def test_app_task_constructs_one_planner_for_all_steps(self):
        class GenericUI(FakeUI):
            def snapshot(self):
                return {'elements':[node(0,'Open layout')]}

        client=model_with([
            {'action':'click','element':0,'text':'','message':''},
            {'action':'done','element':-1,'text':'','message':'Done'},
        ])
        with patch('jarvis.automation.desktop_agent.LLMClient',return_value=client) as client_factory:
            result=await run_app('Example','Open the layout tab',backend_factory=GenericUI)

        self.assertTrue(result['ok'])
        client_factory.assert_called_once_with()
        self.assertEqual(client.create.await_count,2)

    def test_ordinary_control_revalidation_avoids_a_second_full_snapshot(self):
        field=FakeControl('Message','Edit')
        ui=self.make_windows_ui([node(0,'Message','Edit',identity=[1])],{0:field})
        ui.snapshot=Mock(side_effect=AssertionError('ordinary action rescanned the entire app'))
        with patch.object(ui,'_check_scope',return_value=True):
            result=ui.apply({'action':'type','element':0,'text':'Hello'},
                            {'literal':'Hello','recipient':'','submit_allowed':False,'mail':None})
        self.assertEqual(field.value,'Hello')
        self.assertIn('verified',result)
        ui.snapshot.assert_not_called()

    def test_ordinary_control_rechecks_current_text_before_typing(self):
        field=FakeControl('Message','Edit','A user draft')
        ui=self.make_windows_ui([node(0,'Message','Edit',identity=[1])],{0:field})
        ui.snapshot=Mock(side_effect=AssertionError('ordinary action rescanned the entire app'))
        with patch.object(ui,'_check_scope',return_value=True):
            with self.assertRaisesRegex(UIBlocked,'already contains text'):
                ui.apply({'action':'type','element':0,'text':'Hello'},
                         {'literal':'Hello','recipient':'','submit_allowed':False,'mail':None})
        self.assertEqual(field.value,'A user draft')
        ui.snapshot.assert_not_called()

    def test_sensitive_send_refreshes_full_context_and_blocks_changed_recipient(self):
        send=FakeControl('Send','Button',runtime_id=(1,))
        original=[node(0,'Send',identity=[1]),node(1,'Message','Edit','Hello',identity=[2]),
                  node(2,'Sam','Header',in_list=False,identity=[3])]
        ui=self.make_windows_ui(original,{0:send,1:FakeControl('Message','Edit','Hello',(2,)),
                                          2:FakeControl('Sam','Header',runtime_id=(3,))})
        changed=[dict(original[0]),dict(original[1]),
                 node(2,'Another person','Header',in_list=False,identity=[4])]
        ui.snapshot=Mock(return_value={'elements':changed})
        with patch.object(ui,'_check_scope',return_value=True):
            with self.assertRaisesRegex(UIBlocked,'conversation changed'):
                ui.apply({'action':'click','element':0,'text':''},
                         {'literal':'Hello','recipient':'Sam','submit_allowed':True,'mail':None})
        ui.snapshot.assert_called_once_with()
        self.assertFalse(send.invoked)

    def test_inaccessible_generic_app_is_reported_as_untrained(self):
        error = ('This app is not exposing readable controls. No text was entered. '
                 'For Gmail reading, connect Google in Jarvis Settings; Outlook requires an accessible mail window.')
        self.assertEqual(
            failure_message(error),
            "I can't do that yet because I haven't been trained to control this app's interface.")

    def test_mail_access_error_keeps_provider_setup_instructions(self):
        error = ('This app is not exposing readable controls. No text was entered. '
                 'For Gmail reading, connect Google in Jarvis Settings; Outlook requires an accessible mail window.')
        self.assertIn('connect Google in Jarvis Settings', failure_message(error, mail=True))

    async def test_generic_app_task_stops_at_short_deadline(self):
        class SlowModel:
            async def create(self, **_kwargs):
                await asyncio.sleep(1)

        with patch('jarvis.automation.desktop_agent.APP_TASK_TIMEOUT_SECONDS', .01):
            result = await run_app('Example', 'Perform a slow task', backend_factory=FakeUI,
                                   model=SlowModel())
        self.assertFalse(result['ok'])
        self.assertIn('within a few seconds', result['message'])

    def test_mail_timeout_warns_to_check_before_retrying(self):
        message = failure_message(TimeoutError(), mail=True)
        self.assertIn('Check the draft or Sent folder', message)
        self.assertIn("won't repeat a send", message)

    async def test_unsupported_app_control_says_it_is_not_trained(self):
        class UnsupportedUI(FakeUI):
            def snapshot(self):
                raise UIBlocked('This application is outside the supported UI controls.')

        with patch('jarvis.automation.desktop_agent.WindowsUI', UnsupportedUI), \
             patch('jarvis.automation.desktop_agent.open_app', new=AsyncMock(return_value={'success':True,'app':'Example'})):
            result = await run_app('Example', 'Use an unsupported control', backend_factory=UnsupportedUI)
        self.assertFalse(result['ok'])
        self.assertEqual(result['message'], "I can't do that yet because I haven't been trained for that action.")

    async def test_ready_app_has_no_fixed_startup_sleep(self):
        with patch('jarvis.automation.desktop_agent.WindowsUI', FakeUI), \
             patch('jarvis.automation.desktop_agent.open_app', new=AsyncMock(return_value={'success':True,'app':'Example'})), \
             patch('jarvis.automation.desktop_agent.asyncio.sleep', new=AsyncMock()) as sleep:
            await run_app('Example', 'Inspect app', backend_factory=FakeUI,
                          model=model_with([{'action':'ask','element':-1,'text':'','message':'Ready'}]))
        sleep.assert_not_awaited()

    async def test_loading_wait_is_short_and_repeated_unchanged_waits_stop(self):
        wait = {'action':'wait','element':-1,'text':'','message':''}
        with patch('jarvis.automation.desktop_agent.asyncio.sleep', new=AsyncMock()) as sleep:
            result = await run_app('Example', 'Wait for a control', backend_factory=FakeUI,
                                   model=model_with([wait, wait]))
        self.assertFalse(result['ok'])
        self.assertIn('controls have not changed', result['message'])
        sleep.assert_awaited_once_with(.1)

    async def test_loading_app_retries_only_until_controls_exist(self):
        class LoadingUI(FakeUI):
            attempts = 0

            def snapshot(self):
                type(self).attempts += 1
                if type(self).attempts == 1:
                    raise UIBlocked('Open exactly one window or tab of the requested app, then try again.')
                return super().snapshot()

        with patch('jarvis.automation.desktop_agent.WindowsUI', LoadingUI), \
             patch('jarvis.automation.desktop_agent.open_app', new=AsyncMock(return_value={'success':True,'app':'Example'})), \
             patch('jarvis.automation.desktop_agent.asyncio.sleep', new=AsyncMock()) as sleep:
            await run_app('Example', 'Inspect app', backend_factory=LoadingUI,
                          model=model_with([{'action':'ask','element':-1,'text':'','message':'Ready'}]))
        self.assertEqual(LoadingUI.attempts, 2)
        sleep.assert_awaited_once_with(.05)

    async def test_mail_splash_controls_do_not_trigger_planning(self):
        class LoadingMailUI(FakeUI):
            attempts = 0

            def snapshot(self):
                type(self).attempts += 1
                if type(self).attempts == 1:
                    return {'elements': [node(0, 'Loading', 'Button')]}
                return {'elements': [node(0, 'New mail', 'Button')]}

        with patch('jarvis.automation.desktop_agent.WindowsUI', LoadingMailUI), \
             patch('jarvis.automation.desktop_agent.open_app', new=AsyncMock(return_value={'success':True,'app':'Outlook'})), \
             patch('jarvis.automation.desktop_agent.asyncio.sleep', new=AsyncMock()) as sleep:
            await run_app('Outlook', 'Write mail', backend_factory=LoadingMailUI,
                          mail={'mode':'draft','recipient':'alex@example.com','subject':'Meeting','body':'Hello'},
                          model=model_with([{'action':'ask','element':-1,'text':'','message':'Ready'}]))
        self.assertEqual(LoadingMailUI.attempts, 2)
        sleep.assert_not_awaited()

    def test_existing_draft_and_password_are_protected(self):
        action={'action':'type','element':0,'text':'replacement'}
        for n in [node(0,'Message','Edit','existing'),node(0,'Password','Edit'),node(0,'Unknown','Edit',value_known=False)]:
            with self.assertRaises(UIBlocked):check_action(action,[n])

    def test_send_requires_explicit_intent(self):
        with self.assertRaises(UIBlocked):check_action({'action':'click','element':1},[node(1,'Send')])
        check_action({'action':'click','element':1},[node(1,'Send')],submit_allowed=True)
        with self.assertRaises(UIBlocked):check_action({'action':'click','element':1},[node(1,'Delete')],submit_allowed=True)

    def test_literal_message_and_unique_heading(self):
        action={'action':'type','element':0,'text':'Hello'}
        elements=[node(0,'Message','Edit'),node(1,'Franco','Header',in_list=False)]
        check_action(action,elements,literal='Hello',recipient='Franco')
        for wrong in [elements[:1],elements+[node(2,'Franco','Header',in_list=False)]]:
            with self.assertRaises(UIBlocked):check_action(action,wrong,literal='Hello',recipient='Franco')
        with self.assertRaises(UIBlocked):check_action(dict(action,text='Different text'),elements,literal='Hello',recipient='Franco')

    async def test_draft_is_entered_without_sending(self):
        actions=[{'action':'type','element':0,'text':'Hello','message':''},{'action':'done','element':-1,'text':'','message':'Done'}]
        with patch('jarvis.automation.desktop_agent.asyncio.sleep', new=AsyncMock()) as sleep:
            result=await run_app('Example','Write Hello',literal='Hello',backend_factory=FakeUI,model=model_with(actions))
        self.assertTrue(result['ok'])
        self.assertIn('not been sent',result['message'])
        sleep.assert_not_awaited()

    async def test_submission_requires_entry_and_cleared_draft(self):
        actions=[{'action':'type','element':0,'text':'Hello','message':''},{'action':'click','element':1,'text':'','message':''},{'action':'done','element':-1,'text':'','message':'Done'}]
        result=await run_app('Example','Send Hello',literal='Hello',submit_allowed=True,backend_factory=FakeUI,model=model_with(actions))
        self.assertTrue(result['ok'])
        self.assertIn('not verified a reply or delivery',result['message'])
        bad=await run_app('Example','Send Hello',literal='Hello',submit_allowed=True,backend_factory=FakeUI,model=model_with(actions[1:]))
        self.assertFalse(bad['ok'])

    async def test_model_cannot_claim_unperformed_submission(self):
        result=await run_app('Example','Send Hello',literal='Hello',submit_allowed=True,backend_factory=FakeUI,
            model=model_with([{'action':'done','element':-1,'text':'','message':'Sent successfully!'}]))
        self.assertFalse(result['ok'])
        self.assertNotIn('successfully',result['message'])

    async def test_cancel_interrupts_model_and_closes_ui(self):
        started=asyncio.Event()
        async def slow(**kwargs):
            started.set()
            await asyncio.sleep(30)
        instance=FakeUI('Example',None)
        task=asyncio.create_task(run_app('Example','Read',backend_factory=lambda a,c:instance,model=SimpleNamespace(create=slow)))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(instance.closed)

    async def test_generic_app_action_is_routed_to_driver(self):
        from jarvis.automation.local_pc import LocalPC
        local=LocalPC()
        with patch('jarvis.automation.local_pc.run_app',new=AsyncMock(return_value={'ok':True,'message':'Opened the requested view.'})) as driver:
            result=await local.execute('Use Word to open the layout tab',planned_steps=[{'action':'use_app','target':'Word','content':'Open layout'}])
        driver.assert_awaited_once_with('Word','Use Word to open the layout tab')
        self.assertTrue(local.last_action_ok)

