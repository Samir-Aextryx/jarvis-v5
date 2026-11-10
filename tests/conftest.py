"""Shared guards: tests must not touch the developer's real accounts or data."""
from unittest.mock import AsyncMock, patch

import atexit
import os
import shutil
import tempfile

import pytest

# Must happen before any test module imports jarvis.server: runtime_paths reads
# JARVIS_DATA_DIR at import time. Without this, importing the app writes to the
# real memory database, MEMORY.md and the developer's .env/vault.
_TEST_DATA_DIR = tempfile.mkdtemp(prefix='jarvis-tests-')
os.environ['JARVIS_DATA_DIR'] = _TEST_DATA_DIR
atexit.register(shutil.rmtree, _TEST_DATA_DIR, ignore_errors=True)

from jarvis.integrations import credentials_vault


class _MemoryVault:
    """Process-local stand-in for Windows Credential Manager."""

    def __init__(self):
        self.values = {}

    def get_password(self, service, user):
        return self.values.get((service, user))

    def set_password(self, service, user, value):
        self.values[(service, user)] = value

    def delete_password(self, service, user):
        self.values.pop((service, user), None)


# Installed before jarvis.core.auth imports get_vault, so auth_token() never
# creates a real Windows credential during the test run.
credentials_vault._vault_instance = _MemoryVault()


@pytest.fixture(autouse=True)
def _no_live_account_access():
    # Starting the app in a test must neither ask OpenAI whether the stored key is valid
    # nor launch Outlook and scan the real inbox through the urgent-mail watcher.
    with patch('jarvis.server.openai_key_rejected', new=AsyncMock(return_value=False)), \
         patch('jarvis.integrations.urgent_mail.urgent_mail_monitor.run', new=AsyncMock()):
        yield
