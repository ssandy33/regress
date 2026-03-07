"""Acceptance tests for Issue #6: Replace Price/Quote Fetching with Schwab (Phase 2).

Each test class maps to an acceptance criterion from the issue.
"""

import ast
import inspect
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.services.data_fetcher import (
    DataFetcher,
    DataFetchError,
    _df_to_json,
    _fetch_schwab,
    detect_source,
    ASSET_REGISTRY,
)
from app.services.cache import CacheService
from app.services.schwab_client import SchwabClient, SchwabClientError
from app.services.schwab_auth import SchwabAuthError
from app.services.options_scanner import OptionScanner, OptionScannerError
from app.models.schemas import MarketContext


def _sample_df(n=30, start="2024-01-01"):
    dates = pd.date_range(start=start, periods=n, freq="D")
    df = pd.DataFrame({"value": range(100, 100 + n)}, index=dates)
    df.index.name = "date"
    return df


def _mock_cache(has_fresh=False, has_stale=False):
    cache = MagicMock(spec=CacheService)
    df = _sample_df()
    data_json = _df_to_json(df)
    now = datetime.now(timezone.utc).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    cache.get.return_value = {
        "data": data_json, "fetched_at": now,
        "source_frequency": "daily", "source_name": "schwab",
    } if has_fresh else None

    cache.get_stale.return_value = {
        "data": data_json, "fetched_at": old,
        "source_frequency": "daily", "source_name": "schwab",
    } if has_stale else None

    return cache


class TestAC1_RegressionChartsLoadViaSchwab:
    """AC: Regression charts load correctly using Schwab price history."""

    @patch("app.services.data_fetcher._fetch_schwab")
    def test_fetch_routes_stock_through_schwab(self, mock_schwab):
        """DataFetcher.fetch() calls _fetch_schwab for stock tickers."""
        mock_schwab.return_value = _sample_df()
        cache = _mock_cache()
        fetcher = DataFetcher(cache)

        df, meta = fetcher.fetch("AAPL", "2024-01-01", "2024-01-30")

        mock_schwab.assert_called_once_with("AAPL", "2024-01-01", "2024-01-30")
        assert meta.source == "schwab"
        assert not meta.is_stale
        assert len(df) == 30

    @patch("app.services.data_fetcher._fetch_schwab")
    def test_fetch_routes_index_through_schwab(self, mock_schwab):
        """Index tickers (^GSPC) also route through Schwab."""
        mock_schwab.return_value = _sample_df()
        cache = _mock_cache()
        fetcher = DataFetcher(cache)

        _, meta = fetcher.fetch("^GSPC", "2024-01-01", "2024-01-30")

        mock_schwab.assert_called_once_with("^GSPC", "2024-01-01", "2024-01-30")
        assert meta.source == "schwab"

    @patch("app.services.data_fetcher._fetch_schwab")
    def test_fetch_routes_commodity_through_schwab(self, mock_schwab):
        """Commodity tickers (GC=F) also route through Schwab."""
        mock_schwab.return_value = _sample_df()
        cache = _mock_cache()
        fetcher = DataFetcher(cache)

        _, meta = fetcher.fetch("GC=F", "2024-01-01", "2024-01-30")

        mock_schwab.assert_called_once_with("GC=F", "2024-01-01", "2024-01-30")
        assert meta.source == "schwab"

    @patch("app.services.data_fetcher._fetch_schwab")
    def test_returned_dataframe_has_correct_shape(self, mock_schwab):
        """Returned DataFrame has date index and value column (chart-ready)."""
        mock_schwab.return_value = _sample_df()
        cache = _mock_cache()
        fetcher = DataFetcher(cache)

        df, meta = fetcher.fetch("MSFT", "2024-01-01", "2024-01-30")

        assert df.index.name == "date"
        assert "value" in df.columns
        assert meta.record_count == len(df)
        assert meta.date_range.start == df.index[0].strftime("%Y-%m-%d")
        assert meta.date_range.end == df.index[-1].strftime("%Y-%m-%d")

    def test_fred_still_routes_to_fred(self):
        """FRED series must NOT route through Schwab."""
        assert detect_source("FEDFUNDS") == "fred"
        assert detect_source("DGS10") == "fred"
        assert detect_source("UNRATE") == "fred"

    def test_zillow_still_routes_to_zillow(self):
        """Zillow ZIP codes must NOT route through Schwab."""
        assert detect_source("ZIP:10001") == "zillow"


class TestAC2_CurrentPriceViaSchwab:
    """AC: Current price in options scanner resolves via Schwab."""

    @patch("app.services.options_scanner.SchwabClient")
    def test_get_current_price_uses_schwab(self, mock_client_cls):
        """_get_current_price tries Schwab quote first."""
        mock_client_cls.return_value.get_quote.return_value = {"lastPrice": 185.50}
        scanner = OptionScanner()
        ticker_obj = MagicMock()

        price = scanner._get_current_price(ticker_obj, "AAPL")

        assert price == 185.50
        mock_client_cls.return_value.get_quote.assert_called_once_with("AAPL")

    @patch("app.services.options_scanner.SchwabClient")
    def test_get_current_price_falls_back_to_yfinance(self, mock_client_cls):
        """When Schwab fails, falls back to yfinance."""
        mock_client_cls.return_value.get_quote.side_effect = SchwabClientError("API down")
        scanner = OptionScanner()
        ticker_obj = MagicMock()
        fi = MagicMock()
        fi.last_price = 184.00
        ticker_obj.fast_info = fi

        price = scanner._get_current_price(ticker_obj, "AAPL")

        assert price == 184.00

    @patch("app.services.options_scanner.SchwabClient")
    def test_get_current_price_falls_back_on_auth_error(self, mock_client_cls):
        """SchwabAuthError also triggers yfinance fallback."""
        mock_client_cls.return_value.get_quote.side_effect = SchwabAuthError("Token expired")
        scanner = OptionScanner()
        ticker_obj = MagicMock()
        fi = MagicMock()
        fi.last_price = 183.00
        ticker_obj.fast_info = fi

        price = scanner._get_current_price(ticker_obj, "AAPL")

        assert price == 183.00


class TestAC3_VixDisplaysCorrectly:
    """AC: VIX displays correctly in market context."""

    @patch("app.services.options_scanner.SchwabClient")
    def test_vix_from_schwab_quote(self, mock_client_cls):
        """VIX is fetched via Schwab get_quote('^VIX') mapped to $VIX.X."""
        call_count = 0

        def mock_get_quote(ticker):
            nonlocal call_count
            call_count += 1
            if ticker == "^VIX":
                return {"lastPrice": 22.35}
            return {
                "52WeekHigh": 200.0,
                "52WeekLow": 150.0,
                "totalVolume": 3000000,
            }

        mock_client_cls.return_value.get_quote.side_effect = mock_get_quote
        scanner = OptionScanner()
        ticker_obj = MagicMock()
        ticker_obj.ticker = "AAPL"

        ctx = scanner._get_market_context(ticker_obj)

        assert ctx.vix == 22.35

    @patch("app.services.options_scanner.SchwabClient")
    def test_vix_fallback_to_yfinance(self, mock_client_cls):
        """When Schwab VIX fails, falls back to yfinance ^VIX."""
        mock_client_cls.return_value.get_quote.side_effect = SchwabClientError("down")
        scanner = OptionScanner()
        ticker_obj = MagicMock()

        mock_vix_fi = MagicMock()
        mock_vix_fi.last_price = 19.80

        with patch("app.services.options_scanner.yf.Ticker") as mock_yf_ticker:
            mock_yf_ticker.return_value.fast_info = mock_vix_fi
            ticker_obj.fast_info = MagicMock()
            ticker_obj.fast_info.year_high = 200.0
            ticker_obj.fast_info.year_low = 150.0

            ctx = scanner._get_market_context(ticker_obj)

        assert ctx.vix == 19.80

    @patch("app.services.options_scanner.SchwabClient")
    def test_52week_data_from_schwab(self, mock_client_cls):
        """52-week high/low comes from Schwab ticker quote."""
        def mock_get_quote(ticker):
            if ticker == "^VIX":
                return {"lastPrice": 18.0}
            return {
                "52WeekHigh": 195.50,
                "52WeekLow": 142.00,
                "totalVolume": 5000000,
            }

        mock_client_cls.return_value.get_quote.side_effect = mock_get_quote
        scanner = OptionScanner()
        ticker_obj = MagicMock()
        ticker_obj.ticker = "AAPL"

        ctx = scanner._get_market_context(ticker_obj)

        assert ctx.fifty_two_week_high == 195.50
        assert ctx.fifty_two_week_low == 142.00
        assert ctx.avg_volume == 5000000


class TestAC4_CacheBehaviorUnchanged:
    """AC: Cache behavior unchanged (TTL rules still apply)."""

    @patch("app.services.data_fetcher._fetch_schwab")
    def test_fresh_cache_prevents_schwab_call(self, mock_schwab):
        """Fresh cache entry should prevent any Schwab API call."""
        cache = _mock_cache(has_fresh=True)
        fetcher = DataFetcher(cache)

        _, meta = fetcher.fetch("AAPL", "2024-01-01", "2024-01-30")

        mock_schwab.assert_not_called()
        assert not meta.is_stale
        cache.get.assert_called_once_with("schwab:AAPL")

    @patch("app.services.data_fetcher._fetch_schwab")
    def test_cache_key_uses_schwab_prefix(self, mock_schwab):
        """Cache key for stock tickers is 'schwab:<ticker>'."""
        mock_schwab.return_value = _sample_df()
        cache = _mock_cache()
        fetcher = DataFetcher(cache)

        fetcher.fetch("AAPL", "2024-01-01", "2024-01-30")

        # Verify cache.get was called with schwab: prefix
        cache.get.assert_called_with("schwab:AAPL")
        # Verify cache.set stores with schwab: prefix and source
        cache.set.assert_called_once()
        args = cache.set.call_args
        assert args[0][0] == "schwab:AAPL"  # key
        assert args[0][3] == "schwab"  # source

    @patch("app.services.data_fetcher._fetch_schwab")
    def test_stale_cache_fallback_on_schwab_failure(self, mock_schwab):
        """SchwabClientError triggers stale cache fallback."""
        mock_schwab.side_effect = SchwabClientError("API error")
        cache = _mock_cache(has_stale=True)
        fetcher = DataFetcher(cache)

        _, meta = fetcher.fetch("AAPL", "2024-01-01", "2024-01-30")

        assert meta.is_stale

    @patch("app.services.data_fetcher._fetch_schwab")
    def test_stale_cache_fallback_on_auth_error(self, mock_schwab):
        """SchwabAuthError also triggers stale cache fallback."""
        mock_schwab.side_effect = SchwabAuthError("Token expired")
        cache = _mock_cache(has_stale=True)
        fetcher = DataFetcher(cache)

        _, meta = fetcher.fetch("AAPL", "2024-01-01", "2024-01-30")

        assert meta.is_stale

    @patch("app.services.data_fetcher._fetch_schwab")
    def test_no_cache_no_fallback_raises(self, mock_schwab):
        """When Schwab fails and no cache exists, error propagates."""
        mock_schwab.side_effect = SchwabClientError("API error")
        cache = _mock_cache(has_fresh=False, has_stale=False)
        fetcher = DataFetcher(cache)

        with pytest.raises(SchwabClientError):
            fetcher.fetch("AAPL", "2024-01-01", "2024-01-30")

    @patch("app.services.data_fetcher._fetch_schwab")
    def test_index_cache_key_uses_schwab_prefix(self, mock_schwab):
        """Index tickers also use schwab: prefix in cache keys."""
        mock_schwab.return_value = _sample_df()
        cache = _mock_cache()
        fetcher = DataFetcher(cache)

        fetcher.fetch("^GSPC", "2024-01-01", "2024-01-30")

        cache.get.assert_called_with("schwab:^GSPC")


class TestAC5_NoYfinanceInDataFetcher:
    """AC: No remaining yfinance calls in data_fetcher.py."""

    def test_no_yfinance_import(self):
        """data_fetcher.py must not import yfinance."""
        import app.services.data_fetcher as mod
        source = inspect.getsource(mod)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "yfinance", "data_fetcher.py still imports yfinance"
            if isinstance(node, ast.ImportFrom):
                assert node.module != "yfinance", "data_fetcher.py still imports from yfinance"

    def test_no_yf_references_in_source(self):
        """data_fetcher.py AST must not contain yf or yfinance name/attribute nodes."""
        import app.services.data_fetcher as mod
        source = inspect.getsource(mod)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id != "yf", "data_fetcher.py has 'yf' name reference"
                assert node.id != "yfinance", "data_fetcher.py has 'yfinance' name reference"
            if isinstance(node, ast.Attribute):
                assert node.attr != "yfinance", "data_fetcher.py has 'yfinance' attribute reference"

    def test_detect_source_returns_schwab_not_yfinance(self):
        """detect_source() must return 'schwab' for all non-FRED, non-Zillow tickers."""
        stock_tickers = ["AAPL", "MSFT", "TSLA", "GOOGL"]
        index_tickers = ["^GSPC", "^IXIC", "^DJI"]
        commodity_tickers = ["GC=F", "SI=F", "PL=F"]

        for ticker in stock_tickers + index_tickers + commodity_tickers:
            assert detect_source(ticker) == "schwab", f"detect_source('{ticker}') != 'schwab'"

    def test_asset_registry_uses_schwab_not_yfinance(self):
        """All non-FRED entries in ASSET_REGISTRY must use source='schwab'."""
        for entry in ASSET_REGISTRY:
            if entry["source"] != "fred":
                assert entry["source"] == "schwab", (
                    f"ASSET_REGISTRY entry '{entry['identifier']}' "
                    f"still uses source='{entry['source']}'"
                )


class TestAC6_ExistingTestsUpdated:
    """AC: Existing data fetcher tests updated for Schwab response fixtures."""

    def test_mock_cache_uses_schwab_source_name(self):
        """Test fixtures must use 'schwab' as source_name, not 'yfinance'."""
        from tests.test_data_fetcher import _make_mock_cache

        cache = _make_mock_cache(has_fresh=True)
        cached = cache.get.return_value
        assert cached["source_name"] == "schwab"

        cache = _make_mock_cache(has_stale=True)
        stale = cache.get_stale.return_value
        assert stale["source_name"] == "schwab"

