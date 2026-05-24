"""Integration tests for per-trade entry-compliance flow (#160 pilot).

Covers two surfaces:

1. Journal POST hook — ``POST /api/journal/trades`` writes a compliance row
   for ``sell_put`` / ``sell_call`` trades; ``_hint`` fields propagate.
2. Compliance read endpoints — ``GET /api/journal/trades/{id}/compliance``
   and ``GET /api/okrs/entry-compliance`` return the expected shapes.

All tests use the ``client`` fixture from ``conftest.py`` (full FastAPI stack
+ in-memory SQLite). They are ``@pytest.mark.integration`` per the Quality
v1 pyramid (R1).
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers (mirror test_integration_journal_api.py for consistency)
# ---------------------------------------------------------------------------


def _create_position(client, **overrides):
    payload = {
        "ticker": "AAPL",
        "shares": 100,
        "broker_cost_basis": 5000.0,
        "opened_at": "2026-01-15T10:00:00+00:00",
    }
    payload.update(overrides)
    return client.post("/api/journal/positions", json=payload)


def _create_trade(client, position_id, **overrides):
    payload = {
        "position_id": position_id,
        "trade_type": "sell_put",
        "strike": 100.0,
        "expiration": "2026-02-15",  # 31 DTE from opened_at
        "premium": 2.50,
        "fees": 0.65,
        "quantity": 1,
        "opened_at": "2026-01-15T10:00:00+00:00",
    }
    payload.update(overrides)
    return client.post("/api/journal/trades", json=payload)


# ---------------------------------------------------------------------------
# Journal POST hook — compliance row creation
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_post_trade_with_compliance_hints_uses_hints_in_evaluation(client):
    """Hints provided on POST /trades propagate verbatim to the row."""
    pos = _create_position(client).json()
    resp = _create_trade(
        client,
        pos["id"],
        dte_at_entry_hint=30,
        delta_at_entry_hint=0.25,
        earnings_buffer_days_hint=21,
    )
    assert resp.status_code == 201
    trade_id = resp.json()["id"]

    # The compliance row should exist; the hints must be present verbatim.
    detail = client.get(f"/api/journal/trades/{trade_id}/compliance")
    assert detail.status_code == 200
    body = detail.json()
    assert body["delta_at_entry"] == 0.25
    assert body["earnings_buffer_days"] == 21
    assert body["dte_at_entry"] == 30
    assert body["compliant"] is True
    assert body["failed_rules"] == []


@pytest.mark.integration
def test_post_trade_without_hints_records_unknowns(client):
    """Without hints, delta + earnings_buffer record as unknown."""
    pos = _create_position(client).json()
    resp = _create_trade(client, pos["id"])  # no hint fields
    assert resp.status_code == 201
    trade_id = resp.json()["id"]

    detail = client.get(f"/api/journal/trades/{trade_id}/compliance")
    assert detail.status_code == 200
    body = detail.json()
    # DTE always derivable (opened 01-15, expires 02-15 -> 31)
    assert body["dte_at_entry"] == 31
    assert body["delta_at_entry"] is None
    assert body["earnings_buffer_days"] is None
    # Unknown buckets present, but compliant True (unknown does NOT block).
    assert "delta_unknown" in body["failed_rules"]
    assert "earnings_buffer_unknown" in body["failed_rules"]
    assert body["compliant"] is True


# ---------------------------------------------------------------------------
# GET /api/journal/trades/{id}/compliance
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_trade_compliance_returns_row_for_existing_trade(client):
    """Happy path: compliance row exists -> 200 with shape."""
    pos = _create_position(client).json()
    trade = _create_trade(
        client,
        pos["id"],
        dte_at_entry_hint=30,
        delta_at_entry_hint=0.25,
        earnings_buffer_days_hint=21,
    ).json()

    resp = client.get(f"/api/journal/trades/{trade['id']}/compliance")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) >= {
        "trade_id",
        "evaluated_at",
        "dte_at_entry",
        "delta_at_entry",
        "monthly_return_pct",
        "earnings_buffer_days",
        "compliant",
        "failed_rules",
        "entry_rules_snapshot",
    }
    assert body["trade_id"] == trade["id"]
    assert body["compliant"] is True
    assert isinstance(body["entry_rules_snapshot"], dict)


@pytest.mark.integration
def test_get_trade_compliance_returns_404_when_no_compliance_row(client):
    """A trade with no compliance row (e.g. a buy_put_close) returns 404."""
    pos = _create_position(client).json()
    # buy_put_close is out-of-scope for the evaluator -> no row written.
    trade = _create_trade(
        client,
        pos["id"],
        trade_type="buy_put_close",
        premium=-0.50,  # buy = debit (matches the codebase convention)
    ).json()
    resp = client.get(f"/api/journal/trades/{trade['id']}/compliance")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/okrs/entry-compliance
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_okrs_entry_compliance_returns_summary_and_non_compliant_list(
    client,
):
    """Happy path: summary + non_compliant array populated.

    Uses a recent ``opened_at`` so the trades fall inside the rolling 30d
    window (the endpoint filters by ``opened_at >= now - 30d`` in UTC per
    the Wave 3 plan §Edge-Cases-6).
    """
    from datetime import datetime, timedelta, timezone

    pos = _create_position(client).json()
    recent = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    far_exp = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
    near_exp = (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()

    # 1 compliant trade — 30 DTE, default delta band, hinted earnings buffer
    _create_trade(
        client,
        pos["id"],
        opened_at=recent,
        expiration=far_exp,
        dte_at_entry_hint=30,
        delta_at_entry_hint=0.25,
        earnings_buffer_days_hint=21,
    )
    # 1 non-compliant trade — 7 DTE (below the min of 21)
    _create_trade(
        client,
        pos["id"],
        opened_at=recent,
        expiration=near_exp,
        dte_at_entry_hint=7,
        delta_at_entry_hint=0.25,
        earnings_buffer_days_hint=21,
    )

    resp = client.get("/api/okrs/entry-compliance")
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["total"] == 2
    assert body["summary"]["compliant"] == 1
    assert body["summary"]["unknown_only"] == 0
    assert body["summary"]["window_days"] == 30
    assert body["summary"]["compliant_pct"] == 50.0
    # Only the non-compliant trade shows up in the array.
    assert len(body["non_compliant"]) == 1
    assert "dte_too_low" in body["non_compliant"][0]["failed_rules"]


@pytest.mark.integration
def test_get_okrs_entry_compliance_empty_corpus_returns_zero_summary(client):
    """Empty corpus: summary all zeros, pct null, non_compliant empty."""
    resp = client.get("/api/okrs/entry-compliance")
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["total"] == 0
    assert body["summary"]["compliant"] == 0
    assert body["summary"]["unknown_only"] == 0
    assert body["summary"]["compliant_pct"] is None
    assert body["non_compliant"] == []


# ---------------------------------------------------------------------------
# CodeRabbit triage on PR #301 — Fix #2: _hint bounds validation.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_post_trade_rejects_negative_dte_hint(client):
    """Fix #2: negative ``dte_at_entry_hint`` -> HTTP 422 (cannot be < 0)."""
    pos = _create_position(client).json()
    resp = _create_trade(client, pos["id"], dte_at_entry_hint=-1)
    assert resp.status_code == 422


@pytest.mark.integration
def test_post_trade_rejects_negative_earnings_buffer_hint(client):
    """Fix #2: negative ``earnings_buffer_days_hint`` -> HTTP 422."""
    pos = _create_position(client).json()
    resp = _create_trade(client, pos["id"], earnings_buffer_days_hint=-1)
    assert resp.status_code == 422


@pytest.mark.integration
def test_post_trade_rejects_non_finite_delta_hint():
    """Fix #2: NaN / inf in ``delta_at_entry_hint`` -> ValidationError.

    Non-finite floats silently bypass band comparisons and would record a
    misleading verdict; reject at the schema layer instead.

    Direct schema construction here (rather than POSTing literal ``NaN``
    JSON, which would be rejected at the JSON-parse layer with a 400 before
    Pydantic ever sees it). The schema layer is the one that ships the new
    ``allow_inf_nan=False`` rule.
    """
    import math

    from pydantic import ValidationError

    from app.models.schemas import TradeCreate

    base_kwargs = {
        "position_id": "pos-1",
        "trade_type": "sell_put",
        "strike": 100.0,
        "expiration": "2026-02-15",
        "premium": 2.50,
        "fees": 0.65,
        "quantity": 1,
        "opened_at": "2026-01-15T10:00:00+00:00",
    }
    with pytest.raises(ValidationError):
        TradeCreate(**base_kwargs, delta_at_entry_hint=math.nan)
    with pytest.raises(ValidationError):
        TradeCreate(**base_kwargs, delta_at_entry_hint=math.inf)
