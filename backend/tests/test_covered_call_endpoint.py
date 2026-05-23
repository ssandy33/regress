"""Integration tests for the covered-call endpoint (issue #247).

``GET /api/positions/{position_id}/covered-call``.

Uses the in-memory SQLite ``client`` fixture from ``conftest.py``. Patches
``SchwabClient.get_quote`` / ``get_option_chain`` so no real Schwab calls
are made — mirrors ``test_btc_detail_endpoint.py``.

Covers:

- 200 for the canonical F covered call → ``applicability == "covered_call"``,
  ``combined_pnl == 17.63``, ``if_assigned[0].if_assigned_pnl ≈ 217.34``.
- The three not-applicable buckets (no shares, no short call, closed).
- Multi-leg earliest-expiring-first allocation: leg A claims all 100 shares,
  leg B gets 0 but still keeps its premium.
- Degraded paths: no live mid → combined null, if-assigned still real;
  no live share price → stock null, if-assigned still real.
- 404 for unknown position.
- 500 hygiene: a quote failure yields the generic detail with no ``str(e)``.
- The mandatory footer disclaimer is shipped in every payload.
"""

from __future__ import annotations
import pytest

from datetime import date, timedelta
from unittest.mock import patch

from app.models.database import Position, Trade

# ---------------------------------------------------------------------------
# Time-relative expirations — DTE stays constant whatever day this runs.
# ---------------------------------------------------------------------------

_NEAR_DTE = 38
_NEAR_EXPIRY = (date.today() + timedelta(days=_NEAR_DTE)).isoformat()
_FAR_DTE = 60
_FAR_EXPIRY = (date.today() + timedelta(days=_FAR_DTE)).isoformat()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db(client):
    from app.main import app
    from app.models.database import get_db

    override = app.dependency_overrides[get_db]
    return next(override())


def _seed_position(
    client,
    *,
    pos_id: str = "pos-ford",
    ticker: str = "F",
    shares: int = 100,
    broker_cost_basis: float = 1321.0,  # 100 shares * $13.21 / share = $1321 total
    strategy: str = "cc",
    status: str = "open",
) -> str:
    db = _db(client)
    try:
        db.add(
            Position(
                id=pos_id,
                ticker=ticker,
                shares=shares,
                broker_cost_basis=broker_cost_basis,
                status=status,
                strategy=strategy,
                opened_at="2026-01-01",
            )
        )
        db.commit()
    finally:
        db.close()
    return pos_id


def _seed_trade(
    client,
    position_id: str = "pos-ford",
    *,
    trade_id: str = "leg-ford-15c",
    trade_type: str = "sell_call",
    strike: float = 15.0,
    expiration: str | None = None,
    premium: float = 0.3834,
    quantity: int = 1,
    closed_at: str | None = None,
) -> str:
    if expiration is None:
        expiration = _NEAR_EXPIRY
    db = _db(client)
    try:
        db.add(
            Trade(
                id=trade_id,
                position_id=position_id,
                trade_type=trade_type,
                strike=strike,
                expiration=expiration,
                premium=premium,
                fees=0.0,
                quantity=quantity,
                opened_at="2026-04-01T10:00:00Z",
                closed_at=closed_at,
            )
        )
        db.commit()
    finally:
        db.close()
    return trade_id


def _chain(
    strike: float,
    mid: float,
    *,
    option_type: str = "call",
    expiration: str | None = None,
) -> dict:
    """Return a Schwab-shaped option-chain response with one contract."""
    if expiration is None:
        expiration = _NEAR_EXPIRY
    map_key = "callExpDateMap" if option_type == "call" else "putExpDateMap"
    dte = (date.fromisoformat(expiration) - date.today()).days
    return {
        map_key: {
            f"{expiration}:{dte}": {
                f"{strike}": [{"strikePrice": strike, "mark": mid}],
            }
        }
    }


def _merge_chains(*chains: dict) -> dict:
    """Merge multiple ``_chain`` dicts so a two-leg fixture can carry both."""
    merged: dict = {}
    for chain in chains:
        for key, value in chain.items():
            if key in merged and isinstance(merged[key], dict):
                merged[key].update(value)
            else:
                merged[key] = value
    return merged


def _patch_schwab(quote_price: float | None = 13.1579, chain=None):
    """Patch the covered-call service's Schwab client."""
    return patch.multiple(
        "app.services.covered_call.SchwabClient",
        get_quote=lambda self, ticker: (
            {"lastPrice": quote_price} if quote_price is not None else {}
        ),
        get_option_chain=lambda self, ticker: (
            chain if chain is not None else {}
        ),
    )


# ---------------------------------------------------------------------------
# Canonical F covered call — the worked example
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_canonical_covered_call_reconciles_with_worked_example(client):
    """The headline AC: combined +$17.63, if_assigned ≈ +$217."""
    _seed_position(client)
    _seed_trade(client)
    # premium 0.3834, current_mid 0.155 → pnl_dollars = 22.84.
    chain = _chain(15.0, 0.155)
    with _patch_schwab(quote_price=13.1579, chain=chain):
        resp = client.get("/api/positions/pos-ford/covered-call")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["applicability"] == "covered_call"
    today = payload["combined_today"]
    assert today["stock_pnl"] == -5.21
    assert today["options_pnl"] == 22.84
    assert today["combined_pnl"] == 17.63
    assert len(payload["if_assigned"]) == 1
    entry = payload["if_assigned"][0]
    assert entry["leg_id"] == "leg-ford-15c"
    assert entry["strike"] == 15.0
    assert entry["shares_called"] == 100
    assert entry["share_pnl"] == 179.00
    assert entry["premium_kept"] == 38.34
    assert entry["if_assigned_pnl"] == 217.34


@pytest.mark.integration
def test_per_leg_breakdown_carries_coverage_and_pnl(client):
    _seed_position(client)
    _seed_trade(client)
    with _patch_schwab(chain=_chain(15.0, 0.155)):
        resp = client.get("/api/positions/pos-ford/covered-call")
    payload = resp.json()
    assert len(payload["per_leg_breakdown"]) == 1
    row = payload["per_leg_breakdown"][0]
    assert row["leg_id"] == "leg-ford-15c"
    assert row["ticker"] == "F"
    assert row["strike"] == 15.0
    assert row["type"] == "call"
    assert row["coverage"] == "covered"  # shares > 0 + short call ⇒ covered
    assert row["pnl_dollars"] == 22.84
    assert row["if_assigned_pnl"] == 217.34


@pytest.mark.integration
def test_position_summary_basis_is_per_share(client):
    """broker_cost_basis on the response is per-share, not the DB total."""
    _seed_position(client, broker_cost_basis=1321.0, shares=100)
    _seed_trade(client)
    with _patch_schwab(chain=_chain(15.0, 0.155)):
        resp = client.get("/api/positions/pos-ford/covered-call")
    summary = resp.json()["position"]
    assert summary["shares"] == 100
    assert summary["broker_cost_basis"] == 13.21


@pytest.mark.integration
def test_disclaimer_is_present(client):
    _seed_position(client)
    _seed_trade(client)
    with _patch_schwab(chain=_chain(15.0, 0.155)):
        resp = client.get("/api/positions/pos-ford/covered-call")
    payload = resp.json()
    assert payload["disclaimer"]
    assert "report the position state" in payload["disclaimer"]
    # Mandatory framing — the screen reports, it does not advise.
    assert "remain with you" in payload["disclaimer"]


# ---------------------------------------------------------------------------
# Not-applicable branches
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_csp_only_position_returns_not_applicable_no_shares(client):
    _seed_position(client, shares=0, broker_cost_basis=0.0, strategy="csp")
    # Open short put — still not applicable because shares == 0.
    _seed_trade(client, trade_type="sell_put", strike=12.0, premium=0.25)
    with _patch_schwab():
        resp = client.get("/api/positions/pos-ford/covered-call")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["applicability"] == "not_applicable_no_shares"
    assert payload["combined_today"] == {
        "stock_pnl": None,
        "options_pnl": None,
        "combined_pnl": None,
    }
    assert payload["if_assigned"] == []
    assert payload["per_leg_breakdown"] == []


@pytest.mark.integration
def test_holding_with_no_short_call_returns_not_applicable_no_short_call(client):
    # 100 shares, no open option leg at all.
    _seed_position(client, strategy="holding")
    with _patch_schwab():
        resp = client.get("/api/positions/pos-ford/covered-call")
    assert resp.status_code == 200
    assert resp.json()["applicability"] == "not_applicable_no_short_call"


@pytest.mark.integration
def test_holding_with_short_put_only_returns_not_applicable_no_short_call(
    client,
):
    """A position with shares + an open put (no call) is also not applicable."""
    _seed_position(client, strategy="csp")
    _seed_trade(client, trade_type="sell_put", strike=12.0, premium=0.25)
    with _patch_schwab():
        resp = client.get("/api/positions/pos-ford/covered-call")
    assert resp.status_code == 200
    assert resp.json()["applicability"] == "not_applicable_no_short_call"


@pytest.mark.integration
def test_closed_position_returns_not_applicable_closed(client):
    _seed_position(client, status="closed")
    _seed_trade(client)
    with _patch_schwab():
        resp = client.get("/api/positions/pos-ford/covered-call")
    assert resp.status_code == 200
    assert resp.json()["applicability"] == "not_applicable_closed"


# ---------------------------------------------------------------------------
# Multi-leg variant — earliest-expiring-first allocation (Q6)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_multi_leg_earliest_expiring_first_allocation(client):
    """Two short calls, leg A (DTE 38) and leg B (DTE 60), both qty 1."""
    _seed_position(client)
    _seed_trade(
        client,
        trade_id="leg-A",
        strike=15.0,
        expiration=_NEAR_EXPIRY,  # DTE 38 — earliest
        premium=0.3834,
    )
    _seed_trade(
        client,
        trade_id="leg-B",
        strike=16.0,
        expiration=_FAR_EXPIRY,  # DTE 60 — later
        premium=0.25,
    )
    chain = _merge_chains(
        _chain(15.0, 0.155, expiration=_NEAR_EXPIRY),
        _chain(16.0, 0.20, expiration=_FAR_EXPIRY),
    )
    with _patch_schwab(chain=chain):
        resp = client.get("/api/positions/pos-ford/covered-call")
    assert resp.status_code == 200
    payload = resp.json()
    by_id = {entry["leg_id"]: entry for entry in payload["if_assigned"]}
    # Earliest-expiring leg A claims all 100 shares; leg B claims 0.
    assert by_id["leg-A"]["shares_called"] == 100
    assert by_id["leg-B"]["shares_called"] == 0
    # Leg B still keeps its premium even though no shares are called away.
    assert by_id["leg-B"]["premium_kept"] == 25.00
    # Both entries are present.
    assert len(payload["if_assigned"]) == 2


# ---------------------------------------------------------------------------
# Degraded paths
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_degraded_no_live_mid_keeps_if_assigned_real(client):
    """Empty option chain → options_pnl null, but if_assigned survives."""
    _seed_position(client)
    _seed_trade(client)
    with _patch_schwab(quote_price=13.1579, chain={}):
        resp = client.get("/api/positions/pos-ford/covered-call")
    assert resp.status_code == 200
    payload = resp.json()
    today = payload["combined_today"]
    assert today["stock_pnl"] == -5.21  # share price still real
    assert today["options_pnl"] is None  # no live mid
    assert today["combined_pnl"] is None
    # The killer feature: if_assigned still computes — premium + strike + basis
    # are all booked at trade time.
    assert payload["if_assigned"][0]["if_assigned_pnl"] == 217.34


@pytest.mark.integration
def test_degraded_no_live_share_price_keeps_if_assigned_real(client):
    """No live quote → stock_pnl null, options_pnl still real."""
    _seed_position(client)
    _seed_trade(client)
    chain = _chain(15.0, 0.155)
    # An empty quote dict → no usable price.
    with patch.multiple(
        "app.services.covered_call.SchwabClient",
        get_quote=lambda self, ticker: {},
        get_option_chain=lambda self, ticker: chain,
    ):
        resp = client.get("/api/positions/pos-ford/covered-call")
    assert resp.status_code == 200
    payload = resp.json()
    today = payload["combined_today"]
    assert today["stock_pnl"] is None
    assert today["options_pnl"] == 22.84
    assert today["combined_pnl"] is None
    # if_assigned still real — independent of the live share price.
    assert payload["if_assigned"][0]["if_assigned_pnl"] == 217.34


# ---------------------------------------------------------------------------
# 404 + 500 hygiene
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_returns_404_for_unknown_position(client):
    with _patch_schwab():
        resp = client.get("/api/positions/no-such-position/covered-call")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Position not found"}


@pytest.mark.integration
def test_500_on_quote_failure_returns_generic_detail(client):
    """A Schwab failure yields the generic 500; no ``str(e)`` leak."""
    _seed_position(client)
    _seed_trade(client)
    secret = "boom-internal-traceback-detail"

    def _raise(self, ticker):
        raise RuntimeError(secret)

    with patch.object(
        __import__(
            "app.services.covered_call", fromlist=["SchwabClient"]
        ).SchwabClient,
        "get_quote",
        _raise,
    ):
        resp = client.get("/api/positions/pos-ford/covered-call")
    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"] == "Failed to load combined P&L. Please try again."
    # The raw exception text must never reach the client.
    assert secret not in resp.text
