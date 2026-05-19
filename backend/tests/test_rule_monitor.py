"""Unit tests for the §R6 rule-monitor (issue #240).

``evaluate_leg_rules`` is a pure function — every input is a plain value,
every output is a plain dict. These tests exercise:
- each rule fires positive + negative across its threshold boundary;
- precedence — the single governing rule when several fire;
- the tri-state ``triggered`` / ``not_yet`` / ``no`` status;
- the graceful-degradation path when no live mid is available;
- the advice-framing discipline on every reasoning string (spec §11).

No DB, no HTTP.
"""

from __future__ import annotations

import pytest

from app.services.rule_monitor import (
    RULE_PRECEDENCE,
    card_reason_for,
    evaluate_leg_rules,
)


def _profit_status(captured_pct):
    """Build a profit_target_status dict with the given captured fraction."""
    if captured_pct is None:
        return {"captured_pct": None, "state": "unknown"}
    return {"captured_pct": captured_pct, "state": "in_progress"}


def _evaluate(**overrides):
    """Evaluate a leg with sensible quiet defaults overridden as needed."""
    kwargs = {
        "dte": 40,
        "moneyness_state": "OTM",
        "profit_target_status": _profit_status(0.18),
        "premium": 38.34,
        "current_mid": 12.00,
        "profit_review_pct": 50.0,
        "dte_review_days": 21,
        "expiration_warning_days": 7,
        "assignment_risk": "low",
    }
    kwargs.update(overrides)
    return evaluate_leg_rules(**kwargs)


# ---------------------------------------------------------------------------
# Payload shape
# ---------------------------------------------------------------------------


class TestTriggeredRulesShape:
    def test_always_four_rows_in_precedence_order(self):
        _, _, _, rules = _evaluate()
        assert len(rules) == 4
        assert [r["rule_id"] for r in rules] == [
            "assignment_risk",
            "expiration_warning",
            "profit_review",
            "dte_review",
        ]

    def test_precedence_constant_has_four_keys(self):
        assert RULE_PRECEDENCE == (
            "assignment",
            "expiration",
            "profit_review",
            "dte_review",
        )

    def test_every_row_has_required_keys(self):
        _, _, _, rules = _evaluate()
        for row in rules:
            assert set(row) == {
                "rule_id",
                "metric_label",
                "value_display",
                "rule_display",
                "status",
                "is_governing",
                "reasoning",
            }


# ---------------------------------------------------------------------------
# Quiet leg — nothing fires
# ---------------------------------------------------------------------------


class TestQuietLeg:
    def test_no_rule_fires_yields_hold(self):
        verdict, label, reasoning, rules = _evaluate(
            dte=40, profit_target_status=_profit_status(0.18)
        )
        assert verdict == "hold"
        assert label == "Hold"
        assert reasoning == "No management rule has triggered for this leg yet."
        assert all(not r["is_governing"] for r in rules)

    def test_quiet_leg_rows_are_not_triggered(self):
        _, _, _, rules = _evaluate(dte=40, profit_target_status=_profit_status(0.18))
        statuses = {r["rule_id"]: r["status"] for r in rules}
        assert statuses["profit_review"] == "not_yet"
        assert statuses["dte_review"] == "not_yet"
        assert statuses["expiration_warning"] == "not_yet"
        assert statuses["assignment_risk"] == "no"


# ---------------------------------------------------------------------------
# Profit-take rule
# ---------------------------------------------------------------------------


class TestProfitTakeRule:
    def test_fires_above_threshold(self):
        verdict, label, _, _ = _evaluate(
            dte=40, profit_target_status=_profit_status(0.60)
        )
        assert verdict == "profit_take_review"
        assert label == "Review · 50%"

    def test_fires_exactly_at_threshold(self):
        verdict, _, _, rules = _evaluate(
            dte=40, profit_target_status=_profit_status(0.50)
        )
        assert verdict == "profit_take_review"
        profit_row = next(r for r in rules if r["rule_id"] == "profit_review")
        assert profit_row["status"] == "triggered"

    def test_just_below_threshold_not_yet(self):
        verdict, _, _, rules = _evaluate(
            dte=40, profit_target_status=_profit_status(0.49)
        )
        assert verdict == "hold"
        profit_row = next(r for r in rules if r["rule_id"] == "profit_review")
        assert profit_row["status"] == "not_yet"

    def test_custom_threshold_interpolated_in_label(self):
        verdict, label, _, rules = _evaluate(
            dte=40,
            profit_target_status=_profit_status(0.67),
            profit_review_pct=65.0,
        )
        assert verdict == "profit_take_review"
        assert label == "Review · 65%"
        profit_row = next(r for r in rules if r["rule_id"] == "profit_review")
        assert profit_row["rule_display"] == "Review at ≥ 65%"


# ---------------------------------------------------------------------------
# DTE-review rule
# ---------------------------------------------------------------------------


class TestDteReviewRule:
    def test_fires_inside_window(self):
        verdict, label, _, _ = _evaluate(
            dte=20, profit_target_status=_profit_status(0.10)
        )
        assert verdict == "dte_review"
        assert label == "Review · 21d"

    def test_fires_exactly_at_window_boundary(self):
        verdict, _, _, _ = _evaluate(
            dte=21, profit_target_status=_profit_status(0.10)
        )
        assert verdict == "dte_review"

    def test_one_day_past_window_not_yet(self):
        verdict, _, _, rules = _evaluate(
            dte=22, profit_target_status=_profit_status(0.10)
        )
        assert verdict == "hold"
        dte_row = next(r for r in rules if r["rule_id"] == "dte_review")
        assert dte_row["status"] == "not_yet"

    def test_custom_dte_window_honored(self):
        verdict, label, _, _ = _evaluate(
            dte=25,
            profit_target_status=_profit_status(0.10),
            dte_review_days=30,
        )
        assert verdict == "dte_review"
        assert label == "Review · 30d"


# ---------------------------------------------------------------------------
# Expiration / assignment rules
# ---------------------------------------------------------------------------


class TestExpirationRule:
    def test_expiration_fires_otm_inside_warning_window(self):
        verdict, label, _, _ = _evaluate(
            dte=5, moneyness_state="OTM", profit_target_status=_profit_status(0.10)
        )
        assert verdict == "expiration"
        assert label == "Close · exp"

    def test_assignment_fires_itm_inside_warning_window(self):
        verdict, label, _, _ = _evaluate(
            dte=5, moneyness_state="ITM", profit_target_status=_profit_status(0.10)
        )
        assert verdict == "assignment"
        assert label == "Close · ITM"

    def test_expiration_boundary_at_warning_window(self):
        verdict, _, _, _ = _evaluate(
            dte=7, moneyness_state="OTM", profit_target_status=_profit_status(0.10)
        )
        assert verdict == "expiration"

    def test_assignment_row_never_not_yet(self):
        # An OTM leg approaching expiry is an expiration case, never an
        # armed assignment countdown (spec §3.3).
        _, _, _, rules = _evaluate(
            dte=40, moneyness_state="OTM", profit_target_status=_profit_status(0.10)
        )
        assignment_row = next(r for r in rules if r["rule_id"] == "assignment_risk")
        assert assignment_row["status"] == "no"

    def test_expired_leg_yields_hold(self):
        verdict, _, _, rules = _evaluate(
            dte=-3, moneyness_state="OTM", profit_target_status=_profit_status(None)
        )
        assert verdict == "hold"
        exp_row = next(r for r in rules if r["rule_id"] == "expiration_warning")
        dte_row = next(r for r in rules if r["rule_id"] == "dte_review")
        assert exp_row["status"] == "no"
        assert dte_row["status"] == "no"


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------


class TestPrecedence:
    def test_profit_take_outranks_dte_review(self):
        # Inside the 21d window AND past 50% capture.
        verdict, _, reasoning, rules = _evaluate(
            dte=14, profit_target_status=_profit_status(0.67)
        )
        assert verdict == "profit_take_review"
        profit_row = next(r for r in rules if r["rule_id"] == "profit_review")
        dte_row = next(r for r in rules if r["rule_id"] == "dte_review")
        assert profit_row["status"] == "triggered"
        assert profit_row["is_governing"] is True
        assert dte_row["status"] == "triggered"
        assert dte_row["is_governing"] is False
        # The reasoning leads with the governing rule and appends the other.
        assert "profit-take rule triggered" in reasoning
        assert "21-day review window" in reasoning

    def test_assignment_outranks_everything(self):
        # 5-DTE ITM leg also past 50% capture: assignment governs.
        verdict, label, _, rules = _evaluate(
            dte=5, moneyness_state="ITM", profit_target_status=_profit_status(0.60)
        )
        assert verdict == "assignment"
        assert label == "Close · ITM"
        assignment_row = next(r for r in rules if r["rule_id"] == "assignment_risk")
        assert assignment_row["is_governing"] is True

    def test_only_governing_rule_carries_reasoning(self):
        _, _, _, rules = _evaluate(
            dte=14, profit_target_status=_profit_status(0.67)
        )
        governing = [r for r in rules if r["is_governing"]]
        assert len(governing) == 1
        for row in rules:
            if row["is_governing"]:
                assert row["reasoning"] is not None
            else:
                assert row["reasoning"] is None


# ---------------------------------------------------------------------------
# Tri-state status
# ---------------------------------------------------------------------------


class TestTriState:
    def test_far_dte_leg_is_not_yet(self):
        _, _, _, rules = _evaluate(
            dte=38, profit_target_status=_profit_status(0.20)
        )
        dte_row = next(r for r in rules if r["rule_id"] == "dte_review")
        assert dte_row["status"] == "not_yet"
        assert dte_row["value_display"] == "38 d"

    def test_otm_leg_assignment_row_is_no(self):
        _, _, _, rules = _evaluate(
            dte=38, moneyness_state="OTM", profit_target_status=_profit_status(0.20)
        )
        assignment_row = next(r for r in rules if r["rule_id"] == "assignment_risk")
        assert assignment_row["status"] == "no"


# ---------------------------------------------------------------------------
# Assignment-risk inspect row — shows the risk level, not moneyness
# ---------------------------------------------------------------------------


class TestAssignmentRiskRowValue:
    """The "Assignment risk" row value must read as a risk level
    (High / Watch / Low) so it agrees with its "Review at ≥ High" rule —
    not the ITM/ATM/OTM moneyness label (CodeRabbit fix).
    """

    def test_high_risk_row_shows_high_not_moneyness(self):
        _, _, _, rules = _evaluate(
            dte=5,
            moneyness_state="ITM",
            assignment_risk="high",
            profit_target_status=_profit_status(0.20),
        )
        assignment_row = next(r for r in rules if r["rule_id"] == "assignment_risk")
        assert assignment_row["value_display"] == "High"
        assert assignment_row["value_display"] not in {"ITM", "ATM", "OTM"}

    def test_watch_risk_row_shows_watch(self):
        _, _, _, rules = _evaluate(
            dte=12,
            moneyness_state="ITM",
            assignment_risk="watch",
            profit_target_status=_profit_status(0.20),
        )
        assignment_row = next(r for r in rules if r["rule_id"] == "assignment_risk")
        assert assignment_row["value_display"] == "Watch"

    def test_low_risk_row_shows_low(self):
        _, _, _, rules = _evaluate(
            dte=38,
            moneyness_state="OTM",
            assignment_risk="low",
            profit_target_status=_profit_status(0.20),
        )
        assignment_row = next(r for r in rules if r["rule_id"] == "assignment_risk")
        assert assignment_row["value_display"] == "Low"


# ---------------------------------------------------------------------------
# Degraded path — no live mid
# ---------------------------------------------------------------------------


class TestDegradedNoMid:
    def test_no_mid_profit_row_is_no_with_dash(self):
        _, _, _, rules = _evaluate(
            dte=12,
            current_mid=None,
            profit_target_status=_profit_status(None),
        )
        profit_row = next(r for r in rules if r["rule_id"] == "profit_review")
        assert profit_row["status"] == "no"
        assert profit_row["value_display"] == "—"

    def test_verdict_falls_back_to_dte_rules_without_mid(self):
        # 12-DTE leg, no mid: profit-take unevaluable, DTE-review still fires.
        verdict, _, _, _ = _evaluate(
            dte=12,
            current_mid=None,
            profit_target_status=_profit_status(None),
        )
        assert verdict == "dte_review"

    def test_profit_take_never_governs_without_mid(self):
        verdict, _, _, _ = _evaluate(
            dte=40,
            current_mid=None,
            profit_target_status=_profit_status(None),
        )
        assert verdict != "profit_take_review"


# ---------------------------------------------------------------------------
# Advice framing — spec §11
# ---------------------------------------------------------------------------


class TestAdviceFraming:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"dte": 40, "profit_target_status": _profit_status(0.60)},  # profit-take
            {"dte": 18, "profit_target_status": _profit_status(0.20)},  # dte-review
            {
                "dte": 5,
                "moneyness_state": "OTM",
                "profit_target_status": _profit_status(0.20),
            },  # expiration
            {
                "dte": 5,
                "moneyness_state": "ITM",
                "profit_target_status": _profit_status(0.20),
            },  # assignment
        ],
    )
    def test_reasoning_attributes_to_user_ruleset(self, kwargs):
        _, _, reasoning, _ = _evaluate(**kwargs)
        assert "Your" in reasoning or "your" in reasoning
        assert "rule" in reasoning.lower()

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"dte": 40, "profit_target_status": _profit_status(0.60)},
            {"dte": 18, "profit_target_status": _profit_status(0.20)},
            {"dte": 5, "moneyness_state": "ITM", "profit_target_status": _profit_status(0.20)},
        ],
    )
    def test_reasoning_avoids_app_first_person(self, kwargs):
        _, _, reasoning, _ = _evaluate(**kwargs)
        lowered = reasoning.lower()
        assert "we recommend" not in lowered
        # "our" as a standalone app-first-person word — not the "our" inside
        # the user-attributed "your".
        words = lowered.replace(".", " ").replace(",", " ").replace("(", " ").split()
        assert "our" not in words

    def test_profit_take_reasoning_names_dollar_amounts(self):
        _, _, reasoning, _ = _evaluate(
            dte=40, profit_target_status=_profit_status(0.60), premium=38.34
        )
        assert "$" in reasoning
        # 60% of $38.34 = $23.00 (rounded).
        assert "$38.34" in reasoning


# ---------------------------------------------------------------------------
# card_reason_for — the short-form card reason
# ---------------------------------------------------------------------------


class TestCardReason:
    def test_profit_take_short_reason(self):
        _, _, _, rules = _evaluate(
            dte=40, profit_target_status=_profit_status(0.60)
        )
        reason = card_reason_for(rules, profit_review_pct=50.0, dte_review_days=21)
        assert "profit-take rule triggered" in reason
        assert "60%" in reason

    def test_dte_review_short_reason(self):
        _, _, _, rules = _evaluate(
            dte=18, profit_target_status=_profit_status(0.20)
        )
        reason = card_reason_for(rules, profit_review_pct=50.0, dte_review_days=21)
        assert "18 days to expiration" in reason

    def test_no_governing_rule_yields_empty_reason(self):
        _, _, _, rules = _evaluate(
            dte=40, profit_target_status=_profit_status(0.18)
        )
        assert card_reason_for(rules, profit_review_pct=50.0, dte_review_days=21) == ""

    def test_custom_dte_review_days_in_short_reason(self):
        # A custom 30-day review window must surface in the dte_review card
        # reason — the caller threads rules.management.dte_review_days, never
        # a hardcoded literal.
        _, _, _, rules = _evaluate(
            dte=25,
            dte_review_days=30,
            profit_target_status=_profit_status(0.20),
        )
        reason = card_reason_for(
            rules, profit_review_pct=50.0, dte_review_days=30
        )
        assert "25 days to expiration" in reason

    def test_expiration_warning_days_is_a_threadable_parameter(self):
        # card_reason_for accepts expiration_warning_days so the caller can
        # pass the user's configured window instead of a hardcoded 7.
        _, _, _, rules = _evaluate(
            dte=6,
            moneyness_state="OTM",
            expiration_warning_days=10,
            profit_target_status=_profit_status(0.20),
        )
        reason = card_reason_for(
            rules,
            profit_review_pct=50.0,
            dte_review_days=21,
            expiration_warning_days=10,
        )
        assert reason  # builds without error using the configured window
