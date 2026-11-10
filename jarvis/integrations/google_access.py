"""Google desktop OAuth and explicit read commands. Tokens stay in Windows Vault."""
import asyncio
import base64
from email.message import EmailMessage
from jarvis.integrations.email_workflows import draft_fields, recipient_authorized, send_requested, ensure_email_recipient_allowed
from datetime import datetime, timezone
import hashlib
import json
import logging
import re
import threading
import time
import webbrowser

import httpx
import requests
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from keyring.backends.Windows import WinVaultKeyring
from jarvis.core.runtime_paths import DATA_ROOT
from html.parser import HTMLParser
from jarvis.integrations.http_clients import http_client


class _MailText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.hidden += 1
        if tag in {'br', 'p', 'div', 'li'}:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def mail_body(payload):
    """Decode inline text only; never fetch attachments or remote HTML resources."""
    plain, html = [], []
    def visit(part, depth=0):
        if depth > 15 or part.get('filename'):
            return
        data = part.get('body', {}).get('data', '')
        if data and len(data) <= 500000 and part.get('mimeType') in {'text/plain', 'text/html'}:
            try:
                value = base64.urlsafe_b64decode(data + '=' * (-len(data) % 4)).decode('utf-8', errors='replace')
                (plain if part['mimeType'] == 'text/plain' else html).append(value)
            except (ValueError, TypeError):
                pass
        for child in part.get('parts', [])[:30]:
            visit(child, depth + 1)
    visit(payload)
    if plain:
        return '\n'.join(plain).strip()[:10000]
    parser = _MailText()
    parser.feed('\n'.join(html))
    return ''.join(parser.parts).strip()[:10000]

SCOPES = {
    "calendar_write": "https://www.googleapis.com/auth/calendar.events",
    "gmail_send": "https://www.googleapis.com/auth/gmail.send",
    "gmail_drafts": "https://www.googleapis.com/auth/gmail.compose",
    "gmail": "https://www.googleapis.com/auth/gmail.readonly",
    "calendar": "https://www.googleapis.com/auth/calendar.readonly",
    "drive": "https://www.googleapis.com/auth/drive.readonly",
    "tasks": "https://www.googleapis.com/auth/tasks.readonly",
    "contacts": "https://www.googleapis.com/auth/contacts.readonly",
}
WEB_APPS = {
    "gmail": "https://mail.google.com/", "google calendar": "https://calendar.google.com/",
    "google kalender": "https://calendar.google.com/", "google drive": "https://drive.google.com/",
    "google docs": "https://docs.google.com/", "google sheets": "https://sheets.google.com/",
    "google slides": "https://slides.google.com/", "google keep": "https://keep.google.com/",
    "google maps": "https://maps.google.com/", "google photos": "https://photos.google.com/",
    "google kontakte": "https://contacts.google.com/", "google contacts": "https://contacts.google.com/",
    "youtube": "https://www.youtube.com/",
}


class GoogleAccess:
    def __init__(self, root=DATA_ROOT, vault=None):
        self.vault = vault or WinVaultKeyring()
        self.service = "Jarvis-v5-Google-" + hashlib.sha256(str(root).encode()).hexdigest()[:16]
        self.lock = threading.RLock()
        self.connecting = False
        self.error = ""
        self._contact_cache = {}

    def _load(self, name):
        value = self.vault.get_password(self.service, name)
        return json.loads(value) if value else None

    def _save(self, name, value):
        self.vault.set_password(self.service, name, json.dumps(value))

    def configure(self, config, services):
        with self.lock:
            if self.connecting:
                raise ValueError("Finish the current Google sign-in first.")
            client = config.get("installed", {}) if isinstance(config, dict) else {}
            if not re.fullmatch(r"[A-Za-z0-9_-]+\.apps\.googleusercontent\.com", client.get("client_id", "")) or not isinstance(client.get("client_secret"), str) or not 1 <= len(client["client_secret"]) <= 500:
                raise ValueError("Import a Google OAuth client JSON for a Desktop app. An API key is not sufficient.")
            if not services or set(services) - SCOPES.keys():
                raise ValueError("Select supported Google services.")
            # Imported JSON cannot redirect credentials to arbitrary endpoints.
            trusted = {"installed": {"client_id": client["client_id"], "client_secret": client["client_secret"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"]}, "services": sorted(set(services))}
            self._save("client", trusted)
            self._save("tokens", None)
            self._contact_cache.clear()
            self.error = ""
        return self.status()

    def status(self):
        with self.lock:
            config = self._load("client") or {}
            return {"configured": bool(config), "connected": bool(self._load("tokens")),
                "connecting": self.connecting, "services": config.get("services", []), "error": self.error,
                "api_key_set": bool(self._load("api-key"))}

    def save_api_key(self, key):
        key = key.strip()
        if key and not re.fullmatch(r"AIza[A-Za-z0-9_-]{35}", key):
            raise ValueError("Enter a Google API key beginning with AIza (39 characters).")
        with self.lock:
            self._save("api-key", key or None)
        return {"api_key_set": bool(key)}

    def public_youtube(self, limit=5):
        with self.lock:
            key = self._load("api-key")
        if not key:
            raise ValueError("Add a Google API key in Settings > Google first.")
        try:
            # requests does not emit key-bearing URLs in the app's HTTPX request log.
            response = requests.get("https://www.googleapis.com/youtube/v3/videos",
                params={"key": key, "part": "snippet", "chart": "mostPopular", "maxResults": limit},
                timeout=15, allow_redirects=False)
            if response.status_code != 200:
                raise ValueError("YouTube API access failed. Check the key, its restrictions, quota and whether YouTube Data API v3 is enabled.")
            return [{"title": item.get("snippet", {}).get("title", ""), "url": "https://www.youtube.com/watch?v=" + item["id"]} for item in response.json().get("items", [])]
        except requests.RequestException:
            raise ValueError("Google could not be reached. Please try again.") from None

    def connect(self, services=None):
        with self.lock:
            config = self._load("client")
            if not config:
                raise ValueError("Import your Desktop OAuth client JSON first.")
            if self.connecting:
                return self.status()
            if services is not None and sorted(set(services)) != config["services"]:
                self.configure(config, services)
                config = self._load("client")
            self.connecting, self.error = True, ""
        def run():
            try:
                logging.getLogger("google_auth_oauthlib.flow").setLevel(logging.CRITICAL)
                flow = InstalledAppFlow.from_client_config({"installed": config["installed"]},
                    [SCOPES[s] for s in config["services"]], autogenerate_code_verifier=True)
                credentials = flow.run_local_server(host="127.0.0.1", port=0, timeout_seconds=300,
                    authorization_prompt_message=None,
                    success_message="Return to Jarvis to check whether Google sign-in completed.",
                    access_type="offline", prompt="consent")
                granted = set(credentials.granted_scopes or credentials.scopes or [])
                if not set(SCOPES[s] for s in config["services"]).issubset(granted):
                    raise ValueError("Missing permissions")
                with self.lock:
                    self._save("tokens", json.loads(credentials.to_json()))
                    self._contact_cache.clear()
            except Exception:
                self.error = "Google sign-in did not complete. Check the OAuth client, enabled APIs, test users and selected permissions, then retry."
            finally:
                self.connecting = False
        threading.Thread(target=run, daemon=True, name="jarvis-google-login").start()
        return self.status()

    def disconnect(self):
        with self.lock:
            if self.connecting:
                raise ValueError("Finish or cancel Google sign-in first, then disconnect.")
            saved = self._load("tokens")
            self._save("tokens", None)
            self._contact_cache.clear()
            self.error = ""
        if saved:
            try:
                response = httpx.post("https://oauth2.googleapis.com/revoke", data={"token": saved.get("refresh_token") or saved.get("token")}, timeout=15)
                if response.status_code not in {200, 400}:
                    raise RuntimeError()
            except Exception:
                self.error = "Local connection removed. Revoke remaining access in your Google account permissions if needed."
        return self.status()

    def _token(self, service):
        with self.lock:
            config = self._load("client") or {}
            saved = self._load("tokens")
            if not saved or service not in config.get("services", []):
                raise ValueError("Connect " + service + " in Settings > Google first.")
            credentials = Credentials.from_authorized_user_info(saved)
            if not credentials.valid:
                try:
                    credentials.refresh(GoogleRequest())
                except Exception:
                    raise ValueError("Google authorization expired or was revoked. Reconnect in Settings > Google.") from None
                self._save("tokens", json.loads(credentials.to_json()))
            return credentials.token

    def _get(self, client, url, **params):
        response = client.get(url, params=params)
        if not response.is_success:
            raise ValueError(f"Google API returned HTTP {response.status_code}. Check enabled APIs and account permissions in Google Cloud.")
        return response.json()

    async def create_gmail_draft(self, fields, request, *, resolved_recipient=None):
        """Persist a new draft through Gmail; uncertain writes are never replayed."""
        fields = draft_fields(fields.get('recipient'), fields.get('subject'), fields.get('body'))
        if not (recipient_authorized(fields['recipient'], request)
                or resolved_recipient == fields['recipient']):
            raise ValueError('Preparing a draft requires an exact recipient address or one verified Google Contact.')
        token = await asyncio.to_thread(self._token, 'gmail_drafts')
        message = EmailMessage()
        message['To'] = fields['recipient']
        message['Subject'] = fields['subject']
        message.set_content(fields['body'])
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode('ascii')
        try:
            async with http_client(timeout=20) as client:
                response = await client.post('https://gmail.googleapis.com/gmail/v1/users/me/drafts',
                    headers={'Authorization': 'Bearer ' + token}, json={'message': {'raw': raw}})
        except httpx.HTTPError:
            raise ValueError('The Gmail draft result is uncertain. Check Drafts before retrying; I will not create it twice.') from None
        if response.status_code != 200:
            raise ValueError(f'Gmail returned HTTP {response.status_code} while saving the draft. Check Drafts and permissions before retrying; no automatic retry was made.')
        try:
            result = response.json()
            draft_id = result['id']
            message_id = result['message']['id']
            if not all(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,200}', value) for value in (draft_id, message_id)):
                raise ValueError('Invalid identifier')
        except (ValueError, TypeError, KeyError):
            raise ValueError('Gmail did not confirm the saved draft. Check Drafts before retrying; no automatic retry was made.') from None
        return {'id': draft_id, 'message_id': message_id, 'saved': True}

    async def send_gmail(self, fields, request, *, resolved_recipient=None, reply_to=None):
        fields = draft_fields(fields.get('recipient'), fields.get('subject'), fields.get('body'))
        ensure_email_recipient_allowed(fields['recipient'], request, reply_to=reply_to)
        if not send_requested(request) or not (recipient_authorized(fields['recipient'], request) or resolved_recipient == fields['recipient']):
            raise ValueError('Sending requires an explicit request and an exact recipient address supplied by you.')
        token = await asyncio.to_thread(self._token, 'gmail_send')
        message = EmailMessage()
        message['To'] = fields['recipient']
        message['Subject'] = fields['subject']
        payload = {}
        if reply_to:
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', reply_to.get('thread_id', '')) or not re.fullmatch(r'<[^<>\r\n ]+>', reply_to.get('message_id', '')):
                raise ValueError('The original email has no valid reply identifiers. No reply was sent.')
            message['In-Reply-To'] = reply_to['message_id']
            message['References'] = reply_to['message_id']
            payload['threadId'] = reply_to['thread_id']
        message.set_content(fields['body'])
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode('ascii')
        # Never retry a send: timeout/disconnect may occur after Gmail accepted it.
        try:
            async with http_client(timeout=20) as client:
                response = await client.post('https://gmail.googleapis.com/gmail/v1/users/me/messages/send',
                    headers={'Authorization':'Bearer '+token}, json=dict(payload, raw=raw))
        except httpx.HTTPError:
            raise ValueError('The Gmail send result is uncertain. Check Sent mail before retrying; I will not send it twice.') from None
        if response.status_code != 200:
            raise ValueError(f'Gmail returned HTTP {response.status_code} while sending. Check Sent mail and permissions before retrying; no automatic retry was made.')
        try:
            result = response.json()
        except ValueError:
            raise ValueError('Gmail returned an unclear send result. Check Sent mail; no automatic retry was made.') from None
        if not result.get('id'):
            raise ValueError('Gmail did not return a message identifier. Check Sent mail before retrying.')
        return {'id':result['id'], 'accepted':True}

    async def search_gmail(self, query, limit=5):
        """Read matching older or recent mail with the existing readonly permission."""
        if not isinstance(query, str) or len(query) > 500 or any(ord(c) < 32 for c in query):
            raise ValueError('Please use a short mail search, such as from:person@example.com before:2026/09/01.')
        token = await asyncio.to_thread(self._token, 'gmail')
        limit = max(1, min(int(limit), 20))
        base = 'https://gmail.googleapis.com/gmail/v1/users/me/messages'
        async with http_client(timeout=20) as client:
            async def get(url, params):
                response = await client.get(url, params=params, headers={'Authorization': 'Bearer ' + token})
                if response.status_code != 200:
                    raise ValueError(f'Gmail returned HTTP {response.status_code}. Check the Google connection in Settings.')
                return response.json()
            listing = await get(base, {'q': query, 'maxResults': limit})
            rows = listing.get('messages', [])[:limit]
            gate = asyncio.Semaphore(3)
            async def read(row):
                message_id = row.get('id', '')
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', message_id):
                    raise ValueError('Gmail returned an invalid message identifier.')
                async with gate:
                    result = await get(base + '/' + message_id, {'format': 'full'})
                payload = result.get('payload', {})
                headers = {h['name'].casefold(): h['value'] for h in payload.get('headers', [])}
                return {'id': message_id, 'from': headers.get('from', ''), 'to': headers.get('to', ''),
                        'thread_id': result.get('threadId', ''), 'message_id': headers.get('message-id', ''),
                        'reply_to': headers.get('reply-to', ''), 'internal_date': result.get('internalDate', '0'),
                        'subject': headers.get('subject', ''), 'date': headers.get('date', ''),
                        'body': mail_body(payload), 'snippet': result.get('snippet', '')}
            messages = await asyncio.gather(*(read(row) for row in rows))
            messages.sort(key=lambda m: int(m.get('internal_date') or 0), reverse=True)
            return {'service': 'gmail', 'query': query, 'items': messages,
                    'has_more': bool(listing.get('nextPageToken')), 'max_body_characters': 10000}

    async def recent_unread_headers(self, limit=20):
        """Fetch only IDs and mail headers for local alert classification."""
        token = await asyncio.to_thread(self._token, 'gmail')
        base = 'https://gmail.googleapis.com/gmail/v1/users/me/messages'
        headers = {'Authorization': 'Bearer ' + token}
        async with http_client(timeout=15) as client:
            listing = await client.get(base, params={'q': 'is:unread newer_than:2d',
                'maxResults': max(1, min(int(limit), 20))}, headers=headers)
            listing.raise_for_status()
            rows = listing.json().get('messages', [])
            gate = asyncio.Semaphore(3)
            async def read(row):
                message_id = row.get('id', '')
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', message_id):
                    return None
                async with gate:
                    response = await client.get(base + '/' + message_id,
                        params=[('format', 'metadata'), ('metadataHeaders', 'Subject'),
                                ('metadataHeaders', 'From')], headers=headers)
                response.raise_for_status()
                data = response.json()
                fields = {h.get('name', '').casefold(): h.get('value', '')
                          for h in data.get('payload', {}).get('headers', [])}
                return {'source': 'gmail', 'id': message_id,
                        'subject': fields.get('subject', '')[:300],
                        'sender': fields.get('from', '')[:240],
                        'unread': 'UNREAD' in data.get('labelIds', []),
                        'important': 'IMPORTANT' in data.get('labelIds', [])}
            return [item for item in await asyncio.gather(*(read(row) for row in rows)) if item]

    async def search_contacts(self, name, *, use_cache=False):
        """Search contacts; opt-in cache is limited to recent unsent-draft lookups."""
        if not isinstance(name, str) or not 1 <= len(name) <= 100 or any(ord(c)<32 for c in name):
            raise ValueError('Please give a contact name.')
        token = await asyncio.to_thread(self._token, 'contacts')
        cache_key = (hashlib.sha256(token.encode('utf-8')).digest(), name.strip().casefold())
        now = time.monotonic()
        if use_cache:
            with self.lock:
                cached = self._contact_cache.get(cache_key)
                if cached and cached[0] > now:
                    return cached[1]
                self._contact_cache.pop(cache_key, None)
        async with http_client(timeout=15) as client:
            base = 'https://people.googleapis.com/v1/people:searchContacts'
            headers = {'Authorization': 'Bearer ' + token}
            for query in ('', name):
                response = await client.get(base, headers=headers, params={'query':query, 'readMask':'names,emailAddresses', 'pageSize':30})
                if response.status_code != 200:
                    raise ValueError('Could not search Google Contacts. Check the Contacts permission in Settings.')
            result = [row.get('person', {}) for row in response.json().get('results', [])]
        if use_cache:
            with self.lock:
                self._contact_cache[cache_key] = (time.monotonic() + 30, result)
                if len(self._contact_cache) > 64:
                    oldest = min(self._contact_cache, key=lambda key: self._contact_cache[key][0])
                    self._contact_cache.pop(oldest, None)
        return result

    def read(self, service):
        if service not in {'gmail', 'calendar', 'drive', 'tasks', 'contacts'}:
            raise ValueError('This permission is not a Google reading service.')
        token = self._token(service)
        with httpx.Client(headers={"Authorization": "Bearer " + token}, timeout=20) as client:
            if service == "gmail":
                rows = self._get(client, "https://gmail.googleapis.com/gmail/v1/users/me/messages", maxResults=5, q="is:unread").get("messages", [])
                output = []
                for row in rows:
                    message = self._get(client, "https://gmail.googleapis.com/gmail/v1/users/me/messages/" + row["id"], format="metadata")
                    headers = {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}
                    output.append({"from": headers.get("from", ""), "subject": headers.get("subject", ""), "snippet": message.get("snippet", "")})
                return {"service": service, "items": output}
            if service == "calendar":
                result = self._get(client, "https://www.googleapis.com/calendar/v3/calendars/primary/events", maxResults=10, singleEvents="true", orderBy="startTime", timeMin=datetime.now(timezone.utc).isoformat())
                return {"service": service, "items": [{"title": row.get("summary", "Untitled"), "start": row.get("start", {})} for row in result.get("items", [])]}
            if service == "drive":
                result = self._get(client, "https://www.googleapis.com/drive/v3/files", pageSize=20, q="trashed = false", orderBy="modifiedTime desc", fields="files(id,name,mimeType,webViewLink)")
                return {"service": service, "items": result.get("files", [])}
            if service == "tasks":
                result = self._get(client, "https://tasks.googleapis.com/tasks/v1/lists/@default/tasks", maxResults=20, showCompleted="false")
                return {"service": service, "items": [{"title": row.get("title", ""), "due": row.get("due", "")} for row in result.get("items", [])]}
            result = self._get(client, "https://people.googleapis.com/v1/people/me/connections", personFields="names,emailAddresses", pageSize=20)
            return {"service": service, "items": [{"names": row.get("names", []), "emails": row.get("emailAddresses", [])} for row in result.get("connections", [])]}

    @staticmethod
    def parse(text):
        text = re.sub(r"(?i)^(?:hey\s+)?jarvis[,\s]+", "", text).strip().rstrip("!?.")
        if re.fullmatch(r"(?i)(?:show popular youtube videos|zeige beliebte youtube videos)", text):
            return "public", "youtube"
        match = re.fullmatch(r"(?i)(?:open|öffne|starte)\s+(.+)", text)
        if match and match[1].lower() in WEB_APPS:
            return "open", match[1].lower()
        for service, pattern in {
            "gmail": r"(?:read|show|lies|zeige) (?:my |meine |die )?(?:unread |ungelesenen )?(?:gmail|gmail mails|gmail emails|gmail nachrichten)",
            "calendar": r"(?:show|read|zeige|lies) (?:my |meinen |meine |den )?google (?:calendar|kalender|termine)",
            "drive": r"(?:show|list|zeige) (?:my |meine )?google drive(?: files| dateien)?",
            "tasks": r"(?:show|read|zeige|lies) (?:my |meine )?google (?:tasks|aufgaben)",
            "contacts": r"(?:show|list|zeige) (?:my |meine )?google (?:contacts|kontakte)",
        }.items():
            if re.fullmatch(pattern, text, re.I):
                return "read", service
        return None

    async def execute(self, command):
        action, service = command
        if action == "public":
            try:
                return "Popular YouTube videos: " + json.dumps(await asyncio.to_thread(self.public_youtube), ensure_ascii=False)
            except ValueError as exc:
                return str(exc)
        if action == "open":
            from jarvis.automation.website_launcher import open_website
            return await open_website(WEB_APPS[service])
        try:
            result = await asyncio.to_thread(self.read, service)
            return "Your " + service + ": " + (json.dumps(result["items"], ensure_ascii=False) if result["items"] else "No items found.")
        except Exception as exc:
            return str(exc) if isinstance(exc, ValueError) else "Google could not be reached. Check your connection in Settings."


google_access = GoogleAccess()
