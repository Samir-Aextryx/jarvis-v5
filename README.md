# Jarvis v5

Windows desktop voice assistant with OpenAI, Gemini, Grok or Ollama Cloud (GPT-OSS 120B), Fish Audio, local memory/calendar/notes, Google integration and verified desktop actions.

Jarvis v5 runs straight from source: stock Electron opens the interface and runs the backend, which is written in Rust and compiled to WebAssembly (`desktop/backend`, committed). There is no installer and no packaged `.exe`, so it also starts with Windows Smart App Control turned on.

## Install and start

Requirements: Windows 10 or 11, [Node.js 22.12+](https://nodejs.org/) and Git. Python and Rust are not needed to run Jarvis.

```powershell
git clone <this repository> jarvis-v5
cd jarvis-v5
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

The script installs the Node dependencies, builds the frontend, downloads the checksum-verified Electron binary and puts a **Jarvis v5** shortcut on the desktop. Start Jarvis with that shortcut, or with `npm start --prefix desktop`. `scripts\Start-JARVIS.cmd` starts the same app; `scripts\Stop-JARVIS.ps1` closes it.

Enter API keys in Settings → Voice & AI keys. They are stored in Windows Credential Manager, never in the repository. Your personal data (settings, memory, calendar, logs) lives in `Documents\Jarvis v5\config`, outside the source tree.

To update: `git pull`, then run `scripts\install.ps1` again.

## Source layout

- `rust/src/`: the backend. HTTP/WebSocket server and auth, voice turns and speech, settings and AI providers, memory, calendar and notes, Google, Outlook, urgent mail, WhatsApp checks, Atlassian, app launching, UI Automation, PC control and autonomous jobs. `rust/PORTING.md` maps it to the former Python modules.
- `desktop/`: Electron shell. `host.cjs` gives the WebAssembly backend sockets, files, processes and one long-lived PowerShell bridge for Win32, COM and UI Automation; `backend/` is the built backend.
- `frontend/`: TypeScript interface (Vite).
- `scripts/`: install, start, stop and validation.
- `tests/`, `docs/`: frontend checks and documentation.

## Development

Backend changes need Docker Desktop: `rust\build.ps1` builds `rust/` into `desktop/backend`, `rust\build.ps1 -Test` also runs the Rust unit tests and `-Check` verifies that the committed backend matches the source. `scripts\check-and-build.ps1` runs all of that, the TypeScript checks, frontend tests and build, then `scripts/verify-source.cjs` starts the backend against a disposable data profile without external API calls. Changes take effect after restarting Jarvis.

## Settings and authentication

The AI providers, Fish Audio and Google have their own settings.

The local auth token is held in Windows Credential Manager. WebSockets authenticate in the protocol handshake, never in the request URL. Normal HTTP APIs use Bearer authentication. The desktop reads the token from the backend and supplies it through its preload bridge. The browser dashboard receives a single-use, 60-second launch code and exchanges it for a separate dashboard session token that expires after 12 hours; the long-lived token is never written into the page or the link.

Personal data (`.env`, databases, `MEMORY.md`) is runtime data, excluded from Git. Never commit keys or personal records.

See [the user guide](docs/Jarvis-v5-Hilfe.md), [Windows setup](docs/WINDOWS-SETUP.md), [AI providers](docs/AI-PROVIDERS.md) and [the contributing guide](docs/CONTRIBUTING.md).

## License

Jarvis v5 is a modified version of JARVIS by Ethan Rogers. The source is public, but the [license](LICENSE) only allows personal, educational and non-commercial use; commercial use needs a license from the original author. It is therefore source-available, not an OSI-approved open-source license.
