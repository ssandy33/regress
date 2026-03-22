"""Schwab Market Data API client.

Wraps quote and price history endpoints using SchwabTokenManager for auth.
"""

import logging

import httpx
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.services.schwab_auth import SchwabAuthError, SchwabTokenManager

logger = logging.getLogger(__name__)

SCHWAB_SYMBOL_MAP = {
    "^GSPC": "$SPX.X",
    "^IXIC": "$COMPX",
    "^DJI": "$DJI",
    "^VIX": "$VIX.X",
    "GC=F": "/GC",
    "SI=F": "/SI",
    "PL=F": "/PL",
}


class SchwabClientError(Exception):
    """Raised for non-auth Schwab API errors."""
    pass


SCHWAB_TRANSPORT_ERROR_MSG = "Unable to reach Schwab API. Please try again later."


def to_schwab_symbol(ticker: str) -> str:
    """Map common symbol formats to Schwab equivalents. Passthrough for regular tickers."""
    return SCHWAB_SYMBOL_MAP.get(ticker, ticker)


def _to_iso8601(date_str: str) -> str:
    """Convert YYYY-MM-DD to ISO 8601 UTC timestamp for Schwab Trader API."""
    if "T" in date_str:
        return date_str
    return f"{date_str}T00:00:00.000Z"


class SchwabClient:
    BASE_URL = "https://api.schwabapi.com/marketdata/v1"
    TRADER_BASE_URL = "https://api.schwabapi.com/trader/v1"

    def _headers(self) -> dict:
        token = SchwabTokenManager().get_access_token()
        return {"Authorization": f"Bearer {token}"}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception_type(SchwabClientError),
        reraise=True,
    )
    def get_quote(self, ticker: str) -> dict:
        """Get a real-time quote for a ticker.

        Returns dict with keys like lastPrice, 52WeekHigh, 52WeekLow, totalVolume.
        """
        symbol = to_schwab_symbol(ticker)
        url = f"{self.BASE_URL}/quotes"
        try:
            resp = httpx.get(
                url,
                params={"symbols": symbol},
                headers=self._headers(),
                timeout=15,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                SchwabTokenManager().invalidate_token()
                raise SchwabAuthError("Schwab API returned 401 — token may be invalid") from e
            logger.error("Schwab quote API error: %s — response body: %s", e, e.response.text)
            raise SchwabClientError("Schwab quote API error") from e
        except httpx.RequestError as e:
            logger.error("Schwab quote request error: %s", e)
            raise SchwabClientError(SCHWAB_TRANSPORT_ERROR_MSG) from e

        data = resp.json()
        if symbol not in data:
            raise SchwabClientError(f"No quote data returned for '{ticker}' (mapped to '{symbol}')")

        quote = data[symbol].get("quote", data[symbol])
        return quote

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception_type(SchwabClientError),
        reraise=True,
    )
    def get_option_chain(
        self,
        ticker: str,
        contract_type: str = "ALL",
        from_date: str | None = None,
        to_date: str | None = None,
        strike_count: int | None = None,
    ) -> dict:
        """Fetch option chain from Schwab /marketdata/v1/chains.

        Args:
            ticker: equity symbol (e.g. "AAPL")
            contract_type: CALL, PUT, or ALL
            from_date: start of DTE range (YYYY-MM-DD)
            to_date: end of DTE range (YYYY-MM-DD)
            strike_count: number of strikes above/below ATM (optional)

        Returns:
            Raw Schwab chains response dict with keys like symbol, underlyingPrice,
            callExpDateMap, putExpDateMap.
        """
        symbol = to_schwab_symbol(ticker)
        url = f"{self.BASE_URL}/chains"
        params = {
            "symbol": symbol,
            "contractType": contract_type,
            "includeUnderlyingQuote": "true",
        }
        if from_date:
            params["fromDate"] = from_date
        if to_date:
            params["toDate"] = to_date
        if strike_count:
            params["strikeCount"] = strike_count

        try:
            resp = httpx.get(
                url,
                params=params,
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                SchwabTokenManager().invalidate_token()
                raise SchwabAuthError("Schwab API returned 401 — token may be invalid") from e
            logger.error("Schwab chains API error: %s — response body: %s", e, e.response.text)
            raise SchwabClientError("Schwab option chains API error") from e
        except httpx.RequestError as e:
            logger.error("Schwab chains request error: %s", e)
            raise SchwabClientError(SCHWAB_TRANSPORT_ERROR_MSG) from e

        data = resp.json()
        if data.get("status") == "FAILED" or not (data.get("callExpDateMap") or data.get("putExpDateMap")):
            raise SchwabClientError(f"No option chain data returned for '{ticker}'")

        return data

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception_type(SchwabClientError),
        reraise=True,
    )
    def get_price_history(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """Fetch daily price history for a ticker.

        Args:
            ticker: symbol (e.g. "AAPL", "^GSPC", "GC=F")
            start: start date string (e.g. "2024-01-01")
            end: end date string (e.g. "2024-06-01")

        Returns:
            DataFrame with DatetimeIndex named "date" and "value" column (close prices).
        """
        symbol = to_schwab_symbol(ticker)
        start_ms = int(pd.Timestamp(start, tz="America/New_York").timestamp() * 1000)
        end_ms = int(pd.Timestamp(end, tz="America/New_York").timestamp() * 1000)

        url = f"{self.BASE_URL}/pricehistory"
        params = {
            "symbol": symbol,
            "startDate": start_ms,
            "endDate": end_ms,
            "frequencyType": "daily",
            "frequency": 1,
        }

        try:
            resp = httpx.get(
                url,
                params=params,
                headers=self._headers(),
                timeout=15,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                SchwabTokenManager().invalidate_token()
                raise SchwabAuthError("Schwab API returned 401 — token may be invalid") from e
            logger.error("Schwab price history API error for '%s': %s — response body: %s", ticker, e, e.response.text)
            raise SchwabClientError("Schwab price history API error") from e
        except httpx.RequestError as e:
            logger.error("Schwab price history request error: %s", e)
            raise SchwabClientError(SCHWAB_TRANSPORT_ERROR_MSG) from e

        data = resp.json()
        candles = data.get("candles", [])
        if not candles:
            raise SchwabClientError(f"No price history returned for '{ticker}'")

        records = []
        for c in candles:
            records.append({
                "date": pd.Timestamp(c["datetime"], unit="ms"),
                "value": float(c["close"]),
            })

        df = pd.DataFrame(records).set_index("date").sort_index()
        df.index = df.index.normalize()
        df.index.name = "date"
        df = df.dropna(subset=["value"])
        return df

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception_type(SchwabClientError),
        reraise=True,
    )
    def get_accounts(self) -> list[dict]:
        """Get linked brokerage accounts from Trader API."""
        url = f"{self.TRADER_BASE_URL}/accounts"
        try:
            resp = httpx.get(url, headers=self._headers(), timeout=15)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                SchwabTokenManager().invalidate_token()
                raise SchwabAuthError("Schwab API returned 401 — token may be invalid") from e
            logger.error("Schwab accounts API error: %s — response body: %s", e, e.response.text)
            raise SchwabClientError("Schwab accounts API error") from e
        except httpx.RequestError as e:
            logger.error("Schwab accounts request error: %s", e)
            raise SchwabClientError(SCHWAB_TRANSPORT_ERROR_MSG) from e

        return resp.json()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception_type(SchwabClientError),
        reraise=True,
    )
    def get_transactions(self, account_hash: str, start_date: str, end_date: str) -> list[dict]:
        """Get transactions for an account from Trader API.

        Args:
            account_hash: alphanumeric account hash from get_accounts()
            start_date: date string (YYYY-MM-DD), converted to ISO 8601 for API
            end_date: date string (YYYY-MM-DD), converted to ISO 8601 for API
        """
        if not account_hash.isalnum():
            raise SchwabClientError("Invalid account hash")

        url = f"{self.TRADER_BASE_URL}/accounts/{account_hash}/transactions"
        params = {
            "startDate": _to_iso8601(start_date),
            "endDate": _to_iso8601(end_date),
            "types": "TRADE",
        }
        try:
            resp = httpx.get(url, params=params, headers=self._headers(), timeout=30)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                SchwabTokenManager().invalidate_token()
                raise SchwabAuthError("Schwab API returned 401 — token may be invalid") from e
            logger.error("Schwab transactions API error: %s — response body: %s", e, e.response.text)
            raise SchwabClientError("Schwab transactions API error") from e
        except httpx.RequestError as e:
            logger.error("Schwab transactions request error: %s", e)
            raise SchwabClientError(SCHWAB_TRANSPORT_ERROR_MSG) from e

        return resp.json()
