"""Resolve spoken app names against Windows's installed Start-menu catalog."""
import asyncio
import json
import os
import re
import subprocess
import threading
import time
import unicodedata
import winreg
from difflib import SequenceMatcher
from jarvis.core.personal_memory import get_memory
from jarvis.core.runtime_paths import DATA_ROOT
from jarvis.automation.website_launcher import open_in_chrome
from pathlib import Path

_cache = []
_expires = 0.0
_lock = threading.Lock()
_refresh_lock = threading.Lock()
_refreshing = False
_cache_path = DATA_ROOT / "data" / "installed-apps.json"
ALIASES = {
    "teams": ["microsoft teams", "teams"],
    "chat gpt": ["chatgpt"],
    "claude ai": ["claude"], "claude": ["claude"],
    "outlook": ["outlook"],
    "outlook classic": ["outlook classic"],
    "klassisches outlook": ["outlook classic"],
    "whatsapp": ["whatsapp"], "whats app": ["whatsapp"], "whats up": ["whatsapp"],
    "snapchat": ["snapchat"], "snap chat": ["snapchat"],
    "chrome": ["google chrome"], "google chrome": ["google chrome"], "krom": ["google chrome"],
    "vpn": ["proton vpn", "mullvad vpn", "forticlient vpn", "nordvpn", "surfshark", "expressvpn"],
    "v p n": ["proton vpn", "mullvad vpn", "forticlient vpn", "nordvpn", "surfshark", "expressvpn"],
    "proton": ["proton vpn"], "mullvad": ["mullvad vpn"],
    "forti": ["forticlient vpn"], "forticlient": ["forticlient vpn"],
    "calculator": ["rechner", "calculator"], "rechner": ["rechner", "calculator"],
    "notepad": ["editor", "notepad"],
    "edge": ["microsoft edge"], "word": ["word"], "excel": ["excel"],
    "browser": ["google chrome", "microsoft edge", "firefox", "brave"],
    "mein browser": ["google chrome", "microsoft edge", "firefox", "brave"],
}
WEB_FALLBACKS = {
    "chatgpt": "https://chatgpt.com/",
    "chat gpt": "https://chatgpt.com/",
    "claude": "https://claude.ai/",
    "claude ai": "https://claude.ai/",
    "snapchat": "https://web.snapchat.com/",
    "snap chat": "https://web.snapchat.com/",
    "whatsapp": "https://web.whatsapp.com/",
    "whats app": "https://web.whatsapp.com/",
    "whats up": "https://web.whatsapp.com/",
}


def normalize(text):
    text = unicodedata.normalize("NFKD", text.casefold()).replace("ß", "ss")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w ]", " ", text).split())


def _catalog_entries(entries):
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        return []
    apps = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name, app_id = entry.get("Name"), entry.get("AppID")
        if (not isinstance(name, str) or not isinstance(app_id, str)
                or not name.strip() or not app_id.strip() or len(name) > 200 or len(app_id) > 500
                or any(ord(ch) < 32 for ch in name + app_id)):
            continue
        app = {"name": name, "id": app_id}
        direct = _direct_executable(app)
        if direct:
            app["executable"] = direct
        apps.append(app)
    return sorted(apps, key=lambda app: app["name"].casefold())


def _read_catalog():
    try:
        if time.time() - _cache_path.stat().st_mtime > 30 * 86400:
            return []
        return _catalog_entries(json.loads(_cache_path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []


def _query_catalog():
    command = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"
    powershell = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe")
    result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("Windows-App-Liste konnte nicht gelesen werden.")
    entries = json.loads(result.stdout.decode("utf-8-sig") or "[]")
    apps = _catalog_entries(entries)
    if apps:
        try:
            temp = _cache_path.with_suffix(".tmp")
            temp.write_text(json.dumps([{"Name": app["name"], "AppID": app["id"]} for app in apps]), encoding="utf-8")
            os.replace(temp, _cache_path)
        except OSError:
            pass  # A read-only data directory must not prevent launching apps.
    return apps


def installed_apps(refresh=False):
    global _cache, _expires, _refreshing
    with _lock:
        if not refresh and not _cache:
            _cache = _read_catalog()
        if not refresh and _cache:
            if time.monotonic() >= _expires and not _refreshing:
                _refreshing = True
                def update():
                    try:
                        installed_apps(refresh=True)
                    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                        with _lock:
                            global _expires
                            _expires = time.monotonic() + 30
                threading.Thread(target=update, daemon=True).start()
            return list(_cache)
    with _refresh_lock:
        with _lock:
            if not refresh and _cache:
                return list(_cache)
        try:
            apps = _query_catalog()
            with _lock:
                _cache = apps
                _expires = time.monotonic() + 120
            return list(apps)
        finally:
            with _lock:
                _refreshing = False


_SPOKEN_ARTICLE = re.compile(r"^(?:the|my|der|die|das|den|dem|mein(?:e[nmrs]?)?)\s+(?=\S)")


def resolve_app(target, apps):
    query = normalize(target)
    choices = ALIASES.get(query, [query])
    exact = [app for app in apps if normalize(app["name"]) in choices]
    if exact: return exact
    # Match full words only; don't launch a different app from an arbitrary substring.
    matches = [app for app in apps if any(q and f" {q} " in f" {normalize(app['name'])} " for q in choices)]
    if matches: return matches
    # "den Rechner" / "the calculator": drop a spoken article only after the full
    # phrase matched nothing, so titles such as "Die Siedler" resolve as spoken.
    bare = _SPOKEN_ARTICLE.sub("", query)
    return resolve_app(bare, apps) if bare != query else []


def parse_open_request(text):
    text = text.strip().strip(".!?")
    text = re.sub(r"^(?:hey\s+)?jarvis[, ]+", "", text, flags=re.I)
    text = re.sub(r"^(?:(?:kannst|konntest|könntest|würdest) du|can you|could you)\s+", "", text, flags=re.I)
    text = re.sub(r"^bitte\s+|^please\s+", "", text, flags=re.I)
    match = re.fullmatch(r"(?:öffne|offne|oeffne|starte|start|open|launch|öffnen)\s+(.+)", text, re.I)
    if not match:
        match = re.fullmatch(r"(.+?)\s+(?:öffnen|offnen|oeffnen|starten|aufmachen)", text, re.I)
    if not match:
        match = re.fullmatch(r"mach(?:e)?\s+(.+?)\s+auf", text, re.I)
    if not match: return None
    target = re.sub(r"\b(?:bitte|please|für mich|for me|die app|das programm)\b", "", match[1], flags=re.I).strip()
    # "Öffne mir mal Excel": spoken filler before the app name is never part of it.
    target = re.sub(r"(?i)^(?:(?:mir|uns|mal|doch|kurz|einmal)\s+)+", "", target)
    # Voice commands often include a natural article or identify Outlook as
    # the mail app. Canonicalize only the complete Outlook phrase so this
    # never strips meaningful words from arbitrary app names.
    if re.fullmatch(
        r"(?i)(?:(?:the|my|mein(?:e[nr]?)?|das|die|microsoft)\s+)*"
        r"outlook(?:[\s-]+(?:mail|email|e-mail|app|application|programm))?",
        target,
    ):
        target = "Outlook"
    if not target or len(target) > 100: return None
    if re.search(r"\b(?:write|send|prompt|tell|read|check|search|find|review|draft|compose|reply|"
                 r"summari[sz]e|schreibe|schreib|sende|lies|lese|suche|prüfe|pruefe|"
                 r"verfasse|antworte|zusammenfasse)\b", target, re.I):
        return None
    if re.search(r"https?://|www\.|[\w-]+\.(?:com|de|ch|org|net)\b|\b(?:datei|ordner|projekt\w*|website|webseite|file|folder|project)\b", target, re.I):
        return None
        
    targets = [re.sub(r"(?i)^(?:öffne|offne|oeffne|starte|start|open|launch)\s+", "", t.strip()) for t in re.split(r"(?i)\s+and\s+|\s+und\s+|\s+then\s+|\s+danach\s+|,", target) if t.strip()]
    return (targets[0] if len(targets) == 1 else targets) if targets else None


def _launch(app):
    from jarvis.integrations.credentials_vault import child_process_env
    env = child_process_env()
    if app.get("executable"):
        subprocess.Popen([app["executable"]], shell=False, creationflags=subprocess.CREATE_NO_WINDOW, env=env)
        return
    explorer = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "explorer.exe")
    # Only a catalog-derived ID reaches the shell, never the user's raw target or command text.
    subprocess.Popen([explorer, "shell:AppsFolder\\" + app["id"]], shell=False,
                     creationflags=subprocess.CREATE_NO_WINDOW, env=env)


def _direct_executable(app):
    # Resolve verified installed paths once, rather than starting Explorer for Win32 apps.
    app_id = app["id"]
    known_folders = {
        "{6D809377-6AF0-444B-8957-A3773F02200E}": os.environ.get("ProgramW6432", os.environ.get("ProgramFiles", "")),
        "{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}": os.environ.get("ProgramFiles(x86)", ""),
    }
    for marker, directory in known_folders.items():
        if directory and app_id.casefold().startswith(marker.casefold() + "\\"):
            path = Path(directory) / app_id[len(marker) + 1:]
            if path.is_file() and path.suffix.casefold() == ".exe": return str(path)
    executable_name = {"google chrome": "chrome.exe", "outlook classic": "OUTLOOK.EXE"}.get(normalize(app["name"]))
    if executable_name:
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\" + executable_name) as key:
                    path = Path(winreg.QueryValue(key, None).strip('"'))
                    if path.is_file(): return str(path)
            except OSError:
                pass
    return None


def parse_app_preference(text):
    patterns = [r'(?i)^(?:remember(?: that)?[:, ]+)?(.{1,60}?) means (.{1,80}?)[.!?]*$',
                r'(?i)^when i say (.{1,60}?)[, ]+(?:please )?open (.{1,80}?)[.!?]*$',
                r'(?i)^(?:merke? dir[:, ]+)?mit (.{1,60}?) meine ich (.{1,80}?)[.!?]*$']
    for pattern in patterns:
        match=re.fullmatch(pattern,text.strip())
        if match:return match[1].strip(' "'),match[2].strip(' "')
    return None


def suggested_apps(target, apps):
    query=normalize(target).replace(' ','')
    if len(query)<4 or not re.fullmatch(r'[\w .-]{1,100}',target):return []
    ranked=[]
    for app in apps:
        names=[app['name']]+[alias for alias,choices in ALIASES.items() if normalize(app['name']) in choices]
        score=max(SequenceMatcher(None,query,normalize(name).replace(' ','')).ratio() for name in names)
        if score>=.72:ranked.append((score,app))
    return [app for _,app in sorted(ranked,key=lambda item:-item[0])[:3]]


async def save_app_preference(alias, target, memory=None):
    apps=await asyncio.to_thread(installed_apps)
    matches=resolve_app(target,apps)
    if len(matches)!=1:
        return 'Please give the exact installed app name for this preference.'
    await asyncio.to_thread((memory or get_memory()).remember_app,normalize(alias),matches[0])
    return f"Remembered: {alias} means {matches[0]['name']}."


async def open_app(target, candidates=None, *, memory=None, remember_as=None, wait_until_ready=False):
    if isinstance(target, list):
        # Independent app launches should overlap instead of waiting for each
        # process/window check in sequence. gather preserves request order.
        results = await asyncio.gather(*(open_app(t, candidates, memory=memory,
            remember_as=remember_as, wait_until_ready=wait_until_ready) for t in target))
        successes = [res["app"] for res in results if res.get("success")]
        failures = [t for t, res in zip(target, results) if not res.get("success")]
        if successes:
            conf = "Ich öffne " + " und ".join(successes) + "."
            if failures:
                conf += f" Konnte {', '.join(failures)} nicht finden."
            return {"success": not failures, "app": ", ".join(successes), "confirmation": conf}
        return {"success": False, "confirmation": "Keine der Apps konnte gestartet werden."}
    try:
        apps = candidates if candidates is not None else await asyncio.to_thread(installed_apps)
        matches = resolve_app(target, apps)
        memory=memory or get_memory()
        if candidates is None:
            saved=await asyncio.to_thread(memory.app_choice,normalize(target))
            if saved:
                chosen=[app for app in apps if app['id']==saved['app_id']]
                if len(chosen)==1:matches=chosen
        if not matches:
            suggestions=suggested_apps(target,apps)
            if suggestions:
                return {'success':False,'candidates':suggestions,'preference_key':target,
                    'confirmation':'Which app did you mean: '+', '.join(a['name'] for a in suggestions)+'? Please say the app name.'}
            web_url = WEB_FALLBACKS.get(normalize(target)) if candidates is None else None
            if web_url:
                name = next((label for fragment, label in [('chatgpt.com','ChatGPT'), ('claude.ai','Claude'),
                    ('snapchat','Snapchat'), ('whatsapp','WhatsApp')] if fragment in web_url), target)
                try:
                    await asyncio.to_thread(open_in_chrome, web_url)
                except FileNotFoundError:
                    return {'success':False,'confirmation':f"I couldn't find {name} installed or open its web version because Chrome isn't available."}
                return {'success':True,'state':'launching','app':name,
                        'confirmation':f'Opening {name} in Chrome (web version).'}
            return {"success": False, "confirmation": f"Ich finde keine installierte App namens {target}."}
        if len(matches) > 1:
            return {"success": False, "candidates": matches, "preference_key":target,
                    "confirmation": "Which app do you mean: " + ", ".join(app["name"] for app in matches[:8]) + "?"}
        from jarvis.automation.app_windows import focus_existing, verify_started
        existing = await asyncio.to_thread(focus_existing, matches[0])
        if existing:
            if remember_as and existing.get('success'):
                await asyncio.to_thread(memory.remember_app,normalize(remember_as),matches[0])
            return dict(existing, app=matches[0]['name'])
        await asyncio.to_thread(_launch, matches[0])
        if wait_until_ready and not await asyncio.to_thread(verify_started, matches[0]):
            return {'success': False, 'state': 'unverified', 'app': matches[0]['name'],
                    'confirmation': 'Launch requested for ' + matches[0]['name'] + ', but no app window was verified. I did not launch it again.'}
        if remember_as:
            await asyncio.to_thread(memory.remember_app,normalize(remember_as),matches[0])
        state = 'ready' if wait_until_ready else 'launching'
        confirmation = f"Opened {matches[0]['name']}." if wait_until_ready else f"Opening {matches[0]['name']}."
        return {"success": True, "state": state, "app": matches[0]["name"], "confirmation": confirmation}
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        return {"success": False, "confirmation": "Die App konnte nicht gestartet werden. Bitte versuche es erneut."}
