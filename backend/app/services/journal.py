import logging
import time
import uuid

from sqlalchemy.orm import Session, selectinload

from app.models.database import Position, Trade, TradeEntryCompliance
from app.models.schemas import PositionCreate, PositionUpdate, TradeCreate, TradeUpdate
from app.services.positions import compute_assignment_netting

logger = logging.getLogger(__name__)


def compute_total_premiums(trades: list) -> float:
    """Sum of premium * quantity * 100 for all trades.

    Positive premiums = credits received (sell_put, sell_call).
    Negative premiums = debits paid (buy_put_close, buy_call_close).
    """
    return sum(t.premium * t.quantity * 100 for t in trades)


def compute_adjusted_basis(broker_cost_basis: float, total_premiums: float) -> float:
    """Adjusted cost basis = ``broker_cost_basis - total_premiums``.

    After issue #183, ``broker_cost_basis`` already nets the originating
    short put's premium (minus prorated fees) for every assignment that
    matched a paired put. To avoid double-counting, callers must pass a
    ``total_premiums`` value that EXCLUDES the gross premium of those
    netted puts — :func:`_build_position_response` derives that value via
    :func:`app.services.positions.compute_assignment_netting`. The
    subtraction itself is unchanged; the wiring is what shifted.
    """
    return broker_cost_basis - total_premiums


def compute_min_cc_strike(adjusted_basis: float, shares: int) -> float:
    """Minimum compliant covered-call strike = (adjusted_basis / shares) * 1.10.

    Rounded to 2 decimal places.
    """
    if shares <= 0:
        logger.warning("compute_min_cc_strike called with shares=%d", shares)
        return 0.0
    return round((adjusted_basis / shares) * 1.10, 2)


def compute_per_share_basis(total: float, shares: int) -> float | None:
    """Per-share cost basis = ``round(total / shares, 4)`` (issue #320).

    Returns ``None`` when ``shares <= 0`` so the Positions table renders an
    em-dash instead of dividing by zero. Mirrors the covered-call /
    action-engine rounding convention (``covered_call.py:276``) so per-share
    basis has a single source of truth.
    """
    if shares <= 0:
        return None
    return round(total / shares, 4)


def compute_realized_equity_pl(trades: list) -> float:
    """Realized P&L from equity sells, derived (never stored) per ADR #391.

    Replays the position's trades in chronological order, maintaining a running
    ``(shares, basis)`` pair, and accumulates realized P&L for each matched
    ``sell_stock``::

        realized += (unit_amount - avg_basis_before) * shares_sold - fees

    where ``avg_basis_before = basis / shares`` measured immediately before the
    sell. ``buy_stock`` rows fold into the running weighted-average basis (fees
    capitalize). An unmatched sell (``shares_sold > shares``) is skipped — the
    same contract as :func:`app.services.positions.recompute_position_state`.
    Option trades contribute nothing; an options-only position returns ``0.0``.

    Args:
        trades: The position's trade rows (ORM objects or any object exposing
            ``trade_type``, ``quantity``, ``unit_amount``, ``fees``,
            ``opened_at``, ``id``). Sorting is applied internally.

    Returns:
        Total realized equity P&L in dollars.
    """
    ordered = sorted(
        trades, key=lambda t: (getattr(t, "opened_at", None) or "", getattr(t, "id", None) or "")
    )
    shares = 0
    basis = 0.0
    realized = 0.0
    for trade in ordered:
        ttype = trade.trade_type
        if ttype == "buy_stock":
            qty_shares = int(trade.quantity or 0)
            unit = float(trade.unit_amount or 0.0)
            fees = float(trade.fees or 0.0)
            shares += qty_shares
            basis += unit * qty_shares + fees
        elif ttype == "sell_stock":
            qty_shares = int(trade.quantity or 0)
            unit = float(trade.unit_amount or 0.0)
            fees = float(trade.fees or 0.0)
            if qty_shares > shares:
                # Unmatched sell — skipped (consistent with the recomputer).
                continue
            avg = basis / shares if shares > 0 else 0.0
            realized += (unit - avg) * qty_shares - fees
            basis -= avg * qty_shares
            shares -= qty_shares
    return realized


def compute_dividend_income(trades: list) -> float:
    """Total dividend income across ``dividend`` trades, derived per ADR #391.

    A dividend row stores the total payout in ``unit_amount`` (not per-share),
    so the income is a simple sum over ``dividend`` trades. Returns ``0.0`` when
    the position has no dividends.

    Args:
        trades: The position's trade rows.

    Returns:
        Total dividend income in dollars.
    """
    return sum(
        float(t.unit_amount or 0.0) for t in trades if t.trade_type == "dividend"
    )


def _build_trade_response(trade: Trade) -> dict:
    """Build a TradeResponse dict from a Trade ORM object."""
    return {
        "id": trade.id,
        "position_id": trade.position_id,
        "trade_type": trade.trade_type,
        "strike": trade.strike,
        "expiration": trade.expiration,
        "premium": trade.premium,
        "fees": trade.fees,
        "quantity": trade.quantity,
        "opened_at": trade.opened_at,
        "closed_at": trade.closed_at,
        "close_reason": trade.close_reason,
    }


def _build_position_response(position: Position) -> dict:
    """Build a PositionResponse dict from a Position ORM object.

    ``total_premiums`` reports the gross premium collected/paid across every
    trade on the position — that is the "money I have moved on this position
    via options" headline number the dashboard surfaces. ``adjusted_cost_basis``,
    however, must exclude any premium that the recomputer already netted into
    ``broker_cost_basis`` on assignment (issue #183) or it would double-count
    the put twice. We call :func:`compute_assignment_netting` to learn which
    sell_put trade_ids were consumed by assignments and subtract their gross
    premium dollars from the basis-input premium sum.
    """
    trades = list(position.trades)
    total_premiums = compute_total_premiums(trades)
    netted_by_trade_id = compute_assignment_netting(trades)
    netted_premium_total = sum(netted_by_trade_id.values())
    premiums_for_adjusted_basis = total_premiums - netted_premium_total
    adjusted_cost_basis = compute_adjusted_basis(
        position.broker_cost_basis, premiums_for_adjusted_basis
    )
    # Issue #278: caller-side guard avoids the noisy WARNING the function
    # emits for the legitimate ``shares=0`` short-circuit case (one closed
    # position would otherwise log once per dashboard load). The function's
    # own guard stays in place for accidental direct callers and for any
    # ``shares<0`` data-integrity surprise that still warrants a warning.
    # Guard short-circuits ONLY ``shares == 0`` so negative-shares (data
    # corruption) still reach :func:`compute_min_cc_strike` and trigger the
    # defensive WARNING — see test_build_position_response_warns_for_negative_shares.
    if position.shares == 0:
        min_compliant_cc_strike = 0.0
    else:
        min_compliant_cc_strike = compute_min_cc_strike(
            adjusted_cost_basis, position.shares
        )

    # Issue #320: per-share basis so the Positions table reads against the
    # per-share Current column / candidate strikes without head-math. Divide
    # total / shares and round to 4 decimals — identical to the covered-call /
    # action-engine convention (covered_call.py:276). Null when shares == 0 so
    # the display layer renders an em-dash instead of $0.00 / Infinity.
    broker_cost_basis_per_share = compute_per_share_basis(
        position.broker_cost_basis, position.shares
    )
    adjusted_cost_basis_per_share = compute_per_share_basis(
        adjusted_cost_basis, position.shares
    )

    return {
        "id": position.id,
        "ticker": position.ticker,
        "shares": position.shares,
        "broker_cost_basis": position.broker_cost_basis,
        "status": position.status,
        "strategy": position.strategy,
        "opened_at": position.opened_at,
        "closed_at": position.closed_at,
        "notes": position.notes,
        "total_premiums": total_premiums,
        "adjusted_cost_basis": adjusted_cost_basis,
        "broker_cost_basis_per_share": broker_cost_basis_per_share,
        "adjusted_cost_basis_per_share": adjusted_cost_basis_per_share,
        "min_compliant_cc_strike": min_compliant_cc_strike,
        # Equity P&L / dividend income — derived at read time, never stored
        # (ADR #391). Options-only positions return 0.0 for both (issue #386/#387).
        "realized_equity_pl": compute_realized_equity_pl(trades),
        "dividend_income": compute_dividend_income(trades),
        "trades": [_build_trade_response(t) for t in trades],
    }


def get_positions(db: Session, status: str | None = None) -> list[dict]:
    """Query positions, optionally filtered by status."""
    query = db.query(Position).options(selectinload(Position.trades))
    if status is not None:
        query = query.filter(Position.status == status)
    positions = query.all()
    return [_build_position_response(p) for p in positions]


def get_position(db: Session, position_id: str) -> dict | None:
    """Get a single position by ID. Returns None if not found."""
    position = db.query(Position).filter(Position.id == position_id).first()
    if position is None:
        return None
    return _build_position_response(position)


def create_position(db: Session, data: PositionCreate) -> dict:
    """Create a new Position.

    The ``strategy`` column is seeded with the placeholder ``"csp"``; the
    label is *derived* from each position's lifecycle state by
    ``recompute_position_state`` (issue #131). The placeholder is overwritten
    as soon as the first trade is logged and the recomputer runs — until
    then, manually-created positions display as "csp" by default.
    """
    position = Position(
        id=str(uuid.uuid4()),
        ticker=data.ticker,
        shares=data.shares,
        broker_cost_basis=data.broker_cost_basis,
        status="open",
        strategy="csp",
        opened_at=data.opened_at,
        notes=data.notes,
    )
    db.add(position)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(position)
    logger.info("Created position %s for %s", position.id, position.ticker)
    return _build_position_response(position)


def update_position(db: Session, position_id: str, data: PositionUpdate) -> dict | None:
    """Partial update of a position. Returns None if not found."""
    position = db.query(Position).filter(Position.id == position_id).first()
    if position is None:
        return None

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(position, field, value)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(position)
    logger.info("Updated position %s", position_id)
    return _build_position_response(position)


def create_trade(db: Session, data: TradeCreate) -> dict | None:
    """Create a new trade. Returns None if position_id is invalid.

    Side effect (issue #160 / Quality v1 Wave 3): for ``sell_put`` /
    ``sell_call`` trades, after the trade row is persisted, an entry-rule
    compliance row is written via
    :func:`app.services.entry_compliance.record_trade_compliance`. The
    optional ``dte_at_entry_hint`` / ``delta_at_entry_hint`` /
    ``earnings_buffer_days_hint`` fields on :class:`TradeCreate` propagate
    into the evaluator verbatim; Schwab-imported trades that never carry
    hints record with ``delta_unknown`` + ``earnings_buffer_unknown``.

    A compliance failure does not block trade creation — the trade row is
    already committed at that point, and the OKR engine (#157, deferred)
    consumes the compliance verdict downstream. Any persistence error in
    the compliance write is logged at WARNING and swallowed so the trade
    POST stays atomic from the caller's POV.
    """
    position = db.query(Position).filter(Position.id == data.position_id).first()
    if position is None:
        return None

    trade = Trade(
        id=str(uuid.uuid4()),
        position_id=data.position_id,
        trade_type=data.trade_type,
        strike=data.strike,
        expiration=data.expiration,
        premium=data.premium,
        unit_amount=data.unit_amount,
        fees=data.fees,
        quantity=data.quantity,
        opened_at=data.opened_at,
        closed_at=data.closed_at,
        close_reason=data.close_reason,
    )
    db.add(trade)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(trade)
    logger.info("Created trade %s for position %s", trade.id, trade.position_id)

    # Compliance side effect (issue #160). Imported lazily to avoid a circular
    # import at module load (entry_compliance imports schemas; schemas is the
    # consumer of this module's responses).
    if data.trade_type in {"sell_put", "sell_call"}:
        from app.services.entry_compliance import record_trade_compliance
        from app.services.rules_config import load_rules_config

        compliance_started = time.perf_counter()
        try:
            rules = load_rules_config(db)
            record_trade_compliance(
                db,
                trade,
                rules,
                dte_hint=data.dte_at_entry_hint,
                delta_hint=data.delta_at_entry_hint,
                earnings_buffer_hint=data.earnings_buffer_days_hint,
            )
        except Exception as e:
            # Compliance is best-effort; never block the trade POST on a
            # compliance write failure. Generic log message per CLAUDE.md
            # (no str(e) leak). ADR #292: ``.failed`` events carry both
            # ``outcome`` and ``duration_ms``; ``trade_id`` is non-canonical
            # so it travels in the message body, not ``extra``.
            duration_ms = int((time.perf_counter() - compliance_started) * 1000)
            logger.warning(
                "Failed to record trade_entry_compliance for trade %s",
                trade.id,
                extra={
                    "event": "trade_entry_compliance.failed",
                    "outcome": "failed",
                    "duration_ms": duration_ms,
                    "error_class": type(e).__name__,
                    "position_id": trade.position_id,
                },
            )
            db.rollback()

    return _build_trade_response(trade)


def update_trade(db: Session, trade_id: str, data: TradeUpdate) -> dict | None:
    """Partial update of a trade. Returns None if not found."""
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if trade is None:
        return None

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(trade, field, value)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(trade)
    logger.info("Updated trade %s", trade_id)
    return _build_trade_response(trade)


def delete_trade(db: Session, trade_id: str) -> bool:
    """Delete a trade. Returns False if not found."""
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if trade is None:
        return False

    db.delete(trade)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    logger.info("Deleted trade %s", trade_id)
    return True


def delete_position(db: Session, position_id: str) -> bool:
    """Delete a position and cascade-delete its trades.

    Relies on the ``Position.trades`` SQLAlchemy ``cascade="all, delete-orphan"``
    relationship declared on the model — a single ``db.delete(position)``
    removes the position and every child trade in the same transaction.
    Returns False if the position is not found.
    """
    position = db.query(Position).filter(Position.id == position_id).first()
    if position is None:
        return False

    db.delete(position)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    logger.info("Deleted position %s (cascade)", position_id)
    return True


def clear_all_journal_data(db: Session) -> dict:
    """Delete every position and trade in a single transaction.

    Captures the pre-delete row counts so the caller can report exactly how
    much was wiped. Trades are deleted explicitly first to avoid relying on
    the ORM cascade flushing per-position when the parent set is large.
    Returns ``{"deleted_positions": int, "deleted_trades": int}``.
    """
    trade_count = db.query(Trade).count()
    position_count = db.query(Position).count()

    try:
        # Issue #160: ``trade_entry_compliance`` is a child of trades — wipe it
        # FIRST so the bulk Trade delete below doesn't violate the FK (the SQL-
        # level ``ondelete=CASCADE`` only fires when ``PRAGMA foreign_keys=ON``
        # is set, which the project does not enable; bulk ORM deletes also
        # bypass the ``cascade="all, delete-orphan"`` relationship semantics).
        db.query(TradeEntryCompliance).delete(synchronize_session=False)
        db.query(Trade).delete(synchronize_session=False)
        db.query(Position).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        raise

    logger.info(
        "Cleared journal: %d positions, %d trades",
        position_count,
        trade_count,
    )
    return {
        "deleted_positions": position_count,
        "deleted_trades": trade_count,
    }
