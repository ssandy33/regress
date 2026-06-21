"""Integration tests for journal service using a real DB session."""

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base
from app.models.schemas import (
    PositionCreate,
    PositionUpdate,
    TradeCreate,
    TradeUpdate,
)
from app.services.journal import (
    create_position,
    create_trade,
    delete_trade,
    get_position,
    get_positions,
    update_position,
    update_trade,
)


@pytest.fixture()
def db_session():
    """Provide an in-memory SQLite session for integration tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


def _create_sample_position(db_session, **overrides):
    """Helper to create a position with sensible defaults.

    ``strategy`` was dropped from PositionCreate in #131 — the recomputer
    derives the displayed label, and manual creates seed with "csp" until
    a trade is logged. Callers passing a ``strategy`` override are silently
    ignored by Pydantic (extras-allowed by default).
    """
    defaults = {
        "ticker": "AAPL",
        "shares": 100,
        "broker_cost_basis": 5000.0,
        "opened_at": "2025-01-15T10:00:00Z",
        "notes": None,
    }
    defaults.update(overrides)
    data = PositionCreate(**defaults)
    return create_position(db_session, data)


def _create_sample_trade(db_session, position_id, **overrides):
    """Helper to create a trade with sensible defaults."""
    defaults = {
        "position_id": position_id,
        "trade_type": "sell_put",
        "strike": 48.0,
        "expiration": "2025-02-21",
        "premium": 1.50,
        "fees": 0.65,
        "quantity": 1,
        "opened_at": "2025-01-15T10:00:00Z",
        "closed_at": None,
        "close_reason": None,
    }
    defaults.update(overrides)
    data = TradeCreate(**defaults)
    return create_trade(db_session, data)


# --- Position CRUD ---


@pytest.mark.unit
def test_create_position(db_session):
    result = _create_sample_position(db_session)
    assert result["ticker"] == "AAPL"
    assert result["shares"] == 100
    assert result["broker_cost_basis"] == 5000.0
    assert result["strategy"] == "csp"
    assert result["status"] == "open"
    assert result["opened_at"] == "2025-01-15T10:00:00Z"
    assert result["closed_at"] is None
    assert "id" in result
    assert len(result["id"]) == 36  # UUID4 format


@pytest.mark.unit
def test_get_positions_empty(db_session):
    result = get_positions(db_session)
    assert result == []


@pytest.mark.unit
def test_get_positions_after_create(db_session):
    _create_sample_position(db_session)
    result = get_positions(db_session)
    assert len(result) == 1
    assert result[0]["ticker"] == "AAPL"


@pytest.mark.unit
def test_get_positions_filter_by_status(db_session):
    _create_sample_position(db_session, ticker="AAPL")
    pos2 = _create_sample_position(db_session, ticker="MSFT")
    update_position(db_session, pos2["id"], PositionUpdate(status="closed"))

    open_positions = get_positions(db_session, status="open")
    assert len(open_positions) == 1
    assert open_positions[0]["ticker"] == "AAPL"

    closed_positions = get_positions(db_session, status="closed")
    assert len(closed_positions) == 1
    assert closed_positions[0]["ticker"] == "MSFT"


@pytest.mark.unit
def test_get_position_by_id(db_session):
    created = _create_sample_position(db_session)
    result = get_position(db_session, created["id"])
    assert result is not None
    assert result["id"] == created["id"]
    assert result["ticker"] == "AAPL"
    # Computed fields should be present
    assert "total_premiums" in result
    assert "adjusted_cost_basis" in result
    assert "min_compliant_cc_strike" in result


@pytest.mark.unit
def test_get_position_not_found(db_session):
    result = get_position(db_session, "nonexistent-id")
    assert result is None


@pytest.mark.unit
def test_update_position(db_session):
    created = _create_sample_position(db_session)
    updated = update_position(
        db_session,
        created["id"],
        PositionUpdate(notes="Updated note", broker_cost_basis=4800.0),
    )
    assert updated is not None
    assert updated["notes"] == "Updated note"
    assert updated["broker_cost_basis"] == 4800.0
    # Unchanged fields stay the same
    assert updated["ticker"] == "AAPL"


@pytest.mark.unit
def test_update_position_not_found(db_session):
    result = update_position(
        db_session, "nonexistent-id", PositionUpdate(notes="test")
    )
    assert result is None


# --- Trade CRUD ---


@pytest.mark.unit
def test_create_trade(db_session):
    position = _create_sample_position(db_session)
    trade = _create_sample_trade(db_session, position["id"])
    assert trade is not None
    assert trade["position_id"] == position["id"]
    assert trade["trade_type"] == "sell_put"
    assert trade["strike"] == 48.0
    assert trade["premium"] == 1.50
    assert trade["fees"] == 0.65
    assert trade["quantity"] == 1
    assert "id" in trade


@pytest.mark.unit
def test_create_trade_invalid_position(db_session):
    trade = _create_sample_trade(db_session, "nonexistent-position-id")
    assert trade is None


@pytest.mark.unit
def test_update_trade(db_session):
    position = _create_sample_position(db_session)
    trade = _create_sample_trade(db_session, position["id"])
    updated = update_trade(
        db_session,
        trade["id"],
        TradeUpdate(premium=2.00, close_reason="fifty_pct_target"),
    )
    assert updated is not None
    assert updated["premium"] == 2.00
    assert updated["close_reason"] == "fifty_pct_target"
    # Unchanged fields preserved
    assert updated["strike"] == 48.0


@pytest.mark.unit
def test_delete_trade(db_session):
    position = _create_sample_position(db_session)
    trade = _create_sample_trade(db_session, position["id"])
    assert delete_trade(db_session, trade["id"]) is True
    # Verify it's gone - position should have no trades
    pos = get_position(db_session, position["id"])
    assert len(pos["trades"]) == 0


@pytest.mark.unit
def test_delete_trade_not_found(db_session):
    assert delete_trade(db_session, "nonexistent-trade-id") is False


@pytest.mark.unit
def test_update_trade_not_found(db_session):
    result = update_trade(
        db_session, "nonexistent-trade-id", TradeUpdate(premium=2.00)
    )
    assert result is None


# --- Computed fields integration ---


@pytest.mark.unit
def test_adjusted_basis_with_premiums(db_session):
    """Create position + sell trades, verify computed adjusted_cost_basis."""
    position = _create_sample_position(db_session, broker_cost_basis=5000.0)
    _create_sample_trade(
        db_session, position["id"], premium=1.50, quantity=1
    )  # 150
    _create_sample_trade(
        db_session, position["id"], premium=2.00, quantity=1
    )  # 200
    result = get_position(db_session, position["id"])
    assert result["total_premiums"] == 350.0
    assert result["adjusted_cost_basis"] == 4650.0


@pytest.mark.unit
def test_adjusted_basis_mixed_trades(db_session):
    """Sell + buy-to-close trades should net correctly."""
    position = _create_sample_position(db_session, broker_cost_basis=5000.0)
    _create_sample_trade(
        db_session, position["id"], premium=2.00, quantity=1
    )  # +200
    _create_sample_trade(
        db_session,
        position["id"],
        trade_type="buy_put_close",
        premium=-0.50,
        quantity=1,
    )  # -50
    result = get_position(db_session, position["id"])
    assert result["total_premiums"] == 150.0
    assert result["adjusted_cost_basis"] == 4850.0


@pytest.mark.unit
def test_adjusted_basis_no_trades(db_session):
    """With no trades, adjusted_cost_basis equals broker_cost_basis."""
    position = _create_sample_position(db_session, broker_cost_basis=5000.0)
    result = get_position(db_session, position["id"])
    assert result["total_premiums"] == 0.0
    assert result["adjusted_cost_basis"] == 5000.0


@pytest.mark.unit
def test_adjusted_basis_excludes_assignment_consumed_premium(db_session):
    """Issue #183: total_premiums must not double-count the put netted into basis.

    Canonical wheel: Sell Put @ $13.50 premium $0.30 fees $0.66 → Assignment.
    After the recomputer runs, ``broker_cost_basis = 1320.66`` (already nets
    the $30 gross premium minus $0.66 fees). The journal read path's
    ``adjusted_cost_basis`` must NOT subtract the same $30 a second time —
    that would yield $1290.66 instead of the correct $1320.66.

    With no additional premium-earning trades on the position, the canonical
    AC is ``adjusted_cost_basis == broker_cost_basis == 1320.66``.
    """
    # Seed via the service layer so this test exercises the same code path
    # the API uses. broker_cost_basis is recomputed below.
    position = _create_sample_position(
        db_session,
        ticker="F",
        broker_cost_basis=0.0,
        opened_at="2026-03-01T10:00:00Z",
    )
    _create_sample_trade(
        db_session,
        position["id"],
        trade_type="sell_put",
        strike=13.50,
        expiration="2026-03-27",
        premium=0.30,
        fees=0.66,
        quantity=1,
        opened_at="2026-03-01T10:00:00Z",
    )
    _create_sample_trade(
        db_session,
        position["id"],
        trade_type="assignment",
        strike=13.50,
        expiration="2026-03-27",
        premium=0.0,
        fees=0.0,
        quantity=1,
        opened_at="2026-03-27T16:00:00Z",
    )

    # Drive the recomputer so broker_cost_basis lands at the netted value.
    from app.services.positions import recompute_position_state

    recompute_position_state(db_session, position["id"])

    result = get_position(db_session, position["id"])

    assert result["broker_cost_basis"] == pytest.approx(1320.66, abs=1e-4)
    # total_premiums reports gross premium collected (unchanged semantics).
    assert result["total_premiums"] == pytest.approx(30.0, abs=1e-4)
    # adjusted_cost_basis must exclude the netted put — equals basis exactly
    # when there are no other premium-earning trades.
    assert result["adjusted_cost_basis"] == pytest.approx(1320.66, abs=1e-4)


@pytest.mark.unit
def test_adjusted_basis_post_assignment_cc_subtracts_only_new_premium(db_session):
    """Issue #183 follow-on: a CC sold after assignment IS subtracted normally.

    Wheel mid-cycle: Sell Put → Assignment → Sell Call. The assignment-
    netted put premium stays inside ``broker_cost_basis``; the CC premium
    is real new income and shows up in ``adjusted_cost_basis``.

    Canonical F-case extended: basis = $1320.66, sell a $15 CC for $0.40
    → adjusted basis = 1320.66 - 40 = 1280.66.
    """
    position = _create_sample_position(
        db_session,
        ticker="F",
        broker_cost_basis=0.0,
        opened_at="2026-03-01T10:00:00Z",
    )
    _create_sample_trade(
        db_session,
        position["id"],
        trade_type="sell_put",
        strike=13.50,
        expiration="2026-03-27",
        premium=0.30,
        fees=0.66,
        opened_at="2026-03-01T10:00:00Z",
    )
    _create_sample_trade(
        db_session,
        position["id"],
        trade_type="assignment",
        strike=13.50,
        expiration="2026-03-27",
        premium=0.0,
        fees=0.0,
        opened_at="2026-03-27T16:00:00Z",
    )
    _create_sample_trade(
        db_session,
        position["id"],
        trade_type="sell_call",
        strike=15.0,
        expiration="2026-04-17",
        premium=0.40,
        fees=0.66,
        opened_at="2026-04-01T10:00:00Z",
    )

    from app.services.positions import recompute_position_state

    recompute_position_state(db_session, position["id"])

    result = get_position(db_session, position["id"])

    assert result["broker_cost_basis"] == pytest.approx(1320.66, abs=1e-4)
    # total_premiums sums every premium gross (30 from put + 40 from call).
    assert result["total_premiums"] == pytest.approx(70.0, abs=1e-4)
    # adjusted basis subtracts ONLY the new $40 (the put was already netted).
    assert result["adjusted_cost_basis"] == pytest.approx(1280.66, abs=1e-4)


@pytest.mark.unit
def test_min_compliant_cc_strike(db_session):
    """Verify 1.10x calculation on adjusted basis."""
    position = _create_sample_position(
        db_session, broker_cost_basis=5000.0, shares=100
    )
    _create_sample_trade(
        db_session, position["id"], premium=1.50, quantity=1
    )  # 150
    _create_sample_trade(
        db_session, position["id"], premium=2.00, quantity=1
    )  # 200
    result = get_position(db_session, position["id"])
    # adjusted = 5000 - 350 = 4650, min_cc = (4650/100) * 1.10 = 51.15
    assert result["min_compliant_cc_strike"] == 51.15


# --- Input validation ---


@pytest.mark.unit
def test_strategy_field_silently_ignored_on_create():
    """Issue #131: ``strategy`` is no longer a PositionCreate field.

    Pydantic v2 ignores unknown fields by default, so a payload that still
    includes ``strategy`` must build cleanly — proving the back-compat
    contract for stale clients.
    """
    pos = PositionCreate(
        ticker="AAPL",
        broker_cost_basis=5000.0,
        strategy="invalid",  # silently dropped — no longer a declared field
        opened_at="2025-01-15T10:00:00Z",
    )
    assert not hasattr(pos, "strategy")


@pytest.mark.unit
def test_invalid_trade_type_rejected():
    """Invalid trade_type value should be rejected by Pydantic."""
    with pytest.raises(ValidationError):
        TradeCreate(
            position_id="some-id",
            trade_type="invalid",
            strike=48.0,
            expiration="2025-02-21",
            premium=1.50,
            opened_at="2025-01-15T10:00:00Z",
        )


@pytest.mark.unit
def test_zero_shares_rejected():
    """shares=0 should be rejected by Pydantic validation."""
    with pytest.raises(ValidationError):
        PositionCreate(
            ticker="AAPL",
            shares=0,
            broker_cost_basis=5000.0,
            opened_at="2025-01-15T10:00:00Z",
        )


@pytest.mark.unit
def test_freetext_close_reason_accepted():
    """close_reason is free-text (issue #382), not the CLOSE_REASONS enum, so it
    can carry a Schwab dividend sub-type label (e.g. "Qualified Dividend") for
    future tax-bucket recovery. An arbitrary string validates."""
    trade = TradeCreate(
        position_id="some-id",
        trade_type="dividend",
        premium=0.0,
        unit_amount=42.0,
        quantity=0,
        opened_at="2025-01-15T10:00:00Z",
        close_reason="Qualified Dividend",
    )
    assert trade.close_reason == "Qualified Dividend"
