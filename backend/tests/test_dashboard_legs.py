"""Unit tests for dashboard_legs pure helpers (no DB, no HTTP)."""

from datetime import date, timedelta

import pytest

from app.models.schemas import DashboardOpenLeg
from app.services.dashboard_legs import (
    build_option_mark_index,
    build_profit_target_status,
    compute_assignment_risk,
    compute_decision_tag,
    compute_dte,
    compute_earnings_in_window,
    compute_moneyness,
    compute_suggested_action,
    derive_leg_economics,
    derive_open_legs,
)


class TestComputeDte:
    def test_today_is_zero(self):
        today = date(2026, 5, 5)
        assert compute_dte("2026-05-05", today=today) == 0

    def test_tomorrow_is_one(self):
        today = date(2026, 5, 5)
        assert compute_dte("2026-05-06", today=today) == 1

    def test_yesterday_is_negative(self):
        today = date(2026, 5, 5)
        assert compute_dte("2026-05-04", today=today) == -1

    def test_two_weeks_out(self):
        today = date(2026, 5, 5)
        assert compute_dte("2026-05-19", today=today) == 14

    def test_isoformat_with_time_suffix(self):
        today = date(2026, 5, 5)
        assert compute_dte("2026-05-08T10:00:00Z", today=today) == 3

    def test_unparseable_returns_sentinel(self):
        assert compute_dte("not-a-date", today=date(2026, 5, 5)) == 9999

    def test_none_returns_sentinel(self):
        assert compute_dte(None, today=date(2026, 5, 5)) == 9999


class TestComputeMoneyness:
    def test_short_put_itm_when_price_below_strike(self):
        result = compute_moneyness("put", strike=175.0, current_price=174.50)
        assert result["state"] == "ITM"
        assert result["distance_dollars"] == pytest.approx(0.50)
        assert result["distance_pct"] == pytest.approx(0.50 / 175.0)

    def test_short_put_otm_when_price_above_strike(self):
        result = compute_moneyness("put", strike=175.0, current_price=180.0)
        assert result["state"] == "OTM"
        assert result["distance_dollars"] == pytest.approx(5.0)

    def test_short_put_atm_when_equal(self):
        result = compute_moneyness("put", strike=175.0, current_price=175.0)
        assert result["state"] == "ATM"

    def test_short_call_itm_when_price_above_strike(self):
        result = compute_moneyness("call", strike=240.0, current_price=245.0)
        assert result["state"] == "ITM"
        assert result["distance_dollars"] == pytest.approx(5.0)

    def test_short_call_otm_when_price_below_strike(self):
        result = compute_moneyness("call", strike=240.0, current_price=230.0)
        assert result["state"] == "OTM"

    def test_returns_none_when_no_price(self):
        assert compute_moneyness("put", 175.0, None) is None


class TestComputeDecisionTag:
    def test_roll_or_assign_when_short_dte_and_itm(self):
        assert compute_decision_tag(3, "ITM") == "roll-or-assign"
        assert compute_decision_tag(7, "ITM") == "roll-or-assign"

    def test_manage_when_short_dte_and_otm(self):
        assert compute_decision_tag(3, "OTM") == "manage"
        assert compute_decision_tag(0, "ATM") == "manage"  # ATM treated as not-ITM

    def test_watch_when_medium_dte_and_itm(self):
        assert compute_decision_tag(10, "ITM") == "watch"
        assert compute_decision_tag(14, "ITM") == "watch"

    def test_hold_when_far_dte_or_otm_medium(self):
        assert compute_decision_tag(10, "OTM") == "hold"
        assert compute_decision_tag(20, "ITM") == "hold"
        assert compute_decision_tag(30, "OTM") == "hold"

    def test_hold_when_moneyness_unknown(self):
        # Conservative fallback: never recommend an action without a price.
        assert compute_decision_tag(2, None) == "hold"
        assert compute_decision_tag(20, None) == "hold"


class TestDeriveOpenLegs:
    def _position(self, ticker: str, position_id: str, trades: list[dict]) -> dict:
        return {
            "id": position_id,
            "ticker": ticker,
            "trades": trades,
        }

    def test_filters_out_closed_trades(self):
        positions = [
            self._position(
                "AAPL",
                "pos-1",
                [
                    {
                        "id": "t-closed",
                        "trade_type": "sell_put",
                        "strike": 150.0,
                        "expiration": "2026-05-08",
                        "closed_at": "2026-05-04T00:00:00Z",
                    },
                    {
                        "id": "t-open",
                        "trade_type": "sell_put",
                        "strike": 175.0,
                        "expiration": "2026-05-08",
                        "closed_at": None,
                    },
                ],
            )
        ]
        legs = derive_open_legs(
            positions,
            quotes_by_ticker={"AAPL": 174.0},
            today=date(2026, 5, 5),
        )
        assert [leg["id"] for leg in legs] == ["t-open"]

    def test_filters_out_exit_event_trades(self):
        # buy_put_close, assignment, called_away, etc. are exit events — not legs.
        positions = [
            self._position(
                "AAPL",
                "pos-1",
                [
                    {
                        "id": "t-buy-close",
                        "trade_type": "buy_put_close",
                        "strike": 150.0,
                        "expiration": "2026-05-08",
                        "closed_at": None,
                    },
                    {
                        "id": "t-assign",
                        "trade_type": "assignment",
                        "strike": 150.0,
                        "expiration": "2026-05-08",
                        "closed_at": None,
                    },
                ],
            )
        ]
        legs = derive_open_legs(positions, quotes_by_ticker={"AAPL": 175.0})
        assert legs == []

    def test_attaches_dte_and_moneyness(self):
        positions = [
            self._position(
                "AAPL",
                "pos-1",
                [
                    {
                        "id": "t1",
                        "trade_type": "sell_put",
                        "strike": 175.0,
                        "expiration": "2026-05-08",
                        "closed_at": None,
                    }
                ],
            )
        ]
        legs = derive_open_legs(
            positions,
            quotes_by_ticker={"AAPL": 174.50},
            today=date(2026, 5, 5),
        )
        assert len(legs) == 1
        assert legs[0]["dte"] == 3
        assert legs[0]["moneyness"]["state"] == "ITM"

    def test_exposes_raw_current_mid_passthrough(self):
        # Issue #244 — the leg dict carries the raw matched option mid so the
        # BTC detail endpoint can compute cost-to-close. `None` when no mark.
        positions = [
            self._position(
                "AAPL",
                "pos-1",
                [
                    {
                        "id": "t1",
                        "trade_type": "sell_put",
                        "strike": 175.0,
                        "expiration": "2026-05-08",
                        "premium": 2.25,
                        "closed_at": None,
                    }
                ],
            )
        ]
        marks = {("AAPL", "put", 175.0, "2026-05-08"): 0.90}
        legs = derive_open_legs(
            positions,
            quotes_by_ticker={"AAPL": 174.50},
            today=date(2026, 5, 5),
            option_marks=marks,
        )
        assert legs[0]["current_mid"] == 0.90
        assert legs[0]["quantity"] == 1
        # No mark for this contract → current_mid is None.
        no_mark = derive_open_legs(
            positions,
            quotes_by_ticker={"AAPL": 174.50},
            today=date(2026, 5, 5),
        )
        assert no_mark[0]["current_mid"] is None

    def test_sorts_by_dte_then_ticker(self):
        positions = [
            self._position(
                "TSLA",
                "p-tsla",
                [
                    {
                        "id": "t-tsla",
                        "trade_type": "sell_put",
                        "strike": 240.0,
                        "expiration": "2026-05-12",
                        "closed_at": None,
                    }
                ],
            ),
            self._position(
                "AAPL",
                "p-aapl",
                [
                    {
                        "id": "t-aapl",
                        "trade_type": "sell_put",
                        "strike": 175.0,
                        "expiration": "2026-05-08",
                        "closed_at": None,
                    }
                ],
            ),
        ]
        legs = derive_open_legs(positions, quotes_by_ticker={}, today=date(2026, 5, 5))
        assert [leg["ticker"] for leg in legs] == ["AAPL", "TSLA"]


# ---------------------------------------------------------------------------
# V0.5 per-leg signal helpers (issue #146)
# ---------------------------------------------------------------------------


class TestComputeAssignmentRisk:
    def test_high_at_seven_dte_itm(self):
        assert compute_assignment_risk(7, "ITM") == "high"
        assert compute_assignment_risk(0, "ITM") == "high"

    def test_watch_at_fourteen_dte_itm(self):
        # At the boundary the spec rule "dte <= 14 AND ITM" still applies.
        assert compute_assignment_risk(14, "ITM") == "watch"
        assert compute_assignment_risk(8, "ITM") == "watch"

    def test_low_at_fifteen_dte_itm(self):
        # Outside both windows even when ITM.
        assert compute_assignment_risk(15, "ITM") == "low"
        assert compute_assignment_risk(30, "ITM") == "low"

    def test_low_when_not_itm(self):
        assert compute_assignment_risk(3, "OTM") == "low"
        assert compute_assignment_risk(3, "ATM") == "low"

    def test_low_when_moneyness_unknown(self):
        assert compute_assignment_risk(3, None) == "low"

    # Issue #248 — boundary cases that pin the `<=` semantics the frontend's
    # urgency-aware DTE pill mirrors. `dteUrgencyTier()` in OpenLegsCard.jsx
    # consumes the same 7/14 thresholds; drifting either side breaks the
    # "thresholds must match" AC. These assertions sit alongside the existing
    # tests on purpose so a single test file reads as the canonical pin.
    @pytest.mark.parametrize(
        "dte,moneyness_state,expected",
        [
            # Red-tier boundary on the frontend ↔ "high" on the backend.
            (7, "ITM", "high"),
            # Just past the red threshold on the frontend ↔ "watch".
            (8, "ITM", "watch"),
            # Amber-tier boundary on the frontend ↔ "watch" on the backend.
            (14, "ITM", "watch"),
            # Just past the amber threshold on the frontend ↔ "low".
            (15, "ITM", "low"),
            # Non-ITM is "low" regardless of DTE — moneyness gates the risk.
            (7, "OTM", "low"),
            (14, "OTM", "low"),
        ],
    )
    def test_dte_boundary_cases(self, dte, moneyness_state, expected):
        assert compute_assignment_risk(dte, moneyness_state) == expected


class TestComputeSuggestedAction:
    def test_roll_for_roll_or_assign(self):
        assert compute_suggested_action("roll-or-assign") == "roll"

    def test_manage_for_manage(self):
        assert compute_suggested_action("manage") == "manage"

    def test_hold_for_watch(self):
        # Watch maps to hold because the V0.5 vocabulary is intentionally
        # smaller; the frontend already shows a Watch pill via decision_tag.
        assert compute_suggested_action("watch") == "hold"

    def test_hold_for_hold(self):
        assert compute_suggested_action("hold") == "hold"

    def test_never_emits_close_in_v05(self):
        # Locked architectural decision: V0.5 never emits "close" because
        # the 50%-target signal requires live option-chain data.
        values = {
            compute_suggested_action(tag)
            for tag in ("roll-or-assign", "manage", "watch", "hold")
        }
        assert "close" not in values


class TestProfitTargetStatusBuilder:
    """Pure math for the dashboard ``% CAPT`` profit-target signal (#240)."""

    def test_locked_acceptance_screenshot_example(self):
        # LOCKED acceptance test — the F 15C leg from the issue #240 screenshot.
        # premium 0.3834 credit, current mid 0.155 → ~59.57% of credit captured,
        # past the default 50% target.
        result = build_profit_target_status(premium=0.3834, current_mid=0.155)
        assert result["captured_pct"] == pytest.approx(0.5957, abs=1e-4)
        assert result["state"] == "captured_50"

    def test_in_progress_below_target(self):
        # 1.00 credit decayed to 0.70 → 30% captured, under the 50% target.
        result = build_profit_target_status(premium=1.00, current_mid=0.70)
        assert result["captured_pct"] == pytest.approx(0.30)
        assert result["state"] == "in_progress"

    def test_captured_50_at_exact_boundary(self):
        # Exactly the 50% threshold counts as captured (>= compare).
        result = build_profit_target_status(premium=1.00, current_mid=0.50)
        assert result["captured_pct"] == pytest.approx(0.50)
        assert result["state"] == "captured_50"

    def test_underwater_when_mid_above_premium(self):
        # 1.00 credit, mid rose to 1.30 → -30% captured (a paper loss).
        result = build_profit_target_status(premium=1.00, current_mid=1.30)
        assert result["captured_pct"] == pytest.approx(-0.30)
        assert result["state"] == "underwater"

    def test_in_progress_when_mid_equals_premium(self):
        # mid == premium → exactly 0% captured → in_progress, not underwater.
        result = build_profit_target_status(premium=1.00, current_mid=1.00)
        assert result["captured_pct"] == pytest.approx(0.0)
        assert result["state"] == "in_progress"

    @pytest.mark.parametrize(
        "premium,current_mid",
        [
            (1.00, None),  # no live mark
            (None, 0.50),  # no premium recorded
            (0.0, 0.50),  # zero credit — no division
            (-1.00, 0.50),  # debit / non-credit leg
        ],
    )
    def test_degrades_to_unknown_on_bad_inputs(self, premium, current_mid):
        result = build_profit_target_status(
            premium=premium, current_mid=current_mid
        )
        assert result == {"captured_pct": None, "state": "unknown"}

    def test_expired_leg_is_unknown(self):
        # Once expired (dte < 0) there is no live management decision.
        result = build_profit_target_status(
            premium=1.00, current_mid=0.10, dte=-3
        )
        assert result == {"captured_pct": None, "state": "unknown"}

    def test_profit_review_pct_threshold_is_honored(self):
        # ~60% captured, but the user's threshold is 75% → still in_progress.
        result = build_profit_target_status(
            premium=1.00, current_mid=0.40, profit_review_pct=75.0
        )
        assert result["captured_pct"] == pytest.approx(0.60)
        assert result["state"] == "in_progress"


class TestDeriveLegEconomics:
    """Pure coverage + dollar-economics derivation for an open leg (#246)."""

    def test_covered_call_when_shares_held(self):
        # A short call against shares the user holds → covered.
        result = derive_leg_economics(
            option_type="call",
            position_shares=100,
            premium=0.3834,
            current_mid=0.155,
            quantity=1,
        )
        assert result["coverage"] == "covered"

    def test_naked_call_when_zero_shares(self):
        # A short call with no shares to deliver → naked (the warning state).
        result = derive_leg_economics(
            option_type="call",
            position_shares=0,
            premium=0.3834,
            current_mid=0.155,
            quantity=1,
        )
        assert result["coverage"] == "naked"

    def test_short_put_never_naked(self):
        # A cash-secured put is not "naked" — coverage is a short-call axis.
        result = derive_leg_economics(
            option_type="put",
            position_shares=0,
            premium=2.25,
            current_mid=1.00,
            quantity=1,
        )
        assert result["coverage"] is None

    def test_worked_example_pnl_and_cost(self):
        # The F 15C worked example from the issue / spec §1.2.
        # premium 0.3834, mid 0.155, quantity 1 → P&L +$22.84, cost $15.50.
        result = derive_leg_economics(
            option_type="call",
            position_shares=100,
            premium=0.3834,
            current_mid=0.155,
            quantity=1,
        )
        assert result["pnl_dollars"] == 22.84
        assert result["cost_to_close"] == 15.50
        assert result["premium"] == 0.3834

    def test_pnl_reconciles_with_captured_pct(self):
        # The whole-position $ P&L must agree with the per-share % CAPT — they
        # are computed by two different functions but share the same inputs,
        # so they must reconcile. (The F 15C example rounds to 60%, not the
        # spec's loosely-stated 59% — 22.84 / 38.34 = 59.57%; both the
        # dollars-derived and the captured_pct-derived value round to 60.)
        premium, current_mid, quantity = 0.3834, 0.155, 1
        econ = derive_leg_economics(
            option_type="call",
            position_shares=100,
            premium=premium,
            current_mid=current_mid,
            quantity=quantity,
        )
        status = build_profit_target_status(premium=premium, current_mid=current_mid)
        captured_from_dollars = round(
            econ["pnl_dollars"] / (premium * 100 * quantity) * 100
        )
        assert captured_from_dollars == round(status["captured_pct"] * 100) == 60

    def test_quantity_scales_dollars(self):
        # Whole-position dollars scale linearly with the contract count.
        one = derive_leg_economics(
            option_type="call",
            position_shares=100,
            premium=0.3834,
            current_mid=0.155,
            quantity=1,
        )
        three = derive_leg_economics(
            option_type="call",
            position_shares=100,
            premium=0.3834,
            current_mid=0.155,
            quantity=3,
        )
        assert three["pnl_dollars"] == pytest.approx(one["pnl_dollars"] * 3)
        assert three["cost_to_close"] == pytest.approx(one["cost_to_close"] * 3)

    def test_no_mid_degrades_pnl_and_cost(self):
        # No live mid → dollars are None, but coverage + premium survive.
        result = derive_leg_economics(
            option_type="call",
            position_shares=0,
            premium=0.3834,
            current_mid=None,
            quantity=1,
        )
        assert result["pnl_dollars"] is None
        assert result["cost_to_close"] is None
        assert result["coverage"] == "naked"
        assert result["premium"] == 0.3834

    def test_underwater_leg_negative_pnl(self):
        # current_mid > premium → a paper loss: P&L must be negative, not
        # abs()'d or floored at 0. Reconciles with the negative % CAPT.
        premium, current_mid, quantity = 1.00, 1.30, 1
        result = derive_leg_economics(
            option_type="call",
            position_shares=100,
            premium=premium,
            current_mid=current_mid,
            quantity=quantity,
        )
        assert result["pnl_dollars"] == -30.0
        assert result["cost_to_close"] == 130.0
        status = build_profit_target_status(premium=premium, current_mid=current_mid)
        captured_from_dollars = round(
            result["pnl_dollars"] / (premium * 100 * quantity) * 100
        )
        assert captured_from_dollars == round(status["captured_pct"] * 100) == -30

    @pytest.mark.parametrize("dte", [-1, -10])
    def test_expired_leg_degrades_economics(self, dte):
        # An expired leg (dte < 0) mirrors build_profit_target_status's guard —
        # the dollars degrade to None so the panel never shows P&L +$X (—%).
        result = derive_leg_economics(
            option_type="call",
            position_shares=100,
            premium=0.3834,
            current_mid=0.155,
            dte=dte,
            quantity=1,
        )
        assert result["pnl_dollars"] is None
        assert result["cost_to_close"] is None
        # Coverage still derives — it depends only on shares.
        assert result["coverage"] == "covered"

    @pytest.mark.parametrize("quantity", [0, None])
    def test_bad_quantity_degrades_economics(self, quantity):
        # A malformed quantity degrades the dollar figures to None rather than
        # fabricating a quantity-1 value — and never raises.
        result = derive_leg_economics(
            option_type="call",
            position_shares=100,
            premium=0.3834,
            current_mid=0.155,
            quantity=quantity,
        )
        assert result["pnl_dollars"] is None
        assert result["cost_to_close"] is None
        # Coverage is unaffected by a bad quantity.
        assert result["coverage"] == "covered"

    def test_non_credit_premium_degrades_economics(self):
        # premium <= 0 mirrors build_profit_target_status's guard.
        for premium in (0.0, -1.0, None):
            result = derive_leg_economics(
                option_type="call",
                position_shares=100,
                premium=premium,
                current_mid=0.155,
                quantity=1,
            )
            assert result["pnl_dollars"] is None
            assert result["cost_to_close"] is None


class TestBuildOptionMarkIndex:
    """Flatten raw Schwab option chains into the flat mid-price index (#240)."""

    def _chain(self) -> dict:
        return {
            "callExpDateMap": {
                "2026-06-26:38": {
                    "240.0": [{"strikePrice": 240.0, "mark": 3.10}],
                }
            },
            "putExpDateMap": {
                "2026-05-08:3": {
                    # strikePrice given as a bare integer-style string.
                    "175": [{"strikePrice": "175", "bid": 1.40, "ask": 1.60}],
                }
            },
        }

    def test_builds_keys_and_mids(self):
        index = build_option_mark_index({"AAPL": self._chain()})
        # Call leg uses the explicit `mark`.
        assert index[("AAPL", "call", 240.0, "2026-06-26")] == pytest.approx(3.10)
        # Put leg with no `mark` falls back to (bid + ask) / 2.
        assert index[("AAPL", "put", 175.0, "2026-05-08")] == pytest.approx(1.50)

    def test_strike_normalization(self):
        # "15" and "15.0" must both normalize to the float 15.0.
        chain = {
            "callExpDateMap": {
                "2026-06-26:38": {
                    "15": [{"strikePrice": "15", "mark": 0.50}],
                }
            }
        }
        index = build_option_mark_index({"F": chain})
        assert ("F", "call", 15.0, "2026-06-26") in index

    def test_exp_key_prefix_is_split(self):
        # The exp_key carries a ":DTE" suffix that must be stripped.
        index = build_option_mark_index({"AAPL": self._chain()})
        keys = {key[3] for key in index}
        assert keys == {"2026-06-26", "2026-05-08"}

    def test_mark_preferred_over_bid_ask(self):
        chain = {
            "callExpDateMap": {
                "2026-06-26:38": {
                    "100.0": [
                        {"strikePrice": 100.0, "mark": 2.00, "bid": 1.0, "ask": 1.2}
                    ],
                }
            }
        }
        index = build_option_mark_index({"AAPL": chain})
        # mark wins even when bid/ask are present.
        assert index[("AAPL", "call", 100.0, "2026-06-26")] == pytest.approx(2.00)

    def test_contract_with_no_usable_mid_is_skipped(self):
        chain = {
            "callExpDateMap": {
                "2026-06-26:38": {
                    "100.0": [{"strikePrice": 100.0, "bid": 0.0, "ask": 0.0}],
                }
            }
        }
        index = build_option_mark_index({"AAPL": chain})
        assert index == {}

    def test_malformed_chains_do_not_raise(self):
        malformed = {
            "AAPL": {
                "callExpDateMap": {
                    "2026-06-26:38": {
                        "100.0": [],  # empty contract list
                        "105.0": ["not-a-dict"],  # non-dict contract
                        "110.0": [{"bid": 1.0, "ask": 1.2}],  # missing strikePrice
                    },
                    "bad-node": "not-a-strikes-map",
                },
                "putExpDateMap": "not-a-map",
            },
            "TSLA": "not-a-chain",
            "MSFT": {},  # no maps at all
        }
        # Must not raise; everything malformed is simply skipped.
        index = build_option_mark_index(malformed)
        assert index == {}

    def test_none_input_returns_empty(self):
        assert build_option_mark_index(None) == {}


class TestComputeEarningsInWindow:
    def test_false_when_lookup_returns_none(self):
        assert (
            compute_earnings_in_window("AAPL", dte=5, earnings_lookup=lambda _t: None)
            is False
        )

    def test_false_when_dte_zero(self):
        # Zero DTE means the leg expires today — no future window.
        assert (
            compute_earnings_in_window(
                "AAPL", dte=0, earnings_lookup=lambda _t: "2099-01-01"
            )
            is False
        )

    def test_true_when_within_window(self):
        future = (date.today() + timedelta(days=3)).isoformat()
        assert (
            compute_earnings_in_window(
                "AAPL", dte=7, earnings_lookup=lambda _t: future
            )
            is True
        )

    def test_false_when_after_window(self):
        future = (date.today() + timedelta(days=30)).isoformat()
        assert (
            compute_earnings_in_window(
                "AAPL", dte=5, earnings_lookup=lambda _t: future
            )
            is False
        )

    def test_false_when_lookup_returns_garbage(self):
        assert (
            compute_earnings_in_window(
                "AAPL", dte=5, earnings_lookup=lambda _t: "not-a-date"
            )
            is False
        )


class TestDeriveOpenLegsV05Signals:
    """Signal fields added in V0.5 must always be present on each leg."""

    def _position(self, ticker: str, position_id: str, trades: list[dict]) -> dict:
        return {"id": position_id, "ticker": ticker, "trades": trades}

    def test_includes_v05_signal_fields(self):
        positions = [
            self._position(
                "AAPL",
                "p-1",
                [
                    {
                        "id": "t1",
                        "trade_type": "sell_put",
                        "strike": 175.0,
                        "expiration": "2026-05-08",
                        "premium": 2.25,
                        "quantity": 1,
                        "closed_at": None,
                    }
                ],
            )
        ]
        legs = derive_open_legs(
            positions,
            quotes_by_ticker={"AAPL": 174.50},
            today=date(2026, 5, 5),
        )
        leg = legs[0]
        # No option_marks supplied → % CAPT degrades to unknown.
        assert leg["profit_target_status"] == {
            "captured_pct": None,
            "state": "unknown",
        }
        # 3 DTE + ITM → high risk
        assert leg["assignment_risk"] == "high"
        # 3 DTE + ITM → decision tag roll-or-assign → suggested_action "roll"
        assert leg["suggested_action"] == "roll"
        # Earnings lookup defaults to cache-miss → False.
        assert leg["earnings_in_window"] is False

    def test_profit_target_status_uses_matching_option_mark(self):
        positions = [
            self._position(
                "AAPL",
                "p-1",
                [
                    {
                        "id": "t1",
                        "trade_type": "sell_put",
                        "strike": 175.0,
                        "expiration": "2026-05-08",
                        "premium": 1.00,
                        "quantity": 1,
                        "closed_at": None,
                    }
                ],
            )
        ]
        # A live mark of 0.40 → 60% of the 1.00 credit captured.
        option_marks = {("AAPL", "put", 175.0, "2026-05-08"): 0.40}
        legs = derive_open_legs(
            positions,
            quotes_by_ticker={"AAPL": 174.50},
            today=date(2026, 5, 5),
            option_marks=option_marks,
        )
        status = legs[0]["profit_target_status"]
        assert status["captured_pct"] == pytest.approx(0.60)
        assert status["state"] == "captured_50"

    def test_profit_target_status_unknown_when_mark_key_absent(self):
        positions = [
            self._position(
                "AAPL",
                "p-1",
                [
                    {
                        "id": "t1",
                        "trade_type": "sell_put",
                        "strike": 175.0,
                        "expiration": "2026-05-08",
                        "premium": 1.00,
                        "quantity": 1,
                        "closed_at": None,
                    }
                ],
            )
        ]
        # Index has a mark, but for a different strike — no match for this leg.
        option_marks = {("AAPL", "put", 180.0, "2026-05-08"): 0.40}
        legs = derive_open_legs(
            positions,
            quotes_by_ticker={"AAPL": 174.50},
            today=date(2026, 5, 5),
            option_marks=option_marks,
        )
        assert legs[0]["profit_target_status"] == {
            "captured_pct": None,
            "state": "unknown",
        }

    def test_earnings_lookup_must_not_be_called_with_network(self):
        # Custom lookup proves derive_open_legs uses cache-only semantics
        # via the injected callable. No real network is allowed.
        calls: list[str] = []

        def lookup(ticker: str) -> str | None:
            calls.append(ticker)
            return None

        positions = [
            self._position(
                "AAPL",
                "p-1",
                [
                    {
                        "id": "t1",
                        "trade_type": "sell_put",
                        "strike": 175.0,
                        "expiration": "2026-05-08",
                        "premium": 2.25,
                        "quantity": 1,
                        "closed_at": None,
                    }
                ],
            )
        ]
        derive_open_legs(
            positions,
            quotes_by_ticker={"AAPL": 174.50},
            today=date(2026, 5, 5),
            earnings_lookup=lookup,
        )
        assert calls == ["AAPL"]


class TestDeriveOpenLegsRuleMonitor:
    """The §R6 rule-monitor verdict layer attached to each leg (issue #240)."""

    def _position(self, ticker: str, position_id: str, trades: list[dict]) -> dict:
        return {"id": position_id, "ticker": ticker, "trades": trades}

    def _trade(self, **overrides) -> dict:
        trade = {
            "id": "t1",
            "trade_type": "sell_put",
            "strike": 175.0,
            "expiration": "2026-06-12",
            "premium": 1.00,
            "quantity": 1,
            "closed_at": None,
        }
        trade.update(overrides)
        return trade

    def test_every_leg_carries_verdict_layer_fields(self):
        positions = [
            self._position("AAPL", "p-1", [self._trade(expiration="2026-07-31")])
        ]
        legs = derive_open_legs(
            positions,
            quotes_by_ticker={"AAPL": 200.0},
            today=date(2026, 5, 5),
        )
        leg = legs[0]
        assert "verdict" in leg
        assert "verdict_label" in leg
        assert "reasoning" in leg
        assert "triggered_rules" in leg
        assert len(leg["triggered_rules"]) == 4

    def test_quiet_leg_verdict_is_hold(self):
        # 87 DTE, OTM, no mark → nothing fires.
        positions = [
            self._position("AAPL", "p-1", [self._trade(expiration="2026-07-31")])
        ]
        legs = derive_open_legs(
            positions,
            quotes_by_ticker={"AAPL": 200.0},
            today=date(2026, 5, 5),
        )
        assert legs[0]["verdict"] == "hold"
        assert legs[0]["verdict_label"] == "Hold"

    def test_profit_take_verdict_with_live_mark(self):
        # Premium 1.00, mark 0.40 → 60% captured → profit-take verdict.
        positions = [
            self._position("AAPL", "p-1", [self._trade(expiration="2026-07-31")])
        ]
        option_marks = {("AAPL", "put", 175.0, "2026-07-31"): 0.40}
        legs = derive_open_legs(
            positions,
            quotes_by_ticker={"AAPL": 200.0},
            today=date(2026, 5, 5),
            option_marks=option_marks,
        )
        assert legs[0]["verdict"] == "profit_take_review"
        assert legs[0]["verdict_label"] == "Review · 50%"

    def test_dte_review_window_threshold_honored(self):
        # 25-DTE leg with dte_review_days=30 → fires; with default 21 → quiet.
        positions = [
            self._position("AAPL", "p-1", [self._trade(expiration="2026-05-30")])
        ]
        fired = derive_open_legs(
            positions,
            quotes_by_ticker={"AAPL": 200.0},
            today=date(2026, 5, 5),
            dte_review_days=30,
        )
        assert fired[0]["verdict"] == "dte_review"
        assert fired[0]["verdict_label"] == "Review · 30d"

        quiet = derive_open_legs(
            positions,
            quotes_by_ticker={"AAPL": 200.0},
            today=date(2026, 5, 5),
        )
        assert quiet[0]["verdict"] == "hold"

    def test_expiration_warning_threshold_honored(self):
        # 10-DTE OTM leg: fires only when expiration_warning_days >= 10.
        positions = [
            self._position("AAPL", "p-1", [self._trade(expiration="2026-05-15")])
        ]
        legs = derive_open_legs(
            positions,
            quotes_by_ticker={"AAPL": 200.0},
            today=date(2026, 5, 5),
            expiration_warning_days=10,
        )
        assert legs[0]["verdict"] == "expiration"


class TestDeriveOpenLegsEconomics:
    """Coverage + dollar-economics keys attached to each leg (#246)."""

    def _position(
        self,
        ticker: str,
        position_id: str,
        trades: list[dict],
        shares: int = 0,
    ) -> dict:
        return {
            "id": position_id,
            "ticker": ticker,
            "shares": shares,
            "trades": trades,
        }

    def test_covered_call_leg_carries_economics(self):
        # A short call against 100 held shares, with a live mark — the F 15C
        # worked example surfaced through derive_open_legs.
        positions = [
            self._position(
                "F",
                "p-f",
                [
                    {
                        "id": "t-f15c",
                        "trade_type": "sell_call",
                        "strike": 15.0,
                        "expiration": "2026-06-26",
                        "premium": 0.3834,
                        "quantity": 1,
                        "closed_at": None,
                    }
                ],
                shares=100,
            )
        ]
        option_marks = {("F", "call", 15.0, "2026-06-26"): 0.155}
        legs = derive_open_legs(
            positions,
            quotes_by_ticker={"F": 13.50},
            today=date(2026, 5, 19),
            option_marks=option_marks,
        )
        leg = legs[0]
        assert leg["coverage"] == "covered"
        assert leg["premium"] == 0.3834
        assert leg["pnl_dollars"] == 22.84
        assert leg["cost_to_close"] == 15.50

    def test_naked_call_leg_when_no_shares(self):
        # A short call on a position holding 0 shares → naked.
        positions = [
            self._position(
                "SOFI",
                "p-sofi",
                [
                    {
                        "id": "t-sofi8c",
                        "trade_type": "sell_call",
                        "strike": 8.0,
                        "expiration": "2026-06-12",
                        "premium": 0.41,
                        "quantity": 1,
                        "closed_at": None,
                    }
                ],
                shares=0,
            )
        ]
        legs = derive_open_legs(
            positions,
            quotes_by_ticker={"SOFI": 7.50},
            today=date(2026, 5, 19),
        )
        assert legs[0]["coverage"] == "naked"

    def test_short_put_leg_has_no_coverage(self):
        # A cash-secured put always has coverage None, even with 0 shares.
        positions = [
            self._position(
                "AAPL",
                "p-aapl",
                [
                    {
                        "id": "t-aapl185p",
                        "trade_type": "sell_put",
                        "strike": 185.0,
                        "expiration": "2026-07-10",
                        "premium": 2.10,
                        "quantity": 1,
                        "closed_at": None,
                    }
                ],
                shares=0,
            )
        ]
        legs = derive_open_legs(
            positions,
            quotes_by_ticker={"AAPL": 200.0},
            today=date(2026, 5, 19),
        )
        assert legs[0]["coverage"] is None

    def test_wheel_position_per_leg_coverage(self):
        # One wheel position holding 100 shares carries both a sell_put and a
        # sell_call leg — coverage is derived per-leg, not per-position: the
        # call leg reads covered, the put leg reads None, from the same shares.
        positions = [
            self._position(
                "TSLA",
                "p-tsla",
                [
                    {
                        "id": "t-call",
                        "trade_type": "sell_call",
                        "strike": 260.0,
                        "expiration": "2026-06-19",
                        "premium": 3.00,
                        "quantity": 1,
                        "closed_at": None,
                    },
                    {
                        "id": "t-put",
                        "trade_type": "sell_put",
                        "strike": 220.0,
                        "expiration": "2026-06-19",
                        "premium": 2.50,
                        "quantity": 1,
                        "closed_at": None,
                    },
                ],
                shares=100,
            )
        ]
        legs = derive_open_legs(
            positions,
            quotes_by_ticker={"TSLA": 240.0},
            today=date(2026, 5, 19),
        )
        by_id = {leg["id"]: leg for leg in legs}
        assert by_id["t-call"]["coverage"] == "covered"
        assert by_id["t-put"]["coverage"] is None

    def test_degraded_leg_keeps_coverage_drops_dollars(self):
        # No option mark for the leg → pnl_dollars / cost_to_close degrade to
        # None, but the naked coverage badge (from shares) still derives.
        positions = [
            self._position(
                "RIVN",
                "p-rivn",
                [
                    {
                        "id": "t-rivn13c",
                        "trade_type": "sell_call",
                        "strike": 13.0,
                        "expiration": "2026-06-19",
                        "premium": 0.521,
                        "quantity": 1,
                        "closed_at": None,
                    }
                ],
                shares=0,
            )
        ]
        legs = derive_open_legs(
            positions,
            quotes_by_ticker={"RIVN": 12.0},
            today=date(2026, 5, 19),
        )
        leg = legs[0]
        assert leg["coverage"] == "naked"
        assert leg["pnl_dollars"] is None
        assert leg["cost_to_close"] is None
        assert leg["premium"] == 0.521

    # ---- V1.0.8 / #251 — partial-coverage tri-state ----

    def test_wheel_position_per_leg_partial_coverage(self):
        # 100 held shares + 2 short calls (200 shares' worth of obligation).
        # Both call legs share the same position dict — the per-leg `quantity`
        # is what flips them from `covered` to `partial`. The sell_put leg on
        # the same wheel still reads `None` (coverage is a short-call axis).
        positions = [
            self._position(
                "TSLA",
                "p-tsla-partial",
                [
                    {
                        "id": "t-call-2x",
                        "trade_type": "sell_call",
                        "strike": 260.0,
                        "expiration": "2026-06-19",
                        "premium": 3.00,
                        "quantity": 2,
                        "closed_at": None,
                    },
                    {
                        "id": "t-put-1x",
                        "trade_type": "sell_put",
                        "strike": 220.0,
                        "expiration": "2026-06-19",
                        "premium": 2.50,
                        "quantity": 1,
                        "closed_at": None,
                    },
                ],
                shares=100,
            )
        ]
        legs = derive_open_legs(
            positions,
            quotes_by_ticker={"TSLA": 240.0},
            today=date(2026, 5, 19),
        )
        by_id = {leg["id"]: leg for leg in legs}
        # Only 100 of the 200 shares needed to back the 2 short calls — partial.
        assert by_id["t-call-2x"]["coverage"] == "partial"
        # The cash-secured put leg remains coverage-less.
        assert by_id["t-put-1x"]["coverage"] is None

    def test_partial_at_boundary(self):
        # 99 shares vs. 1 short call (100 shares needed) — one share short of
        # covered. The strict-inequality lower boundary of the `covered` branch.
        positions = [
            self._position(
                "F",
                "p-f-99",
                [
                    {
                        "id": "t-f15c-99",
                        "trade_type": "sell_call",
                        "strike": 15.0,
                        "expiration": "2026-06-26",
                        "premium": 0.3834,
                        "quantity": 1,
                        "closed_at": None,
                    }
                ],
                shares=99,
            )
        ]
        legs = derive_open_legs(
            positions,
            quotes_by_ticker={"F": 13.50},
            today=date(2026, 5, 19),
        )
        assert legs[0]["coverage"] == "partial"

    def test_covered_when_shares_meet_obligation_exactly(self):
        # 100 shares vs. 1 short call (100 shares needed) — the inclusive
        # boundary of the `covered` branch. An exact match is `covered`, not
        # `partial`. Pinned so a future refactor does not flip the `>=` to `>`.
        positions = [
            self._position(
                "F",
                "p-f-exact",
                [
                    {
                        "id": "t-f15c-exact",
                        "trade_type": "sell_call",
                        "strike": 15.0,
                        "expiration": "2026-06-26",
                        "premium": 0.3834,
                        "quantity": 1,
                        "closed_at": None,
                    }
                ],
                shares=100,
            )
        ]
        legs = derive_open_legs(
            positions,
            quotes_by_ticker={"F": 13.50},
            today=date(2026, 5, 19),
        )
        assert legs[0]["coverage"] == "covered"


class TestDashboardOpenLegSchemaBackwardCompat:
    """Schema-level guard: the V1.0.6 (#246) economics fields are optional.

    A pre-#246 payload (one that predates the four new economics fields)
    must still validate as a `DashboardOpenLeg`, with each new field
    resolving to `None`. This protects against a future required-field
    change that would silently break callers carrying older payload shapes
    (legacy tests, cached fixtures, downstream consumers).
    """

    def test_dashboard_open_leg_schema_accepts_new_fields(self):
        # A minimal payload that mirrors the pre-#246 shape — none of the
        # four V1.0.6 economics fields are supplied.
        old_payload = {
            "id": "leg-1",
            "ticker": "AAPL",
            "type": "put",
            "strike": 175.0,
            "expiration": "2026-05-08",
            "dte": 7,
            "moneyness": None,
            "position_id": "pos-aapl",
            "profit_target_status": {"captured_pct": None, "state": "unknown"},
            "assignment_risk": "low",
            "suggested_action": "hold",
            "earnings_in_window": False,
        }
        leg = DashboardOpenLeg(**old_payload)
        assert leg.coverage is None
        assert leg.premium is None
        assert leg.pnl_dollars is None
        assert leg.cost_to_close is None


class TestDashboardOpenLegQuantity:
    """Quantity field + per-contract economics reconciliation (V1.0.8 #252).

    The InspectPanel renders `Credit received = premium * 100 * quantity` on
    the degraded path. These tests pin the schema field default and confirm
    `derive_leg_economics` scales `pnl_dollars` / `cost_to_close` by the
    trade's quantity (the field is wired through `dashboard_legs.py:479`).
    """

    def _position(
        self,
        ticker: str,
        position_id: str,
        trades: list[dict],
        shares: int = 0,
    ) -> dict:
        return {
            "id": position_id,
            "ticker": ticker,
            "shares": shares,
            "trades": trades,
        }

    def test_quantity_field_defaults_to_1(self):
        # A pre-#252 payload (no `quantity` key) must still validate, with
        # `quantity` resolving to `1`. Protects backward compat with legacy
        # tests and cached fixtures.
        old_payload = {
            "id": "leg-1",
            "ticker": "AAPL",
            "type": "put",
            "strike": 175.0,
            "expiration": "2026-05-08",
            "dte": 7,
            "moneyness": None,
            "position_id": "pos-aapl",
            "profit_target_status": {"captured_pct": None, "state": "unknown"},
            "assignment_risk": "low",
            "suggested_action": "hold",
            "earnings_in_window": False,
        }
        leg = DashboardOpenLeg(**old_payload)
        assert leg.quantity == 1

    def test_quantity_2_dollars_reconcile(self):
        # qty=2, premium=$3.00/sh, current_mid=$1.50/sh.
        # Credit received  = premium * 100 * qty  = 3.00 * 100 * 2 = $600
        # cost_to_close    = mid * 100 * qty      = 1.50 * 100 * 2 = $300
        # pnl_dollars      = (prem-mid)*100*qty   = 1.50 * 100 * 2 = $300
        # => credit_received == pnl_dollars + cost_to_close  (V1.0.6 §3.4)
        positions = [
            self._position(
                "AAPL",
                "p-aapl",
                [
                    {
                        "id": "t-aapl175c",
                        "trade_type": "sell_call",
                        "strike": 175.0,
                        "expiration": "2026-06-19",
                        "premium": 3.00,
                        "quantity": 2,
                        "closed_at": None,
                    }
                ],
                shares=200,
            )
        ]
        option_marks = {("AAPL", "call", 175.0, "2026-06-19"): 1.50}
        legs = derive_open_legs(
            positions,
            quotes_by_ticker={"AAPL": 170.0},
            today=date(2026, 5, 19),
            option_marks=option_marks,
        )
        leg = legs[0]
        assert leg["quantity"] == 2
        assert leg["pnl_dollars"] == 300.00
        assert leg["cost_to_close"] == 300.00
        # The reconciliation identity the InspectPanel relies on:
        assert leg["pnl_dollars"] + leg["cost_to_close"] == leg["premium"] * 100 * leg["quantity"]

    def test_quantity_3_economics_scale(self):
        # Two-leg comparison: qty=1 vs qty=3 with identical premium/mid → the
        # qty=3 leg's dollar figures are exactly 3× the qty=1 leg's. Confirms
        # the field is wired through from `Trade.quantity` to the schema.
        positions = [
            self._position(
                "F",
                "p-f",
                [
                    {
                        "id": "t-f15c-qty1",
                        "trade_type": "sell_call",
                        "strike": 15.0,
                        "expiration": "2026-06-26",
                        "premium": 0.3834,
                        "quantity": 1,
                        "closed_at": None,
                    },
                    {
                        "id": "t-f15c-qty3",
                        "trade_type": "sell_call",
                        "strike": 15.0,
                        "expiration": "2026-06-26",
                        "premium": 0.3834,
                        "quantity": 3,
                        "closed_at": None,
                    },
                ],
                shares=300,
            )
        ]
        option_marks = {("F", "call", 15.0, "2026-06-26"): 0.155}
        legs = derive_open_legs(
            positions,
            quotes_by_ticker={"F": 13.50},
            today=date(2026, 5, 19),
            option_marks=option_marks,
        )
        by_id = {leg["id"]: leg for leg in legs}
        qty1 = by_id["t-f15c-qty1"]
        qty3 = by_id["t-f15c-qty3"]
        assert qty1["quantity"] == 1
        assert qty3["quantity"] == 3
        assert qty3["pnl_dollars"] == pytest.approx(qty1["pnl_dollars"] * 3)
        assert qty3["cost_to_close"] == pytest.approx(qty1["cost_to_close"] * 3)
