"""Integration tests for the buy-to-close detail endpoint (issue #244).

``GET /api/positions/{position_id}/legs/{leg_id}/btc``.

Uses the in-memory SQLite ``client`` fixture from ``conftest.py``. Patches
``SchwabClient.get_quote`` / ``get_option_chain`` so no real Schwab calls are
made.

Covers:

- 200 for a known open leg whose profit-take rule fired → ``populated``.
- The rules audit + economics fields are correct.
- ``captured_pct`` agrees with the % CAPT signal (lifted, not recomputed).
- 404 for an unknown leg, a closed leg, and a position/leg mismatch.
- ``no-rule-triggered`` 200 for a quiet leg (``verdict == "hold"``).
- Pricing-unavailable degradation when no option mark matches the contract.
- 500 hygiene — a quote failure yields the generic detail with no ``str(e)``.
"""

from __future__ import annotations

from unittest.mock import patch

from app.models.database import Position, Trade


# ---------------------------------------------------------------------------
# Helpers — seed positions / trades directly via SQLAlchemy
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
    shares: int = 0,
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
                broker_cost_basis=1500.0,
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
    expiration: str = "2026-06-26",
    premium: float = 0.3834,
    quantity: int = 1,
    closed_at: str | None = None,
) -> str:
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


def _chain(strike: float, mid: float, *, option_type: str = "call") -> dict:
    """Return a Schwab option-chain-shaped response with one contract."""
    map_key = "callExpDateMap" if option_type == "call" else "putExpDateMap"
    return {
        map_key: {
            "2026-06-26:38": {
                f"{strike}": [{"strikePrice": strike, "mark": mid}],
            }
        }
    }


def _patch_schwab(quote_price=15.0, chain=None):
    """Context manager patching the BTC service's Schwab client."""
    return patch.multiple(
        "app.services.btc_detail.SchwabClient",
        get_quote=lambda self, ticker: {"lastPrice": quote_price},
        get_option_chain=lambda self, ticker: (chain if chain is not None else {}),
    )


# ---------------------------------------------------------------------------
# 200 — populated (profit-take fired)
# ---------------------------------------------------------------------------


def test_btc_detail_200_populated_when_profit_take_fired(client):
    """A leg deep in the money for the seller (% captured high) → populated."""
    _seed_position(client)
    _seed_trade(client)
    # Premium 0.3834, current mid 0.1572 → captured ≈ 59% → profit-take fires.
    chain = _chain(15.0, 0.1572)
    with _patch_schwab(chain=chain):
        resp = client.get("/api/positions/pos-ford/legs/leg-ford-15c/btc")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["state"] == "populated"
    assert payload["verdict"] == "profit_take_review"
    assert payload["leg"]["ticker"] == "F"
    assert payload["leg"]["strike"] == 15.0
    assert payload["leg"]["option_type"] == "C"
    assert payload["leg"]["position_label"] == "F covered call"
    assert payload["disclaimer"]


def test_btc_detail_rules_audit_has_all_four_rules(client):
    _seed_position(client)
    _seed_trade(client)
    with _patch_schwab(chain=_chain(15.0, 0.1572)):
        resp = client.get("/api/positions/pos-ford/legs/leg-ford-15c/btc")
    payload = resp.json()
    rule_ids = {r["rule_id"] for r in payload["triggered_rules"]}
    assert rule_ids == {
        "assignment_risk",
        "expiration_warning",
        "profit_review",
        "dte_review",
    }
    governing = [r for r in payload["triggered_rules"] if r["is_governing"]]
    assert len(governing) == 1
    assert governing[0]["rule_id"] == "profit_review"
    assert governing[0]["status"] == "triggered"
    assert governing[0]["reasoning"]


def test_btc_detail_economics_fields_are_correct(client):
    _seed_position(client)
    # 1 contract, $0.3834 premium → $38.34 credit; $0.1572 mid → $15.72 cost.
    _seed_trade(client, premium=0.3834, quantity=1)
    with _patch_schwab(chain=_chain(15.0, 0.1572)):
        resp = client.get("/api/positions/pos-ford/legs/leg-ford-15c/btc")
    econ = resp.json()["economics"]
    assert econ["credit_received"] == 38.34
    assert econ["cost_to_close"] == 15.72
    assert econ["est_pl_if_closed"] == 22.62
    assert econ["pricing_source"] == "live"
    assert econ["pricing_as_of"] is not None


def test_btc_detail_captured_pct_agrees_with_profit_signal(client):
    """captured_pct is lifted from the % CAPT signal — agree by construction."""
    _seed_position(client)
    _seed_trade(client, premium=0.3834)
    with _patch_schwab(chain=_chain(15.0, 0.1572)):
        resp = client.get("/api/positions/pos-ford/legs/leg-ford-15c/btc")
    econ = resp.json()["economics"]
    # (0.3834 - 0.1572) / 0.3834 ≈ 0.5900.
    assert econ["captured_pct"] is not None
    assert abs(econ["captured_pct"] - 0.5900) < 0.001


# ---------------------------------------------------------------------------
# 200 — no-rule-triggered (quiet leg)
# ---------------------------------------------------------------------------


def test_btc_detail_no_rule_triggered_for_quiet_leg(client):
    """A far-DTE OTM leg with low capture → verdict hold → no-rule-triggered."""
    _seed_position(client)
    # Far expiration, low capture → no rule fires.
    _seed_trade(
        client,
        expiration="2027-06-26",
        premium=1.00,
    )
    # Current mid still high → captured_pct low → profit rule does not fire.
    chain = {
        "callExpDateMap": {
            "2027-06-26:400": {"15.0": [{"strikePrice": 15.0, "mark": 0.95}]}
        }
    }
    with _patch_schwab(chain=chain):
        resp = client.get("/api/positions/pos-ford/legs/leg-ford-15c/btc")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["state"] == "no-rule-triggered"
    assert payload["verdict"] == "hold"
    # Audit still renders — every rule present, none triggered.
    assert len(payload["triggered_rules"]) == 4
    assert all(r["status"] != "triggered" for r in payload["triggered_rules"])
    # Economics still meaningful for an open leg.
    assert payload["economics"]["credit_received"] == 100.0


# ---------------------------------------------------------------------------
# Pricing-unavailable degradation
# ---------------------------------------------------------------------------


def test_btc_detail_pricing_unavailable_when_no_mark(client):
    """No option mark for the contract → pricing fields degrade to null."""
    _seed_position(client)
    _seed_trade(client)
    # Empty option chain → no mark matches the leg.
    with _patch_schwab(chain={}):
        resp = client.get("/api/positions/pos-ford/legs/leg-ford-15c/btc")
    assert resp.status_code == 200
    econ = resp.json()["economics"]
    assert econ["current_option_mid"] is None
    assert econ["cost_to_close"] is None
    assert econ["captured_pct"] is None
    assert econ["est_pl_if_closed"] is None
    assert econ["pricing_source"] == "unavailable"
    # credit_received is static — still real.
    assert econ["credit_received"] == 38.34


# ---------------------------------------------------------------------------
# 404 — unknown / closed / mismatched leg
# ---------------------------------------------------------------------------


def test_btc_detail_404_for_unknown_position(client):
    with _patch_schwab():
        resp = client.get("/api/positions/nope/legs/whatever/btc")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Leg not found"}


def test_btc_detail_404_for_unknown_leg(client):
    _seed_position(client)
    _seed_trade(client)
    with _patch_schwab(chain=_chain(15.0, 0.1572)):
        resp = client.get("/api/positions/pos-ford/legs/no-such-leg/btc")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Leg not found"}


def test_btc_detail_404_for_closed_leg(client):
    _seed_position(client)
    _seed_trade(client, closed_at="2026-05-01T00:00:00Z")
    with _patch_schwab(chain=_chain(15.0, 0.1572)):
        resp = client.get("/api/positions/pos-ford/legs/leg-ford-15c/btc")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Leg not found"}


def test_btc_detail_404_for_position_leg_mismatch(client):
    """A leg id that belongs to a different position → 404, no cross-leak."""
    _seed_position(client, pos_id="pos-ford", ticker="F")
    _seed_position(client, pos_id="pos-aapl", ticker="AAPL")
    _seed_trade(client, position_id="pos-ford", trade_id="leg-ford-15c")
    with _patch_schwab(chain=_chain(15.0, 0.1572)):
        # Ask for the Ford leg under the AAPL position URL.
        resp = client.get("/api/positions/pos-aapl/legs/leg-ford-15c/btc")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Leg not found"}


# ---------------------------------------------------------------------------
# 500 hygiene — no str(e) leak (CLAUDE.md)
# ---------------------------------------------------------------------------


def test_btc_detail_500_uses_generic_detail_on_quote_failure(client):
    _seed_position(client)
    _seed_trade(client)
    secret = "boom-internal-traceback-detail"

    def _raise(self, ticker):
        raise RuntimeError(secret)

    with patch.object(
        __import__(
            "app.services.btc_detail", fromlist=["SchwabClient"]
        ).SchwabClient,
        "get_quote",
        _raise,
    ):
        resp = client.get("/api/positions/pos-ford/legs/leg-ford-15c/btc")
    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"] == "Failed to load buy-to-close detail. Please try again."
    # The raw exception text must never reach the client.
    assert secret not in resp.text
