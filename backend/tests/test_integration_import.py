"""Integration tests for Schwab import API endpoints."""

import logging
from unittest.mock import patch, MagicMock
import pytest


MOCK_ACCOUNTS = [{"hashValue": "abc123", "securitiesAccount": {"accountNumber": "12345678"}}]

MOCK_TRANSACTIONS = [
    {
        "transactionDate": "2025-03-01T10:00:00Z",
        "netAmount": 300.0,
        "fees": {"commission": 0.65, "secFee": 0, "optRegFee": 0, "rFee": 0, "cdscFee": 0, "otherCharges": 0},
        "transferItems": [
            {
                "instruction": "SELL_TO_OPEN",
                "amount": 1,
                "instrument": {
                    "assetType": "OPTION",
                    "underlyingSymbol": "AAPL",
                    "putCall": "PUT",
                    "strikePrice": 150.0,
                    "expirationDate": "2025-03-21T00:00:00.000+0000",
                },
            }
        ],
    },
    {
        "transactionDate": "2025-03-02T10:00:00Z",
        "netAmount": 500.0,
        "fees": {},
        "transferItems": [
            {
                "instruction": "SELL_TO_OPEN",
                "amount": 1,
                "instrument": {
                    "assetType": "OPTION",
                    "underlyingSymbol": "MSFT",
                    "putCall": "CALL",
                    "strikePrice": 400.0,
                    "expirationDate": "2025-04-18T00:00:00.000+0000",
                },
            }
        ],
    },
]


def _mock_schwab_client():
    mock = MagicMock()
    mock.get_accounts.return_value = MOCK_ACCOUNTS
    mock.get_transactions.return_value = MOCK_TRANSACTIONS
    return mock


@pytest.fixture()
def mock_schwab():
    mock = _mock_schwab_client()
    with patch("app.services.schwab_import.SchwabClient", return_value=mock):
        yield mock


class TestImportPreview:
    def test_preview_invalid_date_format(self, client):
        resp = client.get("/api/journal/import/preview", params={"start_date": "not-a-date", "end_date": "2025-03-31"})
        assert resp.status_code == 422

    def test_preview_success(self, client, mock_schwab):
        resp = client.get("/api/journal/import/preview", params={"start_date": "2025-03-01", "end_date": "2025-03-31"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["account_number"] == "****5678"
        assert data["total"] == 2
        assert data["new_count"] == 2
        assert data["duplicates"] == 0
        assert len(data["trades"]) == 2
        assert data["trades"][0]["ticker"] == "AAPL"
        assert data["trades"][0]["trade_type"] == "sell_put"
        assert data["trades"][1]["ticker"] == "MSFT"

    def test_preview_no_auth_returns_401(self, client):
        from app.services.schwab_auth import SchwabAuthCode, SchwabAuthError
        with patch("app.services.schwab_import.SchwabClient") as mock_cls:
            mock_cls.return_value.get_accounts.side_effect = SchwabAuthError("no token", code=SchwabAuthCode.TOKEN_MISSING)
            resp = client.get("/api/journal/import/preview", params={"start_date": "2025-03-01", "end_date": "2025-03-31"})
        assert resp.status_code == 401


class TestImportExecute:
    def test_import_invalid_date_format(self, client):
        resp = client.post("/api/journal/import", json={
            "start_date": "March 1",
            "end_date": "2025-03-31",
        })
        assert resp.status_code == 422

    def test_import_creates_trades(self, client, mock_schwab):
        resp = client.post("/api/journal/import", json={
            "start_date": "2025-03-01",
            "end_date": "2025-03-31",
            "position_strategy": "wheel",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 2
        assert data["skipped_duplicates"] == 0
        assert data["positions_created"] == 2  # AAPL + MSFT

        # Verify trades exist in DB
        positions_resp = client.get("/api/journal/positions")
        positions = positions_resp.json()["positions"]
        assert len(positions) == 2
        tickers = {p["ticker"] for p in positions}
        assert tickers == {"AAPL", "MSFT"}

    def test_import_skips_duplicates(self, client, mock_schwab):
        # First import
        client.post("/api/journal/import", json={
            "start_date": "2025-03-01",
            "end_date": "2025-03-31",
        })

        # Second import — same transactions
        resp = client.post("/api/journal/import", json={
            "start_date": "2025-03-01",
            "end_date": "2025-03-31",
        })
        data = resp.json()
        assert data["imported"] == 0
        assert data["skipped_duplicates"] == 2
        assert data["positions_created"] == 0

    def test_import_reuses_existing_position(self, client, mock_schwab):
        # Create a position for AAPL first
        client.post("/api/journal/positions", json={
            "ticker": "AAPL",
            "shares": 100,
            "broker_cost_basis": 15000.0,
            "strategy": "wheel",
            "opened_at": "2025-01-01T00:00:00Z",
        })

        resp = client.post("/api/journal/import", json={
            "start_date": "2025-03-01",
            "end_date": "2025-03-31",
        })
        data = resp.json()
        assert data["imported"] == 2
        assert data["positions_created"] == 1  # only MSFT created, AAPL reused


class TestImportDateRangeValidation:
    """Tests for date range validation (issue #73)."""

    def test_preview_rejects_range_over_365_days(self, client):
        resp = client.get("/api/journal/import/preview", params={
            "start_date": "2024-01-01",
            "end_date": "2025-02-04",  # 400 days
        })
        assert resp.status_code == 422
        assert "365" in resp.json()["detail"]

    def test_preview_accepts_range_at_365_days(self, client, mock_schwab):
        resp = client.get("/api/journal/import/preview", params={
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",  # exactly 365 days
        })
        assert resp.status_code == 200

    def test_import_rejects_range_over_365_days(self, client):
        resp = client.post("/api/journal/import", json={
            "start_date": "2024-01-01",
            "end_date": "2025-02-04",  # 400 days
        })
        assert resp.status_code == 422
        assert "365" in resp.json()["detail"]

    def test_import_accepts_range_at_365_days(self, client, mock_schwab):
        resp = client.post("/api/journal/import", json={
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",  # exactly 365 days
        })
        assert resp.status_code == 200


class TestImportAuthErrors:
    """Tests for improved auth error messages and logging (issue #69)."""

    def test_preview_expired_token_returns_specific_detail(self, client):
        from app.services.schwab_auth import SchwabAuthCode, SchwabAuthError
        with patch("app.services.schwab_import.SchwabClient") as mock_cls:
            mock_cls.return_value.get_accounts.side_effect = SchwabAuthError(
                "expired", code=SchwabAuthCode.TOKEN_EXPIRED,
            )
            resp = client.get("/api/journal/import/preview", params={"start_date": "2025-03-01", "end_date": "2025-03-31"})
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()
        assert "Settings" in resp.json()["detail"]

    def test_preview_no_token_returns_not_connected(self, client):
        from app.services.schwab_auth import SchwabAuthCode, SchwabAuthError
        with patch("app.services.schwab_import.SchwabClient") as mock_cls:
            mock_cls.return_value.get_accounts.side_effect = SchwabAuthError(
                "no token", code=SchwabAuthCode.TOKEN_MISSING,
            )
            resp = client.get("/api/journal/import/preview", params={"start_date": "2025-03-01", "end_date": "2025-03-31"})
        assert resp.status_code == 401
        assert "not connected" in resp.json()["detail"].lower()

    def test_preview_not_configured_returns_setup_message(self, client):
        from app.services.schwab_auth import SchwabAuthCode, SchwabAuthError
        with patch("app.services.schwab_import.SchwabClient") as mock_cls:
            mock_cls.return_value.get_accounts.side_effect = SchwabAuthError(
                "not configured", code=SchwabAuthCode.NOT_CONFIGURED,
            )
            resp = client.get("/api/journal/import/preview", params={"start_date": "2025-03-01", "end_date": "2025-03-31"})
        assert resp.status_code == 401
        assert "not configured" in resp.json()["detail"].lower()

    def test_import_expired_token_returns_specific_detail(self, client):
        from app.services.schwab_auth import SchwabAuthCode, SchwabAuthError
        with patch("app.services.schwab_import.SchwabClient") as mock_cls:
            mock_cls.return_value.get_accounts.side_effect = SchwabAuthError(
                "expired", code=SchwabAuthCode.TOKEN_EXPIRED,
            )
            resp = client.post("/api/journal/import", json={
                "start_date": "2025-03-01",
                "end_date": "2025-03-31",
            })
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    def test_generic_auth_error_returns_fallback_detail(self, client):
        from app.services.schwab_auth import SchwabAuthCode, SchwabAuthError
        with patch("app.services.schwab_import.SchwabClient") as mock_cls:
            mock_cls.return_value.get_accounts.side_effect = SchwabAuthError(
                "refresh failed", code=SchwabAuthCode.REFRESH_FAILED,
            )
            resp = client.get("/api/journal/import/preview", params={"start_date": "2025-03-01", "end_date": "2025-03-31"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Schwab authentication failed. Please re-authorize in Settings."

    def test_auth_error_is_logged(self, client, caplog):
        from app.services.schwab_auth import SchwabAuthCode, SchwabAuthError
        with patch("app.services.schwab_import.SchwabClient") as mock_cls:
            mock_cls.return_value.get_accounts.side_effect = SchwabAuthError(
                "expired", code=SchwabAuthCode.TOKEN_EXPIRED,
            )
            with caplog.at_level(logging.WARNING, logger="app.routers.journal"):
                client.get("/api/journal/import/preview", params={"start_date": "2025-03-01", "end_date": "2025-03-31"})
        assert any("Schwab auth failed" in r.message for r in caplog.records)

    def test_schwab_auth_detail_maps_all_codes(self):
        """Verify _schwab_auth_detail returns expected strings for each code."""
        from app.routers.journal import _schwab_auth_detail
        from app.services.schwab_auth import SchwabAuthCode, SchwabAuthError

        cases = {
            SchwabAuthCode.TOKEN_EXPIRED: "Schwab token has expired. Please re-authorize in Settings.",
            SchwabAuthCode.REFRESH_FAILED_401: "Schwab token has expired. Please re-authorize in Settings.",
            SchwabAuthCode.API_401: "Schwab token has expired. Please re-authorize in Settings.",
            SchwabAuthCode.TOKEN_MISSING: "Schwab is not connected. Please authorize in Settings.",
            SchwabAuthCode.NOT_CONFIGURED: "Schwab app credentials are not configured. Please set up in Settings.",
            SchwabAuthCode.REFRESH_FAILED: "Schwab authentication failed. Please re-authorize in Settings.",
            SchwabAuthCode.NETWORK_ERROR: "Schwab authentication failed. Please re-authorize in Settings.",
        }
        assert set(cases.keys()) == set(SchwabAuthCode), "Missing code in test coverage"
        for code, expected in cases.items():
            err = SchwabAuthError("test", code=code)
            assert _schwab_auth_detail(err) == expected, f"Mismatch for {code}"
