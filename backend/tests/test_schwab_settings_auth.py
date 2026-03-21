"""Tests for Schwab OAuth setup endpoints in settings router."""

from unittest.mock import patch, MagicMock
import httpx
import pytest


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


class TestSchwabCallback:
    def test_success(self, client):
        token_resp = MagicMock()
        token_resp.json.return_value = {
            "access_token": "at-123",
            "refresh_token": "rt-456",
            "expires_in": 1800,
        }
        token_resp.raise_for_status = MagicMock()

        with patch("app.routers.settings.httpx.post", return_value=token_resp):
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

    def test_no_code_in_url(self, client):
        resp = client.post("/api/settings/schwab/callback", json={
            "app_key": "key",
            "app_secret": "secret",
            "callback_url": "https://127.0.0.1:8089/callback",
        })
        assert resp.status_code == 422
        assert "authorization code" in resp.json()["detail"].lower()

    def test_token_exchange_fails(self, client):
        error_resp = httpx.Response(401, request=httpx.Request("POST", "https://example.com"))
        with patch("app.routers.settings.httpx.post", side_effect=httpx.HTTPStatusError("", request=error_resp.request, response=error_resp)):
            resp = client.post("/api/settings/schwab/callback", json={
                "app_key": "key",
                "app_secret": "bad-secret",
                "callback_url": "https://127.0.0.1:8089/callback?code=invalid",
            })
        assert resp.status_code == 502
        assert "App Key and Secret" in resp.json()["detail"]
