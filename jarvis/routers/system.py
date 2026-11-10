from jarvis.core.diagnostics import report_failure
"""Dedicated API routes; runtime owns shared services during incremental extraction."""
from fastapi import APIRouter, WebSocket, Request
from typing import Optional
from jarvis import __version__
from jarvis.routers.models import *
from jarvis import server as runtime
from pydantic import BaseModel, SecretStr
from typing import Literal
from jarvis.integrations.llm_providers import provider_status
router = APIRouter()


class LLMTest(BaseModel):
    provider: Literal['openai', 'gemini', 'grok', 'ollama']
    key_value: SecretStr | None = None


@router.get('/api/settings/llm')
async def api_llm_status():
    return provider_status()


@router.post('/api/settings/test-llm')
async def api_test_llm(body: LLMTest):
    key = body.key_value.get_secret_value().strip() if body.key_value else None
    if key and (len(key) > 2048 or any(char.isspace() for char in key)):
        return runtime.JSONResponse({'valid': False, 'error': 'Invalid API key value'}, status_code=400)
    try:
        client = runtime.LLMClient(api_key=key or None, provider=body.provider)
        await client.create(max_tokens=256, messages=[{'role': 'user', 'content': 'Reply only with OK.'}])
        return {'valid': True, 'provider': body.provider}
    except Exception:
        return {'valid': False, 'provider': body.provider,
                'error': 'Connection failed. Check the API key, model availability and API credit.'}


async def mail_provider_status():
    """Report actual provider availability without blocking the API event loop."""
    from jarvis.integrations.outlook_com import account_accessible
    outlook_ok = await runtime.asyncio.to_thread(account_accessible)
    google = await runtime.asyncio.to_thread(runtime.google_access.status)
    services = set(google.get('services', []))
    google_ok = bool(google.get('connected') and services.intersection({'gmail', 'gmail_drafts', 'gmail_send'}))
    return {'outlook_accessible': outlook_ok, 'google_mail_accessible': google_ok,
            'mail_accessible': outlook_ok or google_ok}

@router.get('/api/health')
async def health():
    return {'status': 'online', 'name': 'JARVIS', 'version': __version__}

@router.get('/api/usage')
async def api_usage():
    def snapshot():
        periods = runtime._get_usage_periods({
            'today': 86400, 'week': 86400 * 7, 'month': 86400 * 30, 'all_time': None,
        })
        uptime = int(runtime.time.time() - runtime._session_start)
        result = {'session': {**runtime._session_tokens, 'uptime_seconds': uptime}}
        for name, totals in periods.items():
            result[name] = {
                **totals,
                'cost_usd': round(runtime._cost_from_tokens(totals['input_tokens'], totals['output_tokens']), 4),
            }
        return result
    # Parsing the log is disk/CPU work; keep it off the voice event loop.
    return await runtime.asyncio.to_thread(snapshot)

@router.post('/api/settings/keys')
async def api_settings_keys(body: KeyUpdate):
    allowed = {'OPENAI_API_KEY', 'GEMINI_API_KEY', 'XAI_API_KEY', 'OLLAMA_API_KEY', 'FISH_API_KEY', 'FISH_VOICE_ID', 'USER_NAME', 'HONORIFIC', 'OPENAI_MODEL', 'FISH_MODEL'}
    if body.key_name not in allowed:
        return runtime.JSONResponse({'success': False, 'error': 'Invalid key name'}, status_code=400)
    if any((c in body.key_value for c in '\r\n\x00')):
        return runtime.JSONResponse({'success': False, 'error': 'Invalid multiline value'}, status_code=400)
    if body.key_name in {'GEMINI_API_KEY', 'XAI_API_KEY', 'OLLAMA_API_KEY'} and (len(body.key_value) > 2048 or any(c.isspace() for c in body.key_value)):
        return runtime.JSONResponse({'success': False, 'error': 'Invalid API key value'}, status_code=400)
    try:
        runtime._write_env_key(body.key_name, body.key_value)
    except (RuntimeError, OSError):
        return runtime.JSONResponse({'success': False, 'error': 'The key could not be saved securely. Check Windows Credential Manager.'}, status_code=503)
    runtime.OPENAI_API_KEY = runtime.get_secure_key('OPENAI_API_KEY')
    runtime.FISH_API_KEY = runtime.get_secure_key('FISH_API_KEY')
    runtime.FISH_VOICE_ID = runtime.active_fish_voice_id()
    runtime.USER_NAME = runtime.os.getenv('USER_NAME', runtime.USER_NAME)
    client = runtime.LLMClient()
    runtime.llm_client = client if client.api_key else None
    return {'success': True}

@router.post('/api/settings/test-openai')
async def api_test_openai(body: KeyTest):
    key = body.key_value or runtime.OPENAI_API_KEY or runtime.get_secure_key('OPENAI_API_KEY')
    if not key:
        return {'valid': False, 'error': 'No key provided'}
    try:
        client = runtime.LLMClient(api_key=key, provider='openai')
        await client.messages.create(max_tokens=10, messages=[{'role': 'user', 'content': 'Reply only with OK.'}])
        return {'valid': True}
    except Exception as e:
        report_failure('system:45')
        return {'valid': False, 'error': str(e)[:200]}

@router.post('/api/settings/test-fish')
async def api_test_fish(body: KeyTest):
    key = body.key_value or runtime.FISH_API_KEY or runtime.get_secure_key('FISH_API_KEY')
    if not key:
        return {'valid': False, 'error': 'No key provided'}
    try:
        async with runtime.httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post('https://api.fish.audio/v1/tts', headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json', 'model': runtime.os.getenv('FISH_MODEL', 's2.1-pro-free')}, json={'text': 'test', 'reference_id': runtime.FISH_VOICE_ID})
            if resp.status_code in (200, 201):
                return {'valid': True}
            elif resp.status_code == 401:
                return {'valid': False, 'error': 'Invalid API key'}
            else:
                return {'valid': False, 'error': f'HTTP {resp.status_code}'}
    except Exception as e:
        report_failure('system:62')
        return {'valid': False, 'error': str(e)[:200]}

@router.get('/api/settings/status')
async def api_settings_status():
    from jarvis.automation.pc_control import codex_executable
    _, env_dict = await runtime.asyncio.to_thread(runtime._read_env)
    try:
        await runtime.asyncio.to_thread(codex_executable)
        codex_installed = True
    except (OSError, RuntimeError):
        codex_installed = False
    calendar_ok = notes_ok = True
    try:
        await runtime.asyncio.to_thread(runtime.local_calendar.upcoming, 1)
    except Exception:
        report_failure('system:77')
        calendar_ok = False
    try:
        await runtime.get_recent_notes(count=1)
    except Exception:
        report_failure('system:91')
        notes_ok = False
    try:
        mail_status = await mail_provider_status()
    except Exception:
        report_failure('system:mail_status')
        mail_status = {'outlook_accessible': False, 'google_mail_accessible': False,
                       'mail_accessible': False}
    memory_count = task_count = 0
    try:
        memories = await runtime.asyncio.to_thread(runtime.get_important_memories, 9999)
        memory_count = len(memories)
    except Exception:
        report_failure('system:96')
        pass
    try:
        open_tasks = await runtime.asyncio.to_thread(runtime.get_open_tasks)
        task_count = len(open_tasks)
    except Exception:
        report_failure('system:100')
        pass
    active_openai, active_fish = await runtime.asyncio.gather(
        runtime.asyncio.to_thread(runtime.get_secure_key, 'OPENAI_API_KEY'),
        runtime.asyncio.to_thread(runtime.get_secure_key, 'FISH_API_KEY'),
    )
    active_openai = runtime.OPENAI_API_KEY or active_openai
    active_fish = runtime.FISH_API_KEY or active_fish
    return {'platform': 'Windows', 'openai_model': runtime.os.getenv('OPENAI_MODEL', 'gpt-6-luna'), 'codex_installed': codex_installed, 'calendar_accessible': calendar_ok, **mail_status, 'notes_accessible': notes_ok, 'atlassian_accessible': runtime.is_atlassian_ready(), 'memory_count': memory_count, 'task_count': task_count, 'server_port': int(runtime.os.getenv('JARVIS_PORT', '8340')), 'uptime_seconds': int(runtime.time.time() - runtime._session_start), 'env_keys_set': {'openai': bool(active_openai.strip() if isinstance(active_openai, str) else False), 'fish_audio': bool(active_fish.strip() and active_fish != 'your-fish-audio-api-key-here' if isinstance(active_fish, str) else False), 'fish_voice_id': bool(env_dict.get('FISH_VOICE_ID', '').strip()), 'user_name': env_dict.get('USER_NAME', '')}}

@router.get('/api/settings/preferences')
async def api_get_preferences():
    _, env_dict = runtime._read_env()
    return {'user_name': env_dict.get('USER_NAME', ''), 'honorific': env_dict.get('HONORIFIC', 'sir'),
            'stt_keywords': env_dict.get('JARVIS_STT_KEYWORDS', '')}

@router.post('/api/settings/preferences')
async def api_save_preferences(body: PreferencesUpdate):
    keywords = [term.strip() for term in body.stt_keywords.split(',') if term.strip()]
    if (len(body.stt_keywords) > 800 or len(keywords) > 12
            or any(len(term) > 64 or any(char in term for char in '<>\r\n\x00') for term in keywords)):
        return runtime.JSONResponse({'error': 'Use at most 12 comma-separated recognition terms, each 64 characters or less.'}, status_code=400)
    runtime._write_env_key('USER_NAME', body.user_name)
    runtime._write_env_key('HONORIFIC', body.honorific)
    runtime._write_env_key('JARVIS_STT_KEYWORDS', ', '.join(keywords))
    runtime.os.environ['JARVIS_STT_KEYWORDS'] = ', '.join(keywords)
    runtime.USER_NAME = body.user_name
    return {'success': True}

@router.post('/api/restart')
async def api_restart():
    """Restart the JARVIS server."""
    runtime.log.info('Restart requested — shutting down in 2 seconds')

    async def _restart():
        await runtime.asyncio.sleep(2)
        # When the Electron shell started us, it owns the process and will spawn
        # a replacement. Self-restarting here would leave an untracked orphan.
        if runtime.os.getenv('JARVIS_DESKTOP_MANAGED') == '1':
            runtime.os._exit(0)
        if getattr(runtime.sys, 'frozen', False):
            import subprocess
            subprocess.Popen([runtime.sys.executable], env=runtime.os.environ.copy(), creationflags=subprocess.CREATE_NO_WINDOW)
            runtime.os._exit(0)
        cmd = [runtime.sys.executable, '-m', 'jarvis',
               '--port', runtime.os.getenv('JARVIS_PORT', '8340'),
               '--host', runtime.os.getenv('JARVIS_HOST', '127.0.0.1')]
        runtime.os.execv(runtime.sys.executable, cmd)
    runtime.asyncio.create_task(_restart())
    return {'status': 'restarting'}

@router.post('/api/fix-self')
async def api_fix_self():
    """Enter work mode in the JARVIS repo — JARVIS can now fix himself."""
    jarvis_dir = str(runtime.RESOURCE_ROOT)
    result = await runtime.open_codex_in_project(jarvis_dir, 'Inspect this project and help me improve it.')
    return {'status': 'work_mode_active' if result['success'] else 'unavailable',
            'path': jarvis_dir, 'message': result['confirmation']}
