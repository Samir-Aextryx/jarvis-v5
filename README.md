# Jarvis v5

Windows desktop voice assistant with OpenAI, Gemini, Grok or Ollama Cloud (DeepSeek), Fish Audio, TypeSafe Jev, local memory/calendar/notes, Google integration and verified desktop actions.

Jarvis v5 runs straight from source: stock Electron opens the interface and starts the Python backend from a virtual environment. There is no installer and no packaged `.exe`, so it also starts with Windows Smart App Control turned on.

## Install and start

Requirements: Windows 10 or 11, [Python 3.12](https://www.python.org/downloads/), [Node.js 22.12+](https://nodejs.org/) and Git.

```powershell
git clone <this repository> jarvis-v5
cd jarvis-v5
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

The script creates `.venv`, installs the Python and Node dependencies, builds the frontend, downloads the checksum-verified Electron binary and puts a **Jarvis v5** shortcut on the desktop. Start Jarvis with that shortcut, or with `npm start --prefix desktop`. `scripts\Start-JARVIS.cmd` runs the backend alone and opens the interface in the browser.

Enter API keys in Settings → Voice & AI keys. They are stored in Windows Credential Manager, never in the repository. Your personal data (settings, memory, calendar, logs) lives in `Documents\Jarvis v5\config`, outside the source tree.

To update: `git pull`, then run `scripts\install.ps1` again.

## Source layout

- `jarvis/core/`: settings, memory, calendar, planning, task management, prompts and synchronized shared state.
- `jarvis/voice/`: streaming speech, transcription, turn cancellation and metrics.
- `jarvis/integrations/`: AI providers, Fish-related HTTP transport, Jev, Google, Atlassian and credential storage.
- `jarvis/automation/`: app launching, desktop actions, autonomous jobs and PC control.
- `jarvis/routers/`: voice, personal, integration, automation and system API routers.
- `jarvis/server.py`: application composition and remaining orchestration services. Routers currently use this runtime as a compatibility bridge; further dependency extraction remains worthwhile.
- `frontend/`, `desktop/`: TypeScript interface and Electron shell.
- `scripts/`: install, launch, validation and archive restoration tools.
- `tests/`, `benchmarks/`, `docs/`: automated checks, measurements and documentation.

## Development

Run `.venv\Scripts\python.exe -m pytest -q`. `scripts/check-and-build.ps1` runs the regression suite, TypeScript checks and the frontend build, then `scripts/verify-source.py` starts the backend against a disposable data profile without external API calls. Source changes take effect after restarting Jarvis. Optional browser integration tests require `python -m playwright install chromium`.

## Settings and authentication

Settings → AI Settings → Jev accepts, securely saves, removes and tests the Jev API key. Without a key, `JEV_KEY_MISSING` is shown. The explicit fallback checkbox determines whether another route is allowed; it does not hide this configuration error. The AI providers, Fish Audio and Google have their own settings.

The local auth token is held in Windows Credential Manager. WebSockets authenticate in the protocol handshake, never in the request URL. Normal HTTP APIs use Bearer authentication. The desktop reads the token from the backend process and supplies it through its preload bridge. The browser dashboard receives a single-use, 60-second launch code and exchanges it for a separate dashboard session token that expires after 12 hours; the long-lived token is never written into the page or the link.

Personal data (`.env`, databases, `MEMORY.md`) is runtime data, excluded from Git. Never commit keys or personal records.

See [the user guide](docs/Jarvis-v5-Hilfe.md), [Windows setup](docs/WINDOWS-SETUP.md), [AI providers](docs/AI-PROVIDERS.md) and [the contributing guide](docs/CONTRIBUTING.md).

## ESP32 companion project and demo

- [sketch.ino](sketch.ino): Arduino sketch for the ESP32 companion project
- [ESP32-Praesentation/](ESP32-Praesentation): project presentation
- [solar-system/](solar-system): small browser demo

## License

Jarvis v5 is a modified version of JARVIS by Ethan Rogers. The source is public, but the [license](LICENSE) only allows personal, educational and non-commercial use; commercial use needs a license from the original author. It is therefore source-available, not an OSI-approved open-source license.
