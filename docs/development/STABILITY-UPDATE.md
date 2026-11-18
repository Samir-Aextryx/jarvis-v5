# Stability update — 22 September 2026

## Implemented
- Settings loaded from disk are now validated field by field. Invalid JSON shapes and invalid values fall back to defaults while valid preferences survive. Returned lists cannot mutate application defaults.
- Model identifiers require strings; malformed provider values return a validation error instead of a server error.
- Activity history validates its stored structure, serializes concurrent reads/writes, and uses atomic replacement. A truncated or malformed history no longer breaks the next recorded action.
- Availability questions still reach the calendar, while questions about free software/apps no longer do so merely because they contain “free”.

## Verification
146 focused regression tests passed (53 settings/calendar/memory/voice tests and 93 app/email/autonomy tests). Tests use mocked mail services and do not send real messages. New tests reproduce malformed settings/logs, simultaneous log writes, and incorrect calendar classification.

The initial full unittest discovery ran 234 tests with 11 failures and 3 import errors. Three pytest-based modules cannot import because pytest is absent. Several remaining expectations concern superseded silent-composer, blanket-send-denial and unavailable-local-calendar behavior. The complete suite is NOT green and those tests still need reconciliation with the current product contract. The passing subset does not establish universal correctness.

## Assessment of supplied architecture review
The server remains too large; extracting routers and connection-scoped state should be incremental, with characterization tests before moving voice behavior. A blanket lock around all audio processing could increase latency and is not an appropriate unexamined fix. Existing secret-vault support and release backups must be considered before claiming plaintext-only storage or unprotected overwrite. No compatibility files or user backups were removed in this update.

Still open: a full server/router refactor, per-connection concurrency audit, WebSocket authentication review, frontend splitting, consistent automated pre-release checks, and remaining integration gaps recorded in JEV-AGENT-UPDATE.md. This update does not claim error-free operation or completion of the full architecture proposal.

Changed source files: agent_settings.py, calendar_workflows.py, tests/test_stability_settings.py.
