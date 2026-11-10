"""Fast, explicit website opening without an LLM or shell command."""
import asyncio
import re
import os
import subprocess
from pathlib import Path
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit, quote
from jarvis.voice.speech_language import remember_english

SITES = {"google": "https://www.google.com", "youtube": "https://www.youtube.com",
         "gmail": "https://mail.google.com/", "google mail": "https://mail.google.com/",
         "chatgpt": "https://chatgpt.com/", "chat gpt": "https://chatgpt.com/",
         "github": "https://github.com", "wikipedia": "https://en.wikipedia.org",
         "netflix": "https://www.netflix.com", "twitch": "https://www.twitch.tv"}


def parse_website_request(text):
    text = re.sub(r"(?i)^(?:hey\s+)?jarvis[,\s]+", "", text.strip())
    text = re.sub(r"(?i)^(?:can you|could you|kannst du|könntest du)\s+", "", text)
    text = re.sub(r"(?i)^(?:please|bitte)\s+", "", text)
    match = re.fullmatch(r"(?i)(?:open|öffne|oeffne|besuche|visit|geh auf|gehe auf|go to)\s+(?:(?:die |the )?(?:website|webseite|seite)\s+)?(.+)", text)
    if not match:
        return None
    target = re.sub(r"(?i)^(?:please|bitte)\s+", "", match[1]).strip().rstrip("!")
    target = re.sub(r"(?i)\s+(?:punkt|dot)\s+", ".", target)
    site_name = re.sub(r"(?i)\s+(?:in|on|with|mit)\s+(?:google\s+)?chrome[.!?]*$", "", target).rstrip(".!?").lower()
    if site_name in {'switzerland','schweiz','die schweiz','swiss airspace'}:
        return 'jarvis:switzerland'
    if site_name in {'usa','the usa','die usa','u.s.a','u.s.a.','u s a','us','the us','united states','the united states','united states of america','amerika','america','vereinigte staaten','die vereinigten staaten'}:
        return 'jarvis:usa'
    if site_name in {"god's eye view",'gods eye view','gods eye',"god’s eye view"}:
        return 'jarvis:gods-eye'
    if site_name in {"dashboard", "the dashboard", "das dashboard", "jarvis dashboard", "jarvis v5 dashboard"}:
        return "jarvis:dashboard"
    if site_name in SITES:
        return SITES[site_name]
    if re.match(r"(?i)^(?:[a-z][a-z0-9+.-]*:|www\.|localhost[:/]|[\w-]+\.[\w.-]+)", target):
        return target.rstrip("?") if "://" not in target else target
    return None


def validate_url(target):
    if len(target) > 2048 or any(ord(c) < 32 for c in target) or "\\" in target:
        raise ValueError("Please provide a valid website address.")
    url = target if re.match(r"^[a-z][a-z0-9+.-]*://", target, re.I) else "https://" + target
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("Only HTTP and HTTPS websites without embedded login details can be opened.")
    host = parsed.hostname.encode("idna").decode("ascii")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", host) or ("." not in host and host != "localhost"):
        raise ValueError("Please provide a website domain, such as example.com.")
    port = parsed.port  # Validates the port range.
    netloc = host + (":" + str(port) if port else "")
    return urlunsplit((parsed.scheme, netloc, quote(parsed.path, safe="/%:@-._~!$&'()*+,;="), parsed.query, parsed.fragment))


@lru_cache(maxsize=1)
def chrome_executable():
    candidates = []
    if os.name == "nt":
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe", 0, winreg.KEY_READ | view) as key:
                        candidates.append(winreg.QueryValueEx(key, None)[0])
                except OSError:
                    pass
    for root in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        if os.environ.get(root):
            candidates.append(str(Path(os.environ[root]) / "Google/Chrome/Application/chrome.exe"))
    for candidate in candidates:
        path = Path(candidate.strip('"'))
        if path.name.lower() == "chrome.exe" and path.is_file():
            return str(path)
    raise FileNotFoundError("Google Chrome is not installed.")


def open_in_chrome(url):
    from jarvis.integrations.credentials_vault import child_process_env
    subprocess.Popen([chrome_executable(), "--new-tab", url], shell=False,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     env=child_process_env())


async def open_website(target):
    if target in {'jarvis:switzerland','jarvis:gods-eye','jarvis:usa'}:
        from jarvis.automation.gods_eye import open_map
        return remember_english(await open_map(switzerland=target=='jarvis:switzerland',usa=target=='jarvis:usa'))
    try:
        url = validate_url(target)
        await asyncio.to_thread(open_in_chrome, url)
        return remember_english("Opening " + urlsplit(url).hostname + " in Chrome.")
    except FileNotFoundError:
        chrome_executable.cache_clear()
        return remember_english("I couldn't find Google Chrome. Please install Chrome and try again.")
    except OSError:
        return remember_english("I couldn't start Google Chrome. Please try again.")
    except (ValueError, UnicodeError):
        return remember_english("I couldn't open that address. Please use a valid HTTP or HTTPS website.")
