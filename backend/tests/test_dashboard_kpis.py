"""Unit tests for the dashboard KPI extension helpers (issue #146).

Covers:
- ``largest_risk`` picks the worst loser among open positions.
- ``premium_collected_total`` sums correctly across all positions.
- ``premium_collected_ytd`` scopes to the current calendar year only.
- ``realized_pl`` and ``realized_pl_pct`` aggregate closed positions.
- ``largest_loser`` picks the worst closed-position outcome.
- Null-safety paths: no losers, no closed positions, zero basis.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.dashboard import (
    _build_kpis,
    _compute_largest_loser,
    _compute_largest_risk,
    _compute_realized_pl,
    _sum_premium_for_positions,
    _sum_premium_ytd,
)


def _row(
    *,
    position_id: str = "p-1",
    ticker: str = "AAPL",
    shares: int = 100,
    adjusted_cost_basis: float = 17000.0,
    current_price: float | None = None,
    notional: float | None = None,
    unrealized_pl: float | None = None,
    pl_pct: float | None = None,
) -> dict:
    return {
        "id": position_id,
        "ticker": ticker,
        "shares": shares,
        "strategy": "csp",
        "adjusted_cost_basis": adjusted_cost_basis,
        "current_price": current_price,
        "notional": notional,
        "unrealized_pl": unrealized_pl,
        "open_legs_count": 0,
        "wheel_status": "Holding",
        "next_suggested_action": "hold",
        "pl_pct": pl_pct,
    }


def _closed_position(
    *,
    ticker: str = "AAPL",
    total_premiums: float = 0.0,
    broker_cost_basis: float = 17000.0,
    trades: list[dict] | None = None,
) -> dict:
    return {
        "id": f"pc-{ticker}",
        "ticker": ticker,
        "shares": 0,
        "broker_cost_basis": broker_cost_basis,
        "status": "closed",
        "strategy": "holding",
        "opened_at": "2024-01-01T00:00:00Z",
        "closed_at": "2025-06-30T00:00:00Z",
        "notes": None,
        "total_premiums": total_premiums,
        "adjusted_cost_basis": broker_cost_basis - total_premiums,
        "min_compliant_cc_strike": 0.0,
        "trades": trades or [],
    }


def _open_position_with_trades(
    *,
    ticker: str = "AAPL",
    trades: list[dict],
    broker_cost_basis: float = 17000.0,
    total_premiums: float | None = None,
) -> dict:
    if total_premiums is None:
        total_premiums = sum(
            (t.get("premium") or 0.0) * (t.get("quantity") or 0) * 100 for t in trades
        )
    return {
        "id": f"po-{ticker}",
        "ticker": ticker,
        "shares": 100,
        "broker_cost_basis": broker_cost_basis,
        "status": "open",
        "strategy": "csp",
        "opened_at": "2026-01-01T00:00:00Z",
        "closed_at": None,
        "notes": None,
        "total_premiums": total_premiums,
        "adjusted_cost_basis": broker_cost_basis - total_premiums,
        "min_compliant_cc_strike": 0.0,
        "trades": trades,
    }


class TestComputeLargestRisk:
    @pytest.mark.unit
    def test_picks_worst_negative_pl(self):
        rows = [
            _row(position_id="p-a", ticker="AAA", unrealized_pl=-100.0, pl_pct=-0.01),
            _row(position_id="p-b", ticker="BBB", unrealized_pl=-1500.0, pl_pct=-0.10),
            _row(position_id="p-c", ticker="CCC", unrealized_pl=200.0, pl_pct=0.02),
        ]
        result = _compute_largest_risk(rows)
        assert result is not None
        assert result["ticker"] == "BBB"
        assert result["unrealized_pl"] == -1500.0
        assert result["unrealized_pl_pct"] == pytest.approx(-0.10)

    @pytest.mark.unit
    def test_returns_none_when_no_losers(self):
        rows = [
            _row(position_id="p-a", ticker="AAA", unrealized_pl=100.0, pl_pct=0.01),
            _row(position_id="p-b", ticker="BBB", unrealized_pl=0.0, pl_pct=0.0),
        ]
        assert _compute_largest_risk(rows) is None

    @pytest.mark.unit
    def test_returns_none_when_empty(self):
        assert _compute_largest_risk([]) is None

    @pytest.mark.unit
    def test_skips_rows_without_pl(self):
        # Rows with unrealized_pl=None (quote failed) are excluded.
        rows = [
            _row(position_id="p-a", ticker="AAA", unrealized_pl=None),
            _row(position_id="p-b", ticker="BBB", unrealized_pl=-50.0, pl_pct=-0.01),
        ]
        assert _compute_largest_risk(rows)["ticker"] == "BBB"

    @pytest.mark.unit
    def test_breaks_ties_alphabetically(self):
        # Equal-loss positions should sort alphabetically — deterministic
        # output is part of the contract.
        rows = [
            _row(position_id="p-z", ticker="ZZZ", unrealized_pl=-100.0, pl_pct=-0.01),
            _row(position_id="p-a", ticker="AAA", unrealized_pl=-100.0, pl_pct=-0.01),
        ]
        assert _compute_largest_risk(rows)["ticker"] == "AAA"


class TestSumPremiumForPositions:
    @pytest.mark.unit
    def test_sums_total_premiums(self):
        positions = [
            _open_position_with_trades(
                ticker="AAPL",
                trades=[
                    {"premium": 1.50, "quantity": 1, "trade_type": "sell_put",
                     "opened_at": "2026-01-15T00:00:00Z"},
                    {"premium": 2.25, "quantity": 1, "trade_type": "sell_call",
                     "opened_at": "2026-02-10T00:00:00Z"},
                ],
            ),
            _closed_position(ticker="TSLA", total_premiums=300.0),
        ]
        total, count = _sum_premium_for_positions(positions)
        assert total == pytest.approx(150.0 + 225.0 + 300.0)
        assert count == 2  # only AAPL has trade rows

    @pytest.mark.unit
    def test_zero_when_no_positions(self):
        total, count = _sum_premium_for_positions([])
        assert total == 0.0
        assert count == 0


class TestSumPremiumYtd:
    @pytest.mark.unit
    def test_only_current_year_trades_count(self):
        positions = [
            _open_position_with_trades(
                ticker="AAPL",
                trades=[
                    {"premium": 1.0, "quantity": 1, "trade_type": "sell_put",
                     "opened_at": "2024-06-01T00:00:00Z"},  # prior year
                    {"premium": 2.0, "quantity": 1, "trade_type": "sell_put",
                     "opened_at": "2026-03-01T00:00:00Z"},
                ],
            ),
        ]
        ytd = _sum_premium_ytd(positions, today=date(2026, 5, 1))
        assert ytd == pytest.approx(200.0)

    @pytest.mark.unit
    def test_uses_closed_at_when_present(self):
        positions = [
            _open_position_with_trades(
                ticker="AAPL",
                trades=[
                    # Opened last year but closed this year — counts as YTD.
                    {"premium": 1.5, "quantity": 1, "trade_type": "sell_put",
                     "opened_at": "2025-12-15T00:00:00Z",
                     "closed_at": "2026-01-10T00:00:00Z"},
                ],
            ),
        ]
        ytd = _sum_premium_ytd(positions, today=date(2026, 5, 1))
        assert ytd == pytest.approx(150.0)


class TestComputeRealizedPl:
    @pytest.mark.unit
    def test_sums_total_premiums_for_closed_positions(self):
        closed = [
            _closed_position(ticker="A", total_premiums=500.0, broker_cost_basis=10000.0),
            _closed_position(ticker="B", total_premiums=-200.0, broker_cost_basis=5000.0),
        ]
        realized, pct = _compute_realized_pl(closed)
        assert realized == pytest.approx(300.0)
        assert pct == pytest.approx(300.0 / 15000.0)

    @pytest.mark.unit
    def test_returns_zero_and_none_when_empty(self):
        realized, pct = _compute_realized_pl([])
        assert realized == 0.0
        assert pct is None

    @pytest.mark.unit
    def test_returns_none_pct_when_basis_zero(self):
        closed = [_closed_position(total_premiums=200.0, broker_cost_basis=0.0)]
        realized, pct = _compute_realized_pl(closed)
        assert realized == 200.0
        assert pct is None


class TestComputeLargestLoser:
    @pytest.mark.unit
    def test_picks_worst_realized_loser(self):
        closed = [
            _closed_position(ticker="A", total_premiums=200.0, broker_cost_basis=10000.0),
            _closed_position(ticker="B", total_premiums=-500.0, broker_cost_basis=10000.0),
            _closed_position(ticker="C", total_premiums=-100.0, broker_cost_basis=5000.0),
        ]
        result = _compute_largest_loser(closed)
        assert result is not None
        assert result["ticker"] == "B"
        assert result["realized_pl"] == -500.0
        assert result["realized_pl_pct"] == pytest.approx(-0.05)

    @pytest.mark.unit
    def test_returns_none_when_no_losers(self):
        closed = [_closed_position(ticker="A", total_premiums=100.0)]
        assert _compute_largest_loser(closed) is None

    @pytest.mark.unit
    def test_returns_none_when_no_closed_positions(self):
        assert _compute_largest_loser([]) is None


class TestBuildKpis:
    """Integration-level test on _build_kpis to assert the full payload shape."""

    @pytest.mark.unit
    def test_includes_new_kpi_fields(self):
        rows = [
            _row(position_id="p-1", ticker="AAPL", unrealized_pl=-200.0, pl_pct=-0.02),
        ]
        open_legs: list[dict] = []
        open_positions = [
            _open_position_with_trades(
                ticker="AAPL",
                trades=[
                    {"premium": 1.0, "quantity": 1, "trade_type": "sell_put",
                     "opened_at": "2026-02-01T00:00:00Z"},
                ],
            ),
        ]
        closed_positions = [
            _closed_position(ticker="TSLA", total_premiums=400.0, broker_cost_basis=20000.0),
        ]
        kpis = _build_kpis(
            rows,
            open_legs,
            open_positions,
            closed_positions=closed_positions,
            today=date(2026, 5, 11),
        )
        # New fields present.
        assert "largest_risk" in kpis
        assert kpis["largest_risk"]["ticker"] == "AAPL"
        assert "premium_collected_total" in kpis
        assert kpis["premium_collected_total"] == pytest.approx(100.0 + 400.0)
        assert "premium_collected_ytd" in kpis
        assert kpis["premium_collected_ytd"] == pytest.approx(100.0)
        assert "realized_pl" in kpis
        assert kpis["realized_pl"] == pytest.approx(400.0)
        assert kpis["realized_pl_pct"] == pytest.approx(400.0 / 20000.0)
        assert "largest_loser" in kpis
        # TSLA has positive premiums — no realized loser.
        assert kpis["largest_loser"] is None
        # Premium trade count: 1 open trade.
        assert kpis["premium_collected_trades"] == 1

    @pytest.mark.unit
    def test_null_safety_when_empty(self):
        kpis = _build_kpis(
            [], [], [], closed_positions=[], today=date(2026, 5, 11)
        )
        assert kpis["largest_risk"] is None
        assert kpis["largest_loser"] is None
        assert kpis["premium_collected_total"] == 0.0
        assert kpis["premium_collected_ytd"] == 0.0
        assert kpis["realized_pl"] == 0.0
        assert kpis["realized_pl_pct"] is None
        assert kpis["premium_collected_trades"] == 0


class TestAttachNextSuggestedActions:
    """The post-engine pass that stamps each position row with its action label."""

    @pytest.mark.unit
    def test_position_with_no_matching_action_stays_hold(self):
        from app.services.dashboard import _attach_next_suggested_actions

        rows = [_row(position_id="p-1", ticker="AAPL")]
        _attach_next_suggested_actions(rows, next_actions=[], open_legs=[])
        assert rows[0]["next_suggested_action"] == "hold"

    @pytest.mark.unit
    def test_large_loser_label_attaches_by_position_id(self):
        from app.services.dashboard import _attach_next_suggested_actions

        rows = [_row(position_id="p-1", ticker="TSLA", unrealized_pl=-2000.0)]
        next_actions = [
            {
                "id": "position.large_loser.p-1",
                "action_id": "position.large_loser",
                "priority": "P0",
                "title": "Review TSLA",
                "subject": {"ticker": "TSLA"},
                "reason": "below threshold",
                "cta": {"label": "Review", "href": "/journal", "kind": "link"},
            }
        ]
        _attach_next_suggested_actions(rows, next_actions=next_actions, open_legs=[])
        assert rows[0]["next_suggested_action"] == "Review"

    @pytest.mark.unit
    def test_itm_short_dte_label_attaches_via_leg_lookup(self):
        from app.services.dashboard import _attach_next_suggested_actions

        rows = [_row(position_id="p-1", ticker="AAPL")]
        open_legs = [
            {"id": "leg-7", "ticker": "AAPL", "position_id": "p-1", "type": "put"}
        ]
        next_actions = [
            {
                "id": "expiration.itm_short_dte.leg-7",
                "action_id": "expiration.itm_short_dte",
                "priority": "P1",
                "title": "Roll AAPL",
                "subject": {"ticker": "AAPL"},
                "reason": "ITM",
                "cta": {"label": "Manage", "href": "/journal", "kind": "link"},
            }
        ]
        _attach_next_suggested_actions(rows, next_actions=next_actions, open_legs=open_legs)
        assert rows[0]["next_suggested_action"] == "Roll"

    @pytest.mark.unit
    def test_cc_candidate_label_attaches_by_ticker(self):
        from app.services.dashboard import _attach_next_suggested_actions

        rows = [_row(position_id="p-1", ticker="AAPL")]
        next_actions = [
            {
                "id": "position.cc_candidate.aapl",
                "action_id": "position.cc_candidate",
                "priority": "P2",
                "title": "Consider covered call on AAPL",
                "subject": {"ticker": "AAPL"},
                "reason": "100 shares, no open call",
                "cta": {"label": "Scan", "href": "/options?ticker=AAPL", "kind": "link"},
            }
        ]
        _attach_next_suggested_actions(rows, next_actions=next_actions, open_legs=[])
        assert rows[0]["next_suggested_action"] == "Cover"

    @pytest.mark.unit
    def test_highest_priority_action_wins(self):
        """When two actions target the same position, the first one (highest
        priority, since next_actions is pre-sorted) wins."""
        from app.services.dashboard import _attach_next_suggested_actions

        rows = [_row(position_id="p-1", ticker="AAPL")]
        next_actions = [
            {
                "id": "position.large_loser.p-1",
                "action_id": "position.large_loser",
                "priority": "P0",
                "title": "Review",
                "subject": {"ticker": "AAPL"},
                "reason": "loss",
                "cta": {"label": "Review", "href": "/journal", "kind": "link"},
            },
            {
                "id": "position.cc_candidate.aapl",
                "action_id": "position.cc_candidate",
                "priority": "P2",
                "title": "Cover",
                "subject": {"ticker": "AAPL"},
                "reason": "100 shares",
                "cta": {"label": "Scan", "href": "/options", "kind": "link"},
            },
        ]
        _attach_next_suggested_actions(rows, next_actions=next_actions, open_legs=[])
        assert rows[0]["next_suggested_action"] == "Review"
