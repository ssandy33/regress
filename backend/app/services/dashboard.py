"""Dashboard composition service.

Builds the unified `/api/dashboard` payload by composing existing services
(journal, schwab quotes, settings/health, sessions, cache). This module owns
*no* business logic of its own — it stitches together values produced
elsewhere into a single response so the frontend issues only one round-trip.

Per issue #114: avoid N+1 client-side fetches by composing on the server.
"""

from __future__ import annotations

import concurrent.futures
import logging
from datetime import date, datetime, timezone
from typing import Iterable

from sqlalchemy.orm import Session as DBSession

from app.config import get_fred_api_key
from app.models.database import CacheEntry, Position, Session as SessionModel, Trade
from app.services import journal as journal_service
from app.services.dashboard_legs import (
    derive_open_legs,
    filter_upcoming,
    parse_iso_to_utc,
)
from app.services.schwab_auth import SchwabAuthError, SchwabTokenManager
from app.services.schwab_client import SchwabClient, SchwabClientError

logger = logging.getLogger(__name__)

# Cache freshness thresholds — kept identical to routers/settings.py so the
# strip and the Settings page agree. Consolidating these into a single helper
# is tracked as a follow-up.
CACHE_FRESH_DAYS = 30
CACHE_STALE_DAYS = 90
ACTIVITY_LIMIT = 10
# Per-side fetch ceiling before merging; spec §10 risk #10.
ACTIVITY_PER_SIDE_LIMIT = 30
# Quote fan-out: cap concurrency to avoid swamping Schwab's rate limit while
# still keeping first-paint snappy. 8 inflight covers the typical 15–20 ticker
# dashboard within ~3 round-trips even at full saturation. The CTO plan
# originally proposed sequential calls; we override to parallelize because the
# sequential path would create a multi-second first-paint regression on the
# new default route. An in-process TTL cache is deferred — see follow-up issue
# linked in PR #114 description.
QUOTE_FANOUT_WORKERS = 8


def _build_schwab_status() -> tuple[dict, bool]:
    """Return (status_dict, is_configured). Skips the live HTTP probe — the
    detail card can call /api/settings/health/schwab if the user wants live
    validation. Returning early keeps p95 dashboard latency low.
    """
    mgr = SchwabTokenManager()
    configured = mgr.is_configured()
    return (
        {
            "configured": configured,
            "valid": configured,  # static fallback; see plan §4.5 / risk #2
            "expires_at": mgr.get_refresh_token_expiry(),
        },
        configured,
    )


def _build_fred_status() -> dict:
    """Return FRED config status without the live API ping (see Schwab note)."""
    configured = bool(get_fred_api_key())
    return {"configured": configured, "valid": configured}


def _bucket_cache_freshness(db: DBSession) -> dict:
    """Aggregate CacheEntry rows into fresh / stale / very-stale buckets.

    Mirrors the bucketing in routers/settings.py:get_cache_freshness so the
    strip pill and the Settings detail agree.
    """
    entries = db.query(CacheEntry).all()
    now = datetime.now(timezone.utc)
    fresh = stale = very_stale = 0
    for entry in entries:
        try:
            fetched_at = datetime.fromisoformat(entry.fetched_at)
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
            age_days = (now - fetched_at).days
        except (ValueError, TypeError):
            age_days = 999
        if age_days < CACHE_FRESH_DAYS:
            fresh += 1
        elif age_days < CACHE_STALE_DAYS:
            stale += 1
        else:
            very_stale += 1
    return {
        "fresh": fresh,
        "stale": stale,
        "very_stale": very_stale,
        "total": len(entries),
    }


def _fetch_quotes_parallel(
    tickers: Iterable[str],
    schwab_configured: bool,
) -> tuple[dict[str, float | None], bool]:
    """Fetch live quotes for `tickers` concurrently. Returns
    (price_by_ticker, schwab_failed_flag).

    Failures are *expected* states (token expired, network down, ticker
    unknown to Schwab). Individual failures yield a None price; the caller
    surfaces the partial outage via data_meta.sources_unavailable.

    Schwab's client is synchronous (httpx + retry/tenacity decorators), so we
    use a thread pool rather than refactoring it to async. See PR #114.
    """
    unique = sorted({t for t in tickers if t})
    prices: dict[str, float | None] = {t: None for t in unique}
    if not unique or not schwab_configured:
        # If Schwab isn't configured, we don't surface that as a "failure" —
        # it's a known unavailable source. The status strip already reports it.
        # But we still return the dict so callers don't crash.
        return prices, False

    schwab_failed = False
    client = SchwabClient()

    def _fetch(ticker: str) -> tuple[str, float | None, bool]:
        try:
            quote = client.get_quote(ticker)
        except (SchwabClientError, SchwabAuthError) as exc:
            logger.warning("Dashboard quote fetch failed for %s: %s", ticker, exc)
            return ticker, None, True
        # Schwab `quote` payloads have lastPrice or fall back to `mark`.
        price = quote.get("lastPrice") if isinstance(quote, dict) else None
        if price is None and isinstance(quote, dict):
            price = quote.get("mark")
        return ticker, (float(price) if price is not None else None), False

    workers = min(QUOTE_FANOUT_WORKERS, len(unique))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for ticker, price, failed in pool.map(_fetch, unique):
            prices[ticker] = price
            if failed:
                schwab_failed = True
    return prices, schwab_failed


def _build_position_rows(
    open_positions: list[dict],
    quotes_by_ticker: dict[str, float | None],
    open_legs: list[dict],
) -> list[dict]:
    """Convert journal positions into dashboard row shape, sorted by notional."""
    leg_count_by_position = {}
    for leg in open_legs:
        leg_count_by_position[leg["position_id"]] = (
            leg_count_by_position.get(leg["position_id"], 0) + 1
        )

    rows: list[dict] = []
    for position in open_positions:
        shares = position.get("shares") or 0
        adjusted_cost_basis = position["adjusted_cost_basis"]
        ticker = position["ticker"]
        current_price = quotes_by_ticker.get(ticker)
        notional: float | None = None
        unrealized_pl: float | None = None
        if shares > 0 and current_price is not None:
            notional = current_price * shares
            cost_per_share = adjusted_cost_basis / shares if shares else 0.0
            unrealized_pl = (current_price - cost_per_share) * shares
        rows.append(
            {
                "id": position["id"],
                "ticker": ticker,
                "shares": shares,
                "strategy": position["strategy"],
                "adjusted_cost_basis": adjusted_cost_basis,
                "current_price": current_price,
                "notional": notional,
                "unrealized_pl": unrealized_pl,
                "open_legs_count": leg_count_by_position.get(position["id"], 0),
            }
        )
    # Sort by notional desc (None last), then ticker asc.
    rows.sort(key=lambda r: (-(r["notional"] or 0.0), r["ticker"]))
    return rows


def _build_kpis(
    position_rows: list[dict],
    open_legs: list[dict],
    open_positions: list[dict],
) -> dict:
    """Aggregate KPI tiles from already-built row data."""
    open_positions_count = len(position_rows)
    breakdown = {"stock": 0, "csp": 0, "cc": 0, "wheel": 0}
    for position in open_positions:
        strategy = position["strategy"]
        if strategy in breakdown:
            breakdown[strategy] += 1

    notional_value = sum((r["notional"] or 0.0) for r in position_rows)
    cost_basis_total = sum(p["adjusted_cost_basis"] for p in open_positions)
    notional_change_pct: float | None = None
    if cost_basis_total > 0 and notional_value > 0:
        notional_change_pct = (notional_value - cost_basis_total) / cost_basis_total

    puts = sum(1 for leg in open_legs if leg["type"] == "put")
    calls = sum(1 for leg in open_legs if leg["type"] == "call")

    pl_values = [r["unrealized_pl"] for r in position_rows if r["unrealized_pl"] is not None]
    unrealized_pl: float | None = sum(pl_values) if pl_values else None
    unrealized_pl_pct: float | None = None
    if unrealized_pl is not None and cost_basis_total > 0:
        unrealized_pl_pct = unrealized_pl / cost_basis_total

    return {
        "open_positions": open_positions_count,
        "open_positions_breakdown": breakdown,
        "notional_value": notional_value,
        "notional_change_pct": notional_change_pct,
        "open_legs": len(open_legs),
        "open_legs_breakdown": {"puts": puts, "calls": calls},
        "unrealized_pl": unrealized_pl,
        "unrealized_pl_pct": unrealized_pl_pct,
    }


def _build_recent_activity(db: DBSession) -> list[dict]:
    """UNION of recent saved sessions and recent trades, top 10 by timestamp.

    Per Q6: scanner runs are not persisted today and are out of scope for v0.
    """
    sessions = (
        db.query(SessionModel)
        .order_by(SessionModel.created_at.desc())
        .limit(ACTIVITY_PER_SIDE_LIMIT)
        .all()
    )
    trades = (
        db.query(Trade)
        .order_by(Trade.opened_at.desc())
        .limit(ACTIVITY_PER_SIDE_LIMIT)
        .all()
    )

    events: list[dict] = []
    for session in sessions:
        events.append(
            {
                "kind": "session_saved",
                "timestamp": session.created_at,
                "session_name": session.name,
                "session_id": session.id,
            }
        )

    # Build a {position_id: ticker} lookup so we can show the ticker on each
    # trade event without re-querying.
    position_ids = {trade.position_id for trade in trades}
    ticker_by_position: dict[str, str] = {}
    if position_ids:
        for position in (
            db.query(Position).filter(Position.id.in_(position_ids)).all()
        ):
            ticker_by_position[position.id] = position.ticker

    for trade in trades:
        events.append(
            {
                "kind": "trade_added",
                "timestamp": trade.opened_at,
                "ticker": ticker_by_position.get(trade.position_id, ""),
                "trade_type": trade.trade_type,
                "position_id": trade.position_id,
            }
        )

    # Sort timestamp desc; rows that fail parsing fall to the end.
    def _sort_key(event: dict) -> tuple[int, datetime | str]:
        parsed = parse_iso_to_utc(event["timestamp"])
        if parsed is None:
            # Negative-infinity proxy: stable but always last.
            return (1, event["timestamp"] or "")
        # Use negative timestamp so descending sort is implicit.
        return (0, datetime.max.replace(tzinfo=timezone.utc) - parsed)

    events.sort(key=_sort_key)
    return events[:ACTIVITY_LIMIT]


def build_dashboard_payload(db: DBSession, today: date | None = None) -> dict:
    """Compose the full dashboard payload.

    Args:
        db: SQLAlchemy session (request-scoped).
        today: Override "today" for deterministic tests.

    Returns:
        Dict matching DashboardResponse — FastAPI serializes via the
        response_model on the route.
    """
    now = datetime.now(timezone.utc).isoformat()
    today = today or date.today()

    # Status block
    schwab_status, schwab_configured = _build_schwab_status()
    fred_status = _build_fred_status()
    cache_status = _bucket_cache_freshness(db)

    # Positions
    open_positions = journal_service.get_positions(db, status="open")
    journal_status = {"positions_count": len(open_positions)}

    # Quotes (parallelized; deduped by ticker)
    tickers = [p["ticker"] for p in open_positions]
    quotes_by_ticker, schwab_failed = _fetch_quotes_parallel(
        tickers, schwab_configured=schwab_configured
    )

    # Legs derive purely from in-memory data + the quote map.
    open_legs = derive_open_legs(open_positions, quotes_by_ticker, today=today)
    upcoming = filter_upcoming(open_legs, horizon_days=14)

    # Position rows + KPIs piggyback on the same data — no extra DB hits.
    position_rows = _build_position_rows(open_positions, quotes_by_ticker, open_legs)
    kpis = _build_kpis(position_rows, open_legs, open_positions)

    # Activity feed
    recent_activity = _build_recent_activity(db)

    # Freshness
    sources_unavailable: list[str] = []
    if schwab_failed:
        sources_unavailable.append("schwab")
    is_stale = (
        schwab_failed
        or cache_status["stale"] + cache_status["very_stale"] > 0
    )

    return {
        "generated_at": now,
        "status": {
            "schwab": schwab_status,
            "fred": fred_status,
            "cache": cache_status,
            "journal": journal_status,
        },
        "kpis": kpis,
        "positions": position_rows,
        "open_legs": open_legs,
        "upcoming_expirations": upcoming,
        "recent_activity": recent_activity,
        "data_meta": {
            "is_stale": is_stale,
            "fetched_at": now,
            "sources_unavailable": sources_unavailable,
        },
    }
