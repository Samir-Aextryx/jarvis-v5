# Test infrastructure

Jarvis v5 uses one pytest suite in `tests/`. There is no separate `tests/e2e`
tree; slow and opt-in checks live in `benchmarks/` and `scripts/verify-*.py`.

## Running

```powershell
.venv\Scripts\python.exe -m pytest -q
```

`tests/conftest.py` redirects `JARVIS_DATA_DIR` to a disposable temporary
directory and installs an in-memory credential vault, so a normal test run
never touches the user's real memory database, `.env` or Windows Credential
Manager. Do not import `jarvis.server` before that fixture has run.

## Coverage areas

- Authentication and HTTP boundary: `test_http_auth.py`, `test_refactor_security.py`
- Voice pipeline, barge-in and cancellation: `test_audio_suppression.py`,
  `test_call_*.py`, `test_direct_voice_routing.py`, `test_e2e_pipeline.py`
- Personal data: `test_custom_personal.py`, memory/calendar tests
- Integrations: Google, Outlook, Atlassian, Planner, provider settings
- Automation and desktop actions: `test_desktop_agent.py`, `test_pc_control.py`,
  `test_app_launcher.py`, autonomy and task tests
- Frontend/Electron helpers: `tests/*.cjs` under Node

## Gates

`scripts/check-and-build.ps1` runs pytest, `tsc`, the Vite build and
`scripts/verify-source.py`. The smoke check starts the backend from source, as the
desktop shell does, with a temporary data profile on port 8346, verifies health, 401 handling, bearer auth,
static assets, settings, memory and calendar, and deletes the disposable test
credential afterwards. It makes no external API calls.

## Expectations

- No test may send messages or change connected account data.
- No test may read, print or commit real API keys or personal records.
- Browser/Playwright checks are optional and need `python -m playwright install chromium`.
