"""Unit tests for ``app.services.positions.recompute_position_state``.

Each test seeds a Position with a hand-crafted Trade ledger, calls the
recomputer, and asserts the derived state matches the truth table in the
module docstring. The tests bypass the import pipeline entirely so a regression
in the recomputer is caught in isolation from the Schwab parsing/mapping code.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base, Position, Trade
from app.services.positions import (
    _apply_calendar_close,
    _derive_strategy_label,
    _LegKey,
    _reset_unpaired_warning_cache,
    recompute_position_state,
)


# Stable "today" used by tests that exercise the calendar fallback. Picked to
# be after every expiration date in the issue #134 reproduction journal so
# real past-expiration legs close, while leaving room for future-dated tests
# (e.g., 2026-08-15) to stay open.
_FROZEN_TODAY = date(2026, 5, 8)


def _frozen_clock(today: date = _FROZEN_TODAY):
    """Return a callable that always reports ``today`` as the current date."""
    return lambda: today


# --- Fixtures ----------------------------------------------------------------


@pytest.fixture()
def db_session():
    """In-memory SQLite session for isolated recomputer tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_trade(
    position_id: str,
    *,
    trade_type: str,
    strike: float,
    expiration: str,
    opened_at: str,
    quantity: int = 1,
    premium: float = 0.0,
    fees: float = 0.0,
) -> Trade:
    """Build a Trade ORM row with sensible defaults for the recomputer tests."""
    return Trade(
        id=str(uuid.uuid4()),
        position_id=position_id,
        trade_type=trade_type,
        strike=strike,
        expiration=expiration,
        premium=premium,
        fees=fees,
        quantity=quantity,
        opened_at=opened_at,
    )


def _seed_position(
    db,
    *,
    ticker: str,
    trades: Iterable[dict],
    initial_shares: int = 1,
    initial_basis: float = 0.0,
    status: str = "open",
) -> Position:
    """Create a Position + Trade ledger from a compact dict spec."""
    position = Position(
        id=str(uuid.uuid4()),
        ticker=ticker,
        shares=initial_shares,
        broker_cost_basis=initial_basis,
        status=status,
        strategy="wheel",
        opened_at="2026-01-01T00:00:00Z",
    )
    db.add(position)
    db.flush()
    for spec in trades:
        db.add(_make_trade(position.id, **spec))
    db.commit()
    db.refresh(position)
    return position


# --- Per-trade-type semantics ------------------------------------------------


class TestSingleTrades:
    """Recomputer applied to ledgers with a single trade type."""

    def test_sell_put_only_stays_open_zero_shares(self, db_session):
        pos = _seed_position(
            db_session,
            ticker="F",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                }
            ],
        )

        # Freeze clock before the leg's expiration so the calendar-fallback
        # added in #134 doesn't auto-close this still-live leg.
        result = recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 3, 1))
        )

        assert result is not None
        assert result.status == "open"
        assert result.shares == 0
        assert result.broker_cost_basis == 0.0
        assert result.closed_at is None

    def test_sell_call_only_stays_open(self, db_session):
        pos = _seed_position(
            db_session,
            ticker="AAPL",
            trades=[
                {
                    "trade_type": "sell_call",
                    "strike": 200.0,
                    "expiration": "2026-04-18",
                    "opened_at": "2026-03-01",
                }
            ],
        )

        result = recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 3, 1))
        )

        assert result.status == "open"
        assert result.shares == 0


# --- Lifecycle scenarios -----------------------------------------------------


class TestLifecycleScenarios:
    """End-to-end cycles a wheel trader actually walks through."""

    def test_sell_put_then_buy_to_close_closes_position(self, db_session):
        pos = _seed_position(
            db_session,
            ticker="F",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                },
                {
                    "trade_type": "buy_put_close",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-05",
                },
            ],
        )

        result = recompute_position_state(db_session, pos.id)

        assert result.status == "closed"
        assert result.shares == 0
        assert result.broker_cost_basis == 0.0
        assert result.closed_at == "2026-03-05"

    def test_sell_put_then_assignment_acquires_shares(self, db_session):
        pos = _seed_position(
            db_session,
            ticker="F",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-27",
                },
            ],
        )

        result = recompute_position_state(db_session, pos.id)

        assert result.status == "open"
        assert result.shares == 100
        assert result.broker_cost_basis == 1350.0

    def test_full_wheel_cycle_called_away(self, db_session):
        pos = _seed_position(
            db_session,
            ticker="MARA",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 20.0,
                    "expiration": "2026-02-20",
                    "opened_at": "2026-02-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 20.0,
                    "expiration": "2026-02-20",
                    "opened_at": "2026-02-20",
                },
                {
                    "trade_type": "sell_call",
                    "strike": 22.0,
                    "expiration": "2026-03-20",
                    "opened_at": "2026-02-25",
                },
                {
                    "trade_type": "called_away",
                    "strike": 22.0,
                    "expiration": "2026-03-20",
                    "opened_at": "2026-03-20",
                },
            ],
        )

        result = recompute_position_state(db_session, pos.id)

        assert result.status == "closed"
        assert result.shares == 0
        assert result.broker_cost_basis == 0.0
        assert result.closed_at == "2026-03-20"

    def test_sell_put_then_expired_closes_position(self, db_session):
        pos = _seed_position(
            db_session,
            ticker="HPE",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 18.0,
                    "expiration": "2026-04-17",
                    "opened_at": "2026-03-15",
                },
                {
                    "trade_type": "expired",
                    "strike": 18.0,
                    "expiration": "2026-04-17",
                    "opened_at": "2026-04-17",
                },
            ],
        )

        result = recompute_position_state(db_session, pos.id)

        assert result.status == "closed"
        assert result.shares == 0
        assert result.broker_cost_basis == 0.0
        assert result.closed_at == "2026-04-17"

    def test_double_assignment_aggregates_shares_and_basis(self, db_session):
        pos = _seed_position(
            db_session,
            ticker="SOFI",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 28.0,
                    "expiration": "2026-02-20",
                    "opened_at": "2026-02-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 28.0,
                    "expiration": "2026-02-20",
                    "opened_at": "2026-02-20",
                },
                {
                    "trade_type": "sell_put",
                    "strike": 30.0,
                    "expiration": "2026-03-20",
                    "opened_at": "2026-03-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 30.0,
                    "expiration": "2026-03-20",
                    "opened_at": "2026-03-20",
                },
            ],
        )

        result = recompute_position_state(db_session, pos.id)

        assert result.status == "open"
        assert result.shares == 200
        assert result.broker_cost_basis == pytest.approx(2800.0 + 3000.0)

    def test_two_open_legs_one_closed_position_stays_open(self, db_session):
        pos = _seed_position(
            db_session,
            ticker="AAPL",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 200.0,
                    "expiration": "2026-04-18",
                    "opened_at": "2026-03-15",
                },
                {
                    "trade_type": "sell_put",
                    "strike": 195.0,
                    "expiration": "2026-04-18",
                    "opened_at": "2026-03-16",
                },
                {
                    "trade_type": "buy_put_close",
                    "strike": 200.0,
                    "expiration": "2026-04-18",
                    "opened_at": "2026-03-17",
                },
            ],
        )

        # Frozen pre-expiration to keep the surviving 195P open after the
        # 200P is bought-to-close — calendar fallback would otherwise close
        # the still-live leg.
        result = recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 3, 18))
        )

        assert result.status == "open"
        assert result.shares == 0
        assert result.closed_at is None

    def test_covered_call_expires_keeps_shares(self, db_session):
        # Wheel mid-cycle: assigned 100 shares from a put, then sold a covered
        # call that expired worthless. Position must stay open with shares and
        # basis intact — closing this would silently delete shares the trader
        # still holds.
        pos = _seed_position(
            db_session,
            ticker="F",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-27",
                },
                # Now 100 shares held at $1350 basis.
                {
                    "trade_type": "sell_call",
                    "strike": 15.0,
                    "expiration": "2026-04-17",
                    "opened_at": "2026-04-01",
                },
                {
                    "trade_type": "expired",
                    "strike": 15.0,
                    "expiration": "2026-04-17",
                    "opened_at": "2026-04-17",
                },
            ],
        )

        result = recompute_position_state(db_session, pos.id)

        # Covered call expired worthless → shares and basis unchanged from
        # post-assignment state, position stays open, no closed_at stamp.
        assert result.status == "open"
        assert result.shares == 100
        assert result.broker_cost_basis == pytest.approx(1350.0)
        assert result.closed_at is None

    def test_partial_called_away_keeps_position_open(self, db_session):
        # 200 shares held (two assignments at $20), 1 call exercised at $22.
        # Expectation: 100 shares remain, basis halved, status stays open.
        pos = _seed_position(
            db_session,
            ticker="DVN",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 20.0,
                    "expiration": "2026-02-20",
                    "opened_at": "2026-02-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 20.0,
                    "expiration": "2026-02-20",
                    "opened_at": "2026-02-20",
                },
                {
                    "trade_type": "sell_put",
                    "strike": 20.0,
                    "expiration": "2026-03-20",
                    "opened_at": "2026-03-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 20.0,
                    "expiration": "2026-03-20",
                    "opened_at": "2026-03-20",
                },
                # Now 200 shares, basis $4000.
                {
                    "trade_type": "sell_call",
                    "strike": 22.0,
                    "expiration": "2026-04-17",
                    "opened_at": "2026-03-25",
                },
                {
                    "trade_type": "called_away",
                    "strike": 22.0,
                    "expiration": "2026-04-17",
                    "opened_at": "2026-04-17",
                },
            ],
        )

        result = recompute_position_state(db_session, pos.id)

        assert result.status == "open"
        assert result.shares == 100
        # Basis was $4000 across 200 shares; removing 100 shares proportionally
        # halves the basis to $2000.
        assert result.broker_cost_basis == pytest.approx(2000.0)


# --- Edge cases --------------------------------------------------------------


class TestEdgeCases:
    """Defensive behavior when the trade ledger is unusual or partially valid."""

    def test_returns_none_for_unknown_position_id(self, db_session):
        assert recompute_position_state(db_session, "nonexistent-id") is None

    def test_orphan_buy_to_close_does_not_raise(self, db_session, caplog):
        # Closing trade with no matching open leg; recomputer must not raise.
        pos = _seed_position(
            db_session,
            ticker="ZZZ",
            trades=[
                {
                    "trade_type": "buy_put_close",
                    "strike": 50.0,
                    "expiration": "2026-04-17",
                    "opened_at": "2026-04-01",
                },
            ],
        )

        result = recompute_position_state(db_session, pos.id)

        # No shares, no open legs → closed.
        assert result.status == "closed"
        assert result.shares == 0
        # Warning should have been logged.
        assert any(
            "no matching open leg" in record.getMessage()
            for record in caplog.records
        )

    def test_idempotent_two_runs_same_state(self, db_session):
        pos = _seed_position(
            db_session,
            ticker="F",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-27",
                },
            ],
        )

        first = recompute_position_state(db_session, pos.id)
        snapshot = (first.status, first.shares, first.broker_cost_basis, first.closed_at)
        second = recompute_position_state(db_session, pos.id)
        assert (second.status, second.shares, second.broker_cost_basis, second.closed_at) == snapshot

    def test_out_of_order_trades_sorted_by_opened_at(self, db_session):
        # Insert assignment first (chronologically later), then sell_put.
        pos = _seed_position(
            db_session,
            ticker="F",
            trades=[
                {
                    "trade_type": "assignment",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-27",
                },
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                },
            ],
        )

        result = recompute_position_state(db_session, pos.id)

        # Even with reversed insert order, chronological replay yields the
        # same final state as the in-order ledger.
        assert result.status == "open"
        assert result.shares == 100
        assert result.broker_cost_basis == 1350.0

    def test_dry_run_does_not_commit(self, db_session):
        pos = _seed_position(
            db_session,
            ticker="F",
            initial_shares=999,
            initial_basis=12345.67,
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-27",
                },
            ],
        )
        original_id = pos.id

        # commit=False: in-memory mutations only.
        result = recompute_position_state(db_session, original_id, commit=False)
        assert result.shares == 100
        assert result.broker_cost_basis == 1350.0

        # Roll back to discard the uncommitted mutations.
        db_session.rollback()
        reloaded = db_session.query(Position).filter(Position.id == original_id).first()
        assert reloaded.shares == 999
        assert reloaded.broker_cost_basis == 12345.67

    def test_quantity_two_assignment_acquires_two_lots(self, db_session):
        # A single assignment row with quantity=2 should acquire 200 shares
        # at strike, and consume 2 open put legs at the same strike/expiration.
        pos = _seed_position(
            db_session,
            ticker="F",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                    "quantity": 2,
                },
                {
                    "trade_type": "assignment",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-27",
                    "quantity": 2,
                },
            ],
        )

        result = recompute_position_state(db_session, pos.id)

        assert result.status == "open"
        assert result.shares == 200
        assert result.broker_cost_basis == pytest.approx(2700.0)


# --- Strategy label derivation (issue #131) ----------------------------------


class TestDeriveStrategyLabel:
    """Pure-function unit tests for ``_derive_strategy_label``.

    Each test maps one row of the issue #131 truth table to its expected
    label. The recomputer wraps this helper; the integration cases below
    confirm the wiring.
    """

    def _put_leg(self) -> _LegKey:
        return _LegKey(
            option_type="put",
            strike=20.0,
            expiration="2026-03-20",
            trade_id="test-leg-put",
        )

    def _call_leg(self) -> _LegKey:
        return _LegKey(
            option_type="call",
            strike=22.0,
            expiration="2026-03-20",
            trade_id="test-leg-call",
        )

    def test_zero_shares_only_open_puts_is_csp(self):
        assert _derive_strategy_label(0, [self._put_leg()]) == "csp"

    def test_shares_held_only_open_calls_is_cc(self):
        assert _derive_strategy_label(100, [self._call_leg()]) == "cc"

    def test_shares_held_open_puts_and_calls_is_wheel(self):
        assert (
            _derive_strategy_label(100, [self._put_leg(), self._call_leg()])
            == "wheel"
        )

    def test_shares_held_no_open_legs_is_holding(self):
        assert _derive_strategy_label(100, []) == "holding"

    def test_zero_shares_no_open_legs_is_csp(self):
        # The closed-position case: status is closed and the label is not
        # rendered on the dashboard, but the helper still returns a defined
        # label so callers can use it unconditionally.
        assert _derive_strategy_label(0, []) == "csp"

    def test_zero_shares_only_open_calls_is_cc_with_warning(self, caplog):
        # Anomalous (naked-call) case: derive ``cc`` and log a warning
        # because no shares + open calls should not occur in a wheel-only
        # journal. The label still matches the live legs — calling this
        # "csp" would directly contradict what the user is looking at.
        with caplog.at_level("WARNING", logger="app.services.positions"):
            label = _derive_strategy_label(0, [self._call_leg()])
        assert label == "cc"
        assert any(
            "anomalous" in record.getMessage()
            for record in caplog.records
        )

    def test_shares_held_only_open_puts_is_csp(self):
        # Layered-entry edge case: short put while holding shares (e.g.
        # selling a deeper put after assignment but before the next call).
        # csp is the closest single-side label.
        assert _derive_strategy_label(100, [self._put_leg()]) == "csp"


class TestRecomputeWritesDerivedStrategy:
    """Integration: ``recompute_position_state`` must persist the derived label."""

    def test_csp_flow_writes_csp_label(self, db_session):
        pos = _seed_position(
            db_session,
            ticker="F",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                }
            ],
        )

        # Frozen before expiration so the still-live put leg isn't swept by
        # the #134 calendar fallback.
        result = recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 3, 1))
        )

        assert result.shares == 0
        assert result.strategy == "csp"

    def test_holding_flow_writes_holding_label(self, db_session):
        # sell_put → assignment leaves 100 shares, no open legs → holding.
        pos = _seed_position(
            db_session,
            ticker="F",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-27",
                },
            ],
        )

        result = recompute_position_state(db_session, pos.id)

        assert result.shares == 100
        assert result.strategy == "holding"

    def test_cc_flow_writes_cc_label(self, db_session):
        # Hold shares + open call leg → cc.
        pos = _seed_position(
            db_session,
            ticker="F",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-27",
                },
                {
                    "trade_type": "sell_call",
                    "strike": 15.0,
                    "expiration": "2026-04-17",
                    "opened_at": "2026-04-01",
                },
            ],
        )

        # Freeze before the call's expiration so the still-live call leg
        # isn't swept by the #134 calendar fallback.
        result = recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 4, 5))
        )

        assert result.shares == 100
        assert result.strategy == "cc"

    def test_wheel_flow_writes_wheel_label(self, db_session):
        # Hold shares + open call AND open put → wheel.
        pos = _seed_position(
            db_session,
            ticker="F",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-27",
                },
                {
                    "trade_type": "sell_call",
                    "strike": 15.0,
                    "expiration": "2026-04-17",
                    "opened_at": "2026-04-01",
                },
                {
                    "trade_type": "sell_put",
                    "strike": 12.0,
                    "expiration": "2026-04-17",
                    "opened_at": "2026-04-02",
                },
            ],
        )

        result = recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 4, 5))
        )

        assert result.shares == 100
        assert result.strategy == "wheel"

    def test_closed_position_retains_last_derived_label(self, db_session):
        # Full round trip → shares back to 0, no open legs → status closed.
        # The label is whatever the helper says for ``(0, [])`` — currently
        # "csp" — and the row's status flag tells the dashboard not to
        # bucket it.
        pos = _seed_position(
            db_session,
            ticker="MARA",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 20.0,
                    "expiration": "2026-02-20",
                    "opened_at": "2026-02-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 20.0,
                    "expiration": "2026-02-20",
                    "opened_at": "2026-02-20",
                },
                {
                    "trade_type": "sell_call",
                    "strike": 22.0,
                    "expiration": "2026-03-20",
                    "opened_at": "2026-02-25",
                },
                {
                    "trade_type": "called_away",
                    "strike": 22.0,
                    "expiration": "2026-03-20",
                    "opened_at": "2026-03-20",
                },
            ],
        )

        result = recompute_position_state(db_session, pos.id)

        assert result.status == "closed"
        assert result.shares == 0
        assert result.strategy == "csp"

    def test_recompute_overwrites_stale_label(self, db_session):
        # Seeded with "wheel" but real ledger derives "holding". The
        # recomputer must overwrite the stale value — this is the user-
        # facing fix that ``make reconcile-positions`` relies on for
        # already-imported journals.
        pos = _seed_position(
            db_session,
            ticker="F",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-27",
                },
            ],
        )
        # Confirm seed had stale "wheel" label.
        assert pos.strategy == "wheel"

        result = recompute_position_state(db_session, pos.id)

        assert result.strategy == "holding"


# --- Issue #134: leg-pairing on resolution + calendar fallback ---------------


class TestLegPairingOnResolution:
    """ACs from issue #134: assignment / called_away / past-expiration close legs.

    The recomputer must close the originating short leg when a resolving
    trade arrives (strict match first, FIFO fallback for dirty data) and
    must close any past-expiration leg that has no resolving trade at all
    (calendar fallback).
    """

    def test_sell_put_assignment_closes_put_leg(self, db_session):
        # AC #1: After importing a wheel cycle ``sell_put → assignment`` the
        # originating ``sell_put`` leg is closed and does not appear in the
        # open-option-legs count.
        pos = _seed_position(
            db_session,
            ticker="F",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-27",
                },
            ],
        )

        result = recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 4, 1))
        )

        # Shares acquired, no open legs left, status open (still holding).
        assert result.shares == 100
        assert result.strategy == "holding"
        assert result.status == "open"
        # Issue #136: the consumed sell_put's Trade.closed_at must be stamped
        # so dashboard_legs.derive_open_legs drops it from the open-legs view.
        sell_put = _trade_by_type(pos, "sell_put")
        assert sell_put is not None
        assert sell_put.closed_at == "2026-03-27"

    def test_sell_call_called_away_closes_call_leg(self, db_session):
        # AC #2: After importing ``sell_call → called_away`` the originating
        # ``sell_call`` leg is closed.
        pos = _seed_position(
            db_session,
            ticker="MARA",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 20.0,
                    "expiration": "2026-02-20",
                    "opened_at": "2026-02-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 20.0,
                    "expiration": "2026-02-20",
                    "opened_at": "2026-02-20",
                },
                {
                    "trade_type": "sell_call",
                    "strike": 22.0,
                    "expiration": "2026-03-20",
                    "opened_at": "2026-02-25",
                },
                {
                    "trade_type": "called_away",
                    "strike": 22.0,
                    "expiration": "2026-03-20",
                    "opened_at": "2026-03-20",
                },
            ],
        )

        result = recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 4, 1))
        )

        # Full wheel cycle resolved: shares back to zero, no open legs,
        # status closed.
        assert result.status == "closed"
        assert result.shares == 0

    def test_sell_put_past_expiration_no_close_trade_closes_calendar(
        self, db_session
    ):
        # AC #3: An option leg whose ``expiration < today`` and has no
        # closing trade is treated as expired worthless and closed by the
        # recomputer.
        pos = _seed_position(
            db_session,
            ticker="SOFI",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 26.0,
                    "expiration": "2025-09-26",
                    "opened_at": "2025-08-01",
                }
            ],
        )

        result = recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 5, 8))
        )

        # Past expiration, no resolving trade → closed via calendar
        # fallback. closed_at is the leg's expiration (no real trade
        # opened_at exists to use).
        assert result.status == "closed"
        assert result.shares == 0
        assert result.broker_cost_basis == 0.0
        assert result.closed_at == "2025-09-26"
        # Issue #136: the consumed sell_put's Trade.closed_at must also be
        # stamped (with the leg's expiration) so the dashboard's open-legs
        # view drops the calendar-closed leg.
        sell_put = _trade_by_type(pos, "sell_put")
        assert sell_put is not None
        assert sell_put.closed_at == "2025-09-26"

    def test_sell_call_past_expiration_no_close_trade_closes_calendar(
        self, db_session
    ):
        # AC #3 (call side): same calendar fallback for an OTM short call
        # whose Expired row never landed in the CSV.
        pos = _seed_position(
            db_session,
            ticker="SOFI",
            trades=[
                {
                    "trade_type": "sell_call",
                    "strike": 31.0,
                    "expiration": "2025-12-19",
                    "opened_at": "2025-11-01",
                }
            ],
        )

        result = recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 5, 8))
        )

        assert result.status == "closed"
        assert result.shares == 0
        assert result.closed_at == "2025-12-19"

    def test_three_stacked_assignments_aggregate_to_300_shares(self, db_session):
        # AC #5: Multiple stacked assignments (the user's reported SOFI case)
        # all close their puts and shares accumulate to 300.
        pos = _seed_position(
            db_session,
            ticker="SOFI",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 26.0,
                    "expiration": "2025-09-26",
                    "opened_at": "2025-08-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 26.0,
                    "expiration": "2025-09-26",
                    "opened_at": "2025-09-26",
                },
                {
                    "trade_type": "sell_put",
                    "strike": 27.5,
                    "expiration": "2025-10-10",
                    "opened_at": "2025-09-15",
                },
                {
                    "trade_type": "assignment",
                    "strike": 27.5,
                    "expiration": "2025-10-10",
                    "opened_at": "2025-10-10",
                },
                {
                    "trade_type": "sell_put",
                    "strike": 30.0,
                    "expiration": "2025-11-21",
                    "opened_at": "2025-10-20",
                },
                {
                    "trade_type": "assignment",
                    "strike": 30.0,
                    "expiration": "2025-11-21",
                    "opened_at": "2025-11-21",
                },
            ],
        )

        result = recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 5, 8))
        )

        # All three assignments resolved their originating puts; shares
        # stack to 300; basis sums each strike * 100; no open legs remain;
        # label flips to "holding".
        assert result.status == "open"
        assert result.shares == 300
        assert result.broker_cost_basis == pytest.approx(
            26.0 * 100 + 27.5 * 100 + 30.0 * 100
        )
        assert result.strategy == "holding"

    def test_future_expiration_no_close_trade_stays_open(self, db_session):
        # AC #4: Open legs whose expiration is today or later with no
        # closing trade must remain open — calendar fallback must not
        # close future-dated legs.
        pos = _seed_position(
            db_session,
            ticker="SOFI",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 28.0,
                    "expiration": "2026-08-15",
                    "opened_at": "2026-04-01",
                }
            ],
        )

        result = recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 5, 8))
        )

        # Future-dated leg with no close: stays open.
        assert result.status == "open"
        assert result.shares == 0
        assert result.strategy == "csp"
        assert result.closed_at is None


class TestFifoFallbackForDirtyData:
    """Strict-then-FIFO pairing covers Schwab CSV rows whose strike or
    expiration drifts slightly from the originating short leg."""

    def test_assignment_with_mismatched_strike_closes_via_fifo(self, db_session):
        # Resolving ``assignment`` strike differs from the open ``sell_put``
        # by a penny. Strict match fails; FIFO fallback consumes the only
        # open put leg.
        pos = _seed_position(
            db_session,
            ticker="F",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 13.49,  # <-- penny drift, no strict match
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-27",
                },
            ],
        )

        result = recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 4, 1))
        )

        # FIFO fallback closed the leg; shares acquired at the
        # assignment row's strike (13.49 * 100).
        assert result.status == "open"
        assert result.shares == 100
        assert result.broker_cost_basis == pytest.approx(1349.0)
        assert result.strategy == "holding"

    def test_called_away_with_mismatched_strike_closes_via_fifo(self, db_session):
        pos = _seed_position(
            db_session,
            ticker="MARA",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 20.0,
                    "expiration": "2026-02-20",
                    "opened_at": "2026-02-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 20.0,
                    "expiration": "2026-02-20",
                    "opened_at": "2026-02-20",
                },
                {
                    "trade_type": "sell_call",
                    "strike": 22.0,
                    "expiration": "2026-03-20",
                    "opened_at": "2026-02-25",
                },
                {
                    "trade_type": "called_away",
                    "strike": 21.99,  # <-- penny drift
                    "expiration": "2026-03-20",
                    "opened_at": "2026-03-20",
                },
            ],
        )

        result = recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 4, 1))
        )

        # FIFO fallback closed the call leg; full wheel cycle resolved.
        assert result.status == "closed"
        assert result.shares == 0


class TestUnpairedResolvingEvent:
    """When both strict and FIFO passes fail, log a warning and continue."""

    def setup_method(self) -> None:
        # Module-level dedupe cache must start empty so each test gets the
        # genuine first-warning behavior regardless of test order.
        _reset_unpaired_warning_cache()

    def test_assignment_with_no_matching_put_leg_warns_but_no_error(
        self, db_session, caplog
    ):
        # Bare ``assignment`` row with no preceding ``sell_put`` — neither
        # the strict pass nor the FIFO pass can find a matching leg. The
        # recomputer must log a warning and apply the shares/basis side
        # effects; it must not raise.
        pos = _seed_position(
            db_session,
            ticker="ZZZ",
            trades=[
                {
                    "trade_type": "assignment",
                    "strike": 50.0,
                    "expiration": "2026-04-17",
                    "opened_at": "2026-04-17",
                }
            ],
        )

        with caplog.at_level("WARNING", logger="app.services.positions"):
            result = recompute_position_state(
                db_session, pos.id, clock=_frozen_clock(date(2026, 5, 8))
            )

        # Warning surfaced the data-integrity gap; shares still updated.
        assert any(
            "no matching open leg" in record.getMessage()
            for record in caplog.records
        )
        assert result.shares == 100
        assert result.broker_cost_basis == pytest.approx(5000.0)

    def test_repeat_recompute_does_not_re_emit_warning(
        self, db_session, caplog
    ):
        # The recomputer is idempotent and is called both after every Schwab
        # import and from the reconcile_positions script (which a user may run
        # repeatedly). The first encounter of an unpaired resolving event is
        # genuine signal; subsequent recomputes of the same trade should not
        # spam the same WARNING. Confirm the second run drops to INFO so log
        # consumers (and tests asserting on WARNING records) stay clean.
        pos = _seed_position(
            db_session,
            ticker="REPEAT",
            trades=[
                {
                    "trade_type": "assignment",
                    "strike": 50.0,
                    "expiration": "2026-04-17",
                    "opened_at": "2026-04-17",
                }
            ],
        )

        # First recompute: genuine WARNING.
        with caplog.at_level("INFO", logger="app.services.positions"):
            recompute_position_state(
                db_session, pos.id, clock=_frozen_clock(date(2026, 5, 8))
            )
        first_warnings = [
            r
            for r in caplog.records
            if r.levelname == "WARNING"
            and "no matching open leg" in r.getMessage()
        ]
        assert len(first_warnings) == 1

        # Second recompute on the exact same ledger: no new WARNING; the
        # repeat is demoted to INFO so the data-integrity gap stays visible
        # without flooding the log.
        caplog.clear()
        with caplog.at_level("INFO", logger="app.services.positions"):
            recompute_position_state(
                db_session, pos.id, clock=_frozen_clock(date(2026, 5, 8))
            )
        repeat_warnings = [
            r
            for r in caplog.records
            if r.levelname == "WARNING"
            and "no matching open leg" in r.getMessage()
        ]
        repeat_infos = [
            r
            for r in caplog.records
            if r.levelname == "INFO"
            and "no matching open leg" in r.getMessage()
        ]
        assert repeat_warnings == []
        assert len(repeat_infos) == 1


class TestCalendarCloseHelper:
    """Pure-function unit tests for ``_apply_calendar_close``."""

    def test_empty_open_legs_returns_empty_and_none(self):
        still, latest, consumed = _apply_calendar_close(
            [], "F", date(2026, 5, 8)
        )
        assert still == []
        assert latest is None
        assert consumed == []

    def test_all_future_legs_unchanged(self):
        legs = [
            _LegKey(
                option_type="put",
                strike=20.0,
                expiration="2026-08-15",
                trade_id="leg-a",
            ),
            _LegKey(
                option_type="call",
                strike=22.0,
                expiration="2026-09-19",
                trade_id="leg-b",
            ),
        ]
        still, latest, consumed = _apply_calendar_close(
            legs, "F", date(2026, 5, 8)
        )
        assert still == legs
        assert latest is None
        assert consumed == []

    def test_mix_of_past_and_future_legs(self):
        past = _LegKey(
            option_type="put",
            strike=26.0,
            expiration="2025-09-26",
            trade_id="leg-past",
        )
        future = _LegKey(
            option_type="call",
            strike=22.0,
            expiration="2026-09-19",
            trade_id="leg-future",
        )
        still, latest, consumed = _apply_calendar_close(
            [past, future], "SOFI", date(2026, 5, 8)
        )
        assert still == [future]
        assert latest == "2025-09-26"
        # Consumed list surfaces the swept legs so the caller can stamp
        # Trade.closed_at on the originating rows (issue #136).
        assert consumed == [past]

    def test_multiple_past_legs_returns_latest_expiration(self):
        leg_a = _LegKey(
            option_type="put",
            strike=20.0,
            expiration="2025-09-26",
            trade_id="leg-a",
        )
        leg_b = _LegKey(
            option_type="put",
            strike=22.0,
            expiration="2025-12-19",
            trade_id="leg-b",
        )
        leg_c = _LegKey(
            option_type="call",
            strike=30.0,
            expiration="2025-11-07",
            trade_id="leg-c",
        )
        still, latest, consumed = _apply_calendar_close(
            [leg_a, leg_b, leg_c], "SOFI", date(2026, 5, 8)
        )
        assert still == []
        # Latest among the three closed legs is 2025-12-19.
        assert latest == "2025-12-19"
        # All three legs swept; order matches input iteration order so
        # callers can correlate consumed legs back to opening trades.
        assert consumed == [leg_a, leg_b, leg_c]

    def test_unparseable_expiration_leaves_leg_alone(self):
        # Defensive: a malformed expiration string shouldn't trigger
        # calendar close (we can't prove it's past expiration).
        leg = _LegKey(
            option_type="put",
            strike=20.0,
            expiration="not-a-date",
            trade_id="leg-bad-date",
        )
        still, latest, consumed = _apply_calendar_close(
            [leg], "F", date(2026, 5, 8)
        )
        assert still == [leg]
        assert latest is None
        assert consumed == []


class TestCalendarCloseRegressionGuard:
    """Calendar fallback must not regress the covered-call-with-shares case
    introduced in PR #130 (``test_covered_call_expires_keeps_shares``)."""

    def test_calendar_close_does_not_regress_covered_call_with_shares(
        self, db_session
    ):
        # Same flow as ``test_covered_call_expires_keeps_shares`` but with
        # NO explicit "expired" row and the clock frozen *after* the call's
        # expiration. The calendar fallback should close the call leg, but
        # shares and basis must stay intact and the position must remain
        # open with the "holding" label.
        pos = _seed_position(
            db_session,
            ticker="F",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-27",
                },
                # Now 100 shares held at $1350 basis.
                {
                    "trade_type": "sell_call",
                    "strike": 15.0,
                    "expiration": "2026-04-17",
                    "opened_at": "2026-04-01",
                },
                # No "expired" row for the call — calendar fallback closes.
            ],
        )

        result = recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 5, 8))
        )

        assert result.status == "open"
        assert result.shares == 100
        assert result.broker_cost_basis == pytest.approx(1350.0)
        assert result.strategy == "holding"
        assert result.closed_at is None


# --- Issue #136: persist Trade.closed_at on consumed legs --------------------


def _trade_by_type(position: Position, trade_type: str) -> Trade | None:
    """Return the first Trade with the given ``trade_type`` on this Position.

    Helper for the issue #136 tests, which need to reach back from a recompute
    result to the originating opening row to assert ``closed_at`` was stamped.
    Tests in this module each seed a unique trade per ``trade_type`` so the
    "first match" semantics are sufficient.
    """
    for trade in position.trades:
        if trade.trade_type == trade_type:
            return trade
    return None


class TestPersistsTradeClosedAt:
    """Issue #136: ``recompute_position_state`` must stamp ``Trade.closed_at``
    on the originating opening row whenever the lifecycle finalizer consumes
    its leg.

    Without this stamping, ``dashboard_legs.derive_open_legs`` (which filters
    on ``Trade.closed_at IS NULL``) shows zombie legs for every leg the
    recomputer has already paired up. These tests assert directly on the
    persisted ``Trade.closed_at`` column rather than on in-memory state so a
    regression in the write-back loop is caught here.
    """

    def test_assignment_stamps_closed_at_on_consumed_put(self, db_session):
        # AC #1 (strict-match path): ``sell_put → assignment`` stamps the
        # consumed sell_put's closed_at to the assignment's opened_at.
        pos = _seed_position(
            db_session,
            ticker="F",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-27",
                },
            ],
        )

        recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 4, 1))
        )

        sell_put = _trade_by_type(pos, "sell_put")
        assert sell_put is not None
        # closed_at == resolving trade's opened_at (the assignment's date).
        assert sell_put.closed_at == "2026-03-27"

    def test_called_away_stamps_closed_at_on_consumed_call(self, db_session):
        # AC #1 (call side): ``sell_call → called_away`` stamps the consumed
        # sell_call's closed_at to the called_away's opened_at.
        pos = _seed_position(
            db_session,
            ticker="MARA",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 20.0,
                    "expiration": "2026-02-20",
                    "opened_at": "2026-02-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 20.0,
                    "expiration": "2026-02-20",
                    "opened_at": "2026-02-20",
                },
                {
                    "trade_type": "sell_call",
                    "strike": 22.0,
                    "expiration": "2026-03-20",
                    "opened_at": "2026-02-25",
                },
                {
                    "trade_type": "called_away",
                    "strike": 22.0,
                    "expiration": "2026-03-20",
                    "opened_at": "2026-03-20",
                },
            ],
        )

        recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 4, 1))
        )

        sell_call = _trade_by_type(pos, "sell_call")
        sell_put = _trade_by_type(pos, "sell_put")
        assert sell_call is not None
        assert sell_put is not None
        # Each consumed leg gets the resolving trade's opened_at.
        assert sell_call.closed_at == "2026-03-20"
        assert sell_put.closed_at == "2026-02-20"

    def test_buy_to_close_stamps_closed_at_on_consumed_leg(self, db_session):
        # AC #1 (BTC variant): a ``sell_put → buy_put_close`` cycle stamps
        # the sell_put's closed_at to the buy_put_close's opened_at.
        pos = _seed_position(
            db_session,
            ticker="F",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                },
                {
                    "trade_type": "buy_put_close",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-05",
                },
            ],
        )

        recompute_position_state(db_session, pos.id)

        sell_put = _trade_by_type(pos, "sell_put")
        assert sell_put is not None
        assert sell_put.closed_at == "2026-03-05"

    def test_fifo_fallback_stamps_closed_at_on_consumed_leg(self, db_session):
        # AC #2: penny-drift assignment matches via FIFO fallback. The
        # consumed sell_put still gets ``closed_at`` stamped to the
        # assignment's opened_at, even though strict (strike, expiration)
        # match failed.
        pos = _seed_position(
            db_session,
            ticker="F",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 13.49,  # penny drift; strict match fails
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-27",
                },
            ],
        )

        recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 4, 1))
        )

        sell_put = _trade_by_type(pos, "sell_put")
        assert sell_put is not None
        assert sell_put.closed_at == "2026-03-27"

    def test_calendar_close_stamps_closed_at_with_expiration(self, db_session):
        # AC #3: calendar-fallback close stamps the leg's expiration on the
        # consumed Trade (no real resolving trade exists to supply opened_at).
        pos = _seed_position(
            db_session,
            ticker="SOFI",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 26.0,
                    "expiration": "2025-09-26",
                    "opened_at": "2025-08-01",
                }
            ],
        )

        recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 5, 8))
        )

        sell_put = _trade_by_type(pos, "sell_put")
        assert sell_put is not None
        # No resolving trade — the leg's expiration is the canonical close.
        assert sell_put.closed_at == "2025-09-26"

    def test_recompute_idempotent_preserves_trade_closed_at(self, db_session):
        # AC #5: a second recompute on the same ledger does NOT shift the
        # ``closed_at`` value already written on consumed legs. Locks the
        # idempotency contract called out in the issue plan: the recomputer
        # rebuilds open_legs from scratch each call, so a second run produces
        # the same consumption decisions and writes the same value.
        pos = _seed_position(
            db_session,
            ticker="F",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-27",
                },
            ],
        )

        recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 4, 1))
        )
        sell_put = _trade_by_type(pos, "sell_put")
        assert sell_put is not None
        first_close = sell_put.closed_at
        assert first_close == "2026-03-27"

        # Second pass — same ledger, same clock, must produce identical writes.
        recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 4, 1))
        )
        db_session.refresh(sell_put)
        assert sell_put.closed_at == first_close

    def test_existing_closed_at_not_overwritten_by_calendar_close(
        self, db_session
    ):
        # Defensive guard: a Trade with a pre-existing ``closed_at`` value is
        # never overwritten by the calendar-close pass. Real-resolution dates
        # outrank synthetic-expiration dates per the issue plan's Q6b rule.
        pos = _seed_position(
            db_session,
            ticker="SOFI",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 26.0,
                    "expiration": "2025-09-26",
                    "opened_at": "2025-08-01",
                }
            ],
        )

        # Manually pre-stamp closed_at as if a previous reconcile had already
        # written a real resolution date for this leg.
        sell_put = _trade_by_type(pos, "sell_put")
        assert sell_put is not None
        sell_put.closed_at = "2025-09-15"  # earlier than expiration
        db_session.commit()

        # Run recompute with a clock past the leg's expiration so the
        # calendar fallback would otherwise overwrite the stamp.
        recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 5, 8))
        )

        db_session.refresh(sell_put)
        assert sell_put.closed_at == "2025-09-15"

    def test_orphan_assignment_does_not_stamp_anything(self, db_session):
        # When both strict and FIFO passes fail (no matching open leg), no
        # Trade should receive a phantom ``closed_at`` stamp — the orphan
        # resolving trade itself stays open (it never opened a leg).
        _reset_unpaired_warning_cache()
        pos = _seed_position(
            db_session,
            ticker="ZZZ",
            trades=[
                {
                    "trade_type": "assignment",
                    "strike": 50.0,
                    "expiration": "2026-04-17",
                    "opened_at": "2026-04-17",
                }
            ],
        )

        recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 5, 8))
        )

        assignment = _trade_by_type(pos, "assignment")
        assert assignment is not None
        assert assignment.closed_at is None

    def test_holding_label_yields_empty_open_legs_via_derive_open_legs(
        self, db_session
    ):
        # AC #3: a position whose strategy label is "holding" must have an
        # empty open-legs view. This crosses the two services that issue #136
        # is reconciling — recompute_position_state writes Trade.closed_at,
        # and derive_open_legs filters on it. Without the persistence fix,
        # derive_open_legs returns the consumed sell_put as a zombie leg.
        from app.services.dashboard_legs import derive_open_legs

        pos = _seed_position(
            db_session,
            ticker="F",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                },
                {
                    "trade_type": "assignment",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-27",
                },
            ],
        )

        result = recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 4, 1))
        )
        assert result.strategy == "holding"

        # Build the dict shape derive_open_legs expects from the persisted
        # Trade rows. ``closed_at`` is read straight off the column, so this
        # test reflects exactly what the dashboard endpoint observes.
        position_dict = {
            "id": pos.id,
            "ticker": pos.ticker,
            "trades": [
                {
                    "id": t.id,
                    "trade_type": t.trade_type,
                    "strike": t.strike,
                    "expiration": t.expiration,
                    "closed_at": t.closed_at,
                }
                for t in pos.trades
            ],
        }
        legs = derive_open_legs(
            [position_dict],
            quotes_by_ticker={"F": 13.0},
            today=date(2026, 4, 1),
        )
        # Holding-labeled position must surface zero open legs.
        assert legs == []

    def test_buy_to_close_stamp_outranks_calendar_fallback(self, db_session):
        # When a real ``buy_put_close`` resolves the leg, that resolution
        # stamp must win — even when the recompute runs after the leg's
        # expiration date (which would otherwise trigger calendar close).
        pos = _seed_position(
            db_session,
            ticker="F",
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                },
                {
                    "trade_type": "buy_put_close",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-05",
                },
            ],
        )

        # Clock well past the expiration; the leg has already been consumed
        # by the buy_to_close so the calendar-fallback pass should be a no-op.
        recompute_position_state(
            db_session, pos.id, clock=_frozen_clock(date(2026, 5, 8))
        )

        sell_put = _trade_by_type(pos, "sell_put")
        assert sell_put is not None
        # Real resolving date wins, not the synthetic expiration.
        assert sell_put.closed_at == "2026-03-05"
