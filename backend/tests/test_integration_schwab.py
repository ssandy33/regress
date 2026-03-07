"""Integration tests for Schwab auth API endpoints.

Tests the full request path through the API. Since SchwabTokenManager uses
SessionLocal directly (not FastAPI DI), we mock at the manager boundary
for DB state, and mock httpx for external Schwab API calls.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx as _httpx
import pytest

from app.services.schwab_auth import SchwabTokenManager


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the SchwabTokenManager singleton between tests."""
    SchwabTokenManager._instance = None
    yield
    SchwabTokenManager._instance = None


def _future_iso(days=0, minutes=0):
    return (datetime.now(timezone.utc) + timedelta(days=days, minutes=minutes)).isoformat()


class TestSettingsEndpointSchwab:
    """GET /api/settings — schwab_configured and schwab_token_expires fields."""

    def test_unconfigured_returns_false(self, client):
        with patch.object(SchwabTokenManager, "is_configured", return_value=False), \
             patch.object(SchwabTokenManager, "get_refresh_token_expiry", return_value=None):
            resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["schwab_configured"] is False
        assert data["schwab_token_expires"] is None

    def test_configured_returns_true_with_expiry(self, client):
        expiry = _future_iso(days=7)
        with patch.object(SchwabTokenManager, "is_configured", return_value=True), \
             patch.object(SchwabTokenManager, "get_refresh_token_expiry", return_value=expiry):
            resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["schwab_configured"] is True
        assert data["schwab_token_expires"] == expiry
        # Verify it's a valid ISO datetime in the future
        expires_dt = datetime.fromisoformat(data["schwab_token_expires"])
        assert expires_dt > datetime.now(timezone.utc)

    def test_other_settings_still_present(self, client):
        """Schwab fields don't break existing settings response."""
        with patch.object(SchwabTokenManager, "is_configured", return_value=False), \
             patch.object(SchwabTokenManager, "get_refresh_token_expiry", return_value=None):
            resp = client.get("/api/settings")
        data = resp.json()
        assert "fred_api_key_set" in data
        assert "cache_ttl_daily_hours" in data
        assert "theme" in data


class TestSchwabHealthEndpoint:
    """GET /api/settings/health/schwab — configured/valid/error fields."""

    def test_unconfigured(self, client):
        with patch.object(SchwabTokenManager, "is_configured", return_value=False):
            resp = client.get("/api/settings/health/schwab")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False
        assert data["valid"] is False
        assert data["error"] is None

    def test_configured_and_valid(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        with patch.object(SchwabTokenManager, "is_configured", return_value=True), \
             patch.object(SchwabTokenManager, "get_access_token", return_value="test_token"), \
             patch("httpx.get", return_value=mock_resp):
            resp = client.get("/api/settings/health/schwab")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert data["valid"] is True
        assert data["error"] is None

    def test_configured_but_api_returns_401(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.raise_for_status.side_effect = _httpx.HTTPStatusError(
            "401", request=MagicMock(), response=mock_resp
        )

        with patch.object(SchwabTokenManager, "is_configured", return_value=True), \
             patch.object(SchwabTokenManager, "get_access_token", return_value="bad_token"), \
             patch("httpx.get", return_value=mock_resp):
            resp = client.get("/api/settings/health/schwab")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert data["valid"] is False
        assert data["error"] == "HTTP 401"

    def test_configured_but_connection_fails(self, client):
        with patch.object(SchwabTokenManager, "is_configured", return_value=True), \
             patch.object(SchwabTokenManager, "get_access_token", return_value="token"), \
             patch("httpx.get", side_effect=_httpx.ConnectError("refused")):
            resp = client.get("/api/settings/health/schwab")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert data["valid"] is False
        assert data["error"] == "Connection failed"

    def test_configured_but_token_expired(self, client):
        """SchwabAuthError during get_access_token returns valid=False."""
        from app.services.schwab_auth import SchwabAuthError

        with patch.object(SchwabTokenManager, "is_configured", return_value=True), \
             patch.object(SchwabTokenManager, "get_access_token",
                          side_effect=SchwabAuthError("Refresh token expired")):
            resp = client.get("/api/settings/health/schwab")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert data["valid"] is False


class TestSourcesEndpointSchwab:
    """GET /api/health/sources — schwab entry in source checks."""

    def _patch_other_sources(self):
        """Patch non-schwab sources to avoid real network calls."""
        return (
            patch("app.routers.health._check_yfinance", return_value={"available": True, "error": None}),
            patch("app.routers.health._check_fred", return_value={"available": True, "error": None}),
            patch("app.routers.health._check_zillow", return_value={"available": True, "error": None}),
        )

    def test_unconfigured_shows_unavailable(self, client):
        p1, p2, p3 = self._patch_other_sources()
        with p1, p2, p3, \
             patch("app.routers.health._check_schwab",
                   return_value={"available": False, "error": "Not configured"}):
            resp = client.get("/api/health/sources")
        assert resp.status_code == 200
        data = resp.json()
        assert "schwab" in data
        assert data["schwab"]["available"] is False
        assert data["schwab"]["error"] == "Not configured"

    def test_configured_and_available(self, client):
        p1, p2, p3 = self._patch_other_sources()
        with p1, p2, p3, \
             patch("app.routers.health._check_schwab",
                   return_value={"available": True, "error": None}):
            resp = client.get("/api/health/sources")
        assert resp.status_code == 200
        data = resp.json()
        assert data["schwab"]["available"] is True
        assert data["schwab"]["error"] is None
        assert data["all_down"] is False

    def test_all_down_includes_schwab(self, client):
        """all_down is True only when all sources including schwab are down."""
        with patch("app.routers.health._check_yfinance", return_value={"available": False, "error": "down"}), \
             patch("app.routers.health._check_fred", return_value={"available": False, "error": "down"}), \
             patch("app.routers.health._check_zillow", return_value={"available": False, "error": "down"}), \
             patch("app.routers.health._check_schwab", return_value={"available": False, "error": "down"}):
            resp = client.get("/api/health/sources")
        assert resp.status_code == 200
        data = resp.json()
        assert data["all_down"] is True

    def test_not_all_down_when_schwab_available(self, client):
        """all_down is False if only schwab is up."""
        with patch("app.routers.health._check_yfinance", return_value={"available": False, "error": "down"}), \
             patch("app.routers.health._check_fred", return_value={"available": False, "error": "down"}), \
             patch("app.routers.health._check_zillow", return_value={"available": False, "error": "down"}), \
             patch("app.routers.health._check_schwab", return_value={"available": True, "error": None}):
            resp = client.get("/api/health/sources")
        assert resp.status_code == 200
        data = resp.json()
        assert data["all_down"] is False
