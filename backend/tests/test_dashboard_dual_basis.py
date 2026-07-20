"""Tests for the dashboard dual-basis P&L composition (issue #422, PRD #415 R6).

ADR #416 (Option B): the headline P&L stays the premium-adjusted (wheel) basis,
and the RAW broker basis is always surfaced as a labeled secondary. Risk/review
triggers evaluate on the raw drawdown. This file covers the producer side:

- ``_build_position_rows`` stamps ``raw_pl_pct`` / ``raw_unrealized_pl`` on each
  row from the broker basis, while leaving ``pl_pct`` / ``unrealized_pl`` as the
  adjusted headline (unit).
- CSP/0-share rows (no broker basis) → raw fields null (unit).
- The end-to-end payload carries the raw fields (integration).

Unit tests are pure-function (no DB session, no TestClient) → ``@pytest.mark.unit``.
The integration test exercises the FastAPI stack → ``@pytest.mark.integration``.
"""

from __future__ import annotations

import pytest

from app.services.dashboard import _build_position_rows


def _position(
    *,
    position_id: str = "p-1",
    ticker: str = "SOFI",
    shares: int = 100,
    adjusted_cost_basis: float = 4650.0,
    strategy: str = "wheel",
    broker_cost_basis: float | None = 5000.0,
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


# --- raw P&L computation ----------------------------------------------------


@pytest.mark.unit
def test_raw_pl_from_broker_basis():
    """Raw P&L is computed from the RAW broker basis, not the adjusted basis.

    100 sh @ $41 = $4,100 market value; broker basis $5,000 → raw −$900 (−18.0%).
    """
    rows = _build_position_rows(
        [_position(broker_cost_basis=5000.0, adjusted_cost_basis=4650.0)],
        {"SOFI": 41.0},
        [],
    )
    row = rows[0]
    assert row["raw_unrealized_pl"] == pytest.approx(-900.0)
    assert row["raw_pl_pct"] == pytest.approx(-0.18)


@pytest.mark.unit
def test_headline_pl_still_adjusted():
    """The headline ``pl_pct`` / ``unrealized_pl`` stay the ADJUSTED figures.

    Same row: adjusted basis $4,650 → adjusted −$550 (−11.83%). The adjusted
    headline is softer than the raw drawdown (ADR #416 — premium reduces basis).
    """
    rows = _build_position_rows(
        [_position(broker_cost_basis=5000.0, adjusted_cost_basis=4650.0)],
        {"SOFI": 41.0},
        [],
    )
    row = rows[0]
    assert row["unrealized_pl"] == pytest.approx(-550.0)
    assert row["pl_pct"] == pytest.approx(-550.0 / 4650.0)
    # And the raw drawdown is deeper than the adjusted headline.
    assert row["raw_unrealized_pl"] < row["unrealized_pl"]
    assert row["raw_pl_pct"] < row["pl_pct"]


@pytest.mark.unit
def test_raw_pl_null_when_no_broker_basis():
    """CSP/0-share rows carry no broker basis → raw fields null (muted em-dash)."""
    rows = _build_position_rows(
        [_position(broker_cost_basis=None)],
        {"SOFI": 41.0},
        [],
    )
    row = rows[0]
    assert row["raw_unrealized_pl"] is None
    assert row["raw_pl_pct"] is None


@pytest.mark.unit
def test_raw_pl_null_when_no_price():
    """No live price → no raw P&L (nothing to mark against)."""
    rows = _build_position_rows(
        [_position()],
        {"SOFI": None},
        [],
    )
    row = rows[0]
    assert row["raw_unrealized_pl"] is None
    assert row["raw_pl_pct"] is None


@pytest.mark.unit
def test_raw_pl_pct_null_when_zero_broker_basis():
    """A zero broker basis avoids a divide — dollar raw present, pct null."""
    rows = _build_position_rows(
        [_position(broker_cost_basis=0.0)],
        {"SOFI": 41.0},
        [],
    )
    row = rows[0]
    # Dollar raw is market value minus a zero basis = full market value.
    assert row["raw_unrealized_pl"] == pytest.approx(4100.0)
    assert row["raw_pl_pct"] is None


@pytest.mark.unit
def test_raw_pl_positive_when_above_broker_basis():
    """A winner marks positive on both bases (sign is preserved)."""
    rows = _build_position_rows(
        [_position(ticker="F", broker_cost_basis=1200.0, adjusted_cost_basis=1150.0)],
        {"F": 15.0},  # 100 sh @ $15 = $1,500
        [],
    )
    row = rows[0]
    assert row["raw_unrealized_pl"] == pytest.approx(300.0)
    assert row["raw_pl_pct"] == pytest.approx(0.25)
    assert row["unrealized_pl"] == pytest.approx(350.0)
