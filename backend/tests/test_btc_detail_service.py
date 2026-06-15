"""Unit tests for the buy-to-close detail service (issue #244).

Covers the only genuinely-new backend logic in ``btc_detail.py``:

- ``_build_economics`` — per-share scaling, signed P/L, null propagation
  when no live option mark is available.
- ``_position_label`` / ``_moneyness_label`` helpers.

The rule audit itself is reused from ``rule_monitor`` via ``derive_open_legs``
and is covered by ``test_rule_monitor.py`` / ``test_dashboard_legs.py`` — it
is not re-tested here. The full endpoint flow is covered by
``test_btc_detail_endpoint.py``.
"""

from __future__ import annotations
import pytest

from app.services.btc_detail import (
    SCENARIO_OFFSETS,
    _build_analysis,
    _build_economics,
    _moneyness_label,
    _position_label,
)


class TestBuildEconomics:
    @pytest.mark.unit
    def test_per_share_premium_scales_to_whole_position_credit(self):
        # A 1-contract $0.3834 per-share premium → $38.34 credit (×1×100).
        leg = {
            "premium": 0.3834,
            "quantity": 1,
            "current_mid": 0.1572,
            "profit_target_status": {"captured_pct": 0.59},
        }
        econ = _build_economics(leg)
        assert econ["credit_received"] == 38.34
        assert econ["cost_to_close"] == 15.72
        assert econ["pricing_source"] == "live"

    @pytest.mark.unit
    def test_credit_scales_by_contract_count(self):
        leg = {
            "premium": 2.25,
            "quantity": 3,
            "current_mid": 0.90,
            "profit_target_status": {"captured_pct": 0.60},
        }
        econ = _build_economics(leg)
        assert econ["credit_received"] == 675.0  # 2.25 × 3 × 100
        assert econ["cost_to_close"] == 270.0  # 0.90 × 3 × 100

    @pytest.mark.unit
    def test_est_pl_is_signed_credit_minus_cost(self):
        leg = {
            "premium": 2.25,
            "quantity": 1,
            "current_mid": 0.90,
            "profit_target_status": {"captured_pct": 0.60},
        }
        econ = _build_economics(leg)
        # 225 credit - 90 cost = +135 gain.
        assert econ["est_pl_if_closed"] == 135.0

    @pytest.mark.unit
    def test_est_pl_is_negative_when_cost_exceeds_credit(self):
        leg = {
            "premium": 1.00,
            "quantity": 1,
            "current_mid": 2.50,
            "profit_target_status": {"captured_pct": -1.5},
        }
        econ = _build_economics(leg)
        # 100 credit - 250 cost = -150 loss.
        assert econ["est_pl_if_closed"] == -150.0

    @pytest.mark.unit
    def test_captured_pct_is_lifted_not_recomputed(self):
        # The economics block lifts captured_pct verbatim from the % CAPT
        # signal so it agrees with the dashboard column by construction.
        leg = {
            "premium": 2.25,
            "quantity": 1,
            "current_mid": 0.90,
            "profit_target_status": {"captured_pct": 0.6042},
        }
        econ = _build_economics(leg)
        assert econ["captured_pct"] == 0.6042

    @pytest.mark.unit
    def test_no_mid_propagates_null_pricing_fields(self):
        # No live mark → cost/captured/est_pl/as_of all None, source unavailable.
        leg = {
            "premium": 2.25,
            "quantity": 1,
            "current_mid": None,
            "profit_target_status": {"captured_pct": None, "state": "unknown"},
        }
        econ = _build_economics(leg)
        assert econ["current_option_mid"] is None
        assert econ["cost_to_close"] is None
        assert econ["captured_pct"] is None
        assert econ["est_pl_if_closed"] is None
        assert econ["pricing_as_of"] is None
        assert econ["pricing_source"] == "unavailable"
        # credit_received is static — always real even with no live pricing.
        assert econ["credit_received"] == 225.0

    @pytest.mark.unit
    def test_pricing_as_of_is_set_when_mid_available(self):
        leg = {
            "premium": 2.25,
            "quantity": 1,
            "current_mid": 0.90,
            "profit_target_status": {"captured_pct": 0.60},
        }
        econ = _build_economics(leg)
        assert econ["pricing_as_of"] is not None
        assert "T" in econ["pricing_as_of"]  # ISO timestamp


class TestPositionLabel:
    @pytest.mark.unit
    def test_covered_call_label(self):
        assert _position_label({"ticker": "F", "strategy": "cc"}) == "F covered call"

    @pytest.mark.unit
    def test_cash_secured_put_label(self):
        assert (
            _position_label({"ticker": "SOFI", "strategy": "csp"})
            == "SOFI cash-secured put"
        )

    @pytest.mark.unit
    def test_wheel_label(self):
        assert _position_label({"ticker": "F", "strategy": "wheel"}) == "F wheel"

    @pytest.mark.unit
    def test_unknown_strategy_falls_back_to_position(self):
        assert _position_label({"ticker": "F", "strategy": "mystery"}) == "F position"


class TestMoneynessLabel:
    @pytest.mark.unit
    def test_reports_state_when_present(self):
        assert _moneyness_label({"moneyness": {"state": "ITM"}}) == "ITM"
        assert _moneyness_label({"moneyness": {"state": "OTM"}}) == "OTM"

    @pytest.mark.unit
    def test_unknown_when_no_moneyness(self):
        assert _moneyness_label({"moneyness": None}) == "Unknown"
        assert _moneyness_label({}) == "Unknown"


class TestBuildAnalysis:
    """BTC decision-math block (issue #319). Pure-function unit tests — no DB,
    no app, no Schwab. Computes from S (underlying), K (strike), O (mid), n.
    """

    @staticmethod
    def _call_leg(strike=14.5, mid=1.93, quantity=1):
        return {
            "type": "call",
            "strike": strike,
            "current_mid": mid,
            "quantity": quantity,
        }

    @pytest.mark.unit
    def test_intrinsic_extrinsic_split_itm_call(self):
        # F 14.5C, S=16.29, O=1.93 → intrinsic 1.79, extrinsic 0.14.
        a = _build_analysis(self._call_leg(), current_price=16.29)
        assert a["available"] is True
        assert a["intrinsic"] == 1.79
        assert a["extrinsic"] == 0.14

    @pytest.mark.unit
    def test_intrinsic_zero_for_otm_call(self):
        # S below strike → call intrinsic 0; extrinsic is the whole mid.
        a = _build_analysis(self._call_leg(strike=20.0, mid=0.50), current_price=16.29)
        assert a["intrinsic"] == 0.0
        assert a["extrinsic"] == 0.50

    @pytest.mark.unit
    def test_put_leg_returns_not_applicable_not_call_math(self):
        # BRIDGE EDIT (CodeRabbit triage, v1.7.0): this test previously asserted
        # put intrinsic/extrinsic (max(0, K-S)). The decision math is now
        # covered-call-only — put legs are gated to the not-applicable shape so
        # the call-specific breakeven/scenario equations never run for a put.
        # See test_put_leg_is_gated_out_of_cc_decision_math for the full assert.
        leg = {"type": "put", "strike": 20.0, "current_mid": 4.30, "quantity": 1}
        a = _build_analysis(leg, current_price=16.0)
        assert a["available"] is False
        assert a["intrinsic"] is None
        assert a["extrinsic"] is None

    @pytest.mark.unit
    def test_extrinsic_pct_of_mid_is_ratio(self):
        a = _build_analysis(self._call_leg(), current_price=16.29)
        # 0.14 / 1.93 ≈ 0.0725.
        assert a["extrinsic_pct_of_mid"] == pytest.approx(0.0725, abs=1e-4)

    @pytest.mark.unit
    def test_extrinsic_pct_null_when_mid_zero(self):
        a = _build_analysis(self._call_leg(strike=14.5, mid=0.0), current_price=16.29)
        # O == 0 → division guard yields null; breakeven K+0 still valid.
        assert a["extrinsic_pct_of_mid"] is None
        assert a["btc_breakeven"] == 14.5

    @pytest.mark.unit
    def test_negative_extrinsic_clamps_to_zero(self):
        # Stale mid below intrinsic (O=1.50 < intrinsic 1.79) → clamp to 0.
        a = _build_analysis(self._call_leg(mid=1.50), current_price=16.29)
        assert a["extrinsic"] == 0.0
        # Still available — a clamp is not a degrade (Decision 2).
        assert a["available"] is True

    @pytest.mark.unit
    def test_btc_breakeven_is_strike_plus_mid(self):
        a = _build_analysis(self._call_leg(), current_price=16.29)
        assert a["btc_breakeven"] == 16.43  # 14.5 + 1.93

    @pytest.mark.unit
    def test_breakeven_delta_is_signed_underlying_minus_breakeven(self):
        a = _build_analysis(self._call_leg(), current_price=16.29)
        # 16.29 - 16.43 = -0.14 (below breakeven).
        assert a["breakeven_delta"] == -0.14

    @pytest.mark.unit
    def test_scenario_grid_has_four_rows_one_down_one_flat_two_up(self):
        a = _build_analysis(self._call_leg(), current_price=16.29)
        labels = [s["label"] for s in a["scenarios"]]
        assert labels == ["−10%", "Flat", "+5%", "+10%"]
        assert len(a["scenarios"]) == 4

    @pytest.mark.unit
    def test_scenario_let_assign_is_strike_times_n_times_100(self):
        a = _build_analysis(self._call_leg(quantity=2), current_price=16.29)
        # 14.5 × 2 × 100 = 2900, constant across scenarios.
        for s in a["scenarios"]:
            assert s["let_assign"] == 2900.0

    @pytest.mark.unit
    def test_scenario_btc_and_hold_and_delta_math(self):
        a = _build_analysis(self._call_leg(), current_price=16.29)
        flat = next(s for s in a["scenarios"] if s["label"] == "Flat")
        # (16.29 - 1.93) × 1 × 100 = 1436.00; Δ = 1436 - 1450 = -14.
        assert flat["btc_and_hold"] == 1436.0
        assert flat["delta"] == -14.0

    @pytest.mark.unit
    def test_scenario_winner_btc_when_delta_positive(self):
        a = _build_analysis(self._call_leg(), current_price=16.29)
        up = next(s for s in a["scenarios"] if s["label"] == "+5%")
        assert up["delta"] > 0
        assert up["winner"] == "btc"

    @pytest.mark.unit
    def test_scenario_winner_tie_at_exact_breakeven(self):
        # Construct a leg whose +10% scenario lands exactly at breakeven.
        # Want S_e = K + O at offset +0.10 → S × 1.10 = K + O.
        # Pick S=10, O=1 → K+O = S×1.10 = 11 → K = 10. intrinsic max(0,10-10)=0,
        # extrinsic = 1, breakeven 11; +10% S_e = 11.0 → delta 0 → tie.
        leg = {"type": "call", "strike": 10.0, "current_mid": 1.0, "quantity": 1}
        a = _build_analysis(leg, current_price=10.0)
        up = next(s for s in a["scenarios"] if s["label"] == "+10%")
        assert up["delta"] == 0.0
        assert up["winner"] == "tie"

    @pytest.mark.unit
    def test_canonical_F_14_5C_fixture_matches_spec(self):
        a = _build_analysis(self._call_leg(), current_price=16.29)
        assert a["intrinsic"] == 1.79
        assert a["extrinsic"] == 0.14
        assert a["extrinsic_pct_of_mid"] == pytest.approx(0.0725, abs=1e-4)
        assert a["option_mid"] == 1.93
        assert a["btc_breakeven"] == 16.43
        assert a["underlying"] == 16.29
        assert a["breakeven_delta"] == -0.14
        deltas = {s["label"]: s["delta"] for s in a["scenarios"]}
        assert deltas["−10%"] == -177.0
        assert deltas["Flat"] == -14.0
        assert deltas["+5%"] == 67.0
        assert deltas["+10%"] == 149.0

    @pytest.mark.unit
    def test_available_false_when_no_mid_and_no_price(self):
        leg = {"type": "call", "strike": 14.5, "current_mid": None, "quantity": 1}
        a = _build_analysis(leg, current_price=None)
        assert a["available"] is False
        assert a["intrinsic"] is None
        assert a["scenarios"] == []

    @pytest.mark.unit
    def test_greek_null_intrinsic_only_when_mid_missing(self):
        # Underlying live, option mid missing → intrinsic only, rest null.
        leg = {"type": "call", "strike": 14.5, "current_mid": None, "quantity": 1}
        a = _build_analysis(leg, current_price=16.29)
        assert a["available"] is True
        assert a["intrinsic"] == 1.79
        assert a["extrinsic"] is None
        assert a["btc_breakeven"] is None
        assert a["breakeven_delta"] is None
        assert a["scenarios"] == []

    @pytest.mark.unit
    def test_does_not_raise_on_null_quantity(self):
        # Null quantity must default to 1 contract, not crash scenario scaling.
        leg = {"type": "call", "strike": 14.5, "current_mid": 1.93, "quantity": None}
        a = _build_analysis(leg, current_price=16.29)
        assert a["scenarios"][0]["let_assign"] == 1450.0  # 14.5 × 1 × 100

    @pytest.mark.unit
    def test_scenario_offsets_constant_is_frozen(self):
        assert SCENARIO_OFFSETS == [
            (-0.10, "−10%"),
            (0.0, "Flat"),
            (0.05, "+5%"),
            (0.10, "+10%"),
        ]

    @pytest.mark.unit
    def test_put_leg_is_gated_out_of_cc_decision_math(self):
        # v1.7.0 decision math is covered-call-only. A short put must NOT get
        # the call-specific breakeven / let-assign / BTC-and-hold equations —
        # those produce misleading numbers for a put. The service returns the
        # not-applicable (degraded) shape so the panel never shows call-math.
        leg = {"type": "put", "strike": 20.0, "current_mid": 4.30, "quantity": 1}
        a = _build_analysis(leg, current_price=16.0)
        assert a["available"] is False
        # No call-style figures — all decision-math fields are null/empty.
        assert a["intrinsic"] is None
        assert a["extrinsic"] is None
        assert a["btc_breakeven"] is None
        assert a["breakeven_delta"] is None
        assert a["scenarios"] == []

    @pytest.mark.unit
    def test_put_leg_gate_matches_full_degrade_shape(self):
        # The put gate reuses the exact full-degrade shape — no new fields, so
        # no schema change / openapi regen is required.
        from app.services.btc_detail import _degraded_analysis

        put_leg = {"type": "put", "strike": 20.0, "current_mid": 4.30, "quantity": 1}
        assert _build_analysis(put_leg, current_price=16.0) == _degraded_analysis()
