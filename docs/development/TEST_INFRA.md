# Test infrastructure

Jarvis v5 has three layers of checks. All of them run without personal data or
real provider keys.

## Rust unit tests

```powershell
rust\build.ps1 -Test
```

`cargo test --lib` runs natively inside the Docker build container. The tests
sit next to the code they check (`#[cfg(test)] mod tests` in `rust/src/*.rs`)
and cover the pure logic that carries Jarvis's safety rules:

- Recipient and draft handling: mail commands, explicit send detection,
  draft-field validation, Outlook/Gmail address checks
- App identity: app resolution, aliases and full-word matching
- Voice routing: transcript guards, call-request and urgent-mail parsing
- Personal data: urgent-mail state migration, WhatsApp contact normalization,
  Atlassian output parsing

Code that needs the Windows host (sockets, files, PowerShell bridge, COM, UI
Automation) is not unit-tested; the smoke checks below exercise it.

## Frontend checks

`tests/*.cjs` are plain Node scripts for the voice-activity, PCM capture and
playback, streaming and orb modules. `scripts/check-and-build.ps1` runs each
of them, plus `tsc` and the Vite build.

## Backend smoke check

`scripts/verify-source.cjs` loads the built WebAssembly backend with
`desktop/host.cjs` exactly as Electron does, but against a disposable data
folder. It checks authentication, assets, settings, memory and the calendar,
then removes the temporary auth token from Windows Credential Manager.

`scripts/check-and-build.ps1` runs the Rust tests, the reproducible-build
check, the frontend checks and this smoke check in that order.

## Not covered automatically

Google sign-in, Outlook drafts and sending, and the WhatsApp Beta contact-card
check act on real accounts or apps and are verified by hand.
