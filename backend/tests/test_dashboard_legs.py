"""Unit tests for dashboard_legs pure helpers (no DB, no HTTP)."""

from datetime import date, timedelta

import pytest

from app.services.dashboard_legs import (
    compute_decision_tag,
    compute_dte,
    compute_moneyness,
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
