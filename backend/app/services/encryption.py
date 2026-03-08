"""Encryption service for sensitive AppSetting values.

Uses Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256).
Encryption key is loaded from the SCHWAB_ENCRYPTION_KEY env var.
"""

import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)

# Keys that must be encrypted at rest
ENCRYPTED_SETTING_KEYS = frozenset({
    "schwab_access_token",
    "schwab_refresh_token",
    "schwab_app_key",
    "schwab_app_secret",
})


class EncryptionKeyMissing(Exception):
    """Raised when SCHWAB_ENCRYPTION_KEY is not set but encryption is required."""
    pass


def get_encryption_key() -> str | None:
    """Return the encryption key from settings, or None if not configured."""
    key = settings.schwab_encryption_key
    return key if key else None


def require_encryption_key() -> str:
    """Return the encryption key or raise EncryptionKeyMissing."""
    key = get_encryption_key()
    if not key:
        raise EncryptionKeyMissing(
            "SCHWAB_ENCRYPTION_KEY env var is required when Schwab tokens exist"
        )
    return key


def _get_fernet(key: str | None = None) -> Fernet:
    """Build a Fernet instance from the given or configured key."""
    k = key or require_encryption_key()
    return Fernet(k.encode() if isinstance(k, str) else k)


def encrypt_value(plaintext: str, key: str | None = None) -> str:
    """Encrypt a plaintext string, returning a base64-encoded Fernet token."""
    f = _get_fernet(key)
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str, key: str | None = None) -> str:
    """Decrypt a Fernet token back to plaintext."""
    f = _get_fernet(key)
    return f.decrypt(ciphertext.encode()).decode()


def is_encrypted(value: str, key: str | None = None) -> bool:
    """Check whether a value is already Fernet-encrypted with the current key.

    Attempts decryption — if it succeeds, the value is encrypted.
    """
    if not value:
        return False
    try:
        k = key or get_encryption_key()
        if not k:
            return False
        f = Fernet(k.encode() if isinstance(k, str) else k)
        f.decrypt(value.encode())
        return True
    except (InvalidToken, Exception):
        return False


def migrate_plaintext_tokens(db) -> int:
    """Encrypt any plaintext schwab_* values in-place. Returns count migrated."""
    from app.models.database import AppSetting

    key = get_encryption_key()
    if not key:
        return 0

    migrated = 0
    for setting_key in ENCRYPTED_SETTING_KEYS:
        entry = db.query(AppSetting).filter(AppSetting.key == setting_key).first()
        if entry and entry.value and not is_encrypted(entry.value, key):
            entry.value = encrypt_value(entry.value, key)
            migrated += 1

    if migrated:
        db.commit()
        logger.info("Migrated %d plaintext Schwab tokens to encrypted storage", migrated)

    return migrated


def schwab_tokens_exist(db) -> bool:
    """Check if any sensitive Schwab tokens are stored in the DB."""
    from app.models.database import AppSetting
    for key in ENCRYPTED_SETTING_KEYS:
        entry = db.query(AppSetting).filter(AppSetting.key == key).first()
        if entry and entry.value:
            return True
    return False


def check_db_file_permissions(db_path: str) -> list[str]:
    """Check DB file permissions and return warning messages."""
    import os
    import stat

    warnings = []
    if not os.path.exists(db_path):
        return warnings

    mode = os.stat(db_path).st_mode
    file_perms = mode & 0o777
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        warnings.append(
            f"Database file {db_path} has permissions {oct(file_perms)} — "
            f"recommend 'chmod 600 {db_path}' for production"
        )
    return warnings
