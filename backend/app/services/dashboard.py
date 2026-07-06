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

from app.config import get_fred_api_key, settings
from app.models.database import CacheEntry, Position, Session as SessionModel, Trade
from app.services import journal as journal_service
from app.services.action_engine import compute_next_actions
from app.services.alpha_vantage_client import get_cached_next_earnings_date
from app.services.market_client import get_market_client
from app.services.dashboard_legs import (
    build_option_leg_index,
    derive_open_legs,
    market_today,
    parse_iso_to_utc,
)
from app.services.rules_config import load_rules_config
from app.services.schwab_auth import SchwabAuthError, SchwabTokenManager
# ``SchwabClient`` is re-exported into this module's namespace as the stable
# monkeypatch surface the dashboard integration tests target
# (``app.services.dashboard.SchwabClient.get_quote`` / ``.get_option_chain``).
# The live quote/chain fetches now go through :func:`get_market_client` (issue
# #349), which instantiates this same class object, so patching the method here
# still intercepts the live calls. Kept as an explicit re-export rather than an
# unused import.
from app.services.schwab_client import (  # noqa: F401  (test patch surface)
    SchwabClient,
    SchwabClientError,
)

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

    The ``error`` field is initialised to ``None`` and overwritten by
    :func:`build_dashboard_payload` when ``schwab_failed`` flips after the
    parallel quote / option-chain fan-out (issue #277).
    """
    mgr = SchwabTokenManager()
    configured = mgr.is_configured()
    return (
        {
            "configured": configured,
            "valid": configured,  # static fallback; see plan §4.5 / risk #2
            "expires_at": mgr.get_refresh_token_expiry(),
            "error": None,
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
    db: DBSession,
) -> tuple[dict[str, float | None], bool]:
    """Fetch live quotes for `tickers` concurrently. Returns
    (price_by_ticker, schwab_failed_flag).

    Any per-ticker failure — known Schwab errors (auth/client) *or*
    unexpected ones (httpx timeouts that escape tenacity, malformed quote
    payloads, etc.) — yields a None price for that ticker; the caller
    surfaces the partial outage via data_meta.sources_unavailable. We
    deliberately catch broad Exception inside the worker so one bad ticker
    cannot 500 the entire dashboard. KeyboardInterrupt / SystemExit still
    propagate.

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
    # Live Schwab client (prod default) or deterministic stub client on the QA
    # pricing_mode=="stub" path (issue #349). Behavior-neutral on prod.
    client = get_market_client(db)

    def _fetch(ticker: str) -> tuple[str, float | None, bool]:
        try:
            quote = client.get_quote(ticker)
        except (SchwabClientError, SchwabAuthError) as exc:
            logger.warning("Dashboard quote fetch failed for %s: %s", ticker, exc)
            return ticker, None, True
        except Exception:
            # Defense-in-depth: any other exception (network timeouts that
            # escape tenacity, malformed payloads causing KeyError, etc.)
            # must not propagate out of the worker — that would raise from
            # ThreadPoolExecutor.map and 500 the whole dashboard. Log with
            # traceback so the cause is debuggable.
            logger.exception("Unexpected error fetching quote for %s", ticker)
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


def _fetch_option_chains_parallel(
    tickers: Iterable[str],
    schwab_configured: bool,
    db: DBSession,
) -> tuple[dict[str, dict], bool]:
    """Fetch raw Schwab option chains for `tickers` concurrently.

    Returns ``(chains_by_ticker, schwab_failed_flag)``. ``chains_by_ticker``
    maps each ticker that resolved to its raw Schwab chains response; tickers
    whose fetch failed are simply omitted (their legs degrade to ``% CAPT —``).

    Modeled directly on :func:`_fetch_quotes_parallel`: thread pool capped at
    ``QUOTE_FANOUT_WORKERS``, one ``get_option_chain`` call per distinct
    open-leg ticker. Any per-ticker failure — known Schwab errors *or*
    unexpected ones — is caught inside the worker so a single bad ticker
    cannot 500 the dashboard; ``schwab_failed`` is set so the caller surfaces
    the partial outage via ``data_meta.sources_unavailable``.
    KeyboardInterrupt / SystemExit still propagate.

    NOTE: option-chain responses are NOT cached this slice — each dashboard
    load issues N blocking fetches (N = distinct open-leg tickers), consistent
    with the existing stock-quote fan-out. An in-process TTL cache is a
    deferred V1.2 follow-up.
    """
    unique = sorted({t for t in tickers if t})
    chains_by_ticker: dict[str, dict] = {}
    if not unique or not schwab_configured:
        # Schwab not configured is a known-unavailable source, not a failure —
        # the status strip already reports it. Return an empty index.
        return chains_by_ticker, False

    schwab_failed = False
    # Live Schwab client (prod default) or deterministic stub client on the QA
    # pricing_mode=="stub" path (issue #349). Behavior-neutral on prod.
    client = get_market_client(db)

    def _fetch(ticker: str) -> tuple[str, dict | None, bool]:
        try:
            chain = client.get_option_chain(ticker)
        except (SchwabClientError, SchwabAuthError) as exc:
            logger.warning(
                "Dashboard option-chain fetch failed for %s: %s", ticker, exc
            )
            return ticker, None, True
        except Exception:
            # Defense-in-depth: any other exception (network timeouts that
            # escape tenacity, malformed payloads, etc.) must not propagate
            # out of the worker — that would raise from ThreadPoolExecutor.map
            # and 500 the whole dashboard. Log with traceback; never surface
            # the raw message in a response (CLAUDE.md).
            logger.exception(
                "Unexpected error fetching option chain for %s", ticker
            )
            return ticker, None, True
        return ticker, (chain if isinstance(chain, dict) else None), False

    workers = min(QUOTE_FANOUT_WORKERS, len(unique))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for ticker, chain, failed in pool.map(_fetch, unique):
            if chain is not None:
                chains_by_ticker[ticker] = chain
            if failed:
                schwab_failed = True
    return chains_by_ticker, schwab_failed


# Maps the derived ``position.strategy`` lifecycle label to the V0.5 wheel
# status pill (spec §14.6). Unknown values collapse to "Holding" so a
# pre-recompute import doesn't crash the dashboard.
_STRATEGY_TO_WHEEL_STATUS: dict[str, str] = {
    "csp": "CSP",
    "cc": "CC",
    "wheel": "Wheel",
    "holding": "Holding",
}


def _derive_wheel_status(strategy: str, has_open_call: bool, has_open_put: bool) -> str:
    """Translate a position's derived strategy + open-leg presence into a
    user-facing wheel status pill (``CSP`` / ``CC`` / ``Wheel`` / ``Holding``).

    The strategy label is already recomputed authoritatively by
    :func:`app.services.positions.recompute_position_state`. We layer the
    open-call/open-put presence on top only to keep the pill in sync when
    the strategy column is out of date (pre-recompute imports). When both
    a put and a call are open on the same ticker, that's a wheel.
    """
    if has_open_call and has_open_put:
        return "Wheel"
    base = _STRATEGY_TO_WHEEL_STATUS.get(strategy)
    if base is not None:
        return base
    return "Holding"


def _build_position_rows(
    open_positions: list[dict],
    quotes_by_ticker: dict[str, float | None],
    open_legs: list[dict],
) -> list[dict]:
    """Convert journal positions into dashboard row shape, sorted by notional.

    Each row also carries the V0.5 signal fields ``wheel_status`` and
    ``pl_pct``. The ``next_suggested_action`` field is populated later by
    :func:`_attach_next_suggested_actions` after the action engine runs.
    """
    leg_count_by_position: dict[str, int] = {}
    has_open_put_by_ticker: dict[str, bool] = {}
    has_open_call_by_ticker: dict[str, bool] = {}
    for leg in open_legs:
        leg_count_by_position[leg["position_id"]] = (
            leg_count_by_position.get(leg["position_id"], 0) + 1
        )
        if leg.get("type") == "call":
            has_open_call_by_ticker[leg["ticker"]] = True
        elif leg.get("type") == "put":
            has_open_put_by_ticker[leg["ticker"]] = True

    rows: list[dict] = []
    for position in open_positions:
        shares = position.get("shares") or 0
        adjusted_cost_basis = position["adjusted_cost_basis"]
        ticker = position["ticker"]
        current_price = quotes_by_ticker.get(ticker)
        notional: float | None = None
        unrealized_pl: float | None = None
        pl_pct: float | None = None
        if shares > 0 and current_price is not None:
            notional = current_price * shares
            cost_per_share = adjusted_cost_basis / shares if shares else 0.0
            unrealized_pl = (current_price - cost_per_share) * shares
            if adjusted_cost_basis > 0:
                pl_pct = (current_price * shares - adjusted_cost_basis) / adjusted_cost_basis
        wheel_status = _derive_wheel_status(
            position["strategy"],
            has_open_call=has_open_call_by_ticker.get(ticker, False),
            has_open_put=has_open_put_by_ticker.get(ticker, False),
        )
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
                "wheel_status": wheel_status,
                "next_suggested_action": "hold",  # overwritten after the engine runs
                "pl_pct": pl_pct,
                # Broker basis is surfaced so the Positions card can render
                # the dual-line "broker / adjusted" cost-basis cell (#151).
                "broker_cost_basis": position.get("broker_cost_basis"),
                # Per-share basis (#320) — the card renders these so the
                # cost-basis cell aligns with the per-share Current column.
                # Already computed (and shares==0 → null guarded) by the
                # journal producer; thread them straight through.
                "broker_cost_basis_per_share": position.get(
                    "broker_cost_basis_per_share"
                ),
                "adjusted_cost_basis_per_share": position.get(
                    "adjusted_cost_basis_per_share"
                ),
            }
        )
    # Sort by notional desc (None last), then ticker asc.
    rows.sort(key=lambda r: (-(r["notional"] or 0.0), r["ticker"]))
    return rows


# Maps each action_id to a short display label used in the per-position
# "next action" column. The action engine title is intentionally
# action-oriented (e.g. "Roll AAPL 175P"); this label is the *summary*
# rendered in the table cell.
_NEXT_ACTION_TABLE_LABEL: dict[str, str] = {
    "data.schwab_disconnected": "Reconnect",
    "data.cache_very_stale": "Refresh data",
    "data.schwab_token_expiring": "Renew token",
    "position.large_loser": "Review",
    "expiration.itm_short_dte": "Roll",
    "expiration.short_dte": "Manage",
    "position.cc_candidate": "Cover",
    "journal.no_open_legs": "Run scanner",
    # New in V1.0.4 (#240) — the §R6 rule-monitor leg cards.
    "leg.profit_take_review": "Review",
    "leg.dte_review": "Review",
}


def _attach_next_suggested_actions(
    rows: list[dict],
    next_actions: list[dict],
    open_legs: list[dict],
) -> None:
    """Stamp each position row with the highest-priority targeted action label.

    Position-targeted actions point straight to a position by id (e.g.
    ``position.large_loser`` carries the position id in its action id).
    Leg-targeted actions resolve via ``open_legs`` → ``position_id``. The
    first matching action wins because :func:`compute_next_actions`
    already sorted by priority. Positions without a match keep the default
    ``"hold"``.
    """
    position_id_by_leg = {leg["id"]: leg["position_id"] for leg in open_legs}
    label_by_position: dict[str, str] = {}
    for action in next_actions:
        action_id = action["action_id"]
        label = _NEXT_ACTION_TABLE_LABEL.get(action_id)
        if label is None:
            continue
        prefix = f"{action_id}."
        subject_id = (
            action["id"][len(prefix):] if action["id"].startswith(prefix) else ""
        )
        if action_id == "position.large_loser":
            # Subject id is the position uuid.
            if subject_id and subject_id not in label_by_position:
                label_by_position[subject_id] = label
        elif action_id in {
            "expiration.itm_short_dte",
            "leg.profit_take_review",
            "leg.dte_review",
        }:
            # Subject id is the leg/trade uuid — resolve via the legs map.
            position_id = position_id_by_leg.get(subject_id)
            if position_id and position_id not in label_by_position:
                label_by_position[position_id] = label
        elif action_id in {"position.cc_candidate", "expiration.short_dte"}:
            # Subject is a ticker slug — resolve through the row scan so the
            # label lands on every open position for that ticker.
            ticker = (action.get("subject") or {}).get("ticker")
            if not ticker:
                continue
            for row in rows:
                if row["ticker"] == ticker and row["id"] not in label_by_position:
                    label_by_position[row["id"]] = label

    for row in rows:
        row["next_suggested_action"] = label_by_position.get(row["id"], "hold")


def _compute_largest_risk(position_rows: list[dict]) -> dict | None:
    """Return the worst loser among open positions, or ``None``.

    Picks the most-negative ``unrealized_pl``; positions without a price
    or with non-negative P/L are skipped. Ties are broken by ticker A→Z
    so the engine output is deterministic.
    """
    losers: list[tuple[float, str, dict]] = []
    for row in position_rows:
        pl = row.get("unrealized_pl")
        if pl is None or pl >= 0:
            continue
        losers.append((pl, row["ticker"], row))
    if not losers:
        return None
    losers.sort(key=lambda triple: (triple[0], triple[1]))
    _, _, worst = losers[0]
    return {
        "ticker": worst["ticker"],
        "unrealized_pl": worst["unrealized_pl"],
        "unrealized_pl_pct": worst.get("pl_pct"),
    }


def _sum_premium_for_positions(positions: list[dict]) -> tuple[float, int]:
    """Sum ``total_premiums`` and trade counts across positions.

    Trade counts include every trade attached to the supplied positions,
    not just leg-opening trades — the KPI tile is "trades that contributed
    to the premium total".
    """
    total = 0.0
    count = 0
    for position in positions:
        total += float(position.get("total_premiums") or 0.0)
        count += len(position.get("trades") or [])
    return total, count


def _sum_premium_ytd(positions: list[dict], today: date) -> float:
    """Sum credit/debit premium across trades closed in the current year.

    Uses ``closed_at`` when present, falling back to ``opened_at``; per
    the locked spec the YTD field is not rendered as a tile in V0.5 but
    is emitted for downstream analytics. Trades without parseable timestamps
    are skipped silently.
    """
    year = today.year
    total = 0.0
    for position in positions:
        for trade in position.get("trades") or []:
            anchor = trade.get("closed_at") or trade.get("opened_at")
            parsed = parse_iso_to_utc(anchor)
            if parsed is None:
                continue
            if parsed.year != year:
                continue
            premium = float(trade.get("premium") or 0.0)
            qty = int(trade.get("quantity") or 0)
            total += premium * qty * 100
    return total


def _compute_realized_pl(closed_positions: list[dict]) -> tuple[float, float | None]:
    """Compute lifetime realized P/L and percent across closed positions.

    Per the locked architectural decision in issue #146, V0.5 uses the
    "simple" formula: ``realized_pl = sum(total_premiums)`` across closed
    positions. Assignment / called-away cash flows are not yet tracked
    explicitly — a follow-up issue will model close-out proceeds.

    Percent is ``realized_pl / sum(broker_cost_basis)``; returns ``None``
    when the denominator is zero or negative (no comparable basis).
    """
    if not closed_positions:
        return 0.0, None
    realized_pl = sum(
        float(p.get("total_premiums") or 0.0) for p in closed_positions
    )
    cost_basis_total = sum(
        float(p.get("broker_cost_basis") or 0.0) for p in closed_positions
    )
    if cost_basis_total <= 0:
        return realized_pl, None
    return realized_pl, realized_pl / cost_basis_total


def _sum_equity_realized_pl(positions: list[dict]) -> float:
    """Sum derived equity realized P&L across positions (issues #386/#387).

    Each position row carries ``realized_equity_pl`` from
    :func:`app.services.journal._build_position_response` (derived per ADR #391,
    not stored). Open positions can carry realized P&L from a partial sell, so
    this sums across the full open+closed set rather than the closed-only set
    used by the premium-based realized-P/L formula. Options-only positions
    contribute ``0.0``.
    """
    return sum(float(p.get("realized_equity_pl") or 0.0) for p in positions)


def _compute_largest_loser(closed_positions: list[dict]) -> dict | None:
    """Return the worst realized loser among closed positions, or ``None``."""
    if not closed_positions:
        return None
    losers: list[tuple[float, str, dict]] = []
    for position in closed_positions:
        realized = float(position.get("total_premiums") or 0.0)
        if realized >= 0:
            continue
        losers.append((realized, position["ticker"], position))
    if not losers:
        return None
    losers.sort(key=lambda triple: (triple[0], triple[1]))
    realized, ticker, worst = losers[0]
    basis = float(worst.get("broker_cost_basis") or 0.0)
    pct = realized / basis if basis > 0 else None
    return {
        "ticker": ticker,
        "realized_pl": realized,
        "realized_pl_pct": pct,
    }


def _build_kpis(
    position_rows: list[dict],
    open_legs: list[dict],
    open_positions: list[dict],
    closed_positions: list[dict],
    today: date,
) -> dict:
    """Aggregate KPI tiles from already-built row data.

    ``closed_positions`` powers the realized-P/L and largest-loser tiles.
    ``today`` is threaded through so YTD scopes are deterministic in tests.
    """
    open_positions_count = len(position_rows)
    # ``stock`` is a vestigial bucket retained for response-shape stability
    # (see DashboardOpenPositionsBreakdown docstring); ``holding`` is the
    # new bucket added for issue #131. Unknown labels (closed positions or
    # raw values from pre-recompute imports) are silently dropped.
    breakdown = {"stock": 0, "csp": 0, "cc": 0, "wheel": 0, "holding": 0}
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

    all_positions = list(open_positions) + list(closed_positions)
    premium_total, premium_trades = _sum_premium_for_positions(all_positions)
    premium_ytd = _sum_premium_ytd(all_positions, today=today)

    # Realized P/L from CLOSED positions' premium (existing simple formula,
    # issue #146) PLUS equity realized P&L across ALL positions. Equity
    # realized P&L can exist on an OPEN position (partially sold) so it cannot
    # be folded into the closed-only premium path; it is added as a separate
    # addend (issues #386/#387, ADR #391). The premium semantics are unchanged.
    realized_pl, realized_pl_pct = _compute_realized_pl(closed_positions)
    equity_realized_pl = _sum_equity_realized_pl(all_positions)
    realized_pl += equity_realized_pl
    # ``realized_pl_pct`` from _compute_realized_pl describes only the
    # closed-position premium numerator over its cost basis. Once equity
    # realized P&L is folded into the amount, the percent no longer refers to
    # the same numerator and there is no single coherent denominator (equity
    # P&L can come from still-open partial sells). Null it rather than report a
    # mismatched percent (CodeRabbit, PR #392).
    if equity_realized_pl != 0:
        realized_pl_pct = None

    return {
        "open_positions": open_positions_count,
        "open_positions_breakdown": breakdown,
        "notional_value": notional_value,
        "notional_change_pct": notional_change_pct,
        "open_legs": len(open_legs),
        "open_legs_breakdown": {"puts": puts, "calls": calls},
        "unrealized_pl": unrealized_pl,
        "unrealized_pl_pct": unrealized_pl_pct,
        "largest_risk": _compute_largest_risk(position_rows),
        "largest_loser": _compute_largest_loser(closed_positions),
        "premium_collected_total": premium_total,
        "premium_collected_ytd": premium_ytd,
        "premium_collected_trades": premium_trades,
        "realized_pl": realized_pl,
        "realized_pl_pct": realized_pl_pct,
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
    # DTE/expiration counts and YTD scoping run on the US market (Eastern)
    # calendar, not the server's UTC clock (issue #418 — a UTC ``date.today()``
    # rolls a day early after 20:00 ET and knocked DTE one day low).
    today = today or market_today()

    # Status block
    schwab_status, schwab_configured = _build_schwab_status()
    # On the QA stub-pricing path (issue #349) there is no live Schwab feed, so
    # ``schwab_configured`` is False and the fetch fan-outs would short-circuit.
    # The stub client serves the deterministic feed instead, so treat the feed
    # as available whenever pricing_mode=="stub". Prod stays "live" → no change.
    feed_available = schwab_configured or settings.pricing_mode == "stub"
    fred_status = _build_fred_status()
    cache_status = _bucket_cache_freshness(db)

    # Positions — fetch both open and closed in one go so realized-P/L
    # KPIs and the action engine see the same snapshot.
    open_positions = journal_service.get_positions(db, status="open")
    closed_positions = journal_service.get_positions(db, status="closed")
    journal_status = {"positions_count": len(open_positions)}

    # Trading rules — resolved once here (the service layer) and reused by
    # both derive_open_legs (profit-target threshold) and the action engine.
    rules = load_rules_config(db)

    # Quotes (parallelized; deduped by ticker)
    tickers = [p["ticker"] for p in open_positions]
    quotes_by_ticker, schwab_failed = _fetch_quotes_parallel(
        tickers, schwab_configured=feed_available, db=db
    )

    # Option chains for the % CAPT signal — fetched only for positions that
    # actually carry an open sell_put/sell_call leg (a strict subset of the
    # stock-quote ticker set). Parallel fan-out mirrors the quote fetch.
    open_leg_tickers = {
        p["ticker"]
        for p in open_positions
        for trade in p.get("trades", [])
        if trade.get("trade_type") in ("sell_put", "sell_call")
        and not trade.get("closed_at")
    }
    option_chains, chains_failed = _fetch_option_chains_parallel(
        open_leg_tickers, schwab_configured=feed_available, db=db
    )
    schwab_failed = schwab_failed or chains_failed
    # Richer per-leg index carrying delta (issue #318). Spot is threaded so the
    # Black-Scholes delta fallback can run on illiquid strikes.
    option_marks = build_option_leg_index(option_chains, spots_by_ticker=quotes_by_ticker)

    # Legs derive purely from in-memory data + the quote/mark maps. Earnings
    # lookup is cache-hit-only — the request path must not block on AV.
    open_legs = derive_open_legs(
        open_positions,
        quotes_by_ticker,
        today=today,
        earnings_lookup=get_cached_next_earnings_date,
        option_marks=option_marks,
        profit_review_pct=rules.management.profit_review_pct,
        dte_review_days=rules.management.dte_review_days,
        expiration_warning_days=rules.management.expiration_warning_days,
    )

    # Position rows + KPIs piggyback on the same data — no extra DB hits.
    position_rows = _build_position_rows(open_positions, quotes_by_ticker, open_legs)
    kpis = _build_kpis(
        position_rows,
        open_legs,
        open_positions,
        closed_positions=closed_positions,
        today=today,
    )

    # Action engine — pure, deterministic, recomputed every call (spec §2.2).
    # Trading rules are resolved here (the router/service layer) and passed
    # in so the engine stays a pure function with no DB dependency (#156).
    next_actions = compute_next_actions(
        status={
            "schwab": schwab_status,
            "fred": fred_status,
            "cache": cache_status,
            "journal": journal_status,
        },
        kpis=kpis,
        positions=position_rows,
        open_legs=open_legs,
        rules=rules,
    )
    _attach_next_suggested_actions(position_rows, next_actions, open_legs)

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

    # Issue #277: reconcile the Schwab pill with the live-call outcome.
    # ``_build_schwab_status`` reports the token-row state only (configured +
    # refresh-token expiry); it has no visibility into whether the parallel
    # quote / option-chain fans actually succeeded. When ``schwab_failed`` is
    # set we downgrade ``valid`` to ``False`` and surface a frozen ``error``
    # string so the frontend can disambiguate "token expiring" from "calls
    # failing this load". The string is the discriminator only — the visible
    # pill label is built by the frontend.
    if schwab_failed and schwab_status.get("valid"):
        schwab_status["valid"] = False
        schwab_status["error"] = "Schwab API calls failing this load"

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
        "recent_activity": recent_activity,
        "data_meta": {
            "is_stale": is_stale,
            "fetched_at": now,
            "sources_unavailable": sources_unavailable,
        },
        "next_actions": next_actions,
    }
