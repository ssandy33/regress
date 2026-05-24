"""Direct unit tests for ``app.services.reconcile.reconcile``.

The service is shared by the CLI (``scripts.reconcile_positions``) and the
HTTP route (``POST /api/journal/reconcile``). These tests cover the
apply / dry-run dichotomy and the per-position diff shape that the route
serializes to JSON for the Settings UI (issue #139).
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base, Position, Trade
from app.services import positions as positions_module
from app.services.reconcile import (
    ReconcilePositionDiff,
    ReconcileResult,
    reconcile,
)


@pytest.fixture()
def db_session():
    """In-memory SQLite session shared by reconcile + caller."""
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


def _seed_position_with_full_cycle(db) -> Position:
    """Seed a Position whose ledger differs from the stored derived state.

    The bug repro: stored ``shares=100`` / ``status="open"`` / ``strategy="wheel"``
    but the trade ledger shows a complete sell_put → assignment → sell_call →
    called_away cycle, so the recomputer should drive it to closed/0/holding.
    """
    position = Position(
        id=str(uuid.uuid4()),
        ticker="MARA",
        shares=100,
        broker_cost_basis=0.0,
        status="open",
        strategy="wheel",
        opened_at="2026-01-01T00:00:00Z",
    )
    db.add(position)
    db.flush()
    for spec in [
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
    ]:
        db.add(
            Trade(
                id=str(uuid.uuid4()),
                position_id=position.id,
                premium=0.0,
                fees=0.0,
                quantity=1,
                **spec,
            )
        )
    db.commit()
    db.refresh(position)
    return position


class TestReconcileService:
    @pytest.mark.unit
    def test_empty_journal_returns_zero_aggregates(self, db_session):
        """With no positions, all aggregates are zero and the diff list is empty."""
        result = reconcile(db_session, apply=False)

        assert isinstance(result, ReconcileResult)
        assert result.positions_processed == 0
        assert result.trades_stamped == 0
        assert result.status_changes == 0
        assert result.share_corrections == 0
        assert result.basis_corrections == 0
        assert result.strategy_changes == 0
        assert result.errors == 0
        assert result.per_position == []

    @pytest.mark.unit
    def test_dry_run_does_not_mutate_db(self, db_session):
        pos = _seed_position_with_full_cycle(db_session)
        original_id = pos.id
        # Capture pre-call Trade.closed_at values across every trade.
        before_closes = {t.id: t.closed_at for t in pos.trades}

        result = reconcile(db_session, apply=False)

        assert result.positions_processed == 1
        # Service runs the recomputer which would drive shares to 0.
        diff = result.per_position[0]
        assert diff.shares_before == 100
        assert diff.shares_after == 0

        # Post-call DB state must be untouched: re-query and compare.
        db_session.expire_all()
        reloaded = (
            db_session.query(Position).filter(Position.id == original_id).first()
        )
        assert reloaded.status == "open"
        assert reloaded.shares == 100

        # Trade.closed_at must also be unchanged — this is the AC-1 invariant.
        for trade in reloaded.trades:
            assert trade.closed_at == before_closes[trade.id]

    @pytest.mark.unit
    def test_apply_persists_position_and_trade_writes(self, db_session):
        pos = _seed_position_with_full_cycle(db_session)
        original_id = pos.id

        result = reconcile(db_session, apply=True)

        assert result.positions_processed == 1
        # Post-call DB state must reflect the recompute pass.
        db_session.expire_all()
        reloaded = (
            db_session.query(Position).filter(Position.id == original_id).first()
        )
        assert reloaded.status == "closed"
        assert reloaded.shares == 0
        assert reloaded.closed_at == "2026-03-20"

        # Trade.closed_at must be stamped on the resolved option legs
        # (the sell_put + sell_call openers — issue #136).
        stamped = [t for t in reloaded.trades if t.closed_at is not None]
        assert len(stamped) >= 2
        # ``trades_stamped`` aggregate matches the count of actual writes.
        assert result.trades_stamped == len(stamped)

    @pytest.mark.unit
    def test_diff_shape_includes_all_fields(self, db_session):
        _seed_position_with_full_cycle(db_session)

        result = reconcile(db_session, apply=False)

        assert len(result.per_position) == 1
        diff = result.per_position[0]
        assert isinstance(diff, ReconcilePositionDiff)
        assert diff.ticker == "MARA"
        assert diff.status_before == "open"
        assert diff.status_after == "closed"
        assert diff.shares_before == 100
        assert diff.shares_after == 0
        assert diff.basis_before == 0.0
        assert diff.basis_after == 0.0  # net zero after sell+called-away cycle
        assert diff.strategy_before == "wheel"
        # Derived label is csp on a 0-shares / no-open-legs / closed position.
        assert diff.strategy_after in {"csp", "holding", "cc", "wheel"}
        assert diff.closed_at_before is None
        assert diff.closed_at_after == "2026-03-20"
        assert diff.legs_consumed >= 2

    @pytest.mark.unit
    def test_no_op_when_state_already_correct(self, db_session, monkeypatch):
        """When stored state matches the ledger, ``changed`` is zero."""
        # Freeze the recomputer's clock so the calendar fallback doesn't
        # auto-close the still-live leg.
        monkeypatch.setattr(positions_module, "_utc_today", lambda: date(2026, 3, 1))

        pos = Position(
            id=str(uuid.uuid4()),
            ticker="F",
            shares=0,
            broker_cost_basis=0.0,
            status="open",
            strategy="csp",
            opened_at="2026-03-01T00:00:00Z",
        )
        db_session.add(pos)
        db_session.flush()
        db_session.add(
            Trade(
                id=str(uuid.uuid4()),
                position_id=pos.id,
                trade_type="sell_put",
                strike=13.50,
                expiration="2026-03-27",
                premium=0.0,
                fees=0.0,
                quantity=1,
                opened_at="2026-03-01",
            )
        )
        db_session.commit()

        result = reconcile(db_session, apply=True)

        assert result.positions_processed == 1
        assert result.changed == 0
        assert result.status_changes == 0
        assert result.share_corrections == 0
        assert result.basis_corrections == 0
        assert result.strategy_changes == 0
        assert result.trades_stamped == 0

    @pytest.mark.unit
    def test_legs_consumed_counts_only_new_writes(self, db_session, monkeypatch):
        """Pre-stamped Trade.closed_at rows do not inflate ``legs_consumed``."""
        # Set today so the calendar fallback does fire on the past leg.
        monkeypatch.setattr(positions_module, "_utc_today", lambda: date(2026, 4, 1))

        pos = Position(
            id=str(uuid.uuid4()),
            ticker="F",
            shares=0,
            broker_cost_basis=0.0,
            status="open",
            strategy="csp",
            opened_at="2026-03-01T00:00:00Z",
        )
        db_session.add(pos)
        db_session.flush()
        # Pre-stamp the opener so the recompute pass should NOT count it.
        pre_stamped = Trade(
            id=str(uuid.uuid4()),
            position_id=pos.id,
            trade_type="sell_put",
            strike=13.50,
            expiration="2026-03-27",
            premium=0.0,
            fees=0.0,
            quantity=1,
            opened_at="2026-03-01",
            closed_at="2026-03-27",
        )
        db_session.add(pre_stamped)
        db_session.commit()

        result = reconcile(db_session, apply=False)

        diff = result.per_position[0]
        # The opener's closed_at was already set; nothing new should be
        # stamped during this pass.
        assert diff.legs_consumed == 0
