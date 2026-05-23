import csv
import io
import json
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
    except (ImportError, SQLAlchemyError):
        logger.exception("Failed to read alpha_vantage_api_key from DB")
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

        today = datetime.now(timezone.utc).date()
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


def get_cached_next_earnings_date(symbol: str) -> Optional[str]:
    """Return a cached earnings date for ``symbol`` without making a network call.

    Looks at the in-memory hot cache first, then the SQLite durable cache.
    Returns ``None`` when no fresh cache entry exists. By contract this
    function NEVER triggers a network round-trip — callers (e.g. the
    dashboard composition path) rely on cache-hit-only semantics so the
    request path is not blocked on Alpha Vantage rate limits.

    See ``frontend/design-specs/decision-dashboard-v05.md`` §14.5: the
    dashboard surfaces ``earnings_in_window`` only when a fresh cache hit
    is available; otherwise the field defaults to ``false`` and the
    earnings glyph is suppressed.
    """
    now = datetime.now(timezone.utc)

    if symbol in _cache:
        cached_date, fetched_at = _cache[symbol]
        if now - fetched_at < _CACHE_TTL:
            return cached_date

    db_entry = _read_db_cache(symbol)
    if db_entry:
        cached_date, fetched_at = db_entry
        if now - fetched_at < _CACHE_TTL:
            # Backfill the hot cache so subsequent lookups in the same
            # process skip the DB hit.
            _cache[symbol] = (cached_date, fetched_at)
            return cached_date

    return None


def clear_cache() -> None:
    """Clear the in-memory earnings caches (for testing).

    Clears the next-earnings hot cache, the income-statement hot cache,
    and the historical-earnings hot cache. Both worker A (income
    statement) and worker B (historical earnings) attached their own
    in-memory caches to this module; ``clear_cache`` is the single test
    entry point for resetting them all between tests.
    """
    _cache.clear()
    _income_cache.clear()
    _earnings_history_cache.clear()


# ---------------------------------------------------------------------------
# INCOME_STATEMENT (issue #280, plan §3.1 + §4.6) — Worker A
# ---------------------------------------------------------------------------
#
# The financial-scorecard endpoint uses Alpha Vantage's ``INCOME_STATEMENT``
# function as its primary source, with yfinance as a fallback when AV
# rate-limits or errors. This block mirrors the two-tier cache pattern
# above (in-memory hot cache + ``app_settings`` durable cache) so a
# server restart does not burn the 25-calls/day free-tier quota. Cache
# key prefix: ``av_financials:`` (frozen in plan §4.6).
#
# Append-only per the W-A worker contract — existing earnings functions
# above are untouched.

_income_cache: dict[str, tuple[Optional[list[dict]], datetime]] = {}
_INCOME_DB_KEY_PREFIX = "av_financials:"

# Error signals returned by Alpha Vantage as HTTP-200 JSON bodies. Mirrors
# the set ``alpha_vantage_client`` already filters on the EARNINGS_CALENDAR
# path so the rate-limit semantics are identical across the two endpoints.
_AV_ERROR_KEYS = ("Error Message", "Note", "Information")


def _read_income_db_cache(
    symbol: str,
) -> Optional[tuple[Optional[list[dict]], datetime]]:
    """Read cached quarterly income statement from SQLite. ``None`` on miss."""
    try:
        from app.models.database import SessionLocal, AppSetting
        db = SessionLocal()
        try:
            entry = db.query(AppSetting).filter(
                AppSetting.key == f"{_INCOME_DB_KEY_PREFIX}{symbol}"
            ).first()
            if entry:
                # Payload format: ``<iso>|<json-payload>``. ``json-payload``
                # is either a JSON list of quarter dicts, or the literal
                # ``null`` for a known-empty/upstream-fail cached result.
                ts_part, _, json_part = entry.value.partition("|")
                fetched_at = datetime.fromisoformat(ts_part)
                payload = json.loads(json_part) if json_part else None
                return (payload, fetched_at)
        finally:
            db.close()
    except (ImportError, SQLAlchemyError, ValueError) as e:
        logger.debug(
            "Failed to read AV income cache from DB for %s: %s", symbol, e
        )
    return None


def _write_income_db_cache(
    symbol: str, payload: Optional[list[dict]], fetched_at: datetime
) -> None:
    """Persist cached quarterly income statement to SQLite."""
    try:
        from app.models.database import SessionLocal, AppSetting
        db = SessionLocal()
        try:
            key = f"{_INCOME_DB_KEY_PREFIX}{symbol}"
            value = f"{fetched_at.isoformat()}|{json.dumps(payload)}"
            entry = db.query(AppSetting).filter(AppSetting.key == key).first()
            if entry:
                entry.value = value
            else:
                db.add(AppSetting(key=key, value=value))
            db.commit()
        finally:
            db.close()
    except (ImportError, SQLAlchemyError) as e:
        logger.debug(
            "Failed to write AV income cache to DB for %s: %s", symbol, e
        )


def get_income_statement(symbol: str, n: int = 8) -> Optional[list[dict]]:
    """Fetch the most recent ``n`` quarters of income statement data.

    Mirrors :func:`get_next_earnings_date` two-tier cache pattern (in-
    memory hot + SQLite durable; 24h TTL). Returns:

    - ``list[dict]`` (length up to ``n``, newest first) on success — each
      dict contains the raw AV fields the caller needs to compute
      gross_margin and operating_margin: ``fiscalDateEnding``,
      ``totalRevenue``, ``grossProfit``, ``operatingIncome``,
      ``netIncome``, ``reportedEPS`` (best-effort).
    - ``None`` on any of: missing API key, AV rate-limit / error response,
      network failure, malformed JSON. The caller is expected to fall
      back to yfinance per plan §3.1.

    Cache key: ``av_financials:{symbol}`` per plan §4.6 (frozen).
    """
    now = datetime.now(timezone.utc)

    # Tier 1: in-memory hot cache
    if symbol in _income_cache:
        cached, fetched_at = _income_cache[symbol]
        if now - fetched_at < _CACHE_TTL:
            return cached

    # Tier 2: SQLite durable cache
    db_entry = _read_income_db_cache(symbol)
    if db_entry:
        cached, fetched_at = db_entry
        if now - fetched_at < _CACHE_TTL:
            _income_cache[symbol] = (cached, fetched_at)
            return cached

    api_key = get_alpha_vantage_api_key()
    if not api_key:
        logger.warning(
            "Alpha Vantage API key not configured; "
            "skipping income statement lookup for %s",
            symbol,
        )
        return None

    try:
        resp = requests.get(
            "https://www.alphavantage.co/query",
            params={
                "function": "INCOME_STATEMENT",
                "symbol": symbol,
                "apikey": api_key,
            },
            timeout=10,
        )
        resp.raise_for_status()

        try:
            body = resp.json()
        except ValueError:
            logger.warning(
                "Alpha Vantage returned non-JSON income statement for %s",
                symbol,
            )
            return None

        # The documented rate-limit / error envelope
        for key in _AV_ERROR_KEYS:
            if key in body:
                logger.warning(
                    "Alpha Vantage INCOME_STATEMENT %s for %s: %s",
                    key,
                    symbol,
                    body.get(key),
                )
                # Do NOT cache rate-limit responses — caller falls back
                # to yfinance and we want a fresh attempt on the next
                # request after the rate-limit window has passed.
                return None

        quarterly = body.get("quarterlyReports")
        if not isinstance(quarterly, list) or not quarterly:
            logger.warning(
                "Alpha Vantage INCOME_STATEMENT missing quarterlyReports "
                "for %s",
                symbol,
            )
            return None

        # AV returns quarters newest-first; trust the order but slice
        # defensively to ``n``.
        result = quarterly[:n]

        # Cache successful result in both tiers
        _income_cache[symbol] = (result, now)
        _write_income_db_cache(symbol, result, now)
        return result

    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Alpha Vantage income statement lookup failed for %s: %s",
            symbol,
            e,
        )
        # Don't cache transient failures — allow retry on next call
        return None


def clear_income_cache() -> None:
    """Clear the in-memory income statement cache (for testing)."""
    _income_cache.clear()


# ---------------------------------------------------------------------------
# Historical earnings (issue #280 / v1.1.0 — Worker B)
#
# The forward-looking ``EARNINGS_CALENDAR`` endpoint above answers "when is
# the *next* earnings event?" — the research price-history endpoint
# (``/api/positions/{id}/research/price-history``) needs the complement:
# the *past* earnings dates within a charting window so Section C can
# annotate them on the price line.
#
# Alpha Vantage exposes this via the ``EARNINGS`` function (JSON) which
# returns both ``annualEarnings`` and ``quarterlyEarnings``. We only use
# the quarterly array; each row carries ``reportedDate`` (the date the
# report was released — the date that actually shows up as a vertical
# line on the price chart) and ``fiscalDateEnding`` (the quarter end).
# The two are often, but not always, the same.
#
# Two-tier cache mirrors :func:`get_next_earnings_date` exactly: in-memory
# hot cache keyed by symbol, with SQLite ``AppSetting`` durable backing
# under the ``av_earnings_history:`` prefix.
# ---------------------------------------------------------------------------

_EARNINGS_HISTORY_DB_KEY_PREFIX = "av_earnings_history:"

# In-memory hot cache: {symbol: (list[ISO date strings], fetched_at_utc)}
_earnings_history_cache: dict[str, tuple[list[str], datetime]] = {}


def _read_earnings_history_db_cache(
    symbol: str,
) -> Optional[tuple[list[str], datetime]]:
    """Read cached historical earnings dates from SQLite.

    Returns ``(dates, fetched_at)`` on cache hit; ``None`` on miss or
    on any persistence error (callers fall through to a fresh fetch).
    """
    try:
        import json as _json

        from app.models.database import SessionLocal, AppSetting
        db = SessionLocal()
        try:
            entry = db.query(AppSetting).filter(
                AppSetting.key == f"{_EARNINGS_HISTORY_DB_KEY_PREFIX}{symbol}"
            ).first()
            if entry:
                parts = entry.value.split("|", 1)
                fetched_at = datetime.fromisoformat(parts[0])
                payload = parts[1] if len(parts) > 1 and parts[1] else "[]"
                dates: list[str] = _json.loads(payload)
                return (dates, fetched_at)
        finally:
            db.close()
    except (ImportError, SQLAlchemyError, ValueError) as e:
        logger.debug(
            "Failed to read earnings-history cache from DB for %s: %s", symbol, e
        )
    return None


def _write_earnings_history_db_cache(
    symbol: str, dates: list[str], fetched_at: datetime
) -> None:
    """Persist cached historical earnings dates to SQLite."""
    try:
        import json as _json

        from app.models.database import SessionLocal, AppSetting
        db = SessionLocal()
        try:
            key = f"{_EARNINGS_HISTORY_DB_KEY_PREFIX}{symbol}"
            value = f"{fetched_at.isoformat()}|{_json.dumps(dates)}"
            entry = db.query(AppSetting).filter(AppSetting.key == key).first()
            if entry:
                entry.value = value
            else:
                db.add(AppSetting(key=key, value=value))
            db.commit()
        finally:
            db.close()
    except (ImportError, SQLAlchemyError) as e:
        logger.debug(
            "Failed to write earnings-history cache to DB for %s: %s", symbol, e
        )


def get_historical_earnings(symbol: str, since: Optional[str] = None) -> list[str]:
    """Fetch historical earnings reporting dates for a symbol via Alpha Vantage.

    Calls Alpha Vantage's ``EARNINGS`` function (JSON) and returns the
    ``reportedDate`` of each quarterly earnings row, sorted ascending.
    When ``since`` (ISO ``YYYY-MM-DD``) is provided, dates strictly older
    than ``since`` are dropped so callers can request a windowed slice.

    Two-tier cache (24h TTL) mirrors :func:`get_next_earnings_date`:
    in-memory hot cache backed by SQLite ``AppSetting`` rows under the
    ``av_earnings_history:`` key prefix.

    On any failure (network error, AV rate-limit signature, malformed
    JSON, missing API key) returns ``[]`` and logs at WARNING. The
    research/price-history endpoint depends on this: an AV outage must
    degrade to an empty ``earnings_events`` list, not fail the whole
    payload (NFR-3).
    """
    now = datetime.now(timezone.utc)

    # Tier 1: in-memory hot cache
    if symbol in _earnings_history_cache:
        cached_dates, fetched_at = _earnings_history_cache[symbol]
        if now - fetched_at < _CACHE_TTL:
            return _filter_since(cached_dates, since)

    # Tier 2: SQLite durable cache
    db_entry = _read_earnings_history_db_cache(symbol)
    if db_entry:
        cached_dates, fetched_at = db_entry
        if now - fetched_at < _CACHE_TTL:
            _earnings_history_cache[symbol] = (cached_dates, fetched_at)
            return _filter_since(cached_dates, since)

    api_key = get_alpha_vantage_api_key()
    if not api_key:
        logger.warning(
            "Alpha Vantage API key not configured; "
            "skipping earnings-history lookup for %s",
            symbol,
        )
        return []

    try:
        resp = requests.get(
            "https://www.alphavantage.co/query",
            params={
                "function": "EARNINGS",
                "symbol": symbol,
                "apikey": api_key,
            },
            timeout=10,
        )
        resp.raise_for_status()

        try:
            body = resp.json()
        except ValueError:
            logger.warning(
                "Alpha Vantage EARNINGS returned non-JSON body for %s", symbol
            )
            return []

        error_msg = (
            body.get("Error Message")
            or body.get("Note")
            or body.get("Information")
        )
        if error_msg:
            logger.warning(
                "Alpha Vantage EARNINGS returned error for %s: %s",
                symbol,
                error_msg,
            )
            return []

        quarterly = body.get("quarterlyEarnings") or []
        if not isinstance(quarterly, list):
            logger.warning(
                "Alpha Vantage EARNINGS payload missing quarterlyEarnings for %s",
                symbol,
            )
            return []

        dates: list[str] = []
        for row in quarterly:
            if not isinstance(row, dict):
                continue
            # Prefer reportedDate (the release date — that's what plots on
            # the price chart). Fall back to fiscalDateEnding because some
            # thinly-covered tickers omit reportedDate.
            raw = row.get("reportedDate") or row.get("fiscalDateEnding")
            if not raw:
                continue
            try:
                datetime.strptime(raw, "%Y-%m-%d")
            except ValueError:
                continue
            dates.append(raw)

        dates.sort()
        _earnings_history_cache[symbol] = (dates, now)
        _write_earnings_history_db_cache(symbol, dates, now)
        return _filter_since(dates, since)

    except Exception as e:  # noqa: BLE001 — network errors degrade to []
        logger.warning(
            "Alpha Vantage EARNINGS lookup failed for %s: %s", symbol, e
        )
        return []


def _filter_since(dates: list[str], since: Optional[str]) -> list[str]:
    """Return ``dates`` filtered to entries on or after ``since``.

    ``since`` is an ISO ``YYYY-MM-DD`` string. When falsy or invalid the
    input is returned unchanged so callers don't double-validate.
    """
    if not since:
        return list(dates)
    try:
        cutoff = datetime.strptime(since, "%Y-%m-%d").date()
    except ValueError:
        return list(dates)
    out: list[str] = []
    for d in dates:
        try:
            if datetime.strptime(d, "%Y-%m-%d").date() >= cutoff:
                out.append(d)
        except ValueError:
            continue
    return out
