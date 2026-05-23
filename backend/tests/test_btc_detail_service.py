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
