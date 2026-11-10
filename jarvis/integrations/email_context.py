"""Short-lived, per-conversation mail selection and evidence-based addressing."""
from email.utils import parseaddr, getaddresses
import re
import time


class MailContext:
    def __init__(self):
        self.messages = []
        self.selected = None
        self.expires = 0

    def record(self, items, request):
        self.messages = items[:20]
        self.selected = items[0] if items and (len(items)==1 or re.search(r'(?i)\b(latest|newest|last|neueste|letzte)\b', request)) else None
        self.expires = time.monotonic()+900

    def reply_target(self, request):
        if time.monotonic() > self.expires or not self.selected:
            raise ValueError('Which email should I reply to? Find or read the specific email first.')
        row = self.selected
        addresses = getaddresses([row.get('reply_to') or row.get('from', '')])
        if len(addresses) != 1 or not re.fullmatch(r'[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+',addresses[0][1]):
            raise ValueError('The reply recipient is unclear. Please specify the address.')
        # A new named recipient must match this conversation; pronouns may reuse it.
        name = re.search(r'(?i)\breply to\s+(.+?)(?:\s+and\b|\s+saying\b|$)',request)
        if name and name[1].strip().casefold() not in {'him','her','them','it','that email','this email'}:
            candidate=name[1].strip().casefold()
            if candidate not in {addresses[0][0].casefold(),addresses[0][1].casefold()}:
                raise ValueError('The named recipient does not match the selected email. Please find that conversation first.')
        return addresses[0][1], row


async def resolve_contact(name, request, google, *, use_cache=False):
    if not name or not re.search(r'(?i)(?<!\w)'+re.escape(name)+r'(?!\w)',request):
        raise ValueError('Please specify the recipient name or exact address.')
    if '@' in name:
        return name
    people = await google.search_contacts(name, **({'use_cache': True} if use_cache else {}))
    addresses=set()
    for person in people:
        names=[n.get('displayName','').casefold() for n in person.get('names',[])]
        # Require a full stored name, not a fuzzy prefix, before sending.
        if name.casefold() in names:
            addresses.update(e.get('value','') for e in person.get('emailAddresses',[]))
    if len(addresses)!=1:
        raise ValueError('I could not identify one exact contact address. Please give the full name or email address.')
    return addresses.pop()
