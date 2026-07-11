"""Tests for the put-assignment share-delivery double-count fix (bug #425).

When a short put is assigned, the acquisition can reach the import surface
twice: the option-leg ``assignment`` (which the recomputer credits ``qty*100``
shares for, at strike-based basis) AND a same-day equity ``buy_stock`` for the
delivered shares. Both add shares, so the position doubles. The ``assignment``
is the canonical wheel event, so the equity delivery leg must be suppressed at
import so the shares are credited exactly once.

Unit tier exercises the pure suppression detector
(:func:`app.services.schwab_import._detect_assignment_delivery_legs`) against a
lightweight fake session (no real DB). Integration tier drives the real
CSV-parse -> import -> recompute pipeline end to end and asserts the reconciled
share count and basis, using the real prod numbers from position F.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base, Position
from app.services.positions import recompute_position_state
from app.services.schwab_csv import parse_schwab_csv
from app.services.schwab_import import (
    _detect_assignment_delivery_legs,
    build_preview,
    execute_mapped_import,
)


# --- Unit tier: the pure suppression detector -------------------------------


class _FakeQuery:
    """Minimal chainable query stub. ``.all()`` yields persisted assignment
    rows; ``.first()`` yields None so no batch row is seen as a duplicate."""

    def __init__(self, all_rows: list):
        self._all = all_rows

    def join(self, *args, **kwargs) -> "_FakeQuery":
        return self

    def filter(self, *args, **kwargs) -> "_FakeQuery":
        return self

    def all(self) -> list:
        return self._all

    def first(self):
        return None


class _FakeDB:
    """Fake session returning a fixed set of persisted ``assignment`` rows.

    ``persisted`` is a list of ``(quantity, ticker, opened_at)`` triples,
    matching the columns the detector selects for persisted assignments.
    """

    def __init__(self, persisted: list | None = None):
        self._persisted = persisted or []

    def query(self, *args, **kwargs) -> _FakeQuery:
        return _FakeQuery(self._persisted)


def _assignment(ticker: str = "F", opened_at: str = "2026-03-17", quantity: int = 1) -> dict:
    return {
        "ticker": ticker,
        "trade_type": "assignment",
        "strike": 13.50,
        "expiration": "2026-03-17",
        "premium": 0.0,
        "fees": 0.0,
        "quantity": quantity,
        "opened_at": opened_at,
    }


def _buy_stock(ticker: str = "F", opened_at: str = "2026-03-17", quantity: int = 100) -> dict:
    return {
        "ticker": ticker,
        "trade_type": "buy_stock",
        "strike": None,
        "expiration": None,
        "premium": 0.0,
        "unit_amount": 13.50,
        "fees": 0.0,
        "quantity": quantity,
        "opened_at": opened_at,
    }


@pytest.mark.unit
@pytest.mark.ac("425-AC2")
def test_detect_suppresses_coincident_delivery_leg():
    """A buy_stock matching a same-batch put assignment is flagged for suppression."""
    mapped = [_assignment(), _buy_stock()]
    assert _detect_assignment_delivery_legs(_FakeDB(), mapped) == {1}


@pytest.mark.unit
@pytest.mark.ac("425-AC2")
def test_detect_ignores_standalone_buy_stock():
    """A buy_stock with no coincident assignment is left untouched (AC3 guard)."""
    mapped = [_buy_stock(ticker="NOK", quantity=100)]
    assert _detect_assignment_delivery_legs(_FakeDB(), mapped) == set()


@pytest.mark.unit
@pytest.mark.ac("425-AC2")
def test_detect_requires_matching_share_count():
    """Delivered shares must equal assignment.quantity*100 — a 50-share buy on a
    1-contract (100-share) assignment is a distinct event, not a delivery leg."""
    mapped = [_assignment(quantity=1), _buy_stock(quantity=50)]
    assert _detect_assignment_delivery_legs(_FakeDB(), mapped) == set()


@pytest.mark.unit
@pytest.mark.ac("425-AC2")
def test_detect_requires_matching_date():
    """A buy on a different date than the assignment is not its delivery leg."""
    mapped = [_assignment(opened_at="2026-03-17"), _buy_stock(opened_at="2026-03-18")]
    assert _detect_assignment_delivery_legs(_FakeDB(), mapped) == set()


@pytest.mark.unit
@pytest.mark.ac("425-AC2")
def test_detect_requires_matching_ticker():
    """A buy on a different ticker is never an assignment's delivery leg."""
    mapped = [_assignment(ticker="F"), _buy_stock(ticker="AAPL")]
    assert _detect_assignment_delivery_legs(_FakeDB(), mapped) == set()


@pytest.mark.unit
@pytest.mark.ac("425-AC2")
def test_detect_claims_slots_one_to_one():
    """Two same-key assignments cover two buys; a single assignment covers one."""
    two = [_assignment(), _assignment(), _buy_stock(), _buy_stock()]
    assert _detect_assignment_delivery_legs(_FakeDB(), two) == {2, 3}

    # One assignment, two identical buys -> only the first buy is suppressed.
    one = [_assignment(), _buy_stock(), _buy_stock()]
    suppressed = _detect_assignment_delivery_legs(_FakeDB(), one)
    assert len(suppressed) == 1
    assert suppressed <= {1, 2}


@pytest.mark.unit
@pytest.mark.ac("425-AC1")
def test_detect_matches_persisted_assignment_reimport():
    """A re-imported buy_stock matches an assignment already in the DB.

    Simulates the idempotent path: the assignment persisted on a prior import,
    only the duplicate buy_stock comes in again — it must still be suppressed.
    """
    db = _FakeDB(persisted=[(1, "F", "2026-03-17")])  # (quantity, ticker, opened_at)
    mapped = [_buy_stock()]
    assert _detect_assignment_delivery_legs(db, mapped) == {0}


# --- Integration tier: the real CSV -> import -> recompute pipeline ----------

# Real prod numbers (position F): a 13.50-strike put sold for $0.30/sh with
# $0.66 fees, assigned into 100 shares. Broker basis = strike 13.50 * 100 =
# 1350, softened by the net put premium (30.00 - 0.66 = 29.34) to 1320.66.
_HEADER = "Date,Action,Symbol,Description,Quantity,Price,Fees & Comm,Amount"
_SELL_PUT_ROW = "02/17/2026,Sell to Open,F 03/17/2026 13.50 P,PUT,1,0.30,0.66,29.34"
_ASSIGNED_ROW = "03/17/2026,Assigned,F 03/17/2026 13.50 P,PUT,1,,0.00,0.00"
_DELIVERY_BUY_ROW = "03/17/2026,Buy,F,FORD MOTOR CO,100,13.50,0.00,(1350.00)"
# A genuine standalone stock buy on a different ticker with no assignment.
_STANDALONE_BUY_ROW = "06/02/2026,Buy,NOK,NOKIA CORP,100,4.50,1.00,(451.00)"


def _csv(rows: list[str]) -> bytes:
    return ("\n".join([_HEADER, *rows]) + "\n").encode("utf-8")


@pytest.fixture()
def db_session():
    """In-memory SQLite session for the import + recompute pipeline."""
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
    TestSessionLocal = sessionmaker(bind=engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


def _position(db, ticker: str) -> Position:
    positions = db.query(Position).filter(Position.ticker == ticker).all()
    assert len(positions) == 1, f"expected one {ticker} position, got {len(positions)}"
    return positions[0]


@pytest.mark.integration
@pytest.mark.ac("425-AC2")
def test_assignment_plus_delivery_leg_nets_to_100_shares(db_session):
    """The core regression: sell_put + assigned + duplicate buy_stock -> 100 shares.

    Uses the real prod-F numbers. The coincident buy_stock is suppressed, so the
    assignment credits 100 shares once at the strike-based, premium-softened
    basis (1320.66) — not 200 shares.
    """
    mapped = parse_schwab_csv(_csv([_SELL_PUT_ROW, _ASSIGNED_ROW, _DELIVERY_BUY_ROW]))
    result = execute_mapped_import(db_session, mapped)

    pos = _position(db_session, "F")
    assert pos.shares == 100  # not 200
    assert pos.broker_cost_basis == pytest.approx(1320.66, abs=0.01)

    # The delivery leg was suppressed, not inserted, and surfaced to the caller.
    assert len(result["skipped_assignment_legs"]) == 1
    leg = result["skipped_assignment_legs"][0]
    assert leg["ticker"] == "F"
    assert leg["quantity"] == 100


@pytest.mark.integration
@pytest.mark.ac("425-AC1")
def test_assignment_only_credits_100_shares(db_session):
    """assignment-only (no coincident buy_stock) still credits its 100 shares."""
    mapped = parse_schwab_csv(_csv([_SELL_PUT_ROW, _ASSIGNED_ROW]))
    result = execute_mapped_import(db_session, mapped)

    pos = _position(db_session, "F")
    assert pos.shares == 100
    assert result["skipped_assignment_legs"] == []


@pytest.mark.integration
@pytest.mark.ac("425-AC3")
def test_standalone_buy_stock_unaffected(db_session):
    """A genuine standalone stock buy with no assignment still adds its shares."""
    mapped = parse_schwab_csv(_csv([_STANDALONE_BUY_ROW]))
    result = execute_mapped_import(db_session, mapped)

    pos = _position(db_session, "NOK")
    assert pos.shares == 100  # unchanged: no over-correction
    assert result["skipped_assignment_legs"] == []
    assert result["imported"] == 1


@pytest.mark.integration
@pytest.mark.ac("425-AC3")
def test_standalone_and_delivery_legs_coexist(db_session):
    """A standalone buy and an assignment-delivery buy in one import are handled
    independently — the delivery leg is suppressed, the standalone buy is not."""
    mapped = parse_schwab_csv(
        _csv([_SELL_PUT_ROW, _ASSIGNED_ROW, _DELIVERY_BUY_ROW, _STANDALONE_BUY_ROW])
    )
    result = execute_mapped_import(db_session, mapped)

    assert _position(db_session, "F").shares == 100
    assert _position(db_session, "NOK").shares == 100
    assert len(result["skipped_assignment_legs"]) == 1
    assert result["skipped_assignment_legs"][0]["ticker"] == "F"


@pytest.mark.integration
@pytest.mark.ac("425-AC2")
def test_reimport_is_idempotent(db_session):
    """Re-importing the same transactions never reintroduces the duplicate."""
    rows = [_SELL_PUT_ROW, _ASSIGNED_ROW, _DELIVERY_BUY_ROW]
    execute_mapped_import(db_session, parse_schwab_csv(_csv(rows)))
    first = _position(db_session, "F")
    assert first.shares == 100

    # Second identical import: sell_put/assigned dedup, buy_stock stays suppressed.
    result = execute_mapped_import(db_session, parse_schwab_csv(_csv(rows)))
    recompute_position_state(db_session, first.id)

    pos = _position(db_session, "F")
    assert pos.shares == 100  # still 100 after re-import
    assert result["imported"] == 0
    assert len(result["skipped_assignment_legs"]) == 1


@pytest.mark.integration
@pytest.mark.ac("425-AC2")
def test_preview_flags_delivery_leg(db_session):
    """The preview flags the delivery leg and excludes it from ``new_count`` so
    the preview and execute paths agree on what will be imported."""
    mapped = parse_schwab_csv(_csv([_SELL_PUT_ROW, _ASSIGNED_ROW, _DELIVERY_BUY_ROW]))
    preview = build_preview(db_session, mapped)

    assert preview["assignment_legs"] == 1
    assert preview["new_count"] == 2  # sell_put + assignment; buy_stock excluded

    flagged = [t for t in preview["trades"] if t.get("is_assignment_leg")]
    assert len(flagged) == 1
    assert flagged[0]["trade_type"] == "buy_stock"
    assert flagged[0]["ticker"] == "F"
