import logging
import uuid

from sqlalchemy.orm import Session, selectinload

from app.models.database import Position, Trade
from app.models.schemas import PositionCreate, PositionUpdate, TradeCreate, TradeUpdate

logger = logging.getLogger(__name__)


def compute_total_premiums(trades: list) -> float:
    """Sum of premium * quantity * 100 for all trades.

    Positive premiums = credits received (sell_put, sell_call).
    Negative premiums = debits paid (buy_put_close, buy_call_close).
    """
    return sum(t.premium * t.quantity * 100 for t in trades)


def compute_adjusted_basis(broker_cost_basis: float, total_premiums: float) -> float:
    """Adjusted cost basis = broker_cost_basis - total_premiums."""
    return broker_cost_basis - total_premiums


def compute_min_cc_strike(adjusted_basis: float, shares: int) -> float:
    """Minimum compliant covered-call strike = (adjusted_basis / shares) * 1.10.

    Rounded to 2 decimal places.
    """
    return round((adjusted_basis / shares) * 1.10, 2)


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
    """Build a PositionResponse dict from a Position ORM object."""
    trades = list(position.trades)
    total_premiums = compute_total_premiums(trades)
    adjusted_cost_basis = compute_adjusted_basis(position.broker_cost_basis, total_premiums)
    min_compliant_cc_strike = compute_min_cc_strike(adjusted_cost_basis, position.shares)

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
        "min_compliant_cc_strike": min_compliant_cc_strike,
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
    """Create a new Position."""
    position = Position(
        id=str(uuid.uuid4()),
        ticker=data.ticker,
        shares=data.shares,
        broker_cost_basis=data.broker_cost_basis,
        status="open",
        strategy=data.strategy,
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
    """Create a new trade. Returns None if position_id is invalid."""
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
