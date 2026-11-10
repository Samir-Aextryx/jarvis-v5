# Project: Direct Email Draft Creation in Gmail and Outlook (Silent Execution & Visual Review)

> **Historical plan (Jarvis v4 era).** This document records the original
> milestone plan; it is not a description of the current codebase. Module names
> such as `server.py`, `autonomous_tasks.py` and `email_planner.py` at the
> repository root no longer exist — today's code lives under `jarvis/` (for
> example `jarvis/automation/local_pc.py` and `jarvis/integrations/`). The
> safety rules it describes (no automatic sending, visual draft review) still
> apply.

## Architecture
Jarvis v4/v5 voice and command processing architecture:
1. **Intake & Intent**: `server.py` `/ws/voice` receives client audio/transcript messages, normalizes transcript via `clean_transcript` and `apply_speech_corrections`, detects intents (including `is_pc_request` and `is_email_request`).
2. **Speech Synthesis & TTS Pipeline**: `server.py` (`synthesize_speech`, `stream_speech`), `streaming_voice.py` (`StreamingSpeech`, `PhraseBuffer`), and `speech_language.py` (`english_speech`).
3. **Autonomous Tasks & PC Planning**: `autonomous_tasks.py` (`AutonomousTasks`) and `local_pc.py` (`LocalPC`), delegating email planning to `email_planner.py` (`plan_mail`) and field validation to `email_workflows.py`.
4. **Visual Email Dispatchers**:
   - Gmail: Web compose URL `https://mail.google.com/mail/?view=cm&fs=1&to={to}&su={su}&body={body}` launched in Google Chrome / default browser.
   - Outlook: CLI `OUTLOOK.EXE /c ipm.note /mailto "<mailto_url>"` with fallback to `os.startfile(mailto_url)`.
5. **Safety Guardrails**: Zero automated sending (`send_requested() == False`), visual draft review only.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Empty-Text TTS Guard | Prevent TTS synthesis and 'speaking' state emission when response_text is empty or whitespace in `server.py` and `speech_language.py` | M1 | survey_1 |
| 2 | Canned Voice Confirmation Suppression | Suppress hardcoded announcements ("On it, sir", "Building it now, sir", "Understood, sir") across command start handlers | M1 | survey_1 |
| 3 | Banned Confirmation Phrases Filter | Guard in `synthesize_speech` and `stream_speech` to catch and drop phrases like "I am working on your task", "On it" | M1 | survey_1 |
| 4 | Autonomous Tasks Crash Fix | Fix `UnboundLocalError: asyncio` in `autonomous_tasks.py:50` that triggers fallback audio error announcements | M1 | survey_1 |
| 5 | Silent Email Action Results | Ensure draft action returns empty spoken text (`response_text = ""`) while keeping UI notifications visual | M1 | survey_1 |
| 6 | Relaxed Fastpath Email Planning | Modify `email_planner.py` to avoid blocking commands like "write a mail from gmail" when `@` is omitted | M2 | survey_2 |
| 7 | Visual Draft Field Normalization | Update `draft_fields` / validation in `email_workflows.py` to allow empty or placeholder recipient/subject/body for visual drafts | M2 | survey_2 |
| 8 | Gmail Web Compose Formatting | Generate properly URL-encoded compose URL with `quote_via=urllib.parse.quote` and launch via browser | M2 | survey_2 |
| 9 | Gmail Non-Sending Guardrail | Ensure `create_gmail_draft` remains disabled and no automated sending occurs | M2 | survey_2 |
| 10 | Windows Outlook Registry Discovery | Discover `OUTLOOK.EXE` path in Windows App Paths registry with graceful fallback to protocol handler | M3 | survey_3 |
| 11 | Outlook Compose CLI & Protocol Launch | Launch Outlook compose window using `/c ipm.note /mailto "<mailto_url>"` with `os.startfile` fallback | M3 | survey_3 |
| 12 | Outlook Visual Presentation & Parameters | Pre-fill recipient, subject, and body in Outlook compose inspector without auto-sending | M3 | survey_3 |
| 13 | Outlook Non-Sending Guardrail | Enforce `send_requested == False` and verify compose CLI cannot transmit mail | M3 | survey_3 |
| 14 | E2E Test Suite (Tiers 1-4) | Comprehensive opaque-box test suite for silent execution, Gmail drafting, Outlook drafting, and guardrails | M4 | test_infra |
| 15 | Adversarial Hardening (Tier 5) | White-box adversarial testing, edge cases, special characters, and long text handling | M5 | test_infra |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Audio Announcement Suppression | Features 1, 2, 3, 4, 5: Silence voice confirmations, fix autonomous_tasks.py crash, empty TTS guard, banned phrases filter | none | DONE |
| M2 | Instant Visual Gmail Drafting | Features 6, 7, 8, 9: Relaxed planner and draft fields, Gmail URL compose launcher, visual review | M1 | DONE |
| M3 | Instant Visual Outlook Drafting | Features 10, 11, 12, 13: Outlook compose helper, registry discovery, mailto formatting, visual review | M1 | IN_PROGRESS |
| M4 | E2E Test Suite (Tiers 1-4) | Feature 14: Test infra, test runners, Tier 1-4 test cases for silent execution and visual drafting | none | PLANNED |
| M5 | Final Milestone: E2E Pass & Hardening | Feature 15: 100% pass of E2E suite + Tier 5 adversarial hardening | M1, M2, M3, M4 | PLANNED |

## Interface Contracts
### Email Planner ↔ Local PC
- `plan_mail(request: str) -> List[Dict[str, Any]]`:
  - Returns list of step dicts. For visual draft requests without full parameters, returns `[{'action': 'draft_email', 'target': 'Gmail'|'Outlook', 'recipient': recipient or '', 'subject': subject or '', 'content': body or ''}]` instead of returning an `'ask'` step.
### Local PC ↔ Browser Launcher / Gmail
- Gmail draft url: `https://mail.google.com/mail/?view=cm&fs=1&to={to}&su={su}&body={body}`
- Launch mechanism: `open_in_chrome(url)` with fallback `webbrowser.open(url)`.
- Returns: `{'ok': True, 'message': '...', 'silent': True}`.
### Local PC ↔ Outlook Launcher
- Function: `open_outlook_composer(recipient: str = "", subject: str = "", body: str = "") -> bool`
- Launch mechanism: `OUTLOOK.EXE /c ipm.note /mailto "<mailto_url>"` with fallback `os.startfile(mailto_url)`.
- Returns: `{'ok': True, 'message': '...', 'silent': True}`.
### Speech Synthesis Pipeline
- `synthesize_speech(text: str) -> Optional[bytes]`: Returns `None` immediately if `not text or not text.strip()` or if normalized text matches banned confirmation phrases.
- `stream_speech(ws, text: str, metrics=None) -> bool`: Returns `False` immediately if `not text or not text.strip()` or if normalized text matches banned confirmation phrases.
- `english_speech(text: str, api_key: str) -> str`: Returns `""` immediately if `not text or not text.strip()`.

## Code Layout
- `server.py`: WebSocket handler, intent routing, TTS dispatch, status management.
- `autonomous_tasks.py`: Autonomous task runner, background task lifecycle.
- `speech_language.py`: English speech normalization and translation cache.
- `email_planner.py`: Email command parsing and plan generation.
- `email_workflows.py`: Email validation, draft_fields, intent detection.
- `local_pc.py`: Local PC execution, draft_email dispatcher, Outlook compose launcher.
- `website_launcher.py`: Chrome / browser launcher helpers.
- `tests/`: Existing unit test suite (`test_email_workflows.py`, `test_autonomy.py`, etc.).
- `tests/e2e/`: E2E test suite directory (created by E2E Testing Track).
