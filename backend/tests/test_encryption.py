"""Tests for encryption service and integration with Schwab token storage."""

import os
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.services.encryption import (
    ENCRYPTED_SETTING_KEYS,
    EncryptionKeyMissing,
    check_db_file_permissions,
    decrypt_value,
    encrypt_value,
    get_encryption_key,
    is_encrypted,
    migrate_plaintext_tokens,
    require_encryption_key,
)


TEST_KEY = Fernet.generate_key().decode()
OTHER_KEY = Fernet.generate_key().decode()


class TestEncryptDecrypt:
    def test_roundtrip(self):
        """Encrypt then decrypt returns original value."""
        plaintext = "my_secret_token_value"
        ciphertext = encrypt_value(plaintext, key=TEST_KEY)
        assert ciphertext != plaintext
        assert decrypt_value(ciphertext, key=TEST_KEY) == plaintext

    def test_wrong_key_raises(self):
        """Decrypting with a different key raises InvalidToken."""
        ciphertext = encrypt_value("secret", key=TEST_KEY)
        with pytest.raises(InvalidToken):
            decrypt_value(ciphertext, key=OTHER_KEY)

    def test_empty_string_roundtrip(self):
        """Empty string encrypts and decrypts correctly."""
        ciphertext = encrypt_value("", key=TEST_KEY)
        assert decrypt_value(ciphertext, key=TEST_KEY) == ""

    def test_ciphertext_differs_each_call(self):
        """Fernet uses a random IV, so ciphertexts differ."""
        a = encrypt_value("same", key=TEST_KEY)
        b = encrypt_value("same", key=TEST_KEY)
        assert a != b  # different IVs
        assert decrypt_value(a, key=TEST_KEY) == decrypt_value(b, key=TEST_KEY)


class TestIsEncrypted:
    def test_true_for_ciphertext(self):
        ciphertext = encrypt_value("token", key=TEST_KEY)
        assert is_encrypted(ciphertext, key=TEST_KEY) is True

    def test_false_for_plaintext(self):
        assert is_encrypted("plaintext_token", key=TEST_KEY) is False

    def test_false_for_empty(self):
        assert is_encrypted("", key=TEST_KEY) is False

    def test_false_when_no_key(self):
        assert is_encrypted("anything", key=None) is False


class TestRequireEncryptionKey:
    def test_raises_when_missing(self):
        with patch("app.services.encryption.settings") as mock_settings:
            mock_settings.schwab_encryption_key = ""
            with pytest.raises(EncryptionKeyMissing):
                require_encryption_key()

    def test_returns_key_when_set(self):
        with patch("app.services.encryption.settings") as mock_settings:
            mock_settings.schwab_encryption_key = TEST_KEY
            assert require_encryption_key() == TEST_KEY


class TestGetEncryptionKey:
    def test_returns_none_when_empty(self):
        with patch("app.services.encryption.settings") as mock_settings:
            mock_settings.schwab_encryption_key = ""
            assert get_encryption_key() is None

    def test_returns_key_when_set(self):
        with patch("app.services.encryption.settings") as mock_settings:
            mock_settings.schwab_encryption_key = TEST_KEY
            assert get_encryption_key() == TEST_KEY


class TestUpsertEncrypts:
    def test_upsert_encrypts_sensitive_keys(self):
        """_upsert_setting encrypts values for sensitive keys."""
        from app.services.schwab_auth import _upsert_setting

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.services.encryption.settings") as mock_settings:
            mock_settings.schwab_encryption_key = TEST_KEY
            _upsert_setting(mock_db, "schwab_access_token", "my_token")

        # The value stored should be encrypted (not plaintext)
        added_obj = mock_db.add.call_args[0][0]
        assert added_obj.value != "my_token"
        # Should decrypt back to original
        assert decrypt_value(added_obj.value, key=TEST_KEY) == "my_token"

    def test_upsert_does_not_encrypt_non_sensitive_keys(self):
        """_upsert_setting stores plaintext for non-sensitive keys."""
        from app.services.schwab_auth import _upsert_setting

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.services.encryption.settings") as mock_settings:
            mock_settings.schwab_encryption_key = TEST_KEY
            _upsert_setting(mock_db, "schwab_access_token_expires", "2024-01-01T00:00:00")

        added_obj = mock_db.add.call_args[0][0]
        assert added_obj.value == "2024-01-01T00:00:00"


class TestReadSettingDecrypts:
    def test_read_setting_decrypts(self):
        """_read_setting decrypts encrypted values."""
        from app.services.schwab_auth import _read_setting

        encrypted = encrypt_value("real_token", key=TEST_KEY)
        mock_entry = MagicMock()
        mock_entry.value = encrypted

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_entry

        with patch("app.services.encryption.settings") as mock_settings:
            mock_settings.schwab_encryption_key = TEST_KEY
            result = _read_setting(mock_db, "schwab_access_token")

        assert result == "real_token"

    def test_read_setting_returns_plaintext_without_key(self):
        """_read_setting returns raw value when no encryption key."""
        from app.services.schwab_auth import _read_setting

        mock_entry = MagicMock()
        mock_entry.value = "plaintext_token"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_entry

        with patch("app.services.encryption.settings") as mock_settings:
            mock_settings.schwab_encryption_key = ""
            result = _read_setting(mock_db, "schwab_access_token")

        assert result == "plaintext_token"

    def test_read_setting_returns_none_when_missing(self):
        """_read_setting returns None for missing keys."""
        from app.services.schwab_auth import _read_setting

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = _read_setting(mock_db, "schwab_access_token")
        assert result is None


class TestMigratePlaintextTokens:
    def test_migrates_plaintext_to_encrypted(self, client):
        """migrate_plaintext_tokens encrypts plaintext values in-place."""
        from app.models.database import AppSetting, get_db
        from app.main import app

        override_fn = app.dependency_overrides.get(get_db)
        if not override_fn:
            pytest.skip("No DB override found")

        db = next(override_fn())

        # Seed plaintext values
        for key in ENCRYPTED_SETTING_KEYS:
            db.add(AppSetting(key=key, value=f"plaintext_{key}"))
        db.commit()

        with patch("app.services.encryption.settings") as mock_settings:
            mock_settings.schwab_encryption_key = TEST_KEY
            count = migrate_plaintext_tokens(db)

        assert count == 4

        # Verify all values are now encrypted
        for key in ENCRYPTED_SETTING_KEYS:
            entry = db.query(AppSetting).filter(AppSetting.key == key).first()
            assert entry.value != f"plaintext_{key}"
            assert decrypt_value(entry.value, key=TEST_KEY) == f"plaintext_{key}"

        db.close()

    def test_skips_already_encrypted(self, client):
        """migrate_plaintext_tokens skips values already encrypted."""
        from app.models.database import AppSetting, get_db
        from app.main import app

        override_fn = app.dependency_overrides.get(get_db)
        if not override_fn:
            pytest.skip("No DB override found")

        db = next(override_fn())

        # Seed already-encrypted values
        for key in ENCRYPTED_SETTING_KEYS:
            encrypted = encrypt_value(f"secret_{key}", key=TEST_KEY)
            db.add(AppSetting(key=key, value=encrypted))
        db.commit()

        with patch("app.services.encryption.settings") as mock_settings:
            mock_settings.schwab_encryption_key = TEST_KEY
            count = migrate_plaintext_tokens(db)

        assert count == 0
        db.close()

    def test_no_migration_without_key(self):
        """migrate_plaintext_tokens does nothing without encryption key."""
        mock_db = MagicMock()
        with patch("app.services.encryption.settings") as mock_settings:
            mock_settings.schwab_encryption_key = ""
            count = migrate_plaintext_tokens(mock_db)
        assert count == 0


class TestDbFilePermissions:
    def test_warns_on_world_readable(self, tmp_path):
        """Warns when DB file has group/other permissions."""
        db_file = tmp_path / "test.db"
        db_file.touch()
        os.chmod(db_file, 0o644)

        warnings = check_db_file_permissions(str(db_file))
        assert len(warnings) == 1
        assert "chmod 600" in warnings[0]

    def test_no_warning_on_600(self, tmp_path):
        """No warning when file has correct permissions."""
        db_file = tmp_path / "test.db"
        db_file.touch()
        os.chmod(db_file, 0o600)

        warnings = check_db_file_permissions(str(db_file))
        assert len(warnings) == 0

    def test_no_warning_for_missing_file(self, tmp_path):
        """No warning for non-existent file."""
        warnings = check_db_file_permissions(str(tmp_path / "nonexistent.db"))
        assert len(warnings) == 0


class TestEncryptedSettingKeys:
    def test_correct_keys(self):
        """ENCRYPTED_SETTING_KEYS contains exactly the sensitive keys."""
        assert ENCRYPTED_SETTING_KEYS == {
            "schwab_access_token",
            "schwab_refresh_token",
            "schwab_app_key",
            "schwab_app_secret",
        }

    def test_timestamp_keys_not_encrypted(self):
        """Timestamp keys are NOT in the encrypted set."""
        assert "schwab_access_token_expires" not in ENCRYPTED_SETTING_KEYS
        assert "schwab_refresh_token_expires" not in ENCRYPTED_SETTING_KEYS
