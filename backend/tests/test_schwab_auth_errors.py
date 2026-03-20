"""Tests that SchwabAuthError messages from _refresh_tokens() are sanitized."""

import re
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.schwab_auth import SchwabAuthError, SchwabTokenManager


URL_PATTERN = re.compile(r"https?://")


@pytest.fixture(autouse=True)
def reset_singleton():
    SchwabTokenManager._instance = None
    yield
    SchwabTokenManager._instance = None


def _make_mgr_needing_refresh():
    """Create a SchwabTokenManager whose access token is expired so it will call _refresh_tokens."""
    mgr = SchwabTokenManager()
    now = datetime.now(timezone.utc)
    mgr._cached_access_token = "old"
    mgr._cached_access_token_expires = now - timedelta(minutes=5)

    mock_db = MagicMock()
    mock_access = MagicMock(value="old")
    mock_access_exp = MagicMock(value=(now - timedelta(minutes=5)).isoformat())
    mock_refresh = MagicMock(value="refresh_val")
    mock_refresh_exp = MagicMock(value=(now + timedelta(days=5)).isoformat())

    mock_db.query.return_value.filter.return_value.first.side_effect = [
        mock_access, mock_access_exp, mock_refresh, mock_refresh_exp,
    ]

    return mgr, mock_db


class TestRefreshTokenErrorSanitization:
    def test_non_401_http_error_does_not_leak_url(self):
        """Non-401 HTTP errors must not expose internal URLs."""
        mgr, mock_db = _make_mgr_needing_refresh()

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 400

        exc = httpx.HTTPStatusError(
            "400 Bad Request for url https://api.schwabapi.com/v1/oauth/token",
            request=MagicMock(),
            response=mock_resp,
        )

        with patch("app.services.schwab_auth.get_schwab_credentials", return_value=("k", "s")), \
             patch("httpx.post", side_effect=exc), \
             patch("app.models.database.SessionLocal", return_value=mock_db):
            with pytest.raises(SchwabAuthError) as exc_info:
                mgr.get_access_token()

        msg = str(exc_info.value)
        assert not URL_PATTERN.search(msg), f"URL leaked in error message: {msg}"
        assert "400" not in msg
        assert "re-authorize" in msg.lower() or "schwab-auth" in msg.lower()

    def test_request_error_does_not_leak_url(self):
        """Network-level errors must not expose raw exception text."""
        mgr, mock_db = _make_mgr_needing_refresh()

        exc = httpx.RequestError(
            "Connection refused for https://api.schwabapi.com/v1/oauth/token"
        )

        with patch("app.services.schwab_auth.get_schwab_credentials", return_value=("k", "s")), \
             patch("httpx.post", side_effect=exc), \
             patch("app.models.database.SessionLocal", return_value=mock_db):
            with pytest.raises(SchwabAuthError) as exc_info:
                mgr.get_access_token()

        msg = str(exc_info.value)
        assert not URL_PATTERN.search(msg), f"URL leaked in error message: {msg}"
        assert "Connection refused" not in msg
        assert "try again" in msg.lower()

    def test_401_still_mentions_reauth(self):
        """401 errors should still tell the user to re-authorize."""
        mgr, mock_db = _make_mgr_needing_refresh()

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 401

        exc = httpx.HTTPStatusError(
            "401 Unauthorized", request=MagicMock(), response=mock_resp
        )

        with patch("app.services.schwab_auth.get_schwab_credentials", return_value=("k", "s")), \
             patch("httpx.post", side_effect=exc), \
             patch("app.models.database.SessionLocal", return_value=mock_db):
            with pytest.raises(SchwabAuthError, match="schwab-auth"):
                mgr.get_access_token()
