"""Integration tests for the Recovery Plan router.

Uses the in-memory SQLite ``client`` fixture from ``conftest.py``.
Monkeypatches ``SchwabClient.get_quote`` so no real Schwab calls are made.

Covers:

- Happy path: flagged position → ``state == "populated"`` with paths +
  recommendation.
- 404 for unknown position.
- ``state == "not-applicable"`` for shares=0 / closed / zero-basis.
- ``state == "not-flagged"`` for position above the threshold.
- 500 with the **generic** detail message when the quote fails — and the
  500 body does NOT leak ``str(e)`` (CLAUDE.md compliance).
- ``okr_target_yield`` / ``okr_sizing_cap_pct`` read from
  ``app_settings``; defaults when unset.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.models.database import AppSetting, Position
from app.services.rules_config import RULES_CONFIG_KEY
from app.services.schwab_client import SchwabClient


# ---------------------------------------------------------------------------
# Helpers — seed positions directly via SQLAlchemy
# ---------------------------------------------------------------------------


def _seed_position(
    client,
    *,
    pos_id: str = "pos-sofi",
    ticker: str = "SOFI",
    shares: int = 100,
    broker_cost_basis: float = 3800.0,
    status: str = "open",
) -> str:
    """Insert a position row into the in-memory test DB.

    The ``client`` fixture wires the test session against the in-memory
    DB so we just grab one and add. Returns the position id.
    """
    from app.main import app
    from app.models.database import get_db

    override = app.dependency_overrides[get_db]
    db = next(override())
    try:
        pos = Position(
            id=pos_id,
            ticker=ticker,
            shares=shares,
            broker_cost_basis=broker_cost_basis,
            status=status,
            strategy="csp",
            opened_at="2024-01-01",
        )
        db.add(pos)
        db.commit()
    finally:
        db.close()
    return pos_id


def _seed_setting(client, key: str, value: str) -> None:
    from app.main import app
    from app.models.database import get_db

    override = app.dependency_overrides[get_db]
    db = next(override())
    try:
        db.add(AppSetting(key=key, value=value))
        db.commit()
    finally:
        db.close()


def _seed_rules_config(client, *, loss_review_threshold_pct: float) -> None:
    """Persist a ``rules_config`` row overriding the loss-review threshold.

    ``loss_review_threshold_pct`` is whole-percent (e.g. ``-5.0`` for −5%).
    Only the ``risk`` group is provided; :func:`load_rules_config` merges it
    onto the catalog defaults for every other group.
    """
    document = {
        "schema_version": 1,
        "risk": {"loss_review_threshold_pct": loss_review_threshold_pct},
    }
    _seed_setting(client, RULES_CONFIG_KEY, json.dumps(document))


def _quote(last_price: float) -> dict:
    """Return a Schwab-quote-shaped dict for the monkeypatch."""
    return {"lastPrice": last_price}


# ---------------------------------------------------------------------------
# 404
# ---------------------------------------------------------------------------


def test_recovery_plan_returns_404_when_position_missing(client):
    resp = client.post("/api/positions/nope-id/recovery-plan")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Position not found"}


# ---------------------------------------------------------------------------
# Not-applicable / not-flagged
# ---------------------------------------------------------------------------


def test_recovery_plan_not_applicable_for_zero_shares(client):
    _seed_position(client, shares=0)
    with patch.object(SchwabClient, "get_quote", return_value=_quote(8.0)):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["state"] == "not-applicable"
    assert payload["paths"] == []
    assert payload["recommendation"] is None


def test_recovery_plan_not_applicable_for_closed_position(client):
    _seed_position(client, status="closed", shares=100)
    with patch.object(SchwabClient, "get_quote", return_value=_quote(8.0)):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    assert resp.status_code == 200
    assert resp.json()["state"] == "not-applicable"


def test_recovery_plan_not_applicable_for_zero_basis(client):
    _seed_position(client, broker_cost_basis=0.0)
    with patch.object(SchwabClient, "get_quote", return_value=_quote(8.0)):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    assert resp.status_code == 200
    assert resp.json()["state"] == "not-applicable"


def test_recovery_plan_not_flagged_above_threshold(client):
    # Position with $3800 basis at $40 current price → $4000 notional, +$200
    # gain → does not breach either threshold.
    _seed_position(client, broker_cost_basis=3800.0, shares=100)
    with patch.object(SchwabClient, "get_quote", return_value=_quote(40.0)):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["state"] == "not-flagged"
    # Header summary IS rendered (per spec — frontend EmptyState wants the
    # ticker / shares / basis context).
    assert payload["position"]["ticker"] == "SOFI"


# ---------------------------------------------------------------------------
# Flag gate honors rules_config.risk.loss_review_threshold_pct (issue #235)
# ---------------------------------------------------------------------------


def test_recovery_flag_gate_uses_configured_loss_review_threshold(client):
    """The flag gate resolves its loss-review percentage from ``rules_config``.

    An −8% loser is between the retired hardcoded −5% constant and the
    default −15% rule. With a stored −5% rule it is ``populated``; with a
    stored −15% rule the same position is ``not-flagged``. This is the
    headline AC for issue #235.

    A $3,800 basis at $34.96 → $3,496 notional → −$304 / −8%.
    """
    # Stored -5% rule → -8% loser IS flagged.
    _seed_position(client, broker_cost_basis=3800.0, shares=100)
    _seed_rules_config(client, loss_review_threshold_pct=-5.0)
    with patch.object(SchwabClient, "get_quote", return_value=_quote(34.96)):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    assert resp.status_code == 200
    assert resp.json()["state"] == "populated"


def test_recovery_flag_gate_not_flagged_when_rule_stricter_than_loss(client):
    """A −8% loser is ``not-flagged`` when the stored rule is −15%."""
    _seed_position(client, broker_cost_basis=3800.0, shares=100)
    _seed_rules_config(client, loss_review_threshold_pct=-15.0)
    with patch.object(SchwabClient, "get_quote", return_value=_quote(34.96)):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    assert resp.status_code == 200
    assert resp.json()["state"] == "not-flagged"


def test_recovery_default_rules_not_flagged_between_5_and_15_pct(client):
    """With no ``rules_config`` row the default −15% rule applies.

    A −8% loser — between the retired −5% constant and the −15% default —
    is ``not-flagged``, proving the old hardcoded −5% behavior is gone.
    """
    _seed_position(client, broker_cost_basis=3800.0, shares=100)
    # No rules_config row seeded → catalog default -15%.
    with patch.object(SchwabClient, "get_quote", return_value=_quote(34.96)):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    assert resp.status_code == 200
    assert resp.json()["state"] == "not-flagged"


def test_recovery_default_rules_flagged_below_15_pct(client):
    """A −39% loser flags under the default −15% rule (conversion check).

    Pins the whole-percent → fraction conversion: −0.39 ``pl_pct`` vs the
    −15.0 whole-percent rule must compare as ``-0.39 <= -15.0 / 100``.
    A $3,800 basis at $23.18 → $2,318 notional → −39%.
    """
    _seed_position(client, broker_cost_basis=3800.0, shares=100)
    with patch.object(SchwabClient, "get_quote", return_value=_quote(23.18)):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    assert resp.status_code == 200
    assert resp.json()["state"] == "populated"


def test_recovery_dollar_secondary_trigger_still_fires(client):
    """The −$1,000 absolute trigger flags a shallow-percent large position.

    A $100,000 basis at $98.50 → $98,500 notional → −$1,500 / −1.5%. The
    percentage is far above any loss-review rule, but the retained dollar
    trigger still flags it — proving the secondary OR-trigger survives.
    """
    _seed_position(client, broker_cost_basis=100000.0, shares=1000)
    with patch.object(SchwabClient, "get_quote", return_value=_quote(98.50)):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    assert resp.status_code == 200
    assert resp.json()["state"] == "populated"


def test_recovery_assumptions_sizing_cap_source_is_trading_rules(client):
    """The Sizing-cap assumption row is attributed to Settings → Trading Rules.

    Strategy-preference and target-yield rows stay attributed to OKRs —
    those are genuine OKRs, not Trading Rules (issue #235).
    """
    _seed_position(client, broker_cost_basis=3800.0, shares=100)
    with patch.object(SchwabClient, "get_quote", return_value=_quote(8.0)):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["state"] == "populated"
    by_label = {a["label"]: a for a in payload["assumptions"]}
    assert by_label["Sizing cap (Average down)"]["source"] == (
        "Settings → Trading Rules"
    )
    # Genuine OKRs are untouched.
    assert by_label["Target yield (Sell & redeploy)"]["source"] == (
        "Settings → OKRs"
    )
    assert by_label["Strategy preference"]["source"] == "Settings → OKRs (V0.6)"


# ---------------------------------------------------------------------------
# Happy path — populated
# ---------------------------------------------------------------------------


def test_recovery_plan_populated_for_flagged_position(client):
    _seed_position(client, broker_cost_basis=3800.0, shares=100)
    _seed_setting(client, "okr_target_yield", "0.18")
    _seed_setting(client, "okr_sizing_cap_pct", "25.0")
    _seed_setting(client, "okr_total_capital", "20000.0")
    with patch.object(SchwabClient, "get_quote", return_value=_quote(8.0)):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["state"] == "populated"
    # 4 paths in canonical order.
    assert [p["path_id"] for p in payload["paths"]] == [
        "sell-redeploy",
        "wheel-cc",
        "average-down",
        "hold-monitor",
    ]
    # Recommendation present + tie_epsilon surfaced.
    assert payload["recommendation"] is not None
    assert payload["recommendation"]["tie_epsilon"] == 1.0
    # Assumptions panel has all 6 documented rows.
    labels = [a["label"] for a in payload["assumptions"]]
    assert labels == [
        "Premium rate (Wheel)",
        "Target yield (Sell & redeploy)",
        "Sizing cap (Average down)",
        "Strategy preference",
        "Current price",
        "Tax / wash sale",
    ]
    # Disclaimer always present at the top level.
    assert "fit recommendation" in payload["disclaimer"]


def test_recovery_plan_uses_okr_target_yield_from_settings(client):
    _seed_position(client, broker_cost_basis=3800.0)
    _seed_setting(client, "okr_target_yield", "0.20")
    with patch.object(SchwabClient, "get_quote", return_value=_quote(8.0)):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    payload = resp.json()
    assert payload["inputs"]["okr"]["target_yield"] == pytest.approx(0.20)
    # Sell-redeploy is eligible (target yield set).
    sell = next(p for p in payload["paths"] if p["path_id"] == "sell-redeploy")
    assert sell["eligibility"] == "eligible"


def test_recovery_plan_suppresses_sell_redeploy_when_target_yield_unset(client):
    _seed_position(client, broker_cost_basis=3800.0)
    # No target_yield seeded → defaults to None.
    with patch.object(SchwabClient, "get_quote", return_value=_quote(8.0)):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    payload = resp.json()
    sell = next(p for p in payload["paths"] if p["path_id"] == "sell-redeploy")
    assert sell["eligibility"] == "suppressed"
    assert sell["suppression_reason"] == "Target yield not configured"


def test_recovery_plan_uses_default_sizing_cap_when_unset(client):
    _seed_position(client, broker_cost_basis=3800.0)
    _seed_setting(client, "okr_target_yield", "0.18")
    # No sizing-cap seeded → default $5,000.
    with patch.object(SchwabClient, "get_quote", return_value=_quote(8.0)):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    payload = resp.json()
    assert payload["inputs"]["okr"]["sizing_cap_pct"] == pytest.approx(25.0)
    assert payload["inputs"]["okr"]["resolved_sizing_cap_dollars"] == pytest.approx(5000.0)


def test_recovery_plan_sell_redeploy_populated_after_target_yield_set(client):
    """Issue #207 AC3 — once a target yield is set, the Sell & redeploy path
    is eligible and its metrics compute (capital tied up + months to
    breakeven), un-suppressing the path the stopgap exists to unblock."""
    # broker_cost_basis 3800 vs a $8.00 quote on 100 shares → a realized loss,
    # so the breakeven horizon is a positive finite number.
    _seed_position(client, broker_cost_basis=3800.0)
    _seed_setting(client, "okr_target_yield", "0.12")
    with patch.object(SchwabClient, "get_quote", return_value=_quote(8.0)):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    payload = resp.json()

    sell = next(p for p in payload["paths"] if p["path_id"] == "sell-redeploy")
    assert sell["eligibility"] == "eligible"
    assert sell["suppression_reason"] is None
    # Capital tied up is computed (non-null) — not the suppressed-state blank.
    assert sell["capital_tied_up"] is not None
    assert sell["capital_tied_up"] >= 0
    # A positive realized loss + a positive yield → a finite, positive
    # expected months-to-breakeven (no longer the empty {best,expected,worst}).
    assert sell["months_to_breakeven"]["expected"] is not None
    assert sell["months_to_breakeven"]["expected"] > 0


# ---------------------------------------------------------------------------
# Quote failure → generic 500 + no str(e) leak
# ---------------------------------------------------------------------------


_UNIQUE_LEAK_NEEDLE = "ZZZ-do-not-leak-this-needle-ZZZ"


def test_recovery_plan_quote_failure_returns_generic_500(client):
    _seed_position(client, broker_cost_basis=3800.0)

    def _raise(_self, *_args, **_kwargs):
        raise RuntimeError(_UNIQUE_LEAK_NEEDLE)

    with patch.object(SchwabClient, "get_quote", _raise):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")

    assert resp.status_code == 500
    body = resp.json()
    assert body == {"detail": "Failed to build recovery plan. Please try again."}
    # CLAUDE.md compliance: no part of the underlying exception leaks into
    # the response body.
    assert _UNIQUE_LEAK_NEEDLE not in resp.text


def test_recovery_plan_treats_missing_last_price_as_quote_failure(client):
    _seed_position(client, broker_cost_basis=3800.0)
    with patch.object(SchwabClient, "get_quote", return_value={}):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    assert resp.status_code == 500
    assert resp.json() == {
        "detail": "Failed to build recovery plan. Please try again."
    }


# ---------------------------------------------------------------------------
# Response schema validation
# ---------------------------------------------------------------------------


def test_recovery_plan_response_matches_schema(client):
    _seed_position(client, broker_cost_basis=3800.0)
    _seed_setting(client, "okr_target_yield", "0.18")
    with patch.object(SchwabClient, "get_quote", return_value=_quote(8.0)):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    payload = resp.json()
    # Round-trip the response through the Pydantic schema to confirm it
    # validates without errors. If a field is missing or shaped wrong,
    # this raises ValidationError.
    from app.models.schemas import RecoveryPlanResponse

    RecoveryPlanResponse.model_validate(payload)


# ---------------------------------------------------------------------------
# Issue #234 (W-H) — RecoveryOkrInputs V1 contract
#
# The five sizing-cap fields (sizing_cap_pct, total_capital,
# resolved_sizing_cap_dollars, account_id_masked, capital_status) must
# round-trip through the populated response, and the Sizing-cap assumption
# row must render the §6.2 contract copy on both the ok path and the
# cap-unenforceable path.
# ---------------------------------------------------------------------------


def _patch_account_cache(monkeypatch, result):
    """Patch ``positions.get_cached_account_value`` to return ``result``.

    The router resolves the cache via its imported reference, so we patch
    the binding on :mod:`app.routers.positions` rather than the source
    module to ensure the override is honored regardless of import order.
    """
    from app.routers import positions as positions_router

    monkeypatch.setattr(
        positions_router,
        "get_cached_account_value",
        lambda db, sizing_cap_account=None: result,
    )


def test_okr_inputs_shape_ok_when_schwab_cache_populated(client, monkeypatch):
    """A fresh ok-status cache entry flows into the populated OKR inputs.

    Issue #234 V1 contract — the five sizing-cap fields are present and
    populated when the Schwab account-value cache holds a fresh ok entry.
    """
    from datetime import datetime, timezone

    from app.services.schwab_account_value import AccountValueResult

    _seed_position(client, broker_cost_basis=3800.0, shares=100)
    _patch_account_cache(
        monkeypatch,
        AccountValueResult(
            status="ok",
            total_capital=20000.0,
            account_id_masked="…4471",
            account_type="MARGIN",
            cached_at=datetime.now(timezone.utc),
        ),
    )
    with patch.object(SchwabClient, "get_quote", return_value=_quote(8.0)):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["state"] == "populated"
    okr = payload["inputs"]["okr"]
    assert okr["sizing_cap_pct"] == pytest.approx(25.0)
    assert okr["total_capital"] == pytest.approx(20000.0)
    assert okr["resolved_sizing_cap_dollars"] == pytest.approx(5000.0)
    assert okr["account_id_masked"] == "…4471"
    assert okr["capital_status"] == "ok"


def test_okr_inputs_shape_when_capital_status_error_returns_null_total_capital(
    client, monkeypatch
):
    """A cache result with ``status='error'`` surfaces as the unenforceable
    shape: ``capital_status='error'``, ``total_capital`` and
    ``resolved_sizing_cap_dollars`` both ``None``.
    """
    from datetime import datetime, timezone

    from app.services.schwab_account_value import AccountValueResult

    _seed_position(client, broker_cost_basis=3800.0, shares=100)
    _patch_account_cache(
        monkeypatch,
        AccountValueResult(
            status="error",
            total_capital=None,
            account_id_masked=None,
            cached_at=datetime.now(timezone.utc),
            error_detail="Schwab API error",
        ),
    )
    with patch.object(SchwabClient, "get_quote", return_value=_quote(8.0)):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["state"] == "populated"
    okr = payload["inputs"]["okr"]
    assert okr["capital_status"] == "error"
    assert okr["total_capital"] is None
    assert okr["resolved_sizing_cap_dollars"] is None
    # The percent is still surfaced — the row still tells the user what
    # the configured cap is even when the dollar ceiling is unenforceable.
    assert okr["sizing_cap_pct"] == pytest.approx(25.0)


def test_assumptions_panel_formats_resolved_dollars_when_ok(client, monkeypatch):
    """Happy path — the Sizing-cap assumption value renders the percent
    plus the resolved dollar ceiling: ``"25% (≈ $5,000)"``.
    """
    from datetime import datetime, timezone

    from app.services.schwab_account_value import AccountValueResult

    _seed_position(client, broker_cost_basis=3800.0, shares=100)
    _patch_account_cache(
        monkeypatch,
        AccountValueResult(
            status="ok",
            total_capital=20000.0,
            account_id_masked="…4471",
            account_type="MARGIN",
            cached_at=datetime.now(timezone.utc),
        ),
    )
    with patch.object(SchwabClient, "get_quote", return_value=_quote(8.0)):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    assert resp.status_code == 200
    payload = resp.json()
    by_label = {a["label"]: a for a in payload["assumptions"]}
    cap_row = by_label["Sizing cap (Average down)"]
    assert "25%" in cap_row["value"]
    assert "≈ $5,000" in cap_row["value"]


def test_assumptions_panel_formats_unavailable_when_capital_status_error(
    client, monkeypatch
):
    """Degraded path — the Sizing-cap row names the unenforceable state
    explicitly: ``"25% — Schwab account value unavailable"``.
    """
    from datetime import datetime, timezone

    from app.services.schwab_account_value import AccountValueResult

    _seed_position(client, broker_cost_basis=3800.0, shares=100)
    _patch_account_cache(
        monkeypatch,
        AccountValueResult(
            status="error",
            total_capital=None,
            account_id_masked=None,
            cached_at=datetime.now(timezone.utc),
            error_detail="Schwab API error",
        ),
    )
    with patch.object(SchwabClient, "get_quote", return_value=_quote(8.0)):
        resp = client.post("/api/positions/pos-sofi/recovery-plan")
    assert resp.status_code == 200
    payload = resp.json()
    by_label = {a["label"]: a for a in payload["assumptions"]}
    cap_row = by_label["Sizing cap (Average down)"]
    assert "25%" in cap_row["value"]
    assert "Schwab account value unavailable" in cap_row["value"]
