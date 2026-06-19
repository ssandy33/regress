"""Unit tests for the dashboard Next Actions engine.

The engine is a pure function. These tests exercise:
- each trigger fires only when its precondition holds (positive + negative);
- deterministic ranking across the priority buckets and tie-breakers;
- the cap at 8 entries;
- the no-position scanner-card emit-when-empty rule.

No DB, no HTTP — all data is constructed in-memory.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.action_engine import (
    ITM_SHORT_DTE_CAP,
    MAX_ACTIONS,
    compute_next_actions,
)
from app.services.rules_config import (
    ManagementTriggers,
    RiskRules,
    RulesConfig,
)


def _rules(loss_review_threshold_pct: float) -> RulesConfig:
    """Build a :class:`RulesConfig` with a custom loss-review threshold.

    Other rule groups keep their catalog defaults — only the largest-loser
    flag threshold (``rules_config.risk.loss_review_threshold_pct``) varies.
    The value is whole-percent (e.g. ``-15.0`` for −15%).
    """
    return RulesConfig(
        risk=RiskRules(loss_review_threshold_pct=loss_review_threshold_pct)
    )


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _status(
    *,
    schwab_configured: bool = True,
    schwab_valid: bool = True,
    schwab_expires_at: str | None = None,
    cache_very_stale: int = 0,
) -> dict:
    return {
        "schwab": {
            "configured": schwab_configured,
            "valid": schwab_valid,
            "expires_at": schwab_expires_at,
        },
        "cache": {
            "fresh": 0,
            "stale": 0,
            "very_stale": cache_very_stale,
            "total": cache_very_stale,
        },
        "fred": {"configured": True, "valid": True},
        "journal": {"positions_count": 0},
    }


def _kpis(open_legs: int = 0) -> dict:
    return {"open_legs": open_legs, "open_positions": 0}


def _position(
    position_id: str = "p-1",
    ticker: str = "AAPL",
    *,
    shares: int = 100,
    unrealized_pl: float | None = None,
    pl_pct: float | None = None,
    broker_cost_basis: float | None = None,
) -> dict:
    return {
        "id": position_id,
        "ticker": ticker,
        "shares": shares,
        "unrealized_pl": unrealized_pl,
        "pl_pct": pl_pct,
        "broker_cost_basis": broker_cost_basis,
    }


def _leg(
    leg_id: str,
    *,
    ticker: str = "AAPL",
    type_: str = "put",
    strike: float = 175.0,
    dte: int,
    moneyness_state: str | None = "ITM",
    position_id: str = "p-1",
) -> dict:
    moneyness = None
    if moneyness_state is not None:
        moneyness = {
            "state": moneyness_state,
            "distance_pct": 0.01,
            "distance_dollars": 0.5,
        }
    return {
        "id": leg_id,
        "ticker": ticker,
        "type": type_,
        "strike": strike,
        "expiration": "2026-05-08",
        "dte": dte,
        "moneyness": moneyness,
        "position_id": position_id,
    }


# ---------------------------------------------------------------------------
# Per-trigger tests
# ---------------------------------------------------------------------------


class TestSchwabDisconnectedTrigger:
    @pytest.mark.unit
    def test_emits_when_not_configured(self):
        actions = compute_next_actions(
            status=_status(schwab_configured=False, schwab_valid=False),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "data.schwab_disconnected" in ids

    @pytest.mark.unit
    def test_emits_when_invalid(self):
        actions = compute_next_actions(
            status=_status(schwab_configured=True, schwab_valid=False),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "data.schwab_disconnected" in ids

    @pytest.mark.unit
    def test_does_not_emit_when_healthy(self):
        actions = compute_next_actions(
            status=_status(schwab_configured=True, schwab_valid=True),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "data.schwab_disconnected" not in ids


class TestCacheVeryStaleTrigger:
    @pytest.mark.unit
    def test_emits_when_very_stale_positive(self):
        actions = compute_next_actions(
            status=_status(cache_very_stale=3),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[],
        )
        action = next(a for a in actions if a["action_id"] == "data.cache_very_stale")
        assert action["priority"] == "P0"
        assert action["cta"]["kind"] == "inline"

    @pytest.mark.unit
    def test_does_not_emit_when_no_very_stale(self):
        actions = compute_next_actions(
            status=_status(cache_very_stale=0),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "data.cache_very_stale" not in ids


class TestSchwabTokenExpiringTrigger:
    @pytest.mark.unit
    def test_emits_when_within_threshold(self):
        soon = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        actions = compute_next_actions(
            status=_status(schwab_expires_at=soon),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "data.schwab_token_expiring" in ids

    @pytest.mark.unit
    def test_does_not_emit_when_far_from_expiry(self):
        far = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        actions = compute_next_actions(
            status=_status(schwab_expires_at=far),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "data.schwab_token_expiring" not in ids

    @pytest.mark.unit
    def test_does_not_emit_immediately_after_fresh_seven_day_grant(self):
        # Regression: Schwab refresh tokens last exactly 7 days. A 7-day
        # threshold here caused the P1 "Renew Schwab token" card to fire
        # right after every re-auth, displaying "in 6 days" because
        # ``delta.days`` floor-truncates. The threshold lives in
        # ``TOKEN_EXPIRING_DAYS`` and must be strictly below the token
        # lifetime so fresh grants are silent.
        fresh = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        actions = compute_next_actions(
            status=_status(schwab_expires_at=fresh),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "data.schwab_token_expiring" not in ids

    @pytest.mark.unit
    def test_does_not_emit_when_disconnected(self):
        # Disconnected case is handled by `data.schwab_disconnected`. No
        # double-emit when both conditions hold.
        soon = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        actions = compute_next_actions(
            status=_status(schwab_configured=False, schwab_expires_at=soon),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "data.schwab_token_expiring" not in ids


class TestLargeLoserTrigger:
    @pytest.mark.unit
    def test_emits_at_default_pct_threshold_minus_fifteen_pct(self):
        # Whichever-fires-first: the default loss-review threshold (-15%)
        # trips even when dollars are small. With no `rules` override the
        # engine uses the catalog default (issue #235).
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[
                _position("p-loser", "TSLA", unrealized_pl=-50.0, pl_pct=-0.15),
            ],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "position.large_loser" in ids

    @pytest.mark.unit
    def test_emits_at_dollar_threshold_minus_1000(self):
        # Whichever-fires-first: -$1000 trips even at -1% basis. The dollar
        # trigger is a hardcoded heuristic, independent of the rules config.
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[
                _position("p-loser", "AMZN", unrealized_pl=-1000.0, pl_pct=-0.01),
            ],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "position.large_loser" in ids

    @pytest.mark.unit
    def test_does_not_emit_just_below_thresholds(self):
        # -14.9% and -$999 should NOT trigger under the default -15% rule.
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[
                _position("p-ok", "MSFT", unrealized_pl=-999.0, pl_pct=-0.149),
            ],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "position.large_loser" not in ids

    @pytest.mark.unit
    def test_default_rule_does_not_emit_between_5_and_15_pct(self):
        # Issue #235: the old hardcoded -5% constant is gone. An -8% loser
        # — between the retired -5% and the configured -15% — must NOT flag
        # under default rules, proving the migration to rules_config landed.
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[
                _position("p-mild", "NVDA", unrealized_pl=-200.0, pl_pct=-0.08),
            ],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "position.large_loser" not in ids

    @pytest.mark.unit
    def test_largest_loser_honors_configured_loss_review_threshold(self):
        # Issue #235: a stricter-than-default threshold (-5%) flags an -8%
        # loser that the default -15% rule would leave alone — proving the
        # card is wired to rules_config.risk.loss_review_threshold_pct.
        position = _position("p-mild", "NVDA", unrealized_pl=-200.0, pl_pct=-0.08)
        # Default -15% rule: not flagged.
        default_actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[position],
            open_legs=[],
        )
        assert "position.large_loser" not in {
            a["action_id"] for a in default_actions
        }
        # Stored -5% rule: flagged.
        strict_actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[position],
            open_legs=[],
            rules=_rules(-5.0),
        )
        assert "position.large_loser" in {
            a["action_id"] for a in strict_actions
        }

    @pytest.mark.unit
    def test_reason_copy_reflects_configured_threshold_no_hardcoded_pct(self):
        # Issue #235: the card's `reason` string must report the configured
        # threshold, never a hardcoded "-5%". Here a stored -20% rule.
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[
                _position("p-loser", "TSLA", unrealized_pl=-3000.0, pl_pct=-0.25),
            ],
            open_legs=[],
            rules=_rules(-20.0),
        )
        loser_card = next(
            a for a in actions if a["action_id"] == "position.large_loser"
        )
        assert "-20%" in loser_card["reason"]
        assert "-5%" not in loser_card["reason"]

    @pytest.mark.unit
    def test_only_single_largest_loser_emitted(self):
        # Three losers — engine surfaces only the worst.
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[
                _position("p-a", "AAA", unrealized_pl=-500.0, pl_pct=-0.20),
                _position("p-b", "BBB", unrealized_pl=-2000.0, pl_pct=-0.30),
                _position("p-c", "CCC", unrealized_pl=-1500.0, pl_pct=-0.25),
            ],
            open_legs=[],
        )
        loser_cards = [a for a in actions if a["action_id"] == "position.large_loser"]
        assert len(loser_cards) == 1
        assert loser_cards[0]["subject"]["ticker"] == "BBB"

    @pytest.mark.unit
    def test_cta_href_points_at_recovery_plan_route(self):
        # V0.5.8 (#182): the loser CTA destination flipped from the journal
        # filter page to the Recovery Plan route. Both shipped in the same
        # PR so the link does not 404 between deploys.
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[
                _position("p-loser", "TSLA", unrealized_pl=-2000.0, pl_pct=-0.20),
            ],
            open_legs=[],
        )
        loser_card = next(a for a in actions if a["action_id"] == "position.large_loser")
        assert loser_card["cta"]["href"] == "/positions/p-loser/recovery"
        assert "/journal?position=" not in loser_card["cta"]["href"]


class TestItmShortDteTrigger:
    @pytest.mark.unit
    def test_emits_when_itm_and_short_dte(self):
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[_leg("l-1", dte=3, moneyness_state="ITM")],
        )
        ids = {a["action_id"] for a in actions}
        assert "expiration.itm_short_dte" in ids

    @pytest.mark.unit
    def test_does_not_emit_at_exact_boundary_eight_dte(self):
        # 8 DTE is outside the ≤ 7 window — no per-leg ITM card.
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[_leg("l-1", dte=8, moneyness_state="ITM")],
        )
        ids = {a["action_id"] for a in actions}
        assert "expiration.itm_short_dte" not in ids

    @pytest.mark.unit
    def test_capped_at_three(self):
        legs = [
            _leg(f"l-{i}", dte=i, moneyness_state="ITM", position_id=f"p-{i}")
            for i in range(1, 7)
        ]
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=len(legs)),
            positions=[],
            open_legs=legs,
        )
        cards = [a for a in actions if a["action_id"] == "expiration.itm_short_dte"]
        assert len(cards) == ITM_SHORT_DTE_CAP


class TestShortDteAggregateTrigger:
    @pytest.mark.unit
    def test_aggregates_one_per_ticker_when_otm(self):
        # Two OTM short-DTE legs on AAPL → one card.
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=2),
            positions=[],
            open_legs=[
                _leg("l-1", dte=3, moneyness_state="OTM"),
                _leg("l-2", dte=5, moneyness_state="OTM"),
            ],
        )
        cards = [a for a in actions if a["action_id"] == "expiration.short_dte"]
        assert len(cards) == 1
        # Carries leg count in the subject amount.
        assert "2 legs" in cards[0]["subject"]["amount"]

    @pytest.mark.unit
    def test_does_not_emit_when_itm(self):
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[_leg("l-1", dte=3, moneyness_state="ITM")],
        )
        ids = {a["action_id"] for a in actions}
        assert "expiration.short_dte" not in ids


class TestCcCandidateTrigger:
    @pytest.mark.unit
    def test_emits_for_position_with_shares_and_no_open_call(self):
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[_position("p-aapl", "AAPL", shares=100)],
            open_legs=[_leg("l-1", ticker="AAPL", type_="put", dte=30, moneyness_state="OTM")],
        )
        ids = {a["action_id"] for a in actions}
        assert "position.cc_candidate" in ids

    @pytest.mark.unit
    def test_does_not_emit_when_open_call_exists(self):
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[_position("p-aapl", "AAPL", shares=100)],
            open_legs=[_leg("l-1", ticker="AAPL", type_="call", dte=30, moneyness_state="OTM")],
        )
        ids = {a["action_id"] for a in actions}
        assert "position.cc_candidate" not in ids

    @pytest.mark.unit
    def test_does_not_emit_for_less_than_100_shares(self):
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[_position("p-aapl", "AAPL", shares=50)],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "position.cc_candidate" not in ids

    @pytest.mark.unit
    def test_cc_candidate_href_carries_context(self):
        """The CTA href hands off strategy, shares, and cost basis to the scanner."""
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=0),
            positions=[
                _position(
                    "p-aapl",
                    "AAPL",
                    shares=100,
                    broker_cost_basis=17240.0,
                )
            ],
            open_legs=[],
        )
        card = next(a for a in actions if a["action_id"] == "position.cc_candidate")
        href = card["cta"]["href"]
        assert "ticker=AAPL" in href
        assert "strategy=covered_call" in href
        assert "shares=100" in href
        # cost_basis is emitted PER-SHARE (issue #186) — scanner expects that
        # unit. 17240.0 total / 100 shares = 172.4 per share.
        assert "cost_basis=172.4" in href
        # Must never emit the raw total — that breaks the 10% rule downstream.
        assert "cost_basis=17240" not in href

    @pytest.mark.unit
    def test_cc_candidate_href_emits_per_share_basis_canonical_f_case(self):
        """Regression for #186: F at 100 shares with broker_cost_basis=$1,320.66
        must emit cost_basis=13.2066 per-share, not the raw total.

        Pre-fix the scanner's 10%-rule floor became 1320.66 * 1.01 ~= $1,333,
        rejecting every realistic F strike.
        """
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=0),
            positions=[
                _position(
                    "p-f",
                    "F",
                    shares=100,
                    broker_cost_basis=1320.66,
                )
            ],
            open_legs=[],
        )
        card = next(a for a in actions if a["action_id"] == "position.cc_candidate")
        href = card["cta"]["href"]
        assert "cost_basis=13.2066" in href
        assert "cost_basis=1320.66" not in href
        # Regression for #188: no IEEE 754 float-noise tail in the URL.
        assert "13.206600000000002" not in href
        assert "13.20660000000001" not in href

    @pytest.mark.unit
    @pytest.mark.skip(
        reason=(
            "Manual AC from #186: clicking 'Scan F →' on the dashboard yields "
            "a scanner result with at least one non-rejected strike. Requires "
            "live option-chain data from Schwab, not automatable in unit tests."
        )
    )
    def test_manual_ac_cc_candidate_yields_non_rejected_strike(self):
        pass

    @pytest.mark.unit
    def test_cc_candidate_href_omits_cost_basis_when_null(self):
        """Null broker_cost_basis must omit the cost_basis param entirely."""
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=0),
            positions=[
                _position(
                    "p-aapl",
                    "AAPL",
                    shares=100,
                    broker_cost_basis=None,
                )
            ],
            open_legs=[],
        )
        card = next(a for a in actions if a["action_id"] == "position.cc_candidate")
        href = card["cta"]["href"]
        assert "ticker=AAPL" in href
        assert "strategy=covered_call" in href
        assert "shares=100" in href
        assert "cost_basis" not in href


class TestNoOpenLegsTrigger:
    @pytest.mark.unit
    def test_emits_when_zero_open_legs(self):
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=0),
            positions=[],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "journal.no_open_legs" in ids

    @pytest.mark.unit
    def test_emits_when_positions_exist_but_zero_legs(self):
        # Locked decision: emit even when positions exist but kpis.open_legs == 0.
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=0),
            positions=[_position("p-1", "AAPL")],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "journal.no_open_legs" in ids

    @pytest.mark.unit
    def test_does_not_emit_when_legs_exist(self):
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[_leg("l-1", dte=10, moneyness_state="OTM")],
        )
        ids = {a["action_id"] for a in actions}
        assert "journal.no_open_legs" not in ids


# ---------------------------------------------------------------------------
# Ranking / determinism
# ---------------------------------------------------------------------------


class TestRanking:
    @pytest.mark.unit
    def test_p0_data_above_p0_position(self):
        # Spec §14.7: within P0, `data.*` outranks `position.*`.
        actions = compute_next_actions(
            status=_status(cache_very_stale=2),
            kpis=_kpis(open_legs=1),
            positions=[_position("p-1", "AAA", unrealized_pl=-2000.0, pl_pct=-0.10)],
            open_legs=[],
        )
        # The first P0 action is the cache card.
        first_p0 = next(a for a in actions if a["priority"] == "P0")
        assert first_p0["action_id"] == "data.cache_very_stale"

    @pytest.mark.unit
    def test_p0_above_p1(self):
        actions = compute_next_actions(
            status=_status(schwab_configured=False, schwab_valid=False),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[_leg("l-1", dte=3, moneyness_state="ITM")],
        )
        priorities = [a["priority"] for a in actions]
        # Once we see a P1 the remaining actions must not be P0.
        seen_p1 = False
        for p in priorities:
            if p == "P1":
                seen_p1 = True
            if seen_p1 and p == "P0":
                raise AssertionError("P0 found after a P1 — ranking is broken")

    @pytest.mark.unit
    def test_p1_expiration_sorted_by_dte_ascending(self):
        legs = [
            _leg("l-7", dte=7, moneyness_state="ITM", position_id="p-7"),
            _leg("l-3", dte=3, moneyness_state="ITM", position_id="p-3"),
            _leg("l-5", dte=5, moneyness_state="ITM", position_id="p-5"),
        ]
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=3),
            positions=[],
            open_legs=legs,
        )
        cards = [a for a in actions if a["action_id"] == "expiration.itm_short_dte"]
        leg_ids = [a["id"].split(".")[-1] for a in cards]
        assert leg_ids == ["l-3", "l-5", "l-7"]

    @pytest.mark.unit
    def test_p2_cc_before_scanner(self):
        # Both P2 cards in the same payload — covered call ranks first.
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=0),
            positions=[_position("p-aapl", "AAPL", shares=100)],
            open_legs=[],
        )
        p2_ids = [a["action_id"] for a in actions if a["priority"] == "P2"]
        assert p2_ids.index("position.cc_candidate") < p2_ids.index(
            "journal.no_open_legs"
        )

    @pytest.mark.unit
    def test_p2_cc_candidates_sorted_alphabetically(self):
        positions = [
            _position("p-tsla", "TSLA", shares=100),
            _position("p-aapl", "AAPL", shares=100),
            _position("p-msft", "MSFT", shares=100),
        ]
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=positions,
            open_legs=[],
        )
        tickers = [
            a["subject"]["ticker"]
            for a in actions
            if a["action_id"] == "position.cc_candidate"
        ]
        assert tickers == ["AAPL", "MSFT", "TSLA"]

    @pytest.mark.unit
    def test_deterministic_across_runs(self):
        # Same inputs → same outputs across 100 runs.
        positions = [
            _position("p-loser", "TSLA", unrealized_pl=-2000.0, pl_pct=-0.10),
            _position("p-aapl", "AAPL", shares=100),
        ]
        legs = [
            _leg("l-1", ticker="AAPL", dte=3, moneyness_state="ITM", position_id="p-aapl"),
            _leg("l-2", ticker="TSLA", dte=10, moneyness_state="OTM", position_id="p-loser"),
        ]
        first = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=2),
            positions=positions,
            open_legs=legs,
        )
        for _ in range(99):
            again = compute_next_actions(
                status=_status(),
                kpis=_kpis(open_legs=2),
                positions=positions,
                open_legs=legs,
            )
            assert again == first

    @pytest.mark.unit
    def test_capped_at_max(self):
        # Stuff every bucket; ensure the engine truncates at MAX_ACTIONS.
        legs = [
            _leg(f"l-{i}", ticker=f"T{i}", dte=i, moneyness_state="ITM", position_id=f"p-{i}")
            for i in range(1, 8)
        ]
        positions = [
            _position(f"p-cc-{i}", f"CC{i}", shares=100) for i in range(20)
        ]
        actions = compute_next_actions(
            status=_status(schwab_configured=False, schwab_valid=False, cache_very_stale=4),
            kpis=_kpis(open_legs=len(legs)),
            positions=positions,
            open_legs=legs,
        )
        assert len(actions) <= MAX_ACTIONS


class TestActionShape:
    @pytest.mark.unit
    def test_id_is_action_id_dot_subject_id(self):
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=0),
            positions=[],
            open_legs=[],
        )
        scanner = next(a for a in actions if a["action_id"] == "journal.no_open_legs")
        assert scanner["id"].startswith("journal.no_open_legs.")

    @pytest.mark.unit
    def test_cta_kind_inline_only_for_cache_refresh(self):
        actions = compute_next_actions(
            status=_status(cache_very_stale=1),
            kpis=_kpis(open_legs=0),
            positions=[],
            open_legs=[],
        )
        for action in actions:
            if action["action_id"] == "data.cache_very_stale":
                assert action["cta"]["kind"] == "inline"
            else:
                assert action["cta"]["kind"] == "link"

    @pytest.mark.unit
    def test_priority_is_string_label(self):
        actions = compute_next_actions(
            status=_status(schwab_configured=False, schwab_valid=False),
            kpis=_kpis(open_legs=0),
            positions=[],
            open_legs=[],
        )
        for action in actions:
            assert action["priority"] in {"P0", "P1", "P2"}


# ---------------------------------------------------------------------------
# §R6 rule-monitor leg cards (issue #240)
# ---------------------------------------------------------------------------


def _verdict_leg(
    leg_id: str,
    *,
    verdict: str,
    ticker: str = "F",
    type_: str = "call",
    strike: float = 15.0,
    dte: int = 38,
    moneyness_state: str | None = "OTM",
    position_id: str = "p-1",
) -> dict:
    """Build a leg dict carrying the §R6 verdict layer (issue #240).

    ``triggered_rules`` is a minimal but realistic payload — one governing
    rule plus the other three rows — so card builders that read it (for the
    short reason) have a real source to parse.
    """
    leg = _leg(
        leg_id,
        ticker=ticker,
        type_=type_,
        strike=strike,
        dte=dte,
        moneyness_state=moneyness_state,
        position_id=position_id,
    )
    governing_rule_id = {
        "profit_take_review": "profit_review",
        "dte_review": "dte_review",
        "expiration": "expiration_warning",
        "assignment": "assignment_risk",
    }.get(verdict)
    triggered_rules = [
        {
            "rule_id": "assignment_risk",
            "metric_label": "Assignment risk",
            "value_display": "OTM",
            "rule_display": "Review at ≥ High",
            "status": "no",
            "is_governing": False,
            "reasoning": None,
        },
        {
            "rule_id": "expiration_warning",
            "metric_label": "Days to expiration",
            "value_display": f"{dte} d",
            "rule_display": "Warn at ≤ 7 d",
            "status": "not_yet",
            "is_governing": False,
            "reasoning": None,
        },
        {
            "rule_id": "profit_review",
            "metric_label": "Premium captured",
            "value_display": "60%",
            "rule_display": "Review at ≥ 50%",
            "status": "triggered" if verdict == "profit_take_review" else "not_yet",
            "is_governing": verdict == "profit_take_review",
            "reasoning": None,
        },
        {
            "rule_id": "dte_review",
            "metric_label": "Days to expiration",
            "value_display": f"{dte} d",
            "rule_display": "Review at ≤ 21 d",
            "status": "triggered" if verdict == "dte_review" else "not_yet",
            "is_governing": verdict == "dte_review",
            "reasoning": None,
        },
    ]
    for row in triggered_rules:
        if row["rule_id"] == governing_rule_id:
            row["is_governing"] = True
            row["status"] = "triggered"
            row["reasoning"] = "Your rule triggered."
    leg["verdict"] = verdict
    leg["verdict_label"] = "Review · 50%"
    leg["reasoning"] = "Your rule triggered."
    leg["triggered_rules"] = triggered_rules
    return leg


class TestProfitTakeReviewCard:
    @pytest.mark.unit
    def test_emits_when_verdict_is_profit_take_review(self):
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[_verdict_leg("l-1", verdict="profit_take_review")],
        )
        cards = [a for a in actions if a["action_id"] == "leg.profit_take_review"]
        assert len(cards) == 1
        card = cards[0]
        assert card["priority"] == "P1"
        assert card["tone"] == "opportunity"
        assert card["id"] == "leg.profit_take_review.l-1"
        assert card["triggered_rules"]

    @pytest.mark.unit
    def test_card_cta_links_to_btc_detail_route(self):
        # Issue #244 — the CTA repoints from the dead `/dashboard#leg-{id}`
        # hash to the dedicated per-leg buy-to-close detail route.
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[_verdict_leg("l-1", verdict="profit_take_review")],
        )
        card = next(a for a in actions if a["action_id"] == "leg.profit_take_review")
        assert card["cta"]["href"] == "/positions/p-1/legs/l-1/btc"

    @pytest.mark.unit
    def test_not_emitted_for_hold_verdict(self):
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[_verdict_leg("l-1", verdict="hold")],
        )
        ids = {a["action_id"] for a in actions}
        assert "leg.profit_take_review" not in ids

    @pytest.mark.unit
    def test_card_title_and_cta_use_buy_to_close_vocabulary(self):
        """Issue #249 — the card title and CTA label name the destination
        screen, not the rule audit sub-section. Locks the vocabulary contract:
        card title, CTA, and the destination page <h1> all use the same
        ``Buy-to-close review`` language.
        """
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[_verdict_leg("l-1", verdict="profit_take_review")],
        )
        card = next(a for a in actions if a["action_id"] == "leg.profit_take_review")
        assert card["title"] == "Buy-to-close review"
        assert card["cta"]["label"] == "Review buy-to-close"


class TestDteReviewCard:
    @pytest.mark.unit
    def test_emits_when_verdict_is_dte_review(self):
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[_verdict_leg("l-1", verdict="dte_review", dte=18)],
        )
        cards = [a for a in actions if a["action_id"] == "leg.dte_review"]
        assert len(cards) == 1
        card = cards[0]
        assert card["priority"] == "P2"
        # No tone key → schema default "warning" applies.
        assert card.get("tone", "warning") == "warning"
        assert card["id"] == "leg.dte_review.l-1"

    @pytest.mark.unit
    def test_not_emitted_for_profit_take_verdict(self):
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[_verdict_leg("l-1", verdict="profit_take_review")],
        )
        ids = {a["action_id"] for a in actions}
        assert "leg.dte_review" not in ids

    @pytest.mark.unit
    def test_cta_label_uses_buy_to_close_vocabulary(self):
        """Issue #249 — DTE-review CTA also names the destination. The card
        title (``{N}-day review``) is intentionally retained — it describes
        the trigger window, not the destination (design spec §2).
        """
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[_verdict_leg("l-1", verdict="dte_review", dte=18)],
        )
        card = next(a for a in actions if a["action_id"] == "leg.dte_review")
        assert card["cta"]["label"] == "Review buy-to-close"
        # Title intentionally NOT renamed — it names the trigger window
        # (``dte_review_days`` default = 21), not the destination screen.
        assert card["title"] == "21-day review"


class TestRuleMonitorCardPrecedence:
    @pytest.mark.unit
    def test_itm_short_dte_leg_emits_only_expiration_card(self):
        # A 5-DTE ITM leg: verdict is "assignment" (the §R6 governing rule).
        # The legacy expiration.itm_short_dte builder still fires on its own
        # DTE/moneyness gating; the two new builders skip it.
        leg = _verdict_leg(
            "l-1", verdict="assignment", dte=5, moneyness_state="ITM"
        )
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[leg],
        )
        ids = {a["action_id"] for a in actions}
        assert "expiration.itm_short_dte" in ids
        assert "leg.profit_take_review" not in ids
        assert "leg.dte_review" not in ids

    @pytest.mark.unit
    def test_profit_take_leg_inside_dte_window_emits_only_profit_card(self):
        # 18-DTE leg, 60% captured: profit-take governs (verdict drives it),
        # so no leg.dte_review card despite the 21d window also matching.
        leg = _verdict_leg(
            "l-1", verdict="profit_take_review", dte=18, moneyness_state="OTM"
        )
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[leg],
        )
        ids = {a["action_id"] for a in actions}
        assert "leg.profit_take_review" in ids
        assert "leg.dte_review" not in ids


class TestExpirationCardsUnaffected:
    """Regression guard — the existing expiration.* cards are byte-identical
    after the new §R6 builders land (spec §10 cross-cutting AC).
    """

    @pytest.mark.unit
    def test_mixed_leg_set_expiration_cards_unchanged(self):
        legs = [
            # ITM short-DTE → expiration.itm_short_dte
            _verdict_leg(
                "l-itm", verdict="assignment", dte=4, moneyness_state="ITM",
                ticker="SOFI", position_id="p-sofi",
            ),
            # OTM short-DTE → expiration.short_dte (aggregate)
            _verdict_leg(
                "l-otm", verdict="expiration", dte=6, moneyness_state="OTM",
                ticker="MSFT", position_id="p-msft",
            ),
            # Profit-take leg → leg.profit_take_review only
            _verdict_leg(
                "l-pt", verdict="profit_take_review", dte=38, moneyness_state="OTM",
                ticker="F", position_id="p-f",
            ),
        ]
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=len(legs)),
            positions=[],
            open_legs=legs,
        )
        itm = [a for a in actions if a["action_id"] == "expiration.itm_short_dte"]
        short = [a for a in actions if a["action_id"] == "expiration.short_dte"]
        assert len(itm) == 1
        assert itm[0]["id"] == "expiration.itm_short_dte.l-itm"
        assert len(short) == 1
        assert short[0]["id"] == "expiration.short_dte.msft"


class TestRuleMonitorCardSort:
    @pytest.mark.unit
    def test_expiration_card_sorts_before_profit_take_within_p1(self):
        legs = [
            _verdict_leg(
                "l-pt", verdict="profit_take_review", dte=10, moneyness_state="OTM",
                ticker="F", position_id="p-f",
            ),
            _verdict_leg(
                "l-itm", verdict="assignment", dte=3, moneyness_state="ITM",
                ticker="SOFI", position_id="p-sofi",
            ),
        ]
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=len(legs)),
            positions=[],
            open_legs=legs,
        )
        order = [a["action_id"] for a in actions]
        assert order.index("expiration.itm_short_dte") < order.index(
            "leg.profit_take_review"
        )

    @pytest.mark.unit
    def test_dte_review_card_sorts_in_p2(self):
        legs = [
            _verdict_leg(
                "l-dte", verdict="dte_review", dte=18, moneyness_state="OTM",
                ticker="AAPL", position_id="p-aapl",
            ),
        ]
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=len(legs)),
            positions=[],
            open_legs=legs,
        )
        dte_card = next(a for a in actions if a["action_id"] == "leg.dte_review")
        assert dte_card["priority"] == "P2"


class TestProfitTakeCardThreadsManagementThresholds:
    """The profit-take card reason must be built from the user's *actual*
    configured ``rules.management`` thresholds — never a hardcoded literal
    (CodeRabbit fix: ``dte_review_days``/``expiration_warning_days``).
    """

    @pytest.mark.unit
    def test_custom_dte_review_days_flows_into_profit_take_card_reason(
        self, monkeypatch
    ):
        # Spy on card_reason_for to capture the kwargs the profit-take builder
        # threads through — proves the configured value reaches the reason
        # builder rather than a stale literal 21.
        captured: dict = {}
        from app.services import action_engine as _ae

        real_card_reason_for = _ae.card_reason_for

        def _spy(triggered_rules, **kwargs):
            captured.update(kwargs)
            return real_card_reason_for(triggered_rules, **kwargs)

        monkeypatch.setattr(_ae, "card_reason_for", _spy)

        rules = RulesConfig(
            management=ManagementTriggers(
                dte_review_days=30, expiration_warning_days=10
            )
        )
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[_verdict_leg("l-1", verdict="profit_take_review")],
            rules=rules,
        )
        card = next(a for a in actions if a["action_id"] == "leg.profit_take_review")
        assert card["reason"]  # a reason was built
        # The builder passed the configured thresholds, not hardcoded 21 / 7.
        assert captured["dte_review_days"] == 30
        assert captured["expiration_warning_days"] == 10



# ---------------------------------------------------------------------------
# Issue #164 — large_loser subject must use a single space, not double
# ---------------------------------------------------------------------------


class TestLargeLoserSubjectSpacingIssue164:
    """``position.large_loser`` ``subject.amount`` uses a single space.

    Prior code rendered ``"AAPL  -$1,234 (-12.3%)"`` (two spaces) because
    the f-string template hardcoded ``"{ticker}  {amount_dollars}"``. The
    frontend prints the string verbatim, so the double space was a visible
    cosmetic defect.
    """

    @pytest.mark.unit
    def test_subject_amount_uses_single_space_with_pct(self):
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[
                _position("p-loser", "TSLA", unrealized_pl=-2000.0, pl_pct=-0.20),
            ],
            open_legs=[],
        )
        loser = next(
            a for a in actions if a["action_id"] == "position.large_loser"
        )
        amount = loser["subject"]["amount"]
        assert amount.startswith("TSLA -$"), (
            f"expected 'TSLA -$' prefix (single space), got {amount!r}"
        )
        assert "  " not in amount, (
            f"subject.amount must not contain a double space: {amount!r}"
        )

    @pytest.mark.unit
    def test_subject_amount_uses_single_space_when_pct_is_none(self):
        # The no-pct branch hits the alternate f-string at L296 — same
        # spacing rule must hold even though the trailing ``({pct})`` is
        # absent from the rendered string.
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[
                _position("p-loser", "AMZN", unrealized_pl=-1500.0, pl_pct=None),
            ],
            open_legs=[],
        )
        loser = next(
            a for a in actions if a["action_id"] == "position.large_loser"
        )
        amount = loser["subject"]["amount"]
        # No pct → string ends after the dollar amount, no parens.
        assert amount.startswith("AMZN -$")
        assert "(" not in amount
        assert "  " not in amount, (
            f"subject.amount must not contain a double space: {amount!r}"
        )


# ---------------------------------------------------------------------------
# Issue #375 — expiration-urgency cards route to the per-leg BTC decision
# screen instead of dead-ending on the Journal positions table.
# ---------------------------------------------------------------------------


class TestItmShortDteRoutesToBtc:
    """`expiration.itm_short_dte` CTA targets the per-leg BTC route (#375)."""

    @pytest.mark.unit
    def test_itm_short_dte_cta_links_to_btc_route(self):
        # C-1 — a single ITM short-DTE leg routes to its own BTC screen,
        # byte-identical to the buy-to-close cards' route.
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[_leg("l-1", dte=3, moneyness_state="ITM", position_id="p-1")],
        )
        card = next(
            a for a in actions if a["action_id"] == "expiration.itm_short_dte"
        )
        assert card["cta"]["href"] == "/positions/p-1/legs/l-1/btc"

    @pytest.mark.unit
    def test_itm_short_dte_cta_not_journal(self):
        # C-2 — the dead-end Journal destination is gone.
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[_leg("l-1", dte=3, moneyness_state="ITM", position_id="p-1")],
        )
        card = next(
            a for a in actions if a["action_id"] == "expiration.itm_short_dte"
        )
        assert "/journal?position=" not in card["cta"]["href"]


class TestShortDteAggregateRoutesToBtc:
    """`expiration.short_dte` aggregate CTA targets the min-DTE leg's BTC
    route while keeping its aggregated summary subject + id (#375)."""

    @pytest.mark.unit
    def test_short_dte_aggregate_cta_links_to_min_dte_leg_btc(self):
        # C-3 — two OTM legs on one ticker; the aggregate card routes to the
        # most-urgent (min-DTE) leg, l-2 (dte=3), not l-1 (dte=5).
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=2),
            positions=[],
            open_legs=[
                _leg("l-1", dte=5, moneyness_state="OTM", position_id="p-1"),
                _leg("l-2", dte=3, moneyness_state="OTM", position_id="p-1"),
            ],
        )
        card = next(
            a for a in actions if a["action_id"] == "expiration.short_dte"
        )
        assert card["cta"]["href"] == "/positions/p-1/legs/l-2/btc"

    @pytest.mark.unit
    def test_short_dte_aggregate_cta_not_journal(self):
        # C-4 — the dead-end Journal destination is gone.
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=2),
            positions=[],
            open_legs=[
                _leg("l-1", dte=5, moneyness_state="OTM", position_id="p-1"),
                _leg("l-2", dte=3, moneyness_state="OTM", position_id="p-1"),
            ],
        )
        card = next(
            a for a in actions if a["action_id"] == "expiration.short_dte"
        )
        assert "/journal?position=" not in card["cta"]["href"]

    @pytest.mark.unit
    def test_short_dte_aggregate_retains_summary_subject_text(self):
        # C-5 — the aggregated summary subject ("N legs ≤ X DTE") and the card
        # id are unchanged by the routing fix (no regression of the summary).
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=2),
            positions=[],
            open_legs=[
                _leg("l-1", dte=5, moneyness_state="OTM", position_id="p-1"),
                _leg("l-2", dte=3, moneyness_state="OTM", position_id="p-1"),
            ],
        )
        card = next(
            a for a in actions if a["action_id"] == "expiration.short_dte"
        )
        assert card["subject"]["amount"] == "2 legs ≤ 7 DTE"
        assert card["id"] == "expiration.short_dte.aapl"

    @pytest.mark.unit
    def test_short_dte_min_dte_tiebreak_first_seen(self):
        # C-6 — two OTM legs at the same min DTE; the first-seen leg (l-1)
        # wins the tie (strict `<`, deterministic), so the aggregate routes
        # to l-1, not l-2.
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=2),
            positions=[],
            open_legs=[
                _leg("l-1", dte=3, moneyness_state="OTM", position_id="p-1"),
                _leg("l-2", dte=3, moneyness_state="OTM", position_id="p-1"),
            ],
        )
        card = next(
            a for a in actions if a["action_id"] == "expiration.short_dte"
        )
        assert card["cta"]["href"] == "/positions/p-1/legs/l-1/btc"

    @pytest.mark.unit
    def test_short_dte_aggregate_multi_position_same_ticker(self):
        # C-7 — legs on different positions but the same ticker; the aggregate
        # href must use the min-DTE leg's OWN position_id + id (guards the
        # position_id/leg_id pairing, not a cross-leg mix).
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=2),
            positions=[],
            open_legs=[
                _leg("l-1", dte=6, moneyness_state="OTM", position_id="p-1"),
                _leg("l-2", dte=2, moneyness_state="OTM", position_id="p-2"),
            ],
        )
        card = next(
            a for a in actions if a["action_id"] == "expiration.short_dte"
        )
        assert card["cta"]["href"] == "/positions/p-2/legs/l-2/btc"
