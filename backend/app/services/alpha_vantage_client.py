import csv
import io
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

from app.config import settings

logger = logging.getLogger(__name__)

# In-memory cache: {symbol: (earnings_date_str_or_None, fetched_at_utc)}
_cache: dict[str, tuple[Optional[str], datetime]] = {}
_CACHE_TTL = timedelta(hours=24)


def get_alpha_vantage_api_key() -> str:
    """Get Alpha Vantage API key from settings or DB fallback."""
    if settings.alpha_vantage_api_key:
        return settings.alpha_vantage_api_key
    try:
        from app.models.database import SessionLocal, AppSetting
        db = SessionLocal()
        try:
            entry = db.query(AppSetting).filter(AppSetting.key == "alpha_vantage_api_key").first()
            if entry:
                return entry.value
        finally:
            db.close()
    except Exception:
        pass
    return ""


def get_next_earnings_date(symbol: str) -> Optional[str]:
    """Fetch the next earnings date for a symbol via Alpha Vantage.

    Returns an ISO date string (YYYY-MM-DD) or None if unavailable.
    Results are cached in memory for 24 hours.
    """
    now = datetime.now(timezone.utc)

    # Check cache
    if symbol in _cache:
        cached_date, fetched_at = _cache[symbol]
        if now - fetched_at < _CACHE_TTL:
            return cached_date

    api_key = get_alpha_vantage_api_key()
    if not api_key:
        logger.warning("Alpha Vantage API key not configured; skipping earnings lookup for %s", symbol)
        return None

    try:
        resp = requests.get(
            "https://www.alphavantage.co/query",
            params={
                "function": "EARNINGS_CALENDAR",
                "symbol": symbol,
                "horizon": "3month",
                "apikey": api_key,
            },
            timeout=10,
        )
        resp.raise_for_status()

        today = datetime.now().date()
        reader = csv.DictReader(io.StringIO(resp.text))

        future_dates = []
        for row in reader:
            report_date_str = row.get("reportDate", "").strip()
            if not report_date_str:
                continue
            try:
                report_date = datetime.strptime(report_date_str, "%Y-%m-%d").date()
                if report_date >= today:
                    future_dates.append(report_date)
            except ValueError:
                continue

        result = min(future_dates).strftime("%Y-%m-%d") if future_dates else None
        _cache[symbol] = (result, now)
        return result

    except Exception as e:
        logger.warning("Alpha Vantage earnings lookup failed for %s: %s", symbol, e)
        # Cache the failure too, so we don't hammer the API
        _cache[symbol] = (None, now)
        return None


def clear_cache() -> None:
    """Clear the in-memory earnings cache (for testing)."""
    _cache.clear()
