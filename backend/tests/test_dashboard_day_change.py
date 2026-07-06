"""Unit tests for the dashboard day-change composition (issue #421, PRD #415 R3).

Covers:
- ``_extract_quote_view`` threads every rich field off the Schwab quote node
  and preserves the legacy ``lastPrice`` → ``mark`` fallback (Risk #3 substrate).
- ``_fetch_quotes_parallel`` keeps the ``dict[str, float | None]`` price map
  intact alongside the new ``dict[str, QuoteView]`` rich map (Risk #3 regression).
- ``_compute_day_change`` derives signed $/% from Schwab's own netChange /
  netPercentChange, the "no prior close" empty state, and reads correctly across
  a market-closed period (day change is independent of the quote timestamp).
- ``_build_position_rows`` stamps ``day_change`` / ``day_change_pct`` /
  ``day_state`` on each row.
- ``_build_account_summary`` sums per-position equity day changes.

All are pure-function tests (no DB session, no TestClient) → ``@pytest.mark.unit``.
"""

from __future__ import annotations

import pytest

from app.services.dashboard import (
    QuoteView,
    _build_account_summary,
    _build_position_rows,
    _compute_day_change,
    _extract_quote_view,
    _fetch_quotes_parallel,
)


def _position(
    *,
    position_id: str = "p-1",
    ticker: str = "NOK",
    shares: int = 100,
    adjusted_cost_basis: float = 1200.0,
    strategy: str = "holding",
    broker_cost_basis: float | None = 1207.0,
) -> dict:
    return {
        "id": position_id,
        "ticker": ticker,
        "shares": shares,
        "adjusted_cost_basis": adjusted_cost_basis,
        "strategy": strategy,
        "broker_cost_basis": broker_cost_basis,
        "broker_cost_basis_per_share": (
            broker_cost_basis / shares if (broker_cost_basis and shares) else None
        ),
        "adjusted_cost_basis_per_share": (
            adjusted_cost_basis / shares if shares else None
        ),
    }


# --- _extract_quote_view ---------------------------------------------------


@pytest.mark.unit
def test_quote_view_threads_all_fields():
    """The rich view carries every field off the live-verified quote node."""
    quote = {
        "lastPrice": 12.5,
        "mark": 12.5,
        "closePrice": 12.07,
        "netChange": 0.43,
        "netPercentChange": 3.56255178,
        "quoteTime": 1783362215367,
    }
    view = _extract_quote_view(quote)
    assert view.last == pytest.approx(12.5)
    assert view.mark == pytest.approx(12.5)
    assert view.close == pytest.approx(12.07)
    assert view.net_change == pytest.approx(0.43)
    assert view.net_pct == pytest.approx(3.56255178)
    assert view.quote_time_ms == 1783362215367


@pytest.mark.unit
def test_quote_view_falls_back_to_mark_for_last():
    """``last`` falls back to ``mark`` when ``lastPrice`` is absent (legacy rule)."""
    view = _extract_quote_view({"mark": 4.5})
    assert view.last == pytest.approx(4.5)
    assert view.mark == pytest.approx(4.5)


@pytest.mark.unit
def test_quote_view_empty_when_not_a_dict():
    """A malformed (non-dict) payload degrades to an empty view, never raises."""
    view = _extract_quote_view(None)
    assert view == QuoteView()
    assert view.last is None
    assert view.net_change is None


@pytest.mark.unit
def test_quote_view_no_day_fields_yields_none():
    """A quote with only ``lastPrice`` (no close/netChange) has null day fields."""
    view = _extract_quote_view({"lastPrice": 20.0})
    assert view.last == pytest.approx(20.0)
    assert view.close is None
    assert view.net_change is None
    assert view.net_pct is None


# --- _fetch_quotes_parallel price-map regression (Risk #3) ------------------


@pytest.mark.unit
def test_price_map_unchanged_type_for_legacy_consumers():
    """The float price map keeps its ``dict[str, float | None]`` shape alongside
    the new rich map so ``build_option_leg_index`` / spot consumers are unaffected.

    Exercised on the not-configured early-return path so no DB session or network
    is touched (stays a unit test)."""
    prices, views, failed = _fetch_quotes_parallel(
        ["NOK", "BB", "NOK"], schwab_configured=False, db=None
    )
    assert failed is False
    # Price map: one entry per distinct ticker, all None (feed unavailable).
    assert set(prices.keys()) == {"NOK", "BB"}
    assert all(v is None for v in prices.values())
    # Rich map: parallel keys, each an (empty) QuoteView — never a bare float.
    assert set(views.keys()) == {"NOK", "BB"}
    assert all(isinstance(v, QuoteView) for v in views.values())


# --- _compute_day_change ---------------------------------------------------


@pytest.mark.unit
def test_day_change_from_close_and_net_change():
    """Day change $ = per-share netChange × shares; state is populated."""
    view = QuoteView(last=12.5, close=12.07, net_change=0.43, net_pct=3.56)
    day_change, day_change_pct, state = _compute_day_change(view, shares=100)
    assert day_change == pytest.approx(43.0)
    assert state == "populated"


@pytest.mark.unit
def test_day_change_pct_sign():
    """netPercentChange is normalized to a fraction; sign is preserved."""
    up = QuoteView(net_change=0.43, net_pct=3.56)
    down = QuoteView(net_change=-0.50, net_pct=-2.5)
    _, up_pct, _ = _compute_day_change(up, shares=100)
    down_dollar, down_pct, _ = _compute_day_change(down, shares=100)
    assert up_pct == pytest.approx(0.0356)
    assert down_pct == pytest.approx(-0.025)
    assert down_dollar == pytest.approx(-50.0)


@pytest.mark.unit
def test_day_state_no_prior_close_when_close_missing():
    """No netChange / netPercentChange → the explicit no_prior_close empty state."""
    view = QuoteView(last=20.0)  # only a price, no day fields
    day_change, day_change_pct, state = _compute_day_change(view, shares=100)
    assert day_change is None
    assert day_change_pct is None
    assert state == "no_prior_close"


@pytest.mark.unit
def test_day_change_none_view_is_no_prior_close():
    """A missing quote view (ticker fetch failed) degrades to no_prior_close."""
    assert _compute_day_change(None, shares=100) == (None, None, "no_prior_close")


@pytest.mark.unit
def test_day_change_zero_share_row_has_null_dollars():
    """0-share cash-secured rows have no equity dollar exposure; % still shows."""
    view = QuoteView(net_change=0.43, net_pct=3.56)
    day_change, day_change_pct, state = _compute_day_change(view, shares=0)
    assert day_change is None
    assert day_change_pct == pytest.approx(0.0356)
    assert state == "populated"


@pytest.mark.unit
def test_day_change_correct_across_market_closed():
    """Day change uses Schwab's own netChange, so it reads correctly when the
    market is closed — it does not falsely zero out regardless of the (old)
    quote timestamp (#421 AC #4). The quote_time here is irrelevant to the value."""
    # A stale (market-closed) timestamp must not change the day figures.
    stale = QuoteView(net_change=0.43, net_pct=3.56, quote_time_ms=1)
    day_change, day_change_pct, state = _compute_day_change(stale, shares=100)
    assert day_change == pytest.approx(43.0)
    assert day_change_pct == pytest.approx(0.0356)
    assert state == "populated"


# --- _build_position_rows day fields ---------------------------------------


@pytest.mark.unit
def test_build_position_rows_carry_day_change():
    """Each row is stamped with the day-change trio derived from the rich map."""
    positions = [_position(ticker="NOK", shares=100)]
    rich = {"NOK": QuoteView(last=12.5, close=12.07, net_change=0.43, net_pct=3.56)}
    rows = _build_position_rows(
        positions, {"NOK": 12.5}, open_legs=[], rich_quotes=rich
    )
    row = rows[0]
    assert row["day_change"] == pytest.approx(43.0)
    assert row["day_change_pct"] == pytest.approx(0.0356)
    assert row["day_state"] == "populated"


@pytest.mark.unit
def test_build_position_rows_no_rich_quotes_degrades():
    """Without a rich map, day fields degrade to the no_prior_close empty state."""
    rows = _build_position_rows(
        [_position()], {"NOK": 12.5}, open_legs=[], rich_quotes=None
    )
    assert rows[0]["day_change"] is None
    assert rows[0]["day_state"] == "no_prior_close"


# --- _build_account_summary ------------------------------------------------


@pytest.mark.unit
def test_account_day_change_sums_positions():
    """Account-level day change is the sum of per-position equity day changes."""
    positions = [
        _position(position_id="p1", ticker="NOK", shares=100),
        _position(position_id="p2", ticker="BB", shares=200),
    ]
    rich = {
        "NOK": QuoteView(last=12.5, net_change=0.43, net_pct=3.56),
        "BB": QuoteView(last=3.0, net_change=-0.10, net_pct=-3.2),
    }
    rows = _build_position_rows(positions, {}, open_legs=[], rich_quotes=rich)
    # Give the rows a notional so the account % has a denominator.
    for row, notional in zip(rows, [1250.0, 600.0]):
        row["notional"] = notional
    summary = _build_account_summary(
        db=None, position_rows=rows, open_legs=[], schwab_configured=False
    )
    # NOK +43.00 + BB -20.00 = +23.00
    assert summary["day_change"] == pytest.approx(23.0)
    assert summary["day_state"] == "populated"
    # Percent is over prior notional (current 1850 − change 23 = 1827).
    assert summary["day_change_pct"] == pytest.approx(23.0 / 1827.0)
    # Reconciliation fields stay unavailable on the #421 spine.
    assert summary["account_value"] is None
    assert summary["cash"] is None
    assert summary["reconciles"] is False


@pytest.mark.unit
def test_account_day_change_no_prior_close_when_no_day_data():
    """No day data on any row → account day change is the empty state."""
    rows = _build_position_rows(
        [_position()], {}, open_legs=[], rich_quotes={"NOK": QuoteView(last=12.5)}
    )
    summary = _build_account_summary(
        db=None, position_rows=rows, open_legs=[], schwab_configured=False
    )
    assert summary["day_change"] is None
    assert summary["day_state"] == "no_prior_close"
