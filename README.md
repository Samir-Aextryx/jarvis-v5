# Jarvis v5

**A voice-first AI assistant for your Windows PC.** You speak, Jarvis listens, acts and answers out loud. It remembers what matters to you, keeps your calendar and notes, works with your email, opens apps and websites, and carries out desktop tasks, with every action checked before it runs.

## What Jarvis can do

- **Talk naturally.** Streaming speech recognition, a natural voice from Fish Audio and short spoken replies. Interrupt Jarvis at any moment and it stops talking and listens.
- **Choose your AI: cloud or local.** Use OpenAI, Google Gemini, xAI Grok or Ollama Cloud with your own API key, or run a model on your PC. For local AI, Jarvis installs the free, signed Ollama app and downloads GGUF models straight from Hugging Face: pick a recommended model or search Hugging Face in the app. Clear requests skip the AI entirely and run on a fast local path.
- **Guided setup.** On first start, a short setup assistant asks for your name, lets you choose cloud or local AI and takes the keys for OpenAI, Fish Audio and the other providers, checking each key before saving it.
- **Remember and organize.** Personal memory, calendar and notes live in local SQLite databases on your PC.
- **Handle email.** Read, search and draft in Gmail and Classic Outlook. Jarvis sends only when you explicitly ask, and it alerts you to new urgent mail.
- **Use your Google account.** Calendar, Gmail, Contacts, Drive and Tasks, connected with your own sign-in.
- **Open apps and websites.** Launch installed apps and sites by voice; Jarvis learns the names you use.
- **Control the desktop.** Files, drives and Microsoft Defender scans, plus multi-step tasks in Windows apps through UI Automation.
- **Hand off coding work.** Send coding tasks to the Codex app and get spoken updates when they finish.

## Safe by design

- **Nothing is sent without you.** Messages go out and account data changes only on an explicit request, after recipient and app-identity checks. Existing drafts are never overwritten.
- **Content stays content.** Text in emails, web pages or apps never becomes a command, and speech is never run through a shell.
- **Your keys and data stay local.** API keys are stored in Windows Credential Manager; personal data stays in `Documents\Jarvis v5\config`, outside the source tree.
- **Locked-down local API.** All API calls beyond a health check need a local auth token, and WebSockets never carry it in the URL.

## How it runs

Jarvis v5 runs straight from source. Stock Electron opens the interface and runs the backend, which is written in Rust and compiled to WebAssembly (`desktop/backend`, committed). There is no packaged `.exe` of its own, so Jarvis also starts with Windows Smart App Control turned on.

## Download the app

No Git, Node.js, Python or Rust needed; Windows 10 or 11 is enough.

1. Download **`Jarvis-v5.x.x-windows.zip`** from the [latest release](https://github.com/Samir-Aextryx/jarvis-v5/releases/latest).
2. Right-click the ZIP, choose **Properties**, tick **Unblock** and select **OK**. Windows marks downloaded files, and this lets the setup run.
3. Extract the ZIP into a folder you keep, for example `Documents\Jarvis-v5`.
4. Double-click **`Install Jarvis.cmd`**. It downloads the official Electron runtime, checks it against a pinned SHA-256, puts a **Jarvis v5** shortcut on your desktop and starts Jarvis. The setup assistant then walks you through the AI choice (cloud or local) and your API keys.

The extracted folder holds just `Install Jarvis.cmd`, this README, the license and the folder `app`, which contains the complete source code and the built interface. There is no executable in it. Every release also offers the plain source code. To update, extract the new release into the same folder and run `Install Jarvis.cmd` again; your data is kept, and files of an older version go to the Recycle Bin.

## Install from source

Requirements: Windows 10 or 11, [Node.js 22.12+](https://nodejs.org/) and Git. Python and Rust are not needed to run Jarvis.

```powershell
git clone <this repository> jarvis-v5
cd jarvis-v5
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

The script installs the Node dependencies, builds the frontend, downloads the checksum-verified Electron binary and puts a **Jarvis v5** shortcut on the desktop. Start Jarvis with that shortcut, or with `npm start --prefix desktop`. `scripts\Start-JARVIS.cmd` starts the same app; `scripts\Stop-JARVIS.ps1` closes it.

On first start the setup assistant asks for your AI choice and API keys; you can change everything later in Settings (tabs for General, AI, Voice, API keys, Accounts, PC & apps, Calls & alerts and System). Keys are stored in Windows Credential Manager, never in the repository. Your personal data (settings, memory, calendar, logs) lives in `Documents\Jarvis v5\config`, outside the source tree.

To update: `git pull`, then run `scripts\install.ps1` again.

## Source layout

- `rust/src/`: the backend. HTTP/WebSocket server and auth, voice turns and speech, settings and AI providers, memory, calendar and notes, Google, Outlook, urgent mail, WhatsApp checks, Atlassian, app launching, UI Automation, PC control and autonomous jobs. `rust/PORTING.md` maps it to the former Python modules.
- `desktop/`: Electron shell. `host.cjs` gives the WebAssembly backend sockets, files, processes and one long-lived PowerShell bridge for Win32, COM and UI Automation; `backend/` is the built backend.
- `frontend/`: TypeScript interface (Vite).
- `scripts/`: install, start, stop, validation and `package-release.ps1`, which builds the download ZIP.
- `Install Jarvis.cmd`: one-click setup for the download package.
- `tests/`, `docs/`: frontend checks and documentation.

## Development

Backend changes need Docker Desktop: `rust\build.ps1` builds `rust/` into `desktop/backend`, `rust\build.ps1 -Test` also runs the Rust unit tests and `-Check` verifies that the committed backend matches the source. `scripts\check-and-build.ps1` runs all of that, the TypeScript checks, frontend tests and build, then `scripts/verify-source.cjs` starts the backend against a disposable data profile without external API calls. Changes take effect after restarting Jarvis.

## Settings and authentication

Settings is one window with tabs. **AI** switches between cloud and local AI and manages local models (download, use, remove, Hugging Face search). **API keys** holds every key with Save, Test and Remove. Changes save automatically. Local models run through Ollama on `127.0.0.1:11434`; nothing is sent to a cloud AI while local AI is selected, while speech recognition and the voice still use OpenAI and Fish Audio.

The local auth token is held in Windows Credential Manager. WebSockets authenticate in the protocol handshake, never in the request URL. Normal HTTP APIs use Bearer authentication. The desktop reads the token from the backend and supplies it through its preload bridge. The browser dashboard receives a single-use, 60-second launch code and exchanges it for a separate dashboard session token that expires after 12 hours; the long-lived token is never written into the page or the link.

Personal data (`.env`, databases, `MEMORY.md`) is runtime data, excluded from Git. Never commit keys or personal records.

See [the user guide](docs/Jarvis-v5-Hilfe.md), [Windows setup](docs/WINDOWS-SETUP.md), [AI providers](docs/AI-PROVIDERS.md) and [the contributing guide](docs/CONTRIBUTING.md). Development notes and earlier reports are in [docs/development](docs/development/).

## License

Jarvis v5 is a modified version of JARVIS by Ethan Rogers. The source is public, but the [license](LICENSE) only allows personal, educational and non-commercial use; commercial use needs a license from the original author. It is therefore source-available, not an OSI-approved open-source license.
