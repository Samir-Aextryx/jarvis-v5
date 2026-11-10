"""Bounded goal execution with durable progress and no replay of completed steps."""
import asyncio
import json
from pathlib import Path
import re
import time
import uuid
from urllib.parse import urlsplit
from jarvis.automation.local_pc import LocalPC
from jarvis.automation.pc_control import controller as pc
from jarvis.core.runtime_paths import DATA_ROOT
from jarvis.voice.speech_language import remember_english
from jarvis.automation.pc_fastpath import normalize_request
from jarvis.integrations.email_workflows import is_email_request

_active_ids = set()
# The task duration ceiling is not a per-action delay: individual planners and
# UI steps already have their own short deadlines. Keep the documented five-
# minute ceiling so a multi-step goal can finish instead of being cut off after
# one or two slow-but-valid Windows UI actions.
AUTONOMOUS_TASK_TIMEOUT_SECONDS = 300
AUTONOMOUS_EMAIL_TIMEOUT_SECONDS = 300
MAX_QUEUED_TASKS = 4
READ_ACTIONS = {'read_file', 'list_folder', 'read_email'}
TERMINAL_OBSERVATION_ACTIONS = READ_ACTIONS | {'open_app', 'open_url'}
TRANSIENT_READ_FAILURES = (
    'temporary network error', 'network unavailable', 'network timeout',
    'timed out', 'timeout', 'temporarily unavailable', 'connection reset',
    'connection lost', 'connection timed out', 'please try again',
    'pc planning is unavailable',
)


def _is_transient_read_failure(result):
    """Only repeat a read for an explicitly transient-looking failure."""
    text = str(result or '').casefold()
    return any(marker in text for marker in TRANSIENT_READ_FAILURES)


def goal_request(text):
    match = re.fullmatch(r"(?is)(?:autonomous task|your task is|deine aufgabe ist|erledige selbstständig|erledige selbständig|erledige autonom|solve this task|take care of|handle this task|kümmere dich um|kümmer dich um)\s*[:,-]?\s+(.+)", normalize_request(text))
    return match[1].strip() if match else None


def recent_jobs(root=DATA_ROOT):
    folder = Path(root) / "data/autonomous-tasks"
    rows = []
    for path in sorted(folder.glob('*.json'), key=lambda p:p.stat().st_mtime, reverse=True)[:20]:
        try:
            row = json.loads(path.read_text(encoding='utf-8'))
            if row['state'] in {'running','planning'} and row['id'] not in _active_ids:
                row.update(state='interrupted',message='The app stopped before this task finished. Review completed steps before restarting it.')
            rows.append(row)
        except (OSError, ValueError):
            pass
    return rows


class AutonomousTasks:
    def __init__(self, root=DATA_ROOT):
        self.root = Path(root)
        self.planner = LocalPC()
        self.pending = ""
        self.queued_goals = []
        self.job = None
        self.task = None
        self.notify = None
        self.observations = []
        self.executed = set()

    def start(self, goal, previous="", notify=None):
        if self.task and not self.task.done():
            if goal.lower().strip('.!? ') in {'stop', 'cancel', 'halt', 'abbruch', 'stop the task'}:
                self.queued_goals.clear()
                asyncio.create_task(self.cancel())
                return remember_english('Stopping the current task and clearing queued tasks.')
            if len(self.queued_goals) >= MAX_QUEUED_TASKS:
                return remember_english('The task queue is full. Wait for a task to finish or say stop.')
            self.queued_goals.append((goal, previous, notify))
            return remember_english('I added that as the next task. I will start it after the current task finishes.')
        async def work():
            next_goal, next_previous, next_notify = goal, previous, notify
            completed_normally = False
            try:
                while True:
                    self.notify = next_notify
                    await self.run(next_goal, next_previous)
                    await self.publish()
                    if not self.queued_goals:
                        completed_normally = True
                        break
                    next_goal, next_previous, next_notify = self.queued_goals.pop(0)
            finally:
                if not completed_normally and self.notify and self.job:
                    try:
                        await self.publish()
                    except Exception:
                        pass
        self.task=asyncio.create_task(work())
        return ''

    async def cancel(self):
        self.queued_goals.clear()
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task,return_exceptions=True)
        self.pending=''
        if self.job and self.job['state']=='needs_input':
            self.job.update(state='cancelled',message='Stopped. Completed actions were preserved.')
            self.save()
            await self.publish()

    def save(self):
        folder = self.root / "data/autonomous-tasks"
        folder.mkdir(parents=True, exist_ok=True)
        self.job['updated'] = time.time()
        destination = folder / (self.job['id']+'.json')
        temporary = destination.with_suffix('.tmp')
        # Keep content only in the live task; durable history records progress.
        saved = dict(self.job, goal='Task details are kept only in the active session.',
                     message='Task '+self.job['state'].replace('_',' ')+'.',
                     steps=[{k:v for k,v in step.items() if k not in {'result','target'}} for step in self.job['steps']])
        data = json.dumps(saved,ensure_ascii=False,indent=2)
        temporary.write_text(data,encoding='utf-8')
        temporary.replace(destination)

    async def publish(self):
        if self.notify and self.job:
            try:
                await self.notify({'type':'task_update','state':self.job['state'],
                    'message':self.job.get('message',''),
                    'completed':sum(s['state']=='completed' for s in self.job['steps']),
                    'total':len(self.job['steps']),
                    'duration_ms':self.job.get('duration_ms',0),
                    'planning_ms':self.job.get('planning_ms',0),
                    'action_ms':self.job.get('action_ms',0)})
            except Exception:
                pass

    async def _finish_verified_batch(self, count):
        """Finish a terminal batch from the actual per-action results."""
        rows = self.job['steps'][-count:]
        observations = self.observations[-count:]
        if (len(rows) != count or len(observations) != count
                or any(row['state'] != 'completed' for row in rows)
                or any(not item['success'] for item in observations)):
            self.job.update(state='needs_attention',
                            message='One or more requested actions did not complete. Review the task results.')
        else:
            parts = []
            for item in observations:
                action = item['step']['action']
                target = item['step'].get('target', '')
                result = item['result']
                if action == 'read_file':
                    result = Path(target).name + ': ' + result
                elif action == 'list_folder':
                    result = target + ': ' + result
                parts.append(result)
            message = ' '.join(parts)[-2000:]
            self.job.update(state='completed',message=message or 'All requested actions completed.')
        self.save()
        await self.publish()
        return remember_english(self.job['message'])

    async def _execute_independent_local_steps(self, request, previous, steps):
        """Run independent reads or one calendar action alongside an explicit open."""
        read_actions = {'read_file', 'list_folder', 'read_email'}
        calendar_actions = {'calendar_task'}
        work_actions = read_actions | calendar_actions
        open_actions = {'open_app', 'open_url'}
        actions = [step.get('action') for step in steps]
        opens = [step for step in steps if step.get('action') in open_actions]
        if (len(steps) < 2 or len(self.job['steps']) + len(steps) > 12
                or not any(action in work_actions for action in actions)
                or any(action not in work_actions | open_actions for action in actions)
                or len(opens) > 1):
            return False

        mail_reads = [step for step in steps if step.get('action') == 'read_email']
        if mail_reads:
            # A single mail read may overlap one unrelated launch. Keep an
            # Outlook read and Outlook launch ordered to avoid competing COM
            # and UI startups; likewise keep Gmail's own page ordered.
            if (len(mail_reads) != 1 or len(steps) != 2 or len(opens) != 1
                    or any(action not in {'read_email', *open_actions} for action in actions)):
                return False
            provider = mail_reads[0].get('target', '').strip().casefold()
            opening = opens[0]
            target = str(opening.get('target', '')).strip()
            same_surface = (provider in {'outlook', 'microsoft outlook'}
                            and opening['action'] == 'open_app'
                            and target.casefold() in {'outlook', 'microsoft outlook'})
            if opening['action'] == 'open_url':
                host = (urlsplit(target).hostname or '').casefold()
                same_surface = same_surface or (
                    provider in {'gmail', 'google mail'} and host in {'mail.google.com', 'gmail.com'})
                same_surface = same_surface or (
                    provider in {'outlook', 'microsoft outlook'}
                    and host in {'outlook.office.com', 'outlook.live.com', 'outlook.com'})
            if same_surface:
                return False

        # Calendar workflows may read or update their own local/API store, and
        # never need the foreground window. Keep them separate from file batches
        # and allow at most one calendar operation per concurrent phase.
        calendar_count = sum(action in calendar_actions for action in actions)
        if calendar_count and (calendar_count != 1 or any(action in read_actions for action in actions)):
            return False

        rows = []
        prepared = []
        existing = set(self.executed)
        batch_fingerprints = set()
        repeated = False
        for step in steps:
            fingerprint = json.dumps(step, sort_keys=True)
            prior = [item for item in self.observations if item['step'] == step]
            retry_read = (step['action'] in read_actions and len(prior) == 1
                          and not prior[0]['success'])
            if fingerprint in batch_fingerprints or (fingerprint in existing and not retry_read):
                repeated = True
                break
            batch_fingerprints.add(fingerprint)
            prepared.append((step, prior, retry_read))

        if repeated:
            self.job.update(state='needs_attention',
                            message='A repeated action was prevented. Review the task history.')
            self.save()
            await self.publish()
            return True

        for step, prior, retry_read in prepared:
            fingerprint = json.dumps(step, sort_keys=True)
            self.executed.add(fingerprint)
            row = {'action':step['action'], 'target':step['target'][:300], 'state':'running'}
            self.job['steps'].append(row)
            rows.append((step, row, prior, retry_read))

        file_count = sum(step['action'] in {'read_file','list_folder'} for step, _row, _prior, _retry in rows)
        mail_count = sum(step['action'] == 'read_email' for step, _row, _prior, _retry in rows)
        open_count = sum(step['action'] in open_actions for step, _row, _prior, _retry in rows)
        calendar_count = sum(step['action'] in calendar_actions for step, _row, _prior, _retry in rows)
        activities = []
        if file_count:
            activities.append(f'Reading {file_count} independent files and folders')
        if mail_count:
            activities.append('Reading email')
        if calendar_count:
            activities.append('Checking the requested calendar action')
        message = ' and '.join(activities)
        if open_count:
            message += (' while ' if message else '') + 'opening ' + next(
                step['target'] for step, _row, _prior, _retry in rows
                if step['action'] in open_actions)
        self.job.update(state='running',message=message + '.')
        self.save()
        await self.publish()

        async def execute_one(step):
            reader = LocalPC()
            started = time.perf_counter()
            try:
                result = await reader.execute(request, previous, planned_steps=[step])
                return (result, reader.last_action_ok, round((time.perf_counter()-started)*1000),
                        reader.mail_context if step['action'] == 'read_email' else None)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return ('Action did not complete (' + type(exc).__name__ + ').', False,
                        round((time.perf_counter()-started)*1000), None)

        outcomes = await asyncio.gather(*(execute_one(step) for step, _, _, _ in rows))
        retry_indices = [index for index, ((step, _row, _prior, retry_read),
                                           (result, ok, _duration, _context)) in enumerate(zip(rows, outcomes))
                         if (not ok and not retry_read and step['action'] in read_actions
                             and _is_transient_read_failure(result))]
        if retry_indices:
            retried = await asyncio.gather(*(execute_one(rows[index][0]) for index in retry_indices))
            for index, (retry_result, retry_ok, retry_ms, retry_context) in zip(retry_indices, retried):
                first_result, _first_ok, first_ms, _first_context = outcomes[index]
                outcomes[index] = (
                    retry_result if retry_ok else f'{first_result} Retry: {retry_result}',
                    retry_ok,
                    first_ms + retry_ms,
                    retry_context,
                )
        retried_indices = set(retry_indices)
        for index, ((step, row, prior, retry_read), (result, ok, duration_ms, mail_context)) in enumerate(zip(rows, outcomes)):
            row.update(state='completed' if ok else 'needs_attention', result=result[:1000],
                       attempts=2 if retry_read or index in retried_indices else 1, duration_ms=duration_ms)
            self.job['action_ms'] = self.job.get('action_ms',0) + duration_ms
            if step['action'] == 'read_email' and mail_context is not None:
                self.planner.mail_context = mail_context
            if retry_read and ok:
                prior[0]['recovered'] = True
                for old in self.job['steps'][:-len(rows)]:
                    if (old['action'] == step['action'] and
                            old['target'] == step['target'][:300] and
                            old['state'] == 'needs_attention'):
                        old['state'] = 'recovered'
            self.observations.append({'step':step,'success':ok,'result':result[:8000]})

        self.save()
        await self.publish()
        return True

    async def _execute_independent_app_opens(self, request, previous, steps):
        """Launch independent app-only batches concurrently, never with a website."""
        if (len(steps) < 2 or len(self.job['steps']) + len(steps) > 12
                or any(step.get('action') != 'open_app'
                       or not str(step.get('target', '')).strip() for step in steps)):
            return False

        rows = []
        fingerprints = set()
        targets = set()
        for step in steps:
            fingerprint = json.dumps(step, sort_keys=True)
            normalized_target = (step['action'], step['target'].strip().casefold())
            if fingerprint in fingerprints or fingerprint in self.executed or normalized_target in targets:
                self.job.update(state='needs_attention',
                                message='A repeated action was prevented. Review the task history.')
                self.save()
                await self.publish()
                return True
            fingerprints.add(fingerprint)
            targets.add(normalized_target)

        for step in steps:
            self.executed.add(json.dumps(step, sort_keys=True))
            row = {'action': step['action'], 'target': step['target'][:300], 'state': 'running'}
            self.job['steps'].append(row)
            rows.append((step, row))

        self.job.update(state='running', message=f'Opening {len(rows)} independent apps.')
        self.save()
        await self.publish()

        async def open_one(step):
            executor = LocalPC()
            started = time.perf_counter()
            try:
                result = await executor.execute(request, previous, planned_steps=[step])
                return result, executor.last_action_ok, round((time.perf_counter() - started) * 1000)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return 'Launch did not complete (' + type(exc).__name__ + ').', False, round((time.perf_counter() - started) * 1000)

        outcomes = await asyncio.gather(*(open_one(step) for step, _ in rows))
        for (step, row), (result, ok, duration_ms) in zip(rows, outcomes):
            row.update(state='completed' if ok else 'needs_attention', result=result[:1000],
                       attempts=1, duration_ms=duration_ms)
            self.job['action_ms'] = self.job.get('action_ms', 0) + duration_ms
            self.observations.append({'step': step, 'success': ok, 'result': result[:8000]})

        self.save()
        await self.publish()
        return True

    async def run(self, goal, previous=""):
        run_started = time.perf_counter()
        resuming = bool(self.pending and self.job and self.job['state']=='needs_input')
        request = (self.pending + '\nUser clarification: ' + goal) if resuming else goal
        self.pending = ""
        if not resuming:
            self.observations = []
            self.executed = set()
            self.job = {'id':uuid.uuid4().hex,'goal':request[:2000], 'state':'planning', 'steps':[], 'started':time.time(), 'rounds':0,
                        'duration_ms':0,'planning_ms':0,'action_ms':0}
        else:
            self.job.update(goal=request[:2000],state='planning')
            self.job.setdefault('duration_ms',0)
            self.job.setdefault('planning_ms',0)
            self.job.setdefault('action_ms',0)
        _active_ids.add(self.job['id'])
        self.save()
        email_task = is_email_request(normalize_request(request))
        timeout_seconds = (AUTONOMOUS_EMAIL_TIMEOUT_SECONDS if email_task
                           else AUTONOMOUS_TASK_TIMEOUT_SECONDS)
        active_action = None

        def finish_action_timing():
            nonlocal active_action
            if active_action is None:
                return
            row, started = active_action
            duration_ms = round((time.perf_counter()-started)*1000)
            row['duration_ms'] = duration_ms
            self.job['action_ms'] = self.job.get('action_ms',0) + duration_ms
            active_action = None

        try:
            async with asyncio.timeout(timeout_seconds):
                while self.job['rounds'] < 8 and len(self.job['steps']) < 12:
                    self.job.update(state='planning',message='Evaluating the next steps.')
                    self.job['rounds'] += 1
                    self.save()
                    await self.publish()
                    planning_started = time.perf_counter()
                    try:
                        phase = await self.planner.plan_next(request, previous, self.observations)
                    finally:
                        self.job['planning_ms'] = self.job.get('planning_ms',0) + round((time.perf_counter()-planning_started)*1000)
                    if phase['complete']:
                        # A model may not erase unresolved failures by declaring success.
                        if any(row['state']=='needs_attention' for row in self.job['steps']):
                            self.job.update(state='needs_attention',message='Some actions failed. Review the task history.')
                        else:
                            self.job.update(state='completed',message=phase['message'] or 'All requested supported actions completed.')
                        return remember_english(self.job['message'])
                    terminal_observation_phase = (
                        bool(phase.get('terminal')) and bool(phase['steps'])
                        and all(step['action'] in TERMINAL_OBSERVATION_ACTIONS
                                for step in phase['steps']))
                    if await self._execute_independent_app_opens(request, previous, phase['steps']):
                        if self.job['state'] == 'needs_attention':
                            return remember_english(self.job['message'])
                        if phase.get('terminal'):
                            return await self._finish_verified_batch(len(phase['steps']))
                        continue
                    terminal_parallel_read_batch = (
                        terminal_observation_phase
                        and len(phase['steps']) > 1
                        and any(step['action'] in READ_ACTIONS for step in phase['steps']))
                    if await self._execute_independent_local_steps(request, previous, phase['steps']):
                        if self.job['state'] == 'needs_attention':
                            return remember_english(self.job['message'])
                        if terminal_parallel_read_batch:
                            return await self._finish_verified_batch(len(phase['steps']))
                        if phase.get('terminal'):
                            latest = self.observations[-len(phase['steps']):]
                            if len(latest) == len(phase['steps']) and all(item['success'] for item in latest):
                                return await self._finish_verified_batch(len(phase['steps']))
                            # A failed read may be retried once; the next plan
                            # receives these verified results and cannot replay
                            # the successful sibling reads.
                        continue
                    for step_index, step in enumerate(phase['steps']):
                        if step['action']=='ask':
                            self.pending = request
                            self.job.update(state='needs_input',message=step['content'])
                            return remember_english(step['content'])
                        if len(self.job['steps']) >= 12:
                            break
                        fingerprint = json.dumps(step,sort_keys=True)
                        prior = [o for o in self.observations if o['step'] == step]
                        retry_read = step['action'] in {'read_file','list_folder','read_email'} and len(prior)==1 and not prior[0]['success']
                        if fingerprint in self.executed and not retry_read:
                            self.job.update(state='needs_attention',message='A repeated action was prevented. Review the task history.')
                            return remember_english(self.job['message'])
                        self.executed.add(fingerprint)
                        row={'action':step['action'],'target':step['target'][:300],'state':'running'}
                        self.job['steps'].append(row)
                        self.job.update(state='running',message=f"Step {len(self.job['steps'])}: {step['action'].replace('_',' ')}")
                        self.save()
                        await self.publish()
                        active_action = (row,time.perf_counter())
                        if step['action']=='codex_prompt':
                            self.job['message']='Codex is working. I will evaluate its report before continuing.'
                            await self.publish()
                            try:
                                result = await pc.run_code(step['content'],step['target'] or None)
                                ok = True
                            except (RuntimeError,OSError,ValueError) as exc:
                                result = 'Coding task did not complete: ' + str(exc)[:400]
                                ok = False
                        else:
                            result = await self.planner.execute(request, previous, planned_steps=[step])
                            ok = self.planner.last_action_ok
                            if self.planner.needs_input:
                                # Validation asks before opening or editing a composer.
                                self.executed.discard(fingerprint)
                                row.update(state='awaiting_input', result=result[:1000], attempts=0)
                                self.pending = request
                                self.planner.pending = ''
                                self.job.update(state='needs_input', message=result)
                                finish_action_timing()
                                return result
                        finish_action_timing()
                        automatic_read_retry = False
                        if (not ok and terminal_observation_phase and not retry_read
                                and step['action'] in READ_ACTIONS
                                and _is_transient_read_failure(result)):
                            first_result = result
                            first_duration_ms = row.get('duration_ms', 0)
                            automatic_read_retry = True
                            row.update(state='retrying', attempts=2,
                                       result='A transient read error occurred; retrying once.')
                            self.save()
                            await self.publish()
                            active_action = (row, time.perf_counter())
                            result = await self.planner.execute(request, previous, planned_steps=[step])
                            ok = self.planner.last_action_ok
                            finish_action_timing()
                            row['duration_ms'] = first_duration_ms + row.get('duration_ms', 0)
                            if not ok:
                                result = f'{first_result} Retry: {result}'
                        row.update(state='completed' if ok else 'needs_attention',result=result[:1000],attempts=2 if retry_read else 1)
                        if automatic_read_retry:
                            row['attempts'] = 2
                        if retry_read and ok:
                            prior[0]['recovered'] = True
                            for old in self.job['steps'][:-1]:
                                if old['action']==step['action'] and old['target']==step['target'][:300] and old['state']=='needs_attention':
                                    old['state']='recovered'
                        self.observations.append({'step':step,'success':ok,'result':result[:8000]})
                        self.save()
                        await self.publish()
                        if not ok:
                            # A failed action does not invalidate explicitly
                            # planned app/website launches. Finish those safe,
                            # independent opens before another planning round;
                            # keep writes and UI interactions behind the result.
                            remaining = phase['steps'][step_index + 1:]
                            if (remaining and all(next_step['action'] in {'open_app', 'open_url'}
                                                  for next_step in remaining)):
                                continue
                            if step['action'] not in {'read_file','list_folder','read_email','open_app','open_url'}:
                                self.job.update(state='needs_attention',message=result[:1000])
                                return result
                            if terminal_observation_phase:
                                return await self._finish_verified_batch(len(phase['steps']))
                            # The next planning round sees the real error; no blind retry.
                            break
                        if step['action'] == 'read_email':
                            # A planner-approved app/site open after the read is
                            # already determined by the original request. Run it
                            # before the next LLM round, while keeping any action
                            # that depends on the messages behind the read result.
                            remaining = phase['steps'][step_index + 1:]
                            if remaining and all(item['action'] in {'open_app','open_url'}
                                                 for item in remaining):
                                continue
                            if phase.get('terminal'):
                                return await self._finish_verified_batch(len(phase['steps']))
                            break
                        if step['action'] == 'codex_prompt':
                            # The report must be observed and evaluated before
                            # planning dependent coding follow-up actions.
                            break
                    else:
                        if phase.get('terminal'):
                            if any(row['state'] == 'needs_attention' for row in self.job['steps']):
                                self.job.update(state='needs_attention',
                                                message='Some actions failed. Review the task history.')
                            else:
                                self.job.update(state='completed',message=' '.join(o['result'] for o in self.observations)[-2000:])
                            return remember_english(self.job['message'])
                self.job.update(state='needs_attention',message='Task reached its limit of 12 actions or 8 planning rounds. Completed actions were preserved.')
                return remember_english(self.job['message'])
        except asyncio.CancelledError:
            finish_action_timing()
            self.pending=''
            self.job.update(state='cancelled',message='Stopped. Completed actions were not undone.')
            for row in self.job['steps']:
                if row['state']=='running': row['state']='interrupted'
            raise
        except TimeoutError:
            finish_action_timing()
            for row in self.job['steps']:
                if row['state'] == 'running':
                    row['state'] = 'interrupted'
            self.job.update(state='needs_attention',message=f'Task exceeded its {timeout_seconds}-second time limit.')
            if email_task:
                return remember_english('The email task took too long. Check the draft or Sent folder and task history before retrying; I will not repeat a send automatically.')
            return remember_english('The task reached its time limit. Check task status for completed steps before retrying.')
        except Exception:
            finish_action_timing()
            for row in self.job['steps']:
                if row['state'] == 'running':
                    row['state'] = 'interrupted'
            self.job.update(state='needs_attention',message='Planning or execution failed; completed steps will not be repeated automatically.')
            return remember_english('I could not complete that task. Check the OpenAI connection and the task history in Settings.')
        finally:
            self.job['duration_ms'] = self.job.get('duration_ms',0) + round((time.perf_counter()-run_started)*1000)
            self.save()
            _active_ids.discard(self.job['id'])

    def progress(self):
        rows = [s for s in self.job['steps'] if s['state']!='recovered'] if self.job else []
        return sum(s['state']=='completed' for s in rows), len(rows)

    def status(self):
        if not self.job:
            return remember_english('No autonomous task has been started in this session.')
        completed, total = self.progress()
        result = f"Task status: {self.job['state'].replace('_',' ')}. {completed} of {total} steps completed."
        if self.job.get('message'):
            result += ' ' + self.job.get('message','')
        return remember_english(result)
