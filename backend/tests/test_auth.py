"""Tests for the authentication dependency.

Covers acceptance criteria from issue #20 (original auth) and issue #28
(remove GITHUB_ID/GITHUB_SECRET from backend):
- AC1: App works out of the box with no auth env vars set
- AC2: Setting NEXTAUTH_SECRET enables full auth (no GitHub secrets needed)
- AC3: _is_partially_configured() always returns False (single-var model)
- AC4: ALLOWED_USERS still restricts access when auth is enabled
- AC5: No DEV_AUTH_BYPASS flag needed
- AC6: github_id and github_secret removed from Settings
"""

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user, is_auth_configured, _is_partially_configured

SECRET = "test-secret-key-for-unit-tests"


def _make_app():
    """Create a minimal FastAPI app with an auth-protected endpoint."""
    app = FastAPI()

    @app.get("/protected")
    async def protected(
        user: dict = pytest.importorskip("fastapi").Depends(get_current_user),
    ):
        return {"user": user}

    return app


def _make_token(payload: dict, secret: str = SECRET, algorithm: str = "HS256") -> str:
    """Create a signed JWT for testing."""
    return jwt.encode(payload, secret, algorithm=algorithm)


def _valid_payload(**overrides):
    """Build a valid token payload with sensible defaults."""
    base = {
        "sub": "12345",
        "username": "testuser",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    base.update(overrides)
    return base


def _mock_no_auth(mock_settings):
    """Configure mock for no auth env vars set."""
    mock_settings.nextauth_secret = None


def _mock_full_auth(mock_settings, allowed_users=""):
    """Configure mock for auth enabled (only NEXTAUTH_SECRET needed)."""
    mock_settings.nextauth_secret = SECRET
    mock_settings.allowed_users = allowed_users


# ---------------------------------------------------------------------------
# AC1: App works out of the box with no auth env vars set
# ---------------------------------------------------------------------------


class TestAC1NoAuthEnvVars:
    """AC1: App works out of the box with no auth env vars set."""

    def test_anonymous_access_when_no_env_vars(self):
        """Protected routes allow anonymous access when no auth env vars are set."""
        app = _make_app()
        client = TestClient(app)

        with patch("app.auth.settings") as mock_settings:
            _mock_no_auth(mock_settings)
            resp = client.get("/protected")

        assert resp.status_code == 200
        assert resp.json()["user"]["username"] == "anonymous"
        assert resp.json()["user"]["sub"] == "anonymous"

    def test_anonymous_access_without_bearer_token(self):
        """No Authorization header needed when auth is unconfigured."""
        app = _make_app()
        client = TestClient(app)

        with patch("app.auth.settings") as mock_settings:
            _mock_no_auth(mock_settings)
            resp = client.get("/protected")

        assert resp.status_code == 200

    def test_is_auth_configured_false_when_nothing_set(self):
        """is_auth_configured() returns False when NEXTAUTH_SECRET is not set."""
        with patch("app.auth.settings") as mock_settings:
            _mock_no_auth(mock_settings)
            assert is_auth_configured() is False

    def test_is_auth_configured_false_for_empty_string(self):
        """is_auth_configured() returns False for empty NEXTAUTH_SECRET."""
        with patch("app.auth.settings") as mock_settings:
            mock_settings.nextauth_secret = ""
            assert is_auth_configured() is False

    def test_logs_info_when_unconfigured(self, caplog):
        """Logs an info message when auth is not configured."""
        import app.auth

        app.auth._auth_warning_logged = False

        app_ = _make_app()
        client = TestClient(app_)

        with patch("app.auth.settings") as mock_settings:
            _mock_no_auth(mock_settings)
            with caplog.at_level(logging.INFO, logger="app.auth"):
                client.get("/protected")

        assert any("auth disabled" in r.message.lower() for r in caplog.records)
        app.auth._auth_warning_logged = False  # reset for other tests


# ---------------------------------------------------------------------------
# AC2: Setting NEXTAUTH_SECRET enables full auth
# ---------------------------------------------------------------------------


class TestAC2FullAuthEnabled:
    """AC2: Setting NEXTAUTH_SECRET enables full auth (no GitHub secrets needed)."""

    def test_is_auth_configured_true_when_secret_set(self):
        """is_auth_configured() returns True when NEXTAUTH_SECRET is set."""
        with patch("app.auth.settings") as mock_settings:
            _mock_full_auth(mock_settings)
            assert is_auth_configured() is True

    def test_returns_401_when_no_token_provided(self):
        """When auth is configured but no token is sent, return 401."""
        app = _make_app()
        client = TestClient(app)

        with patch("app.auth.settings") as mock_settings:
            _mock_full_auth(mock_settings)
            resp = client.get("/protected")

        assert resp.status_code == 401
        assert "Authentication required" in resp.json()["detail"]

    def test_returns_user_for_valid_token(self):
        """A valid HS256 JWT returns the user info."""
        app = _make_app()
        client = TestClient(app)
        token = _make_token(_valid_payload())

        with patch("app.auth.settings") as mock_settings:
            _mock_full_auth(mock_settings)
            resp = client.get(
                "/protected", headers={"Authorization": f"Bearer {token}"}
            )

        assert resp.status_code == 200
        data = resp.json()["user"]
        assert data["sub"] == "12345"
        assert data["username"] == "testuser"

    def test_returns_401_for_expired_token(self):
        """An expired JWT returns 401."""
        app = _make_app()
        client = TestClient(app)
        token = _make_token(
            _valid_payload(
                exp=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        )

        with patch("app.auth.settings") as mock_settings:
            _mock_full_auth(mock_settings)
            resp = client.get(
                "/protected", headers={"Authorization": f"Bearer {token}"}
            )

        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    def test_returns_401_for_wrong_secret(self):
        """A JWT signed with a different secret returns 401."""
        app = _make_app()
        client = TestClient(app)
        token = _make_token(_valid_payload(), secret="wrong-secret")

        with patch("app.auth.settings") as mock_settings:
            _mock_full_auth(mock_settings)
            resp = client.get(
                "/protected", headers={"Authorization": f"Bearer {token}"}
            )

        assert resp.status_code == 401
        assert "Invalid token" in resp.json()["detail"]

    def test_returns_401_for_malformed_token(self):
        """A garbage string returns 401."""
        app = _make_app()
        client = TestClient(app)

        with patch("app.auth.settings") as mock_settings:
            _mock_full_auth(mock_settings)
            resp = client.get(
                "/protected", headers={"Authorization": "Bearer not-a-jwt"}
            )

        assert resp.status_code == 401

    def test_rejects_blank_username(self):
        """A token with an empty username is rejected."""
        app = _make_app()
        client = TestClient(app)
        token = _make_token(_valid_payload(username=""))

        with patch("app.auth.settings") as mock_settings:
            _mock_full_auth(mock_settings)
            resp = client.get(
                "/protected", headers={"Authorization": f"Bearer {token}"}
            )

        assert resp.status_code == 401
        assert "missing username" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# AC3: _is_partially_configured() always returns False
# ---------------------------------------------------------------------------


class TestAC3PartialConfig:
    """AC3: With single-var auth model, partial config is not possible."""

    def test_is_partially_configured_always_false(self):
        """_is_partially_configured() always returns False with single-var model."""
        with patch("app.auth.settings") as mock_settings:
            _mock_no_auth(mock_settings)
            assert _is_partially_configured() is False

        with patch("app.auth.settings") as mock_settings:
            _mock_full_auth(mock_settings)
            assert _is_partially_configured() is False

    def test_anonymous_access_when_secret_not_set(self):
        """Anonymous access works when NEXTAUTH_SECRET is not set."""
        app = _make_app()
        client = TestClient(app)

        with patch("app.auth.settings") as mock_settings:
            mock_settings.nextauth_secret = None
            resp = client.get("/protected")

        assert resp.status_code == 200
        assert resp.json()["user"]["username"] == "anonymous"


# ---------------------------------------------------------------------------
# AC4: ALLOWED_USERS still restricts access when auth is enabled
# ---------------------------------------------------------------------------


class TestAC4AllowedUsers:
    """AC4: ALLOWED_USERS still restricts access when auth is enabled."""

    def test_rejects_user_not_in_allowlist(self):
        """A valid token for a user not in ALLOWED_USERS is rejected with 403."""
        app = _make_app()
        client = TestClient(app)
        token = _make_token(_valid_payload(username="outsider"))

        with patch("app.auth.settings") as mock_settings:
            _mock_full_auth(mock_settings, allowed_users="alice,bob")
            resp = client.get(
                "/protected", headers={"Authorization": f"Bearer {token}"}
            )

        assert resp.status_code == 403
        assert "not authorized" in resp.json()["detail"].lower()

    def test_allows_user_in_allowlist(self):
        """A valid token for a user in ALLOWED_USERS succeeds."""
        app = _make_app()
        client = TestClient(app)
        token = _make_token(_valid_payload(username="Alice"))

        with patch("app.auth.settings") as mock_settings:
            _mock_full_auth(mock_settings, allowed_users="alice,bob")
            resp = client.get(
                "/protected", headers={"Authorization": f"Bearer {token}"}
            )

        assert resp.status_code == 200
        assert resp.json()["user"]["username"] == "Alice"

    def test_case_insensitive_allowlist(self):
        """Allowlist matching is case-insensitive."""
        app = _make_app()
        client = TestClient(app)
        token = _make_token(_valid_payload(username="BOB"))

        with patch("app.auth.settings") as mock_settings:
            _mock_full_auth(mock_settings, allowed_users="alice,bob")
            resp = client.get(
                "/protected", headers={"Authorization": f"Bearer {token}"}
            )

        assert resp.status_code == 200

    def test_empty_allowlist_allows_any_user(self):
        """When ALLOWED_USERS is empty, any authenticated user is allowed."""
        app = _make_app()
        client = TestClient(app)
        token = _make_token(_valid_payload(username="anyone"))

        with patch("app.auth.settings") as mock_settings:
            _mock_full_auth(mock_settings, allowed_users="")
            resp = client.get(
                "/protected", headers={"Authorization": f"Bearer {token}"}
            )

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# AC5: No DEV_AUTH_BYPASS flag needed
# ---------------------------------------------------------------------------


class TestAC5NoDevBypass:
    """AC5: DEV_AUTH_BYPASS is removed — not needed when unconfigured = open."""

    def test_no_dev_auth_bypass_in_settings(self):
        """The Settings class no longer has a dev_auth_bypass field."""
        from app.config import Settings

        assert "dev_auth_bypass" not in Settings.model_fields

    def test_no_dev_auth_bypass_in_env_example(self):
        """DEV_AUTH_BYPASS is not referenced in .env.example."""
        import pathlib

        env_example = pathlib.Path(__file__).resolve().parents[2] / ".env.example"
        if env_example.exists():
            content = env_example.read_text()
            assert "DEV_AUTH_BYPASS" not in content

    def test_anonymous_without_bypass_flag(self):
        """Anonymous access works without any bypass flag when auth is unconfigured."""
        app = _make_app()
        client = TestClient(app)

        with patch("app.auth.settings") as mock_settings:
            _mock_no_auth(mock_settings)
            resp = client.get("/protected")

        assert resp.status_code == 200
        assert resp.json()["user"]["username"] == "anonymous"


# ---------------------------------------------------------------------------
# AC6: github_id and github_secret removed from Settings
# ---------------------------------------------------------------------------


class TestAC6NoGitHubSecretsInBackend:
    """AC6: GITHUB_ID and GITHUB_SECRET are removed from the backend."""

    def test_no_github_id_in_settings(self):
        """The Settings class no longer has a github_id field."""
        from app.config import Settings

        assert "github_id" not in Settings.model_fields

    def test_no_github_secret_in_settings(self):
        """The Settings class no longer has a github_secret field."""
        from app.config import Settings

        assert "github_secret" not in Settings.model_fields

    def test_auth_works_without_github_secrets(self):
        """Auth is fully functional with only NEXTAUTH_SECRET."""
        app = _make_app()
        client = TestClient(app)
        token = _make_token(_valid_payload())

        with patch("app.auth.settings") as mock_settings:
            _mock_full_auth(mock_settings)
            resp = client.get(
                "/protected", headers={"Authorization": f"Bearer {token}"}
            )

        assert resp.status_code == 200
        assert resp.json()["user"]["username"] == "testuser"

    def test_is_auth_configured_ignores_github_vars(self):
        """is_auth_configured() only checks NEXTAUTH_SECRET, not GitHub vars."""
        with patch("app.auth.settings") as mock_settings:
            mock_settings.nextauth_secret = SECRET
            # No github_id or github_secret attributes at all
            assert is_auth_configured() is True


# ---------------------------------------------------------------------------
# Route protection integration tests
# ---------------------------------------------------------------------------


class TestRouteProtection:
    """Verify health is public and protected routes require auth when configured."""

    def test_health_check_is_public(self):
        """The /api/health endpoint works without auth."""
        from app.main import app

        client = TestClient(app)

        with patch("app.auth.settings") as mock_settings:
            _mock_full_auth(mock_settings)
            resp = client.get("/api/health")

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_protected_route_returns_401_when_auth_enabled(self):
        """A protected endpoint returns 401 without auth when NEXTAUTH_SECRET is set."""
        from app.main import app

        client = TestClient(app)

        with patch("app.auth.settings") as mock_settings:
            _mock_full_auth(mock_settings)
            resp = client.get("/api/assets/search", params={"q": "AAPL"})

        assert resp.status_code == 401

    def test_protected_route_allows_anonymous_when_auth_disabled(self):
        """A protected endpoint allows anonymous access when auth is not configured."""
        app = _make_app()
        client = TestClient(app)

        with patch("app.auth.settings") as mock_settings:
            _mock_no_auth(mock_settings)
            resp = client.get("/protected")

        assert resp.status_code == 200
        assert resp.json()["user"]["username"] == "anonymous"

    def test_protected_route_allows_anonymous_when_secret_not_set(self):
        """A protected endpoint allows anonymous access when NEXTAUTH_SECRET is not set."""
        app = _make_app()
        client = TestClient(app)

        with patch("app.auth.settings") as mock_settings:
            mock_settings.nextauth_secret = None
            mock_settings.allowed_users = ""
            resp = client.get("/protected")

        assert resp.status_code == 200
        assert resp.json()["user"]["username"] == "anonymous"
