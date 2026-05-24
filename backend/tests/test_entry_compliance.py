"""Unit + integration tests for per-trade entry-rule compliance tagging (#160).

This file is the Worker A pilot of pragmatic-TDD on Quality v1 Wave 3 (#271).
Tests are organised in the same order as the plan's Test List:

1. Schema model — round-trips through SQLite, unique-per-trade, JSON fields.
   (``@pytest.mark.integration`` — these tests own a real SQLAlchemy session.)
2. Evaluation logic — pure-function checks against the failed_rules vocabulary
   locked in the Wave 3 plan §V1-Freeze-3. (``@pytest.mark.unit`` — no DB.)
3. KR-5 rolling-window summary — denominator excludes unknown_only trades.
   (``@pytest.mark.integration`` — owns a real SQLAlchemy session.)

The "no DB session" rule in PRD #261 / Quality v1 R3 means an in-memory
SQLAlchemy session still classifies as integration even when there is no
FastAPI app or TestClient — CodeRabbit caught this on the pilot's own tests
during PR #301 triage. See the Wave 3 lessons-learned subsection in CLAUDE.md.
"""

from __future__ import annotations

import json

import pytest
import sqlalchemy.exc
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base, Position, Trade, TradeEntryCompliance
from app.services.entry_compliance import (
    compute_rolling_compliance,
    evaluate_trade_compliance,
)
from app.services.rules_config import DEFAULT_RULES_CONFIG, RulesConfig


def _make_in_memory_session():
    """Create an isolated in-memory SQLite session for schema tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _seed_position(db, *, position_id: str = "pos-1", ticker: str = "AAPL") -> Position:
    """Insert a Position parent so a Trade's FK is satisfied."""
    position = Position(
        id=position_id,
        ticker=ticker,
        shares=100,
        broker_cost_basis=5000.0,
        status="open",
        strategy="csp",
        opened_at="2026-01-01T10:00:00+00:00",
    )
    db.add(position)
    db.commit()
    return position


def _seed_trade(
    db,
    *,
    trade_id: str = "trade-1",
    position_id: str = "pos-1",
    trade_type: str = "sell_put",
    strike: float = 100.0,
    expiration: str = "2026-02-15",
    premium: float = 2.50,
    opened_at: str = "2026-01-15T10:00:00+00:00",
) -> Trade:
    """Insert a Trade row for compliance tests; defaults yield a 31-DTE put."""
    trade = Trade(
        id=trade_id,
        position_id=position_id,
        trade_type=trade_type,
        strike=strike,
        expiration=expiration,
        premium=premium,
        fees=0.65,
        quantity=1,
        opened_at=opened_at,
    )
    db.add(trade)
    db.commit()
    return trade


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_trade_entry_compliance_model_persists_all_fields():
    """Schema AC-1: every column survives a write + read cycle."""
    db = _make_in_memory_session()
    _seed_position(db)
    _seed_trade(db)

    row = TradeEntryCompliance(
        trade_id="trade-1",
        evaluated_at="2026-01-15T10:00:00+00:00",
        dte_at_entry=31,
        delta_at_entry=0.25,
        monthly_return_pct=2.5,
        earnings_buffer_days=14,
        compliant=1,
        failed_rules=json.dumps([]),
        entry_rules_snapshot=json.dumps({"schema_version": 2}),
    )
    db.add(row)
    db.commit()

    fetched = (
        db.query(TradeEntryCompliance).filter_by(trade_id="trade-1").one()
    )
    assert fetched.trade_id == "trade-1"
    assert fetched.evaluated_at == "2026-01-15T10:00:00+00:00"
    assert fetched.dte_at_entry == 31
    assert fetched.delta_at_entry == 0.25
    assert fetched.monthly_return_pct == 2.5
    assert fetched.earnings_buffer_days == 14
    assert fetched.compliant == 1
    assert json.loads(fetched.failed_rules) == []
    assert json.loads(fetched.entry_rules_snapshot) == {"schema_version": 2}


@pytest.mark.integration
def test_trade_entry_compliance_unique_per_trade():
    """Schema AC-1: ``trade_id`` is the primary key — only one row per trade."""
    db = _make_in_memory_session()
    _seed_position(db)
    _seed_trade(db)

    db.add(
        TradeEntryCompliance(
            trade_id="trade-1",
            evaluated_at="2026-01-15T10:00:00+00:00",
            dte_at_entry=31,
            delta_at_entry=0.25,
            monthly_return_pct=2.5,
            earnings_buffer_days=None,
            compliant=1,
            failed_rules=json.dumps([]),
            entry_rules_snapshot=json.dumps({}),
        )
    )
    db.commit()

    db.add(
        TradeEntryCompliance(
            trade_id="trade-1",
            evaluated_at="2026-01-16T10:00:00+00:00",
            dte_at_entry=31,
            delta_at_entry=0.25,
            monthly_return_pct=2.5,
            earnings_buffer_days=None,
            compliant=1,
            failed_rules=json.dumps([]),
            entry_rules_snapshot=json.dumps({}),
        )
    )
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db.commit()


@pytest.mark.integration
def test_trade_entry_compliance_jsonb_fields_round_trip():
    """Schema AC-1: JSON-encoded fields survive write/read with nested shapes."""
    db = _make_in_memory_session()
    _seed_position(db)
    _seed_trade(db)

    failed = ["dte_too_low", "delta_unknown"]
    snapshot = {
        "schema_version": 2,
        "dte_range": {"min": 21, "max": 45},
        "delta_range_csp": {"min": 0.20, "max": 0.30},
        "min_monthly_return_pct": 2.0,
    }
    db.add(
        TradeEntryCompliance(
            trade_id="trade-1",
            evaluated_at="2026-01-15T10:00:00+00:00",
            dte_at_entry=14,
            delta_at_entry=None,
            monthly_return_pct=1.8,
            earnings_buffer_days=None,
            compliant=0,
            failed_rules=json.dumps(failed),
            entry_rules_snapshot=json.dumps(snapshot),
        )
    )
    db.commit()

    fetched = (
        db.query(TradeEntryCompliance).filter_by(trade_id="trade-1").one()
    )
    assert json.loads(fetched.failed_rules) == failed
    assert json.loads(fetched.entry_rules_snapshot) == snapshot


# ---------------------------------------------------------------------------
# Evaluation logic tests (pure functions)
# ---------------------------------------------------------------------------


def _build_trade(
    *,
    trade_type: str = "sell_put",
    strike: float = 100.0,
    expiration: str = "2026-02-15",
    opened_at: str = "2026-01-15T10:00:00+00:00",
    premium: float = 2.50,
) -> Trade:
    """Build an in-memory Trade ORM instance (no DB session needed)."""
    return Trade(
        id="trade-eval",
        position_id="pos-eval",
        trade_type=trade_type,
        strike=strike,
        expiration=expiration,
        premium=premium,
        fees=0.0,
        quantity=1,
        opened_at=opened_at,
    )


@pytest.mark.unit
def test_evaluate_sell_put_compliant_within_bands():
    """Evaluation: a sell_put inside all bands is compliant (happy path)."""
    rules = DEFAULT_RULES_CONFIG  # dte 21-45, csp delta 0.20-0.30, return >= 2.0
    trade = _build_trade(
        trade_type="sell_put",
        strike=100.0,
        # 31 DTE: opened 2026-01-15, expires 2026-02-15 -> 31 days
        opened_at="2026-01-15T10:00:00+00:00",
        expiration="2026-02-15",
        # Monthly return pct = (2.50 / 100.0) * 100 / (31/30) ≈ 2.42 — above 2.0
        premium=2.50,
    )
    result = evaluate_trade_compliance(
        trade,
        rules,
        dte_hint=None,
        delta_hint=0.25,
        earnings_buffer_hint=21,
    )
    assert result["compliant"] is True
    assert result["failed_rules"] == []
    assert result["dte_at_entry"] == 31
    assert result["delta_at_entry"] == 0.25
    assert result["earnings_buffer_days"] == 21


@pytest.mark.unit
def test_evaluate_sell_put_fails_dte_too_low():
    """Evaluation: DTE below dte_range.min flags ``dte_too_low`` + non-compliant."""
    rules = DEFAULT_RULES_CONFIG
    # 7 DTE — well below the default min (21)
    trade = _build_trade(
        opened_at="2026-01-15T10:00:00+00:00",
        expiration="2026-01-22",
        premium=2.50,
    )
    result = evaluate_trade_compliance(
        trade, rules, dte_hint=None, delta_hint=0.25, earnings_buffer_hint=21
    )
    assert result["compliant"] is False
    assert "dte_too_low" in result["failed_rules"]


@pytest.mark.unit
def test_evaluate_sell_put_fails_dte_too_high():
    """Evaluation: DTE above dte_range.max flags ``dte_too_high`` + non-compliant."""
    rules = DEFAULT_RULES_CONFIG
    # 90 DTE — well above the default max (45)
    trade = _build_trade(
        opened_at="2026-01-15T10:00:00+00:00",
        expiration="2026-04-15",
        premium=2.50,
    )
    result = evaluate_trade_compliance(
        trade, rules, dte_hint=None, delta_hint=0.25, earnings_buffer_hint=21
    )
    assert result["compliant"] is False
    assert "dte_too_high" in result["failed_rules"]


@pytest.mark.unit
def test_evaluate_sell_put_fails_delta_too_high():
    """Evaluation: a put with delta above csp band's max flags ``delta_too_high``."""
    rules = DEFAULT_RULES_CONFIG  # csp delta band: 0.20-0.30
    trade = _build_trade(
        opened_at="2026-01-15T10:00:00+00:00",
        expiration="2026-02-15",
        premium=2.50,
    )
    result = evaluate_trade_compliance(
        trade, rules, dte_hint=None, delta_hint=0.45, earnings_buffer_hint=21
    )
    assert result["compliant"] is False
    assert "delta_too_high" in result["failed_rules"]


@pytest.mark.unit
def test_evaluate_sell_call_uses_delta_range_cc():
    """Evaluation: ``sell_call`` is checked against ``delta_range_cc`` (not csp)."""
    rules = DEFAULT_RULES_CONFIG  # cc delta band: 0.20-0.35
    # Delta 0.32 — would fail csp (>0.30) but is inside the cc band (≤0.35).
    trade = _build_trade(
        trade_type="sell_call",
        opened_at="2026-01-15T10:00:00+00:00",
        expiration="2026-02-15",
        premium=2.50,
    )
    result = evaluate_trade_compliance(
        trade, rules, dte_hint=None, delta_hint=0.32, earnings_buffer_hint=21
    )
    assert result["compliant"] is True
    assert "delta_too_high" not in result["failed_rules"]


@pytest.mark.unit
def test_evaluate_delta_unknown_does_not_count_as_non_compliant():
    """Evaluation: missing delta marks ``delta_unknown`` but stays compliant."""
    rules = DEFAULT_RULES_CONFIG
    trade = _build_trade(
        opened_at="2026-01-15T10:00:00+00:00",
        expiration="2026-02-15",
        premium=2.50,
    )
    result = evaluate_trade_compliance(
        trade, rules, dte_hint=None, delta_hint=None, earnings_buffer_hint=21
    )
    assert "delta_unknown" in result["failed_rules"]
    assert result["compliant"] is True  # unknown does NOT block compliance


@pytest.mark.unit
def test_evaluate_earnings_buffer_unknown_excluded_from_compliance():
    """Evaluation: missing earnings_buffer marks unknown but stays compliant."""
    rules = DEFAULT_RULES_CONFIG
    trade = _build_trade(
        opened_at="2026-01-15T10:00:00+00:00",
        expiration="2026-02-15",
        premium=2.50,
    )
    result = evaluate_trade_compliance(
        trade, rules, dte_hint=None, delta_hint=0.25, earnings_buffer_hint=None
    )
    assert "earnings_buffer_unknown" in result["failed_rules"]
    assert result["compliant"] is True


@pytest.mark.unit
def test_evaluate_monthly_return_below_threshold_fails():
    """Evaluation: monthly_return_pct below min flags ``monthly_return_too_low``."""
    rules = DEFAULT_RULES_CONFIG  # min_monthly_return_pct: 2.0
    # premium 0.50 on strike 100, 31 DTE → ~0.48% monthly return (below 2.0)
    trade = _build_trade(
        opened_at="2026-01-15T10:00:00+00:00",
        expiration="2026-02-15",
        premium=0.50,
    )
    result = evaluate_trade_compliance(
        trade, rules, dte_hint=None, delta_hint=0.25, earnings_buffer_hint=21
    )
    assert result["compliant"] is False
    assert "monthly_return_too_low" in result["failed_rules"]


@pytest.mark.unit
def test_evaluate_snapshots_entry_rules_at_evaluation_time():
    """Evaluation: ``entry_rules_snapshot`` is a snapshot, not a reference.

    Re-evaluating the same trade with mutated rules produces a different
    snapshot — proving the historical snapshot is independent of the live
    config. The non-retroactivity invariant is enforced at the
    ``record_trade_compliance`` layer (one-shot write); evaluation-time
    snapshotting is the foundation that makes it possible.
    """
    rules_a = DEFAULT_RULES_CONFIG
    rules_b = RulesConfig.model_validate(
        {
            **DEFAULT_RULES_CONFIG.model_dump(),
            "entry": {
                **DEFAULT_RULES_CONFIG.entry.model_dump(),
                "min_monthly_return_pct": 5.0,
            },
        }
    )
    trade = _build_trade(
        opened_at="2026-01-15T10:00:00+00:00",
        expiration="2026-02-15",
        premium=2.50,
    )
    result_a = evaluate_trade_compliance(
        trade, rules_a, dte_hint=None, delta_hint=0.25, earnings_buffer_hint=21
    )
    result_b = evaluate_trade_compliance(
        trade, rules_b, dte_hint=None, delta_hint=0.25, earnings_buffer_hint=21
    )
    assert result_a["entry_rules_snapshot"]["min_monthly_return_pct"] == 2.0
    assert result_b["entry_rules_snapshot"]["min_monthly_return_pct"] == 5.0


@pytest.mark.unit
def test_evaluate_failed_rules_lists_all_violations_when_multiple_fail():
    """Evaluation: ``failed_rules`` aggregates every violation (no short-circuit)."""
    rules = DEFAULT_RULES_CONFIG
    # 7 DTE + delta 0.45 + tiny premium → DTE low + delta high + return low all fire
    trade = _build_trade(
        opened_at="2026-01-15T10:00:00+00:00",
        expiration="2026-01-22",
        premium=0.20,
    )
    result = evaluate_trade_compliance(
        trade, rules, dte_hint=None, delta_hint=0.45, earnings_buffer_hint=21
    )
    assert result["compliant"] is False
    assert "dte_too_low" in result["failed_rules"]
    assert "delta_too_high" in result["failed_rules"]
    assert "monthly_return_too_low" in result["failed_rules"]


# ---------------------------------------------------------------------------
# KR-5 rolling-window summary tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_compute_rolling_compliance_excludes_unknowns_from_denominator():
    """KR-5 AC: ``compliant_pct = compliant / (total - unknown_only)``.

    A trade whose ONLY failed_rules entries are ``*_unknown`` markers is
    "unknown_only" — counted in ``total`` and ``unknown_only`` but excluded
    from the compliant/non-compliant denominator.
    """
    from datetime import datetime, timedelta, timezone

    db = _make_in_memory_session()
    _seed_position(db)
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=5)).isoformat()

    # 1 compliant trade (no failed_rules)
    db.add(
        Trade(
            id="t-comp",
            position_id="pos-1",
            trade_type="sell_put",
            strike=100.0,
            expiration="2026-02-15",
            premium=2.50,
            fees=0.0,
            quantity=1,
            opened_at=recent,
        )
    )
    db.add(
        TradeEntryCompliance(
            trade_id="t-comp",
            evaluated_at=recent,
            dte_at_entry=31,
            delta_at_entry=0.25,
            monthly_return_pct=2.4,
            earnings_buffer_days=21,
            compliant=1,
            failed_rules=json.dumps([]),
            entry_rules_snapshot=json.dumps({}),
        )
    )

    # 1 non-compliant trade (real violation: monthly_return_too_low)
    db.add(
        Trade(
            id="t-noncomp",
            position_id="pos-1",
            trade_type="sell_put",
            strike=100.0,
            expiration="2026-02-15",
            premium=0.20,
            fees=0.0,
            quantity=1,
            opened_at=recent,
        )
    )
    db.add(
        TradeEntryCompliance(
            trade_id="t-noncomp",
            evaluated_at=recent,
            dte_at_entry=31,
            delta_at_entry=0.25,
            monthly_return_pct=0.5,
            earnings_buffer_days=21,
            compliant=0,
            failed_rules=json.dumps(["monthly_return_too_low"]),
            entry_rules_snapshot=json.dumps({}),
        )
    )

    # 2 unknown-only trades (only delta_unknown + earnings_buffer_unknown)
    for tid in ("t-unk-1", "t-unk-2"):
        db.add(
            Trade(
                id=tid,
                position_id="pos-1",
                trade_type="sell_put",
                strike=100.0,
                expiration="2026-02-15",
                premium=2.50,
                fees=0.0,
                quantity=1,
                opened_at=recent,
            )
        )
        db.add(
            TradeEntryCompliance(
                trade_id=tid,
                evaluated_at=recent,
                dte_at_entry=31,
                delta_at_entry=None,
                monthly_return_pct=2.4,
                earnings_buffer_days=None,
                compliant=1,
                failed_rules=json.dumps(
                    ["delta_unknown", "earnings_buffer_unknown"]
                ),
                entry_rules_snapshot=json.dumps({}),
            )
        )

    db.commit()

    summary = compute_rolling_compliance(db, DEFAULT_RULES_CONFIG, window_days=30)
    assert summary.total == 4
    assert summary.unknown_only == 2
    assert summary.compliant == 1
    # Denominator = 4 - 2 = 2; compliant = 1; pct = 50.0
    assert summary.compliant_pct == 50.0
    assert summary.window_days == 30


@pytest.mark.integration
def test_compute_rolling_compliance_returns_none_when_denominator_zero():
    """KR-5 AC: ``compliant_pct`` is ``None`` when (total - unknown_only) == 0."""
    db = _make_in_memory_session()
    summary = compute_rolling_compliance(
        db, DEFAULT_RULES_CONFIG, window_days=30
    )
    assert summary.total == 0
    assert summary.unknown_only == 0
    assert summary.compliant == 0
    assert summary.compliant_pct is None


# ---------------------------------------------------------------------------
# CodeRabbit triage on PR #301 — regression coverage for the 9 fixes.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_deleting_trade_cascade_deletes_entry_compliance_row():
    """Fix #1: ``trade_entry_compliance`` is a child of ``trades``.

    When the parent trade is deleted via the ORM, the compliance row is
    removed in the same transaction (``cascade="all, delete-orphan"`` on
    ``Trade.entry_compliance``). Without this the compliance row would
    orphan (or block the delete with a FK violation when pragma is on).
    """
    db = _make_in_memory_session()
    _seed_position(db)
    _seed_trade(db)

    db.add(
        TradeEntryCompliance(
            trade_id="trade-1",
            evaluated_at="2026-01-15T10:00:00+00:00",
            dte_at_entry=31,
            delta_at_entry=0.25,
            monthly_return_pct=2.4,
            earnings_buffer_days=21,
            compliant=1,
            failed_rules=json.dumps([]),
            entry_rules_snapshot=json.dumps({}),
        )
    )
    db.commit()
    assert db.query(TradeEntryCompliance).count() == 1

    trade = db.query(Trade).filter_by(id="trade-1").one()
    db.delete(trade)
    db.commit()

    assert db.query(Trade).filter_by(id="trade-1").first() is None
    assert db.query(TradeEntryCompliance).count() == 0


@pytest.mark.integration
def test_compute_rolling_compliance_excludes_future_dated_trades():
    """Fix #6: ``opened_at`` strictly in the future is excluded from total.

    Without the upper bound, future-dated trades inflate ``total`` and skew
    ``compliant_pct``. With it, a trade dated ``now + 1 day`` is NOT counted.
    """
    from datetime import datetime, timedelta, timezone

    db = _make_in_memory_session()
    _seed_position(db)
    now = datetime.now(timezone.utc)
    future = (now + timedelta(days=1)).isoformat()

    db.add(
        Trade(
            id="t-future",
            position_id="pos-1",
            trade_type="sell_put",
            strike=100.0,
            expiration="2026-12-15",
            premium=2.50,
            fees=0.0,
            quantity=1,
            opened_at=future,
        )
    )
    db.add(
        TradeEntryCompliance(
            trade_id="t-future",
            evaluated_at=future,
            dte_at_entry=31,
            delta_at_entry=0.25,
            monthly_return_pct=2.4,
            earnings_buffer_days=21,
            compliant=1,
            failed_rules=json.dumps([]),
            entry_rules_snapshot=json.dumps({}),
        )
    )
    db.commit()

    summary = compute_rolling_compliance(
        db, DEFAULT_RULES_CONFIG, window_days=30
    )
    assert summary.total == 0
    assert summary.compliant == 0
