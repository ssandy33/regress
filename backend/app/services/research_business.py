"""Section A — Business snapshot service (issue #280, W-A).

Composes the ``/api/positions/{id}/research/business`` response payload
per the PRD §"API Contracts → A" frozen contract:

    {
      "ticker":     "SOFI",
      "name":       "SoFi Technologies, Inc.",
      "summary":    "<longBusinessSummary>",
      "sector":     "Financial Services",
      "industry":   "Credit Services",
      "market_cap": 18230000000,
      "employees":  4900,
      "source":     "yfinance",
      "fetched_at": "2026-05-22T17:30:00Z"
    }

Caching (plan §3.5 + §4.6 — frozen)
-----------------------------------

Two tiers, both keyed by ticker (positions that hold the same ticker
share the cache hit):

1. **In-memory** via :mod:`app.services.research_cache` (24 h TTL). The
   ``research_cache`` key is ``yf_business:{ticker}``.
2. **Durable** via ``app_settings`` keyed by ``yf_business:{ticker}`` —
   mirrors the two-tier pattern in :mod:`app.services.alpha_vantage_client`
   so a server restart does not re-burn the yfinance fetch latency for
   every position on the dashboard.

Error semantics (plan §4.5 + CLAUDE.md)
---------------------------------------

The router maps :class:`ResearchSourceUnavailable` to a 502 with the
sanitized detail string carried by the exception. We never propagate
``str(e)`` for the underlying yfinance/requests exception — every
upstream failure is logged at WARNING and surfaced as the same generic
"Source unavailable" message.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from app.services import research_cache, yfinance_client
from app.services.research_cache_utils import (
    read_app_setting,
    write_app_setting,
)
from app.services.yfinance_client import YFinanceRateLimitedError

logger = logging.getLogger(__name__)

# Per plan §3.5 — 24h hard TTL for the business snapshot.
BUSINESS_CACHE_TTL = timedelta(hours=24)

# Cache key formats frozen in plan §4.6.
_MEMORY_CACHE_KEY = "yf_business:{ticker}"
_APP_SETTING_KEY = "yf_business:{ticker}"

# Sanitized 502 detail string. Mirrors PRD "→ 502 {detail: ...}".
_SOURCE_UNAVAILABLE_DETAIL = "Source unavailable"


class ResearchSourceUnavailable(RuntimeError):
    """Raised when every upstream for a research section is unreachable.

    Carries a pre-sanitized detail string (never ``str(original_exc)``) so
    the router can map directly to a 502 ``{"detail": ...}`` body without
    further sanitization. Per CLAUDE.md.
    """

    def __init__(self, detail: str = _SOURCE_UNAVAILABLE_DETAIL) -> None:
        super().__init__(detail)
        self.detail = detail


# Injectable fetcher hook — tests override this without monkey-patching
# the yfinance import path. Production code always uses the default.
_BusinessFetcher = Callable[[str], Optional[dict[str, Any]]]


def build_business_payload(
    db: Session,
    ticker: str,
    *,
    fetcher: _BusinessFetcher | None = None,
) -> dict[str, Any]:
    """Build the Section A payload for ``ticker``.

    Reads through the two-tier cache before calling yfinance. Raises
    :class:`ResearchSourceUnavailable` when yfinance itself fails AND
    neither cache tier has a fresh entry.

    The optional ``fetcher`` parameter is for test injection — production
    callers should leave it ``None`` and the default
    :func:`yfinance_client.fetch_business_info` is used.
    """
    ticker_norm = ticker.upper()
    memory_key = _MEMORY_CACHE_KEY.format(ticker=ticker_norm)
    app_setting_key = _APP_SETTING_KEY.format(ticker=ticker_norm)

    # Tier 1 — in-memory
    hit = research_cache.get(memory_key, BUSINESS_CACHE_TTL)
    if isinstance(hit, dict):
        return hit

    # Tier 2 — durable app_settings
    db_hit = read_app_setting(db, app_setting_key)
    if db_hit is not None:
        payload, fetched_at = db_hit
        if datetime.now(timezone.utc) - fetched_at < BUSINESS_CACHE_TTL:
            research_cache.set(memory_key, payload)
            return payload

    # Cache miss / stale — go upstream
    fetch_impl = fetcher or yfinance_client.fetch_business_info
    try:
        info = fetch_impl(ticker_norm)
    except YFinanceRateLimitedError as exc:
        logger.warning(
            "Yahoo Finance rate-limited business snapshot",
            extra={"ticker": ticker_norm, "source": "yfinance"},
        )
        raise ResearchSourceUnavailable(
            "Yahoo Finance is throttling us — try again in a few minutes."
        ) from exc
    if info is None:
        logger.warning(
            "Business snapshot upstream returned no data",
            extra={"ticker": ticker_norm, "source": "yfinance"},
        )
        raise ResearchSourceUnavailable(_SOURCE_UNAVAILABLE_DETAIL)

    fetched_at = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "ticker": ticker_norm,
        "name": info.get("name"),
        "summary": info.get("long_business_summary"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": info.get("market_cap"),
        "employees": info.get("employees"),
        "source": "yfinance",
        "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
    }

    research_cache.set(memory_key, payload)
    write_app_setting(db, app_setting_key, payload, fetched_at)
    return payload
