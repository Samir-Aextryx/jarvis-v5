import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import jarvis.integrations.credentials_vault as credentials_vault


class CredentialsVaultTests(unittest.TestCase):
    def test_default_llm_client_uses_vault_key(self):
        from jarvis.integrations.llm_client import LLMClient
        with patch('jarvis.integrations.llm_client.get_secure_key', return_value='vault-test-key') as secure:
            self.assertEqual(LLMClient().api_key, 'vault-test-key')
        secure.assert_called_once_with('OPENAI_API_KEY')

    def test_fallback_to_environ(self):
        with patch.object(credentials_vault, "get_vault", return_value=None):
            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env-test"}):
                val = credentials_vault.get_secure_key("OPENAI_API_KEY")
                self.assertEqual(val, "sk-env-test")

    def test_vault_takes_precedence(self):
        mock_vault = MagicMock()
        mock_vault.get_password.return_value = "sk-vault-secret"
        with patch.object(credentials_vault, "get_vault", return_value=mock_vault):
            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env-test"}):
                val = credentials_vault.get_secure_key("OPENAI_API_KEY")
                self.assertEqual(val, "sk-vault-secret")

    def test_migration_from_env_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            env_file = tmppath / ".env"
            env_file.write_text(
                "OPENAI_API_KEY=sk-test-migrate-openai\n"
                "FISH_API_KEY=sk-test-migrate-fish\n"
                "USER_NAME=samir\n"
            )
            mock_vault = MagicMock()
            mock_vault.get_password.return_value = None  # Not yet in vault
            with patch.object(credentials_vault, "DATA_ROOT", tmppath):
                with patch.object(credentials_vault, "get_vault", return_value=mock_vault):
                    credentials_vault.migrate_plaintext_secrets()

                    # Verify keys were set in vault
                    mock_vault.set_password.assert_any_call(
                        credentials_vault._service_name(), "OPENAI_API_KEY", "sk-test-migrate-openai"
                    )
                    mock_vault.set_password.assert_any_call(
                        credentials_vault._service_name(), "FISH_API_KEY", "sk-test-migrate-fish"
                    )

            # Verify .env file no longer has plaintext secrets
            content = env_file.read_text()
            self.assertNotIn("sk-test-migrate-openai", content)
            self.assertNotIn("sk-test-migrate-fish", content)
            self.assertIn("USER_NAME=samir", content)
            self.assertIn("securely stored in Windows Credential Manager", content)

    def test_vault_backed_save_keeps_the_secret_out_of_the_environment(self):
        vault = MagicMock()
        vault.get_password.return_value = "sk-new-secret"
        with patch.dict(os.environ, {"OPENAI_API_KEY": "older-value"}):
            with patch.object(credentials_vault, "get_vault", return_value=vault):
                credentials_vault.set_secure_key(
                    "OPENAI_API_KEY", "sk-new-secret", require_persistence=True
                )
            vault.set_password.assert_called_once()
            self.assertNotIn("OPENAI_API_KEY", os.environ)

    def test_migration_does_not_mirror_secrets_into_the_environment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / ".env").write_text(
                "OPENAI_API_KEY=sk-test-migrate-openai\n"
                "FISH_API_KEY=sk-test-migrate-fish\n"
                "USER_NAME=samir\n"
            )
            mock_vault = MagicMock()
            mock_vault.get_password.return_value = None
            with patch.dict(os.environ, {}, clear=True):
                with patch.object(credentials_vault, "DATA_ROOT", tmppath):
                    with patch.object(credentials_vault, "get_vault", return_value=mock_vault):
                        credentials_vault.migrate_plaintext_secrets()
                self.assertNotIn("OPENAI_API_KEY", os.environ)
                self.assertNotIn("FISH_API_KEY", os.environ)


if __name__ == "__main__":
    unittest.main()
