"""Unit tests for journal computation functions."""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.database import Base, Position, Trade
from app.services.journal import (
    clear_all_journal_data,
    compute_adjusted_basis,
    compute_min_cc_strike,
    compute_per_share_basis,
    compute_total_premiums,
    delete_position,
)


def _make_trade(premium: float, quantity: int = 1) -> SimpleNamespace:
    """Create a minimal trade-like object for computation tests."""
    return SimpleNamespace(premium=premium, quantity=quantity)


@pytest.mark.unit
def test_compute_total_premiums_sell_only():
    """Two sell_put trades should produce a positive total."""
    trades = [
        _make_trade(premium=1.50, quantity=1),  # 1.50 * 1 * 100 = 150
        _make_trade(premium=2.00, quantity=1),  # 2.00 * 1 * 100 = 200
    ]
    assert compute_total_premiums(trades) == 350.0


@pytest.mark.unit
def test_compute_total_premiums_multi_contract():
    """Multi-contract trades correctly multiply by quantity."""
    trades = [
        _make_trade(premium=1.50, quantity=3),  # 1.50 * 3 * 100 = 450
    ]
    assert compute_total_premiums(trades) == 450.0


@pytest.mark.unit
def test_compute_total_premiums_mixed():
    """Sells and buy-to-close should net out correctly."""
    trades = [
        _make_trade(premium=2.00, quantity=1),   # +200
        _make_trade(premium=-0.50, quantity=1),  # -50
    ]
    assert compute_total_premiums(trades) == 150.0


@pytest.mark.unit
def test_compute_total_premiums_empty():
    """No trades should return 0.0."""
    assert compute_total_premiums([]) == 0.0


@pytest.mark.unit
def test_compute_adjusted_basis():
    """broker_cost_basis 5000, premiums 350 -> 4650."""
    assert compute_adjusted_basis(5000.0, 350.0) == 4650.0


# --- Issue #320: per-share cost basis ---


@pytest.mark.unit
def test_compute_per_share_basis_divides_and_rounds():
    """round(total / shares, 4) — the covered-call/action-engine convention."""
    assert compute_per_share_basis(2856.0, 100) == 28.56


@pytest.mark.unit
def test_compute_per_share_basis_rounds_to_four_decimals():
    """Non-terminating quotient is rounded to 4 decimals, not truncated."""
    # 2632.10 / 100 = 26.321 exactly; pick a divisor that needs rounding.
    assert compute_per_share_basis(1000.0, 3) == 333.3333


@pytest.mark.unit
def test_compute_per_share_basis_shares_zero_returns_none():
    """shares == 0 → None (display renders an em-dash, never a divide)."""
    assert compute_per_share_basis(2856.0, 0) is None


@pytest.mark.unit
def test_compute_per_share_basis_negative_shares_returns_none():
    """shares < 0 (data corruption) → None, no negative per-share leaks out."""
    assert compute_per_share_basis(2856.0, -100) is None


@pytest.mark.unit
def test_compute_per_share_basis_zero_total():
    """A zero total with real shares is a legitimate $0.00/sh, not None."""
    assert compute_per_share_basis(0.0, 100) == 0.0


@pytest.mark.unit
def test_compute_min_cc_strike():
    """adjusted 4650, 100 shares -> (4650/100)*1.10 = 51.15."""
    assert compute_min_cc_strike(4650.0, 100) == 51.15


@pytest.mark.unit
def test_compute_min_cc_strike_rounding():
    """Verify result is rounded to 2 decimal places."""
    # 4777 / 100 = 47.77, * 1.10 = 52.547 -> 52.55
    result = compute_min_cc_strike(4777.0, 100)
    assert result == 52.55
    # Confirm it's actually rounded (string check)
    assert len(str(result).split(".")[-1]) <= 2


# --- delete / clear-all service-layer tests ---


@pytest.fixture
def db_session():
    """In-memory SQLite session for direct service-layer tests."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_position(db, ticker: str = "AAPL", trade_count: int = 0) -> Position:
    pos = Position(
        id=str(uuid.uuid4()),
        ticker=ticker,
        shares=100,
        broker_cost_basis=10_000.0,
        status="open",
        strategy="csp",
        opened_at="2025-01-01T00:00:00Z",
    )
    db.add(pos)
    for i in range(trade_count):
        db.add(
            Trade(
                id=str(uuid.uuid4()),
                position_id=pos.id,
                trade_type="sell_put",
                strike=100.0,
                expiration="2025-02-21",
                premium=1.0 + i,
                fees=0.0,
                quantity=1,
                opened_at="2025-01-02T00:00:00Z",
            )
        )
    db.commit()
    return pos


@pytest.mark.unit
def test_delete_position_cascades_trades(db_session):
    """delete_position should also remove every child trade via ORM cascade."""
    pos = _seed_position(db_session, trade_count=3)

    assert delete_position(db_session, pos.id) is True
    assert db_session.query(Position).count() == 0
    assert db_session.query(Trade).count() == 0


@pytest.mark.unit
def test_delete_position_returns_false_for_unknown(db_session):
    assert delete_position(db_session, "missing-id") is False


@pytest.mark.unit
def test_clear_all_journal_data_returns_counts(db_session):
    _seed_position(db_session, ticker="AAPL", trade_count=2)
    _seed_position(db_session, ticker="MSFT", trade_count=1)

    result = clear_all_journal_data(db_session)
    assert result == {"deleted_positions": 2, "deleted_trades": 3}
    assert db_session.query(Position).count() == 0
    assert db_session.query(Trade).count() == 0


@pytest.mark.unit
def test_clear_all_journal_data_empty_db(db_session):
    result = clear_all_journal_data(db_session)
    assert result == {"deleted_positions": 0, "deleted_trades": 0}


# --- Issue #278: caller-side guard against compute_min_cc_strike log spam ---


@pytest.mark.unit
def test_build_position_response_no_warning_for_shares_zero(db_session, caplog):
    """``_build_position_response`` must not emit the noisy ``shares=0`` WARNING.

    Issue #278: ``_build_position_response`` is the hot-path caller that runs
    once per position on every dashboard load. Closed/cleared positions with
    ``shares=0`` were producing one identical WARNING per load per position,
    which dominated Axiom ingest. The caller-side guard skips
    :func:`compute_min_cc_strike` entirely when shares <= 0 so the function's
    defensive WARNING never fires for the legitimate short-circuit case.
    """
    from app.services.journal import _build_position_response

    closed = Position(
        id=str(uuid.uuid4()),
        ticker="AAPL",
        shares=0,
        broker_cost_basis=0.0,
        status="closed",
        strategy="csp",
        opened_at="2025-01-01T00:00:00Z",
    )
    db_session.add(closed)
    db_session.commit()

    caplog.clear()
    with caplog.at_level("WARNING", logger="app.services.journal"):
        result = _build_position_response(closed)

    assert "compute_min_cc_strike called with shares=" not in caplog.text
    assert result["min_compliant_cc_strike"] == 0.0
    assert result["shares"] == 0


@pytest.mark.unit
def test_build_position_response_still_computes_for_positive_shares(db_session, caplog):
    """Positive-shares path is unchanged: real call, no warning, real value."""
    from app.services.journal import _build_position_response

    open_pos = Position(
        id=str(uuid.uuid4()),
        ticker="MSFT",
        shares=100,
        broker_cost_basis=10_000.0,
        status="open",
        strategy="csp",
        opened_at="2025-01-01T00:00:00Z",
    )
    db_session.add(open_pos)
    db_session.commit()

    caplog.clear()
    with caplog.at_level("WARNING", logger="app.services.journal"):
        result = _build_position_response(open_pos)

    assert "compute_min_cc_strike called with shares=" not in caplog.text
    # 10_000 / 100 * 1.10 = 110.0
    assert result["min_compliant_cc_strike"] == 110.0


# --- Issue #320: per-share basis on the built position response ---
#
# Classification note (CodeRabbit triage): the two tests below call
# `_build_position_response` directly with a DB session (no TestClient). They
# are correctly `@pytest.mark.integration`, not `@pytest.mark.unit`: per
# CLAUDE.md's Wave 3 precedent, any test that touches a real DB session is
# integration-tier (the "no DB session" disqualifier in PRD #261/R3). The happy
# path also has a real TestClient endpoint test in test_integration_journal_api.py;
# these are the producer-level integration tests for `_build_position_response`
# itself. The shares==0 null path is endpoint-unreachable — PositionCreate
# rejects 0 shares with a 422 — so a true endpoint test for it is impossible;
# exercising the producer directly is the only way to cover that branch.


@pytest.mark.integration
def test_build_position_response_emits_per_share_basis(db_session):
    """Producer divides total/shares for both broker and adjusted basis."""
    from app.services.journal import _build_position_response

    pos = Position(
        id=str(uuid.uuid4()),
        ticker="MSFT",
        shares=100,
        broker_cost_basis=2856.0,
        status="open",
        strategy="csp",
        opened_at="2025-01-01T00:00:00Z",
    )
    db_session.add(pos)
    db_session.commit()

    result = _build_position_response(pos)
    # No trades → adjusted total == broker total → same per-share value.
    assert result["broker_cost_basis_per_share"] == 28.56
    assert result["adjusted_cost_basis_per_share"] == 28.56


@pytest.mark.integration
def test_build_position_response_per_share_basis_null_when_zero_shares(db_session):
    """shares == 0 → per-share fields are None (no divide-by-zero)."""
    from app.services.journal import _build_position_response

    closed = Position(
        id=str(uuid.uuid4()),
        ticker="AAPL",
        shares=0,
        broker_cost_basis=0.0,
        status="closed",
        strategy="csp",
        opened_at="2025-01-01T00:00:00Z",
    )
    db_session.add(closed)
    db_session.commit()

    result = _build_position_response(closed)
    assert result["broker_cost_basis_per_share"] is None
    assert result["adjusted_cost_basis_per_share"] is None


@pytest.mark.unit
def test_compute_min_cc_strike_direct_call_still_warns_for_zero_shares(caplog):
    """Direct calls to :func:`compute_min_cc_strike` still emit the defensive WARNING.

    The fix in #278 is caller-side only — the function's own guard remains in
    place so accidental direct callers (or any future caller that does not
    pre-filter) still see the warning at the def site.
    """
    caplog.clear()
    with caplog.at_level("WARNING", logger="app.services.journal"):
        result = compute_min_cc_strike(1000.0, 0)
    assert result == 0.0
    assert "compute_min_cc_strike called with shares=0" in caplog.text


@pytest.mark.unit
def test_build_position_response_warns_for_negative_shares(db_session, caplog):
    """Negative-shares (data corruption) still reaches the defensive WARNING path.

    CodeRabbit triage on PR #279: the issue #278 caller-side guard was
    initially written as ``if position.shares > 0`` which also swallowed the
    ``shares < 0`` case, contradicting the comment that says negative shares
    should still hit :func:`compute_min_cc_strike`'s defensive warning. The
    guard was tightened to ``if position.shares == 0`` — this test locks in
    the negative-shares contract so the regression cannot recur.
    """
    from app.services.journal import _build_position_response

    corrupt = Position(
        id=str(uuid.uuid4()),
        ticker="BAD",
        shares=-10,
        broker_cost_basis=1_000.0,
        status="open",
        strategy="csp",
        opened_at="2025-01-01T00:00:00Z",
    )
    db_session.add(corrupt)
    db_session.commit()

    caplog.clear()
    with caplog.at_level("WARNING", logger="app.services.journal"):
        result = _build_position_response(corrupt)

    assert "compute_min_cc_strike called with shares=-10" in caplog.text
    assert result["min_compliant_cc_strike"] == 0.0
    assert result["shares"] == -10
