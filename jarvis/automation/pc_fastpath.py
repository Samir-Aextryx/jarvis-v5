"""Unambiguous commands need neither inference nor a network connection."""
import ntpath
import re


def normalize_request(text):
    for _ in range(4):
        text = re.sub(r"(?i)^(?:(?:hey\s+)?jarvis[, ]+|please\s+|bitte\s+|can you\s+|could you\s+|kannst du\s+)", "", text.strip())
    return text


_MESSAGE_BODY = r'\s+(?:saying|with\s+(?:the\s+)?(?:text|body)|message\s+is|text:|mit\s+(?:dem\s+)?(?:text|inhalt)|dass|:)\s+'
_MESSAGE_APP = r'(?:(?:microsoft\s+)?teams|snapchat|whatsapp)'
_UNSUPPORTED_ACTION = re.compile(
    r'(?i)^(?:delete|remove|erase|uninstall|install|upload|download|attach|'
    r'buy|purchase|pay|checkout|publish|post|cancel|lösche|loesche|löschen|'
    r'lösch|loesch|entferne|entfernen|entfern|deinstalliere|installiere|'
    r'lade\s+hoch|lade\s+herunter|'
    r'hänge\s+an|kaufe|bezahle|veröffentliche|veroeffentliche|poste|kündige|kuendige)\b'
)
_UNSUPPORTED_SECURITY_CHANGE = re.compile(
    r'(?i)^(?:change|reset|set|update|ändere|aendere|setze|aktualisiere)\s+'
    r'(?:(?:my|the|your|mein(?:e|en|em|er)?|dein(?:e|en|em|er)?|das|den|die)\s+)?'
    r'(?:password|passcode|account|security|privacy|permission|payment|billing|'
    r'recovery|two[ -]?factor|2fa|passwort|konto|sicherheit|datenschutz|berechtigung|'
    r'zwei[ -]?faktor)\b'
)
_CALENDAR_OBJECT = re.compile(
    r'(?i)\b(?:calendar|appointment|meeting|event|termin|kalender|besprechung|ereignis)\b'
)
_BODY_START = re.compile(
    r'(?i)\b(?:saying|message\s+is|with\s+(?:the\s+)?(?:text|body|content)|'
    r'body:|content:|text:|mit\s+(?:dem\s+)?(?:text|inhalt)|und\s+(?:text|inhalt)|dass)\b'
)


def unsupported_action_plan(text):
    """Fail fast for UI operations this desktop agent is explicitly not trained to do."""
    text = normalize_request(text)
    # ChatGPT/Codex prompts are the user's requested content, not actions Jarvis
    # should execute in the current app.
    if re.match(r'(?i)^(?:(?:open|launch|öffne|oeffne)\s+)?(?:chat\s*gpt|claude|codex)\b.*\b(?:prompt|tell|ask|sage|schreibe)\b', text):
        return None
    command = _BODY_START.split(text, maxsplit=1)[0]
    command = re.sub(
        r'(?i)^(?:(?:i\s+(?:want|need|would\s+like)\s+you\s+to)|'
        r'(?:ich\s+(?:möchte|moechte|will)\s+(?:dass\s+du\s+)?)|'
        r'(?:please|bitte|could\s+you|would\s+you))\s+', '', command.strip()
    )
    fragments = re.split(r'(?i)\s+(?:and\s+then|then|and|und\s+dann|und|danach)\s+', command)
    for fragment in fragments:
        phrase = fragment.strip(' ,.!?')
        if re.match(r"(?i)^(?:don't|do\s+not|never|not|without|nicht|niemals|kein(?:e|en|er|es)?)\b", phrase):
            continue
        # Existing local/Google calendar workflows handle supported event edits;
        # leave those requests to their dedicated planner for accurate capability checks.
        if _CALENDAR_OBJECT.search(phrase) and re.match(r'(?i)^(?:delete|remove|cancel|lösche|loesche|entferne|storniere|absage)\b', phrase):
            continue
        if _UNSUPPORTED_ACTION.match(phrase) or _UNSUPPORTED_SECURITY_CHANGE.match(phrase):
            return [{'action': 'ask', 'target': '',
                     'content': "I can't do that yet because I haven't been trained for that action."}]
    return None


def message_request_parts(text):
    """Parse one explicitly addressed message, separating command from literal text."""
    text = normalize_request(text).strip()
    app = 'Teams'
    explicit_app = False
    opening = re.match(r'(?is)^(?:open|launch|öffne|oeffne)\s+(' + _MESSAGE_APP + r')\b(?:\s+(?:and|then|und)\s+)?', text)
    if opening:
        name = re.sub(r'(?i)^microsoft\s+', '', opening[1]).casefold()
        app = {'teams': 'Teams', 'snapchat': 'Snapchat', 'whatsapp': 'WhatsApp'}[name]
        explicit_app = True
        text = text[opening.end():]

    action = re.match(r'(?is)^(send|sende|schick(?:e)?|versende|write|draft|compose|schreibe|schreib|verfasse)\s+(?:(?:a|an|eine|einen)\s+)?', text)
    if not action:
        return None
    verb = action[1].casefold()
    rest = text[action.end():]
    prefix = re.match(r'(?is)^(' + _MESSAGE_APP + r')\s+(?:message|messag|text|nachricht)\s+(?:to|an)\s+', rest)
    if prefix:
        name = re.sub(r'(?i)^microsoft\s+', '', prefix[1]).casefold()
        app = {'teams': 'Teams', 'snapchat': 'Snapchat', 'whatsapp': 'WhatsApp'}[name]
        explicit_app = True
        rest = rest[prefix.end():]
    else:
        noun = re.match(r'(?is)^(?:message|messag|text|nachricht)\s+(?:to|an)\s+', rest)
        if not noun:
            return None
        rest = rest[noun.end():]

    body_match = re.search(_MESSAGE_BODY, rest, flags=re.I)
    recipient = (rest[:body_match.start()] if body_match else rest).strip()
    body = rest[body_match.end():].strip() if body_match else ''
    if not body_match:
        recipient = recipient.rstrip('.!? ')
    suffix_app = re.search(r'(?is)\s+(?:on|in|via|über)\s+(' + _MESSAGE_APP + r')\s*$', recipient)
    if suffix_app:
        name = re.sub(r'(?i)^microsoft\s+', '', suffix_app[1]).casefold()
        app = {'teams': 'Teams', 'snapchat': 'Snapchat', 'whatsapp': 'WhatsApp'}[name]
        explicit_app = True
        recipient = recipient[:suffix_app.start()].strip()
    if not recipient or len(recipient) > 80 or not re.fullmatch(r'[\w .@+-]+', recipient, re.UNICODE):
        return None
    if len(body) > 12000 or any(ord(char) < 32 and char not in '\n\r\t' for char in body):
        return None
    return {'app': app, 'recipient': recipient, 'content': body,
            'send_requested': verb in {'send', 'sende', 'schick', 'schicke', 'versende'},
            'explicit_app': explicit_app}


def direct_message_plan(text):
    """Extract an exact one-recipient message without asking a model to rewrite it."""
    parts = message_request_parts(text)
    if not parts or not parts['content']:
        return None
    return {'action':'draft_message','target':parts['app'],
            'recipient':parts['recipient'],'content':parts['content']}


def message_send_requested(text):
    """Only a send verb in the command (before message text) can authorize submission."""
    parts = message_request_parts(text)
    return bool(parts and parts['send_requested'])


def message_clarification_plan(text):
    """Turn a reply to a missing-message question into a literal draft without an LLM."""
    match = re.fullmatch(r'(?is)(.*?)\nUser clarification:\s*(.+)', text.strip())
    if not match:
        return None
    original, content = match[1].strip(), match[2].strip()
    parts = message_request_parts(original)
    if not parts or not parts['explicit_app'] or parts['content'] or not content:
        return None
    if re.fullmatch(r'(?i)(?:send|send it|send the message|sende|sende es|sende sie|abschicken)', content):
        return [{'action':'ask','target':'','content':f'What should I say to {parts["recipient"]}?'}]
    return [{'action':'draft_message','target':parts['app'],
             'recipient':parts['recipient'],'content':content}]


def _explicit_file_read_batch(text):
    """Plan multiple explicitly named local text files for one parallel read."""
    command = re.match(
        r'(?is)^(?:read|lies|lese)\s+(?:(?:both|these|the|die|diese)\s+)?'
        r'(?:files?|dateien)?\s*(.+)$', text.strip())
    if not command:
        return None
    remainder = command[1]
    paths = re.compile(
        r'"(?P<double>[^"\r\n]+)"|\'(?P<single>[^\'\r\n]+)\'|'
        r'(?P<plain>(?:[A-Za-z]:[\\/]|\\\\)[^\s,;]+)')
    matches = list(paths.finditer(remainder))
    if not 2 <= len(matches) <= 4 or remainder[:matches[0].start()].strip():
        return None
    targets = []
    seen = set()
    separators = re.compile(r'(?i)\s*(?:and(?:\s+then)?|then|und(?:\s+(?:dann|danach))?|danach|,)\s*')
    for index, match in enumerate(matches):
        raw = match.group('double') or match.group('single') or match.group('plain')
        target = raw.rstrip('.!?') if match.group('plain') else raw
        if (not ntpath.isabs(target) or target.startswith('\\\\')
                or ntpath.splitext(target)[1].casefold() not in {'.txt','.md','.csv','.py','.js','.ts','.html','.css'}):
            return None
        key = ntpath.normcase(ntpath.normpath(target))
        if key in seen:
            return None
        seen.add(key)
        targets.append({'action':'read_file','target':target,'content':'','recipient':'','subject':''})
        if index:
            gap = remainder[matches[index-1].end():match.start()]
            if not separators.fullmatch(gap):
                return None
    if remainder[matches[-1].end():].strip().strip('.!?'):
        return None
    return targets


def fast_plan(text):
    text = normalize_request(text)
    unsupported = unsupported_action_plan(text)
    if unsupported:
        return unsupported
    clarified_message = message_clarification_plan(text)
    if clarified_message:
        return clarified_message
    message = direct_message_plan(text)
    if message:
        return [message]
    missing = re.fullmatch(r"(?i)(?:open|launch|öffne|oeffne)\s+(snapchat|whatsapp|telegram|teams)\s+(?:(?:and|then|und)\s+)?(?:write|send|schreibe|schreib|sende)\s+(?:(?:a|eine)\s+)?(?:message|messag|text|nachricht)\s+(?:to|an)\s+([\w -]{1,60})[.!?]*",text)
    if missing:
        return [{'action':'ask','target':'','content':f'What would you like to tell {missing[2].strip()}?'}]
    ai_app = r'(?:chat\s*gpt|chatgpt|claude(?:\s+code)?)'
    prompt_verb = r'(?:prompt|prompte|tell|ask|sage?|frage?|schreibe?)'
    # "to fix it", "dass er ...", "er soll ..." introduce the prompt; they are not part of it.
    prompt_link = r'(?:to\s+|that\s+|dass\s+|(?:er|sie|es)\s+soll\s+)?'
    prompt_patterns = (
        r"(?is)(?:open|launch|öffne|oeffne)\s+(?P<app>" + ai_app +
        r")[,:]?\s+(?:(?:and|then|und)\s+)?" + prompt_verb + r"\s+"
        r"(?:(?:it|him|her|ihm|ihr)\s+)?" + prompt_link + r"(?P<content>.+)",
        r"(?is)" + prompt_verb + r"\s+(?P<app>" + ai_app +
        r")[,:]?\s+" + prompt_link + r"(?P<content>.+)",
    )
    for pattern in prompt_patterns:
        spoken_prompt = re.fullmatch(pattern, text)
        if spoken_prompt:
            spoken_app = ' '.join(spoken_prompt['app'].casefold().split())
            content = spoken_prompt['content'].strip().strip(' ,')
            if content and spoken_app.startswith('claude'):
                return [{'action':'claude_prompt',
                         'target':'Claude Code' if spoken_app.endswith('code') else 'Claude', 'content':content}]
            if content:
                return [{'action':'chatgpt_prompt', 'target':'', 'content':content}]
    match = re.fullmatch(r"(?is)(?:save|create|write)\s+(?:a\s+)?file\s+(?:called|named)\s+(.+?)\s+(?:to|on)\s+(?:the\s+)?(?:desktop|desktp)\s+with\s+(?:the\s+)?(?:content|text)\s+(.+)", text)
    if match:
        filename = re.sub(r"(?i)\s+dot\s+", ".", match[1].strip().strip('"'))
        return [{"action": "write_desktop", "target": filename, "content": match[2]}]
    if re.fullmatch(r"(?i)(?:save|create|write)\s+(?:a\s+)?file\s+(?:to|on)\s+(?:the\s+)?(?:desktop|desktp)[.!?]*", text):
        return [{"action": "ask", "target": "", "content": "What filename should I use, and what should the file contain?"}]

    # A fully named batch is safe to read concurrently without planner latency.
    read_batch = _explicit_file_read_batch(text)
    if read_batch:
        return read_batch

    # Explicit local reads need no language-model planning: the path and read-only
    # action are already supplied, and PCControl applies the normal path/type guards.
    read_match = re.fullmatch(
        r"(?is)(?:read|lies|lese)\s+(?:(?:me|mir)\s+)?"
        r"(?:(?:the|die|das|eine?)\s+)?(?:file|datei)\s+(.+)", text)
    list_match = None
    for pattern in (
        r"(?is)(?:list|liste)\s+(?:(?:the|den)\s+)?(?:folder|directory|ordner)\s+(.+)",
        r"(?is)(?:show|display|list)\s+(?:(?:me|the)\s+)*(?:contents|files)\s+(?:of|in)\s+(?:(?:the|folder)\s+)?(.+)",
        r"(?is)(?:zeige|liste)\s+(?:(?:den|die)\s+)?(?:inhalt\s+von|dateien\s+in)\s+(.+)",
    ):
        list_match = re.fullmatch(pattern, text)
        if list_match:
            break
    local_read = (('read_file', read_match[1]) if read_match else
                  ('list_folder', list_match[1]) if list_match else None)
    if local_read:
        action, spoken_path = local_read
        target = spoken_path.strip()
        if target.endswith(('.', '!', '?')):
            target = target[:-1].rstrip()
        target = target.strip('"').strip()
        # A compound instruction needs a planner phase so its next action is not
        # lost by treating the whole sentence as a filename.
        if (not target or re.search(
                r"(?i)\s+(?:and|then|und|danach)\s+(?:open|read|list|write|save|send|schreibe|öffne|lies|liste|zeige)\b",
                target)):
            return None
        return [{'action':action,'target':target,'content':'','recipient':'','subject':''}]

    mail_match = re.fullmatch(r"(?is)(?:open|launch|ffne|oeffne)?\s*(?:(?:write|draft|compose|schreibe|schreib|verfasse)\s+(?:an\s+|a\s+|eine\s+)?(?:email|e-mail|mail|nachricht)\s+(?:to|an)\s+([\w\s@.-]+?)|(?:email|e-mail|mail)\s+([\w\s@.-]+?))(?:\s+(?:saying|with text|mit dem text|mit text|dass|das)\s+(.+))?", text)
    if mail_match:
        name = (mail_match[1] or mail_match[2]).strip()
        body = mail_match[3] or ""
        email = None
        
        import sqlite3
        import os
        db_path = os.path.join(os.path.expanduser('~'), 'Documents', 'Jarvis v5', 'config', 'data', 'personal_memory.db')
        if os.path.exists(db_path):
            try:
                conn = sqlite3.connect(db_path)
                cur = conn.cursor()
                cur.execute('SELECT content FROM facts WHERE content LIKE ? COLLATE NOCASE', (f'%{name}%@%',))
                for row in cur.fetchall():
                    import re as reg
                    emails = reg.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", row[0])
                    if emails:
                        email = emails[0]
                        break
            except Exception:
                pass
                
        if not email:
            import re as reg
            emails = reg.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", name)
            if emails:
                email = emails[0]
            else:
                return [{'action':'ask','target':'','content':f"I don't have {name}'s email address in my memory. What is it?"}]
                
        if not body:
            return [{'action':'ask','target':'','content':f"What should I write to {name}?"}]
            
        return [{'action':'draft_email','target':'Gmail','recipient':email,'subject':f'Message for {name}','content':body}]

    return None
