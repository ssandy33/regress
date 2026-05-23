import logging
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import httpx

from app.services.schwab_client import (
    SchwabClient,
    SchwabClientError,
    to_schwab_symbol,
    SCHWAB_SYMBOL_MAP,
)
from app.services.schwab_auth import SchwabAuthError


class TestSymbolMapping:
    @pytest.mark.unit
    def test_all_mapped_symbols(self):
        assert to_schwab_symbol("^GSPC") == "$SPX.X"
        assert to_schwab_symbol("^IXIC") == "$COMPX"
        assert to_schwab_symbol("^DJI") == "$DJI"
        assert to_schwab_symbol("^VIX") == "$VIX.X"
        assert to_schwab_symbol("GC=F") == "/GC"
        assert to_schwab_symbol("SI=F") == "/SI"
        assert to_schwab_symbol("PL=F") == "/PL"

    @pytest.mark.unit
    def test_passthrough_regular_tickers(self):
        assert to_schwab_symbol("AAPL") == "AAPL"
        assert to_schwab_symbol("MSFT") == "MSFT"
        assert to_schwab_symbol("TSLA") == "TSLA"


class TestGetQuote:
    @pytest.mark.unit
    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_get_quote_success(self, mock_get, mock_tm_cls):
        mock_tm_cls.return_value.get_access_token.return_value = "test-token"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "AAPL": {
                "quote": {
                    "lastPrice": 150.0,
                    "52WeekHigh": 180.0,
                    "52WeekLow": 120.0,
                    "totalVolume": 5000000,
                }
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = SchwabClient()
        quote = client.get_quote("AAPL")

        assert quote["lastPrice"] == 150.0
        assert quote["52WeekHigh"] == 180.0
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args
        assert call_kwargs.kwargs["params"] == {"symbols": "AAPL"}
        assert "Bearer test-token" in call_kwargs.kwargs["headers"]["Authorization"]

    @pytest.mark.unit
    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_get_quote_maps_index_symbol(self, mock_get, mock_tm_cls):
        mock_tm_cls.return_value.get_access_token.return_value = "test-token"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "$VIX.X": {"quote": {"lastPrice": 18.5}}
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = SchwabClient()
        quote = client.get_quote("^VIX")
        assert quote["lastPrice"] == 18.5
        assert mock_get.call_args.kwargs["params"] == {"symbols": "$VIX.X"}

    @pytest.mark.unit
    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_get_quote_401_raises_auth_error(self, mock_get, mock_tm_cls):
        mock_tm_cls.return_value.get_access_token.return_value = "bad-token"
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 401
        mock_get.return_value = mock_resp
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=mock_resp
        )

        client = SchwabClient()
        with pytest.raises(SchwabAuthError):
            client.get_quote("AAPL")

    @pytest.mark.unit
    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_get_quote_500_raises_client_error(self, mock_get, mock_tm_cls):
        mock_tm_cls.return_value.get_access_token.return_value = "token"
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 500
        mock_get.return_value = mock_resp
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=mock_resp
        )

        client = SchwabClient()
        with pytest.raises(SchwabClientError):
            client.get_quote("AAPL")

    @pytest.mark.unit
    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_get_quote_missing_symbol_raises(self, mock_get, mock_tm_cls):
        mock_tm_cls.return_value.get_access_token.return_value = "token"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = SchwabClient()
        with pytest.raises(SchwabClientError, match="No quote data"):
            client.get_quote("AAPL")


    @pytest.mark.unit
    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_get_quote_network_error_raises_client_error(self, mock_get, mock_tm_cls):
        mock_tm_cls.return_value.get_access_token.return_value = "token"
        mock_get.side_effect = httpx.RequestError("Connection refused")

        client = SchwabClient()
        with pytest.raises(SchwabClientError, match="Unable to reach Schwab API"):
            client.get_quote("AAPL")

    @pytest.mark.unit
    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_get_quote_401_invalidates_token(self, mock_get, mock_tm_cls):
        mock_tm = mock_tm_cls.return_value
        mock_tm.get_access_token.return_value = "bad-token"
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 401
        mock_get.return_value = mock_resp
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=mock_resp
        )

        client = SchwabClient()
        with pytest.raises(SchwabAuthError):
            client.get_quote("AAPL")

        mock_tm.invalidate_token.assert_called_once()


class TestGetPriceHistory:
    @pytest.mark.unit
    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_get_price_history_success(self, mock_get, mock_tm_cls):
        mock_tm_cls.return_value.get_access_token.return_value = "token"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candles": [
                {"datetime": 1704067200000, "close": 100.0, "open": 99.0, "high": 101.0, "low": 98.0, "volume": 1000},
                {"datetime": 1704153600000, "close": 102.0, "open": 100.0, "high": 103.0, "low": 99.0, "volume": 1200},
                {"datetime": 1704240000000, "close": 101.5, "open": 102.0, "high": 104.0, "low": 100.0, "volume": 900},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = SchwabClient()
        df = client.get_price_history("AAPL", "2024-01-01", "2024-01-03")

        assert len(df) == 3
        assert "value" in df.columns
        assert df.index.name == "date"
        assert df["value"].iloc[0] == 100.0
        assert df["value"].iloc[1] == 102.0

    @pytest.mark.unit
    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_get_price_history_empty_candles_raises(self, mock_get, mock_tm_cls):
        mock_tm_cls.return_value.get_access_token.return_value = "token"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"candles": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = SchwabClient()
        with pytest.raises(SchwabClientError, match="No price history"):
            client.get_price_history("BADTICKER", "2024-01-01", "2024-01-03")

    @pytest.mark.unit
    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_get_price_history_401_raises_auth_error(self, mock_get, mock_tm_cls):
        mock_tm_cls.return_value.get_access_token.return_value = "bad-token"
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 401
        mock_get.return_value = mock_resp
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=mock_resp
        )

        client = SchwabClient()
        with pytest.raises(SchwabAuthError):
            client.get_price_history("AAPL", "2024-01-01", "2024-01-03")

    @pytest.mark.unit
    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_get_price_history_maps_symbol(self, mock_get, mock_tm_cls):
        mock_tm_cls.return_value.get_access_token.return_value = "token"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candles": [
                {"datetime": 1704067200000, "close": 4800.0, "open": 4790.0, "high": 4810.0, "low": 4780.0, "volume": 0},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = SchwabClient()
        df = client.get_price_history("^GSPC", "2024-01-01", "2024-01-01")

        assert len(df) == 1
        # Verify the symbol was mapped
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs["params"]["symbol"] == "$SPX.X"

    @pytest.mark.unit
    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_get_price_history_network_error_raises_client_error(self, mock_get, mock_tm_cls):
        mock_tm_cls.return_value.get_access_token.return_value = "token"
        mock_get.side_effect = httpx.RequestError("Connection refused")

        client = SchwabClient()
        with pytest.raises(SchwabClientError, match="Unable to reach Schwab API"):
            client.get_price_history("AAPL", "2024-01-01", "2024-01-03")

    @pytest.mark.unit
    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_get_price_history_401_invalidates_token(self, mock_get, mock_tm_cls):
        mock_tm = mock_tm_cls.return_value
        mock_tm.get_access_token.return_value = "bad-token"
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 401
        mock_get.return_value = mock_resp
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=mock_resp
        )

        client = SchwabClient()
        with pytest.raises(SchwabAuthError):
            client.get_price_history("AAPL", "2024-01-01", "2024-01-03")

        mock_tm.invalidate_token.assert_called_once()


HANDLER_CALL_ARGS = {
    "get_quote": ("AAPL",),
    "get_option_chain": ("AAPL",),
    "get_price_history": ("AAPL", "2024-01-01", "2024-01-03"),
    "get_account_numbers": (),
    "get_accounts": (),
    "get_transactions": ("abc123", "2024-01-01", "2025-03-01"),
}


class TestGetTransactions:
    """Tests for get_transactions request parameters (issue #119)."""

    @pytest.mark.unit
    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_get_transactions_passes_trade_and_receive_and_deliver_types(
        self, mock_get, mock_tm_cls
    ):
        """Both TRADE and RECEIVE_AND_DELIVER types are sent so assignments are returned."""
        mock_tm_cls.return_value.get_access_token.return_value = "token"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = SchwabClient()
        client.get_transactions("abc123", "2024-01-01", "2024-03-01")

        params = mock_get.call_args.kwargs["params"]
        assert params["types"] == "TRADE,RECEIVE_AND_DELIVER"
        assert "startDate" in params
        assert "endDate" in params

    @pytest.mark.unit
    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_get_transactions_returns_response_json(self, mock_get, mock_tm_cls):
        """Response JSON is returned as-is for the importer to map."""
        mock_tm_cls.return_value.get_access_token.return_value = "token"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"type": "TRADE"}, {"type": "RECEIVE_AND_DELIVER"}]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = SchwabClient()
        result = client.get_transactions("abc123", "2024-01-01", "2024-03-01")
        assert result == [{"type": "TRADE"}, {"type": "RECEIVE_AND_DELIVER"}]


class TestErrorResponseLogging:
    """Tests for logging Schwab error response bodies (issue #73)."""

    @pytest.mark.unit
    @pytest.mark.parametrize("handler_name", list(HANDLER_CALL_ARGS.keys()))
    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_error_logs_response_body(self, mock_get, mock_tm_cls, caplog, handler_name):
        """Error handler logs the response body for debugging."""
        mock_tm_cls.return_value.get_access_token.return_value = "token"
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 400
        mock_resp.text = '{"error": "date range too large"}'
        mock_get.return_value = mock_resp
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400 Bad Request", request=MagicMock(), response=mock_resp
        )

        client = SchwabClient()
        with caplog.at_level(logging.ERROR, logger="app.services.schwab_client"):
            with pytest.raises(SchwabClientError):
                getattr(client, handler_name)(*HANDLER_CALL_ARGS[handler_name])

        assert any("date range too large" in r.message for r in caplog.records)

    @pytest.mark.unit
    @pytest.mark.parametrize("handler_name", list(HANDLER_CALL_ARGS.keys()))
    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_error_message_stays_sanitized(self, mock_get, mock_tm_cls, handler_name):
        """SchwabClientError message must not leak the response body."""
        mock_tm_cls.return_value.get_access_token.return_value = "token"
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 400
        mock_resp.text = '{"error": "secret internal detail"}'
        mock_get.return_value = mock_resp
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400 Bad Request", request=MagicMock(), response=mock_resp
        )

        client = SchwabClient()
        with pytest.raises(SchwabClientError) as exc_info:
            getattr(client, handler_name)(*HANDLER_CALL_ARGS[handler_name])

        assert "secret internal detail" not in str(exc_info.value)


class TestPeriodTypeAndRetryOn4xx:
    """Issue #286: pricehistory must include periodType=year; 4xx must not be retried."""

    @pytest.mark.unit
    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_get_price_history_includes_period_type_year(self, mock_get, mock_tm_cls):
        mock_tm_cls.return_value.get_access_token.return_value = "token"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candles": [{"datetime": 1704067200000, "close": 100.0}]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        SchwabClient().get_price_history("AAPL", "2024-01-01", "2024-01-03")

        params = mock_get.call_args.kwargs["params"]
        assert params["periodType"] == "year"
        assert params["frequencyType"] == "daily"
        assert params["frequency"] == 1

    @pytest.mark.unit
    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_get_price_history_does_not_retry_on_4xx(self, mock_get, mock_tm_cls):
        mock_tm_cls.return_value.get_access_token.return_value = "token"
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 400
        mock_resp.text = '{"errors": [{"detail": "bad request"}]}'
        mock_get.return_value = mock_resp
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400 Bad Request", request=MagicMock(), response=mock_resp
        )

        client = SchwabClient()
        with pytest.raises(SchwabClientError):
            client.get_price_history("AAPL", "2024-01-01", "2024-01-03")

        assert mock_get.call_count == 1

    @pytest.mark.unit
    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_get_price_history_still_retries_on_5xx(self, mock_get, mock_tm_cls):
        mock_tm_cls.return_value.get_access_token.return_value = "token"

        # First call: 503. Second call: 200 with valid candle.
        err_resp = MagicMock(spec=httpx.Response)
        err_resp.status_code = 503
        err_resp.text = "Service Unavailable"
        err_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "503", request=MagicMock(), response=err_resp
        )

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {
            "candles": [{"datetime": 1704067200000, "close": 100.0}]
        }
        ok_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [err_resp, ok_resp]

        df = SchwabClient().get_price_history("AAPL", "2024-01-01", "2024-01-03")

        assert mock_get.call_count == 2
        assert len(df) == 1
        assert df["value"].iloc[0] == 100.0

    @pytest.mark.unit
    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_get_quote_does_not_retry_on_4xx(self, mock_get, mock_tm_cls):
        """Cross-handler regression: 4xx no-retry applies to every @retry-decorated method."""
        mock_tm_cls.return_value.get_access_token.return_value = "token"
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 400
        mock_resp.text = '{"errors": []}'
        mock_get.return_value = mock_resp
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400 Bad Request", request=MagicMock(), response=mock_resp
        )

        client = SchwabClient()
        with pytest.raises(SchwabClientError):
            client.get_quote("AAPL")

        assert mock_get.call_count == 1
