"""Unit tests for dashboard_legs pure helpers (no DB, no HTTP)."""

from datetime import date, timedelta

import pytest

from app.services.dashboard_legs import (
    build_option_mark_index,
    build_profit_target_status,
    compute_assignment_risk,
    compute_decision_tag,
    compute_dte,
    compute_earnings_in_window,
    compute_moneyness,
    compute_suggested_action,
    derive_open_legs,
    filter_upcoming,
    format_decision_reason,
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


class TestFormatDecisionReason:
    def test_itm_includes_dollar_distance(self):
        moneyness = {"state": "ITM", "distance_pct": 0.005, "distance_dollars": 0.42}
        assert format_decision_reason(moneyness, dte=3) == "ITM by $0.42"

    def test_otm_includes_pct_distance(self):
        moneyness = {"state": "OTM", "distance_pct": 0.041, "distance_dollars": 9.84}
        assert format_decision_reason(moneyness, dte=10) == "OTM 4.1%"

    def test_atm_label(self):
        moneyness = {"state": "ATM", "distance_pct": 0.0, "distance_dollars": 0.0}
        assert format_decision_reason(moneyness, dte=5) == "At the money"

    def test_no_moneyness_uses_dte(self):
        assert format_decision_reason(None, dte=3) == "3 DTE — awaiting price"


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


class TestFilterUpcoming:
    def test_keeps_only_within_horizon(self):
        legs = [
            {
                "id": "soon",
                "ticker": "AAPL",
                "type": "put",
                "strike": 175.0,
                "expiration": "2026-05-08",
                "dte": 3,
                "moneyness": {"state": "ITM", "distance_pct": 0.005, "distance_dollars": 0.42},
                "position_id": "p1",
            },
            {
                "id": "far",
                "ticker": "AAPL",
                "type": "call",
                "strike": 200.0,
                "expiration": "2026-08-01",
                "dte": 30,
                "moneyness": None,
                "position_id": "p1",
            },
        ]
        upcoming = filter_upcoming(legs, horizon_days=14)
        assert [leg["id"] for leg in upcoming] == ["soon"]
        assert upcoming[0]["decision_tag"] == "roll-or-assign"
        assert upcoming[0]["decision_reason"] == "ITM by $0.42"

    def test_sorts_itm_before_otm_at_same_dte(self):
        legs = [
            {
                "id": "otm",
                "ticker": "AAPL",
                "type": "put",
                "strike": 170.0,
                "expiration": "2026-05-08",
                "dte": 3,
                "moneyness": {"state": "OTM", "distance_pct": 0.03, "distance_dollars": 5.0},
                "position_id": "p1",
            },
            {
                "id": "itm",
                "ticker": "AAPL",
                "type": "put",
                "strike": 200.0,
                "expiration": "2026-05-08",
                "dte": 3,
                "moneyness": {"state": "ITM", "distance_pct": 0.10, "distance_dollars": 25.0},
                "position_id": "p1",
            },
        ]
        upcoming = filter_upcoming(legs)
        assert [leg["id"] for leg in upcoming] == ["itm", "otm"]


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
