import asyncio

import tempfile

import unittest

from pathlib import Path

from unittest.mock import AsyncMock,patch

from jarvis.automation.autonomous_tasks import AutonomousTasks,recent_jobs,goal_request

from jarvis.voice.transcript_guard import clean_transcript





class AutonomyTests(unittest.IsolatedAsyncioTestCase):

    def test_hallucinated_vocabulary_is_not_a_command(self):

        text='Windows App-Namen: Outlook, WhatsApp, Snapchat, Google Chrome, Proton VPN, Mullvad VPN, FortiClient VPN.'

        self.assertEqual(clean_transcript(text),'')

        self.assertEqual(clean_transcript('Open Outlook and WhatsApp'),'Open Outlook and WhatsApp')

        self.assertEqual(goal_request('Autonomous task: Open Chrome'),'Open Chrome')



    def test_natural_task_prefixes(self):

        for prefix in ['Take care of', 'Handle this task:', 'Kümmere dich um', 'Erledige selbstständig']:

            self.assertEqual(goal_request(prefix + ' Open Chrome'), 'Open Chrome')

        self.assertIsNone(goal_request('What does take care of mean?'))



    async def test_goal_creates_verified_file_and_history(self):

        with tempfile.TemporaryDirectory() as root, patch('jarvis.automation.local_pc.desktop',return_value=Path(root)):

            runner=AutonomousTasks(root)

            result=await runner.run('Save a file called result.txt to Desktop with the content Task completed.')

            self.assertIn('Saved',result)

            self.assertEqual(Path(root,'result.txt').read_text(),'Task completed.')

            self.assertEqual(recent_jobs(root)[0]['state'],'completed')

            self.assertEqual(recent_jobs(root)[0]['steps'][0]['state'],'completed')


    async def test_direct_app_open_completes_without_remote_planning(self):

        with tempfile.TemporaryDirectory() as root:

            runner=AutonomousTasks(root)

            with patch('jarvis.automation.local_pc.open_app',new=AsyncMock(return_value={
                'success':True,'confirmation':'Opening Chrome.'})), \
                 patch('jarvis.automation.local_pc.LLMClient.create',new=AsyncMock(
                     side_effect=AssertionError('A direct app open must not call the planner'))):

                result=await runner.run('Open Chrome')

            self.assertEqual(runner.job['state'],'completed')

            self.assertEqual(runner.job['rounds'],1)

            self.assertEqual(len(runner.job['steps']),1)

            self.assertIn('Opening Chrome',result)


    async def test_explicit_local_file_read_completes_without_remote_planning(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root,'notes for Jarvis.txt')
            source.write_text('The local task was completed.',encoding='utf-8')
            runner=AutonomousTasks(root)
            with patch('jarvis.automation.local_pc.LLMClient.create',new=AsyncMock(
                    side_effect=AssertionError('An explicit local file read must not call the model'))):
                result=await runner.run(f'Read the file "{source}".')
            self.assertIn('The local task was completed.',result)
            self.assertEqual(runner.job['state'],'completed')
            self.assertEqual(runner.job['rounds'],1)
            self.assertEqual(runner.job['steps'][0]['action'],'read_file')


    async def test_calendar_result_completes_without_redundant_task_planning(self):
        with tempfile.TemporaryDirectory() as root:
            runner=AutonomousTasks(root)
            with patch('jarvis.automation.local_pc.run_local_calendar',new=AsyncMock(
                    return_value={'ok':True,'message':'Your Jarvis calendar: []'})), \
                 patch('jarvis.automation.local_pc.LLMClient.create',new=AsyncMock(
                     side_effect=AssertionError('Calendar parser already verified this task'))):
                result=await runner.run('Show my calendar tomorrow')
            self.assertIn('calendar',result.casefold())
            self.assertEqual(runner.job['state'],'completed')
            self.assertEqual(runner.job['rounds'],1)
            self.assertEqual([step['action'] for step in runner.job['steps']],['calendar_task'])


    async def test_calendar_action_and_explicit_app_open_run_in_parallel(self):
        with tempfile.TemporaryDirectory() as root:
            runner=AutonomousTasks(root)
            active=0
            max_active=0
            both_started=asyncio.Event()
            executed=[]

            async def record(action):
                nonlocal active,max_active
                executed.append(action)
                active+=1
                max_active=max(max_active,active)
                if len(executed)==2:
                    both_started.set()
                try:
                    await asyncio.wait_for(both_started.wait(),.5)
                finally:
                    active-=1

            async def calendar(*_args,**_kwargs):
                await record('calendar_task')
                return {'ok':True,'message':'Your Jarvis calendar: []'}

            async def open_outlook(*_args,**_kwargs):
                await record('open_app')
                return {'success':True,'confirmation':'Opening Outlook.'}

            with patch('jarvis.automation.local_pc.run_local_calendar',new=calendar), \
                 patch('jarvis.automation.local_pc.open_app',new=open_outlook), \
                 patch('jarvis.automation.local_pc.LLMClient.create',new=AsyncMock(
                     side_effect=AssertionError('The explicit calendar request is planned locally'))):
                await runner.run('Show my calendar tomorrow and open Outlook')

            self.assertCountEqual(executed,['calendar_task','open_app'])
            self.assertEqual(max_active,2)
            self.assertEqual(runner.job['state'],'completed')
            self.assertEqual(runner.job['rounds'],1)


    async def test_multiple_app_open_uses_one_local_action(self):

        with tempfile.TemporaryDirectory() as root:

            runner=AutonomousTasks(root)

            opened=[]

            async def open_apps(target,**kwargs):

                opened.append(target)

                return {'success':True,'confirmation':'Opening Chrome and Notepad.'}

            with patch('jarvis.automation.local_pc.open_app',new=open_apps), \
                 patch('jarvis.automation.local_pc.LLMClient.create',new=AsyncMock(
                     side_effect=AssertionError('Explicit app batches must not call the planner'))):

                await runner.run('Open Chrome and Notepad')

            self.assertEqual(opened,[['Chrome','Notepad']])

            self.assertEqual(runner.job['rounds'],1)

            self.assertEqual(runner.job['state'],'completed')


    async def test_task_records_content_free_planning_and_action_times(self):
        with tempfile.TemporaryDirectory() as root:
            runner=AutonomousTasks(root)
            updates=AsyncMock()
            phases=[{'complete':False,'steps':[{'action':'open_app','target':'C:/private/Outlook',
                       'content':'','recipient':''}]},
                    {'complete':True,'steps':[],'message':'The requested app is open.'}]

            async def execute(*args,planned_steps,**kwargs):
                await asyncio.sleep(.01)
                runner.planner.last_action_ok=True
                return 'Opened.'

            with patch.object(runner.planner,'plan_next',new=AsyncMock(side_effect=phases)), \
                 patch.object(runner.planner,'execute',new=execute):
                runner.start('Open the private Outlook app',notify=updates)
                await runner.task

            self.assertGreaterEqual(runner.job['duration_ms'],runner.job['action_ms'])
            self.assertGreaterEqual(runner.job['planning_ms'],0)
            self.assertGreaterEqual(runner.job['steps'][0]['duration_ms'],5)
            final_update=updates.call_args_list[-1].args[0]
            self.assertEqual(final_update['duration_ms'],runner.job['duration_ms'])
            self.assertEqual(final_update['planning_ms'],runner.job['planning_ms'])
            stored=next((Path(root)/'data/autonomous-tasks').glob('*.json')).read_text(encoding='utf-8')
            self.assertIn('duration_ms',stored)
            self.assertNotIn('C:/private',stored)
            self.assertNotIn('private Outlook',stored)



    async def test_missing_information_never_creates_a_file(self):

        with tempfile.TemporaryDirectory() as root:

            runner=AutonomousTasks(root)

            await runner.run('Save a file to Desktop')

            self.assertEqual(runner.job['state'],'needs_input')

            self.assertTrue(runner.pending)



    async def test_stop_cancels_background_planning(self):

        with tempfile.TemporaryDirectory() as root:

            runner=AutonomousTasks(root)

            started=asyncio.Event()

            async def slow(*args):

                started.set()

                await asyncio.sleep(30)

            with patch.object(runner.planner,'plan_next',new=slow):

                runner.start('Open Chrome')

                await started.wait()

                runner.start('Open Notepad')

                await runner.cancel()

            self.assertEqual(recent_jobs(root)[0]['state'],'cancelled')

            self.assertFalse(runner.queued_goals)


    async def test_new_task_during_active_work_is_queued_and_not_lost(self):

        with tempfile.TemporaryDirectory() as root:

            runner=AutonomousTasks(root)

            first_started=asyncio.Event()

            release_first=asyncio.Event()

            executed=[]

            async def execute(request,previous,planned_steps):

                executed.append(request)

                if request=='Open Chrome':

                    first_started.set()

                    await release_first.wait()

                runner.planner.last_action_ok=True

                return 'Opened ' + planned_steps[0]['target']

            with patch.object(runner.planner,'execute',new=execute):

                runner.start('Open Chrome')

                await first_started.wait()

                response=runner.start('Open Notepad')

                self.assertIn('next task',response)

                release_first.set()

                await runner.task

            self.assertEqual(executed,['Open Chrome','Open Notepad'])

            self.assertEqual(runner.job['goal'],'Open Notepad')

            self.assertEqual(runner.job['state'],'completed')

            self.assertFalse(runner.queued_goals)



    async def test_completed_steps_are_not_replayed_after_failure(self):

        with tempfile.TemporaryDirectory() as root, patch('jarvis.automation.local_pc.desktop',return_value=Path(root)):

            runner=AutonomousTasks(root)

            steps=[{'action':'write_desktop','target':'ok.txt','content':'first'}, {'action':'write_desktop','target':'ok.txt','content':'second'}]

            with patch.object(runner.planner,'plan_next',new=AsyncMock(return_value={'complete':False,'steps':steps})):

                await runner.run('test')

            self.assertEqual(Path(root,'ok.txt').read_text(),'first')

            self.assertEqual(runner.job['state'],'needs_attention')

            self.assertEqual(runner.job['steps'][1]['attempts'],1)



    async def test_read_results_drive_next_plan(self):

        with tempfile.TemporaryDirectory() as root:

            runner=AutonomousTasks(root)

            phases=[{'complete':False,'steps':[{'action':'list_folder','target':'Desktop','content':'','recipient':''}]},

                    {'complete':False,'steps':[{'action':'read_file','target':'C:/notes.txt','content':'','recipient':''}]},

                    {'complete':True,'steps':[],'message':'Read the requested notes.'}]

            observed=[]

            async def plan(goal,previous,observations):

                observed.append(list(observations))

                return phases[len(observed)-1]

            async def execute(*args,**kwargs):

                runner.planner.last_action_ok=True

                return 'notes.txt' if len(observed)==1 else 'These are the notes.'

            with patch.object(runner.planner,'plan_next',new=plan),patch.object(runner.planner,'execute',new=execute):

                await runner.run('Find my notes on Desktop and read them')

            self.assertEqual(observed[1][0]['result'],'notes.txt')

            self.assertEqual(observed[2][1]['result'],'These are the notes.')

            self.assertEqual(runner.job['state'],'completed')


    async def test_independent_file_reads_in_one_phase_are_not_dropped(self):

        with tempfile.TemporaryDirectory() as root:

            runner=AutonomousTasks(root)

            phase={'complete':False,'steps':[
                {'action':'read_file','target':'C:/notes/a.txt','content':'','recipient':''},
                {'action':'read_file','target':'C:/notes/b.txt','content':'','recipient':''}],
                'message':'','terminal':True}

            observed=[]
            executed=[]
            both_started=asyncio.Event()

            async def plan(goal,previous,observations):

                observed.append(list(observations))

                return phase if len(observed)==1 else {'complete':True,'steps':[],'message':'Both files were read.'}

            async def execute(reader,*args,planned_steps,**kwargs):

                executed.append(planned_steps[0]['target'])

                if len(executed)==2:

                    both_started.set()

                await asyncio.wait_for(both_started.wait(),.5)

                reader.last_action_ok=True

                return 'Contents of ' + planned_steps[0]['target']

            with patch.object(runner.planner,'plan_next',new=plan), \
                 patch('jarvis.automation.local_pc.LocalPC.execute',new=execute):

                await runner.run('Read C:/notes/a.txt and C:/notes/b.txt')

            self.assertEqual(set(executed),{'C:/notes/a.txt','C:/notes/b.txt'})

            self.assertEqual(len(runner.observations),2)

            self.assertEqual(runner.job['state'],'completed')

            self.assertEqual(runner.job['rounds'],1)


    async def test_two_explicit_local_file_reads_skip_planning_and_run_in_parallel(self):
        with tempfile.TemporaryDirectory() as root:
            paths=[Path(root,'meeting notes.txt'),Path(root,'project notes.md')]
            paths[0].write_text('The meeting starts at ten.',encoding='utf-8')
            paths[1].write_text('The project is ready.',encoding='utf-8')
            runner=AutonomousTasks(root)
            request=f'Read files "{paths[0]}" and "{paths[1]}"'
            with patch('jarvis.automation.local_pc.LLMClient.create',new=AsyncMock(
                    side_effect=AssertionError('Explicit read-only paths need no planner call'))):
                result=await runner.run(request)
            self.assertIn('meeting notes.txt:',result)
            self.assertIn('project notes.md:',result)
            self.assertIn('The meeting starts at ten.',result)
            self.assertIn('The project is ready.',result)
            self.assertEqual(runner.job['state'],'completed')
            self.assertEqual(runner.job['rounds'],1)
            self.assertEqual([row['action'] for row in runner.job['steps']],['read_file','read_file'])


    async def test_explicit_file_read_and_app_open_run_in_parallel_without_planning(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root,'notes.txt')
            source.write_text('Task notes.',encoding='utf-8')
            runner=AutonomousTasks(root)
            active=0
            max_active=0
            started=asyncio.Event()
            executed=[]

            async def execute(local,*args,planned_steps,**kwargs):
                nonlocal active,max_active
                step=planned_steps[0]
                executed.append(step['action'])
                active+=1
                max_active=max(max_active,active)
                if len(executed)==2:
                    started.set()
                try:
                    await asyncio.wait_for(started.wait(),.5)
                    local.last_action_ok=True
                    return 'File read.' if step['action']=='read_file' else 'Outlook opened.'
                finally:
                    active-=1

            request=f'Read the file "{source}" and open Outlook'
            with patch('jarvis.automation.local_pc.LLMClient.create',new=AsyncMock(
                    side_effect=AssertionError('A named file and independent app open need no planner call'))), \
                 patch('jarvis.automation.local_pc.LocalPC.execute',new=execute):
                await runner.run(request)

            self.assertCountEqual(executed,['read_file','open_app'])
            self.assertEqual(max_active,2)
            self.assertEqual(runner.job['state'],'completed')
            self.assertEqual(runner.job['rounds'],1)


    async def test_parallel_file_reads_return_actual_contents(self):

        with tempfile.TemporaryDirectory() as root:

            paths=[Path(root,'a.txt'),Path(root,'b.txt')]

            paths[0].write_text('First source.',encoding='utf-8')

            paths[1].write_text('Second source.',encoding='utf-8')

            runner=AutonomousTasks(root)

            phase={'complete':False,'steps':[
                {'action':'read_file','target':str(path),'content':'','recipient':''}
                for path in paths], 'message':'','terminal':True}

            with patch.object(runner.planner,'plan_next',new=AsyncMock(return_value=phase)):

                await runner.run('Read both local source files')

            self.assertEqual([item['result'] for item in runner.observations],
                             ['First source.','Second source.'])

            self.assertTrue(all(item['success'] for item in runner.observations))

            self.assertEqual(runner.job['state'],'completed')
            self.assertEqual(runner.job['rounds'],1)



    async def test_independent_app_launches_start_concurrently(self):

        with tempfile.TemporaryDirectory() as root:

            runner=AutonomousTasks(root)

            phase={'complete':False,'steps':[
                {'action':'open_app','target':'Outlook','content':'','recipient':''},
                {'action':'open_app','target':'Chrome','content':'','recipient':''}], 'message':''}

            complete={'complete':True,'steps':[],'message':'Both apps are open.'}

            launched=[]
            both_started=asyncio.Event()

            async def execute(executor,*args,planned_steps,**kwargs):
                launched.append(planned_steps[0]['target'])
                if len(launched)==2:
                    both_started.set()
                await asyncio.wait_for(both_started.wait(),.5)
                executor.last_action_ok=True
                return 'Opened '+planned_steps[0]['target']

            with patch.object(runner.planner,'plan_next',new=AsyncMock(side_effect=[phase,complete])), \
                 patch('jarvis.automation.local_pc.LocalPC.execute',new=execute):
                await runner.run('Open Outlook and Chrome')

            self.assertCountEqual(launched,['Outlook','Chrome'])
            self.assertEqual(len(runner.observations),2)
            self.assertTrue(all(item['success'] for item in runner.observations))
            self.assertEqual(runner.job['state'],'completed')


    async def test_desktop_app_and_website_open_serially_without_a_planner_call(self):

        with tempfile.TemporaryDirectory() as root:

            runner=AutonomousTasks(root)

            launched=[]
            active=0
            max_active=0

            async def execute(executor,*args,planned_steps,**kwargs):
                nonlocal active,max_active
                active+=1
                max_active=max(max_active,active)
                launched.append(planned_steps[0]['action'])
                try:
                    await asyncio.sleep(.01)
                    executor.last_action_ok=True
                    return 'Launch verified.'
                finally:
                    active-=1

            with patch('jarvis.automation.local_pc.LLMClient.create',new=AsyncMock(
                     side_effect=AssertionError('A plain app-and-website open needs no model call'))), \
                 patch('jarvis.automation.local_pc.LocalPC.execute',new=execute):
                await runner.run('Open Outlook and open YouTube')

            self.assertCountEqual(launched,['open_app','open_url'])
            self.assertEqual(max_active,1)
            self.assertEqual(len(runner.observations),2)
            self.assertEqual(runner.job['state'],'completed')
            self.assertEqual(runner.job['rounds'],1)


    async def test_browser_and_website_launch_remain_serial(self):

        with tempfile.TemporaryDirectory() as root:

            runner=AutonomousTasks(root)

            active=0
            max_active=0
            executed=[]

            async def execute(executor,*args,planned_steps,**kwargs):
                nonlocal active,max_active
                active+=1
                max_active=max(max_active,active)
                executed.append(planned_steps[0]['action'])
                await asyncio.sleep(.01)
                executor.last_action_ok=True
                active-=1
                return 'Launch verified.'

            with patch('jarvis.automation.local_pc.LLMClient.create',new=AsyncMock(
                     side_effect=AssertionError('A plain app-and-website open needs no model call'))), \
                 patch('jarvis.automation.local_pc.LocalPC.execute',new=execute):
                await runner.run('Open Chrome and open YouTube')

            self.assertEqual(executed,['open_app','open_url'])
            self.assertEqual(max_active,1)
            self.assertEqual(runner.job['state'],'completed')
            self.assertEqual(runner.job['rounds'],1)


    async def test_clarification_resumes_same_job_without_replaying_write(self):

        with tempfile.TemporaryDirectory() as root,patch('jarvis.automation.local_pc.desktop',return_value=Path(root)):

            runner=AutonomousTasks(root)

            phases=[{'complete':False,'steps':[{'action':'write_desktop','target':'first.txt','content':'first','recipient':''},

                       {'action':'ask','target':'','content':'What should the second file contain?','recipient':''}]},

                    {'complete':False,'steps':[{'action':'write_desktop','target':'second.txt','content':'second','recipient':''}]},

                    {'complete':True,'steps':[],'message':'Both files saved.'}]

            with patch.object(runner.planner,'plan_next',new=AsyncMock(side_effect=phases)):

                await runner.run('Save two files')

                job_id=runner.job['id']

                self.assertEqual(runner.job['state'],'needs_input')

                await runner.run('Use second')

            self.assertEqual(runner.job['id'],job_id)

            self.assertEqual(len(runner.job['steps']),2)

            self.assertEqual(Path(root,'first.txt').read_text(),'first')

            self.assertEqual(Path(root,'second.txt').read_text(),'second')

            self.assertEqual(runner.job['state'],'completed')



    async def test_repeated_send_is_blocked(self):

        with tempfile.TemporaryDirectory() as root:

            runner=AutonomousTasks(root)

            phase={'complete':False,'steps':[{'action':'chatgpt_prompt','target':'','content':'hello','recipient':''}]}

            async def execute(*args,**kwargs):

                runner.planner.last_action_ok=True

                return 'Submitted.'

            with patch.object(runner.planner,'plan_next',new=AsyncMock(return_value=phase)),patch.object(runner.planner,'execute',new=AsyncMock(side_effect=execute)) as action:

                await runner.run('Tell ChatGPT hello')

            self.assertEqual(action.await_count,1)

            self.assertEqual(runner.job['state'],'needs_attention')



    async def test_failure_cannot_be_declared_complete(self):

        with tempfile.TemporaryDirectory() as root:

            runner=AutonomousTasks(root)

            phases=[{'complete':False,'steps':[{'action':'read_file','target':'missing','content':'','recipient':''}]},

                    {'complete':True,'steps':[],'message':'All done!'}]

            with patch.object(runner.planner,'plan_next',new=AsyncMock(side_effect=phases)),patch.object(runner.planner,'execute',new=AsyncMock(return_value='File missing')):

                await runner.run('Read the missing file')

            self.assertEqual(runner.job['state'],'needs_attention')



    async def test_progress_includes_question(self):

        with tempfile.TemporaryDirectory() as root:

            runner=AutonomousTasks(root)

            updates=AsyncMock()

            runner.start('Save a file to Desktop',notify=updates)

            await runner.task

            self.assertEqual(updates.call_args.args[0]['state'],'needs_input')

            self.assertTrue(updates.call_args.args[0]['message'])
