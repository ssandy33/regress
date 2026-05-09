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
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.database import Position, Trade

logger = logging.getLogger(__name__)


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
    """Identifies an open option leg for matching against a closing trade."""

    option_type: str  # "put" or "call"
    strike: float
    expiration: str


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
) -> bool:
    """Remove the first matching open leg from ``open_legs``.

    Match is by (option_type, strike, expiration); when ``option_type`` is None
    (``expired`` trade type — see :func:`_option_type_for_close`) either side
    is accepted, put first. FIFO for ties.

    Returns ``True`` if a leg was consumed, ``False`` if no match was found
    (which we tolerate but log — see the partial-ledger discussion in the
    module docstring).
    """
    candidates: list[str]
    if option_type is None:
        candidates = ["put", "call"]
    else:
        candidates = [option_type]

    for candidate in candidates:
        for idx, leg in enumerate(open_legs):
            if (
                leg.option_type == candidate
                and leg.strike == strike
                and leg.expiration == expiration
            ):
                del open_legs[idx]
                return True

    logger.warning(
        "recompute_position_state: no matching open leg for %s on %s "
        "(strike=%s, expiration=%s); ledger may be incomplete",
        trade_type,
        ticker,
        strike,
        expiration,
    )
    return False


def recompute_position_state(
    db: Session, position_id: str, commit: bool = True
) -> Position | None:
    """Walk a position's trade ledger and derive its lifecycle state.

    Sorts trades by ``(opened_at, id)`` and replays them, tracking shares,
    broker_cost_basis, and the list of currently-open option legs. At the end:

    * ``status`` is ``"closed"`` if and only if shares == 0 and no open option
      legs remain. ``closed_at`` is set to the ``opened_at`` of the last trade
      that drove the position to a closed state (cleared again if it later
      reopens within the same Position — though "reopen-after-close" creates a
      new Position elsewhere, so this clearing path is mostly defensive).
    * ``shares`` and ``broker_cost_basis`` are recomputed from scratch.

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

    Returns:
        The refreshed Position ORM object, or None if no Position with that ID
        exists. Never raises on per-trade ledger inconsistencies (orphan close,
        missing leg) — those are logged as warnings so the recomputer keeps
        running across the rest of the journal.
    """
    position = db.query(Position).filter(Position.id == position_id).first()
    if position is None:
        return None

    trades: list[Trade] = sorted(
        position.trades,
        key=lambda t: (t.opened_at or "", t.id or ""),
    )

    shares = 0
    basis = 0.0
    open_legs: list[_LegKey] = []
    last_close_at: str | None = None

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
                    )
                )
            continue

        # Closing trade types: consume one matching open leg per contract.
        if ttype in _OPTION_CLOSE_TYPES:
            close_side = _option_type_for_close(ttype)
            for _ in range(qty):
                _consume_leg(
                    open_legs,
                    close_side,
                    float(trade.strike),
                    trade.expiration,
                    position.ticker,
                    ttype,
                )

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

    # Apply the derived state to the Position row.
    position.shares = shares
    position.broker_cost_basis = round(basis, 4)
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
