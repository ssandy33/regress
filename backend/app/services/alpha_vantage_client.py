import csv
import io
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings

logger = logging.getLogger(__name__)

# In-memory hot cache: {symbol: (earnings_date_str_or_None, fetched_at_utc)}
_cache: dict[str, tuple[Optional[str], datetime]] = {}
_CACHE_TTL = timedelta(hours=24)

# SQLite table key prefix for earnings cache
_DB_KEY_PREFIX = "av_earnings:"


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
    except (ImportError, SQLAlchemyError) as e:
        logger.error("Failed to read alpha_vantage_api_key from DB: %s", e)
    return ""


def _read_db_cache(symbol: str) -> Optional[tuple[Optional[str], datetime]]:
    """Read cached earnings date from SQLite."""
    try:
        from app.models.database import SessionLocal, AppSetting
        db = SessionLocal()
        try:
            entry = db.query(AppSetting).filter(
                AppSetting.key == f"{_DB_KEY_PREFIX}{symbol}"
            ).first()
            if entry:
                parts = entry.value.split("|", 1)
                fetched_at = datetime.fromisoformat(parts[0])
                earnings_date = parts[1] if len(parts) > 1 and parts[1] else None
                return (earnings_date, fetched_at)
        finally:
            db.close()
    except (ImportError, SQLAlchemyError) as e:
        logger.debug("Failed to read earnings cache from DB for %s: %s", symbol, e)
    return None


def _write_db_cache(symbol: str, earnings_date: Optional[str], fetched_at: datetime) -> None:
    """Persist cached earnings date to SQLite."""
    try:
        from app.models.database import SessionLocal, AppSetting
        db = SessionLocal()
        try:
            key = f"{_DB_KEY_PREFIX}{symbol}"
            value = f"{fetched_at.isoformat()}|{earnings_date or ''}"
            entry = db.query(AppSetting).filter(AppSetting.key == key).first()
            if entry:
                entry.value = value
            else:
                db.add(AppSetting(key=key, value=value))
            db.commit()
        finally:
            db.close()
    except (ImportError, SQLAlchemyError) as e:
        logger.debug("Failed to write earnings cache to DB for %s: %s", symbol, e)


def get_next_earnings_date(symbol: str) -> Optional[str]:
    """Fetch the next earnings date for a symbol via Alpha Vantage.

    Returns an ISO date string (YYYY-MM-DD) or None if unavailable.
    Uses a two-tier cache: in-memory hot cache backed by SQLite persistence.
    """
    now = datetime.now(timezone.utc)

    # Tier 1: in-memory hot cache
    if symbol in _cache:
        cached_date, fetched_at = _cache[symbol]
        if now - fetched_at < _CACHE_TTL:
            return cached_date

    # Tier 2: SQLite durable cache
    db_entry = _read_db_cache(symbol)
    if db_entry:
        cached_date, fetched_at = db_entry
        if now - fetched_at < _CACHE_TTL:
            _cache[symbol] = (cached_date, fetched_at)
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

        # Alpha Vantage returns HTTP 200 with JSON error body on failures
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type or "text/json" in content_type:
            try:
                body = resp.json()
                error_msg = (
                    body.get("Error Message")
                    or body.get("Note")
                    or body.get("Information")
                )
                if error_msg:
                    logger.warning("Alpha Vantage returned error for %s: %s", symbol, error_msg)
                    return None
            except ValueError:
                pass

        today = datetime.now().date()
        reader = csv.DictReader(io.StringIO(resp.text))

        # Validate CSV header contains expected field
        if reader.fieldnames is None or "reportDate" not in reader.fieldnames:
            logger.warning("Alpha Vantage CSV missing 'reportDate' header for %s", symbol)
            return None

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

        # Cache successful result in both tiers
        _cache[symbol] = (result, now)
        _write_db_cache(symbol, result, now)
        return result

    except Exception as e:
        logger.warning("Alpha Vantage earnings lookup failed for %s: %s", symbol, e)
        # Don't cache transient failures — allow retry on next call
        return None


def clear_cache() -> None:
    """Clear the in-memory earnings cache (for testing)."""
    _cache.clear()
