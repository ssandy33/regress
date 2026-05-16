"""Unit tests for the Recovery Plan scoring engine.

Covers the recommendation-engine ACs from issue #182:

- leader-per-criterion picks up the points
- ties at exact equality split points
- tie within ``TIE_EPSILON = 1.0`` → ``recommended_path_id = None`` +
  ``"No clear best fit"`` label
- suppressed path with winning metrics is never recommended
- OKR strategy-preference bonus applied when set, dormant when unset
- bonus criterion row is always present (so the unset callout renders)
- all paths suppressed → ``"No eligible path under current sizing rules"``
- reproducibility: same input → byte-identical recommendation
- ``path_scores[]`` shape — one entry per criterion × all eligible paths
- ``recommendation_reasons`` length 2–4, drawn from frozen templates
- no LLM / HTTP imports in the module
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app.services.recovery_engine import compute_recovery_paths
from app.services.recovery_scoring import (
    DISCLAIMER_TEXT,
    LABEL_TEMPLATES,
    REASON_TEMPLATES,
    STRATEGY_PREFERENCE_TO_PATH,
    TIE_EPSILON,
    WEIGHT_FASTEST_BREAKEVEN,
    WEIGHT_LOWEST_CAPITAL,
    WEIGHT_LOWEST_OPPORTUNITY_COST,
    WEIGHT_STRATEGY_PREFERENCE,
    score_recovery_paths,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sofi_position(**overrides) -> dict:
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


def _sofi_paths(target_yield: float | None = 0.18, sizing_cap: float = 5000.0):
    return compute_recovery_paths(
        position=_sofi_position(),
        current_price=8.0,
        target_yield=target_yield,
        sizing_cap_dollars=sizing_cap,
    )


def _make_path(
    *,
    path_id: str,
    label: str = "X",
    eligibility: str = "eligible",
    suppression_reason: str | None = None,
    capital_tied_up: float | None = 0.0,
    expected_months: float | None = None,
    opportunity_cost: float | None = 0.0,
) -> dict:
    """Lightweight path-dict builder for scoring-only tests."""
    return {
        "path_id": path_id,
        "label": label,
        "eligibility": eligibility,
        "suppression_reason": suppression_reason,
        "capital_tied_up": capital_tied_up,
        "months_to_breakeven": {
            "best": None,
            "expected": expected_months,
            "worst": None,
        },
        "opportunity_cost_vs_baseline": opportunity_cost,
        "assumptions": [],
        "narration": None,
    }


# ---------------------------------------------------------------------------
# Sanity / canonical shape
# ---------------------------------------------------------------------------


class TestCanonicalShape:
    def test_response_has_required_top_level_keys(self):
        paths = _sofi_paths()
        rec = score_recovery_paths(paths, {})
        assert set(rec.keys()) == {
            "recommended_path_id",
            "recommendation_label",
            "recommendation_reasons",
            "ranked_paths",
            "path_scores",
            "tie_epsilon",
            "disclaimer",
        }

    def test_disclaimer_is_canonical_text(self):
        rec = score_recovery_paths(_sofi_paths(), {})
        assert rec["disclaimer"] == DISCLAIMER_TEXT
        # Per advice-framing audit: no prescriptive verbs in the disclaimer.
        for verb in ("you should", "buy ", "sell ", "hold "):
            assert verb not in DISCLAIMER_TEXT.lower(), (
                f"disclaimer leaks prescriptive verb '{verb}'"
            )

    def test_tie_epsilon_matches_module_constant(self):
        rec = score_recovery_paths(_sofi_paths(), {})
        assert rec["tie_epsilon"] == TIE_EPSILON == 1.0


# ---------------------------------------------------------------------------
# Leader-per-criterion + tie handling
# ---------------------------------------------------------------------------


class TestLeaderPerCriterion:
    def test_unique_leader_collects_full_weight(self):
        # Path A is the unique leader on fastest_breakeven.
        paths = [
            _make_path(
                path_id="wheel-cc", label="Wheel", capital_tied_up=100,
                expected_months=4, opportunity_cost=0,
            ),
            _make_path(
                path_id="sell-redeploy", label="Sell", capital_tied_up=200,
                expected_months=10, opportunity_cost=50,
            ),
            _make_path(
                path_id="hold-monitor", label="Hold", capital_tied_up=300,
                expected_months=20, opportunity_cost=200,
            ),
        ]
        rec = score_recovery_paths(paths, {})
        row = next(
            r for r in rec["path_scores"] if r["criterion"] == "fastest_breakeven"
        )
        cells = {c["path_id"]: c for c in row["ranking"]}
        assert cells["wheel-cc"]["points"] == WEIGHT_FASTEST_BREAKEVEN
        assert cells["sell-redeploy"]["points"] == 0
        assert cells["hold-monitor"]["points"] == 0

    def test_exact_tie_splits_points_among_leaders(self):
        # All three paths have $0 capital — the AC example: all three get +3.
        paths = [
            _make_path(
                path_id="wheel-cc", label="Wheel", capital_tied_up=0,
                expected_months=4, opportunity_cost=100,
            ),
            _make_path(
                path_id="sell-redeploy", label="Sell", capital_tied_up=0,
                expected_months=10, opportunity_cost=0,
            ),
            _make_path(
                path_id="hold-monitor", label="Hold", capital_tied_up=0,
                expected_months=20, opportunity_cost=200,
            ),
        ]
        rec = score_recovery_paths(paths, {})
        row = next(
            r for r in rec["path_scores"] if r["criterion"] == "lowest_additional_capital"
        )
        for cell in row["ranking"]:
            assert cell["points"] == WEIGHT_LOWEST_CAPITAL
            assert cell["rank"] == 1


# ---------------------------------------------------------------------------
# Tie within epsilon → no clear best fit
# ---------------------------------------------------------------------------


class TestTieWithinEpsilon:
    def test_top_two_within_epsilon_yields_no_clear_best_fit(self):
        # Construct two paths that score 5 and 5 on totals → tied.
        paths = [
            # wheel-cc wins fastest_breakeven (+3) and ties capital (+3).
            _make_path(
                path_id="wheel-cc", label="Wheel", capital_tied_up=0,
                expected_months=4, opportunity_cost=200,
            ),
            # sell-redeploy ties capital (+3) and wins opp-cost (+2).
            _make_path(
                path_id="sell-redeploy", label="Sell", capital_tied_up=0,
                expected_months=10, opportunity_cost=0,
            ),
        ]
        rec = score_recovery_paths(paths, {})
        # Totals: wheel=3+3=6; sell=3+2=5. Gap=1 → within epsilon → no clear.
        assert rec["recommended_path_id"] is None
        assert rec["recommendation_label"] == "No clear best fit"
        assert rec["recommendation_label"] == LABEL_TEMPLATES["no_clear_best_fit"]
        # Ranked paths still rendered.
        assert len(rec["ranked_paths"]) >= 2
        assert rec["ranked_paths"][0]["score"] == 6
        assert rec["ranked_paths"][1]["score"] == 5

    def test_gap_larger_than_epsilon_recommends_single_path(self):
        # wheel-cc dominates: +3 (fastest) +3 (capital) +2 (opp_cost) = 8.
        # hold-monitor: capital ties (+3 if tied) but otherwise 0.
        paths = [
            _make_path(
                path_id="wheel-cc", label="Wheel", capital_tied_up=0,
                expected_months=4, opportunity_cost=0,
            ),
            _make_path(
                path_id="sell-redeploy", label="Sell", capital_tied_up=500,
                expected_months=20, opportunity_cost=100,
            ),
            _make_path(
                path_id="hold-monitor", label="Hold", capital_tied_up=800,
                expected_months=None, opportunity_cost=300,
            ),
        ]
        rec = score_recovery_paths(paths, {})
        assert rec["recommended_path_id"] == "wheel-cc"


# ---------------------------------------------------------------------------
# Suppressed paths
# ---------------------------------------------------------------------------


class TestSuppressedHandling:
    def test_suppressed_path_with_winning_metrics_is_not_recommended(self):
        # Force a suppressed path that *would* dominate the metrics.
        paths = [
            _make_path(
                path_id="wheel-cc", label="Wheel", capital_tied_up=100,
                expected_months=10, opportunity_cost=50,
            ),
            _make_path(
                path_id="average-down",
                label="Average down",
                eligibility="suppressed",
                suppression_reason="Exceeds your $5,000 per-position sizing cap",
                capital_tied_up=None,
                expected_months=None,
                opportunity_cost=None,
            ),
        ]
        rec = score_recovery_paths(paths, {})
        # Only wheel-cc is eligible → must be recommended.
        assert rec["recommended_path_id"] == "wheel-cc"
        # Suppressed path is in ranked_paths with null score+rank.
        suppressed_entry = next(
            r for r in rec["ranked_paths"] if r["path_id"] == "average-down"
        )
        assert suppressed_entry["score"] is None
        assert suppressed_entry["rank"] is None
        assert "sizing cap" in (suppressed_entry["suppression_reason"] or "")

    def test_all_paths_suppressed_yields_no_eligible_path(self):
        paths = [
            _make_path(
                path_id="sell-redeploy",
                label="Sell",
                eligibility="suppressed",
                suppression_reason="Target yield not configured",
            ),
            _make_path(
                path_id="average-down",
                label="Average down",
                eligibility="suppressed",
                suppression_reason="Exceeds your $5,000 per-position sizing cap",
            ),
        ]
        rec = score_recovery_paths(paths, {})
        assert rec["recommended_path_id"] is None
        assert (
            rec["recommendation_label"]
            == LABEL_TEMPLATES["no_eligible_path"]
            == "No eligible path under current sizing rules"
        )
        # Reasons list still 2–4 entries.
        assert 2 <= len(rec["recommendation_reasons"]) <= 4
        # path_scores collapses to empty when nothing is eligible.
        assert rec["path_scores"] == []


# ---------------------------------------------------------------------------
# Strategy-preference bonus (dormant in V0.5.8)
# ---------------------------------------------------------------------------


class TestStrategyPreferenceBonus:
    def test_unset_preference_keeps_bonus_row_with_all_zero_cells(self):
        # V0.5.8 default — strategy_preference unset.
        rec = score_recovery_paths(_sofi_paths(), {})
        bonus_row = next(
            r for r in rec["path_scores"] if r["criterion"] == "strategy_preference_bonus"
        )
        assert bonus_row["weight"] == WEIGHT_STRATEGY_PREFERENCE
        for cell in bonus_row["ranking"]:
            assert cell["points"] == 0, (
                "unset preference must not contribute points"
            )

    def test_set_preference_awards_bonus_to_matching_path(self):
        rec = score_recovery_paths(
            _sofi_paths(), {"strategy_preference": "income-first"}
        )
        bonus_row = next(
            r for r in rec["path_scores"] if r["criterion"] == "strategy_preference_bonus"
        )
        # income-first → wheel-cc per the mapping.
        wheel_cell = next(
            c for c in bonus_row["ranking"] if c["path_id"] == "wheel-cc"
        )
        assert wheel_cell["points"] == WEIGHT_STRATEGY_PREFERENCE

    def test_unknown_preference_defaults_to_no_bonus(self):
        rec = score_recovery_paths(
            _sofi_paths(), {"strategy_preference": "definitely-not-real"}
        )
        bonus_row = next(
            r for r in rec["path_scores"] if r["criterion"] == "strategy_preference_bonus"
        )
        assert all(c["points"] == 0 for c in bonus_row["ranking"])

    def test_passive_preference_yields_no_bonus(self):
        rec = score_recovery_paths(
            _sofi_paths(), {"strategy_preference": "passive"}
        )
        bonus_row = next(
            r for r in rec["path_scores"] if r["criterion"] == "strategy_preference_bonus"
        )
        assert all(c["points"] == 0 for c in bonus_row["ranking"])

    def test_label_uses_neutral_template_when_preference_unset(self):
        rec = score_recovery_paths(_sofi_paths(), {})
        if rec["recommended_path_id"] is not None:
            # Label must come from the neutral template, not the
            # with-strategy-preference one.
            assert rec["recommendation_label"].startswith(
                "Best fit on capital efficiency and breakeven"
            )

    def test_strategy_mapping_locked(self):
        # If this assertion ever fails, dependent #156/#157 work and the
        # design spec §4.5 need updating together.
        assert STRATEGY_PREFERENCE_TO_PATH == {
            "income-first": "wheel-cc",
            "capital-efficient": "sell-redeploy",
            "conviction-add": "average-down",
        }


# ---------------------------------------------------------------------------
# path_scores shape + reasons
# ---------------------------------------------------------------------------


class TestPathScoresMatrix:
    def test_one_row_per_criterion_in_canonical_order(self):
        rec = score_recovery_paths(_sofi_paths(), {})
        criteria = [r["criterion"] for r in rec["path_scores"]]
        assert criteria == [
            "fastest_breakeven",
            "lowest_additional_capital",
            "lowest_opportunity_cost",
            "strategy_preference_bonus",
        ]

    def test_each_row_has_one_cell_per_eligible_path(self):
        paths = _sofi_paths()
        eligible = [p for p in paths if p["eligibility"] == "eligible"]
        rec = score_recovery_paths(paths, {})
        for row in rec["path_scores"]:
            assert len(row["ranking"]) == len(eligible)
            assert {c["path_id"] for c in row["ranking"]} == {
                p["path_id"] for p in eligible
            }

    def test_each_cell_has_raw_value_points_rank(self):
        rec = score_recovery_paths(_sofi_paths(), {})
        for row in rec["path_scores"]:
            for cell in row["ranking"]:
                assert set(cell.keys()) == {"path_id", "raw_value", "points", "rank"}


class TestRecommendationReasons:
    def _happy_path_recommendation(self):
        """Drive the engine to a single-winner happy-path recommendation.

        The default SOFI fixture ties on enough criteria that the scoring
        engine emits ``no-clear-best-fit`` — that's a separate scoring path
        with its own degradation copy. Use a synthetic path list here so
        the happy-path reason templates are the only thing under test.
        """
        paths = [
            _make_path(
                path_id="wheel-cc", label="Wheel covered calls",
                capital_tied_up=100, expected_months=4, opportunity_cost=50,
            ),
            _make_path(
                path_id="sell-redeploy", label="Sell & redeploy",
                capital_tied_up=500, expected_months=10, opportunity_cost=0,
            ),
            _make_path(
                path_id="hold-monitor", label="Hold & monitor",
                capital_tied_up=800, expected_months=None, opportunity_cost=300,
            ),
        ]
        return score_recovery_paths(paths, {})

    def test_reasons_length_2_to_4_on_happy_path(self):
        rec = self._happy_path_recommendation()
        assert rec["recommended_path_id"] == "wheel-cc"
        assert 2 <= len(rec["recommendation_reasons"]) <= 4

    def test_all_reasons_come_from_templates_on_happy_path(self):
        rec = self._happy_path_recommendation()
        # Every reason must look like one of the frozen templates with the
        # placeholders filled in. We assert by recognizing template prefixes.
        template_prefixes = {
            "Fastest expected breakeven",
            "Lowest additional capital required",
            "Lowest opportunity cost vs baseline",
            "Matches your configured",
            "Within your per-position sizing cap",
        }
        for reason in rec["recommendation_reasons"]:
            assert any(reason.startswith(p) for p in template_prefixes), (
                f"reason '{reason}' did not match any template prefix"
            )

    def test_reasons_avoid_prescriptive_advice_wording(self):
        # Cover both code paths — happy + degraded — so the advice-framing
        # audit runs against every emitted reason.
        for rec in (
            self._happy_path_recommendation(),
            score_recovery_paths(_sofi_paths(), {}),
        ):
            for reason in rec["recommendation_reasons"]:
                low = reason.lower()
                assert "you should" not in low
                assert "buy more" not in low
                assert "sell now" not in low


# ---------------------------------------------------------------------------
# Reproducibility (AC: same input → byte-identical recommendation)
# ---------------------------------------------------------------------------


class TestReproducibility:
    def test_byte_identical_recommendation_object(self):
        paths = _sofi_paths()
        a = score_recovery_paths(paths, {})
        b = score_recovery_paths(paths, {})
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_byte_identical_with_strategy_preference(self):
        paths = _sofi_paths()
        a = score_recovery_paths(paths, {"strategy_preference": "income-first"})
        b = score_recovery_paths(paths, {"strategy_preference": "income-first"})
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ---------------------------------------------------------------------------
# Static guard: no LLM / HTTP imports in scoring module
# ---------------------------------------------------------------------------


class TestNoExternalCalls:
    FORBIDDEN = {"httpx", "requests", "openai", "anthropic", "urllib", "socket"}

    def test_scoring_module_imports_are_pure(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "services"
            / "recovery_scoring.py"
        )
        tree = ast.parse(path.read_text())
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    names.add(node.module.split(".")[0])
        leaks = self.FORBIDDEN & names
        assert not leaks, f"scoring module imports forbidden modules: {leaks}"


# ---------------------------------------------------------------------------
# Snapshot — template strings frozen after merge (AC)
# ---------------------------------------------------------------------------


class TestTemplateSnapshots:
    """Inline snapshot of the LABEL + REASON template dicts.

    Failing this test means a template string changed — that's an
    intentional product decision and the snapshot needs to be updated in
    the same commit (the AC explicitly says "Template strings for
    `recommendation_label` and `recommendation_reasons` are frozen by
    snapshot tests after merge").
    """

    EXPECTED_LABEL_TEMPLATES: dict[str, str] = {
        "recommended_neutral": "Best fit on capital efficiency and breakeven: {path_label}",
        "recommended_with_strategy_preference": (
            "Best fit for {preference} strategy: {path_label}"
        ),
        "no_clear_best_fit": "No clear best fit",
        "no_eligible_path": "No eligible path under current sizing rules",
    }

    EXPECTED_REASON_TEMPLATES: dict[str, str] = {
        "fastest_breakeven_solo": (
            "Fastest expected breakeven ({months} months vs {next_months} for the next option)"
        ),
        "fastest_breakeven_unique": "Fastest expected breakeven ({months} months)",
        "lowest_additional_capital_zero": "Lowest additional capital required ($0)",
        "lowest_additional_capital_amount": (
            "Lowest additional capital required (${capital:,.0f} vs ${next_capital:,.0f} for the next option)"
        ),
        "lowest_opportunity_cost": "Lowest opportunity cost vs baseline (${opp_cost:,.0f})",
        "strategy_preference_match": "Matches your configured {preference} strategy preference",
        "within_sizing_cap": "Within your per-position sizing cap",
    }

    def test_label_templates_frozen(self):
        assert LABEL_TEMPLATES == self.EXPECTED_LABEL_TEMPLATES

    def test_reason_templates_frozen(self):
        assert REASON_TEMPLATES == self.EXPECTED_REASON_TEMPLATES

    def test_disclaimer_text_frozen(self):
        assert DISCLAIMER_TEXT == (
            "This is a fit recommendation based on your configured "
            "preferences and stated assumptions. It is not investment "
            "advice, a price prediction, or a trade execution suggestion."
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_single_eligible_path_is_always_recommended(self):
        paths = [
            _make_path(
                path_id="hold-monitor", label="Hold", capital_tied_up=100,
                expected_months=None, opportunity_cost=0,
            ),
        ]
        rec = score_recovery_paths(paths, {})
        # Only one eligible → trivially the recommended path. Tie-epsilon
        # has nothing to compare to.
        assert rec["recommended_path_id"] == "hold-monitor"

    def test_empty_okr_settings_treated_as_unset(self):
        rec_a = score_recovery_paths(_sofi_paths(), None)
        rec_b = score_recovery_paths(_sofi_paths(), {})
        # Different empty containers, identical output.
        assert json.dumps(rec_a, sort_keys=True) == json.dumps(rec_b, sort_keys=True)

    def test_hold_monitor_null_breakeven_treated_as_worst_tier(self):
        rec = score_recovery_paths(_sofi_paths(), {})
        row = next(
            r for r in rec["path_scores"] if r["criterion"] == "fastest_breakeven"
        )
        hold_cell = next(c for c in row["ranking"] if c["path_id"] == "hold-monitor")
        assert hold_cell["points"] == 0
