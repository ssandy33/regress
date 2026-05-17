"""Tests for the startup security gate and exception handlers in ``app.main``.

``_run_security_checks()`` is a fail-closed encryption gate: if Schwab
tokens exist in the DB but no encryption key is configured, the app must
refuse to start. The registered exception handlers must never leak raw
exception text into responses. See issue #85.
"""

from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import _run_security_checks
from app.models.database import AppSetting, Base
from app.services.encryption import EncryptionKeyMissing, encrypt_value

TEST_KEY = Fernet.generate_key().decode()


@pytest.fixture()
def db_session_factory():
    """In-memory SQLite sessionmaker for patching ``app.main.SessionLocal``."""
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


class TestSecurityChecks:
    def test_security_checks_pass_with_valid_key(self, db_session_factory):
        """Valid encryption key — the check completes without raising."""
        with patch("app.main.SessionLocal", db_session_factory), patch(
            "app.services.encryption.settings"
        ) as enc_settings, patch("app.main.app_settings") as app_settings:
            enc_settings.schwab_encryption_key = TEST_KEY
            app_settings.database_url = "sqlite:///:memory:"
            # Must not raise — valid key satisfies the gate.
            _run_security_checks()

    def test_security_checks_pass_without_key_when_no_tokens(
        self, db_session_factory
    ):
        """No key and no stored tokens — the check warns but does not raise."""
        with patch("app.main.SessionLocal", db_session_factory), patch(
            "app.services.encryption.settings"
        ) as enc_settings, patch("app.main.app_settings") as app_settings, patch(
            "app.main.logger"
        ) as mock_logger:
            enc_settings.schwab_encryption_key = ""
            app_settings.database_url = "sqlite:///:memory:"
            # No tokens in DB: must not raise, but must log a warning.
            _run_security_checks()
            assert mock_logger.warning.called

    def test_security_checks_fail_without_key(self, db_session_factory):
        """Fail-closed: stored Schwab tokens + no key — raises EncryptionKeyMissing.

        This is the critical security gate. If it passed silently, the app
        could start and overwrite encrypted tokens with plaintext.
        """
        _seed(db_session_factory, schwab_access_token="some_stored_token")
        with patch("app.main.SessionLocal", db_session_factory), patch(
            "app.services.encryption.settings"
        ) as enc_settings, patch("app.main.app_settings") as app_settings:
            enc_settings.schwab_encryption_key = ""
            app_settings.database_url = "sqlite:///:memory:"
            with pytest.raises(EncryptionKeyMissing):
                _run_security_checks()

    def test_security_checks_migrates_plaintext_tokens_with_key(
        self, db_session_factory
    ):
        """With a key set, plaintext tokens in the DB are encrypted in place."""
        _seed(db_session_factory, schwab_access_token="plaintext_token")
        with patch("app.main.SessionLocal", db_session_factory), patch(
            "app.services.encryption.settings"
        ) as enc_settings, patch("app.main.app_settings") as app_settings:
            enc_settings.schwab_encryption_key = TEST_KEY
            app_settings.database_url = "sqlite:///:memory:"
            _run_security_checks()

        db = db_session_factory()
        try:
            entry = (
                db.query(AppSetting)
                .filter(AppSetting.key == "schwab_access_token")
                .first()
            )
            # The plaintext value must no longer be stored as-is.
            assert entry.value != "plaintext_token"
            assert entry.value.startswith("ENC:")
        finally:
            db.close()

    def test_security_checks_db_error_propagates_when_no_key(self):
        """A DB error during the no-key token check propagates — fail-closed.

        The source comments are explicit: better to fail than to silently
        run with unencrypted tokens.
        """
        def _boom():
            raise RuntimeError("db unavailable")

        with patch("app.main.SessionLocal", _boom), patch(
            "app.services.encryption.settings"
        ) as enc_settings, patch("app.main.app_settings") as app_settings:
            enc_settings.schwab_encryption_key = ""
            app_settings.database_url = "sqlite:///:memory:"
            with pytest.raises(RuntimeError):
                _run_security_checks()


class TestExceptionHandlers:
    """The registered handlers must return safe, generic response bodies.

    Exercised through the ``client`` fixture and dedicated error-raising
    routes so the full FastAPI handler path is covered.
    """

    def test_schwab_auth_handler_returns_generic_message(self, client):
        """SchwabAuthError handler returns a generic message, not raw text."""
        from app.main import app
        from app.services.schwab_auth import SchwabAuthError

        secret = "leaky-internal-detail-XYZ"

        @app.get("/api/_test/schwab-error")
        def _raise_schwab_error():
            raise SchwabAuthError(secret)

        try:
            resp = client.get("/api/_test/schwab-error")
            assert resp.status_code == 401
            body = resp.text
            # The raw exception text must not appear in the response.
            assert secret not in body
            assert "not configured" in resp.json()["detail"]
        finally:
            app.router.routes = [
                r
                for r in app.router.routes
                if getattr(r, "path", None) != "/api/_test/schwab-error"
            ]

    def test_unhandled_exception_does_not_leak_raw_text(self):
        """A generic unhandled exception does not echo its message to the client.

        FastAPI's default 500 handler returns a generic ``Internal Server
        Error`` body; the raw exception text must not reach the response.
        A dedicated ``TestClient`` with ``raise_server_exceptions=False`` is
        used so the server-side 500 response is observable (the shared
        ``client`` fixture re-raises unhandled exceptions instead).
        """
        from fastapi.testclient import TestClient

        from app.main import app

        secret = "unhandled-secret-detail-ABC"

        @app.get("/api/_test/boom")
        def _raise_unhandled():
            raise RuntimeError(secret)

        try:
            with patch("app.main.init_db"), patch(
                "app.main.setup_logging"
            ), patch("app.main.create_backup", return_value=""), patch(
                "app.main._run_security_checks"
            ):
                with TestClient(
                    app, raise_server_exceptions=False
                ) as boom_client:
                    resp = boom_client.get("/api/_test/boom")
            assert resp.status_code == 500
            assert secret not in resp.text
        finally:
            app.router.routes = [
                r
                for r in app.router.routes
                if getattr(r, "path", None) != "/api/_test/boom"
            ]

    def test_data_fetch_error_handler_status_code(self, client):
        """DataFetchError handler maps to HTTP 502."""
        from app.main import app
        from app.services.data_fetcher import DataFetchError

        @app.get("/api/_test/data-fetch-error")
        def _raise_data_fetch_error():
            raise DataFetchError("upstream provider unavailable")

        try:
            resp = client.get("/api/_test/data-fetch-error")
            assert resp.status_code == 502
        finally:
            app.router.routes = [
                r
                for r in app.router.routes
                if getattr(r, "path", None) != "/api/_test/data-fetch-error"
            ]

    def test_invalid_ticker_error_handler_status_code(self, client):
        """InvalidTickerError handler maps to HTTP 404."""
        from app.main import app
        from app.services.data_fetcher import InvalidTickerError

        @app.get("/api/_test/invalid-ticker")
        def _raise_invalid_ticker():
            raise InvalidTickerError("ZZZZ")

        try:
            resp = client.get("/api/_test/invalid-ticker")
            assert resp.status_code == 404
        finally:
            app.router.routes = [
                r
                for r in app.router.routes
                if getattr(r, "path", None) != "/api/_test/invalid-ticker"
            ]

    def test_value_error_handler_status_code(self, client):
        """ValueError handler maps to HTTP 400."""
        from app.main import app

        @app.get("/api/_test/value-error")
        def _raise_value_error():
            raise ValueError("bad input")

        try:
            resp = client.get("/api/_test/value-error")
            assert resp.status_code == 400
        finally:
            app.router.routes = [
                r
                for r in app.router.routes
                if getattr(r, "path", None) != "/api/_test/value-error"
            ]
