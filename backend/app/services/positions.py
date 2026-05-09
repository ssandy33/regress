"""Derive position lifecycle state from a position's trade ledger.

The journal stores positions and the trades attached to them as an append-only
ledger. ``status`` / ``shares`` / ``broker_cost_basis`` / ``closed_at`` on the
``Position`` row are *derived* values: they are whatever the trade ledger says
they should be. This module is the single source of truth for that derivation.

The function :func:`recompute_position_state` is called from two places:

* :mod:`app.services.schwab_import` after a Schwab import (CSV or API path)
  inserts trades, so the touched positions are immediately consistent with the
  ledger they just received.
* :mod:`backend.scripts.reconcile_positions`, which lets a user re-derive every
  position in their journal in case earlier imports (pre-fix) left stale state.

The recomputer is **idempotent** — running it twice on the same ledger yields
the same final state. That property is what makes the reconciliation script
safe to re-run.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.database import Position, Trade

logger = logging.getLogger(__name__)


# Module-level dedupe set for unpaired-resolution warnings. Reconciliation can
# replay the entire journal repeatedly (e.g., backend/scripts/reconcile_positions
# runs across the whole DB and a user may run it more than once); the first
# encounter of an unpaired resolving event is genuine signal, but subsequent
# replays of the same ``(position_id, trade_id)`` are noise. We log the first
# at WARNING and any later replay at INFO. The set is process-local — that is
# good enough for the dev/reconciliation workflow this guards, and it resets
# cleanly on process restart.
_warned_unpaired: set[tuple[str, str]] = set()


def _reset_unpaired_warning_cache() -> None:
    """Clear the unpaired-resolution warning de-dup cache.

    Exposed for tests that need a deterministic starting state. Production
    callers should not need to invoke this.
    """
    _warned_unpaired.clear()


def _utc_today() -> date:
    """Return today's date in UTC.

    Used as the default ``clock`` for :func:`recompute_position_state`. UTC is
    fine at day granularity because option expirations settle at 4 PM ET; by
    the time UTC ticks over the next calendar day, ET is well past close, so
    "is this expiration date < today (UTC)?" never closes a leg before its
    settlement time. Tests inject a frozen-clock callable to keep behavior
    deterministic.
    """
    return datetime.now(tz=timezone.utc).date()


# Trade types that close out an existing option leg. Each consumes one open leg
# of the matching (option_type, strike, expiration) when it appears.
_OPTION_CLOSE_TYPES = {
    "buy_put_close",
    "buy_call_close",
    "assignment",
    "called_away",
    "expired",
}


@dataclass(frozen=True)
class _LegKey:
    """Identifies an open option leg for matching against a closing trade.

    ``trade_id`` is the ``Trade.id`` of the originating opening row (e.g. the
    ``sell_put`` / ``sell_call`` that created the leg). It is carried through
    the in-memory replay so that when the leg is consumed (by a resolving
    trade or by the calendar fallback) the recomputer can stamp
    ``Trade.closed_at`` on the right Trade row — which is what the dashboard's
    ``derive_open_legs`` filter reads to drop already-resolved legs from the
    "Open option legs" view (issue #136).
    """

    option_type: str  # "put" or "call"
    strike: float
    expiration: str
    trade_id: str  # Trade.id of the originating opening row


def _option_type_for_open(trade_type: str) -> str | None:
    """Return ``"put"`` / ``"call"`` for an opening trade, else ``None``."""
    if trade_type == "sell_put":
        return "put"
    if trade_type == "sell_call":
        return "call"
    return None


def _option_type_for_close(trade_type: str) -> str | None:
    """Return the option side that this closing trade consumes, else ``None``.

    ``assignment`` consumes a put leg (the put that was assigned). ``called_away``
    consumes a call leg. ``expired`` is ambiguous on its own, but the matching
    pass tries put-then-call so the worthless-expired side is cleared either way.
    """
    if trade_type == "buy_put_close" or trade_type == "assignment":
        return "put"
    if trade_type == "buy_call_close" or trade_type == "called_away":
        return "call"
    if trade_type == "expired":
        return None  # try both sides
    return None


def _consume_leg(
    open_legs: list[_LegKey],
    option_type: str | None,
    strike: float,
    expiration: str,
    ticker: str,
    trade_type: str,
    position_id: str | None = None,
    trade_id: str | None = None,
) -> _LegKey | None:
    """Remove a matching open leg from ``open_legs`` using a two-pass strategy.

    **Pass 1 (strict):** match by ``(option_type, strike, expiration)``. This
    is the well-formed case — most resolving events match the originating leg
    exactly and this pass picks them off without disturbing other legs.

    **Pass 2 (FIFO fallback):** when no strict match exists, consume the
    earliest-expiring open leg of the matching side (``put`` for
    ``buy_put_close`` / ``assignment``; ``call`` for ``buy_call_close`` /
    ``called_away``; either side for ``expired``). Ties broken by insertion
    order, which mirrors ``opened_at`` because ``recompute_position_state``
    replays trades in chronological order. This handles the dirty-data case
    documented in issue #134 where strikes or expirations on a resolving
    Schwab CSV row drift slightly from the originating short leg.

    When ``option_type`` is ``None`` (``expired`` — ambiguous side) each pass
    runs put-first then call so the worthless-expired side gets cleared
    deterministically.

    Returns the consumed :class:`_LegKey` if a leg was matched, or ``None``
    when both passes fail. The caller uses ``_LegKey.trade_id`` of the
    returned leg to stamp ``Trade.closed_at`` on the originating opening row
    (issue #136). The first failure for a given ``(position_id, trade_id)``
    is logged at WARNING; subsequent replays of the same pair (e.g., when
    the reconciliation script is re-run) drop to INFO via the module-level
    :data:`_warned_unpaired` cache so the same data-integrity gap doesn't
    flood the log on every recompute. The caller continues either way,
    applying any shares/basis side effects the resolution event still implies.
    """
    candidates: list[str]
    if option_type is None:
        candidates = ["put", "call"]
    else:
        candidates = [option_type]

    # Pass 1 — strict (option_type, strike, expiration) match.
    for candidate in candidates:
        for idx, leg in enumerate(open_legs):
            if (
                leg.option_type == candidate
                and leg.strike == strike
                and leg.expiration == expiration
            ):
                consumed = open_legs[idx]
                del open_legs[idx]
                return consumed

    # Pass 2 — FIFO fallback by expiration on the matching side.
    for candidate in candidates:
        side_indices = [
            i for i, leg in enumerate(open_legs) if leg.option_type == candidate
        ]
        if not side_indices:
            continue
        # NOTE: ``expiration`` is stored as an ISO ``YYYY-MM-DD`` string, which
        # sorts lexicographically the same as chronologically — but only because
        # of that fixed format. If the storage format ever changes (e.g., to a
        # date object or a different string layout), parse to ``date`` here.
        fifo_idx = min(side_indices, key=lambda i: open_legs[i].expiration)
        consumed = open_legs[fifo_idx]
        del open_legs[fifo_idx]
        logger.info(
            "recompute_position_state: FIFO fallback closed %s leg "
            "strike=%s exp=%s for %s on %s (no strict match for "
            "strike=%s exp=%s)",
            consumed.option_type,
            consumed.strike,
            consumed.expiration,
            trade_type,
            ticker,
            strike,
            expiration,
        )
        return consumed

    # First encounter of this unpaired event is genuine signal (WARNING).
    # Subsequent recomputes of the same ``(position_id, trade_id)`` pair are
    # noise — reconciliation re-runs would otherwise spam identical warnings —
    # so demote to INFO. When ``position_id`` or ``trade_id`` are unknown
    # (defensive default), fall back to the original WARNING behavior.
    dedupe_key: tuple[str, str] | None = None
    if position_id is not None and trade_id is not None:
        dedupe_key = (position_id, trade_id)
    log_fn = (
        logger.info
        if dedupe_key is not None and dedupe_key in _warned_unpaired
        else logger.warning
    )
    log_fn(
        "recompute_position_state: no matching open leg for %s on %s "
        "(strike=%s, expiration=%s); ledger may be incomplete",
        trade_type,
        ticker,
        strike,
        expiration,
    )
    if dedupe_key is not None:
        _warned_unpaired.add(dedupe_key)
    return None


def _apply_calendar_close(
    open_legs: list[_LegKey],
    ticker: str,
    today: date,
) -> tuple[list[_LegKey], str | None, list[_LegKey]]:
    """Close any open leg whose expiration date is in the past.

    A leg whose ``expiration < today`` with no recorded resolving trade is
    treated as expired worthless. This is the calendar fallback for the
    Schwab-CSV gap where an "Expired" row never lands for a long-OTM
    contract. See issue #134.

    Returns a tuple of ``(still_open, latest_expiration, consumed_legs)``:

    * ``still_open`` — subset of ``open_legs`` whose expiration is today or
      later (legs that were not swept by the calendar fallback).
    * ``latest_expiration`` — largest expiration string among the closed
      legs (used by the caller as a candidate ``closed_at`` when no real
      resolving trade has stamped one). ``None`` if no legs were closed.
    * ``consumed_legs`` — legs swept by this pass. The caller uses each
      consumed leg's ``trade_id`` to stamp ``Trade.closed_at`` on the
      originating opening row (issue #136). Empty list if no legs were
      closed.
    """
    still_open: list[_LegKey] = []
    consumed: list[_LegKey] = []
    closed_expirations: list[str] = []
    for leg in open_legs:
        try:
            leg_exp = date.fromisoformat(leg.expiration)
        except (TypeError, ValueError):
            # Unparseable expiration: leave the leg alone — calendar-close
            # only fires when we can prove the leg is past expiration.
            still_open.append(leg)
            continue
        if leg_exp < today:
            consumed.append(leg)
            closed_expirations.append(leg.expiration)
            logger.info(
                "recompute_position_state: calendar fallback closing %s leg "
                "strike=%s exp=%s on %s (past expiration, no resolving trade)",
                leg.option_type,
                leg.strike,
                leg.expiration,
                ticker,
            )
        else:
            still_open.append(leg)

    latest = max(closed_expirations) if closed_expirations else None
    return still_open, latest, consumed


def _derive_strategy_label(shares: int, open_legs: list[_LegKey]) -> str:
    """Derive the displayed strategy label from a position's current state.

    Maps ``(shares, open_put_count, open_call_count)`` to one of
    ``"csp" | "cc" | "wheel" | "holding"`` per issue #131:

    ====================================  =========
    state                                 label
    ====================================  =========
    0 shares, only open puts              ``csp``
    shares held, only open calls          ``cc``
    shares held, open puts AND calls      ``wheel``
    shares held, no open option legs      ``holding``
    0 shares, no open option legs         ``csp`` (caller-handled "closed")
    0 shares, only open calls (anomaly)   ``cc`` (logged warning — naked
                                          call has no place in a wheel flow
                                          but the label that matches the
                                          live legs is the least-misleading
                                          choice)
    0 shares, both open puts and calls    ``csp`` (puts dominate when no
                                          shares are held)
    ====================================  =========

    Pure function — no DB access — to keep the mapping unit-testable in
    isolation from the trade-replay machinery in
    :func:`recompute_position_state`. The caller is responsible for
    short-circuiting on the closed state (``shares == 0`` and no open legs);
    this function still returns a defensible label for that input so it is
    safe to call unconditionally.
    """
    open_puts = sum(1 for leg in open_legs if leg.option_type == "put")
    open_calls = sum(1 for leg in open_legs if leg.option_type == "call")

    if shares > 0:
        if open_puts > 0 and open_calls > 0:
            return "wheel"
        if open_calls > 0:
            return "cc"
        if open_puts > 0:
            # Short put while holding shares — uncommon (mid-cycle layered
            # entry) but valid; csp is the closest single-side label.
            return "csp"
        return "holding"

    # shares == 0 below
    if open_calls > 0 and open_puts == 0:
        # Naked calls without shares should not occur in a wheel-only flow.
        # Surface the anomaly via a warning but return ``"cc"`` because that
        # is the label that best matches the live legs — the alternative
        # ("csp") would directly contradict what the user is looking at.
        logger.warning(
            "_derive_strategy_label: 0 shares with %d open call leg(s) and "
            "no open puts; returning 'cc' but this state is anomalous in a "
            "wheel-only journal",
            open_calls,
        )
        return "cc"
    return "csp"


def recompute_position_state(
    db: Session,
    position_id: str,
    commit: bool = True,
    clock: Callable[[], date] | None = None,
) -> Position | None:
    """Walk a position's trade ledger and derive its lifecycle state.

    Sorts trades by ``(opened_at, id)`` and replays them, tracking shares,
    broker_cost_basis, and the list of currently-open option legs. At the end:

    * ``status`` is ``"closed"`` if and only if shares == 0 and no open option
      legs remain. ``closed_at`` is set to the ``opened_at`` of the last trade
      that drove the position to a closed state (cleared again if it later
      reopens within the same Position — though "reopen-after-close" creates a
      new Position elsewhere, so this clearing path is mostly defensive). When
      the calendar fallback (below) is what drove the position to closed,
      ``closed_at`` is the latest ``expiration`` among the calendar-closed
      legs, since no real resolving trade exists to supply an ``opened_at``.
    * ``shares`` and ``broker_cost_basis`` are recomputed from scratch.
    * ``strategy`` is derived from ``(shares, open_legs)`` per issue #131 —
      see :func:`_derive_strategy_label` for the truth table. This makes the
      label authoritative on what the position is actually doing right now
      (csp / cc / wheel / holding) instead of trusting whatever the import
      pipeline guessed at row-creation time. Closed positions retain their
      last-derived label for historical reading; the dashboard suppresses
      the label for closed positions.

    **Leg pairing strategy (issue #134):** when a resolving trade arrives
    (``buy_put_close`` / ``buy_call_close`` / ``assignment`` / ``called_away``
    / ``expired``), :func:`_consume_leg` first tries a strict
    ``(option_type, strike, expiration)`` match. If no exact match exists it
    falls back to FIFO-by-expiration on the matching side — the
    earliest-expiring open leg of the right side is consumed instead. This
    fixes the dirty-data case where a Schwab CSV row's strike or expiration
    drifts slightly from the originating short leg. After both passes fail a
    warning is logged but the import keeps running.

    **Calendar fallback (issue #134):** after replaying every trade, any open
    leg whose ``expiration`` is strictly before ``clock()`` is treated as
    expired worthless and removed. This covers the case where Schwab never
    posted an "Expired" row for a long-OTM contract. The current UTC date is
    the default cutoff; tests inject a frozen-clock callable. Future-dated
    legs (``expiration >= today``) are never auto-closed.

    Per-trade-type semantics:

    ====================  ============  ===================================  ============
    trade_type            shares delta  basis delta                          legs delta
    ====================  ============  ===================================  ============
    sell_put              0             0                                    +1 put
    sell_call             0             0                                    +1 call
    buy_put_close         0             0                                    -1 put leg
    buy_call_close        0             0                                    -1 call leg
    assignment (PUT)      + qty*100     + strike * qty * 100                 -1 put leg
    called_away (CALL)    - qty*100     - basis * (qty*100 / shares)         -1 call leg
    expired               0             0                                    -1 leg (any)
    ====================  ============  ===================================  ============

    **Partial called-away basis rule:** if the user holds 200 shares and a
    single call (100 shares' worth) is exercised, basis is reduced
    *proportionally* (``basis * 100 / 200``); shares go to 100, position stays
    open. This is simpler than tracking lot-FIFO and matches typical broker
    journal display closely enough; the trade-off is documented in the module
    docstring of the issue plan.

    The function is idempotent: running it twice on the same trade ledger
    yields the same Position state.

    Args:
        db: SQLAlchemy session bound to the journal database.
        position_id: ID of the Position to recompute.
        commit: If True (default), commit the derived state to the database.
            Pass False from a dry-run / preview caller that wants to inspect
            the result without persisting it.
        clock: Callable returning today's date. Defaults to ``None``, which
            resolves to :func:`_utc_today` lazily inside the function so a
            test can ``monkeypatch.setattr(module, "_utc_today", ...)`` and
            have it take effect through normal call sites that don't pass
            ``clock`` explicitly. Tests with direct access to this kwarg
            inject a frozen-clock callable for deterministic fallback
            behavior.

    Returns:
        The refreshed Position ORM object, or None if no Position with that ID
        exists. Never raises on per-trade ledger inconsistencies (orphan close,
        missing leg) — those are logged as warnings so the recomputer keeps
        running across the rest of the journal.
    """
    position = db.query(Position).filter(Position.id == position_id).first()
    if position is None:
        return None

    # Resolve ``clock`` lazily so tests that monkey-patch ``_utc_today`` see
    # the patched callable. Default-argument binding would freeze the
    # original module-level function at import time and defeat the patch.
    if clock is None:
        clock = _utc_today

    trades: list[Trade] = sorted(
        position.trades,
        key=lambda t: (t.opened_at or "", t.id or ""),
    )

    shares = 0
    basis = 0.0
    open_legs: list[_LegKey] = []
    last_close_at: str | None = None
    # (trade_id, closed_at) pairs accumulated while replaying trades and from
    # the calendar-fallback pass. Applied to ``Trade.closed_at`` in a single
    # pass after the replay so the helpers stay pure (issue #136).
    closes_to_write: list[tuple[str, str]] = []

    for trade in trades:
        ttype = trade.trade_type
        qty = int(trade.quantity or 1)
        contract_shares = qty * 100

        # Opening a new option leg.
        opening_side = _option_type_for_open(ttype)
        if opening_side is not None:
            for _ in range(qty):
                open_legs.append(
                    _LegKey(
                        option_type=opening_side,
                        strike=float(trade.strike),
                        expiration=trade.expiration,
                        trade_id=trade.id,
                    )
                )
            continue

        # Closing trade types: consume one matching open leg per contract.
        if ttype in _OPTION_CLOSE_TYPES:
            close_side = _option_type_for_close(ttype)
            for _ in range(qty):
                consumed = _consume_leg(
                    open_legs,
                    close_side,
                    float(trade.strike),
                    trade.expiration,
                    position.ticker,
                    ttype,
                    position_id=position.id,
                    trade_id=trade.id,
                )
                if consumed is not None and trade.opened_at is not None:
                    # Stamp the resolving trade's opened_at on the consumed
                    # leg's originating Trade row (issue #136).
                    closes_to_write.append((consumed.trade_id, trade.opened_at))

            if ttype == "assignment":
                # Put assigned: acquire shares at strike.
                shares += contract_shares
                basis += float(trade.strike) * contract_shares
            elif ttype == "called_away":
                # Call exercised: shares are removed at the option's strike;
                # broker basis is reduced proportionally to the shares removed.
                if shares > 0:
                    removed = min(contract_shares, shares)
                    if removed < contract_shares:
                        logger.warning(
                            "recompute_position_state: called_away on %s "
                            "requested %d shares but only %d held; "
                            "truncating removal (ledger may be incomplete)",
                            position.ticker,
                            contract_shares,
                            shares,
                        )
                    if shares > 0 and basis != 0.0:
                        basis = basis * (1 - removed / shares)
                    shares -= removed
                else:
                    logger.warning(
                        "recompute_position_state: called_away on %s with no "
                        "shares held; treating as no-op",
                        position.ticker,
                    )

            # If this trade brought the position to a fully-closed state,
            # remember its opened_at as the close timestamp.
            if shares == 0 and not open_legs:
                last_close_at = trade.opened_at

            continue

        logger.warning(
            "recompute_position_state: unknown trade_type %r on %s; ignoring",
            ttype,
            position.ticker,
        )

    # Calendar fallback: any leg past expiration with no resolving trade is
    # treated as expired worthless. See module/function docstring (issue #134).
    open_legs, calendar_close_at, calendar_consumed = _apply_calendar_close(
        open_legs, position.ticker, clock()
    )
    for leg in calendar_consumed:
        # Synthetic worthless-expiry: stamp the leg's expiration on the
        # originating Trade row (issue #136). No real resolving trade exists
        # to supply an ``opened_at``, so the expiration is the canonical
        # close date — same value the position-level ``closed_at`` would use.
        closes_to_write.append((leg.trade_id, leg.expiration))
    if (
        calendar_close_at is not None
        and shares == 0
        and not open_legs
        and last_close_at is None
    ):
        # No real resolving trade stamped a closed_at — use the latest
        # calendar-closed leg's expiration as the canonical close date.
        last_close_at = calendar_close_at

    # Persist Trade.closed_at on consumed legs so dashboard_legs.derive_open_legs
    # (which filters on Trade.closed_at IS NULL) sees the resolved legs as
    # closed. Build the trade map from the already-loaded ``position.trades``
    # collection — no extra query, and the rows are tracked by the session.
    # Skip rows that already have ``closed_at`` set so a real resolving date
    # is never overwritten by a later synthetic-expiration stamp (issue #136).
    if closes_to_write:
        trade_by_id = {t.id: t for t in position.trades}
        for trade_id, close_value in closes_to_write:
            trade_row = trade_by_id.get(trade_id)
            if trade_row is None:
                # Defensive — _LegKey.trade_id always comes from a Trade
                # currently attached to this Position, so this should not
                # fire in practice.
                continue
            if trade_row.closed_at is not None:
                continue
            trade_row.closed_at = close_value

    # Apply the derived state to the Position row.
    position.shares = shares
    position.broker_cost_basis = round(basis, 4)
    position.strategy = _derive_strategy_label(shares, open_legs)
    if shares == 0 and not open_legs:
        position.status = "closed"
        position.closed_at = last_close_at or position.closed_at
    else:
        position.status = "open"
        position.closed_at = None

    if commit:
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(position)
    return position
