# App and email automation latency — 23 September 2026

Plain app-opening voice commands now bypass the remote Jev router when Jev is configured. The missing-Jev error remains visible when no key is configured. The Windows Start-menu catalog is saved under Jarvis's local data directory and refreshed in the background; a refresh no longer holds the lookup lock. Existing windows get a second foreground activation attempt when Windows rejects the first one.

The same direct routing now covers locally recognized websites, screenshots, Google commands and PC commands. A single fully specified email goes straight to the mail executor instead of starting the multi-step autonomous planner. Compound mail tasks still use the planner so reading or opening another app is not silently dropped.

Fully specified Gmail/Outlook requests with an exact address, subject and literal body are planned locally. Sending still requires an explicit send request and the existing field, permission and result checks. Requests that need Jarvis to compose missing content still use the language model. The benchmark does not send email.

On this PC, a fresh Start-menu scan took about 1,170 ms before the change. Loading the saved catalog in a new Python process took about 3 ms. The installed Jarvis backend returned a successful Chrome-focus result in 17–25 ms on warm runs; a direct local run took 43 ms. Planning a fully specified email took 2–4 ms. These measurements cover local command processing and focusing an already running Chrome window. Starting an app that is closed, generating email text, contacting Gmail/Outlook and sending mail depend on Windows or network services and cannot be guaranteed to finish in milliseconds.

The default OpenAI model is now `gpt-6-luna` with `reasoning.effort=low`; both are visible in AI Settings. The installed profile was switched to those values and a live OpenAI Responses API request accepted them. Keys remain in the Windows Credential Manager. Fully specified Outlook sends use the single configured classic Outlook account directly, after Jarvis verifies the user's exact recipient and send request. The Outlook test email to the sole authorized test address was accepted in about 1.9 seconds and appeared once in Sent Items with the intended SMTP recipient; delivery was not independently confirmed. A Teams test message to the sole authorized Teams contact appeared in the conversation and the composer cleared. Teams automation now identifies the chat participant heading separately from repeated sender labels in message history and handles the empty-composer placeholder.

Run `python benchmarks/automation_latency.py --open-chrome` to repeat the installed-app test; omit `--open-chrome` to measure only local mail planning. The full regression run passed 289 tests with 1 skipped. The rebuilt backend was installed into Jarvis v5, and the installed app returned HTTP 200. Gmail is not currently connected in the installed profile; direct Gmail sends require reconnecting it with the send permission.

## Live verification — 24 September 2026

The installed backend binary matches the current build by SHA-256, and its authenticated status reports `gpt-6-luna` with `low` reasoning effort. A read-only OpenAI model lookup confirmed that the configured model is available to this API key.

An authenticated voice-route test for “Open Outlook” took 67 ms from transcript submission to the server's completion event; the already-running Outlook window was observed after 73 ms. The local mail parser classified a complete draft as `draft_email` in 3.8 ms without sending it. These figures show that the deterministic Outlook and complete-mail paths are not the dominant delay.

Three installed-pipeline runs used the same synthetic, non-command audio sample and emitted live partial and final transcripts. Median STT-final time was 872 ms, median first LLM token was 2,525 ms, and median first server PCM arrived at 3,200 ms. The three first-PCM samples were 2,470, 3,200 and 10,065 ms, so network/provider variance is substantial. These measure server output, not sound reaching the speaker. No email or desktop command was executed by these audio tests.

`benchmarks/installed_smoke.py` now accepts `JARVIS_INSTALLED_SMOKE_OUTPUT` so repeat tests can preserve the historical `benchmarks/installed.json` result. The app-open and email regression subset passed 67 tests with 4 subtests. The remaining response delay is mainly in live STT and first-token delivery; reducing the local Outlook path further would have little effect on the measured end-to-end result.

## Fast mail-read planning — 24 September 2026

Simple email reads now bypass the planning model when the command and filters are explicit: sender email address, topic, unread status, ISO date bounds, or the existing unfiltered/latest defaults. German `lies`/`ungelesen` forms are covered. Vague periods such as “old emails,” named senders that need contact lookup, provider conflicts, and compound read-then-write tasks still use the existing planner. A sender domain such as `alex@gmail.com` does not override the configured mail provider.

One hundred local planning runs had a 0.049 ms median and 0.076 ms p95, with zero LLM calls. The full suite passed 375 tests, 1 skipped and 78 subtests; the isolated packaged-backend check passed. The installed backend matches the build by SHA-256 and returned HTTP 200 after restart. The previous backend is preserved in `backup-updates/20260924-215224`.

The installed profile still defaults to Gmail, which is not connected. This planner optimization does not bypass that account requirement; an explicit Outlook request continues to select Outlook.
