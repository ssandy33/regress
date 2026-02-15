import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pandas as pd
import requests as _requests
import yfinance as yf
from fredapi import Fred
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings, get_fred_api_key
from app.models.schemas import DataMeta, DateRange
from app.services.cache import CacheService

logger = logging.getLogger(__name__)

# --- Exceptions ---


class DataFetchError(Exception):
    pass


class InvalidTickerError(Exception):
    pass


class DataAlignmentError(Exception):
    pass


# --- Known FRED series ---

FRED_SERIES = {
    # Interest rates
    "FEDFUNDS", "DGS10", "DGS2", "MORTGAGE30US",
    # Case-Shiller national
    "CSUSHPINSA",
    # Case-Shiller 20-city
    "SPCS20RSA",
    # Case-Shiller metros (20 cities)
    "PHXRNSA", "LXXRNSA", "SFXRNSA", "NYXRNSA", "MIXRNSA", "LVXRNSA",
    "DNXRNSA", "SEXRNSA", "TPXRNSA", "DAXRNSA", "CHXRNSA", "ATXRNSA",
    "BOXRNSA", "CLXRNSA", "DEXRNSA", "MNXRNSA", "POXRNSA", "SDXRNSA",
    "WDXRNSA", "CEXRNSA",
    # FHFA HPI
    "USSTHPI",
}

# --- Asset registry for search ---

ASSET_REGISTRY = [
    # FRED - Interest rates
    {"identifier": "FEDFUNDS", "name": "Federal Funds Rate", "source": "fred", "category": "interest_rates"},
    {"identifier": "DGS10", "name": "10-Year Treasury Yield", "source": "fred", "category": "interest_rates"},
    {"identifier": "DGS2", "name": "2-Year Treasury Yield", "source": "fred", "category": "interest_rates"},
    {"identifier": "MORTGAGE30US", "name": "30-Year Fixed Mortgage Rate", "source": "fred", "category": "interest_rates"},
    # FRED - Housing
    {"identifier": "CSUSHPINSA", "name": "Case-Shiller National Home Price Index", "source": "fred", "category": "housing"},
    {"identifier": "SPCS20RSA", "name": "Case-Shiller 20-City Composite", "source": "fred", "category": "housing"},
    {"identifier": "USSTHPI", "name": "FHFA House Price Index", "source": "fred", "category": "housing"},
    {"identifier": "PHXRNSA", "name": "Case-Shiller Phoenix", "source": "fred", "category": "housing"},
    {"identifier": "LXXRNSA", "name": "Case-Shiller Los Angeles", "source": "fred", "category": "housing"},
    {"identifier": "SFXRNSA", "name": "Case-Shiller San Francisco", "source": "fred", "category": "housing"},
    {"identifier": "NYXRNSA", "name": "Case-Shiller New York", "source": "fred", "category": "housing"},
    {"identifier": "MIXRNSA", "name": "Case-Shiller Miami", "source": "fred", "category": "housing"},
    {"identifier": "LVXRNSA", "name": "Case-Shiller Las Vegas", "source": "fred", "category": "housing"},
    {"identifier": "DNXRNSA", "name": "Case-Shiller Denver", "source": "fred", "category": "housing"},
    {"identifier": "SEXRNSA", "name": "Case-Shiller Seattle", "source": "fred", "category": "housing"},
    {"identifier": "TPXRNSA", "name": "Case-Shiller Tampa", "source": "fred", "category": "housing"},
    {"identifier": "DAXRNSA", "name": "Case-Shiller Dallas", "source": "fred", "category": "housing"},
    {"identifier": "CHXRNSA", "name": "Case-Shiller Chicago", "source": "fred", "category": "housing"},
    {"identifier": "ATXRNSA", "name": "Case-Shiller Atlanta", "source": "fred", "category": "housing"},
    {"identifier": "BOXRNSA", "name": "Case-Shiller Boston", "source": "fred", "category": "housing"},
    {"identifier": "CLXRNSA", "name": "Case-Shiller Cleveland", "source": "fred", "category": "housing"},
    {"identifier": "DEXRNSA", "name": "Case-Shiller Detroit", "source": "fred", "category": "housing"},
    {"identifier": "MNXRNSA", "name": "Case-Shiller Minneapolis", "source": "fred", "category": "housing"},
    {"identifier": "POXRNSA", "name": "Case-Shiller Portland", "source": "fred", "category": "housing"},
    {"identifier": "SDXRNSA", "name": "Case-Shiller San Diego", "source": "fred", "category": "housing"},
    {"identifier": "WDXRNSA", "name": "Case-Shiller Washington DC", "source": "fred", "category": "housing"},
    {"identifier": "CEXRNSA", "name": "Case-Shiller Charlotte", "source": "fred", "category": "housing"},
    # Market indices
    {"identifier": "^GSPC", "name": "S&P 500", "source": "yfinance", "category": "indices"},
    {"identifier": "^IXIC", "name": "NASDAQ Composite", "source": "yfinance", "category": "indices"},
    {"identifier": "^DJI", "name": "Dow Jones Industrial Average", "source": "yfinance", "category": "indices"},
    # Metals
    {"identifier": "GC=F", "name": "Gold Futures", "source": "yfinance", "category": "commodities"},
    {"identifier": "SI=F", "name": "Silver Futures", "source": "yfinance", "category": "commodities"},
    {"identifier": "PL=F", "name": "Platinum Futures", "source": "yfinance", "category": "commodities"},
]

# --- Thread pool for sync yfinance calls ---

_executor = ThreadPoolExecutor(max_workers=4)

# --- FRED rate limiter ---

_fred_lock = threading.Lock()
_fred_last_call = 0.0
_FRED_MIN_INTERVAL = 0.5  # 500ms between calls


def _fred_throttle():
    global _fred_last_call
    with _fred_lock:
        now = time.monotonic()
        elapsed = now - _fred_last_call
        if elapsed < _FRED_MIN_INTERVAL:
            time.sleep(_FRED_MIN_INTERVAL - elapsed)
        _fred_last_call = time.monotonic()


# --- Source detection ---


def detect_source(identifier: str) -> str:
    """Determine data source for an identifier."""
    if identifier.upper().startswith("ZIP:"):
        return "zillow"
    if identifier.upper() in FRED_SERIES:
        return "fred"
    return "yfinance"


# --- Fetcher functions with retry ---


def _fetch_yahoo_direct(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Fetch data directly from Yahoo Finance API (bypasses yfinance library)."""
    start_ts = int(pd.Timestamp(start).timestamp())
    end_ts = int(pd.Timestamp(end).timestamp())
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?period1={start_ts}&period2={end_ts}&interval=1d"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    resp = _requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    chart = data.get("chart", {}).get("result")
    if not chart:
        raise InvalidTickerError(f"No data returned for ticker '{ticker}'")

    timestamps = chart[0].get("timestamp", [])
    closes = chart[0]["indicators"]["quote"][0].get("close", [])
    if not timestamps:
        raise InvalidTickerError(f"No data returned for ticker '{ticker}'")

    df = pd.DataFrame({"date": pd.to_datetime(timestamps, unit="s"), "value": closes})
    df = df.dropna(subset=["value"])
    df = df.set_index("date")
    df.index = df.index.normalize()
    df.index.name = "date"
    return df


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=10),
    retry=retry_if_exception_type(DataFetchError),
    reraise=True,
)
def _fetch_yfinance(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Fetch data from Yahoo Finance. Tries yfinance library first, falls back to direct API."""
    # Attempt 1: yfinance library
    try:
        t = yf.Ticker(ticker)
        df = t.history(start=start, end=end)
        if not df.empty:
            result = pd.DataFrame({"value": df["Close"]})
            result.index = pd.to_datetime(result.index).tz_localize(None)
            result.index.name = "date"
            return result
    except Exception as e:
        logger.debug(f"yfinance library failed for '{ticker}': {e}")

    # Attempt 2: Direct Yahoo API (avoids query2 rate limits)
    try:
        return _fetch_yahoo_direct(ticker, start, end)
    except InvalidTickerError:
        raise
    except Exception as e:
        raise DataFetchError(f"Yahoo Finance error for '{ticker}': {e}") from e


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _fetch_fred(series_id: str, start: str, end: str) -> pd.DataFrame:
    """Fetch data from FRED API."""
    api_key = get_fred_api_key()
    if not api_key:
        raise DataFetchError("FRED_API_KEY not configured. Set it in Settings or .env file.")

    _fred_throttle()

    try:
        fred = Fred(api_key=api_key)
        series = fred.get_series(series_id, observation_start=start, observation_end=end)
        if series.empty:
            raise DataFetchError(f"No FRED data for series '{series_id}'")
        result = pd.DataFrame({"value": series})
        result.index = pd.to_datetime(result.index)
        result.index.name = "date"
        result = result.dropna()
        return result
    except DataFetchError:
        raise
    except Exception as e:
        raise DataFetchError(f"FRED error for '{series_id}': {e}") from e


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _fetch_zillow_csv() -> pd.DataFrame:
    """Download the full Zillow ZHVI CSV."""
    url = "https://files.zillowstatic.com/research/public_csvs/zhvi/Zip_zhvi_uf_sm_sa_month.csv"
    try:
        df = pd.read_csv(url)
        return df
    except Exception as e:
        raise DataFetchError(f"Zillow CSV download failed: {e}") from e


def _parse_zillow_for_zip(raw_df: pd.DataFrame, zip_code: str, start: str, end: str) -> pd.DataFrame:
    """Extract time series for a specific zip code from the Zillow CSV."""
    row = raw_df[raw_df["RegionName"].astype(str).str.zfill(5) == str(zip_code).zfill(5)]
    if row.empty:
        raise InvalidTickerError(f"No Zillow data for zip code '{zip_code}'")

    row = row.iloc[0]
    # Date columns start after the metadata columns
    meta_cols = {"RegionID", "SizeRank", "RegionName", "RegionType", "StateName", "State", "City", "Metro", "CountyName"}
    date_cols = [c for c in raw_df.columns if c not in meta_cols]

    values = []
    for col in date_cols:
        try:
            dt = pd.to_datetime(col)
            val = row[col]
            if pd.notna(val):
                values.append({"date": dt, "value": float(val)})
        except (ValueError, TypeError):
            continue

    if not values:
        raise DataFetchError(f"No valid data points for zip '{zip_code}'")

    result = pd.DataFrame(values).set_index("date").sort_index()

    # Filter date range
    if start:
        result = result[result.index >= pd.to_datetime(start)]
    if end:
        result = result[result.index <= pd.to_datetime(end)]

    return result


def _df_to_json(df: pd.DataFrame) -> str:
    """Serialize a DataFrame to JSON for caching."""
    records = []
    for idx, row in df.iterrows():
        records.append({"date": idx.isoformat(), "value": float(row["value"])})
    return json.dumps(records)


def _json_to_df(data_json: str) -> pd.DataFrame:
    """Deserialize cached JSON back to DataFrame."""
    records = json.loads(data_json)
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df["value"] = df["value"].astype(float)
    return df


def _infer_frequency(df: pd.DataFrame) -> str:
    """Infer data frequency from a DataFrame."""
    if len(df) < 2:
        return "daily"
    diffs = pd.Series(df.index).diff().dropna()
    median_days = diffs.dt.days.median()
    if median_days <= 7:
        return "daily"
    elif median_days <= 45:
        return "monthly"
    return "quarterly"


def _build_meta(
    df: pd.DataFrame, source: str, frequency: str, fetched_at: str, is_stale: bool
) -> DataMeta:
    """Build a DataMeta from a DataFrame."""
    return DataMeta(
        source=source,
        frequency=frequency,
        fetched_at=fetched_at,
        is_stale=is_stale,
        record_count=len(df),
        date_range=DateRange(
            start=df.index[0].strftime("%Y-%m-%d"),
            end=df.index[-1].strftime("%Y-%m-%d"),
        ),
    )


# --- Public API ---


class DataFetcher:
    def __init__(self, cache: CacheService):
        self.cache = cache

    def fetch(self, identifier: str, start: str, end: str) -> tuple[pd.DataFrame, DataMeta]:
        """Fetch data for an identifier, using cache-first pattern.

        Returns (DataFrame, DataMeta).
        """
        source = detect_source(identifier)

        # Route Zillow ZIP codes to fetch_zillow
        if source == "zillow":
            zip_code = identifier.split(":", 1)[1] if ":" in identifier else identifier
            return self.fetch_zillow(zip_code, start, end)

        asset_key = f"{source}:{identifier}"

        # 1. Check fresh cache
        cached = self.cache.get(asset_key)
        if cached is not None:
            df = _json_to_df(cached["data"])
            # Filter to requested range
            if start:
                df = df[df.index >= pd.to_datetime(start)]
            if end:
                df = df[df.index <= pd.to_datetime(end)]
            meta = _build_meta(
                df, source, cached["source_frequency"],
                cached["fetched_at"], is_stale=False,
            )
            return df, meta

        # 2. Fetch from source
        try:
            if source == "fred":
                df = _fetch_fred(identifier.upper(), start, end)
            else:
                future = _executor.submit(_fetch_yfinance, identifier, start, end)
                df = future.result(timeout=30)

            frequency = _infer_frequency(df)
            data_json = _df_to_json(df)
            self.cache.set(asset_key, data_json, frequency, source)

            fetched_at = datetime.now(timezone.utc).isoformat()
            meta = _build_meta(df, source, frequency, fetched_at, is_stale=False)
            return df, meta

        except (InvalidTickerError, DataFetchError):
            # 3. Fall back to stale cache
            stale = self.cache.get_stale(asset_key)
            if stale is not None:
                df = _json_to_df(stale["data"])
                if start:
                    df = df[df.index >= pd.to_datetime(start)]
                if end:
                    df = df[df.index <= pd.to_datetime(end)]
                meta = _build_meta(
                    df, source, stale["source_frequency"],
                    stale["fetched_at"], is_stale=True,
                )
                logger.warning(f"Using stale cache for {asset_key}")
                return df, meta

            # 4. No cache, re-raise
            raise

    def fetch_zillow(self, zip_code: str, start: str, end: str) -> tuple[pd.DataFrame, DataMeta]:
        """Fetch Zillow ZHVI data for a zip code."""
        csv_cache_key = "zillow:__csv__"
        asset_key = f"zillow:{zip_code}"

        # Check if we have a fresh parsed result for this zip
        cached = self.cache.get(asset_key)
        if cached is not None:
            df = _json_to_df(cached["data"])
            if start:
                df = df[df.index >= pd.to_datetime(start)]
            if end:
                df = df[df.index <= pd.to_datetime(end)]
            meta = _build_meta(
                df, "zillow", "monthly", cached["fetched_at"], is_stale=False,
            )
            return df, meta

        # Try to fetch the CSV
        raw_df = None
        try:
            raw_df = _fetch_zillow_csv()
            # Cache the entire CSV as JSON
            self.cache.set(csv_cache_key, raw_df.to_json(), "monthly", "zillow")
        except DataFetchError:
            # Fall back to cached CSV
            stale = self.cache.get_stale(csv_cache_key)
            if stale is not None:
                raw_df = pd.read_json(stale["data"])
                logger.warning("Using stale cached Zillow CSV")
            else:
                raise

        # Parse for the specific zip code
        df = _parse_zillow_for_zip(raw_df, zip_code, start, end)
        frequency = "monthly"
        data_json = _df_to_json(df)
        self.cache.set(asset_key, data_json, frequency, "zillow")

        fetched_at = datetime.now(timezone.utc).isoformat()
        meta = _build_meta(df, "zillow", frequency, fetched_at, is_stale=False)
        return df, meta
