"""Fail-closed recipient check for the installed WhatsApp Beta desktop UI.

WhatsApp Beta does not expose the contact text through Windows UI Automation on
this machine. We can still select the visible number in Contact info, copy it
locally, and compare it to the owner's vault entry. This module never clicks
the voice-call button. Layout changes cause a failed check, not a guessed call.
"""

import ctypes
import re
import threading
import time
from dataclasses import dataclass

_UI_LOCK = threading.Lock()


class ContactNotVerified(RuntimeError):
    """The exact saved WhatsApp recipient could not be confirmed."""


@dataclass(frozen=True)
class ContactLayout:
    search: tuple[int, int]
    first_result: tuple[int, int]
    contact_header: tuple[int, int]
    number_start: tuple[int, int]
    number_end: tuple[int, int]


def contact_layout(width: int, height: int) -> ContactLayout:
    """Supported WhatsApp Beta layout; reject unfamiliar window sizes."""
    if not 850 <= width <= 2000 or not 560 <= height <= 1200:
        raise ContactNotVerified('WhatsApp Beta window layout is unsupported.')
    sidebar = min(round(width * .415), 444)
    # Contact info opens in a fixed-width panel on the right, rather than in
    # the center of the chat. Keep the selected range inside that panel.
    number_center = width - min(round(width * .45), 462) // 2
    return ContactLayout((round(sidebar * .58), 123), (150, 273),
                         (sidebar + 90, 70), (number_center - 85, 309),
                         (number_center + 85, 309))


def _visible_window_rect(hwnd):
    import win32gui
    from ctypes import wintypes

    rect = wintypes.RECT()
    dwm = ctypes.windll.dwmapi.DwmGetWindowAttribute
    dwm.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    if dwm(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) == 0:
        return rect.left, rect.top, rect.right, rect.bottom
    return win32gui.GetWindowRect(hwnd)


def _mouse_click(point):
    import win32api
    import win32con
    win32api.SetCursorPos(point)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def _mouse_drag(start, end):
    import win32api
    import win32con
    win32api.SetCursorPos(start)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    try:
        for step in range(1, 11):
            win32api.SetCursorPos((round(start[0] + (end[0] - start[0]) * step / 10),
                                   round(start[1] + (end[1] - start[1]) * step / 10)))
            time.sleep(.01)
    finally:
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def _key_chord(key):
    import win32api
    import win32con
    control = win32con.VK_CONTROL
    win32api.keybd_event(control, 0, 0, 0)
    try:
        win32api.keybd_event(key, 0, 0, 0)
        win32api.keybd_event(key, 0, win32con.KEYEVENTF_KEYUP, 0)
    finally:
        win32api.keybd_event(control, 0, win32con.KEYEVENTF_KEYUP, 0)


def _type_search_number(expected_number: str):
    """Search the saved Swiss number, never an ambiguous display name."""
    import win32api
    import win32con
    from jarvis.integrations.whatsapp_call import normalize_swiss_mobile

    digits = '0' + normalize_swiss_mobile(expected_number)[3:]
    if not re.fullmatch(r'07\d{8}', digits):
        raise ContactNotVerified('The saved phone number is not searchable.')
    for letter in digits:
        key = ord(letter)
        win32api.keybd_event(key, 0, 0, 0)
        win32api.keybd_event(key, 0, win32con.KEYEVENTF_KEYUP, 0)


def _copy_visible_number(hwnd, layout: ContactLayout, left: int, top: int) -> str:
    """Restore all previous clipboard formats; never trust stale clipboard text."""
    import pythoncom
    import pywintypes
    import win32clipboard
    import win32gui

    user32 = ctypes.windll.user32
    pythoncom.OleInitialize()
    original = None
    copy_sequence = None
    copied = ''
    restored = False
    try:
        original = pythoncom.OleGetClipboard()
        before = user32.GetClipboardSequenceNumber()
        if win32gui.GetForegroundWindow() != hwnd:
            raise ContactNotVerified('WhatsApp Beta lost focus before contact verification.')
        start = (left + layout.number_start[0], top + layout.number_start[1])
        end = (left + layout.number_end[0], top + layout.number_end[1])
        _mouse_drag(start, end)
        if win32gui.GetForegroundWindow() != hwnd:
            raise ContactNotVerified('WhatsApp Beta lost focus while selecting the contact number.')
        _key_chord(ord('C'))
        for _ in range(10):
            copy_sequence = user32.GetClipboardSequenceNumber()
            if copy_sequence != before:
                break
            time.sleep(.05)
        else:
            raise ContactNotVerified('WhatsApp did not copy a contact number.')
        for _ in range(10):
            try:
                win32clipboard.OpenClipboard()
                try:
                    copied = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                finally:
                    win32clipboard.CloseClipboard()
                break
            except (OSError, TypeError, pywintypes.error):
                time.sleep(.05)
    finally:
        if original is not None and copy_sequence is not None:
            # Do not overwrite a newer clipboard change made by the user.
            if user32.GetClipboardSequenceNumber() == copy_sequence:
                for _ in range(10):
                    try:
                        pythoncom.OleSetClipboard(original)
                        restored = True
                        break
                    except (OSError, pywintypes.error, pywintypes.com_error):
                        time.sleep(.05)
        pythoncom.CoUninitialize()
    if not restored:
        raise ContactNotVerified('The original clipboard could not be safely restored.')
    return copied


def _verify_boss_contact_sta(expected_number: str) -> bool:
    """Run all UI and clipboard work on one fresh STA thread."""
    import win32gui
    from jarvis.automation.app_launcher import installed_apps, resolve_app
    from jarvis.automation.app_windows import focus_existing, windows
    from jarvis.integrations.whatsapp_call import normalize_swiss_mobile

    matches = resolve_app('WhatsApp Beta', installed_apps())
    if len(matches) != 1 or matches[0]['name'].casefold() != 'whatsapp beta':
        raise ContactNotVerified('One exact WhatsApp Beta installation is required.')
    handles = windows(matches[0])
    if len(handles) != 1 or not focus_existing(matches[0]).get('success'):
        raise ContactNotVerified('One focused WhatsApp Beta window is required.')
    hwnd = handles[0]
    if win32gui.GetForegroundWindow() != hwnd:
        raise ContactNotVerified('WhatsApp Beta is not the foreground window.')
    left, top, right, bottom = _visible_window_rect(hwnd)
    layout = contact_layout(right - left, bottom - top)

    def ensure_focus():
        if win32gui.GetForegroundWindow() != hwnd:
            raise ContactNotVerified('WhatsApp Beta lost focus.')

    def click(point):
        ensure_focus()
        _mouse_click((left + point[0], top + point[1]))

    click(layout.search)
    ensure_focus()
    _key_chord(ord('A'))
    ensure_focus()
    _type_search_number(expected_number)
    time.sleep(.35)
    click(layout.first_result)
    time.sleep(.2)
    click(layout.contact_header)
    time.sleep(.2)
    copied = _copy_visible_number(hwnd, layout, left, top)
    try:
        return normalize_swiss_mobile(copied) == normalize_swiss_mobile(expected_number)
    except ValueError:
        return False


def verify_boss_contact(expected_number: str) -> bool:
    """Open Boss's contact card and verify its number without reusing COM state."""
    result = []
    def work():
        try:
            result.append((True, _verify_boss_contact_sta(expected_number)))
        except BaseException as exc:
            result.append((False, exc))
    with _UI_LOCK:
        worker = threading.Thread(target=work, name='JarvisWhatsAppContact')
        worker.start()
        worker.join()
    if not result:
        raise ContactNotVerified('WhatsApp contact verification did not finish.')
    succeeded, value = result[0]
    if not succeeded:
        raise value
    return value
