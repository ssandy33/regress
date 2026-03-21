"""Tests for Schwab OAuth setup endpoints in settings router."""

from unittest.mock import patch, MagicMock
import httpx
import pytest

from app.models.database import AppSetting


class TestSchwabAuthUrl:
    def test_generates_auth_url(self, client):
        resp = client.post("/api/settings/schwab/auth-url", json={"app_key": "test-key-123"})
        assert resp.status_code == 200
        data = resp.json()
        assert "auth_url" in data
        assert "test-key-123" in data["auth_url"]
        assert "redirect_uri" in data

    def test_empty_app_key_returns_422(self, client):
        resp = client.post("/api/settings/schwab/auth-url", json={"app_key": "  "})
        assert resp.status_code == 422


def _mock_token_response():
    mock = MagicMock()
    mock.json.return_value = {
        "access_token": "at-123",
        "refresh_token": "rt-456",
        "expires_in": 1800,
    }
    mock.raise_for_status = MagicMock()
    return mock


class TestSchwabCallback:
    def test_success(self, client):
        with patch("app.routers.settings.httpx.post", return_value=_mock_token_response()):
            resp = client.post("/api/settings/schwab/callback", json={
                "app_key": "key",
                "app_secret": "secret",
                "callback_url": "https://127.0.0.1:8089/callback?code=auth-code-xyz",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "access_token_expires" in data
        assert "refresh_token_expires" in data

    def test_tokens_persisted_in_db(self, client):
        """Verify tokens are actually stored in the database after successful exchange."""
        with patch("app.routers.settings.httpx.post", return_value=_mock_token_response()):
            resp = client.post("/api/settings/schwab/callback", json={
                "app_key": "my-key",
                "app_secret": "my-secret",
                "callback_url": "https://127.0.0.1:8089/callback?code=xyz",
            })
        assert resp.status_code == 200

        # Query DB directly via an endpoint that reads AppSettings
        # Use the settings health endpoint which calls is_configured()
        # Instead, check the DB through the test client's overridden session
        from app.models.database import get_db
        from app.main import app
        db_gen = app.dependency_overrides[get_db]()
        db = next(db_gen)
        try:
            access = db.query(AppSetting).filter(AppSetting.key == "schwab_access_token").first()
            refresh = db.query(AppSetting).filter(AppSetting.key == "schwab_refresh_token").first()
            app_key = db.query(AppSetting).filter(AppSetting.key == "schwab_app_key").first()
            assert access is not None and access.value
            assert refresh is not None and refresh.value
            assert app_key is not None and app_key.value == "my-key"
        finally:
            db.close()

    def test_no_code_in_url(self, client):
        resp = client.post("/api/settings/schwab/callback", json={
            "app_key": "key",
            "app_secret": "secret",
            "callback_url": "https://127.0.0.1:8089/callback",
        })
        assert resp.status_code == 422
        assert "authorization code" in resp.json()["detail"].lower()

    def test_token_exchange_http_error(self, client):
        error_resp = httpx.Response(401, request=httpx.Request("POST", "https://example.com"))
        with patch("app.routers.settings.httpx.post", side_effect=httpx.HTTPStatusError("", request=error_resp.request, response=error_resp)):
            resp = client.post("/api/settings/schwab/callback", json={
                "app_key": "key",
                "app_secret": "bad-secret",
                "callback_url": "https://127.0.0.1:8089/callback?code=invalid",
            })
        assert resp.status_code == 502
        assert "App Key and Secret" in resp.json()["detail"]

    def test_token_exchange_network_error(self, client):
        with patch("app.routers.settings.httpx.post", side_effect=httpx.ConnectError("connection refused")):
            resp = client.post("/api/settings/schwab/callback", json={
                "app_key": "key",
                "app_secret": "secret",
                "callback_url": "https://127.0.0.1:8089/callback?code=some-code",
            })
        assert resp.status_code == 502
        assert "Unable to reach Schwab API" in resp.json()["detail"]
