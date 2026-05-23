"""Section D — Financial scorecard service (issue #280, W-A).

Composes the ``/api/positions/{id}/research/financials`` response payload
per the PRD §"API Contracts → D" frozen contract:

    {
      "ticker": "SOFI",
      "quarters": [
        { "period_end": "2025-03-31",
          "revenue": 645000000,
          "eps": 0.02,
          "gross_margin": 0.43,
          "operating_margin": 0.04 },
        ...   // up to 8 quarters, newest first
      ],
      "source": "alphavantage",   // or "yfinance" if AV failed
      "fetched_at": "2026-05-22T17:30:00Z"
    }

Source strategy (plan §3.1, frozen)
-----------------------------------

1. Alpha Vantage ``INCOME_STATEMENT`` is the primary source. The
   :func:`app.services.alpha_vantage_client.get_income_statement` helper
   already implements the two-tier cache and AV's documented rate-limit
   error filtering (any of ``Error Message`` / ``Note`` / ``Information``
   in the JSON body → returns ``None`` from the helper, which we treat
   as "fall back to yfinance").
2. yfinance ``Ticker.quarterly_income_stmt`` is the fallback when AV
   returns ``None``. The fallback payload sets ``"source": "yfinance"``
   so the frontend can render the provenance caption per the spec
   ("Source: yfinance (alphavantage rate-limited) · refreshed …").
3. Both upstreams returning ``None`` → 502 with sanitized detail
   ``"Financials source unavailable"`` per plan §4.5.

Caching
-------

The AV upstream has its own two-tier cache (in :mod:`alpha_vantage_client`)
keyed by ``av_financials:{ticker}``. The composed response payload is
also stored in the in-memory :mod:`research_cache` under
``av_financials:{ticker}`` / ``yf_financials:{ticker}`` so a second
request inside the 24h TTL skips both the AV/yfinance call AND the
margin recomputation. The durable ``yf_financials:{ticker}`` AppSetting
backs the yfinance fallback path so a server restart does not re-burn
the (slower, less rate-limited but still costly) yfinance call.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from app.services import alpha_vantage_client, research_cache, yfinance_client
from app.services.research_business import ResearchSourceUnavailable
from app.services.research_cache_utils import (
    read_app_setting,
    write_app_setting,
)

logger = logging.getLogger(__name__)

# Per plan §3.5 — 24h hard TTL for the financial scorecard.
FINANCIALS_CACHE_TTL = timedelta(hours=24)
QUARTERS = 8

# Cache key formats frozen in plan §4.6.
_AV_MEMORY_KEY = "av_financials:{ticker}"
_YF_MEMORY_KEY = "yf_financials:{ticker}"
_YF_APP_SETTING_KEY = "yf_financials:{ticker}"

_SOURCE_UNAVAILABLE_DETAIL = "Financials source unavailable"

# Hook types for test injection — production code uses the defaults.
_AVFetcher = Callable[[str, int], Optional[list[dict]]]
_YFFetcher = Callable[[str, int], Optional[list[dict]]]


def _safe_float(value: Any) -> Optional[float]:
    """Convert ``value`` to ``float``; return ``None`` on any failure.

    AV returns numbers as strings (``"645000000"``); yfinance returns
    floats / ``NaN``. Either can be missing entirely (``"None"`` string
    from AV when a quarter has no reported value). This helper normalizes
    both to ``Optional[float]``.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        v = value.strip()
        if not v or v.lower() in ("none", "null", "n/a", "nan", "-"):
            return None
        try:
            return float(v)
        except ValueError:
            return None
    if isinstance(value, (int, float)):
        f = float(value)
        # NaN check — ``f != f`` is the canonical Python NaN test
        if f != f:
            return None
        return f
    return None


def _safe_div(numerator: Any, denominator: Any) -> Optional[float]:
    """Return ``num / denom`` or ``None`` when either is missing or denom is 0."""
    num = _safe_float(numerator)
    denom = _safe_float(denominator)
    if num is None or denom is None or denom == 0:
        return None
    return num / denom


def _project_av_quarter(raw: dict) -> dict[str, Any]:
    """Project one AV ``quarterlyReports`` entry into the response shape.

    AV's fields use camelCase strings: ``fiscalDateEnding``,
    ``totalRevenue``, ``grossProfit``, ``operatingIncome``,
    ``reportedEPS``. We compute ``gross_margin`` and ``operating_margin``
    from the raw numerator/denominator pair; either is ``None`` when a
    needed field is missing (so the frontend can render a `—` cell
    instead of a fabricated 0).
    """
    return {
        "period_end": raw.get("fiscalDateEnding"),
        "revenue": _safe_float(raw.get("totalRevenue")),
        "eps": _safe_float(raw.get("reportedEPS")),
        "gross_margin": _safe_div(
            raw.get("grossProfit"), raw.get("totalRevenue")
        ),
        "operating_margin": _safe_div(
            raw.get("operatingIncome"), raw.get("totalRevenue")
        ),
    }


def _project_yf_quarter(raw: dict) -> dict[str, Any]:
    """Project one yfinance-shaped quarter into the response shape.

    yfinance gives us the same set of fundamentals under snake_case keys
    (the :mod:`yfinance_client` normalization layer), so the margin math
    is identical — we just rename for the public payload.
    """
    return {
        "period_end": raw.get("fiscal_date_ending"),
        "revenue": _safe_float(raw.get("total_revenue")),
        "eps": _safe_float(raw.get("diluted_eps")),
        "gross_margin": _safe_div(
            raw.get("gross_profit"), raw.get("total_revenue")
        ),
        "operating_margin": _safe_div(
            raw.get("operating_income"), raw.get("total_revenue")
        ),
    }


def build_financials_payload(
    db: Session,
    ticker: str,
    *,
    av_fetcher: _AVFetcher | None = None,
    yf_fetcher: _YFFetcher | None = None,
) -> dict[str, Any]:
    """Build the Section D payload for ``ticker``.

    Source order: in-memory cache (AV or YF) → AV upstream → yfinance
    fallback → ``app_settings`` durable cache (yfinance fallback only —
    AV has its own durable cache inside :mod:`alpha_vantage_client`) →
    :class:`ResearchSourceUnavailable`.

    The ``av_fetcher`` / ``yf_fetcher`` parameters are for test injection
    — production callers leave both ``None`` and the defaults are used.
    """
    ticker_norm = ticker.upper()
    av_memory_key = _AV_MEMORY_KEY.format(ticker=ticker_norm)
    yf_memory_key = _YF_MEMORY_KEY.format(ticker=ticker_norm)
    yf_app_key = _YF_APP_SETTING_KEY.format(ticker=ticker_norm)

    # Tier 1 — in-memory hot cache (composed payload, either source)
    for key in (av_memory_key, yf_memory_key):
        hit = research_cache.get(key, FINANCIALS_CACHE_TTL)
        if isinstance(hit, dict):
            return hit

    # Try AV primary
    av_impl = av_fetcher or alpha_vantage_client.get_income_statement
    av_raw = av_impl(ticker_norm, QUARTERS)
    if av_raw is not None:
        quarters = [_project_av_quarter(q) for q in av_raw[:QUARTERS]]
        fetched_at = datetime.now(timezone.utc)
        payload: dict[str, Any] = {
            "ticker": ticker_norm,
            "quarters": quarters,
            "source": "alphavantage",
            "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
        }
        research_cache.set(av_memory_key, payload)
        # AV's own durable cache (av_financials key prefix) is written
        # inside ``alpha_vantage_client.get_income_statement`` — we do
        # NOT write again here to avoid two AppSetting rows for the same
        # ticker.
        return payload

    # Fall back to yfinance
    # First check the durable yf cache so a server restart with AV down
    # still serves a fresh-enough payload.
    yf_db_hit = read_app_setting(db, yf_app_key)
    if yf_db_hit is not None:
        payload, fetched_at = yf_db_hit
        if datetime.now(timezone.utc) - fetched_at < FINANCIALS_CACHE_TTL:
            research_cache.set(yf_memory_key, payload)
            return payload

    yf_impl = yf_fetcher or yfinance_client.fetch_quarterly_income_stmt
    yf_raw = yf_impl(ticker_norm, QUARTERS)
    if yf_raw is None:
        logger.warning(
            "Both AV and yfinance returned no income statement",
            extra={"ticker": ticker_norm, "source": "alphavantage+yfinance"},
        )
        raise ResearchSourceUnavailable(_SOURCE_UNAVAILABLE_DETAIL)

    quarters = [_project_yf_quarter(q) for q in yf_raw[:QUARTERS]]
    fetched_at = datetime.now(timezone.utc)
    payload = {
        "ticker": ticker_norm,
        "quarters": quarters,
        "source": "yfinance",
        "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
    }
    research_cache.set(yf_memory_key, payload)
    write_app_setting(db, yf_app_key, payload, fetched_at)
    return payload
