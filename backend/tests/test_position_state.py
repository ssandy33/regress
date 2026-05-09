"""Unit tests for ``app.services.positions.recompute_position_state``.

Each test seeds a Position with a hand-crafted Trade ledger, calls the
recomputer, and asserts the derived state matches the truth table in the
module docstring. The tests bypass the import pipeline entirely so a regression
in the recomputer is caught in isolation from the Schwab parsing/mapping code.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base, Position, Trade
from app.services.positions import _derive_strategy_label, _LegKey, recompute_position_state


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

        result = recompute_position_state(db_session, pos.id)

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

        result = recompute_position_state(db_session, pos.id)

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

        result = recompute_position_state(db_session, pos.id)

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
        return _LegKey(option_type="put", strike=20.0, expiration="2026-03-20")

    def _call_leg(self) -> _LegKey:
        return _LegKey(option_type="call", strike=22.0, expiration="2026-03-20")

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

        result = recompute_position_state(db_session, pos.id)

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

        result = recompute_position_state(db_session, pos.id)

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

        result = recompute_position_state(db_session, pos.id)

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
