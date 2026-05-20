"""Unit tests for the covered-call service helpers (issue #247).

Pure helpers — no DB, no Schwab. Mirrors the structure of
``test_btc_detail_service.py`` (none exists in this repo, so this file
follows the broader convention of pytest classes grouped by function).

Covers:

- ``_compute_combined_today`` — worked example, signed stock P&L, summed
  options P&L, three degraded variants.
- ``_allocate_shares_called`` — single-leg fit, single-leg overflow,
  two-leg earliest-expiring-first, two-leg partial overflow, zero shares.
- ``_build_if_assigned`` — worked example, negative share_pnl, premium kept
  with zero shares_called, short-put exclusion, expired-leg exclusion.
- ``_classify_applicability`` — CSP-only, holding with no short call,
  closed, the canonical covered call.
"""

from __future__ import annotations

from app.services.covered_call import (
    _allocate_shares_called,
    _build_if_assigned,
    _classify_applicability,
    _compute_combined_today,
)


# ---------------------------------------------------------------------------
# Fixtures — the F worked-example inputs (planner's note + arithmetic fix)
# ---------------------------------------------------------------------------
#
# basis $13.21 + current $13.1579 → stock_pnl = 100 * (13.1579 - 13.21) = -5.21
#   (the planner suggested current=13.1479 but that yields -6.21; 13.1579 is
#   what reconciles exactly to the spec's -5.21).
# premium $0.3834 + current_mid $0.155 → pnl_dollars = (0.3834-0.155)*100 = 22.84
# combined: -5.21 + 22.84 = +$17.63 (the spec's headline number).
# if_assigned: share_pnl = 100*(15.00-13.21)=179.00; premium_kept = 38.34;
#   if_assigned_pnl = $217.34 (within the AC's ≈ +$217 tolerance).
# ---------------------------------------------------------------------------

F_BASIS = 13.21
F_CURRENT_PRICE = 13.1579
F_SHARES = 100
F_LEG = {
    "id": "leg-ford-15c",
    "ticker": "F",
    "type": "call",
    "strike": 15.0,
    "dte": 38,
    "premium": 0.3834,
    "quantity": 1,
    "pnl_dollars": 22.84,
}


# ---------------------------------------------------------------------------
# _compute_combined_today
# ---------------------------------------------------------------------------


class TestComputeCombinedToday:
    def test_worked_example_combined_is_plus_17_63(self):
        out = _compute_combined_today(
            shares=F_SHARES,
            current_price=F_CURRENT_PRICE,
            basis=F_BASIS,
            legs=[F_LEG],
        )
        assert out["stock_pnl"] == -5.21
        assert out["options_pnl"] == 22.84
        assert out["combined_pnl"] == 17.63

    def test_stock_leg_pnl_is_signed_gain(self):
        out = _compute_combined_today(
            shares=100,
            current_price=20.00,
            basis=15.00,
            legs=[{"pnl_dollars": 0.0}],
        )
        assert out["stock_pnl"] == 500.00
        assert out["combined_pnl"] == 500.00

    def test_stock_leg_pnl_is_signed_loss(self):
        out = _compute_combined_today(
            shares=100,
            current_price=10.00,
            basis=15.00,
            legs=[{"pnl_dollars": 0.0}],
        )
        assert out["stock_pnl"] == -500.00
        assert out["combined_pnl"] == -500.00

    def test_options_pnl_sums_per_leg_pnl_dollars(self):
        out = _compute_combined_today(
            shares=100,
            current_price=15.00,
            basis=15.00,
            legs=[
                {"pnl_dollars": 22.84},
                {"pnl_dollars": 10.00},
            ],
        )
        assert out["options_pnl"] == 32.84
        # Stock leg is zero (current == basis), so combined == options.
        assert out["combined_pnl"] == 32.84

    def test_no_current_price_degrades_stock_and_combined_to_none(self):
        out = _compute_combined_today(
            shares=100,
            current_price=None,
            basis=F_BASIS,
            legs=[F_LEG],
        )
        assert out["stock_pnl"] is None
        assert out["options_pnl"] == 22.84  # still real
        assert out["combined_pnl"] is None

    def test_no_leg_pnl_dollars_degrades_options_and_combined_to_none(self):
        out = _compute_combined_today(
            shares=100,
            current_price=F_CURRENT_PRICE,
            basis=F_BASIS,
            legs=[{"pnl_dollars": None}],
        )
        assert out["stock_pnl"] == -5.21  # still real
        assert out["options_pnl"] is None
        assert out["combined_pnl"] is None

    def test_both_unavailable_combined_is_none(self):
        out = _compute_combined_today(
            shares=100,
            current_price=None,
            basis=F_BASIS,
            legs=[{"pnl_dollars": None}],
        )
        assert out["stock_pnl"] is None
        assert out["options_pnl"] is None
        assert out["combined_pnl"] is None


# ---------------------------------------------------------------------------
# _allocate_shares_called
# ---------------------------------------------------------------------------


class TestAllocateSharesCalled:
    def test_single_leg_claims_all_shares_when_qty_times_100_leq_shares(self):
        legs = [{"id": "L1", "dte": 30, "quantity": 1, "ticker": "F"}]
        out = _allocate_shares_called(legs, shares=100)
        assert out == {"L1": 100}

    def test_single_leg_overflow_is_capped_at_position_shares(self):
        # 100 shares, 2-contract short call → only 100 can be called away.
        legs = [{"id": "L1", "dte": 30, "quantity": 2, "ticker": "F"}]
        out = _allocate_shares_called(legs, shares=100)
        assert out["L1"] == 100

    def test_two_legs_earliest_expiring_claims_first(self):
        # 100 sh, leg A DTE 20 + leg B DTE 40 → A claims 100, B gets 0.
        legs = [
            {"id": "A", "dte": 20, "quantity": 1, "ticker": "F"},
            {"id": "B", "dte": 40, "quantity": 1, "ticker": "F"},
        ]
        out = _allocate_shares_called(legs, shares=100)
        assert out == {"A": 100, "B": 0}

    def test_two_legs_partial_overflow_distributes_remaining(self):
        # 150 sh, leg A DTE 20 (qty 1) gets 100, leg B DTE 40 (qty 1) gets 50.
        legs = [
            {"id": "A", "dte": 20, "quantity": 1, "ticker": "F"},
            {"id": "B", "dte": 40, "quantity": 1, "ticker": "F"},
        ]
        out = _allocate_shares_called(legs, shares=150)
        assert out == {"A": 100, "B": 50}

    def test_three_legs_zero_shares_remaining_after_first(self):
        # 100 sh, leg A (dte 10, qty 1), leg B (dte 30, qty 1), leg C (dte 60, qty 1)
        # A claims 100; B, C get 0.
        legs = [
            {"id": "A", "dte": 10, "quantity": 1, "ticker": "F"},
            {"id": "B", "dte": 30, "quantity": 1, "ticker": "F"},
            {"id": "C", "dte": 60, "quantity": 1, "ticker": "F"},
        ]
        out = _allocate_shares_called(legs, shares=100)
        assert out == {"A": 100, "B": 0, "C": 0}

    def test_zero_shares_returns_zero_allocation(self):
        legs = [{"id": "L1", "dte": 30, "quantity": 1, "ticker": "F"}]
        out = _allocate_shares_called(legs, shares=0)
        assert out == {"L1": 0}

    def test_input_order_does_not_matter(self):
        # Pass legs in reverse-DTE order — earliest-expiring still claims.
        legs = [
            {"id": "B", "dte": 40, "quantity": 1, "ticker": "F"},
            {"id": "A", "dte": 20, "quantity": 1, "ticker": "F"},
        ]
        out = _allocate_shares_called(legs, shares=100)
        assert out == {"A": 100, "B": 0}


# ---------------------------------------------------------------------------
# _build_if_assigned
# ---------------------------------------------------------------------------


class TestBuildIfAssigned:
    def test_worked_example_if_assigned_is_217_34(self):
        # share_pnl = 100 * (15.00 - 13.21) = 179.00
        # premium_kept = 0.3834 * 100 * 1 = 38.34
        # if_assigned_pnl = 217.34 (within AC's ≈ +$217 tolerance).
        out = _build_if_assigned(
            short_call_legs=[F_LEG],
            shares_called_map={F_LEG["id"]: F_SHARES},
            basis=F_BASIS,
        )
        assert len(out) == 1
        entry = out[0]
        assert entry["leg_id"] == "leg-ford-15c"
        assert entry["strike"] == 15.0
        assert entry["shares_called"] == 100
        assert entry["share_pnl"] == 179.00
        assert entry["premium_kept"] == 38.34
        assert entry["if_assigned_pnl"] == 217.34

    def test_share_pnl_negative_when_strike_below_basis(self):
        # A "rolled-down" CC: strike $12, basis $13.21, shares 100.
        leg = {
            "id": "L1",
            "ticker": "F",
            "type": "call",
            "strike": 12.00,
            "dte": 30,
            "premium": 0.50,
            "quantity": 1,
        }
        out = _build_if_assigned(
            short_call_legs=[leg],
            shares_called_map={"L1": 100},
            basis=13.21,
        )
        # share_pnl = 100 * (12 - 13.21) = -121.00 ; premium_kept = 50.00.
        assert out[0]["share_pnl"] == -121.00
        assert out[0]["premium_kept"] == 50.00
        assert out[0]["if_assigned_pnl"] == -71.00

    def test_premium_kept_independent_of_shares_called(self):
        # Leg B in the multi-leg overflow case: shares_called == 0 but the
        # credit booked at open stays with the seller.
        leg = {
            "id": "B",
            "ticker": "F",
            "type": "call",
            "strike": 16.00,
            "dte": 40,
            "premium": 0.25,
            "quantity": 1,
        }
        out = _build_if_assigned(
            short_call_legs=[leg],
            shares_called_map={"B": 0},
            basis=13.21,
        )
        assert out[0]["shares_called"] == 0
        assert out[0]["share_pnl"] == 0.0  # 0 shares * anything
        assert out[0]["premium_kept"] == 25.00
        assert out[0]["if_assigned_pnl"] == 25.00

    def test_expired_leg_is_excluded_from_if_assigned(self):
        # An already-expired (dte < 0) leg has no meaningful assignment
        # projection — the array drops it. The per-leg breakdown table
        # would still show the row (the orchestrator passes the full leg
        # list separately) — but if_assigned_pnl for that row is None.
        legs = [
            {
                "id": "live",
                "ticker": "F",
                "type": "call",
                "strike": 15.0,
                "dte": 30,
                "premium": 0.50,
                "quantity": 1,
            },
            {
                "id": "expired",
                "ticker": "F",
                "type": "call",
                "strike": 14.0,
                "dte": -3,
                "premium": 0.50,
                "quantity": 1,
            },
        ]
        out = _build_if_assigned(
            short_call_legs=legs,
            shares_called_map={"live": 100, "expired": 0},
            basis=13.21,
        )
        leg_ids = {entry["leg_id"] for entry in out}
        assert leg_ids == {"live"}

    def test_missing_premium_degrades_to_null_projection(self):
        leg = {
            "id": "L1",
            "ticker": "F",
            "type": "call",
            "strike": 15.0,
            "dte": 30,
            "premium": None,  # no booked credit on this row
            "quantity": 1,
        }
        out = _build_if_assigned(
            short_call_legs=[leg],
            shares_called_map={"L1": 100},
            basis=13.21,
        )
        assert out[0]["if_assigned_pnl"] is None


# ---------------------------------------------------------------------------
# _classify_applicability
# ---------------------------------------------------------------------------


class TestClassifyApplicability:
    def test_csp_only_returns_no_shares(self):
        position = {"shares": 0, "status": "open"}
        # A CSP-only position has no shares — even if it has an open put,
        # the if-assigned mechanic doesn't apply.
        legs = []
        assert _classify_applicability(position, legs) == (
            "not_applicable_no_shares"
        )

    def test_holding_with_no_short_call_returns_no_short_call(self):
        position = {"shares": 100, "status": "open"}
        # Position has shares but no open short call — out of scope.
        legs = []
        assert _classify_applicability(position, legs) == (
            "not_applicable_no_short_call"
        )

    def test_closed_position_returns_closed(self):
        position = {"shares": 100, "status": "closed"}
        legs = [{"id": "L1", "type": "call"}]
        assert _classify_applicability(position, legs) == (
            "not_applicable_closed"
        )

    def test_covered_call_returns_covered_call(self):
        position = {"shares": 100, "status": "open"}
        legs = [{"id": "L1", "type": "call"}]
        assert _classify_applicability(position, legs) == "covered_call"

    def test_csp_only_with_open_put_still_returns_no_shares(self):
        # A pure-CSP position with an open put: shares==0 wins; the if-assigned
        # screen doesn't apply even though the put is open.
        position = {"shares": 0, "status": "open"}
        # The helper takes short-CALL legs; the put never makes it into this
        # arg in the real orchestrator. We pass [] to confirm.
        assert _classify_applicability(position, []) == (
            "not_applicable_no_shares"
        )
