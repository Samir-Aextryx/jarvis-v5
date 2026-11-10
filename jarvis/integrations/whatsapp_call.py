"""Verified WhatsApp Beta contact and honest call capability checks."""

import asyncio
import logging
import re
import threading
import time

from jarvis.integrations.credentials_vault import get_vault, _service_name

_CONTACT_KEY = "WHATSAPP_BOSS_NUMBER"
log = logging.getLogger('jarvis.whatsapp_call')
_audio_test_lock = threading.Lock()
_audio_test_cache = (0.0, (), False)
_CALL_COMMAND = re.compile(
    r"(?i)^(?:(?:please|bitte)\s+)?(?:call|ring|ruf(?:e)?|anrufen|telefoniere(?:n)?)"
    r"\s+(?:(?:mich|me|boss)(?:\s+an)?|(?:boss|mich|me)\s+(?:via|auf|mit|on)\s+whatsapp(?:\s+beta)?)"
    r"(?:\s+(?:via|auf|mit|on)\s+whatsapp(?:\s+beta)?)?[.!?]*$"
)


def parse_call_request(text: str) -> bool:
    """Recognize only an explicit request to call the owner's saved contact."""
    return bool(_CALL_COMMAND.fullmatch(text.strip()))


def normalize_swiss_mobile(number: str) -> str:
    compact = re.sub(r"[\s().-]", "", number)
    if re.fullmatch(r"07\d{8}", compact):
        return "+41" + compact[1:]
    if re.fullmatch(r"\+417\d{8}", compact):
        return compact
    raise ValueError("Enter a Swiss mobile number beginning with 07 or +417.")


def save_boss_number(number: str) -> None:
    vault = get_vault()
    if vault is None:
        raise RuntimeError("Windows Credential Manager is unavailable; the number was not saved.")
    normalized = normalize_swiss_mobile(number)
    vault.set_password(_service_name(), _CONTACT_KEY, normalized)
    if vault.get_password(_service_name(), _CONTACT_KEY) != normalized:
        raise RuntimeError("The contact number could not be verified in Windows Credential Manager.")


def boss_number_configured() -> bool:
    vault = get_vault()
    if vault is None:
        return False
    try:
        return bool(normalize_swiss_mobile(vault.get_password(_service_name(), _CONTACT_KEY) or ""))
    except (ValueError, OSError):
        return False


def whatsapp_beta_microphone_allowed() -> bool:
    """Read the package's current Windows microphone grant before any dial."""
    import winreg

    package = '5319275A.51895FA4EA97F_cv1g1gvanyjgm'
    path = (r'Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager'
            r'\ConsentStore\microphone' + '\\' + package)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            value, _ = winreg.QueryValueEx(key, 'Value')
    except OSError:
        return False
    return value == 'Allow'


def _verified_audio_devices(devices) -> bool:
    global _audio_test_cache
    from jarvis.voice.call_audio_bridge import verify_virtual_cable

    identifiers = (devices.cable_input.id, devices.cable_output.id)
    with _audio_test_lock:
        previous_time, previous_ids, previous_result = _audio_test_cache
        if previous_ids == identifiers and time.monotonic() - previous_time < 300:
            return previous_result
        verified = verify_virtual_cable(devices)
        _audio_test_cache = (time.monotonic(), identifiers, verified)
        return verified


async def call_readiness() -> dict:
    """Do not claim a callable path until the voice bridge and call UI exist."""
    from jarvis.automation.app_launcher import installed_apps, resolve_app

    apps = await asyncio.to_thread(installed_apps)
    beta = resolve_app("WhatsApp Beta", apps)
    if not beta:
        apps = await asyncio.to_thread(installed_apps, True)
        beta = resolve_app("WhatsApp Beta", apps)
    installed = len(beta) == 1 and beta[0]["name"].casefold() == "whatsapp beta"
    contact_saved = boss_number_configured()
    microphone_permission_granted = whatsapp_beta_microphone_allowed()
    try:
        from jarvis.voice.call_audio_bridge import discover_call_audio_devices
        devices = await asyncio.wait_for(asyncio.to_thread(discover_call_audio_devices), timeout=3)
        virtual_audio_present = bool(devices.cable_input and devices.cable_output)
        call_loopback_present = bool(devices.call_speaker and devices.call_loopback)
        audio_bridge_ready = bool(virtual_audio_present and call_loopback_present and
                                  await asyncio.wait_for(
                                      asyncio.to_thread(_verified_audio_devices, devices), timeout=4))
    except (ImportError, OSError, RuntimeError, ValueError, TimeoutError):
        virtual_audio_present = False
        call_loopback_present = False
        audio_bridge_ready = False
    if not installed:
        reason = "WhatsApp Beta is not installed or cannot be identified uniquely."
    elif not contact_saved:
        reason = "Boss's contact number is not saved in Windows Credential Manager."
    elif not microphone_permission_granted:
        reason = "Windows has not granted WhatsApp Beta microphone access."
    elif not virtual_audio_present:
        reason = "A virtual microphone is missing. Jarvis cannot send its voice into a WhatsApp call."
    elif not audio_bridge_ready:
        reason = "The virtual audio cable has not passed its playback and capture check."
    else:
        reason = "Audio is ready, but WhatsApp contact, call connection and conversation controls are not verified yet."
    return {
        "contact_saved": contact_saved,
        "whatsapp_beta_installed": installed,
        "microphone_permission_granted": microphone_permission_granted,
        "virtual_audio_present": virtual_audio_present,
        "call_loopback_present": call_loopback_present,
        "audio_bridge_ready": audio_bridge_ready,
        "automatic_call_ready": False,
        "reason": reason,
    }


async def prepare_call_to_boss() -> str:
    """Open the exact desktop app, but never present an unplaced call as placed."""
    readiness = await call_readiness()
    if not readiness["contact_saved"]:
        return "Boss's contact number is not saved in Windows Credential Manager. I did not place a call."
    if not readiness["whatsapp_beta_installed"]:
        return "WhatsApp Beta is not installed or cannot be identified uniquely. I did not place a call."
    from jarvis.automation.app_launcher import open_app

    result = await open_app("WhatsApp Beta", wait_until_ready=True)
    if not result.get("success"):
        return "I could not verify the WhatsApp Beta window. I did not place a call."
    from jarvis.automation.whatsapp_beta_ui import ContactNotVerified, verify_boss_contact
    try:
        vault = get_vault()
        number = vault.get_password(_service_name(), _CONTACT_KEY) if vault else None
        matched = await asyncio.to_thread(verify_boss_contact, number or '')
    except (ContactNotVerified, OSError, RuntimeError, ValueError, ImportError) as exc:
        log.warning('Boss contact verification failed: %s', type(exc).__name__)
        matched = False
    except Exception as exc:
        # The desktop UI can change without notice; never let an unexpected
        # automation result become permission to call an unverified contact.
        log.exception('Unexpected WhatsApp Beta contact verification failure: %s', type(exc).__name__)
        matched = False
    if not matched:
        return "WhatsApp Beta is open, but I could not verify Boss's exact contact number. I did not place a call."
    return "I verified Boss's exact WhatsApp contact. I cannot place or speak in the call yet because the two-way audio bridge and answered-call controls are not ready. I did not place a call."


async def attempt_urgent_call(alert: dict) -> dict:
    """Fail closed until dialing, recipient and answered-call checks exist."""
    if alert.get('source') not in {'gmail', 'outlook'} or not alert.get('id'):
        return {'state': 'not_ready'}
    readiness = await call_readiness()
    if (not readiness['contact_saved'] or not readiness['whatsapp_beta_installed']
            or not readiness.get('microphone_permission_granted')):
        return {'state': 'not_ready'}
    if not readiness['audio_bridge_ready'] or not readiness['automatic_call_ready']:
        return {'state': 'not_ready'}
    # Devices alone are insufficient. The caller must also verify Boss, place
    # the call, detect an answer and finish speaking before reporting success.
    return {'state': 'not_ready'}
