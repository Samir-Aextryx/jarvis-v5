"""Hand a prompt to the installed Claude Desktop app through its documented claude:// links."""
import os
import winreg
from urllib.parse import quote

# https://support.claude.com/en/articles/14729294-open-claude-desktop-with-a-link
# Claude Desktop prefills the composer and leaves sending to the user; longer text is truncated.
PROMPT_LIMIT = 14000
CHAT_LINK = 'claude://claude.ai/new?q='
CODE_LINK = 'claude://code/new?q='


def claude_link_available():
    """Check the registered handler first; an unknown scheme opens a Windows store dialog."""
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r'claude\shell\open\command'))
        return True
    except OSError:
        return False


def claude_prompt_link(prompt, *, code=False):
    prompt = prompt.strip() if isinstance(prompt, str) else ''
    if not prompt or len(prompt) > PROMPT_LIMIT or any(ord(char) < 32 and char not in '\n\r\t' for char in prompt):
        raise ValueError('Please give me a prompt of at most 14,000 characters for Claude.')
    # Everything is percent-encoded, so spoken text can never add link parameters.
    return (CODE_LINK if code else CHAT_LINK) + quote(prompt, safe='')


def open_claude_prompt(prompt, *, code=False):
    """Open a new Claude chat or Claude Code session with the exact prompt prefilled."""
    link = claude_prompt_link(prompt, code=code)
    os.startfile(link)
    where = 'a new Claude Code session' if code else 'a new Claude chat'
    return {'ok': True, 'message': f'Your prompt is ready in {where}. Review it and press Enter to send it.'}
