# Rust port plan

The Rust backend (`rust/`, built to `desktop/backend/`) replaces the Python
backend (`jarvis/`). It is compiled to WebAssembly and run by stock Electron,
so Jarvis never ships an executable of its own (Smart App Control stays on).
Keep behavior identical to `main`.

Build: `rust/build.ps1` (Docker). `rust/build.ps1 -Check` verifies that the
committed `desktop/backend/` matches the source.

## Done
- HTTP server, WebSocket, auth, CORS/CSP (`server.rs`, `ws.rs`, `auth.rs`, `http.rs`)
- Config, `.env`, Windows Credential Manager (`config.rs`, `vault.rs`, `winapi.rs`)
- Settings, providers, usage (`settings.rs`), LLM client (`llm.rs`)
- Speech output, Fish TTS, streaming speech (`speech.rs`), STT relay (`stt.rs`)
- Phone privacy (`privacy.rs`), personal memory (`personal.rs`)
- Deterministic intents / fast path (`intents.rs`), apps (`apps.rs`),
  websites (`websites.rs`), Win32 desktop bridge (`desktop.rs`)

## Phase 1 — voice turn (done)
- `voice.rs` <- `routers/voice.py`: greeting, turn epochs, stop/barge-in,
  routing order, history + rolling summary, speech output.
- `brain.rs` <- `server.py`: `generate_response`, context cache, weather,
  background lookups, dispatch to Codex projects, project scan.
- `memory.rs` <- `core/memory.py` (SQLite memories, tasks, notes).
- `notes.rs` / `calendar.rs` <- `core/local_notes.py`, `core/local_calendar*.py`,
  `integrations/notes_access.py`.
- `dispatch.rs` <- `core/dispatch_registry.py`; `tasks.rs` <- `core/tasks.py`.

## Phase 2 — REST API (done)
- `routers/system.py`, `personal.py`, `agent_api.py`, `automation.py`,
  `integrations.py`, voice metrics -> `routes.rs`.

## Phase 3 — PC automation (done)
- `pc_control.py`, `local_pc.py`, `pc_fastpath.py` (rest), `app_windows.py`,
  `desktop_agent.py` (UI Automation), `screen.py`, `autonomous_tasks.py`,
  `work_mode.py` (Codex), `planner.py`, `actions.py`, `claude_desktop.py`,
  `windows_support.py`.

## Phase 4 — integrations (done)
- `agent_router.py` (deterministic, without JEV), `email_planner.py`, `email_workflows.py`,
  `email_context.py`, `google_access.py`, `outlook_com.py`, `urgent_mail.py`,
  `whatsapp_call.py` + `whatsapp_beta_ui.py` + `call_audio_bridge.py`,
  `atlassian_access.py`.
- Not verified live yet (needs the user): Google sign-in, Outlook drafts and
  sending, the WhatsApp Beta contact-card check. The virtual-cable probe uses
  winmm (waveIn/waveOut) and is unit-tested only; no VB-Cable is installed here.

## Phase 5 — remove Python
- JEV (TypeSafe) is dropped on purpose: no `jev_client.py`, no JEV key, no
  JEV routing or mail filtering. Remove its docs, tests and UI text with Python.
- Delete `jarvis/`, `pyproject.toml`, `requirements.txt`; port the tests that
  still matter to `cargo test` (runs in the Docker build container).
- `scripts/install.ps1` without venv; README, CLAUDE.md, CI (wasm build +
  reproducibility check).

## Not ported (dead code: nothing imports it)
`core/ab_testing.py`, `core/evolution.py`, `core/learning.py`, `core/monitor.py`,
`core/conversation.py`, `integrations/browser.py`,
`integrations/microsoft_graph_auth.py`, `integrations/microsoft_planner.py`,
`integrations/whatsapp_call_session.py`, `voice/call_conversation.py`,
`voice/silent_call_audio.py`, `core/planner.py` (`start_planning` is never called).

## Behavior changes made on `main` that the port must keep
- God's Eye View removed (no map commands, no map window).
- The solar-system background is removed again (particles orb only).
- Ollama default model `gpt-oss:120b`; for `gpt-oss*` models the reasoning
  level is never `none` (minimum `low`), and Ollama requests that reason get
  +1024 `max_tokens` (done in `llm.rs`).
- Urgent-mail monitor never starts Outlook: it scans Outlook only when
  `GetActiveObject('Outlook.Application')` finds a running instance and
  otherwise skips silently (no error notice, no baseline).
