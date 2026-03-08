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
    return jwt.encode(payload, secret, algorithm=algorithm)


class TestGetCurrentUser:
    """Test the get_current_user FastAPI dependency."""

    def test_returns_anonymous_when_auth_not_configured(self):
        """When NEXTAUTH_SECRET is empty, auth is bypassed (dev mode)."""
        app = _make_app()
        client = TestClient(app)

        with patch("app.auth.settings") as mock_settings:
            mock_settings.nextauth_secret = ""
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

        token = _make_token({
            "sub": "12345",
            "username": "testuser",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        })

        with patch("app.auth.settings") as mock_settings:
            mock_settings.nextauth_secret = SECRET
            resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 200
        data = resp.json()["user"]
        assert data["sub"] == "12345"
        assert data["username"] == "testuser"

    def test_returns_401_for_expired_token(self):
        """An expired JWT returns 401."""
        app = _make_app()
        client = TestClient(app)

        token = _make_token({
            "sub": "12345",
            "username": "testuser",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        })

        with patch("app.auth.settings") as mock_settings:
            mock_settings.nextauth_secret = SECRET
            resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    def test_returns_401_for_wrong_secret(self):
        """A JWT signed with a different secret returns 401."""
        app = _make_app()
        client = TestClient(app)

        token = _make_token(
            {"sub": "12345", "username": "testuser",
             "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            secret="wrong-secret",
        )

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


class TestHealthRouteRemainsPublic:
    """Verify that health endpoints don't require auth."""

    def test_health_check_is_public(self):
        from app.main import app
        client = TestClient(app)

        with patch("app.auth.settings") as mock_settings:
            mock_settings.nextauth_secret = SECRET
            resp = client.get("/api/health")

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
