"""Tests for the authentication dependency."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user

SECRET = "test-secret-key-for-unit-tests"


def _make_app():
    """Create a minimal FastAPI app with an auth-protected endpoint."""
    app = FastAPI()

    @app.get("/protected")
    async def protected(user: dict = pytest.importorskip("fastapi").Depends(get_current_user)):
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


class TestGetCurrentUser:
    """Test the get_current_user FastAPI dependency."""

    def test_fails_closed_when_secret_not_configured(self):
        """When NEXTAUTH_SECRET is None and dev_auth_bypass is off, return 401."""
        app = _make_app()
        client = TestClient(app)

        with patch("app.auth.settings") as mock_settings:
            mock_settings.nextauth_secret = None
            mock_settings.dev_auth_bypass = False
            resp = client.get("/protected")

        assert resp.status_code == 401
        assert "not configured" in resp.json()["detail"].lower()

    def test_returns_anonymous_when_dev_bypass_enabled(self):
        """When dev_auth_bypass is True and secret is None, allow anonymous."""
        app = _make_app()
        client = TestClient(app)

        with patch("app.auth.settings") as mock_settings:
            mock_settings.nextauth_secret = None
            mock_settings.dev_auth_bypass = True
            resp = client.get("/protected")

        assert resp.status_code == 200
        assert resp.json()["user"]["username"] == "anonymous"

    def test_returns_401_when_no_token_provided(self):
        """When auth is configured but no token is sent, return 401."""
        app = _make_app()
        client = TestClient(app)

        with patch("app.auth.settings") as mock_settings:
            mock_settings.nextauth_secret = SECRET
            resp = client.get("/protected")

        assert resp.status_code == 401
        assert "Authentication required" in resp.json()["detail"]

    def test_returns_user_for_valid_token(self):
        """A valid HS256 JWT returns the user info."""
        app = _make_app()
        client = TestClient(app)
        token = _make_token(_valid_payload())

        with patch("app.auth.settings") as mock_settings:
            mock_settings.nextauth_secret = SECRET
            mock_settings.allowed_users = ""
            resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 200
        data = resp.json()["user"]
        assert data["sub"] == "12345"
        assert data["username"] == "testuser"

    def test_returns_401_for_expired_token(self):
        """An expired JWT returns 401."""
        app = _make_app()
        client = TestClient(app)
        token = _make_token(_valid_payload(
            exp=datetime.now(timezone.utc) - timedelta(hours=1),
        ))

        with patch("app.auth.settings") as mock_settings:
            mock_settings.nextauth_secret = SECRET
            resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    def test_returns_401_for_wrong_secret(self):
        """A JWT signed with a different secret returns 401."""
        app = _make_app()
        client = TestClient(app)
        token = _make_token(_valid_payload(), secret="wrong-secret")

        with patch("app.auth.settings") as mock_settings:
            mock_settings.nextauth_secret = SECRET
            resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 401
        assert "Invalid token" in resp.json()["detail"]

    def test_returns_401_for_malformed_token(self):
        """A garbage string returns 401."""
        app = _make_app()
        client = TestClient(app)

        with patch("app.auth.settings") as mock_settings:
            mock_settings.nextauth_secret = SECRET
            resp = client.get("/protected", headers={"Authorization": "Bearer not-a-jwt"})

        assert resp.status_code == 401

    def test_rejects_blank_username(self):
        """A token with an empty username is rejected."""
        app = _make_app()
        client = TestClient(app)
        token = _make_token(_valid_payload(username=""))

        with patch("app.auth.settings") as mock_settings:
            mock_settings.nextauth_secret = SECRET
            mock_settings.allowed_users = ""
            resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 401
        assert "missing username" in resp.json()["detail"].lower()

    def test_rejects_user_not_in_allowlist(self):
        """A valid token for a user not in ALLOWED_USERS is rejected with 403."""
        app = _make_app()
        client = TestClient(app)
        token = _make_token(_valid_payload(username="outsider"))

        with patch("app.auth.settings") as mock_settings:
            mock_settings.nextauth_secret = SECRET
            mock_settings.allowed_users = "alice,bob"
            resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 403
        assert "not authorized" in resp.json()["detail"].lower()

    def test_allows_user_in_allowlist(self):
        """A valid token for a user in ALLOWED_USERS succeeds."""
        app = _make_app()
        client = TestClient(app)
        token = _make_token(_valid_payload(username="Alice"))

        with patch("app.auth.settings") as mock_settings:
            mock_settings.nextauth_secret = SECRET
            mock_settings.allowed_users = "alice,bob"
            resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 200
        assert resp.json()["user"]["username"] == "Alice"

    def test_empty_allowlist_allows_any_user(self):
        """When ALLOWED_USERS is empty, any authenticated user is allowed."""
        app = _make_app()
        client = TestClient(app)
        token = _make_token(_valid_payload(username="anyone"))

        with patch("app.auth.settings") as mock_settings:
            mock_settings.nextauth_secret = SECRET
            mock_settings.allowed_users = ""
            resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 200


class TestRouteProtection:
    """Verify health is public and protected routes require auth."""

    def test_health_check_is_public(self):
        """The /api/health endpoint works without auth."""
        from app.main import app
        client = TestClient(app)

        with patch("app.auth.settings") as mock_settings:
            mock_settings.nextauth_secret = SECRET
            resp = client.get("/api/health")

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_protected_route_returns_401(self):
        """A protected endpoint (e.g. /api/assets/search) returns 401 without auth."""
        from app.main import app
        client = TestClient(app)

        with patch("app.auth.settings") as mock_settings:
            mock_settings.nextauth_secret = SECRET
            resp = client.get("/api/assets/search", params={"q": "AAPL"})

        assert resp.status_code == 401
