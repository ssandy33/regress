"""Direct tests for credential retrieval in ``app.config``.

Covers the two-tier lookup pattern of ``get_fred_api_key()`` and
``get_schwab_credentials()``: environment variable first, then the
encrypted ``AppSetting`` DB fallback. See issue #85.
"""

from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_fred_api_key, get_schwab_credentials
from app.models.database import AppSetting, Base
from app.services.encryption import encrypt_value

TEST_KEY = Fernet.generate_key().decode()


@pytest.fixture()
def db_session_factory():
    """In-memory SQLite sessionmaker for patching ``SessionLocal``.

    Returns the ``sessionmaker`` so tests can both seed data and pass it
    in as the ``SessionLocal`` the config functions import.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


def _seed(factory, **kv):
    """Insert ``AppSetting`` rows from key/value pairs."""
    db = factory()
    try:
        for key, value in kv.items():
            db.add(AppSetting(key=key, value=value))
        db.commit()
    finally:
        db.close()


class TestGetFredApiKey:
    def test_get_fred_api_key_from_env(self):
        """Env var set — returns the env value without touching the DB."""
        with patch("app.config.settings") as mock_settings:
            mock_settings.fred_api_key = "env_fred_key"
            assert get_fred_api_key() == "env_fred_key"

    def test_get_fred_api_key_from_db_fallback(self, db_session_factory):
        """No env var — returns the value stored in the DB."""
        _seed(db_session_factory, fred_api_key="db_fred_key")
        with patch("app.config.settings") as mock_settings, patch(
            "app.models.database.SessionLocal", db_session_factory
        ):
            mock_settings.fred_api_key = ""
            assert get_fred_api_key() == "db_fred_key"

    def test_get_fred_api_key_env_precedence_over_db(self, db_session_factory):
        """Env var wins even when a DB row also exists."""
        _seed(db_session_factory, fred_api_key="db_fred_key")
        with patch("app.config.settings") as mock_settings, patch(
            "app.models.database.SessionLocal", db_session_factory
        ):
            mock_settings.fred_api_key = "env_fred_key"
            assert get_fred_api_key() == "env_fred_key"

    def test_get_fred_api_key_missing_both(self, db_session_factory):
        """No env var and no DB row — returns empty string, never raises."""
        with patch("app.config.settings") as mock_settings, patch(
            "app.models.database.SessionLocal", db_session_factory
        ):
            mock_settings.fred_api_key = ""
            assert get_fred_api_key() == ""

    def test_get_fred_api_key_db_error_returns_empty(self):
        """A DB failure is swallowed — returns empty string, never raises."""
        def _boom():
            raise RuntimeError("db unavailable")

        with patch("app.config.settings") as mock_settings, patch(
            "app.models.database.SessionLocal", _boom
        ):
            mock_settings.fred_api_key = ""
            assert get_fred_api_key() == ""


class TestGetSchwabCredentials:
    def test_get_schwab_credentials_from_env(self):
        """Both env vars set — returns them without touching the DB."""
        with patch("app.config.settings") as mock_settings:
            mock_settings.schwab_app_key = "env_key"
            mock_settings.schwab_app_secret = "env_secret"
            assert get_schwab_credentials() == ("env_key", "env_secret")

    def test_get_schwab_credentials_partial_env(self, db_session_factory):
        """Only one env var set — falls through to the DB fallback path.

        ``get_schwab_credentials`` only short-circuits when *both* env vars
        are set. With one missing, it enters the DB branch, and any DB row
        found overwrites the corresponding value — including the half that
        was supplied via env. This documents the actual two-tier behavior.
        """
        _seed(
            db_session_factory,
            schwab_app_key=encrypt_value("db_key", key=TEST_KEY),
            schwab_app_secret=encrypt_value("db_secret", key=TEST_KEY),
        )
        with patch("app.config.settings") as mock_settings, patch(
            "app.models.database.SessionLocal", db_session_factory
        ), patch("app.services.encryption.settings") as enc_settings:
            mock_settings.schwab_app_key = "env_key"
            mock_settings.schwab_app_secret = ""
            enc_settings.schwab_encryption_key = TEST_KEY
            app_key, app_secret = get_schwab_credentials()
        # Both DB rows present — both halves are taken from the DB.
        assert app_key == "db_key"
        assert app_secret == "db_secret"

    def test_get_schwab_credentials_partial_env_no_db_keeps_env(
        self, db_session_factory
    ):
        """One env var set, no DB rows — the env half is preserved.

        With no DB rows to overwrite it, the env-supplied value survives
        and the missing half stays empty.
        """
        with patch("app.config.settings") as mock_settings, patch(
            "app.models.database.SessionLocal", db_session_factory
        ), patch("app.services.encryption.settings") as enc_settings:
            mock_settings.schwab_app_key = "env_key"
            mock_settings.schwab_app_secret = ""
            enc_settings.schwab_encryption_key = TEST_KEY
            app_key, app_secret = get_schwab_credentials()
        assert app_key == "env_key"
        assert app_secret == ""

    def test_get_schwab_credentials_db_fallback(self, db_session_factory):
        """No env vars — credentials are decrypted from the DB."""
        _seed(
            db_session_factory,
            schwab_app_key=encrypt_value("real_key", key=TEST_KEY),
            schwab_app_secret=encrypt_value("real_secret", key=TEST_KEY),
        )
        with patch("app.config.settings") as mock_settings, patch(
            "app.models.database.SessionLocal", db_session_factory
        ), patch("app.services.encryption.settings") as enc_settings:
            mock_settings.schwab_app_key = ""
            mock_settings.schwab_app_secret = ""
            enc_settings.schwab_encryption_key = TEST_KEY
            assert get_schwab_credentials() == ("real_key", "real_secret")

    def test_get_schwab_credentials_db_fallback_no_key(self, db_session_factory):
        """No encryption key configured — DB values are returned as stored."""
        _seed(
            db_session_factory,
            schwab_app_key="plain_key",
            schwab_app_secret="plain_secret",
        )
        with patch("app.config.settings") as mock_settings, patch(
            "app.models.database.SessionLocal", db_session_factory
        ), patch("app.services.encryption.settings") as enc_settings:
            mock_settings.schwab_app_key = ""
            mock_settings.schwab_app_secret = ""
            enc_settings.schwab_encryption_key = ""
            assert get_schwab_credentials() == ("plain_key", "plain_secret")

    def test_get_schwab_credentials_env_precedence_over_db(self, db_session_factory):
        """Env vars win even when DB rows also exist."""
        _seed(
            db_session_factory,
            schwab_app_key=encrypt_value("db_key", key=TEST_KEY),
            schwab_app_secret=encrypt_value("db_secret", key=TEST_KEY),
        )
        with patch("app.config.settings") as mock_settings, patch(
            "app.models.database.SessionLocal", db_session_factory
        ), patch("app.services.encryption.settings") as enc_settings:
            mock_settings.schwab_app_key = "env_key"
            mock_settings.schwab_app_secret = "env_secret"
            enc_settings.schwab_encryption_key = TEST_KEY
            assert get_schwab_credentials() == ("env_key", "env_secret")

    def test_get_schwab_credentials_missing_both(self, db_session_factory):
        """No env vars and no DB rows — returns ('', ''), never raises."""
        with patch("app.config.settings") as mock_settings, patch(
            "app.models.database.SessionLocal", db_session_factory
        ), patch("app.services.encryption.settings") as enc_settings:
            mock_settings.schwab_app_key = ""
            mock_settings.schwab_app_secret = ""
            enc_settings.schwab_encryption_key = TEST_KEY
            assert get_schwab_credentials() == ("", "")

    def test_credential_decryption_failure(self, db_session_factory):
        """A corrupted DB value is handled gracefully — never raises.

        ``decrypt_value`` raises ``InvalidToken`` on garbage ciphertext;
        ``get_schwab_credentials`` swallows it and returns the env-level
        defaults (empty strings here) instead of propagating.
        """
        _seed(
            db_session_factory,
            schwab_app_key="ENC:not-a-valid-fernet-token",
            schwab_app_secret="ENC:also-garbage",
        )
        with patch("app.config.settings") as mock_settings, patch(
            "app.models.database.SessionLocal", db_session_factory
        ), patch("app.services.encryption.settings") as enc_settings:
            mock_settings.schwab_app_key = ""
            mock_settings.schwab_app_secret = ""
            enc_settings.schwab_encryption_key = TEST_KEY
            # Must not raise; corrupted ciphertext degrades to the defaults.
            assert get_schwab_credentials() == ("", "")

    def test_get_schwab_credentials_db_error_returns_defaults(self):
        """A DB failure is swallowed — returns ('', ''), never raises."""
        def _boom():
            raise RuntimeError("db unavailable")

        with patch("app.config.settings") as mock_settings, patch(
            "app.models.database.SessionLocal", _boom
        ):
            mock_settings.schwab_app_key = ""
            mock_settings.schwab_app_secret = ""
            assert get_schwab_credentials() == ("", "")
