"""Observe process-owned windows, restore existing apps, verify launches."""
import os
from pathlib import Path
import time

PROCESSES = {'outlook': {'olk.exe', 'outlook.exe'}, 'outlook classic': {'outlook.exe'},
             'microsoft teams': {'ms-teams.exe', 'teams.exe'}, 'teams': {'ms-teams.exe', 'teams.exe'},
             'whatsapp': {'whatsapp.root.exe'}, 'whatsapp beta': {'whatsapp.root.exe'},
             'google chrome': {'chrome.exe'}, 'chatgpt': {'chatgpt.exe'}, 'spotify': {'spotify.exe'},
             'paint': {'mspaint.exe'}, 'rechner': {'calculatorapp.exe'}, 'editor': {'notepad.exe'}}


def windows(app):
    import win32gui
    import win32process
    import win32api
    allowed = _allowed_processes(app)
    if not allowed:
        return []
    found = []
    def visit(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        if _window_matches_app(hwnd, app, win32process, win32api):
            found.append(hwnd)
    win32gui.EnumWindows(visit, None)
    return found


def _allowed_processes(app):
    from jarvis.automation.app_launcher import normalize
    allowed = PROCESSES.get(normalize(app['name']), set()).copy()
    if app.get('executable'):
        allowed.add(Path(app['executable']).name.casefold())
    return allowed


def _process_image_path(hwnd, win32process=None, win32api=None):
    """Return the owning executable path, if Windows permits querying it."""
    if win32process is None:
        import win32process
    if win32api is None:
        import win32api
    handle = None
    try:
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        handle = win32api.OpenProcess(0x1000, False, pid)
        # QueryFullProcessImageName supports limited query access.
        import ctypes
        from ctypes import wintypes
        buf = ctypes.create_unicode_buffer(32768)
        size = ctypes.c_ulong(len(buf))
        query = ctypes.windll.kernel32.QueryFullProcessImageNameW
        query.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        query.restype = wintypes.BOOL
        if query(int(handle), 0, buf, ctypes.byref(size)):
            return buf.value.casefold()
    except Exception:
        return None
    finally:
        if handle is not None:
            handle.Close()
    return None


def _process_image_name(hwnd, win32process=None, win32api=None):
    path = _process_image_path(hwnd, win32process, win32api)
    return Path(path).name.casefold() if path else None


def _window_matches_app(hwnd, app, win32process=None, win32api=None):
    """Distinguish Store editions even when their process names are identical."""
    from jarvis.automation.app_launcher import normalize
    if normalize(app['name']) in {'whatsapp', 'whatsapp beta'}:
        path = _process_image_path(hwnd, win32process, win32api)
        if not path or Path(path).name.casefold() not in _allowed_processes(app):
            return False
        package = str(app.get('id', '')).split('_', 1)[0].casefold()
        return bool(package and '\\' + package + '_' in path.replace('/', '\\'))
    return _process_image_name(hwnd, win32process, win32api) in _allowed_processes(app)


def focus_existing(app):
    import win32gui
    import win32con
    import win32process
    foreground = win32gui.GetForegroundWindow()
    if (foreground and win32gui.IsWindowVisible(foreground)
            and _window_matches_app(foreground, app, win32process)):
        return {'success': True, 'state': 'focused',
                'confirmation': 'Focused ' + app['name'] + '.'}
    found = windows(app)
    if not found:
        return None
    hwnd = found[0]
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        focused = win32gui.GetForegroundWindow() == hwnd
    except Exception:
        focused = False
    if not focused:
        # Temporarily join both input queues involved in the foreground switch.
        # Joining only the current and old foreground threads often leaves a
        # packaged app visible in the background when Jarvis runs as a child.
        import ctypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        foreground = win32gui.GetForegroundWindow()
        own_thread = kernel32.GetCurrentThreadId()
        foreground_thread = win32process.GetWindowThreadProcessId(foreground)[0] if foreground else 0
        target_thread = win32process.GetWindowThreadProcessId(hwnd)[0]
        attached = []
        try:
            for thread in {foreground_thread, target_thread} - {0, own_thread}:
                if user32.AttachThreadInput(own_thread, thread, True):
                    attached.append(thread)
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
            win32gui.SetActiveWindow(hwnd)
            win32gui.SetFocus(hwnd)
            focused = win32gui.GetForegroundWindow() == hwnd
        except Exception:
            focused = False
        finally:
            for thread in reversed(attached):
                user32.AttachThreadInput(own_thread, thread, False)
    return {'success': focused, 'state': 'focused' if focused else 'already_running',
            'confirmation': ('Focused ' if focused else 'Already running, but Windows did not allow me to focus ') + app['name'] + '.'}


def verify_started(app, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if windows(app):
            return True
        time.sleep(.025)
    return False
