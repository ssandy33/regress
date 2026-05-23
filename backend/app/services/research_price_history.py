"""Research price-history composition (issue #280 / v1.1.0 — Worker B).

Composes the payload for ``GET /api/positions/{id}/research/price-history``:

1. **Prices** — daily closes from the existing :class:`DataFetcher` over the
   requested window (default ``1Y``).
2. **Basis lines** — broker basis from the Position row, adjusted basis from
   the journal recomputation (premiums-net-of-assignment).
3. **Trade events** — the position's own ledger, mapped to chart markers
   with the v1 frozen vocabulary (``sell_put``, ``sell_call``, ``assignment``,
   ``called_away``, ``expired``, ``buy_close``).
4. **Earnings events** — past reporting dates within the window from
   Alpha Vantage's ``EARNINGS`` function. Degrades gracefully to ``[]``
   when AV is unavailable — the price line is the primary signal.

Per the v1 contract freeze the only accepted ``window`` value is ``"1Y"``,
but ``6M`` and ``2Y`` are accepted too so the API surface is forwards-
compatible with the deferred window picker (CTO plan §4.1). Anything else
raises :class:`InvalidWindowError`.

The endpoint is cached in-process for 15 minutes (NFR-7) keyed on
``research:price-history:{position_id}:{window}``. The cache is intentionally
in-memory-only — restarts evict harmlessly, the daily quotes have already
been cached at the :class:`DataFetcher` layer, and the trade ledger lives
in SQLite. See CTO plan §3.5.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session as DBSession

from app.services import journal, research_cache
from app.services.alpha_vantage_client import get_historical_earnings
from app.services.cache import CacheService
from app.services.data_fetcher import DataFetcher

logger = logging.getLogger(__name__)


# --- v1 contract: accepted windows -----------------------------------------

# Order matters only for documentation — the dict's values are the lookback
# in calendar days used when slicing the price DataFrame.
SUPPORTED_WINDOWS: dict[str, int] = {
    "6M": 183,
    "1Y": 365,
    "2Y": 730,
}
DEFAULT_WINDOW: str = "1Y"

# Trade-marker vocabulary frozen at design-spec §4 Section B. The router
# returns the raw enum value as ``type``; the frontend reads
# ``tradeMarkerVocabulary.js`` to render symbol + color. Some legacy
# ``trade_type`` strings on existing rows need normalization (e.g.
# ``buy_put_close`` and ``buy_call_close`` both render as ``buy_close``).
_TRADE_TYPE_NORMALIZE: dict[str, str] = {
    "sell_put": "sell_put",
    "sell_call": "sell_call",
    "assignment": "assignment",
    "called_away": "called_away",
    "expired": "expired",
    "buy_put_close": "buy_close",
    "buy_call_close": "buy_close",
}

# 15-minute in-memory cache for the composed payload (CTO plan §3.5).
#
# Backed by the shared :mod:`app.services.research_cache` helper now that
# Worker A's module has landed on the integration branch. Earlier worker
# isolation required this to be inlined; the dedup happened in the
# v1.1.0 cleanup pass (Phase 5 should-fix S1).
_CACHE_TTL = timedelta(minutes=15)


# --- Pydantic response models ----------------------------------------------
#
# The CTO plan §5 Worker W reconciles all five endpoint models into
# ``schemas.py`` under a single ``# --- Research (#280) ---`` divider. Until
# Worker W's pass, the models live here so this worker's PR is self-contained.


class PriceHistoryPoint(BaseModel):
    """A single date + close-price tuple on the price line."""

    model_config = ConfigDict(extra="forbid")

    date: str
    close: float


class BasisLines(BaseModel):
    """The two horizontal basis lines plotted on the chart.

    ``broker`` is the IRS/Schwab basis (strike × shares − net premium of the
    matched short put). ``adjusted`` subtracts the *additional* premiums
    collected on the position after the assignment that established the
    position — the "real" basis the wheel trader trades against. See
    :func:`app.services.journal.compute_adjusted_basis` for the math.
    """

    model_config = ConfigDict(extra="forbid")

    broker: float
    adjusted: float


class TradeEvent(BaseModel):
    """A user-recorded trade plotted as a chart marker.

    ``type`` is one of the six v1 marker vocabulary values frozen at design
    spec §4 Section B: ``sell_put``, ``sell_call``, ``assignment``,
    ``called_away``, ``expired``, ``buy_close``. ``strike`` is omitted for
    rows where it would be misleading (no current trade type omits it, but
    the field is ``Optional`` for forwards-compatibility).
    """

    model_config = ConfigDict(extra="forbid")

    date: str
    type: str
    strike: float | None = None


class EarningsEvent(BaseModel):
    """A historical earnings release date annotated on the chart."""

    model_config = ConfigDict(extra="forbid")

    date: str
    label: str


class PriceHistoryResponse(BaseModel):
    """Composed payload for the research price-history endpoint."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    window: str
    prices: list[PriceHistoryPoint]
    basis: BasisLines
    trade_events: list[TradeEvent]
    earnings_events: list[EarningsEvent]


# --- Errors ---------------------------------------------------------------


class InvalidWindowError(ValueError):
    """Raised when the caller passes an unsupported ``window`` value."""


class PriceSourceUnavailableError(RuntimeError):
    """Raised when the price source (Schwab/yfinance) fails hard.

    The router maps this to a sanitized 502 — never propagate the
    underlying exception's ``str()`` per CLAUDE.md.
    """


# --- Cache helpers --------------------------------------------------------


def _cache_get(key: str) -> dict[str, Any] | None:
    """Read the 15-min in-memory payload cache; ``None`` on miss or expiry."""
    hit = research_cache.get(key, _CACHE_TTL)
    if isinstance(hit, dict):
        return hit
    return None


def _cache_set(key: str, value: dict[str, Any]) -> None:
    """Write to the 15-min in-memory payload cache."""
    research_cache.set(key, value)


def clear_cache() -> None:
    """Clear the price-history payload cache (testing hook).

    Routes through the shared :mod:`research_cache` ``clear()`` so all
    research caches drop together — the price-history cache used to be a
    private dict; tests that imported this helper still work unchanged.
    """
    research_cache.clear()


# --- Composition pieces ---------------------------------------------------


def _window_dates(window: str) -> tuple[str, str]:
    """Return ``(start, end)`` ISO date strings for a window keyword."""
    if window not in SUPPORTED_WINDOWS:
        raise InvalidWindowError(f"Unsupported window: {window!r}")
    end = date.today()
    start = end - timedelta(days=SUPPORTED_WINDOWS[window])
    return start.isoformat(), end.isoformat()


def _fetch_prices(
    ticker: str, window: str, fetcher: DataFetcher
) -> list[PriceHistoryPoint]:
    """Fetch daily closes for ``ticker`` over ``window``.

    Wraps any data-source error in :class:`PriceSourceUnavailableError`
    with a generic message so the router can return a sanitized 502.
    """
    start, end = _window_dates(window)
    try:
        df, _meta = fetcher.fetch(ticker, start, end)
    except Exception as exc:  # noqa: BLE001 — sanitized at the boundary
        logger.warning(
            "Price-history fetch failed",
            extra={
                "ticker": ticker,
                "window": window,
                "error": exc.__class__.__name__,
            },
        )
        raise PriceSourceUnavailableError(
            "Price source unavailable"
        ) from exc

    points: list[PriceHistoryPoint] = []
    if df is None or df.empty:
        return points

    for idx, row in df.iterrows():
        try:
            close = float(row["value"])
        except (KeyError, TypeError, ValueError):
            continue
        # The fetcher returns a DatetimeIndex; isoformat the date component.
        if isinstance(idx, pd.Timestamp):
            iso = idx.strftime("%Y-%m-%d")
        else:
            iso = str(idx)
        points.append(PriceHistoryPoint(date=iso, close=close))

    return points


def _trade_events_from_position(position: dict[str, Any]) -> list[TradeEvent]:
    """Map the position's trade ledger to v1 chart-marker events.

    Reads the ``trades`` array on the position dict returned by
    :func:`app.services.journal.get_position`. Each trade's ``opened_at``
    is the marker date — that's the date the *user took the action* (the
    one the chart user would recognize). Closed legs are still rendered;
    the close itself is its own event when ``closed_at`` exists.
    """
    events: list[TradeEvent] = []
    for trade in position.get("trades") or []:
        raw_type = trade.get("trade_type")
        if not raw_type:
            continue
        normalized = _TRADE_TYPE_NORMALIZE.get(raw_type)
        if normalized is None:
            logger.debug(
                "Skipping trade with unknown trade_type",
                extra={
                    "trade_type": raw_type,
                    "position_id": position.get("id"),
                },
            )
            continue
        opened = trade.get("opened_at")
        if not opened:
            continue
        # Normalize ``opened_at`` (may be ``YYYY-MM-DD`` or
        # ``YYYY-MM-DDTHH:MM:SSZ``) down to the date-only form the chart
        # x-axis expects.
        date_only = str(opened).split("T", 1)[0]
        strike = trade.get("strike")
        try:
            strike_f: float | None = float(strike) if strike is not None else None
        except (TypeError, ValueError):
            strike_f = None
        events.append(
            TradeEvent(date=date_only, type=normalized, strike=strike_f)
        )
    events.sort(key=lambda e: e.date)
    return events


def _earnings_events_for_window(
    ticker: str, window: str
) -> list[EarningsEvent]:
    """Fetch historical earnings dates for ``ticker`` within the window.

    Returns an empty list when Alpha Vantage is unavailable — the endpoint
    must degrade gracefully rather than fail the whole payload (NFR-3).
    The label string is deterministic: ``"Earnings"`` for v1; Section C
    can enrich it later with quarter labels.
    """
    start, _end = _window_dates(window)
    try:
        raw_dates = get_historical_earnings(ticker, since=start)
    except Exception as exc:  # noqa: BLE001 — degrade to []
        logger.warning(
            "Historical earnings fetch failed; returning empty earnings_events",
            extra={
                "ticker": ticker,
                "source": "alphavantage",
                "error": exc.__class__.__name__,
            },
        )
        return []
    return [EarningsEvent(date=d, label="Earnings") for d in raw_dates]


# --- Public API -----------------------------------------------------------


def build_price_history(
    db: DBSession,
    position_id: str,
    window: str | None,
    fetcher: DataFetcher | None = None,
) -> PriceHistoryResponse | None:
    """Compose the research price-history payload for one position.

    Returns ``None`` when the position does not exist so the router can map
    that to a 404. Raises :class:`InvalidWindowError` on bad ``window`` and
    :class:`PriceSourceUnavailableError` on a hard price-source failure;
    both are sanitized at the router boundary.

    A 15-minute in-process cache short-circuits the composition; the cache
    key is ``research:price-history:{position_id}:{window}`` per the v1
    contract freeze (CTO plan §4.6).
    """
    resolved_window = (window or DEFAULT_WINDOW).upper()
    if resolved_window not in SUPPORTED_WINDOWS:
        raise InvalidWindowError(
            f"Unsupported window: {window!r}. Supported: "
            f"{sorted(SUPPORTED_WINDOWS)}"
        )

    # 1. Position lookup (also drives 404 + ticker + basis values)
    position = journal.get_position(db, position_id)
    if position is None:
        return None

    cache_key = f"research:price-history:{position_id}:{resolved_window}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return PriceHistoryResponse(**cached)

    ticker = str(position.get("ticker") or "").upper()

    # 2. Prices (raises PriceSourceUnavailableError on hard failure)
    if fetcher is None:
        fetcher = DataFetcher(CacheService(db))
    prices = _fetch_prices(ticker, resolved_window, fetcher)

    # 3. Basis lines from the position row (broker) + journal recompute
    #    (adjusted). Both are floats; the journal layer guarantees they
    #    are non-negative and well-formed.
    basis = BasisLines(
        broker=float(position.get("broker_cost_basis") or 0.0),
        adjusted=float(position.get("adjusted_cost_basis") or 0.0),
    )

    # 4. Trade events from the ledger
    trade_events = _trade_events_from_position(position)

    # 5. Earnings events (degrades to [] on AV failure)
    earnings_events = _earnings_events_for_window(ticker, resolved_window)

    response = PriceHistoryResponse(
        ticker=ticker,
        window=resolved_window,
        prices=prices,
        basis=basis,
        trade_events=trade_events,
        earnings_events=earnings_events,
    )

    # Cache the dict form so a hit can rehydrate via ``PriceHistoryResponse(**)``
    _cache_set(cache_key, response.model_dump())
    return response


__all__ = [
    "BasisLines",
    "DEFAULT_WINDOW",
    "EarningsEvent",
    "InvalidWindowError",
    "PriceHistoryPoint",
    "PriceHistoryResponse",
    "PriceSourceUnavailableError",
    "SUPPORTED_WINDOWS",
    "TradeEvent",
    "build_price_history",
    "clear_cache",
]
