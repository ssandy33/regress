"""Tests for SchwabClient.get_accounts and get_transactions methods."""

from unittest.mock import patch, MagicMock
import httpx
import pytest

from app.services.schwab_client import SchwabClient, SchwabClientError
from app.services.schwab_auth import SchwabAuthError


@pytest.fixture(autouse=True)
def mock_token():
    with patch("app.services.schwab_client.SchwabTokenManager") as mock_cls:
        mock_cls.return_value.get_access_token.return_value = "fake-token"
        yield


class TestGetAccounts:
    def test_success(self):
        accounts = [{"hashValue": "abc123", "securitiesAccount": {"accountNumber": "12345678"}}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = accounts
        mock_resp.raise_for_status = MagicMock()

        with patch("app.services.schwab_client.httpx.get", return_value=mock_resp):
            result = SchwabClient().get_accounts()

        assert result == accounts

    def test_401_raises_auth_error(self):
        resp = httpx.Response(401, request=httpx.Request("GET", "https://example.com"))
        with patch("app.services.schwab_client.httpx.get", side_effect=httpx.HTTPStatusError("", request=resp.request, response=resp)):
            with pytest.raises(SchwabAuthError):
                SchwabClient().get_accounts()

    def test_network_error_raises_client_error(self):
        with patch("app.services.schwab_client.httpx.get", side_effect=httpx.ConnectError("connection failed")):
            with pytest.raises(SchwabClientError):
                SchwabClient().get_accounts()


class TestGetTransactions:
    def test_success(self):
        txns = [{"transactionId": "1", "type": "TRADE"}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = txns
        mock_resp.raise_for_status = MagicMock()

        with patch("app.services.schwab_client.httpx.get", return_value=mock_resp):
            result = SchwabClient().get_transactions("abc123", "2025-01-01", "2025-03-01")

        assert result == txns

    def test_401_raises_auth_error(self):
        resp = httpx.Response(401, request=httpx.Request("GET", "https://example.com"))
        with patch("app.services.schwab_client.httpx.get", side_effect=httpx.HTTPStatusError("", request=resp.request, response=resp)):
            with pytest.raises(SchwabAuthError):
                SchwabClient().get_transactions("abc123", "2025-01-01", "2025-03-01")

    def test_empty_list(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()

        with patch("app.services.schwab_client.httpx.get", return_value=mock_resp):
            result = SchwabClient().get_transactions("abc123", "2025-01-01", "2025-03-01")

        assert result == []

    def test_invalid_account_hash(self):
        with pytest.raises(SchwabClientError, match="Invalid account hash"):
            SchwabClient().get_transactions("abc/123!!", "2025-01-01", "2025-03-01")
