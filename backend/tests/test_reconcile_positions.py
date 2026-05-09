"""Tests for the ``reconcile_positions`` CLI script.

The script is the user-visible fix path for journals imported before issue
#127 was patched (every position stuck at ``shares=100`` / ``basis=0`` /
``status="open"``). These tests exercise both ``--dry-run`` and ``--apply``
modes through the function-level entry point so we don't shell out.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base, Position, Trade
from scripts.reconcile_positions import main, reconcile_all


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


def _seed_ghost_open_position(
    db,
    ticker: str,
    *,
    bad_shares: int = 100,
    bad_basis: float = 0.0,
    trades: list[dict],
) -> Position:
    """Seed a Position with intentionally wrong derived state + a trade ledger.

    Mirrors the bug repro from issue #127 — pre-fix imports left
    ``shares=100`` and ``broker_cost_basis=0.0`` even when the trade ledger
    showed something different.
    """
    position = Position(
        id=str(uuid.uuid4()),
        ticker=ticker,
        shares=bad_shares,
        broker_cost_basis=bad_basis,
        status="open",
        strategy="wheel",
        opened_at="2026-01-01T00:00:00Z",
    )
    db.add(position)
    db.flush()
    for spec in trades:
        db.add(
            Trade(
                id=str(uuid.uuid4()),
                position_id=position.id,
                premium=0.0,
                fees=0.0,
                quantity=spec.get("quantity", 1),
                **{k: v for k, v in spec.items() if k != "quantity"},
            )
        )
    db.commit()
    db.refresh(position)
    return position


class TestReconcileAll:
    def test_dry_run_makes_no_writes(self, db_session, capsys):
        pos = _seed_ghost_open_position(
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
                    "trade_type": "called_away",
                    "strike": 20.0,
                    "expiration": "2026-02-20",
                    "opened_at": "2026-02-20",
                },
            ],
        )
        original_id = pos.id

        total, changed, errors = reconcile_all(db_session, apply=False)

        assert total == 1
        assert changed == 1
        assert errors == 0

        # Re-query to confirm DB was not written.
        db_session.expire_all()
        reloaded = db_session.query(Position).filter(Position.id == original_id).first()
        assert reloaded.status == "open"  # unchanged from the bad seed
        assert reloaded.shares == 100  # unchanged

        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out
        assert "MARA" in captured.out

    def test_apply_corrects_ghost_open_positions(self, db_session, capsys):
        # Bad state: shares=100, status=open. Real ledger: full cycle ending
        # in called_away → should be closed with 0 shares.
        pos = _seed_ghost_open_position(
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
        original_id = pos.id

        total, changed, errors = reconcile_all(db_session, apply=True)

        assert total == 1
        assert changed == 1
        assert errors == 0

        db_session.expire_all()
        reloaded = db_session.query(Position).filter(Position.id == original_id).first()
        assert reloaded.status == "closed"
        assert reloaded.shares == 0
        assert reloaded.closed_at == "2026-03-20"

        captured = capsys.readouterr()
        assert "Applied" in captured.out

    def test_apply_aggregates_double_assignment(self, db_session):
        # Bad state: shares=100. Real ledger: two assignments → 200 shares.
        pos = _seed_ghost_open_position(
            db_session,
            ticker="SOFI",
            bad_shares=100,
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
        original_id = pos.id

        reconcile_all(db_session, apply=True)

        db_session.expire_all()
        reloaded = db_session.query(Position).filter(Position.id == original_id).first()
        assert reloaded.shares == 200
        assert reloaded.broker_cost_basis == pytest.approx(2800.0 + 3000.0)

    def test_no_changes_when_state_already_correct(self, db_session, capsys):
        # Seed with correct state for a simple sell_put leg: 0 shares, open.
        # Strategy must already match the derived "csp" label, otherwise the
        # reconciler will record a change for the label fix.
        pos = _seed_ghost_open_position(
            db_session,
            ticker="F",
            bad_shares=0,
            bad_basis=0.0,
            trades=[
                {
                    "trade_type": "sell_put",
                    "strike": 13.50,
                    "expiration": "2026-03-27",
                    "opened_at": "2026-03-01",
                },
            ],
        )
        # Override the seed's "wheel" label to the derived value so this
        # truly represents an "already correct" row.
        pos.strategy = "csp"
        db_session.commit()

        total, changed, errors = reconcile_all(db_session, apply=True)

        assert total == 1
        assert changed == 0
        assert errors == 0

    def test_apply_re_derives_strategy_label(self, db_session):
        # Bad state: stored as "wheel" but the ledger shows held shares with
        # no open option legs → the derived label is "holding". This
        # mirrors the real-world repro from the issue (wheel-imported batch
        # left two equity-only positions stuck on "wheel" on the dashboard).
        pos = _seed_ghost_open_position(
            db_session,
            ticker="F",
            bad_shares=100,
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
        assert pos.strategy == "wheel"  # stale seed

        total, changed, errors = reconcile_all(db_session, apply=True)

        assert total == 1
        assert changed == 1
        assert errors == 0

        db_session.expire_all()
        reloaded = (
            db_session.query(Position).filter(Position.id == original_id).first()
        )
        assert reloaded.strategy == "holding"
        assert reloaded.shares == 100


class TestMainCli:
    """Argparse-driven entry point for the script (``python -m scripts...``)."""

    def test_main_dry_run_default(self, db_session):
        # Patch SessionLocal so the CLI uses the test engine.
        with patch(
            "scripts.reconcile_positions.SessionLocal",
            return_value=db_session,
        ):
            # SessionLocal() is called inside main(); patching the class so
            # main()'s `SessionLocal()` call returns our pre-built session.
            with patch.object(db_session, "close"):
                exit_code = main([])

        assert exit_code == 0

    def test_main_apply_returns_zero_with_no_errors(self, db_session):
        with patch(
            "scripts.reconcile_positions.SessionLocal",
            return_value=db_session,
        ):
            with patch.object(db_session, "close"):
                exit_code = main(["--apply"])

        assert exit_code == 0
