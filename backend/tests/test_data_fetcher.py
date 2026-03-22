import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.services.cache import CacheService
from app.services.data_fetcher import (
    DataFetcher,
    DataFetchError,
    InvalidTickerError,
    detect_source,
    _df_to_json,
    _json_to_df,
)


def _make_sample_df(n=10, start="2024-01-01"):
    """Create a sample DataFrame for testing."""
    dates = pd.date_range(start=start, periods=n, freq="D")
    return pd.DataFrame({"value": range(100, 100 + n)}, index=dates)


def _make_mock_cache(has_fresh=False, has_stale=False, sample_df=None):
    """Create a mock CacheService."""
    cache = MagicMock(spec=CacheService)
    df = sample_df or _make_sample_df()
    data_json = _df_to_json(df)
    now = datetime.now(timezone.utc).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    if has_fresh:
        cache.get.return_value = {
            "data": data_json,
            "fetched_at": now,
            "source_frequency": "daily",
            "source_name": "schwab",
        }
    else:
        cache.get.return_value = None

    if has_stale:
        cache.get_stale.return_value = {
            "data": data_json,
            "fetched_at": old,
            "source_frequency": "daily",
            "source_name": "schwab",
        }
    else:
        cache.get_stale.return_value = None

    return cache


class TestSourceDetection:
    def test_fred_series(self):
        assert detect_source("FEDFUNDS") == "fred"
        assert detect_source("DGS10") == "fred"
        assert detect_source("CSUSHPINSA") == "fred"

    def test_schwab_default(self):
        assert detect_source("AAPL") == "schwab"
        assert detect_source("^GSPC") == "schwab"
        assert detect_source("GC=F") == "schwab"


class TestSerializationRoundtrip:
    def test_roundtrip(self):
        df = _make_sample_df()
        json_str = _df_to_json(df)
        restored = _json_to_df(json_str)
        assert len(restored) == len(df)
        assert list(restored["value"]) == list(df["value"])


class TestDataFetcherCacheHit:
    def test_cache_hit_no_api_call(self):
        """When cache is fresh, no external API should be called."""
        cache = _make_mock_cache(has_fresh=True)
        fetcher = DataFetcher(cache)

        with patch("app.services.data_fetcher._fetch_schwab") as mock_schwab:
            df, meta = fetcher.fetch("AAPL", "2024-01-01", "2024-01-10")

            mock_schwab.assert_not_called()
            assert not meta.is_stale
            assert meta.source == "schwab"
            assert len(df) > 0


class TestDataFetcherCacheMiss:
    @patch("app.services.data_fetcher._fetch_schwab")
    def test_cache_miss_fetches_and_caches(self, mock_fetch_schwab):
        """When cache is empty, should fetch from API and populate cache."""
        cache = _make_mock_cache(has_fresh=False, has_stale=False)
        fetcher = DataFetcher(cache)

        sample_df = _make_sample_df()
        mock_fetch_schwab.return_value = sample_df

        df, meta = fetcher.fetch("AAPL", "2024-01-01", "2024-01-10")

        mock_fetch_schwab.assert_called_once_with("AAPL", "2024-01-01", "2024-01-10")
        cache.set.assert_called_once()
        assert not meta.is_stale


class TestDataFetcherFallbackToStale:
    @patch("app.services.data_fetcher._fetch_schwab")
    def test_api_failure_uses_stale_cache(self, mock_fetch_schwab):
        """When API fails but stale cache exists, return stale data."""
        cache = _make_mock_cache(has_fresh=False, has_stale=True)
        fetcher = DataFetcher(cache)

        mock_fetch_schwab.side_effect = DataFetchError("API down")

        df, meta = fetcher.fetch("AAPL", "2024-01-01", "2024-01-10")

        assert meta.is_stale
        assert len(df) > 0

    @patch("app.services.data_fetcher._fetch_schwab")
    def test_auth_error_uses_stale_cache(self, mock_fetch_schwab):
        """When Schwab auth fails but stale cache exists, return stale data."""
        from app.services.schwab_auth import SchwabAuthCode, SchwabAuthError
        cache = _make_mock_cache(has_fresh=False, has_stale=True)
        fetcher = DataFetcher(cache)

        mock_fetch_schwab.side_effect = SchwabAuthError("Token expired", code=SchwabAuthCode.TOKEN_EXPIRED)

        df, meta = fetcher.fetch("AAPL", "2024-01-01", "2024-01-10")

        assert meta.is_stale
        assert len(df) > 0


class TestDataFetcherNoFallback:
    @patch("app.services.data_fetcher._fetch_schwab")
    def test_api_failure_no_cache_raises(self, mock_fetch_schwab):
        """When API fails and no cache exists, should raise error."""
        cache = _make_mock_cache(has_fresh=False, has_stale=False)
        fetcher = DataFetcher(cache)

        mock_fetch_schwab.side_effect = DataFetchError("API down")

        with pytest.raises(DataFetchError):
            fetcher.fetch("AAPL", "2024-01-01", "2024-01-10")
