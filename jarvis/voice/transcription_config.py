"""Small, shared vocabulary hints for live, fallback and phone recognition."""

import os
import re


def transcription_keywords():
    common = ['JARVIS', 'ChatGPT', 'Claude', 'Codex', 'Outlook', 'Gmail',
              'E-Mail', 'email', 'Betreff', 'Google Calendar', 'Microsoft Teams',
              'WhatsApp', 'Snapchat', 'Proton VPN', 'Mullvad VPN', 'FortiClient']
    personal = [os.getenv('USER_NAME', '')] + os.getenv('JARVIS_STT_KEYWORDS', '').split(',')
    cleaned = []
    seen = set()
    for term in personal + common:
        if any(char in term for char in '<>\r\n'):
            continue
        term = ' '.join(term.split())
        if term and len(term) <= 64 and term.casefold() not in seen:
            cleaned.append(term)
            seen.add(term.casefold())
        if len(cleaned) >= 24:
            break
    return cleaned


def file_transcription_options():
    model = os.getenv('OPENAI_TRANSCRIBE_MODEL', 'gpt-4o-mini-transcribe')
    data = {'model': model}
    # Empty/auto means detect the original input language. Jarvis's English
    # speaking policy must never force English recognition of German names.
    language = os.getenv('OPENAI_TRANSCRIBE_LANGUAGE', '').strip().lower()
    if re.fullmatch(r'[a-z]{2}', language):
        data['language'] = language
    if model != 'gpt-4o-transcribe-diarize':
        data['prompt'] = ', '.join(transcription_keywords())[:600]
    if model == 'gpt-transcribe':
        data.pop('language', None)
        data['languages[]'] = [language] if re.fullmatch(r'[a-z]{2}', language) else ['en', 'de']
        data['keywords[]'] = transcription_keywords()
    return data
