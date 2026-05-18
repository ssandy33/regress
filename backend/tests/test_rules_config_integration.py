"""Integration tests for the ``rules_config`` engine wiring (issue #156).

Exercises the three resolution sites — the scan router, the recovery
endpoint, and the dashboard's action engine — against a stored ``rules_config``
``app_settings`` row. Uses the in-memory SQLite ``client`` TestClient fixture
from ``conftest.py``.

Covered:

- Scan with no stored row → catalog defaults backfilled onto the request.
- Scan with a stored config → stored values backfilled.
- Scan with an explicit per-request rule value → the override wins.
- A covered-call scan surfaces ``below_cost_basis``; the candidate stays in
  the response (never dropped); ``cost_basis_floor_enabled=False`` suppresses it.
- A stored ``min_open_interest`` rejects a strike the default floor would pass.
- The recovery endpoint honors a stored ``sizing_cap_dollars``.
- The action engine's ITM/short-DTE card honors a non-default
  ``management.expiration_warning_days`` — the boundary shifts with the stored
  value, not the catalog default.
- A fresh DB with no ``rules_config`` row still yields working scans (rollout
  AC — no migration required).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.models.database import AppSetting, Position, get_db
from app.models.schemas import OptionScanRequest
from app.services.action_engine import compute_next_actions
from app.services.options_scanner import OptionScanner
from app.services.rules_config import DEFAULT_RULES_CONFIG, RULES_CONFIG_KEY, RulesConfig
from app.services.schwab_client import SchwabClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_setting(client, key: str, value: str) -> None:
    """Write an ``app_settings`` row through the test DB session."""
    from app.main import app

    override = app.dependency_overrides[get_db]
    db = next(override())
    try:
        db.add(AppSetting(key=key, value=value))
        db.commit()
    finally:
        db.close()


def _seed_position(client, *, pos_id: str = "pos-sofi", broker_cost_basis: float) -> None:
    """Insert an open position row into the in-memory test DB."""
    from app.main import app

    override = app.dependency_overrides[get_db]
    db = next(override())
    try:
        db.add(
            Position(
                id=pos_id,
                ticker="SOFI",
                shares=100,
                broker_cost_basis=broker_cost_basis,
                status="open",
                strategy="csp",
                opened_at="2024-01-01",
            )
        )
        db.commit()
    finally:
        db.close()


class _CaptureScanner(OptionScanner):
    """A scanner subclass that records the request it was handed.

    Lets a router-resolution test assert which rule values were backfilled
    without needing a mocked Schwab chain.
    """

    captured: OptionScanRequest | None = None

    def scan(self, request: OptionScanRequest) -> dict:  # noqa: D102
        type(self).captured = request
        return {
            "ticker": request.ticker,
            "current_price": 14.0,
            "strategy": request.strategy,
            "scan_time": datetime.now().isoformat(),
            "earnings_date": None,
            "iv_rank": None,
            "recommendations": [],
            "rejected": [],
            "market_context": {},
        }


def _scan(client, body: dict) -> OptionScanRequest:
    """POST a scan, returning the OptionScanRequest the scanner received.

    Overrides the ``_get_scanner`` dependency with a capturing scanner so the
    router's ``rules_config`` backfill can be inspected directly.
    """
    from app.main import app
    from app.routers.options import _get_scanner

    _CaptureScanner.captured = None
    app.dependency_overrides[_get_scanner] = lambda: _CaptureScanner()
    try:
        resp = client.post("/api/options/scan", json=body)
    finally:
        app.dependency_overrides.pop(_get_scanner, None)
    assert resp.status_code == 200, resp.text
    assert _CaptureScanner.captured is not None
    return _CaptureScanner.captured


def _full_rules_config(**overrides) -> str:
    """Build a JSON string for a stored ``rules_config`` with overrides."""
    base = {
        "schema_version": 1,
        "universe": {
            "min_open_interest": 500,
            "max_bid_ask_spread_pct": 10.0,
            "min_iv_rank": 30.0,
        },
        "entry": {
            "dte_range": {"min": 21, "max": 45},
            "delta_range_csp": {"min": 0.20, "max": 0.30},
            "delta_range_cc": {"min": 0.20, "max": 0.35},
            "min_monthly_return_pct": 2.0,
            "earnings_buffer_days": 7,
            "min_call_distance_pct": 5.0,
            "min_call_distance_from_cost_basis_pct": 0.0,
        },
        "position": {
            "sizing_cap_dollars": 5000.0,
            "max_ticker_concentration_pct": 25.0,
        },
    }
    for group, fields in overrides.items():
        base.setdefault(group, {}).update(fields)
    return json.dumps(base)


# ---------------------------------------------------------------------------
# Scan router — backfill from rules_config
# ---------------------------------------------------------------------------


def test_scan_no_stored_row_uses_catalog_defaults(client):
    """With no ``rules_config`` row, the catalog defaults are backfilled.

    Resolves the four documented entry-rule inconsistencies: DTE 21-45,
    delta 0.20-0.30 (CSP), min return 2%, earnings buffer 7d.
    """
    req = _scan(
        client,
        {"ticker": "SOFI", "strategy": "cash_secured_put", "capital_available": 5000.0},
    )
    assert req.min_dte == 21 and req.max_dte == 45
    assert req.min_delta == 0.20 and req.max_delta == 0.30
    assert req.min_return_pct == 2.0
    assert req.exclude_earnings_dte == 7
    assert req.min_open_interest == 500
    assert req.max_bid_ask_spread_pct == 10.0
    assert req.min_iv_rank == 30.0


def test_scan_covered_call_uses_cc_delta_band(client):
    """A covered-call scan with no delta override gets the CC band (0.20-0.35)."""
    req = _scan(
        client,
        {"ticker": "AMD", "strategy": "covered_call", "cost_basis": 95.0},
    )
    assert req.min_delta == 0.20 and req.max_delta == 0.35


def test_scan_stored_config_is_honored(client):
    """A stored ``rules_config`` is backfilled onto the request."""
    _seed_setting(
        client,
        RULES_CONFIG_KEY,
        _full_rules_config(
            entry={"dte_range": {"min": 30, "max": 40}, "min_monthly_return_pct": 3.0}
        ),
    )
    req = _scan(
        client,
        {"ticker": "SOFI", "strategy": "cash_secured_put", "capital_available": 5000.0},
    )
    assert req.min_dte == 30 and req.max_dte == 40
    assert req.min_return_pct == 3.0


def test_scan_explicit_per_request_value_overrides_stored_config(client):
    """An explicit per-request rule value wins over the stored config."""
    _seed_setting(
        client,
        RULES_CONFIG_KEY,
        _full_rules_config(entry={"dte_range": {"min": 30, "max": 40}}),
    )
    req = _scan(
        client,
        {
            "ticker": "SOFI",
            "strategy": "cash_secured_put",
            "capital_available": 5000.0,
            "min_dte": 14,
            "max_dte": 28,
        },
    )
    # Explicit request values are kept; only the un-set fields are backfilled.
    assert req.min_dte == 14 and req.max_dte == 28
    assert req.min_return_pct == 2.0  # not overridden → from config


def test_fresh_db_yields_working_scan_no_migration(client):
    """Rollout AC: a fresh DB with no ``rules_config`` row still scans.

    No migration is required — ``load_rules_config`` treats the absent row as
    "all defaults" and the scan completes with a valid response shape.
    """
    from app.main import app
    from app.routers.options import _get_scanner

    _CaptureScanner.captured = None
    app.dependency_overrides[_get_scanner] = lambda: _CaptureScanner()
    try:
        resp = client.post(
            "/api/options/scan",
            json={
                "ticker": "SOFI",
                "strategy": "cash_secured_put",
                "capital_available": 5000.0,
            },
        )
    finally:
        app.dependency_overrides.pop(_get_scanner, None)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "SOFI"
    assert body["recommendations"] == []
    assert body["rejected"] == []


# ---------------------------------------------------------------------------
# Scanner — below_cost_basis + min_open_interest, end to end
# ---------------------------------------------------------------------------


def _schwab_call_chain(strike: float, *, oi: int, dte: int = 30):
    """Build a one-strike Schwab CALL chain response."""
    exp_date = (datetime.now().date() + timedelta(days=dte)).strftime("%Y-%m-%d")
    contract = {
        "strikePrice": strike,
        "bid": 0.43,
        "ask": 0.47,
        "mark": 0.45,
        "delta": -0.25,
        "gamma": 0.03,
        "theta": -0.02,
        "vega": 0.04,
        "openInterest": oi,
        "totalVolume": 100,
        "volatility": 35.0,
        "daysToExpiration": dte,
    }
    return {
        "symbol": "TEST",
        "status": "SUCCESS",
        "underlying": {"last": 14.0, "close": 14.0, "totalVolume": 1_000_000},
        "callExpDateMap": {f"{exp_date}:{dte}": {str(strike): [contract]}},
        "putExpDateMap": {},
    }


def test_cc_scan_surfaces_below_cost_basis_reason(client):
    """A CC strike below cost basis is flagged ``below_cost_basis``, not dropped."""
    # Strike $14 sits below the $20 cost basis.
    chain = _schwab_call_chain(14.0, oi=500)
    with patch.object(OptionScanner, "_get_vix", return_value=None), patch(
        "app.services.options_scanner.get_next_earnings_date", return_value=None
    ), patch.object(SchwabClient, "get_option_chain", return_value=chain):
        resp = client.post(
            "/api/options/scan",
            json={"ticker": "TEST", "strategy": "covered_call", "cost_basis": 20.0},
        )
    assert resp.status_code == 200
    rejected = resp.json()["rejected"]
    below = [
        r
        for r in rejected
        if any("below_cost_basis" in code for code in r["rejection_reasons"])
    ]
    assert below, "expected a below_cost_basis rejection"
    # The candidate is present (not silently dropped) with a human sentence.
    assert below[0]["strike"] == 14.0
    assert any("cost-basis floor" in s for s in below[0]["human_reasons"])


def test_cc_scan_below_cost_basis_suppressed_when_floor_disabled(client):
    """``cost_basis_floor_enabled=False`` suppresses the ``below_cost_basis`` reason."""
    chain = _schwab_call_chain(14.0, oi=500)
    with patch.object(OptionScanner, "_get_vix", return_value=None), patch(
        "app.services.options_scanner.get_next_earnings_date", return_value=None
    ), patch.object(SchwabClient, "get_option_chain", return_value=chain):
        resp = client.post(
            "/api/options/scan",
            json={
                "ticker": "TEST",
                "strategy": "covered_call",
                "cost_basis": 20.0,
                "cost_basis_floor_enabled": False,
            },
        )
    assert resp.status_code == 200
    rejected = resp.json()["rejected"]
    assert not any(
        "below_cost_basis" in code
        for r in rejected
        for code in r["rejection_reasons"]
    )


def test_scan_min_open_interest_rejects_thin_strike(client):
    """A stored ``min_open_interest`` of 1000 rejects a 600-OI strike.

    The default 500 floor would pass the same strike — confirms the inline
    ``oi < 50`` literal is gone and the floor comes from ``rules_config``.
    """
    _seed_setting(
        client,
        RULES_CONFIG_KEY,
        _full_rules_config(universe={"min_open_interest": 1000}),
    )
    # Strike well above the $10 cost basis so only the OI rule can reject it.
    chain = _schwab_call_chain(20.0, oi=600)
    with patch.object(OptionScanner, "_get_vix", return_value=None), patch(
        "app.services.options_scanner.get_next_earnings_date", return_value=None
    ), patch.object(SchwabClient, "get_option_chain", return_value=chain):
        resp = client.post(
            "/api/options/scan",
            json={"ticker": "TEST", "strategy": "covered_call", "cost_basis": 10.0},
        )
    assert resp.status_code == 200
    rejected = resp.json()["rejected"]
    assert any(
        "low_open_interest: 600 < 1000" in code
        for r in rejected
        for code in r["rejection_reasons"]
    )


# ---------------------------------------------------------------------------
# Recovery endpoint — sizing cap from rules_config.position
# ---------------------------------------------------------------------------


def test_recovery_endpoint_honors_stored_sizing_cap(client):
    """The recovery endpoint resolves its sizing cap from ``rules_config``.

    With a stored ``position.sizing_cap_dollars`` of $500, the average-down
    path is suppressed at a capital level the default $5,000 cap would allow.
    """
    _seed_position(client, broker_cost_basis=3800.0)
    _seed_setting(client, "okr_target_yield", "0.18")
    _seed_setting(
        client,
        RULES_CONFIG_KEY,
        _full_rules_config(position={"sizing_cap_dollars": 500.0}),
    )
    with patch.object(SchwabClient, "get_quote", return_value={"lastPrice": 8.0}):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["state"] == "populated"
    # The resolved cap is surfaced on the inputs block.
    assert payload["inputs"]["okr"]["sizing_cap_dollars"] == pytest.approx(500.0)
    # $800+ of fresh capital would breach the $500 cap → average-down suppressed.
    avg = next(p for p in payload["paths"] if p["path_id"] == "average-down")
    assert avg["eligibility"] == "suppressed"


def test_recovery_endpoint_default_sizing_cap_with_no_rules_row(client):
    """With no ``rules_config`` row the recovery endpoint uses the $5,000 default."""
    _seed_position(client, broker_cost_basis=3800.0)
    _seed_setting(client, "okr_target_yield", "0.18")
    with patch.object(SchwabClient, "get_quote", return_value={"lastPrice": 8.0}):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    assert resp.status_code == 200
    assert resp.json()["inputs"]["okr"]["sizing_cap_dollars"] == pytest.approx(5000.0)


# ---------------------------------------------------------------------------
# Loss-review threshold — recovery flag gate ↔ dashboard largest-loser card
# must agree (issue #235, AC2 "no new drift")
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("loss_review_threshold_pct", "pl_pct"),
    [
        (-15.0, -0.08),  # default rule, mild loser → neither flags
        (-15.0, -0.20),  # default rule, deep loser → both flag
        (-5.0, -0.08),   # strict rule, mild loser → both flag
        (-20.0, -0.18),  # lenient rule, -18% loser → neither flags
    ],
)
def test_flag_gate_and_largest_loser_card_agree(
    loss_review_threshold_pct, pl_pct
):
    """The recovery flag gate and the dashboard largest-loser card agree.

    Issue #235 AC2: both surfaces honor the same configured
    ``loss_review_threshold_pct``. A user must never click a dashboard
    "Review" card and land on a ``not-flagged`` recovery empty state. This
    runs the same P/L through ``_is_flagged`` (recovery) and
    ``_largest_loser_action`` (dashboard) and asserts an identical verdict.
    """
    from app.routers.positions import _is_flagged
    from app.services.action_engine import _largest_loser_action

    # An unrealized_pl too small to trip the -$1,000 dollar trigger, so the
    # percentage rule alone decides — isolating the loss_review comparison.
    unrealized_pl = -100.0

    recovery_flagged = _is_flagged(
        unrealized_pl, pl_pct, loss_review_threshold_pct
    )
    card = _largest_loser_action(
        [
            {
                "id": "p-1",
                "ticker": "SOFI",
                "unrealized_pl": unrealized_pl,
                "pl_pct": pl_pct,
            }
        ],
        loss_review_threshold_pct,
    )
    dashboard_flagged = card is not None

    assert recovery_flagged == dashboard_flagged


# ---------------------------------------------------------------------------
# IV-rank gate — plumbed but inert (ADR-002 OQ4 / issue #156)
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason="iv_rank has no data source — the gate is plumbed but inert (ADR-002 OQ4). "
    "Wiring a real IV-rank feed is a data-pipeline change beyond #156."
)
def test_iv_rank_gate_rejects_low_rank_strike():
    """The iv_rank_below_floor gate cannot be tested end to end yet.

    ``OptionScanResponse.iv_rank`` is hard-coded ``None`` because no IV-rank
    data source is wired. The ``min_iv_rank`` field, the ``iv_rank_below_floor``
    rejection code, and the humanizer are all in place (see
    ``OptionScanner._check_iv_rank`` and ``rejection_messages``), so a future
    IV-rank feed activates the gate with no scanner change. There is no
    end-to-end assertion to make until that feed exists.
    """


# ---------------------------------------------------------------------------
# Action engine — ITM/short-DTE card honors rules_config.management
# ---------------------------------------------------------------------------


def _itm_short_dte_ids(rules: RulesConfig) -> list[str]:
    """Run ``compute_next_actions`` for a single 10-DTE ITM leg under ``rules``.

    The leg's 10 DTE deliberately sits *between* the catalog default
    ``expiration_warning_days`` (7) and the non-default threshold exercised
    below (14), so the presence of the ``expiration.itm_short_dte`` card is a
    direct readout of which threshold the engine actually resolved.
    """
    status = {
        "schwab": {"configured": True, "valid": True, "expires_at": None},
        "cache": {"fresh": 0, "stale": 0, "very_stale": 0, "total": 0},
    }
    leg = {
        "id": "leg-1",
        "ticker": "SOFI",
        "type": "put",
        "strike": 14.0,
        "expiration": "2026-05-27",
        "dte": 10,
        "moneyness": {"state": "ITM", "distance_pct": 0.01, "distance_dollars": 0.5},
        "position_id": "pos-sofi",
    }
    actions = compute_next_actions(
        status=status,
        kpis={"open_legs": 1, "open_positions": 1},
        positions=[],
        open_legs=[leg],
        rules=rules,
    )
    return [a["action_id"] for a in actions]


def test_action_engine_default_threshold_excludes_10dte_itm_leg():
    """With the default 7-day window, a 10-DTE ITM leg is outside the warning.

    Pins the lower side of the boundary: ``DEFAULT_RULES_CONFIG`` resolves
    ``expiration_warning_days = 7``, so a leg at 10 DTE does NOT emit the card.
    """
    assert "expiration.itm_short_dte" not in _itm_short_dte_ids(DEFAULT_RULES_CONFIG)


def test_action_engine_honors_non_default_expiration_warning_days():
    """A stored ``expiration_warning_days`` of 14 shifts the ITM/short-DTE boundary.

    Issue #156 requires the action engine to honor the stored management
    thresholds — not the catalog default. With ``expiration_warning_days``
    raised from the default 7 to 14, a 10-DTE ITM leg now falls inside the
    warning window and the ``expiration.itm_short_dte`` card appears. Paired
    with :func:`test_action_engine_default_threshold_excludes_10dte_itm_leg`,
    this pins the boundary on both sides and would catch a regression that
    ignored ``rules`` and silently fell back to the hard-coded ``7``.
    """
    rules = RulesConfig(management={"expiration_warning_days": 14})
    assert rules.management.expiration_warning_days == 14
    assert "expiration.itm_short_dte" in _itm_short_dte_ids(rules)
