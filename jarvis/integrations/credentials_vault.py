"""Windows Vault / Credential Manager integration for sensitive API keys."""
import hashlib
import logging
import os
from pathlib import Path
from jarvis.core.runtime_paths import DATA_ROOT

log = logging.getLogger("jarvis.vault")

SECURE_KEY_NAMES = {
    "OPENAI_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY", "OLLAMA_API_KEY", "FISH_API_KEY",
    "JARVIS_AUTH_TOKEN", "CLIENT_SECRET",
}


def child_process_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for launched apps: never inherit the vault-backed secrets."""
    env = {key: value for key, value in os.environ.items() if key not in SECURE_KEY_NAMES}
    if extra:
        env.update(extra)
    return env

_vault_instance = None


def get_vault():
    global _vault_instance
    if _vault_instance is None:
        try:
            from keyring.backends.Windows import WinVaultKeyring
            _vault_instance = WinVaultKeyring()
        except Exception as e:
            log.warning(f"Windows Vault unavailable: {e}")
            _vault_instance = None
    return _vault_instance


def _service_name() -> str:
    return "Jarvis-v5-Keys-" + hashlib.sha256(str(DATA_ROOT).encode()).hexdigest()[:16]


def get_secure_key(key_name: str) -> str:
    """Retrieve sensitive key from Windows Vault, falling back to environment variable."""
    vault = get_vault()
    if vault:
        try:
            val = vault.get_password(_service_name(), key_name)
            if val:
                return val.strip()
        except Exception as e:
            log.debug(f"Vault read failed for {key_name}: {e}")
    return os.environ.get(key_name, "").strip()


def set_secure_key(key_name: str, key_value: str, *, require_persistence: bool = False) -> None:
    """Save a sensitive key to Windows Vault.

    Vault-backed keys are deliberately kept out of ``os.environ``: child
    processes inherit the server environment, and a key that is only in the
    vault cannot leak that way. The environment is used only as a fallback
    when the vault is unavailable or the write failed.
    """
    vault = get_vault()
    if require_persistence and vault is None:
        raise RuntimeError('Windows Credential Manager is unavailable; the API key was not saved.')
    stored = False
    if vault:
        try:
            if key_value:
                vault.set_password(_service_name(), key_name, key_value)
            else:
                try:
                    vault.delete_password(_service_name(), key_name)
                except Exception:
                    if vault.get_password(_service_name(), key_name):
                        raise
            if require_persistence and (vault.get_password(_service_name(), key_name) or '') != key_value:
                raise RuntimeError('Credential persistence could not be verified.')
            stored = True
        except Exception as e:
            if require_persistence:
                raise RuntimeError('Windows Credential Manager could not save the API key.') from None
            log.warning(f"Vault write failed for {key_name}: {e}")
    if stored:
        os.environ.pop(key_name, None)
    else:
        os.environ[key_name] = key_value


def migrate_plaintext_secrets() -> None:
    """Migrate plaintext secrets from .env into Windows Credential Manager and strip them from .env."""
    env_path = DATA_ROOT / ".env"
    if not env_path.exists():
        return
    try:
        content = env_path.read_text(encoding="utf-8")
    except Exception:
        return

    lines = content.splitlines()
    new_lines = []
    migrated = False

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _, v = stripped.partition("=")
            key = k.strip()
            val = v.strip().strip('"').strip("'")
            if key in SECURE_KEY_NAMES and val:
                vault = get_vault()
                if vault is None:
                    new_lines.append(line)
                    continue
                if vault:
                    try:
                        existing = vault.get_password(_service_name(), key)
                        if not existing:
                            vault.set_password(_service_name(), key, val)
                            log.info(f"Migrated {key} from .env to Windows Credential Manager")
                    except Exception:
                        log.warning("Credential migration failed for %s; original retained", key)
                        new_lines.append(line)
                        continue
                # The vault now holds the key; do not keep a second copy in the
                # process environment where launched apps could inherit it.
                os.environ.pop(key, None)
                migrated = True
                new_lines.append(f"# {key} is securely stored in Windows Credential Manager")
                continue
        new_lines.append(line)

    if migrated:
        try:
            env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            log.info("Sanitized plaintext secrets from .env file")
        except Exception as e:
            log.warning(f"Could not rewrite sanitized .env: {e}")
