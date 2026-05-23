"""Tests for the rejection-relax preview service + endpoint (issue #258).

Coverage maps directly to the V1 contract relax recipes locked in the
v1.0.8 plan. The tests exercise the service via the FastAPI endpoint so
they incidentally also assert the router wiring + Pydantic shapes.

Test plan (~12 cases):

1. Each of 7 relaxable rules: "would recover N" with a known fixture.
2. Each of 2 binary rules: 400 with the canonical not-relaxable message.
3. Empty ``rejected`` → 200, ``recovered_count: 0``, ``recovered_strikes: []``.
4. Strike with TWO rejection reasons including the relaxed rule → does
   NOT recover (still failing the other rule).
5. Strike with ONLY the relaxed rule whose value is *still* below the
   relaxed threshold → does NOT recover.
"""

from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _payload(rule: str, rejected: list[dict]) -> dict:
    """Build the request body the endpoint expects."""
    return {
        "ticker": "F",
        "strategy": "covered_call",
        "rule": rule,
        "rejected": rejected,
    }


def _post(client, body: dict):
    return client.post("/api/options/scan/relax", json=body)


# ---------------------------------------------------------------------------
# Relaxable rule recoveries — one fixture per rule
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_relax_delta_widens_band_and_recovers(client):
    """``delta_out_of_range`` — band widens ±0.05; |0.38| is now inside
    [0.15, 0.40], so the strike recovers.
    """
    rejected = [
        {
            "strike": 13.5,
            "expiration": "2026-06-26",
            "rejection_reasons": [
                "delta_out_of_range: |0.38| not in [0.20, 0.35]"
            ],
            "human_reasons": [],
        },
        # A strike at 0.50 is still outside even after widening — does NOT
        # recover.
        {
            "strike": 14.0,
            "expiration": "2026-06-26",
            "rejection_reasons": [
                "delta_out_of_range: |0.50| not in [0.20, 0.35]"
            ],
            "human_reasons": [],
        },
    ]
    res = _post(client, _payload("delta_out_of_range", rejected))
    assert res.status_code == 200
    data = res.json()
    assert data["rule"] == "delta_out_of_range"
    assert data["recovered_count"] == 1
    assert data["recovered_strikes"] == [
        {"strike": 13.5, "expiration": "2026-06-26"}
    ]


@pytest.mark.integration
def test_relax_low_oi_halves_floor_and_recovers(client):
    """``low_open_interest`` — floor ÷ 2; OI=25 vs min=50 recovers when
    new floor = 25.
    """
    rejected = [
        # OI=30 vs original floor=50 → new floor=25 → 30 >= 25 → recovers.
        {
            "strike": 14.0,
            "expiration": "2026-06-26",
            "rejection_reasons": ["low_open_interest: 30 < 50"],
            "human_reasons": [],
        },
        # OI=10 vs original floor=50 → new floor=25 → 10 < 25 → still fails.
        {
            "strike": 14.5,
            "expiration": "2026-06-26",
            "rejection_reasons": ["low_open_interest: 10 < 50"],
            "human_reasons": [],
        },
    ]
    res = _post(client, _payload("low_open_interest", rejected))
    assert res.status_code == 200
    data = res.json()
    assert data["recovered_count"] == 1
    assert data["recovered_strikes"][0]["strike"] == 14.0


@pytest.mark.integration
def test_relax_wide_spread_caps_x_1_5_and_recovers(client):
    """``wide_bid_ask_spread`` — cap × 1.5; 12% vs cap=10% recovers when
    new cap=15%.
    """
    rejected = [
        # spread 12% vs cap 10% → relaxed cap 15% → 12 <= 15 → recovers.
        {
            "strike": 5.0,
            "expiration": "2026-06-26",
            "rejection_reasons": ["wide_bid_ask_spread: 12.0% > 10.0%"],
            "human_reasons": [],
        },
        # spread 22% vs cap 10% → relaxed cap 15% → 22 > 15 → still fails.
        {
            "strike": 6.0,
            "expiration": "2026-06-26",
            "rejection_reasons": ["wide_bid_ask_spread: 22.0% > 10.0%"],
            "human_reasons": [],
        },
    ]
    res = _post(client, _payload("wide_bid_ask_spread", rejected))
    assert res.status_code == 200
    data = res.json()
    assert data["recovered_count"] == 1
    assert data["recovered_strikes"][0]["strike"] == 5.0


@pytest.mark.integration
def test_relax_fails_10pct_drops_required_by_5pp_and_recovers(client):
    """``fails_10pct_rule`` — required distance − 5pp; strike at 6%
    above basis vs 10% rule → new threshold 5% → 6 >= 5 → recovers.
    """
    rejected = [
        # 6% above basis vs requires 10% → relaxed=5% → 6 >= 5 → recovers.
        {
            "strike": 14.0,
            "expiration": "2026-06-26",
            "rejection_reasons": [
                "fails_10pct_rule: strike 6.0% above basis, requires 10.0%"
            ],
            "human_reasons": [],
        },
        # 3% vs requires 10% → relaxed=5% → 3 < 5 → still fails.
        {
            "strike": 13.5,
            "expiration": "2026-06-26",
            "rejection_reasons": [
                "fails_10pct_rule: strike 3.0% above basis, requires 10.0%"
            ],
            "human_reasons": [],
        },
    ]
    res = _post(client, _payload("fails_10pct_rule", rejected))
    assert res.status_code == 200
    data = res.json()
    assert data["recovered_count"] == 1
    assert data["recovered_strikes"][0]["strike"] == 14.0


@pytest.mark.integration
def test_relax_below_cost_basis_drops_floor_and_recovers(client):
    """``below_cost_basis`` — floor − 5pp (≈ floor × 0.95 at the default
    0% baseline); strike $12.80 vs $13.21 floor → relaxed floor ≈ $12.55
    → 12.80 >= 12.55 → recovers.
    """
    rejected = [
        {
            "strike": 12.80,
            "expiration": "2026-06-26",
            "rejection_reasons": ["below_cost_basis: strike $12.80 < floor $13.21"],
            "human_reasons": [],
        },
        # Strike $10 is still below 0.95 * 13.21 ≈ 12.55 → still fails.
        {
            "strike": 10.0,
            "expiration": "2026-06-26",
            "rejection_reasons": ["below_cost_basis: strike $10.00 < floor $13.21"],
            "human_reasons": [],
        },
    ]
    res = _post(client, _payload("below_cost_basis", rejected))
    assert res.status_code == 200
    data = res.json()
    assert data["recovered_count"] == 1
    assert data["recovered_strikes"][0]["strike"] == 12.80


@pytest.mark.integration
def test_relax_return_below_drops_target_by_1pp_and_recovers(client):
    """``return_below_target`` — target − 1pp; 1.5% vs 2% target →
    relaxed 1% → 1.5 >= 1 → recovers.
    """
    rejected = [
        {
            "strike": 14.0,
            "expiration": "2026-06-26",
            "rejection_reasons": ["return_below_target: 1.5% < 2.0%"],
            "human_reasons": [],
        },
        # 0.5% vs 2.0% → relaxed 1.0% → 0.5 < 1.0 → still fails.
        {
            "strike": 15.0,
            "expiration": "2026-06-26",
            "rejection_reasons": ["return_below_target: 0.5% < 2.0%"],
            "human_reasons": [],
        },
    ]
    res = _post(client, _payload("return_below_target", rejected))
    assert res.status_code == 200
    data = res.json()
    assert data["recovered_count"] == 1
    assert data["recovered_strikes"][0]["strike"] == 14.0


@pytest.mark.integration
def test_relax_return_above_lifts_cap_by_50pp_and_recovers(client):
    """``return_above_cap`` — cap + 50pp; 120% vs 100% cap → relaxed 150%
    → 120 <= 150 → recovers. Threshold text reads the cap inline (no
    persisted config field today).
    """
    rejected = [
        {
            "strike": 8.0,
            "expiration": "2026-06-26",
            "rejection_reasons": ["return_above_cap: 120.0% > 100.0%"],
            "human_reasons": [],
        },
        # 200% vs 100% → relaxed 150% → 200 > 150 → still fails.
        {
            "strike": 9.0,
            "expiration": "2026-06-26",
            "rejection_reasons": ["return_above_cap: 200.0% > 100.0%"],
            "human_reasons": [],
        },
    ]
    res = _post(client, _payload("return_above_cap", rejected))
    assert res.status_code == 200
    data = res.json()
    assert data["recovered_count"] == 1
    assert data["recovered_strikes"][0]["strike"] == 8.0
    # The cap is parsed out of the rejection text — assert both threshold
    # texts are populated (not the "—" fallback).
    assert data["current_threshold_text"] != "—"
    assert data["relaxed_threshold_text"] != "—"


# ---------------------------------------------------------------------------
# Binary / unknown rules — 400 with the canonical generic detail
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_relax_itm_put_is_not_relaxable_400(client):
    """``itm_put`` is binary — endpoint returns 400 with the generic detail."""
    rejected = [
        {
            "strike": 15.0,
            "expiration": "2026-06-26",
            "rejection_reasons": ["itm_put: strike $15.00 > price $13.50"],
            "human_reasons": [],
        }
    ]
    res = _post(client, _payload("itm_put", rejected))
    assert res.status_code == 400
    assert res.json()["detail"] == "rule not relaxable"


@pytest.mark.integration
def test_relax_zero_bid_is_not_relaxable_400(client):
    """``zero_bid`` is binary — endpoint returns 400 with the generic detail."""
    rejected = [
        {
            "strike": 15.0,
            "expiration": "2026-06-26",
            "rejection_reasons": ["zero_bid"],
            "human_reasons": [],
        }
    ]
    res = _post(client, _payload("zero_bid", rejected))
    assert res.status_code == 400
    assert res.json()["detail"] == "rule not relaxable"


@pytest.mark.integration
def test_relax_unknown_rule_is_not_relaxable_400(client):
    """An unknown rule family is treated the same as a binary rule.

    Defends the V1 contract against a stray frontend refactor that emits a
    typo'd rule name.
    """
    res = _post(client, _payload("not_a_real_rule", []))
    assert res.status_code == 400
    assert res.json()["detail"] == "rule not relaxable"


# ---------------------------------------------------------------------------
# Boundary cases — empty payload, multi-reason rows
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_relax_empty_rejected_returns_zero_count(client):
    """An empty ``rejected`` payload still validates and returns a 200
    with ``recovered_count: 0`` and an empty strike list.
    """
    res = _post(client, _payload("low_open_interest", []))
    assert res.status_code == 200
    data = res.json()
    assert data["rule"] == "low_open_interest"
    assert data["recovered_count"] == 0
    assert data["recovered_strikes"] == []
    # Threshold text is still populated from rules_config.
    assert data["current_threshold_text"] != ""
    assert data["relaxed_threshold_text"] != ""


@pytest.mark.integration
def test_relax_multi_reason_strike_does_not_recover(client):
    """A strike failing TWO rules — including the relaxed one — does NOT
    recover. Relaxing one rule does not free a strike still failing the
    other.
    """
    rejected = [
        # Single-reason strike that DOES recover under low_open_interest
        # relaxation.
        {
            "strike": 14.0,
            "expiration": "2026-06-26",
            "rejection_reasons": ["low_open_interest: 30 < 50"],
            "human_reasons": [],
        },
        # Multi-reason strike — OI=30 would pass under the relaxed floor
        # (25), but it is *also* failing delta_out_of_range. Relaxing OI
        # alone does NOT free it.
        {
            "strike": 13.5,
            "expiration": "2026-06-26",
            "rejection_reasons": [
                "low_open_interest: 30 < 50",
                "delta_out_of_range: |0.42| not in [0.20, 0.35]",
            ],
            "human_reasons": [],
        },
    ]
    res = _post(client, _payload("low_open_interest", rejected))
    assert res.status_code == 200
    data = res.json()
    assert data["recovered_count"] == 1
    assert data["recovered_strikes"] == [
        {"strike": 14.0, "expiration": "2026-06-26"}
    ]


@pytest.mark.integration
def test_relax_single_reason_still_failing_does_not_recover(client):
    """A strike whose ONLY rejection is the relaxed rule but whose value
    is still below the relaxed threshold does NOT recover.

    Covers the negative branch of the single-reason recovery condition —
    the relax math itself has to clear the strike, not just its
    rejection-reason set.
    """
    rejected = [
        # OI=5 vs original floor=50 → relaxed floor=25 → 5 < 25 → still fails.
        {
            "strike": 14.5,
            "expiration": "2026-06-26",
            "rejection_reasons": ["low_open_interest: 5 < 50"],
            "human_reasons": [],
        },
    ]
    res = _post(client, _payload("low_open_interest", rejected))
    assert res.status_code == 200
    assert res.json()["recovered_count"] == 0


# ---------------------------------------------------------------------------
# Threshold-text format — anchors the locked V1 contract strings
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_relax_low_oi_threshold_text_uses_rules_config(client):
    """``current_threshold_text`` reads from the persisted rules_config;
    the default ``min_open_interest`` is 500 → relaxed = 250.
    """
    res = _post(client, _payload("low_open_interest", []))
    assert res.status_code == 200
    data = res.json()
    assert data["current_threshold_text"] == "500"
    assert data["relaxed_threshold_text"] == "250"
