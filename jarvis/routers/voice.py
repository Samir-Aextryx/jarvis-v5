from jarvis.voice.voice_turn import SerializedSocket
from jarvis.core.diagnostics import report_failure
from jarvis.voice.call_privacy import phone_call_privacy
from jarvis.voice.transcription_config import file_transcription_options
"""Dedicated API routes; runtime owns shared services during incremental extraction."""
from fastapi import APIRouter, WebSocket, Request
from typing import Optional
from jarvis.routers.models import *
from jarvis import server as runtime
router = APIRouter()

@router.websocket('/ws/stt')
async def live_transcription(ws: WebSocket):
    await runtime.serve_stt(ws, runtime.JARVIS_AUTH_TOKEN, runtime.OPENAI_API_KEY)

@router.get('/api/voice/metrics')
async def voice_latency_metrics():
    return {'measurements': list(runtime.voice_metrics.recent)}

@router.post('/api/transcribe')
async def transcribe(request: Request):
    if phone_call_privacy.active:
        return runtime.JSONResponse({'error': 'Desktop microphone is disabled during a phone call.'}, status_code=423)
    if not runtime.OPENAI_API_KEY:
        return runtime.JSONResponse({'error': 'OpenAI API-Schlüssel fehlt.'}, status_code=503)
    content_type = request.headers.get('content-type', '').split(';')[0]
    formats = {'audio/webm': 'webm', 'audio/mpeg': 'mp3', 'audio/wav': 'wav'}
    if content_type not in formats:
        return runtime.JSONResponse({'error': 'Audioformat nicht unterstützt.'}, status_code=415)
    audio = bytearray()
    async for chunk in request.stream():
        if phone_call_privacy.active:
            return runtime.JSONResponse({'error': 'Desktop microphone is disabled during a phone call.'}, status_code=423)
        audio.extend(chunk)
        if len(audio) > 20 * 1024 * 1024:
            return runtime.JSONResponse({'error': 'Aufnahme zu groß.'}, status_code=413)
    if not audio:
        return runtime.JSONResponse({'error': 'Aufnahme ist leer.'}, status_code=400)
    if phone_call_privacy.active:
        return runtime.JSONResponse({'error': 'Desktop microphone is disabled during a phone call.'}, status_code=423)
    async with runtime.http_client(timeout=60) as client:
        response = await client.post('https://api.openai.com/v1/audio/transcriptions', headers={'Authorization': f'Bearer {runtime.OPENAI_API_KEY}'}, data=file_transcription_options(), files={'file': ('speech.' + formats[content_type], bytes(audio), content_type)})
    if response.status_code == 401:
        return runtime.JSONResponse({'error': 'OpenAI hat den API-Schlüssel abgelehnt. Bitte in Settings unter Voice & AI keys einen neuen Schlüssel speichern.'}, status_code=502)
    if response.is_error:
        return runtime.JSONResponse({'error': f'OpenAI-Spracherkennung: HTTP {response.status_code}'}, status_code=502)
    return {'text': runtime.clean_transcript(response.json().get('text', ''))}

@router.get('/api/tts-test')
async def tts_test():
    """Generate a test audio clip for debugging."""
    audio = await runtime.synthesize_speech('Testing audio, sir.')
    if audio:
        return {'audio': runtime.base64.b64encode(audio).decode()}
    return {'audio': None, 'error': 'TTS failed'}

@router.websocket('/ws/voice')
async def voice_handler(ws: WebSocket):
    """
    WebSocket protocol:

    Client -> Server:
        {"type": "transcript", "text": "...", "isFinal": true}

    Server -> Client:
        {"type": "audio", "data": "<base64 mp3>", "text": "spoken text"}
        {"type": "status", "state": "thinking"|"speaking"|"idle"|"working"}
        {"type": "task_spawned", "task_id": "...", "prompt": "..."}
        {"type": "task_complete", "task_id": "...", "summary": "..."}
    """
    if not await runtime.authenticate_websocket(ws, runtime.JARVIS_AUTH_TOKEN):
        return
    ws = SerializedSocket(ws)
    runtime.task_manager.register_websocket(ws)
    if phone_call_privacy.active:
        await ws.send_json({'type': 'phone_call_privacy', 'active': True,
                            'session': phone_call_privacy.session})
    history: list[dict] = []
    work_session = runtime.WorkSession()
    planner = runtime.TaskPlanner()
    _current_response_id = 0
    _cancel_response = False
    voice_state = {'last_user_time': 0.0}
    last_jarvis_response = ''
    session_summary: str = ''
    summary_update_pending: bool = False
    messages_since_last_summary: int = 0
    summarized_history_count: int = 0
    runtime.log.info('Voice WebSocket connected')
    pending_app_choices = []
    pending_app_key = None
    local_pc = runtime.LocalPC()
    autonomous = runtime.AutonomousTasks()
    raw_ws = ws
    turn_epoch = 0
    active_turn = None
    greeting_task = None
    seen_turn_ids = set()
    try:
        now = runtime.datetime.now()
        hour = now.hour
        if hour < 12:
            greeting = 'Good morning, sir.'
        elif hour < 17:
            greeting = 'Good afternoon, sir.'
        else:
            greeting = 'Good evening, sir.'
        should_greet = (runtime.time.time() - runtime._last_greeting_time > 60
                        and not phone_call_privacy.active)
        if should_greet:
            runtime._last_greeting_time = runtime.time.time()

            async def _send_greeting():
                try:
                    spoken = greeting
                    if await runtime.openai_key_rejected():
                        # Listening (and answering, with OpenAI selected) needs this key; say so instead of staying silent.
                        spoken = (runtime.OPENAI_KEY_REJECTED_NOTICE if runtime.provider_config().id == 'openai'
                                  else runtime.OPENAI_STT_KEY_REJECTED_NOTICE)
                    audio_bytes = await runtime.synthesize_speech(spoken)
                    if audio_bytes:
                        encoded = runtime.base64.b64encode(audio_bytes).decode()
                        await ws.send_json({'type': 'status', 'state': 'speaking'})
                        await ws.send_json({'type': 'audio', 'data': encoded, 'text': spoken})
                        history.append({'role': 'assistant', 'content': spoken})
                        runtime.log.info(f'JARVIS: {spoken}')
                        await ws.send_json({'type': 'status', 'state': 'idle'})
                    elif spoken is not greeting:
                        await ws.send_json({'type': 'text', 'text': spoken})
                except Exception as e:
                    report_failure('voice:107')
                    runtime.log.warning(f'Greeting failed: {e}')
            greeting_task = runtime.asyncio.create_task(_send_greeting())
        try:
            await ws.send_json({'type': 'status', 'state': 'idle'})
        except Exception:
            report_failure('voice:112')
            return

        async def process_message(msg, epoch):
            nonlocal pending_app_choices, pending_app_key, _current_response_id, _cancel_response
            nonlocal last_jarvis_response, session_summary, summary_update_pending, messages_since_last_summary
            nonlocal summarized_history_count
            ws = runtime.TurnSocket(raw_ws, lambda: turn_epoch == epoch, msg.get('turn_id'))
            metrics = runtime.VoiceMetrics(ws)
            speech_stream = None
            llm_original = None
            await ws.send_json({'type': 'turn_start'})
            if msg.get('type') == 'fix_self':
                jarvis_dir = str(runtime.RESOURCE_ROOT)
                await work_session.start(jarvis_dir)
                response_text = 'Work mode active in my own repo, sir. Tell me what needs fixing.'
                tts = runtime.strip_markdown_for_tts(response_text)
                await ws.send_json({'type': 'status', 'state': 'speaking'})
                audio = await runtime.synthesize_speech(tts)
                if audio:
                    await ws.send_json({'type': 'audio', 'data': runtime.base64.b64encode(audio).decode(), 'text': response_text})
                else:
                    await ws.send_json({'type': 'text', 'text': response_text})
                return
            if msg.get('type') != 'transcript' or not msg.get('isFinal'):
                return
            user_text = runtime.apply_speech_corrections(runtime.clean_transcript(msg.get('text', '')))
            if phone_call_privacy.active:
                return
            if not user_text:
                return
            from jarvis.integrations.whatsapp_call import parse_call_request, prepare_call_to_boss
            if not runtime.agent_settings.get()['automation'] and (not runtime.personal_panel_request(user_text)):
                await ws.send_json({'type': 'text', 'text': 'Command execution is paused in AI Settings. Stop and the personal views remain available.'})
                await ws.send_json({'type': 'status', 'state': 'idle'})
                return
            await metrics.mark('stt_final')
            app_preference = runtime.parse_app_preference(user_text)
            explicit_memory = runtime.personal_memory.explicit_content(user_text)
            personal_panel = runtime.personal_panel_request(user_text)
            autonomous_goal = runtime.goal_request(user_text)
            autonomous_status = user_text.lower().strip('.!? ') in {'task status', 'autonomous status', 'aufgabenstatus'}
            local_command = bool(local_pc.pending or runtime.is_pc_request(user_text) or autonomous_goal or autonomous.pending or autonomous_status)
            memory_open = bool(runtime._action_re.search('(?i)(?:öffne|zeige|open|show).*(?:gedächtnis|gedaechtnis|memory\\.md|deine erinnerungen)', user_text))
            google_command = runtime.google_access.parse(user_text)
            website_target = runtime.parse_website_request(user_text)
            pc_command = runtime.pc_control.parse(user_text)
            direct_mail = runtime.direct_mail_plan(user_text, runtime.agent_settings.get()['default_email']) if not (autonomous.pending or local_pc.pending) else None
            direct_message = runtime.direct_message_plan(user_text) if not (autonomous.pending or local_pc.pending) else None
            direct_pc_steps = (runtime.fast_plan(user_text)
                if runtime.is_pc_request(user_text) and not runtime.is_email_request(user_text)
                and not (autonomous_goal or autonomous.pending or local_pc.pending) else None)
            screenshot_command = bool(runtime.re.fullmatch(
                '(?i)(?:screenshot|bildschirmfoto|(?:take|make)\\s+a\\s+screenshot|'
                '(?:mache?|nimm|erstelle)\\s+(?:bitte\\s+)?(?:einen\\s+screenshot|ein\\s+bildschirmfoto)(?:\\s+auf)?|'
                '(?:screenshot|bildschirmfoto)\\s+(?:machen|aufnehmen|erstellen))', runtime.normalize_request(user_text).strip('.!? ')))
            call_boss = parse_call_request(user_text)
            routine_match = runtime.re.fullmatch('(?is)(?:train|learn|trainiere|lerne|merke(?:\\s+dir)?)\\s+(?:a\\s+)?(?:routine|task|aufgabe)(?:\\s+(?:called|named|namens))?\\s+(.+?)\\s*[:,]\\s*(.+)', runtime.normalize_request(user_text))
            routine_execute = runtime.re.fullmatch('(?is)(?:run|execute|starte|führe(?:\\s+aus)?|mach(?:e)?|do)\\s+(?:the\\s+)?(?:routine|task|aufgabe|my)?\\s*(.+)', runtime.normalize_request(user_text))
            # "Mach Outlook auf" is an app launch and "Mach einen Screenshot" a capture, never a routine name.
            if routine_execute and (screenshot_command or runtime.parse_open_request(user_text)):
                routine_execute = None
            quit_command = runtime.re.fullmatch('(?i)(?:close|quit|exit|beende)\\s+(?:yourself|jarvis|dich)', user_text.strip('.!? '))
            quick_app_target = runtime.parse_open_request(user_text) if (not memory_open) and (not pc_command) and (not google_command) and (not website_target) and (not local_command) and (not routine_execute) and (not routine_match) else None
            quick_app_choice = bool(pending_app_choices and runtime.resolve_app(user_text, pending_app_choices))
            if pending_app_choices and (not quick_app_choice) and (not quick_app_target):
                pending_app_choices = []
                pending_app_key = None
            _current_response_id += 1
            my_response_id = _current_response_id
            _cancel_response = True
            _cancel_response = False
            voice_state['last_user_time'] = runtime.time.time()
            runtime.log.info('Command received (%d characters)', len(user_text))
            await ws.send_json({'type': 'status', 'state': 'thinking'})
            try:
                t_lower = user_text.lower()
                opened_app_name = None
                app_target = quick_app_target
                selected_app_choices = None
                if pending_app_choices and runtime.resolve_app(app_target or user_text, pending_app_choices):
                    app_target = app_target or user_text
                    selected_app_choices = pending_app_choices
                routed = {'intent': None}
                # Deterministic local actions do not need an agent-classification API.
                # Jev is still required for requests that need agent routing.
                direct_action = bool(app_target or local_command or website_target or google_command or pc_command or screenshot_command or call_boss)
                measure_action = bool(app_target or website_target or google_command or pc_command or screenshot_command or call_boss
                                      or direct_mail or direct_message or (local_pc.pending and local_command))
                if measure_action:
                    await metrics.mark('automation_start')
                if not (quit_command or routine_match or routine_execute or app_preference or (explicit_memory is not None) or personal_panel or pending_app_choices or planner.is_planning or autonomous.pending or local_pc.pending or direct_action):
                    routed = await runtime.agent_router.route(user_text)
                    if routed.get('notice'):
                        await ws.send_json({'type': 'text', 'text': routed['notice']})
                if not runtime.agent_settings.get()['automation'] and (local_command or app_target or website_target or pc_command or google_command or call_boss or routine_execute or (routed.get('intent') in {'open_apps', 'work_apps', 'personal_update', 'workflow'})):
                    response_text = 'Automatic tool execution is disabled in AI Settings.'
                elif call_boss:
                    response_text = await prepare_call_to_boss()
                elif routed.get('intent') in {'error', 'work_apps', 'personal_update', 'open_apps'}:
                    response_text = await runtime.agent_router.execute(routed)
                elif routed.get('intent') == 'workflow' and (not (local_command or app_target or website_target or pc_command or google_command)):
                    response_text = autonomous.start(user_text, last_jarvis_response, raw_ws.send_json)
                elif quit_command:
                    response_text = 'Shutting down, sir.'
                    await ws.send_json({'type': 'status', 'state': 'speaking'})
                    audio = await runtime.synthesize_speech(response_text)
                    if audio:
                        await ws.send_json({'type': 'audio', 'data': runtime.base64.b64encode(audio).decode(), 'text': response_text})
                    runtime.sys.exit(0)
                elif routine_match:
                    saved = await runtime.asyncio.to_thread(runtime.personal_memory.save_routine, routine_match[1], routine_match[2].strip())
                    response_text = 'I have saved the routine: ' + routine_match[1].strip() + '.'
                elif routine_execute:
                    routine_name = routine_execute[1].strip().lower()
                    facts = await runtime.asyncio.to_thread(runtime.personal_memory.facts)
                    found = next((f for f in facts if f['kind'] == 'routine' and f['key'].replace('routine_', '').replace('_', ' ') == routine_name.replace('_', ' ')), None)
                    if not found:
                        found = next((f for f in facts if f['kind'] == 'routine' and routine_name in f['key'].replace('_', ' ')), None)
                    if found:
                        user_text = found['content']
                        quick_app_target = runtime.parse_open_request(user_text)
                        app_target = quick_app_target
                        if app_target:
                            result = await runtime.open_app(app_target, selected_app_choices, memory=runtime.personal_memory)
                            response_text = result['confirmation']
                        else:
                            response_text = autonomous.start(user_text, last_jarvis_response, raw_ws.send_json)
                    else:
                        response_text = 'I could not find a routine named ' + routine_name + '.'
                elif app_preference:
                    response_text = runtime.remember_english(await runtime.save_app_preference(*app_preference, memory=runtime.personal_memory))
                elif explicit_memory is not None:
                    saved = await runtime.asyncio.to_thread(runtime.personal_memory.remember_explicit, explicit_memory)
                    response_text = runtime.remember_english('Saved in my long-term memory.' if saved else 'I did not save this. Please leave out passwords, keys and tokens and keep the note under 4000 characters.')
                elif personal_panel:
                    await ws.send_json({'type': 'open_personal', 'view': personal_panel})
                    response_text = ''
                elif screenshot_command:
                    screenshot = await runtime.take_screenshot()
                    if screenshot:
                        from jarvis.automation.pc_control import desktop
                        shot_path = desktop() / ('Jarvis-Screenshot-' + runtime.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.png')
                        await runtime.asyncio.to_thread(shot_path.write_bytes, runtime.base64.b64decode(screenshot))
                        response_text = runtime.remember_english('Screenshot saved to your Desktop.')
                    else:
                        response_text = runtime.remember_english('I could not capture the screenshot.')
                elif local_command:
                    if autonomous_status:
                        response_text = autonomous.status()
                    elif autonomous_goal or autonomous.pending or (runtime.is_pc_request(user_text) and (not local_pc.pending) and not (direct_mail or direct_message or direct_pc_steps)):
                        if autonomous_goal:
                            autonomous.pending = ''
                        response_text = autonomous.start(autonomous_goal or user_text, last_jarvis_response, raw_ws.send_json)
                    else:
                        if direct_pc_steps is not None:
                            response_text = await local_pc.execute(user_text, last_jarvis_response, planned_steps=direct_pc_steps)
                        else:
                            response_text = await local_pc.execute(user_text, last_jarvis_response)
                        if getattr(local_pc, 'last_action_silent', False):
                            response_text = ''
                elif website_target:
                    if website_target in {'jarvis:switzerland', 'jarvis:usa', 'jarvis:gods-eye'}:
                        from jarvis.automation.gods_eye import ensure_running, SWITZERLAND_URL, USA_URL, BASE
                        try:
                            await ensure_running()
                            map_url = {'jarvis:switzerland': SWITZERLAND_URL, 'jarvis:usa': USA_URL, 'jarvis:gods-eye': BASE + '/?performance=efficient'}[website_target]
                            await ws.send_json({'type': 'open_map', 'url': map_url})
                            response_text = runtime.remember_english('Opening the map inside Jarvis.')
                        except Exception:
                            report_failure('voice:252')
                            response_text = runtime.remember_english('The map server could not start. Please check God’s Eye View.')
                    elif website_target == 'jarvis:dashboard':
                        dashboard_port = int(runtime.os.getenv('JARVIS_PORT', '8340'))
                        # Chrome's command line is readable by other processes;
                        # hand it a single-use code, never the long-lived token.
                        dashboard_url = f'http://127.0.0.1:{dashboard_port}/launch/' + runtime.create_dashboard_code()
                        response_text = await runtime.open_website(dashboard_url)
                        if response_text.startswith('Opening '):
                            response_text = runtime.remember_english('Opening your Jarvis dashboard in Chrome.')
                    else:
                        response_text = await runtime.open_website(website_target)
                elif google_command:
                    response_text = await runtime.google_access.execute(google_command)
                elif pc_command:
                    response_text = await runtime.pc_control.execute(pc_command)
                elif memory_open:
                    await runtime.api_open_memory()
                    response_text = 'Ich öffne meine MEMORY.md mit deinen gespeicherten Infos.'
                elif app_target:
                    result = await runtime.open_app(app_target, selected_app_choices, memory=runtime.personal_memory, remember_as=pending_app_key if selected_app_choices else None)
                    pending_app_key = result.get('preference_key')
                    opened_app_name = result.get('app') if result.get('success') else None
                    pending_app_choices = result.get('candidates', [])
                    response_text = result['confirmation']
                elif planner.is_planning:
                    if any((p in t_lower for p in BYPASS_PHRASES)):
                        plan = planner.active_plan
                        if plan:
                            plan.skipped = True
                            for q in plan.pending_questions[plan.current_question_index:]:
                                if q.get('default') is not None and q['key'] not in plan.answers:
                                    plan.answers[q['key']] = q['default']
                        prompt = await planner.build_prompt()
                        name = runtime._generate_project_name(prompt)
                        path = str(runtime.Path.home() / 'Desktop' / name)
                        runtime.os.makedirs(path, exist_ok=True)
                        runtime.Path(path, 'CLAUDE.md').write_text(prompt)
                        did = runtime.dispatch_registry.register(name, path, prompt[:200])
                        runtime.asyncio.create_task(runtime._execute_prompt_project(name, prompt, work_session, ws, dispatch_id=did, history=history, voice_state=voice_state))
                        planner.reset()
                        response_text = ''
                    elif planner.active_plan and planner.active_plan.confirmed is False and (planner.active_plan.current_question_index >= len(planner.active_plan.pending_questions)):
                        result = await planner.handle_confirmation(user_text)
                        if result['confirmed']:
                            prompt = await planner.build_prompt()
                            name = runtime._generate_project_name(prompt)
                            path = str(runtime.Path.home() / 'Desktop' / name)
                            runtime.os.makedirs(path, exist_ok=True)
                            runtime.Path(path, 'CLAUDE.md').write_text(prompt)
                            did = runtime.dispatch_registry.register(name, path, prompt[:200])
                            runtime.asyncio.create_task(runtime._execute_prompt_project(name, prompt, work_session, ws, dispatch_id=did, history=history, voice_state=voice_state))
                            planner.reset()
                            response_text = ''
                        elif result['cancelled']:
                            planner.reset()
                            response_text = 'Cancelled, sir.'
                        else:
                            response_text = result.get('modification_question', 'How shall I adjust the plan, sir?')
                    else:
                        result = await planner.process_answer(user_text, runtime.cached_projects)
                        if result['plan_complete']:
                            response_text = result.get('confirmation_summary', 'Ready to build. Shall I proceed, sir?')
                        else:
                            response_text = result.get('next_question', 'What else, sir?')
                elif any((w in t_lower for w in ['quit work mode', 'exit work mode', 'go back to chat', 'regular mode', 'stop working'])):
                    if work_session.active:
                        await work_session.stop()
                        response_text = 'Back to conversation mode, sir.'
                    else:
                        response_text = 'Already in conversation mode, sir.'
                elif work_session.active:
                    if runtime.is_casual_question(user_text):
                        response_text = await runtime.generate_response(user_text, runtime.llm_client, runtime.task_manager, runtime.cached_projects, history, last_response=last_jarvis_response, session_summary=session_summary)
                    else:
                        await ws.send_json({'type': 'status', 'state': 'working'})
                        runtime.log.info(f'Work mode → Codex project task: {user_text[:80]}')
                        full_response = await work_session.send(user_text)
                        if full_response and runtime.llm_client:
                            stall_words = ['which option', 'would you prefer', 'would you like me to', 'before I proceed', 'before proceeding', 'should I', 'do you want me to', 'let me know', 'please confirm', 'which approach', 'what would you']
                            is_stalling = any((w in full_response.lower() for w in stall_words))
                            if is_stalling and work_session._message_count >= 2:
                                runtime.log.info('Codex stalling — pushing to build')
                                push_response = await work_session.send('Stop asking questions. Use your best judgment and start building now. Write the actual code files. Go with the simplest reasonable approach.')
                                if push_response:
                                    full_response = push_response
                        import re as _re
                        localhost_match = _re.search('https?://localhost:\\d+', full_response or '')
                        if localhost_match:
                            runtime.asyncio.create_task(runtime._execute_browse(localhost_match.group(0)))
                            runtime.log.info(f'Auto-opening {localhost_match.group(0)}')
                        if full_response and runtime.llm_client:
                            try:
                                summary = await runtime.llm_client.messages.create(max_tokens=100, system=f"You are JARVIS reporting to the user ({runtime.USER_NAME}). Summarize what happened in 1-2 sentences. Speak in first person — 'I built', 'I found', 'I set up'. You are talking TO THE USER, not to a coding tool. NEVER give instructions like 'go ahead and build' or 'set up the frontend' — those are NOT for the user. NEVER say 'Codex'. NEVER output [ACTION:...] tags. NEVER read out URLs. No markdown. British precision.", messages=[{'role': 'user', 'content': f'Codex reported:\n{full_response[:2000]}'}])
                                response_text = summary.content[0].text
                            except Exception:
                                report_failure('voice:346')
                                response_text = full_response[:200]
                        else:
                            response_text = full_response
                else:
                    action = runtime.detect_action_fast(user_text)
                    if action:
                        if action['action'] == 'open_terminal':
                            response_text = await runtime.handle_open_terminal()
                        elif action['action'] == 'show_recent':
                            response_text = await runtime.handle_show_recent()
                        elif action['action'] == 'describe_screen':
                            response_text = ''
                            runtime.asyncio.create_task(runtime._lookup_and_report('screen', runtime._do_screen_lookup, ws, history=history, voice_state=voice_state))
                        elif action['action'] == 'check_calendar':
                            response_text = ''
                            runtime.asyncio.create_task(runtime._lookup_and_report('calendar', runtime._do_calendar_lookup, ws, history=history, voice_state=voice_state))
                        elif action['action'] == 'check_mail':
                            response_text = ''
                            runtime.asyncio.create_task(runtime._lookup_and_report('mail', runtime._do_mail_lookup, ws, history=history, voice_state=voice_state))
                        elif action['action'] == 'check_dispatch':
                            recent = runtime.dispatch_registry.get_most_recent()
                            if not recent:
                                response_text = 'No recent builds on record, sir.'
                            else:
                                name = recent['project_name']
                                status = recent['status']
                                if status == 'building' or status == 'pending':
                                    elapsed = int(runtime.time.time() - recent['updated_at'])
                                    response_text = f'Still working on {name}, sir. Been at it for {elapsed} seconds.'
                                elif status == 'completed':
                                    response_text = recent.get('summary') or f'{name} is complete, sir.'
                                elif status in ('failed', 'timeout'):
                                    response_text = f'{name} ran into problems, sir.'
                                else:
                                    response_text = f'{name} is {status}, sir.'
                        elif action['action'] == 'check_tasks':
                            tasks = runtime.get_open_tasks()
                            response_text = runtime.format_tasks_for_voice(tasks)
                        elif action['action'] == 'check_notes':
                            response_text = ''
                            runtime.asyncio.create_task(runtime._lookup_and_report('notes', runtime._do_notes_lookup, ws, history=history, voice_state=voice_state))
                        elif action['action'] == 'check_tickets':
                            response_text = ''
                            runtime.asyncio.create_task(runtime._lookup_and_report('tickets', runtime._do_tickets_lookup, ws, history=history, voice_state=voice_state))
                        elif action['action'] == 'check_usage':
                            response_text = runtime.get_usage_summary()
                        else:
                            response_text = ''
                    elif not runtime.llm_client:
                        response_text = 'API key not configured.'
                    else:
                        if msg.get('streamAudio') and runtime.FISH_API_KEY:

                            def streamed_usage():
                                runtime._session_tokens['tts_calls'] += 1
                                runtime._append_usage_entry(0, 0, 'tts')
                            speech_stream = runtime.StreamingSpeech(ws, api_key=runtime.FISH_API_KEY, voice_id=runtime.FISH_VOICE_ID, model=runtime.os.getenv('FISH_MODEL', 's2.1-pro-free'), latency=runtime.os.getenv('FISH_LATENCY', 'balanced'), metrics=metrics, usage=streamed_usage)
                        response_text = await runtime.generate_response(user_text, runtime.llm_client, runtime.task_manager, runtime.cached_projects, history, last_response=last_jarvis_response, session_summary=session_summary, on_delta=speech_stream.feed if speech_stream else None)
                        llm_original = runtime.extract_action(response_text)[0]
                        clean_response, embedded_action = runtime.extract_action(response_text)
                        if embedded_action:
                            runtime.log.info(f'LLM embedded action: {embedded_action}')
                            if speech_stream:
                                await speech_stream.abort()
                                speech_stream = None
                            if not clean_response.strip() or runtime.is_banned_confirmation(clean_response):
                                response_text = ''
                            else:
                                response_text = clean_response
                            if embedded_action['action'] == 'build':
                                target = embedded_action['target']
                                name = runtime._generate_project_name(target)
                                path = str(runtime.Path.home() / 'Desktop' / name)
                                runtime.os.makedirs(path, exist_ok=True)
                                runtime.Path(path, 'CLAUDE.md').write_text(f"# Task\n\n{target}\n\n## Instructions\n- BUILD THIS NOW. Do not ask clarifying questions.\n- Use your best judgment for any design/architecture decisions.\n- Write complete, working code files — not plans or specs.\n- If it's a web app: use React + Vite + Tailwind unless specified otherwise.\n- Make it look polished and professional. Modern UI, clean layout.\n- Ensure it runs with a single command (npm run dev or similar).\n- If you reference a real product's UI (e.g. 'Zillow clone'), match their actual layout and features closely.\n- Use realistic mock data, not placeholder Lorem Ipsum.\n- After building, start the dev server and verify the app loads without errors.\n- IMPORTANT: Your LAST line of output MUST be exactly: RUNNING_AT=http://localhost:PORT (the actual port the dev server is using)\n")
                                did = runtime.dispatch_registry.register(name, path, target)
                                runtime.recently_built.append({'name': name, 'path': path, 'time': runtime.time.time()})
                                del runtime.recently_built[:-20]
                                runtime.asyncio.create_task(runtime._execute_prompt_project(name, target, work_session, ws, dispatch_id=did, history=history, voice_state=voice_state))
                            elif embedded_action['action'] == 'open_app':
                                result = await runtime.open_app(embedded_action['target'])
                                opened_app_name = result.get('app') if result.get('success') else None
                                pending_app_choices = result.get('candidates', [])
                                response_text = result['confirmation']
                            elif embedded_action['action'] == 'browse':
                                runtime.asyncio.create_task(runtime._execute_browse(embedded_action['target']))
                            elif embedded_action['action'] == 'research':
                                name = runtime._generate_project_name(embedded_action['target'])
                                path = str(runtime.Path.home() / 'Desktop' / name)
                                runtime.os.makedirs(path, exist_ok=True)
                                await work_session.start(path)
                                runtime.asyncio.create_task(runtime.self_work_and_notify(work_session, embedded_action['target'], ws))
                            elif embedded_action['action'] == 'open_terminal':
                                runtime.asyncio.create_task(runtime._execute_open_terminal())
                            elif embedded_action['action'] == 'prompt_project':
                                target = embedded_action['target']
                                if '|||' in target:
                                    proj_name, _, prompt = target.partition('|||')
                                    proj_name = proj_name.strip()
                                    prompt = prompt.strip()
                                    recent = runtime.dispatch_registry.get_recent_for_project(proj_name)
                                    if recent and recent.get('summary'):
                                        runtime.log.info(f'Using recent dispatch result for {proj_name} instead of re-dispatching')
                                        response_text = recent['summary']
                                        history.append({'role': 'assistant', 'content': f"[Previous dispatch result for {proj_name}]: {recent['summary']}"})
                                    else:
                                        runtime.asyncio.create_task(runtime._execute_prompt_project(proj_name, prompt, work_session, ws, history=history, voice_state=voice_state))
                                else:
                                    runtime.log.warning(f'PROMPT_PROJECT missing ||| delimiter: {target}')
                            elif embedded_action['action'] == 'add_task':
                                target = embedded_action['target']
                                parts = target.split('|||')
                                if len(parts) >= 2:
                                    priority = parts[0].strip() or 'medium'
                                    title = parts[1].strip()
                                    desc = parts[2].strip() if len(parts) > 2 else ''
                                    due = parts[3].strip() if len(parts) > 3 else ''
                                    runtime.create_task(title=title, description=desc, priority=priority, due_date=due)
                                    runtime.log.info(f'Task created: {title}')
                            elif embedded_action['action'] == 'add_note':
                                target = embedded_action['target']
                                if '|||' in target:
                                    topic, _, content = target.partition('|||')
                                    runtime.create_note(content=content.strip(), topic=topic.strip())
                                    runtime.local_notes.create_note(title=topic.strip(), body=content.strip(), folder='Notes')
                                else:
                                    runtime.create_note(content=target)
                                    runtime.local_notes.create_note(title='Note', body=target.strip(), folder='Notes')
                                runtime.log.info(f'Note created')
                            elif embedded_action['action'] == 'complete_task':
                                try:
                                    task_id = int(embedded_action['target'].strip())
                                    runtime.complete_task(task_id)
                                    runtime.log.info(f'Task {task_id} completed')
                                except ValueError:
                                    pass
                            elif embedded_action['action'] == 'remember':
                                runtime.remember(embedded_action['target'].strip(), mem_type='fact', importance=7)
                                runtime.log.info(f"Memory stored: {embedded_action['target'][:60]}")
                            elif embedded_action['action'] == 'create_note':
                                target = embedded_action['target']
                                if '|||' in target:
                                    title, _, body = target.partition('|||')
                                    runtime.asyncio.create_task(runtime.create_local_note(title.strip(), body.strip()))
                                    runtime.log.info(f'Local note created: {title.strip()}')
                                else:
                                    runtime.asyncio.create_task(runtime.create_local_note('JARVIS Note', target))
                            elif embedded_action['action'] == 'screen':
                                runtime.asyncio.create_task(runtime._lookup_and_report('screen', runtime._do_screen_lookup, ws, history=history, voice_state=voice_state))
                            elif embedded_action['action'] == 'read_note':

                                async def _read_and_report(search_term, _ws):
                                    note = await runtime.read_note(search_term)
                                    if note:
                                        msg = f"Sir, your note '{note['title']}' says: {note['body'][:200]}"
                                    else:
                                        msg = f"Couldn't find a note matching '{search_term}', sir."
                                    audio = await runtime.synthesize_speech(runtime.strip_markdown_for_tts(msg))
                                    if audio and _ws:
                                        try:
                                            await _ws.send_json({'type': 'status', 'state': 'speaking'})
                                            await _ws.send_json({'type': 'audio', 'data': runtime.base64.b64encode(audio).decode(), 'text': msg})
                                        except Exception:
                                            report_failure('voice:507')
                                            pass
                                runtime.asyncio.create_task(_read_and_report(embedded_action['target'].strip(), ws))
                if measure_action:
                    await metrics.mark('automation_complete')
                history.append({'role': 'user', 'content': user_text})
                history.append({'role': 'assistant', 'content': response_text})
                # An always-on socket must not retain the whole session. Trim the
                # prefix and shift the summary cursor; the rolling summary keeps
                # the older context in condensed form.
                if len(history) > 100:
                    removed = len(history) - 100
                    del history[:removed]
                    summarized_history_count = max(0, summarized_history_count - removed)
                messages_since_last_summary += 1
                if messages_since_last_summary >= 5 and len(history) > 20 and (not summary_update_pending) and (not local_command):
                    summary_update_pending = True
                    messages_since_last_summary = 0
                    summary_end = min(len(history) - 20, summarized_history_count + 20)
                    rotated = history[summarized_history_count:summary_end]
                    if rotated and runtime.llm_client:

                        async def _do_summary(batch=rotated, end=summary_end):
                            nonlocal session_summary, summary_update_pending, summarized_history_count
                            try:
                                session_summary = await runtime._update_session_summary(session_summary, batch, runtime.llm_client)
                                summarized_history_count = end
                            except Exception:
                                report_failure('voice:527')
                                pass
                            finally:
                                summary_update_pending = False
                        runtime.asyncio.create_task(_do_summary())
                    else:
                        summary_update_pending = False
                runtime.asyncio.create_task(runtime._save_personal_turn(user_text, opened_app_name, voice_state['last_user_time'], runtime.llm_client, not (quick_app_target or quick_app_choice or memory_open or pc_command or google_command or website_target or local_command)))
                tts = runtime.strip_markdown_for_tts(response_text)
                if not tts.strip() or runtime.is_banned_confirmation(tts):
                    if speech_stream:
                        await speech_stream.close()
                    await ws.send_json({'type': 'status', 'state': 'idle'})
                    runtime.log.info('Response completed (audio suppressed)')
                    last_jarvis_response = response_text
                else:
                    await ws.send_json({'type': 'status', 'state': 'speaking'})
                    if speech_stream:
                        if llm_original is not None and runtime.strip_markdown_for_tts(llm_original).strip() != tts.strip():
                            for phrase in speech_stream.buffer.push('', final=True):
                                await speech_stream.enqueue(phrase)
                            await speech_stream.enqueue(tts)
                        streamed = await speech_stream.finish()
                    else:
                        streamed = await runtime.stream_speech(ws, tts, metrics) if msg.get('streamAudio') else False
                    if not streamed:
                        audio = await runtime.synthesize_speech(tts)
                        if audio:
                            await ws.send_json({'type': 'audio', 'data': runtime.base64.b64encode(audio).decode(), 'text': response_text})
                        else:
                            await ws.send_json({'type': 'text', 'text': response_text})
                            await ws.send_json({'type': 'status', 'state': 'idle'})
                    runtime.log.info('Response completed')
                    last_jarvis_response = response_text
            except Exception as e:
                report_failure('voice:561')
                runtime.log.error(f'Error: {e}', exc_info=True)
                if speech_stream and speech_stream.sent:
                    await speech_stream.close()
                    await ws.send_json({'type': 'pcm_end', 'id': speech_stream.id})
                    await ws.send_json({'type': 'text', 'text': 'The response was interrupted by a connection error. Please try again.'})
                    return
                try:
                    fallback = 'Something went wrong, sir.'
                    audio = await runtime.synthesize_speech(fallback)
                    if audio:
                        await ws.send_json({'type': 'audio', 'data': runtime.base64.b64encode(audio).decode(), 'text': fallback})
                    else:
                        await ws.send_json({'type': 'audio', 'data': '', 'text': fallback})
                except Exception:
                    report_failure('voice:575')
                    pass
            finally:
                if speech_stream:
                    await speech_stream.close()
        while True:
            raw = await raw_ws.receive_text()
            try:
                msg = runtime.json.loads(raw)
            except runtime.json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get('type') == 'phone_call_privacy_ready':
                phone_call_privacy.acknowledge(ws, str(msg.get('session', '')))
                continue
            if phone_call_privacy.active and msg.get('type') == 'transcript':
                continue
            if msg.get('type') == 'playback_metrics':
                await runtime.asyncio.to_thread(runtime.voice_metrics.record, msg)
                continue
            turn_id = msg.get('turn_id')
            if turn_id and msg.get('type') == 'transcript':
                if not isinstance(turn_id, str) or len(turn_id) > 80 or turn_id in seen_turn_ids:
                    continue
                seen_turn_ids.add(turn_id)
                if len(seen_turn_ids) > 256:
                    seen_turn_ids.clear()
                    seen_turn_ids.add(turn_id)
            stop = msg.get('type') == 'stop' or (msg.get('type') == 'transcript' and bool(runtime._action_re.fullmatch('(?i)\\s*(?:(?:jarvis|please)[, ]+)?(?:stop|stopp|stop talking|be quiet|quiet|halt)(?:[,.! ]+please)?[.!? ]*', str(msg.get('text', '')))))
            if not stop and msg.get('type') != 'fix_self' and (not (msg.get('type') == 'transcript' and msg.get('isFinal'))):
                continue
            turn_epoch += 1
            if greeting_task:
                greeting_task.cancel()
            if stop:
                local_pc.pending = ''
                if msg.get('cancelTasks') or msg.get('type') == 'transcript':
                    # Signal Codex before cancelling the coroutine that awaits
                    # it, otherwise the worker thread keeps editing files.
                    await autonomous.cancel()
                    await work_session.cancel()
                    runtime.pc_control.cancel_code()
            if active_turn and (not active_turn.done()):
                active_turn.cancel()
                await runtime.asyncio.gather(active_turn, return_exceptions=True)
            if stop:
                await raw_ws.send_json({'type': 'stopped'})
                continue
            active_turn = runtime.asyncio.create_task(process_message(msg, turn_epoch))
    except runtime.WebSocketDisconnect:
        runtime.log.info('Voice WebSocket disconnected')
    except Exception as e:
        report_failure('voice:617')
        runtime.log.error(f'WebSocket error: {e}', exc_info=True)
    finally:
        await autonomous.cancel()
        for pending in (active_turn, greeting_task):
            if pending:
                pending.cancel()
        await runtime.asyncio.gather(*(t for t in (active_turn, greeting_task) if t), return_exceptions=True)
        runtime.task_manager.unregister_websocket(ws)
