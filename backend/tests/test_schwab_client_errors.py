"""Tests that SchwabClientError messages are sanitized (no raw httpx text)."""

import re
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.schwab_client import SchwabClient, SchwabClientError


URL_PATTERN = re.compile(r"https?://")


@pytest.fixture
def client_obj():
    with patch("app.services.schwab_client.SchwabTokenManager") as mock_tm_cls:
        mock_tm_cls.return_value.get_access_token.return_value = "token"
        yield SchwabClient()


class TestQuoteErrorSanitization:
    def test_http_error_no_url_leak(self, client_obj):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 500

        exc = httpx.HTTPStatusError(
            "500 Internal Server Error for url https://api.schwabapi.com/v1/quotes",
            request=MagicMock(),
            response=mock_resp,
        )

        with patch("app.services.schwab_client.httpx.get") as mock_get:
            mock_get.return_value = mock_resp
            mock_resp.raise_for_status.side_effect = exc

            with pytest.raises(SchwabClientError) as exc_info:
                client_obj.get_quote("AAPL")

        msg = str(exc_info.value)
        assert not URL_PATTERN.search(msg), f"URL leaked: {msg}"
        assert "500" not in msg

    def test_request_error_no_raw_text(self, client_obj):
        exc = httpx.RequestError("Connection refused for https://api.schwabapi.com/v1/quotes")

        with patch("app.services.schwab_client.httpx.get", side_effect=exc):
            with pytest.raises(SchwabClientError) as exc_info:
                client_obj.get_quote("AAPL")

        msg = str(exc_info.value)
        assert not URL_PATTERN.search(msg), f"URL leaked: {msg}"
        assert "Connection refused" not in msg


class TestChainsErrorSanitization:
    def test_http_error_no_url_leak(self, client_obj):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 403

        exc = httpx.HTTPStatusError(
            "403 Forbidden for url https://api.schwabapi.com/v1/chains",
            request=MagicMock(),
            response=mock_resp,
        )

        with patch("app.services.schwab_client.httpx.get") as mock_get:
            mock_get.return_value = mock_resp
            mock_resp.raise_for_status.side_effect = exc

            with pytest.raises(SchwabClientError) as exc_info:
                client_obj.get_option_chain("AAPL")

        msg = str(exc_info.value)
        assert not URL_PATTERN.search(msg), f"URL leaked: {msg}"
        assert "403" not in msg


class TestPriceHistoryErrorSanitization:
    def test_http_error_no_url_leak(self, client_obj):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 500

        exc = httpx.HTTPStatusError(
            "500 for url https://api.schwabapi.com/v1/pricehistory",
            request=MagicMock(),
            response=mock_resp,
        )

        with patch("app.services.schwab_client.httpx.get") as mock_get:
            mock_get.return_value = mock_resp
            mock_resp.raise_for_status.side_effect = exc

            with pytest.raises(SchwabClientError) as exc_info:
                client_obj.get_price_history("AAPL", "2024-01-01", "2024-01-03")

        msg = str(exc_info.value)
        assert not URL_PATTERN.search(msg), f"URL leaked: {msg}"
        assert "500" not in msg

    def test_request_error_no_raw_text(self, client_obj):
        exc = httpx.RequestError("SSL error connecting to https://api.schwabapi.com")

        with patch("app.services.schwab_client.httpx.get", side_effect=exc):
            with pytest.raises(SchwabClientError) as exc_info:
                client_obj.get_price_history("AAPL", "2024-01-01", "2024-01-03")

        msg = str(exc_info.value)
        assert not URL_PATTERN.search(msg), f"URL leaked: {msg}"
        assert "SSL error" not in msg
