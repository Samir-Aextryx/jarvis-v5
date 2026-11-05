# Jarvis agent update — 22 September 2026

## Implemented

- Official TypeSafe Jev decision API, fixed HTTPS endpoint, pooled connections, confidence validation, bounded retry for transient errors, temporary failure cooldown and configurable fallback.
- Settings: password input with show/hide, save, connection test, remove, status; Windows Credential Manager storage fails explicitly rather than claiming an unsaved key is secure. Saved secrets are never returned by the settings API.
- Configurable Open Everything Apps (Outlook, Teams, Chrome, ChatGPT by default), large-model identifier, default mail provider, command pause and content-free activity log with clear action.
- Jev command routing and next-tool hints reuse the existing validated executor. Jev does not generate arbitrary executable code or grant send/delete authority.
- Existing process-owned windows are focused before launching. Unverified launches no longer count as success; Windows foreground-focus denial is reported. Process matching supports the named default apps and catalog entries with verified executable paths.
- “What's new?” reads up to 20 recent unread/important Gmail messages and calendar sources concurrently. Jev excludes only confidently promotional previews; uncertain messages stay visible. Unavailable sources and bounded coverage are stated. No mail is marked read, removed or replied to by this command.
- Explicit send commands are enabled again; write/compose requests remain drafts. Complete connected Gmail drafts use the API. Desktop/browser drafts use observed controls rather than treating a mailto launch as proof of completion.
- Google Contacts resolution requires one exact stored contact name and one address. Ambiguity prompts for clarification; no guessed address.
- Gmail reply threading uses a selected message, its thread ID and Message-ID. Context lasts 15 minutes in the current session. Changed or ambiguous recipients are rejected. Uncertain sends are never retried.
- Calendar recognition covers meetings and availability queries. Local availability checks list conflicting events and explicitly state that other calendars were not checked.
- Failed reads can be replanned once; successful operations and uncertain writes are not replayed. Durable task history no longer stores full goals or mail results.
- Optional typed-command panel shares the voice WebSocket pipeline, shows text results, and includes Stop. Existing memory/calendar views and voice pipeline remain.

## Validation

143 automated tests passed across routing, credentials, contact/reply context, app opening, memory/calendar, mail, multi-step execution, desktop safeguards and voice. TypeScript and production frontend build passed. Mail and Jev network tests used mocked responses; no real email was sent. Live Jev quality/latency requires the user's key.

Browser checks verified the new fields, missing-key connection error and persistence of a custom app list. A command reused running default applications and correctly reported Windows focus restrictions. Empty-list storage was verified directly in an isolated settings store. Test data/configuration were isolated from the installed app.

## Not complete yet

The full 39-section specification is not completely implemented. Microsoft Graph OAuth, Outlook API threading, Teams notifications, attachment retrieval, general app closing/window management, and retrieving a completed ChatGPT UI answer are still outstanding. Conditional email-to-calendar creation with conflict resolution is not yet an end-to-end verified workflow. Outlook continues to use its existing accessible desktop controls. There is no claim that every desktop app can be operated.

The September 22 update installed and started successfully: the installed health endpoint and authenticated agent settings both returned HTTP 200. The installed backend SHA-256 matches the new build. The earlier Windows application-control block did not recur; no Windows policy was changed. Enter the new Jev key in Settings → AI Settings → Jev. Gmail reading/sending/drafts/contacts each require their corresponding connected Google permission.

## Main files

New: `jev_client.py`, `agent_settings.py`, `agent_router.py`, `agent_api.py`, `app_windows.py`, `personal_update.py`, `email_context.py`, `frontend/src/agent-settings.ts`, `tests/test_jev_agent.py`, `tests/test_agent_mail_context.py`.

Updated: `server.py`, `app_launcher.py`, `google_access.py`, `email_planner.py`, `email_workflows.py`, `local_pc.py`, `autonomous_tasks.py`, `calendar_workflows.py`, `local_calendar_workflows.py`, frontend main/settings/style/index and relevant regression tests.

## References

- TypeSafe API: https://docs.typesafe.ai/api
- TypeSafe typed decisions: https://docs.typesafe.ai/introduction
- Gmail threading: https://developers.google.com/workspace/gmail/api/guides/threads
- Google Contacts search: https://developers.google.com/people/api/rest/v1/people/searchContacts
