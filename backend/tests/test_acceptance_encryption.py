"""Acceptance tests for Issue #14: Secure Schwab tokens at rest.

Maps directly to the acceptance criteria:
  AC1: All schwab_* values in AppSetting are encrypted at rest
  AC2: App refuses to start without SCHWAB_ENCRYPTION_KEY when Schwab tokens exist
  AC3: Startup warns if DB file has group/world read permissions
  AC5: Existing tests pass; new tests cover encrypt/decrypt round-trip and missing key
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from app.models.database import AppSetting
from app.services.encryption import (
    ENCRYPTED_SETTING_KEYS,
    EncryptionKeyMissing,
    decrypt_value,
    encrypt_value,
)

TEST_KEY = Fernet.generate_key().decode()


# ---------------------------------------------------------------------------
# AC1: All schwab_* values in AppSetting are encrypted at rest
# ---------------------------------------------------------------------------


class TestAC1_SchwabValuesEncryptedAtRest:
    """Verify that writing via _upsert_setting encrypts, and reading via
    _read_setting decrypts, through a real SQLite DB."""

    def test_upsert_stores_encrypted_values_in_db(self, client):
        """Values written via _upsert_setting are encrypted in the raw DB."""
        from app.main import app
        from app.models.database import get_db
        from app.services.schwab_auth import _upsert_setting

        override_fn = app.dependency_overrides.get(get_db)
        if not override_fn:
            pytest.skip("No DB override found")

        db = next(override_fn())

        with patch("app.services.encryption.settings") as mock_settings:
            mock_settings.schwab_encryption_key = TEST_KEY
            for key in ENCRYPTED_SETTING_KEYS:
                _upsert_setting(db, key, f"plaintext_{key}")
            db.commit()

        # Raw DB values must NOT be plaintext
        for key in ENCRYPTED_SETTING_KEYS:
            entry = db.query(AppSetting).filter(AppSetting.key == key).first()
            assert entry is not None
            assert entry.value != f"plaintext_{key}", (
                f"{key} stored in plaintext — encryption failed"
            )
            # Must decrypt back to original
            assert decrypt_value(entry.value, key=TEST_KEY) == f"plaintext_{key}"

        db.close()

    def test_read_setting_returns_decrypted_values(self, client):
        """Values read via _read_setting are transparently decrypted."""
        from app.main import app
        from app.models.database import get_db
        from app.services.schwab_auth import _read_setting, _upsert_setting

        override_fn = app.dependency_overrides.get(get_db)
        if not override_fn:
            pytest.skip("No DB override found")

        db = next(override_fn())

        with patch("app.services.encryption.settings") as mock_settings:
            mock_settings.schwab_encryption_key = TEST_KEY
            for key in ENCRYPTED_SETTING_KEYS:
                _upsert_setting(db, key, f"secret_{key}")
            db.commit()

            # Read back through _read_setting — should get plaintext
            for key in ENCRYPTED_SETTING_KEYS:
                value = _read_setting(db, key)
                assert value == f"secret_{key}", (
                    f"{key} not decrypted correctly"
                )

        db.close()

    def test_non_sensitive_keys_stored_as_plaintext(self, client):
        """Timestamp keys are NOT encrypted."""
        from app.main import app
        from app.models.database import get_db
        from app.services.schwab_auth import _upsert_setting

        override_fn = app.dependency_overrides.get(get_db)
        if not override_fn:
            pytest.skip("No DB override found")

        db = next(override_fn())

        with patch("app.services.encryption.settings") as mock_settings:
            mock_settings.schwab_encryption_key = TEST_KEY
            _upsert_setting(db, "schwab_access_token_expires", "2025-01-01T00:00:00")
            _upsert_setting(db, "schwab_refresh_token_expires", "2025-01-07T00:00:00")
            db.commit()

        for ts_key in ["schwab_access_token_expires", "schwab_refresh_token_expires"]:
            entry = db.query(AppSetting).filter(AppSetting.key == ts_key).first()
            assert entry is not None
            assert "2025-" in entry.value, f"{ts_key} should be stored as plaintext ISO string"

        db.close()

    def test_all_four_sensitive_keys_are_covered(self):
        """ENCRYPTED_SETTING_KEYS covers exactly the 4 sensitive schwab_* keys."""
        expected = {
            "schwab_access_token",
            "schwab_refresh_token",
            "schwab_app_key",
            "schwab_app_secret",
        }
        assert ENCRYPTED_SETTING_KEYS == expected

    def test_migration_encrypts_existing_plaintext(self, client):
        """On startup migration, existing plaintext tokens become encrypted."""
        from app.main import app
        from app.models.database import get_db
        from app.services.encryption import migrate_plaintext_tokens

        override_fn = app.dependency_overrides.get(get_db)
        if not override_fn:
            pytest.skip("No DB override found")

        db = next(override_fn())

        # Seed plaintext values directly (simulating pre-encryption state)
        for key in ENCRYPTED_SETTING_KEYS:
            db.add(AppSetting(key=key, value=f"old_plaintext_{key}"))
        db.commit()

        with patch("app.services.encryption.settings") as mock_settings:
            mock_settings.schwab_encryption_key = TEST_KEY
            migrated = migrate_plaintext_tokens(db)

        assert migrated == 4

        # Verify raw values are now encrypted
        for key in ENCRYPTED_SETTING_KEYS:
            entry = db.query(AppSetting).filter(AppSetting.key == key).first()
            assert entry.value != f"old_plaintext_{key}"
            assert decrypt_value(entry.value, key=TEST_KEY) == f"old_plaintext_{key}"

        db.close()


# ---------------------------------------------------------------------------
# AC2: App refuses to start without SCHWAB_ENCRYPTION_KEY when tokens exist
# ---------------------------------------------------------------------------


class TestAC2_FailClosedWithoutEncryptionKey:
    """App must refuse to start when Schwab tokens exist but key is missing."""

    def test_startup_raises_when_tokens_exist_without_key(self):
        """_run_security_checks raises EncryptionKeyMissing when tokens
        exist in DB but SCHWAB_ENCRYPTION_KEY is not set."""
        from app.main import _run_security_checks

        mock_db = MagicMock()

        with patch("app.main.SessionLocal", return_value=mock_db), \
             patch("app.services.encryption.settings") as mock_settings, \
             patch("app.main.app_settings") as mock_app_settings, \
             patch("app.services.encryption.schwab_tokens_exist", return_value=True):
            mock_settings.schwab_encryption_key = ""
            mock_app_settings.database_url = "sqlite:///./test.db"

            with pytest.raises(EncryptionKeyMissing, match="SCHWAB_ENCRYPTION_KEY"):
                _run_security_checks()

    def test_startup_ok_when_no_tokens_and_no_key(self):
        """No error when there are no Schwab tokens and no key (fresh install)."""
        from app.main import _run_security_checks

        mock_db = MagicMock()

        with patch("app.main.SessionLocal", return_value=mock_db), \
             patch("app.services.encryption.settings") as mock_settings, \
             patch("app.main.app_settings") as mock_app_settings, \
             patch("app.services.encryption.schwab_tokens_exist", return_value=False):
            mock_settings.schwab_encryption_key = ""
            mock_app_settings.database_url = "sqlite:///./test.db"

            # Should not raise
            _run_security_checks()

    def test_startup_ok_when_tokens_exist_with_key(self):
        """No error when tokens exist and encryption key is set."""
        from app.main import _run_security_checks

        mock_db = MagicMock()

        with patch("app.main.SessionLocal", return_value=mock_db), \
             patch("app.services.encryption.settings") as mock_settings, \
             patch("app.main.app_settings") as mock_app_settings, \
             patch("app.services.encryption.migrate_plaintext_tokens", return_value=0):
            mock_settings.schwab_encryption_key = TEST_KEY
            mock_app_settings.database_url = "sqlite:///./test.db"

            # Should not raise
            _run_security_checks()

    def test_schwab_tokens_exist_detects_stored_tokens(self, client):
        """schwab_tokens_exist returns True when tokens are in DB."""
        from app.main import app
        from app.models.database import get_db
        from app.services.encryption import schwab_tokens_exist

        override_fn = app.dependency_overrides.get(get_db)
        if not override_fn:
            pytest.skip("No DB override found")

        db = next(override_fn())

        # Empty DB — no tokens
        assert schwab_tokens_exist(db) is False

        # Add one token
        db.add(AppSetting(key="schwab_access_token", value="some_token"))
        db.commit()
        assert schwab_tokens_exist(db) is True

        db.close()


# ---------------------------------------------------------------------------
# AC3: Startup warns if DB file has group/world read permissions
# ---------------------------------------------------------------------------


class TestAC3_StartupWarnsOnBadDbPermissions:
    """Startup must log a warning when the DB file is group/world readable."""

    def test_warns_on_group_readable_db(self, tmp_path):
        """_run_security_checks logs a warning for group-readable DB file."""
        from app.main import _run_security_checks

        db_file = tmp_path / "test.db"
        db_file.touch()
        os.chmod(db_file, 0o640)

        mock_db = MagicMock()

        with patch("app.main.SessionLocal", return_value=mock_db), \
             patch("app.services.encryption.settings") as mock_settings, \
             patch("app.main.app_settings") as mock_app_settings, \
             patch("app.services.encryption.schwab_tokens_exist", return_value=False):
            mock_settings.schwab_encryption_key = ""
            mock_app_settings.database_url = f"sqlite:///{db_file}"

            with patch("app.main.logger") as mock_logger:
                _run_security_checks()

            # Should have logged a permission warning
            warning_calls = [
                str(call) for call in mock_logger.warning.call_args_list
            ]
            assert any("chmod 600" in w for w in warning_calls), (
                f"Expected permission warning, got: {warning_calls}"
            )

    def test_warns_on_world_readable_db(self, tmp_path):
        """_run_security_checks logs a warning for world-readable DB file."""
        from app.main import _run_security_checks

        db_file = tmp_path / "test.db"
        db_file.touch()
        os.chmod(db_file, 0o644)

        mock_db = MagicMock()

        with patch("app.main.SessionLocal", return_value=mock_db), \
             patch("app.services.encryption.settings") as mock_settings, \
             patch("app.main.app_settings") as mock_app_settings, \
             patch("app.services.encryption.schwab_tokens_exist", return_value=False):
            mock_settings.schwab_encryption_key = ""
            mock_app_settings.database_url = f"sqlite:///{db_file}"

            with patch("app.main.logger") as mock_logger:
                _run_security_checks()

            warning_calls = [
                str(call) for call in mock_logger.warning.call_args_list
            ]
            assert any("chmod 600" in w for w in warning_calls)

    def test_no_warning_on_secure_permissions(self, tmp_path):
        """No permission warning when DB file has 0600."""
        from app.main import _run_security_checks

        db_file = tmp_path / "test.db"
        db_file.touch()
        os.chmod(db_file, 0o600)

        mock_db = MagicMock()

        with patch("app.main.SessionLocal", return_value=mock_db), \
             patch("app.services.encryption.settings") as mock_settings, \
             patch("app.main.app_settings") as mock_app_settings, \
             patch("app.services.encryption.schwab_tokens_exist", return_value=False):
            mock_settings.schwab_encryption_key = ""
            mock_app_settings.database_url = f"sqlite:///{db_file}"

            with patch("app.main.logger") as mock_logger:
                _run_security_checks()

            warning_calls = [
                str(call) for call in mock_logger.warning.call_args_list
            ]
            assert not any("chmod 600" in w for w in warning_calls)


# ---------------------------------------------------------------------------
# AC5: Existing tests pass; encrypt/decrypt round-trip and missing key
# ---------------------------------------------------------------------------


class TestAC5_EncryptDecryptRoundtripAndMissingKey:
    """Verify core encrypt/decrypt round-trip and missing-key behavior."""

    def test_encrypt_decrypt_roundtrip_all_sensitive_keys(self):
        """Each sensitive key type encrypts and decrypts correctly."""
        for key_name in ENCRYPTED_SETTING_KEYS:
            value = f"test_value_for_{key_name}"
            encrypted = encrypt_value(value, key=TEST_KEY)
            assert encrypted != value
            assert decrypt_value(encrypted, key=TEST_KEY) == value

    def test_missing_key_raises_on_encrypt(self):
        """encrypt_value raises EncryptionKeyMissing without a key."""
        with patch("app.services.encryption.settings") as mock_settings:
            mock_settings.schwab_encryption_key = ""
            with pytest.raises(EncryptionKeyMissing):
                encrypt_value("secret")

    def test_missing_key_raises_on_decrypt(self):
        """decrypt_value raises EncryptionKeyMissing without a key."""
        ciphertext = encrypt_value("secret", key=TEST_KEY)
        with patch("app.services.encryption.settings") as mock_settings:
            mock_settings.schwab_encryption_key = ""
            with pytest.raises(EncryptionKeyMissing):
                decrypt_value(ciphertext)

    def test_health_endpoint_includes_token_expiry(self, client):
        """GET /api/settings/health/schwab returns token_expiry field."""
        from app.services.schwab_auth import SchwabTokenManager

        now = datetime.now(timezone.utc)
        future_expiry = (now + timedelta(hours=24)).isoformat()

        with patch.object(SchwabTokenManager, "is_configured", return_value=True), \
             patch.object(SchwabTokenManager, "get_refresh_token_expiry", return_value=future_expiry), \
             patch.object(SchwabTokenManager, "get_access_token", return_value="token"), \
             patch("httpx.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp
            resp = client.get("/api/settings/health/schwab")

        assert resp.status_code == 200
        data = resp.json()
        assert "token_expiry" in data
        assert data["token_expiry"] is not None
        assert data["token_expiry"]["warning"] is True  # 24h < 48h threshold
        assert data["token_expiry"]["expired"] is False
        assert "hours_remaining" in data["token_expiry"]

    def test_health_endpoint_token_expiry_null_when_not_configured(self, client):
        """GET /api/settings/health/schwab returns token_expiry=null when unconfigured."""
        from app.services.schwab_auth import SchwabTokenManager

        with patch.object(SchwabTokenManager, "is_configured", return_value=False):
            resp = client.get("/api/settings/health/schwab")

        assert resp.status_code == 200
        data = resp.json()
        assert data["token_expiry"] is None
