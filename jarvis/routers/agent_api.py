"""Authenticated by the server's existing /api middleware."""
import asyncio
import os
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, SecretStr
from jarvis.core.agent_settings import agent_settings
from jarvis.integrations.jev_client import jev, save_jev_key, JevError, MISSING_KEY_CODE, MISSING_KEY_MESSAGE
from jarvis.integrations.whatsapp_call import call_readiness, save_boss_number
from jarvis.integrations.urgent_mail import urgent_mail_monitor
from jarvis.voice.call_privacy import phone_call_privacy
from jarvis.integrations.llm_providers import apply_provider_settings

router = APIRouter(prefix='/api/agent')


@router.get('/phone-privacy/status')
async def phone_privacy_status():
    return {'active': phone_call_privacy.active}


class KeyBody(BaseModel):
    key: SecretStr


class PhoneBody(BaseModel):
    number: SecretStr


@router.get('/whatsapp-call/status')
async def whatsapp_call_status():
    return await call_readiness()


@router.post('/whatsapp-call/contact')
async def whatsapp_call_contact(body: PhoneBody):
    try:
        await asyncio.to_thread(save_boss_number, body.number.get_secret_value())
        return {'saved': True}
    except (ValueError, RuntimeError, OSError) as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)


@router.get('/urgent-mail/status')
async def urgent_mail_status():
    return urgent_mail_monitor.status()


@router.get('/settings')
async def settings():
    configured = jev.configured()
    return dict(agent_settings.get(), jev_configured=configured,
                jev_status=jev.connection if jev.configured() else 'Not Connected',
                jev_error=jev.last_error if configured else MISSING_KEY_MESSAGE,
                jev_error_code=("JEV_CONNECTION_ERROR" if jev.last_error else None) if configured else MISSING_KEY_CODE,
                capabilities={'gmail':'Configure in Google settings', 'outlook_graph':'Not connected / unavailable',
                              'teams_notifications':'Unavailable', 'local_calendar':'Available'})


@router.post('/settings')
async def save_settings(body: dict):
    try:
        result = await asyncio.to_thread(agent_settings.save, body)
        apply_provider_settings(result)
        # Replace the shared conversation client without changing any request
        # already in flight. Subsequent planners construct the selected provider.
        from jarvis import server as runtime
        client = runtime.LLMClient()
        runtime.llm_client = client if client.api_key else None
        return result
    except ValueError as exc:
        return JSONResponse({'error':str(exc)}, status_code=400)


@router.post('/jev/key')
async def save_key(body: KeyBody):
    try:
        await asyncio.to_thread(save_jev_key, body.key.get_secret_value())
        jev.connection, jev.last_error, jev.cooldown = 'Not Connected', '', 0
        return {'saved':jev.configured(), 'status':jev.connection}
    except (JevError, ValueError) as exc:
        return JSONResponse({'error':str(exc)}, status_code=400)


@router.post('/jev/test')
async def test_key():
    try:
        return await jev.test()
    except JevError as exc:
        return JSONResponse({'error':str(exc), 'code':exc.code, 'status':'Connection Error'}, status_code=409 if exc.code == MISSING_KEY_CODE else 502)


@router.get('/activity')
async def activity():
    return {'items':await asyncio.to_thread(agent_settings.logs)}


@router.post('/activity/clear')
async def clear_activity():
    await asyncio.to_thread(agent_settings.clear_logs)
    return {'ok':True}
