"""Integration tests for Schwab auth API endpoints.

Tests the full request path through the API. SchwabTokenManager uses
SessionLocal directly, so we patch it to use the test DB session.
Only external httpx calls to Schwab API are mocked.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx as _httpx
import pytest

from app.models.database import AppSetting, get_db
from app.services.schwab_auth import SchwabTokenManager


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the SchwabTokenManager singleton between tests."""
    SchwabTokenManager._instance = None
    yield
    SchwabTokenManager._instance = None


@pytest.fixture()
def test_session_local(client):
    """Patch SessionLocal so SchwabTokenManager uses the test DB."""
    from app.main import app

    override_fn = app.dependency_overrides[get_db]
    # Keep track of generators so their finally blocks run on cleanup
    generators = []

    def patched_session_local():
        gen = override_fn()
        generators.append(gen)
        return next(gen)

    with patch("app.models.database.SessionLocal", patched_session_local):
        yield patched_session_local

    # Run generator cleanup (closes DB sessions)
    for gen in generators:
        try:
            next(gen)
        except StopIteration:
            pass


def _insert_tokens(session_local_fn, access_minutes=30, refresh_days=7):
    """Insert Schwab tokens into the test DB."""
    db = session_local_fn()
    now = datetime.now(timezone.utc)
    tokens = {
        "schwab_app_key": "test_app_key",
        "schwab_app_secret": "test_app_secret",
        "schwab_access_token": "test_access_token_abc123",
        "schwab_refresh_token": "test_refresh_token_xyz789",
        "schwab_access_token_expires": (now + timedelta(minutes=access_minutes)).isoformat(),
        "schwab_refresh_token_expires": (now + timedelta(days=refresh_days)).isoformat(),
    }
    try:
        for key, value in tokens.items():
            entry = db.query(AppSetting).filter(AppSetting.key == key).first()
            if entry:
                entry.value = value
            else:
                db.add(AppSetting(key=key, value=value))
        db.commit()
    finally:
        db.close()


class TestSettingsEndpointSchwab:
    """GET /api/settings — schwab_configured and schwab_token_expires fields."""

    def test_unconfigured_returns_false(self, client, test_session_local):
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["schwab_configured"] is False
        assert data["schwab_token_expires"] is None

    def test_configured_returns_true_with_expiry(self, client, test_session_local):
        _insert_tokens(test_session_local)
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["schwab_configured"] is True
        assert data["schwab_token_expires"] is not None
        expires_dt = datetime.fromisoformat(data["schwab_token_expires"])
        assert expires_dt > datetime.now(timezone.utc)

    def test_other_settings_still_present(self, client, test_session_local):
        """Schwab fields don't break existing settings response."""
        resp = client.get("/api/settings")
        data = resp.json()
        assert "fred_api_key_set" in data
        assert "cache_ttl_daily_hours" in data
        assert "theme" in data


class TestSchwabHealthEndpoint:
    """GET /api/settings/health/schwab — configured/valid/error fields."""

    def test_unconfigured(self, client, test_session_local):
        resp = client.get("/api/settings/health/schwab")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False
        assert data["valid"] is False
        assert data["error"] is None

    def test_configured_and_valid(self, client, test_session_local):
        _insert_tokens(test_session_local)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_resp):
            resp = client.get("/api/settings/health/schwab")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert data["valid"] is True
        assert data["error"] is None

    def test_configured_but_api_returns_401(self, client, test_session_local):
        _insert_tokens(test_session_local)
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.raise_for_status.side_effect = _httpx.HTTPStatusError(
            "401", request=MagicMock(), response=mock_resp
        )

        with patch("httpx.get", return_value=mock_resp):
            resp = client.get("/api/settings/health/schwab")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert data["valid"] is False
        assert data["error"] == "HTTP 401"

    def test_configured_but_connection_fails(self, client, test_session_local):
        _insert_tokens(test_session_local)

        with patch("httpx.get", side_effect=_httpx.ConnectError("refused")):
            resp = client.get("/api/settings/health/schwab")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert data["valid"] is False
        assert data["error"] == "Connection failed"

    def test_configured_but_token_expired(self, client, test_session_local):
        """Expired access + expired refresh returns valid=False."""
        _insert_tokens(test_session_local, access_minutes=-5, refresh_days=-1)

        with patch("app.services.schwab_auth.get_schwab_credentials",
                    return_value=("test_app_key", "test_app_secret")):
            resp = client.get("/api/settings/health/schwab")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert data["valid"] is False


class TestSourcesEndpointSchwab:
    """GET /api/health/sources — schwab entry exercises real _check_schwab."""

    def _patch_other_sources(self):
        """Patch non-schwab sources to avoid real network calls."""
        return (
            patch("app.routers.health._check_alpha_vantage", return_value={"available": True, "error": None}),
            patch("app.routers.health._check_fred", return_value={"available": True, "error": None}),
            patch("app.routers.health._check_zillow", return_value={"available": True, "error": None}),
        )

    def test_unconfigured_shows_unavailable(self, client, test_session_local):
        p1, p2, p3 = self._patch_other_sources()
        with p1, p2, p3:
            resp = client.get("/api/health/sources")
        assert resp.status_code == 200
        data = resp.json()
        assert "schwab" in data
        assert data["schwab"]["available"] is False
        assert data["schwab"]["error"] == "Not configured"

    def test_configured_and_available(self, client, test_session_local):
        _insert_tokens(test_session_local)
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        p1, p2, p3 = self._patch_other_sources()
        with p1, p2, p3, patch("httpx.get", return_value=mock_resp):
            resp = client.get("/api/health/sources")
        assert resp.status_code == 200
        data = resp.json()
        assert data["schwab"]["available"] is True
        assert data["schwab"]["error"] is None
        assert data["all_down"] is False

    def test_all_down_includes_schwab(self, client, test_session_local):
        """all_down is True when all sources including schwab are down."""
        with patch("app.routers.health._check_alpha_vantage", return_value={"available": False, "error": "down"}), \
             patch("app.routers.health._check_fred", return_value={"available": False, "error": "down"}), \
             patch("app.routers.health._check_zillow", return_value={"available": False, "error": "down"}):
            resp = client.get("/api/health/sources")
        assert resp.status_code == 200
        data = resp.json()
        # schwab is also down (not configured in empty test DB)
        assert data["schwab"]["available"] is False
        assert data["all_down"] is True

    def test_not_all_down_when_schwab_available(self, client, test_session_local):
        """all_down is False if only schwab is up."""
        _insert_tokens(test_session_local)
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("app.routers.health._check_alpha_vantage", return_value={"available": False, "error": "down"}), \
             patch("app.routers.health._check_fred", return_value={"available": False, "error": "down"}), \
             patch("app.routers.health._check_zillow", return_value={"available": False, "error": "down"}), \
             patch("httpx.get", return_value=mock_resp):
            resp = client.get("/api/health/sources")
        assert resp.status_code == 200
        data = resp.json()
        assert data["schwab"]["available"] is True
        assert data["all_down"] is False
