import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import pytest

import jarvis.server as server
from jarvis.automation.pc_fastpath import direct_message_plan, fast_plan, message_send_requested
from jarvis.automation.desktop_agent import run_app, check_action
from tests.test_desktop_agent import model_with, node


def test_exact_teams_message_is_planned_locally():
    for command in ('Send a Teams message to Samir Sali saying Jarvis test',
                    'Open Teams and send a message to Samir Sali saying Jarvis test',
                    'Schicke eine Teams Nachricht an Samir Sali mit dem Text Jarvis test'):
        assert fast_plan(command) == [{'action':'draft_message','target':'Teams',
                                      'recipient':'Samir Sali','content':'Jarvis test'}]
    assert direct_message_plan('Send a Teams message to Samir Sali') is None


def test_snapchat_and_whatsapp_messages_are_planned_locally_and_send_is_intent_only():
    assert fast_plan('Open Snapchat and write a message to Branko saying Send me the notes.') == [
        {'action':'draft_message','target':'Snapchat','recipient':'Branko','content':'Send me the notes.'}]
    assert fast_plan('Write a WhatsApp message to Branko saying See you soon!') == [
        {'action':'draft_message','target':'WhatsApp','recipient':'Branko','content':'See you soon!'}]
    assert not message_send_requested('Open Snapchat and write a message to Branko saying Send me the notes.')
    assert message_send_requested('Open Snapchat and send a message to Branko saying Hello!')


@pytest.mark.asyncio
async def test_clarified_message_uses_original_app_and_never_sends_body_text_as_command():
    from jarvis.automation.local_pc import LocalPC
    local = LocalPC()
    local.pending = 'Open Snapchat and write a message to Branko'
    with patch('jarvis.automation.local_pc.run_app', new=AsyncMock(return_value={'ok':True,'message':'Draft prepared.'})) as run, \
         patch('jarvis.automation.local_pc.LLMClient.create', new=AsyncMock(side_effect=AssertionError('No planning request needed'))):
        result = await local.execute('I will send the notes tomorrow.')
    assert result == 'Draft prepared.'
    run.assert_awaited_once_with('Snapchat',
        'Open Snapchat and write a message to Branko\nUser clarification: I will send the notes tomorrow.',
        literal='I will send the notes tomorrow.', recipient='Branko', submit_allowed=False)


@pytest.mark.asyncio
async def test_autonomous_message_clarification_does_not_call_planner_llm():
    from jarvis.automation.local_pc import LocalPC
    local = LocalPC()
    with patch('jarvis.automation.local_pc.LLMClient.create', new=AsyncMock(side_effect=AssertionError('No LLM needed'))):
        phase = await local.plan_next(
            'Open Snapchat and write a message to Branko\nUser clarification: I will send the notes tomorrow.')
    assert phase == {'complete':False,'message':'','steps':[{
        'action':'draft_message','target':'Snapchat','recipient':'Branko',
        'content':'I will send the notes tomorrow.'}], 'terminal':True}


def test_repeated_message_authors_do_not_override_verified_chat_heading():
    nodes = [node(0, 'Message', 'Edit'),
             dict(node(1, 'Samir Sali', 'Text', in_list=True), conversation_heading=True),
             node(2, 'Samir Sali', 'Text', in_list=False),
             node(3, 'Other Person', 'Text', in_list=False)]
    action = {'action':'type', 'element':0, 'text':'Jarvis test', 'message':''}
    check_action(action, nodes, literal='Jarvis test', recipient='Samir Sali')
    with pytest.raises(Exception, match='conversation heading'):
        check_action(action, nodes, literal='Jarvis test', recipient='Other Person')


def test_voice_teams_message_skips_autonomous_planner():
    local = SimpleNamespace(pending='', last_action_silent=False,
                            execute=AsyncMock(return_value='Message submitted.'))
    with patch.object(server, 'LocalPC', return_value=local), \
         patch.object(server.jev, 'configured', return_value=True), \
         patch.object(server.agent_router, 'route', new=AsyncMock()) as route, \
         patch.object(server.AutonomousTasks, 'start', return_value='') as autonomous, \
         patch.object(server, 'synthesize_speech', new=AsyncMock(return_value=None)):
        with TestClient(server.app) as client:
            with client.websocket_connect('/ws/voice', subprotocols=['jarvis', 'jarvis.auth.' + server.JARVIS_AUTH_TOKEN]) as ws:
                ws.send_json({'type':'transcript', 'text':'Send a Teams message to Samir Sali saying Jarvis test',
                              'isFinal':True})
                for _ in range(8):
                    event = ws.receive_json()
                    if event.get('type') == 'text':
                        assert 'Message submitted.' in event['text']
                        break
                else:
                    pytest.fail('No Teams command response')
    local.execute.assert_awaited_once()
    assert local.execute.call_args.kwargs['planned_steps'] == [{
        'action':'draft_message','target':'Teams','recipient':'Samir Sali','content':'Jarvis test'}]
    autonomous.assert_not_called()
    route.assert_not_awaited()


def test_voice_missing_message_text_asks_locally_without_autonomous_planning():
    local = SimpleNamespace(pending='', last_action_silent=False,
                            execute=AsyncMock(return_value='What would you like to tell Branko?'))
    with patch.object(server, 'LocalPC', return_value=local), \
         patch.object(server.jev, 'configured', return_value=True), \
         patch.object(server.agent_router, 'route', new=AsyncMock()) as route, \
         patch.object(server.AutonomousTasks, 'start', return_value='') as autonomous, \
         patch.object(server, 'synthesize_speech', new=AsyncMock(return_value=None)):
        with TestClient(server.app) as client:
            with client.websocket_connect('/ws/voice', subprotocols=['jarvis', 'jarvis.auth.' + server.JARVIS_AUTH_TOKEN]) as ws:
                ws.send_json({'type':'transcript', 'text':'Open Snapchat and write a message to Branko',
                              'isFinal':True})
                for _ in range(8):
                    event = ws.receive_json()
                    if event.get('type') == 'text':
                        assert event['text'] == 'What would you like to tell Branko?'
                        break
                else:
                    pytest.fail('No local message clarification')
    local.execute.assert_awaited_once_with('Open Snapchat and write a message to Branko', '',
        planned_steps=[{'action':'ask','target':'','content':'What would you like to tell Branko?'}])
    autonomous.assert_not_called()
    route.assert_not_awaited()


class TeamsUI:
    def __init__(self, app, cancel):
        self.value = ''
        self.sent = False

    def snapshot(self):
        return {'elements':[node(0,'Message','Edit',self.value),
                            node(1,'Samir Sali','Header',in_list=False),node(2,'Send')]}

    def apply(self, action, options):
        check_action(action, self.snapshot()['elements'], **options)
        if action['action'] == 'type':
            self.value = action['text']
        elif action['action'] == 'click':
            self.sent = True
            self.value = ''
        return 'Verified'

    def close(self):
        pass


@pytest.mark.asyncio
async def test_teams_send_requires_matching_visible_recipient_and_exact_text():
    actions = [{'action':'type','element':0,'text':'Jarvis test','message':''},
               {'action':'click','element':2,'text':'','message':''},
               {'action':'done','element':-1,'text':'','message':''}]
    result = await run_app('Teams', 'Send a Teams message to Samir Sali saying Jarvis test',
                           literal='Jarvis test', recipient='Samir Sali', submit_allowed=True,
                           backend_factory=TeamsUI, model=model_with(actions))
    assert result['ok']
    assert 'submitted' in result['message']
    wrong = await run_app('Teams', 'Send a Teams message to Someone Else saying Jarvis test',
                          literal='Jarvis test', recipient='Someone Else', submit_allowed=True,
                          backend_factory=TeamsUI, model=model_with(actions))
    assert not wrong['ok']
