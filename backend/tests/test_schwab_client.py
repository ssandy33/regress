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
    def test_all_mapped_symbols(self):
        assert to_schwab_symbol("^GSPC") == "$SPX.X"
        assert to_schwab_symbol("^IXIC") == "$COMPX"
        assert to_schwab_symbol("^DJI") == "$DJI"
        assert to_schwab_symbol("^VIX") == "$VIX.X"
        assert to_schwab_symbol("GC=F") == "/GC"
        assert to_schwab_symbol("SI=F") == "/SI"
        assert to_schwab_symbol("PL=F") == "/PL"

    def test_passthrough_regular_tickers(self):
        assert to_schwab_symbol("AAPL") == "AAPL"
        assert to_schwab_symbol("MSFT") == "MSFT"
        assert to_schwab_symbol("TSLA") == "TSLA"


class TestGetQuote:
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


    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_get_quote_network_error_raises_client_error(self, mock_get, mock_tm_cls):
        mock_tm_cls.return_value.get_access_token.return_value = "token"
        mock_get.side_effect = httpx.RequestError("Connection refused")

        client = SchwabClient()
        with pytest.raises(SchwabClientError, match="request failed"):
            client.get_quote("AAPL")

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

    @patch("app.services.schwab_client.SchwabTokenManager")
    @patch("app.services.schwab_client.httpx.get")
    def test_get_price_history_network_error_raises_client_error(self, mock_get, mock_tm_cls):
        mock_tm_cls.return_value.get_access_token.return_value = "token"
        mock_get.side_effect = httpx.RequestError("Connection refused")

        client = SchwabClient()
        with pytest.raises(SchwabClientError, match="request failed"):
            client.get_price_history("AAPL", "2024-01-01", "2024-01-03")

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
