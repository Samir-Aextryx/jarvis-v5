from jarvis.core.diagnostics import report_failure
"""Dedicated API routes; runtime owns shared services during incremental extraction."""
from fastapi import APIRouter, WebSocket, Request
from typing import Optional
from jarvis.routers.models import *
from jarvis import server as runtime
router = APIRouter()

@router.post('/api/google/api-key')
async def api_google_key(body: GoogleAPIKeyRequest):
    try:
        return await runtime.asyncio.to_thread(runtime.google_access.save_api_key, body.key)
    except ValueError as exc:
        return runtime.JSONResponse({'error': str(exc)}, status_code=400)

@router.post('/api/google/test-api-key')
async def api_google_test_key():
    try:
        await runtime.asyncio.to_thread(runtime.google_access.public_youtube, 1)
        return {'valid': True, 'message': 'YouTube Data API access verified. Private Gmail and Calendar still require Google sign-in.'}
    except ValueError as exc:
        return runtime.JSONResponse({'error': str(exc)}, status_code=400)

@router.get('/api/google/status')
async def api_google_status():
    return await runtime.asyncio.to_thread(runtime.google_access.status)

@router.post('/api/google/config')
async def api_google_config(body: GoogleConfigRequest):
    try:
        if len(runtime.json.dumps(body.config)) > 16000:
            raise ValueError('OAuth JSON is too large.')
        return await runtime.asyncio.to_thread(runtime.google_access.configure, body.config, body.services)
    except ValueError as exc:
        return runtime.JSONResponse({'error': str(exc)}, status_code=400)

@router.post('/api/google/connect')
async def api_google_connect(body: GoogleConnectRequest):
    try:
        return await runtime.asyncio.to_thread(runtime.google_access.connect, body.services)
    except ValueError as exc:
        return runtime.JSONResponse({'error': str(exc)}, status_code=400)

@router.post('/api/google/disconnect')
async def api_google_disconnect():
    try:
        return await runtime.asyncio.to_thread(runtime.google_access.disconnect)
    except ValueError as exc:
        return runtime.JSONResponse({'error': str(exc)}, status_code=400)

@router.get('/api/google/read/{service}')
async def api_google_read(service: str):
    if service not in runtime.GOOGLE_SCOPES:
        return runtime.JSONResponse({'error': 'Unsupported Google service.'}, status_code=400)
    try:
        return await runtime.asyncio.to_thread(runtime.google_access.read, service)
    except ValueError as exc:
        return runtime.JSONResponse({'error': str(exc)}, status_code=400)
    except Exception:
        report_failure('integrations:58')
        return runtime.JSONResponse({'error': 'Google could not be reached.'}, status_code=502)
