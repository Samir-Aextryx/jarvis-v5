"""Windows-native desktop and process helpers."""
import asyncio
import base64
import ctypes
from ctypes import wintypes
import io
import shutil
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit


async def open_browser(url, browser="chrome"):
    if urlsplit(url).scheme not in {"http", "https", "file"}:
        return {"success": False, "confirmation": "Unsupported URL scheme."}
    ok = await asyncio.to_thread(webbrowser.open, url)
    return {"success": ok, "confirmation": "Browser geöffnet." if ok else "Browser konnte nicht geöffnet werden."}


async def open_terminal():
    executable = shutil.which("powershell.exe")
    if not executable:
        return {"success": False, "confirmation": "PowerShell nicht gefunden."}
    args = [executable, "-NoLogo", "-NoExit"]
    subprocess.Popen(args, creationflags=subprocess.CREATE_NEW_CONSOLE)
    return {"success": True, "confirmation": "PowerShell ist geöffnet."}


async def open_codex_in_project(project_dir, prompt):
    from jarvis.automation.pc_control import controller, codex_executable, local_path
    try:
        codex_executable()
        local_path(project_dir)
        response = controller._start("code", controller._code, prompt, project_dir)
        return {"success": True, "confirmation": response}
    except (OSError, ValueError, RuntimeError) as exc:
        return {"success": False, "confirmation": str(exc)}


async def prompt_existing_terminal(project_name, prompt):
    return {"success": False, "confirmation": "Das Tippen in fremde Terminalfenster ist unter Windows nicht verfügbar. Verwende den Projektmodus."}


async def get_chrome_tab_info():
    return {"title": "", "url": ""}


def _windows():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    foreground = user32.GetForegroundWindow()
    result = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    @callback_type
    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            size = user32.GetWindowTextLengthW(hwnd)
            if size:
                title = ctypes.create_unicode_buffer(size + 1)
                user32.GetWindowTextW(hwnd, title, size + 1)
                result.append({"app": "Windows", "title": title.value, "frontmost": hwnd == foreground})
        return True
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows(callback, 0)
    return result


async def get_active_windows():
    return await asyncio.to_thread(_windows)


async def get_running_apps():
    return [w["title"] for w in await get_active_windows()]


async def take_screenshot(display_only=True):
    def capture():
        from PIL import ImageGrab
        with io.BytesIO() as output:
            ImageGrab.grab(all_screens=not display_only).save(output, format="PNG")
            return base64.b64encode(output.getvalue()).decode("ascii")
    return await asyncio.to_thread(capture)
