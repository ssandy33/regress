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
    def test_emits_when_not_configured(self):
        actions = compute_next_actions(
            status=_status(schwab_configured=False, schwab_valid=False),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "data.schwab_disconnected" in ids

    def test_emits_when_invalid(self):
        actions = compute_next_actions(
            status=_status(schwab_configured=True, schwab_valid=False),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "data.schwab_disconnected" in ids

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
    def test_emits_within_seven_days(self):
        soon = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        actions = compute_next_actions(
            status=_status(schwab_expires_at=soon),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "data.schwab_token_expiring" in ids

    def test_does_not_emit_when_more_than_seven_days(self):
        far = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        actions = compute_next_actions(
            status=_status(schwab_expires_at=far),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "data.schwab_token_expiring" not in ids

    def test_does_not_emit_when_disconnected(self):
        # Disconnected case is handled by `data.schwab_disconnected`. No
        # double-emit when both conditions hold.
        soon = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        actions = compute_next_actions(
            status=_status(schwab_configured=False, schwab_expires_at=soon),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "data.schwab_token_expiring" not in ids


class TestLargeLoserTrigger:
    def test_emits_at_pct_threshold_minus_five_pct(self):
        # Whichever-fires-first: -5% trips even when dollars are small.
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[
                _position("p-loser", "TSLA", unrealized_pl=-50.0, pl_pct=-0.05),
            ],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "position.large_loser" in ids

    def test_emits_at_dollar_threshold_minus_1000(self):
        # Whichever-fires-first: -$1000 trips even at -1% basis.
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

    def test_does_not_emit_just_below_thresholds(self):
        # -4.9% and -$999 should NOT trigger.
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[
                _position("p-ok", "MSFT", unrealized_pl=-999.0, pl_pct=-0.049),
            ],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "position.large_loser" not in ids

    def test_only_single_largest_loser_emitted(self):
        # Three losers — engine surfaces only the worst.
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[
                _position("p-a", "AAA", unrealized_pl=-500.0, pl_pct=-0.10),
                _position("p-b", "BBB", unrealized_pl=-2000.0, pl_pct=-0.20),
                _position("p-c", "CCC", unrealized_pl=-1500.0, pl_pct=-0.15),
            ],
            open_legs=[],
        )
        loser_cards = [a for a in actions if a["action_id"] == "position.large_loser"]
        assert len(loser_cards) == 1
        assert loser_cards[0]["subject"]["ticker"] == "BBB"


class TestItmShortDteTrigger:
    def test_emits_when_itm_and_short_dte(self):
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[],
            open_legs=[_leg("l-1", dte=3, moneyness_state="ITM")],
        )
        ids = {a["action_id"] for a in actions}
        assert "expiration.itm_short_dte" in ids

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
    def test_emits_for_position_with_shares_and_no_open_call(self):
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[_position("p-aapl", "AAPL", shares=100)],
            open_legs=[_leg("l-1", ticker="AAPL", type_="put", dte=30, moneyness_state="OTM")],
        )
        ids = {a["action_id"] for a in actions}
        assert "position.cc_candidate" in ids

    def test_does_not_emit_when_open_call_exists(self):
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[_position("p-aapl", "AAPL", shares=100)],
            open_legs=[_leg("l-1", ticker="AAPL", type_="call", dte=30, moneyness_state="OTM")],
        )
        ids = {a["action_id"] for a in actions}
        assert "position.cc_candidate" not in ids

    def test_does_not_emit_for_less_than_100_shares(self):
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=1),
            positions=[_position("p-aapl", "AAPL", shares=50)],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "position.cc_candidate" not in ids

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

    @pytest.mark.skip(
        reason=(
            "Manual AC from #186: clicking 'Scan F →' on the dashboard yields "
            "a scanner result with at least one non-rejected strike. Requires "
            "live option-chain data from Schwab, not automatable in unit tests."
        )
    )
    def test_manual_ac_cc_candidate_yields_non_rejected_strike(self):
        pass

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
    def test_emits_when_zero_open_legs(self):
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=0),
            positions=[],
            open_legs=[],
        )
        ids = {a["action_id"] for a in actions}
        assert "journal.no_open_legs" in ids

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
    def test_id_is_action_id_dot_subject_id(self):
        actions = compute_next_actions(
            status=_status(),
            kpis=_kpis(open_legs=0),
            positions=[],
            open_legs=[],
        )
        scanner = next(a for a in actions if a["action_id"] == "journal.no_open_legs")
        assert scanner["id"].startswith("journal.no_open_legs.")

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

    def test_priority_is_string_label(self):
        actions = compute_next_actions(
            status=_status(schwab_configured=False, schwab_valid=False),
            kpis=_kpis(open_legs=0),
            positions=[],
            open_legs=[],
        )
        for action in actions:
            assert action["priority"] in {"P0", "P1", "P2"}


