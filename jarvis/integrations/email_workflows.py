"""Mail-specific routing and observable draft checks, independent of model claims."""
import re
import unicodedata


_BLOCKED_HAENER = re.compile(r'(?<!\w)(?:haener|haner|hener|haenner|hanner)(?!\w)', re.I)
_MAIL_BODY_START = re.compile(r'(?i)\b(?:saying|with\s+(?:the\s+)?(?:text|body)|message\s+is|body:|content:|message:|text:|(?:und|mit)\s+(?:dem\s+)?(?:text|inhalt)|inhalt:|dass)\b')


def _fold_name(value):
    decomposed = unicodedata.normalize('NFKD', str(value or '').casefold())
    return ''.join(char for char in decomposed if not unicodedata.combining(char))


def blocked_email_recipient(recipient, request='', *, reply_to=None):
    """Match Herr Häner despite common German speech-to-text spellings."""
    def has_name(value):
        return bool(_BLOCKED_HAENER.search(_fold_name(value)))

    if has_name(recipient):
        return True
    command = str(request or '')
    body = _MAIL_BODY_START.search(command)
    if body:
        command = command[:body.start()]
    command = _fold_name(command)
    if re.search(r'(?i)\b(?:to|an|dem|den|from|von|reply\s+to|antworte\s+(?:dem\s+)?)\s+(?:(?:herrn?|mr\.?)\s+)?(?:haener|haner|hener|haenner|hanner)\b', command):
        return True
    if isinstance(reply_to, dict) and any(has_name(reply_to.get(key, '')) for key in ('from', 'reply_to', 'name', 'sender')):
        return True
    return False


def ensure_email_recipient_allowed(recipient, request='', *, reply_to=None):
    if blocked_email_recipient(recipient, request, reply_to=reply_to):
        raise ValueError('Sending email to Herr Häner is disabled by your instruction. I did not send it.')


def is_email_request(text):
    if re.match(r'(?i)^(?:reply|antworte)\b', text):
        return True
    # App-opening phrases can contain "Outlook" or "Outlook mail" without
    # asking for a mail operation. Keep those on the local launcher fast path.
    try:
        from jarvis.automation.app_launcher import parse_open_request
        target = parse_open_request(text)
        if isinstance(target, str) and target.casefold() == 'outlook':
            return False
        if isinstance(target, list):
            # The app parser returns a list only for explicit multi-app open
            # commands. Treat those as launches even when Outlook is one item.
            return False
    except (ImportError, AttributeError):
        pass
    starts_mail_action = bool(re.match(
        r"(?i)^(?:open|launch|use|read|check|review|scan|get|fetch|list|show|find|search|write|draft|compose|send|reply|unread|any|what(?:'s|s| is)|öffne|oeffne|benutze|lies|lese|zeige|suche|prüfe|pruefe|schreibe|schreib|verfasse|sende|schicke|schick|versende|antworte|was)\b",
        text))
    has_mail_subject = bool(re.search(
        r'(?i)\b(?:e-?mails?|emails?|mails?|inbox|posteingang|gmail|outlook)\b', text))
    # Provider names alone are enough for imperative requests such as
    # "Check Gmail", but not for informational questions such as "What is Gmail?".
    if re.match(r"(?i)^(?:what(?:'s|s| is)|was)\b", text):
        has_mail_subject = bool(re.search(r'(?i)\b(?:e-?mails?|emails?|mails?|inbox|posteingang)\b', text))
    return bool(starts_mail_action and has_mail_subject
                and not re.fullmatch(r'(?i)(?:open|launch|öffne|oeffne|starte)\s+(?:gmail|outlook)(?:\s+(?:in|on)\s+chrome)?[.!? ]*', text))


def provider_name(value):
    name = value.strip().casefold()
    if name in {'gmail', 'gmail in chrome', 'google mail'}:
        return 'Gmail'
    if name in {'outlook', 'microsoft outlook'}:
        return 'Outlook'
    raise ValueError('Which mail app should I use: Outlook or Gmail?')


def draft_fields(recipient, subject, body, visual=False):
    if not visual:
        # Names and display labels are not a verified delivery address for strict workflows.
        if not isinstance(recipient, str) or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", recipient):
            raise ValueError('What is the recipient\'s exact email address?')
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 200 or any(ord(c) < 32 for c in subject):
            raise ValueError('What subject should I use for the email?')
        if not isinstance(body, str) or not body.strip() or len(body) > 12000 or any(ord(c) < 32 and c not in '\n\r\t' for c in body):
            raise ValueError('What should the email say? You can give me the text or describe what to write.')
        return {'mode': 'draft', 'recipient': recipient, 'subject': subject.strip(), 'body': normalized(body).replace('\t', '    ')}

    # Visual drafting mode: accepts empty or partial recipient/subject/body
    recipient = '' if recipient is None else recipient
    subject = '' if subject is None else subject
    body = '' if body is None else body

    if not isinstance(recipient, str):
        raise ValueError('What is the recipient\'s exact email address?')
    if not isinstance(subject, str):
        raise ValueError('What subject should I use for the email?')
    if not isinstance(body, str):
        raise ValueError('What should the email say? You can give me the text or describe what to write.')

    # Control character validation (prevent header injection, URL splitting, or control corruption)
    if any(ord(c) < 32 or ord(c) == 127 for c in recipient):
        raise ValueError('Recipient contains invalid control characters.')
    if any(ord(c) < 32 or ord(c) == 127 for c in subject):
        raise ValueError('Subject contains invalid control characters.')
    if any((ord(c) < 32 and c not in '\n\r\t') or ord(c) == 127 for c in body):
        raise ValueError('Body contains invalid control characters.')

    # Length limits
    if len(recipient) > 320:
        raise ValueError('Recipient address is too long.')
    if len(subject) > 200:
        raise ValueError('What subject should I use for the email?')
    if len(body) > 12000:
        raise ValueError('What should the email say? You can give me the text or describe what to write.')

    norm_body = normalized(body).replace('\t', '    ') if body.strip() else ''
    return {
        'mode': 'draft',
        'recipient': recipient.strip(),
        'subject': subject.strip(),
        'body': norm_body
    }


def visual_draft_fields(recipient, subject, body):
    """Normalize fields for visual drafting without raising ValueError for missing fields."""
    return draft_fields(recipient, subject, body, visual=True)


def recipient_authorized(recipient, request):
    addresses = re.findall(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", request)
    return recipient.casefold() in {value.casefold() for value in addresses}


def field_kind(node):
    name = node.get('name', '').strip().casefold()
    if node.get('role') not in {'Edit', 'Document'}:
        return None
    if re.fullmatch(r'to|to:|to recipients|recipients?|an|an:|empfänger|empfänger hinzufügen|add recipients', name):
        return 'recipient'
    if re.search(r'\b(subject|betreff|thema)\b', name):
        return 'subject'
    if re.search(r'\b(search|suche|suchen)\b', name):
        return 'query'
    if re.fullmatch(r'message(?: body)?|email body|body|nachricht(?:entext)?|e-mail-text|textkörper|nachricht eingeben|nachrichtentext eingeben', name):
        return 'body'
    return None


def normalized(value):
    return value.replace('\r\n', '\n').replace('\r', '\n').strip()


def verify_draft(nodes, fields, entered):
    """Require all three controls still contain exactly what this run entered."""
    for kind in ('recipient', 'subject', 'body'):
        matches = [n for n in nodes if field_kind(n) == kind and n.get('value_known', True)]
        if len(matches) != 1 or kind not in entered:
            return False
        if matches[0].get('identity', matches[0]['id']) != entered[kind]:
            return False
        if normalized(matches[0].get('value', '')) != normalized(fields[kind]):
            return False
    return True


def check_mail_action(action, node, nodes, mail):
    """Mail mode cannot send, delete, follow mail links, or overwrite a draft."""
    kind = action['action']
    if kind in {'type', 'search'}:
        field = field_kind(node)
        allowed = {'recipient', 'subject', 'body'} if mail['mode'] == 'draft' else {'query'}
        if field not in allowed or (kind == 'search' and field != 'query'):
            raise ValueError('I could not identify the correct email field. Please check the mail window.')
        if not node.get('value_known', True) or node.get('value', '').strip():
            raise ValueError('The email field already contains text or cannot be read. I left it untouched.')
        if action.get('text') != mail[field]:
            raise ValueError('The proposed text differs from the prepared email or search.')
        if mail['mode'] == 'draft':
            # Multiple composers, or text from another draft, must not be mixed.
            for other in ('recipient', 'subject', 'body'):
                matching = [n for n in nodes if field_kind(n) == other]
                if len(matching) != 1:
                    raise ValueError('Please open exactly one new email composer.')
                value = matching[0].get('value', '')
                if not matching[0].get('value_known', True) or (value.strip() and normalized(value) != normalized(mail[other])):
                    raise ValueError('An existing email draft is present. I left it untouched.')
        return
    label = node['name'].strip()
    if kind == 'click' and node['role'] == 'Button' and re.fullmatch(r'(?i)send|senden|abschicken', label):
        if mail.get('submit_allowed') is not True or mail.get('submitted'):
            raise ValueError('Sending requires your explicit instruction and is never repeated automatically.')
        if not verify_draft(nodes, mail, mail.get('entered', {})):
            raise ValueError('The recipient, subject or body changed. Nothing was sent.')
        for other in nodes:
            if re.fullmatch(r'(?i)cc:?|bcc:?|copy|blind copy|kopie|blindkopie', other.get('name','').strip()):
                if not other.get('value_known',True) or other.get('value','').strip():
                    raise ValueError('Additional recipients are present or cannot be verified. Nothing was sent.')
        return

    # A mail subject can itself contain words such as "reply" or "unsubscribe".
    # Selecting its row reads the message; invoking a button is a different action.
    if mail['mode'] == 'read' and node['role'] in {'ListItem', 'DataItem'}:
        return
    if re.search(r'(?i)send|senden|submit|abschicken|delete|löschen|discard|verwerfen|archive|archiv|forward|weiterleiten|reply|antworten|attachment|anhang|upload|download|herunterladen|link|unsubscribe|abmelden', label):
        raise ValueError('This mail workflow only reads messages or prepares a new draft; it does not send or change existing mail.')
    if mail['mode'] == 'draft':
        if node['role'] != 'Button' or not re.fullmatch(r'(?i)compose|verfassen|new (?:mail|message|email)|neue? (?:e-mail|nachricht)|neu', label):
            raise ValueError('Only opening a new email composer is allowed for this draft.')
    elif node['role'] not in {'ListItem', 'DataItem', 'TreeItem'} and not (
        node['role'] == 'Button' and re.fullmatch(r'(?i)search|suchen|suche|older|älter|next page|nächste seite|inbox|posteingang|all mail|alle nachrichten', label)
    ):
        raise ValueError('I can open mail rows and search, but cannot follow links inside messages.')


def visible_mail_text(nodes):
    """Return observed text, never an invented model-only summary."""
    rows = []
    for node in nodes:
        if node['role'] in {'Text', 'Document', 'ListItem', 'DataItem', 'Header'}:
            value = node.get('value') or node.get('name', '')
            if value and value not in rows:
                rows.append(value)
    return '\n'.join(rows)[:10000]


def send_requested(request):
    # Authority comes from the current user's command, never the draft or a model.
    if re.search(r"(?i)\b(?:do not|don't|never|nicht|noch nicht|not yet)\b", request):
        return False
    # Dictated subject or body text ("... und dem Text bitte sende mir ...") is content, never a command.
    command = re.split(r'(?i)\b(?:saying|with\s+(?:the\s+)?(?:body|text|subject)|body:|inhalt:|text:|about how|betreff:|'
                       r'mit\s+(?:dem\s+)?betreff|(?:und|mit)\s+(?:dem\s+)?(?:text|inhalt))\b', request, maxsplit=1)[0]
    command = re.sub(r'"[^"]*"', '', command)
    return bool(re.search(r'(?i)(?:^|\b(?:and|then|und|danach)\s+|\bplease\s+|\bbitte\s+)(?:send|sende|senden|schicke|versende|reply|antworte)\b', command.strip()))
