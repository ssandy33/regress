"""Unit tests for the Recovery Plan path engine.

The engine is a pure function. These tests exercise the math per path
against fixed inputs (no DB, no HTTP), the suppression branches
(target-yield missing, sizing-cap exceeded), and the determinism /
external-call guarantees from the AC.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app.services.recovery_engine import (
    WHEEL_BE_MULTIPLIERS,
    WHEEL_MONTHLY_PREMIUM_PCT,
    canonical_path_order,
    compute_recovery_paths,
)


# ---------------------------------------------------------------------------
# Fixtures — the canonical SOFI position used across most tests.
# ---------------------------------------------------------------------------


def _sofi_position(**overrides) -> dict:
    """Canonical SOFI fixture from the design spec (100 sh, basis $38)."""
    base = {
        "id": "pos-sofi",
        "ticker": "SOFI",
        "shares": 100,
        "adjusted_cost_basis": 3800.0,
        "broker_cost_basis": 3800.0,
        "status": "open",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Canonical shape + ordering
# ---------------------------------------------------------------------------


class TestCanonicalShape:
    def test_returns_four_paths_in_canonical_order(self):
        paths = compute_recovery_paths(
            position=_sofi_position(),
            current_price=8.0,
            target_yield=0.18,
            sizing_cap_dollars=5000.0,
        )
        assert [p["path_id"] for p in paths] == list(canonical_path_order())
        assert len(paths) == 4

    def test_every_path_has_required_fields(self):
        paths = compute_recovery_paths(
            position=_sofi_position(),
            current_price=8.0,
            target_yield=0.18,
            sizing_cap_dollars=5000.0,
        )
        for p in paths:
            assert set(p.keys()) >= {
                "path_id",
                "label",
                "eligibility",
                "suppression_reason",
                "capital_tied_up",
                "months_to_breakeven",
                "opportunity_cost_vs_baseline",
                "assumptions",
                "narration",
            }
            assert p["eligibility"] in {"eligible", "suppressed"}
            assert set(p["months_to_breakeven"].keys()) == {
                "best",
                "expected",
                "worst",
            }
            # narration is reserved for V0.6; engine emits None.
            assert p["narration"] is None
            # assumptions must always be a non-empty list of strings so the
            # frontend has at least one row to render per path.
            assert isinstance(p["assumptions"], list)
            assert all(isinstance(s, str) for s in p["assumptions"])

    def test_no_irr_field_anywhere(self):
        paths = compute_recovery_paths(
            position=_sofi_position(),
            current_price=8.0,
            target_yield=0.18,
            sizing_cap_dollars=5000.0,
        )
        for p in paths:
            assert "irr" not in p, f"path {p['path_id']} leaked stale 'irr' field"


# ---------------------------------------------------------------------------
# sell-redeploy
# ---------------------------------------------------------------------------


class TestSellRedeployPath:
    def test_suppressed_when_target_yield_missing(self):
        paths = compute_recovery_paths(
            position=_sofi_position(),
            current_price=8.0,
            target_yield=None,
            sizing_cap_dollars=5000.0,
        )
        sell = next(p for p in paths if p["path_id"] == "sell-redeploy")
        assert sell["eligibility"] == "suppressed"
        assert sell["suppression_reason"] == "Target yield not configured"
        assert sell["capital_tied_up"] is None
        assert sell["opportunity_cost_vs_baseline"] is None

    def test_eligible_when_target_yield_set(self):
        paths = compute_recovery_paths(
            position=_sofi_position(),
            current_price=8.0,
            target_yield=0.18,
            sizing_cap_dollars=5000.0,
        )
        sell = next(p for p in paths if p["path_id"] == "sell-redeploy")
        assert sell["eligibility"] == "eligible"
        assert sell["suppression_reason"] is None
        # freed_capital = 100 sh * $8 = $800
        assert sell["capital_tied_up"] == pytest.approx(800.0)
        # baseline path → opportunity cost is exactly zero
        assert sell["opportunity_cost_vs_baseline"] == 0.0
        # realized_loss = $3800 - $800 = $3000; annual_return = $800 * 0.18 = $144
        # months_expected = (3000 / 144) * 12 = 250
        assert sell["months_to_breakeven"]["expected"] == pytest.approx(250.0)
        assert sell["months_to_breakeven"]["best"] == pytest.approx(200.0)
        assert sell["months_to_breakeven"]["worst"] == pytest.approx(325.0)


# ---------------------------------------------------------------------------
# wheel-cc
# ---------------------------------------------------------------------------


class TestWheelCcPath:
    def test_premium_pct_in_assumptions(self):
        paths = compute_recovery_paths(
            position=_sofi_position(),
            current_price=8.0,
            target_yield=0.18,
            sizing_cap_dollars=5000.0,
        )
        wheel = next(p for p in paths if p["path_id"] == "wheel-cc")
        # The exact "1.5%/month" copy must be in the assumption list — the
        # frontend pattern-matches on this string.
        assumption_blob = " ".join(wheel["assumptions"])
        pct_str = f"{WHEEL_MONTHLY_PREMIUM_PCT * 100:.1f}%/month"
        assert pct_str in assumption_blob
        assert "heuristic" in assumption_blob.lower()

    def test_breakeven_range_uses_multipliers(self):
        paths = compute_recovery_paths(
            position=_sofi_position(),
            current_price=8.0,
            target_yield=0.18,
            sizing_cap_dollars=5000.0,
        )
        wheel = next(p for p in paths if p["path_id"] == "wheel-cc")
        # monthly_premium = 0.015 * $8 * 100 = $12
        # realized_loss = $3000; base months = 250
        # best = ceil(250 * 0.8) = 200; expected = 250; worst = ceil(250 * 1.3) = 325
        assert wheel["months_to_breakeven"]["best"] == 200
        assert wheel["months_to_breakeven"]["expected"] == 250
        assert wheel["months_to_breakeven"]["worst"] == 325
        # Multipliers stay in sync with the published constant.
        assert WHEEL_BE_MULTIPLIERS == (0.8, 1.0, 1.3)

    def test_capital_tied_up_is_strike_proxy_x_shares(self):
        paths = compute_recovery_paths(
            position=_sofi_position(),
            current_price=8.0,
            target_yield=0.18,
            sizing_cap_dollars=5000.0,
        )
        wheel = next(p for p in paths if p["path_id"] == "wheel-cc")
        # strike_proxy = $8, shares = 100 → $800
        assert wheel["capital_tied_up"] == pytest.approx(800.0)

    def test_opportunity_cost_vs_baseline_when_yield_set(self):
        paths = compute_recovery_paths(
            position=_sofi_position(),
            current_price=8.0,
            target_yield=0.18,
            sizing_cap_dollars=5000.0,
        )
        wheel = next(p for p in paths if p["path_id"] == "wheel-cc")
        # baseline_annual = $800 * 0.18 = $144
        # annual_premium = $12/mo * 12 = $144
        # opp_cost = $144 - $144 = $0
        assert wheel["opportunity_cost_vs_baseline"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# average-down
# ---------------------------------------------------------------------------


class TestAverageDownPath:
    def test_suppressed_when_sizing_cap_breached(self):
        # SOFI: shares=100, basis=$3800, current=$8 → adding 100 shares at
        # $8 = $800 in fresh capital; total tied up = $4600 → within $5000
        # cap. To force suppression, bump the cap below the new total.
        paths = compute_recovery_paths(
            position=_sofi_position(),
            current_price=8.0,
            target_yield=0.18,
            sizing_cap_dollars=2000.0,
        )
        avg = next(p for p in paths if p["path_id"] == "average-down")
        assert avg["eligibility"] == "suppressed"
        assert avg["suppression_reason"] is not None
        assert "sizing cap" in avg["suppression_reason"].lower()
        # Capital fields must be None per the suppressed contract.
        assert avg["capital_tied_up"] is None
        assert avg["opportunity_cost_vs_baseline"] is None

    def test_eligible_within_cap(self):
        paths = compute_recovery_paths(
            position=_sofi_position(),
            current_price=8.0,
            target_yield=0.18,
            sizing_cap_dollars=5000.0,
        )
        avg = next(p for p in paths if p["path_id"] == "average-down")
        assert avg["eligibility"] == "eligible"
        # capital_tied_up = $3800 + $800 = $4600
        assert avg["capital_tied_up"] == pytest.approx(4600.0)
        # opp_cost = additional_capital * target_yield = $800 * 0.18 = $144
        assert avg["opportunity_cost_vs_baseline"] == pytest.approx(144.0)

    def test_uses_supplied_sizing_cap(self):
        # The engine no longer carries its own default cap (issue #156):
        # the caller resolves it from rules_config and always supplies a
        # concrete value. With the SOFI fixture, $4600 < the $5000 catalog
        # default cap → eligible.
        paths = compute_recovery_paths(
            position=_sofi_position(),
            current_price=8.0,
            target_yield=0.18,
            sizing_cap_dollars=5000.0,
        )
        avg = next(p for p in paths if p["path_id"] == "average-down")
        assert avg["eligibility"] == "eligible"

    def test_eligible_breakeven_range_is_positive(self):
        # Average-down now projects a deterministic breakeven by grinding
        # wheel-CC premium on the doubled position (issue #237).
        # SOFI: shares=100, basis=$3800, current=$8.
        #   additional_capital = $8 * 100               = $800
        #   new_basis_total    = $3800 + $800            = $4600
        #   total_shares       = 100 * 2                 = 200
        #   remaining_loss     = $4600 - $8 * 200        = $3000
        #   monthly_premium    = 0.015 * $8 * 200        = $24
        #   base_months        = $3000 / $24             = 125.0
        #   best  = ceil(125.0 * 0.8) = ceil(100.0)      = 100
        #   expected = ceil(125.0 * 1.0) = ceil(125.0)   = 125
        #   worst = ceil(125.0 * 1.3) = ceil(162.5)      = 163
        paths = compute_recovery_paths(
            position=_sofi_position(),
            current_price=8.0,
            target_yield=0.18,
            sizing_cap_dollars=5000.0,
        )
        avg = next(p for p in paths if p["path_id"] == "average-down")
        be = avg["months_to_breakeven"]
        assert be["expected"] is not None
        assert be["expected"] > 0
        assert be["best"] == 100
        assert be["expected"] == 125
        assert be["worst"] == 163

    def test_breakeven_methodology_in_assumptions(self):
        # The assumption blob must document the new premium-grind
        # methodology and must NOT carry the stale "not modeled" copy.
        paths = compute_recovery_paths(
            position=_sofi_position(),
            current_price=8.0,
            target_yield=0.18,
            sizing_cap_dollars=5000.0,
        )
        avg = next(p for p in paths if p["path_id"] == "average-down")
        assumption_blob = " ".join(avg["assumptions"])
        pct_str = f"{WHEEL_MONTHLY_PREMIUM_PCT * 100:.1f}%/month"
        assert pct_str in assumption_blob
        assert "premium" in assumption_blob.lower()
        assert "doubled position" in assumption_blob.lower()
        assert "not modeled" not in assumption_blob.lower()

    def test_breakeven_collapses_only_on_zero_price_or_zero_shares(self):
        null_range = {"best": None, "expected": None, "worst": None}

        # Case A — current_price == 0 → no premium can be earned, no
        # breakeven horizon.
        paths_zero_price = compute_recovery_paths(
            position=_sofi_position(),
            current_price=0.0,
            target_yield=0.18,
            sizing_cap_dollars=5000.0,
        )
        avg_zero_price = next(
            p for p in paths_zero_price if p["path_id"] == "average-down"
        )
        assert avg_zero_price["months_to_breakeven"] == null_range

        # Case B — shares == 0 → doubled position is still zero shares, no
        # premium base.
        paths_zero_shares = compute_recovery_paths(
            position=_sofi_position(shares=0),
            current_price=8.0,
            target_yield=0.18,
            sizing_cap_dollars=5000.0,
        )
        avg_zero_shares = next(
            p for p in paths_zero_shares if p["path_id"] == "average-down"
        )
        assert avg_zero_shares["months_to_breakeven"] == null_range

        # Case C — positive control: an eligible fixture still projects a
        # real, non-null breakeven.
        paths_eligible = compute_recovery_paths(
            position=_sofi_position(),
            current_price=8.0,
            target_yield=0.18,
            sizing_cap_dollars=5000.0,
        )
        avg_eligible = next(p for p in paths_eligible if p["path_id"] == "average-down")
        assert avg_eligible["months_to_breakeven"]["expected"] is not None


# ---------------------------------------------------------------------------
# hold-monitor
# ---------------------------------------------------------------------------


class TestHoldMonitorPath:
    def test_breakeven_range_is_all_null(self):
        paths = compute_recovery_paths(
            position=_sofi_position(),
            current_price=8.0,
            target_yield=0.18,
            sizing_cap_dollars=5000.0,
        )
        hold = next(p for p in paths if p["path_id"] == "hold-monitor")
        assert hold["months_to_breakeven"] == {
            "best": None,
            "expected": None,
            "worst": None,
        }

    def test_opportunity_cost_is_freed_capital_x_yield(self):
        paths = compute_recovery_paths(
            position=_sofi_position(),
            current_price=8.0,
            target_yield=0.18,
            sizing_cap_dollars=5000.0,
        )
        hold = next(p for p in paths if p["path_id"] == "hold-monitor")
        # freed_capital = $800; opp_cost = $800 * 0.18 = $144
        assert hold["opportunity_cost_vs_baseline"] == pytest.approx(144.0)

    def test_capital_tied_up_is_current_basis(self):
        paths = compute_recovery_paths(
            position=_sofi_position(),
            current_price=8.0,
            target_yield=0.18,
            sizing_cap_dollars=5000.0,
        )
        hold = next(p for p in paths if p["path_id"] == "hold-monitor")
        # adjusted_cost_basis = $3800
        assert hold["capital_tied_up"] == pytest.approx(3800.0)

    def test_eligible_even_when_yield_unset(self):
        paths = compute_recovery_paths(
            position=_sofi_position(),
            current_price=8.0,
            target_yield=None,
            sizing_cap_dollars=5000.0,
        )
        hold = next(p for p in paths if p["path_id"] == "hold-monitor")
        # Hold needs no target yield to be eligible — it's the "do nothing"
        # baseline.
        assert hold["eligibility"] == "eligible"
        assert hold["opportunity_cost_vs_baseline"] is None


# ---------------------------------------------------------------------------
# Determinism + external-call guarantees
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_byte_identical_output_for_same_input(self):
        kwargs = {
            "position": _sofi_position(),
            "current_price": 8.0,
            "target_yield": 0.18,
            "sizing_cap_dollars": 5000.0,
        }
        out_a = compute_recovery_paths(**kwargs)
        out_b = compute_recovery_paths(**kwargs)
        assert json.dumps(out_a, sort_keys=True) == json.dumps(out_b, sort_keys=True)


class TestNoExternalCalls:
    """Static check: engine must not import HTTP / LLM clients."""

    FORBIDDEN_TOP_LEVEL_MODULES = {
        "httpx",
        "requests",
        "openai",
        "anthropic",
        "urllib",
        "socket",
    }

    def test_engine_module_has_no_forbidden_imports(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "services"
            / "recovery_engine.py"
        )
        tree = ast.parse(path.read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split(".")[0])
        leaks = self.FORBIDDEN_TOP_LEVEL_MODULES & imported
        assert not leaks, f"recovery_engine.py imports forbidden modules: {leaks}"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_position_above_water_returns_eligible_paths_with_null_breakeven(self):
        # current_price * shares > adjusted_cost_basis → no realized loss.
        paths = compute_recovery_paths(
            position=_sofi_position(adjusted_cost_basis=500.0),
            current_price=8.0,
            target_yield=0.18,
            sizing_cap_dollars=5000.0,
        )
        # sell-redeploy: realized_loss=0 → breakeven range collapses
        sell = next(p for p in paths if p["path_id"] == "sell-redeploy")
        assert sell["months_to_breakeven"]["expected"] is None

    def test_zero_current_price_treated_as_zero_dollars(self):
        paths = compute_recovery_paths(
            position=_sofi_position(),
            current_price=0.0,
            target_yield=0.18,
            sizing_cap_dollars=5000.0,
        )
        wheel = next(p for p in paths if p["path_id"] == "wheel-cc")
        # Premium math collapses to zero — no breakeven horizon.
        assert wheel["months_to_breakeven"]["expected"] is None

    def test_zero_shares_collapses_paths_to_zero_dollars(self):
        paths = compute_recovery_paths(
            position=_sofi_position(shares=0),
            current_price=8.0,
            target_yield=0.18,
            sizing_cap_dollars=5000.0,
        )
        wheel = next(p for p in paths if p["path_id"] == "wheel-cc")
        assert wheel["capital_tied_up"] == pytest.approx(0.0)
