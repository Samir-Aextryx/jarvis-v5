"""Dedicated API routes; runtime owns shared services during incremental extraction."""
from fastapi import APIRouter, WebSocket, Request
from typing import Optional
from jarvis.routers.models import *
from jarvis import server as runtime
router = APIRouter()

@router.get('/api/apps')
async def api_apps():
    apps = await runtime.asyncio.to_thread(runtime.installed_apps)
    return {'apps': [app['name'] for app in apps]}

@router.post('/api/pc/command')
async def api_pc_command(body: PCCommandRequest):
    if not runtime.agent_settings.get()['automation']:
        return runtime.JSONResponse({'error': 'Command execution is paused in AI Settings.'}, status_code=409)
    if len(body.text) > 16000:
        return runtime.JSONResponse({'error': 'Befehl zu lang.'}, status_code=400)
    command = runtime.pc_control.parse(body.text)
    if not command:
        return runtime.JSONResponse({'error': 'Kein unterstützter PC-Befehl.'}, status_code=400)
    return {'text': await runtime.pc_control.execute(command)}

@router.get('/api/pc/jobs')
async def api_pc_jobs():
    return {'jobs': list(runtime.pc_control.jobs.values())}

@router.get('/api/local-pc/status')
async def api_local_pc_status():
    from jarvis.integrations.llm_providers import provider_status
    return {**provider_status(), 'scope': 'Explicit PC commands and autonomous tasks'}

@router.get('/api/autonomy/jobs')
async def api_autonomous_jobs():
    return {'jobs': runtime.recent_jobs()}

@router.post('/api/apps/open')
async def api_open_app(body: OpenAppRequest):
    if not runtime.agent_settings.get()['automation']:
        return runtime.JSONResponse({'error': 'Command execution is paused in AI Settings.'}, status_code=409)
    result = await runtime.open_app(body.name)
    return {key: value for key, value in result.items() if key != 'candidates'}

@router.get('/api/tasks')
async def api_list_tasks():
    tasks = await runtime.task_manager.list_tasks()
    return {'tasks': [t.to_dict() for t in tasks]}

@router.get('/api/tasks/{task_id}')
async def api_get_task(task_id: str):
    task = await runtime.task_manager.get_status(task_id)
    if not task:
        return runtime.JSONResponse(status_code=404, content={'error': 'Task not found'})
    return {'task': task.to_dict()}

@router.post('/api/tasks')
async def api_create_task(req: TaskRequest):
    try:
        task_id = await runtime.task_manager.spawn(req.prompt, req.working_dir)
        return {'task_id': task_id, 'status': 'spawned'}
    except RuntimeError as e:
        return runtime.JSONResponse(status_code=429, content={'error': str(e)})

@router.delete('/api/tasks/{task_id}')
async def api_cancel_task(task_id: str):
    cancelled = await runtime.task_manager.cancel(task_id)
    if not cancelled:
        return runtime.JSONResponse(status_code=404, content={'error': 'Task not found or not cancellable'})
    return {'task_id': task_id, 'status': 'cancelled'}

@router.get('/api/projects')
async def api_list_projects():
    runtime.cached_projects = await runtime.scan_projects()
    return {'projects': runtime.cached_projects}
