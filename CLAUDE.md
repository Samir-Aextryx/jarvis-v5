# Jarvis v5 — Windows voice assistant

Jarvis v5 is a Windows desktop voice assistant. The UI is voice-first: users speak to Jarvis and hear spoken replies. Settings remain available for setup and configuration.

## Architecture

- Backend: Python 3.12, FastAPI and WebSockets under `jarvis/`.
- Voice input: Windows microphone audio, streaming speech recognition and interrupt handling.
- Responses: OpenAI Responses API; default model `gpt-6-luna`, reasoning effort `low`.
- Speech output: Fish Audio.
- Desktop: Windows app catalog, UI Automation and local PC controls.
- Personal data: local SQLite memory, notes and calendar; optional Google and Outlook integrations.
- Coding handoff: installed Codex app and its signed-in account.
- Frontend: TypeScript, Vite, Electron and the voice orb.

## Development notes

- Keep voice requests on the deterministic local fast path whenever their intent is unambiguous.
- Preserve recipient checks, app identity checks, safe handling of existing drafts and stop/barge-in behavior.
- Do not send messages or modify connected account data unless the user explicitly asked.
- Keep API credentials in Windows Credential Manager.
- Windows is the only supported runtime platform. Do not add macOS or Linux branches or integrations.
- Jarvis runs only from source: stock Electron starts `desktop/`, which starts the backend with the venv Python; user data stays in `Documents\Jarvis v5\config`. Source changes are live after restarting Jarvis. `scripts/install.ps1` sets up the venv, frontend build, Electron and the desktop shortcut. Do not add an own packaged or compiled executable: Smart App Control blocks unsigned executables, and it must never be changed.
- Keep responses concise and in English.
