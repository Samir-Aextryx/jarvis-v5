"""Dedicated API routes; runtime owns shared services during incremental extraction."""
from fastapi import APIRouter, WebSocket, Request
from typing import Optional
from jarvis.routers.models import *
from jarvis import server as runtime
router = APIRouter()

@router.get('/api/memory/profile')
async def api_memory_profile():
    # Reading MEMORY.md and parsing facts is disk work; keep it off the loop.
    markdown = await runtime.asyncio.to_thread(runtime.personal_memory.path.read_text, encoding='utf-8')
    facts = await runtime.asyncio.to_thread(runtime.personal_memory.facts)
    return {'markdown': markdown, 'facts': facts}

@router.post('/api/memory/open')
async def api_open_memory():
    try:
        runtime.os.startfile(str(runtime.personal_memory.path))
    except OSError:
        import subprocess
        subprocess.Popen([str(runtime.Path(runtime.os.environ.get('SystemRoot', 'C:\\Windows')) / 'notepad.exe'), str(runtime.personal_memory.path)])
    return {'success': True}

@router.post('/api/memory/custom')
async def api_memory_custom(body: dict):
    try:
        fact = await runtime.asyncio.to_thread(runtime.personal_memory.edit_fact, content=body.get('content', ''), kind=body.get('kind', 'fact'), key=body.get('key'), expected_updated=body.get('expected_updated'))
        return {'fact': fact}
    except ValueError as e:
        msg = str(e)
        status = 409 if 'changed or was removed' in msg else 400
        return runtime.StarletteJSONResponse({'error': msg}, status_code=status)

@router.post('/api/memory/delete')
async def api_memory_delete(body: dict):
    try:
        await runtime.asyncio.to_thread(runtime.personal_memory.delete_fact, key=body.get('key', ''), expected_updated=body.get('expected_updated'))
        return {'success': True}
    except ValueError as e:
        return runtime.StarletteJSONResponse({'error': str(e)}, status_code=409)

@router.get('/api/local-calendar/events')
async def api_local_calendar_events(start: Optional[str]=None, end: Optional[str]=None):
    from jarvis.integrations.calendar_workflows import ZONE
    from datetime import timedelta
    try:
        if not start or not end:
            now = runtime.datetime.now()
            start = start or now.strftime('%Y-%m-%d')
            end = end or (now + timedelta(days=30)).strftime('%Y-%m-%d')
        events = await runtime.asyncio.to_thread(runtime.local_calendar.list_events, start, end)
        return {'events': events, 'timezone': ZONE}
    except ValueError as e:
        return runtime.StarletteJSONResponse({'error': str(e)}, status_code=400)

@router.post('/api/local-calendar/events')
async def api_local_calendar_save_event(body: dict):
    try:
        event = await runtime.asyncio.to_thread(runtime.local_calendar.save, data=body, event_id=body.get('id'), expected_version=body.get('version'))
        return {'event': event}
    except ValueError as e:
        msg = str(e)
        status = 409 if 'changed or was removed' in msg else 400
        return runtime.StarletteJSONResponse({'error': msg}, status_code=status)

@router.post('/api/local-calendar/delete')
async def api_local_calendar_delete_event(body: dict):
    try:
        await runtime.asyncio.to_thread(runtime.local_calendar.delete, event_id=body.get('id', ''), expected_version=body.get('version'))
        return {'success': True}
    except ValueError as e:
        return runtime.StarletteJSONResponse({'error': str(e)}, status_code=409)

@router.get('/api/notes')
async def api_list_notes(query: Optional[str]=None):
    if query:
        notes = await runtime.asyncio.to_thread(runtime.local_notes.search_notes, query)
    else:
        notes = await runtime.asyncio.to_thread(runtime.local_notes.list_notes)
    return {'notes': notes}

@router.post('/api/notes')
async def api_create_note(body: dict):
    note = await runtime.asyncio.to_thread(
        runtime.local_notes.create_note,
        title=body.get('title', ''), body=body.get('body', ''),
        folder=body.get('folder', 'Notes'), tags=body.get('tags'))
    return {'note': note}

@router.delete('/api/notes/{note_id}')
async def api_delete_note(note_id: str):
    success = await runtime.asyncio.to_thread(runtime.local_notes.delete_note, note_id)
    if not success:
        return runtime.StarletteJSONResponse({'error': 'Note not found'}, status_code=404)
    return {'success': True}
