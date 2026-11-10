# Contributing to JARVIS

Thanks for your interest in contributing! Here's how to get involved.

## Getting Started

1. Fork the repo
2. Clone your fork
3. Follow the setup instructions in the README
4. Make your changes
5. Test that JARVIS still works (start the server, talk to him)
6. Submit a PR

## What We're Looking For

- **Bug fixes** — if something's broken, fix it
- **New integrations** — Spotify, Slack, Notion, etc.
- **Windows desktop automation** — improve installed-app launch, UI Automation and voice task completion
- **Better error handling** — things fail silently in places
- **Voice improvements** — alternative TTS providers, better speech recognition
- **New actions** — extend what JARVIS can do

## Code Style

`server.py` still owns application composition and shared runtime state. Routers
use it as a compatibility bridge; extracting more services is welcome, but keep
the voice loop working.

- Keep voice responses short (1-2 sentences max)
- Don't add dependencies unless necessary
- Run `.venv\Scripts\python.exe -m pytest -q`, `tsc` and the Vite build before a PR
- Keep the personality consistent — British butler, dry wit, economy of language
- Windows is the only supported runtime platform

## What NOT to Do

- Don't add telemetry or analytics
- Don't send data to external services beyond the existing API calls (OpenAI, Fish Audio, Google, Atlassian)
- Don't add features that modify or delete user data in connected services (Mail, Calendar, Notes)
- Don't commit API keys, `.env`, databases or `MEMORY.md`
- Don't break the existing voice loop or the stop/barge-in path

## Reporting Issues

Open an issue with:
- What you expected to happen
- What actually happened
- Your Windows and Python version
- Any error messages from the terminal

## Questions?

Open an issue or start a discussion. Keep it simple.
