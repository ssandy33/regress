"""Integration tests for the covered-call distance rule (issue TBD).

Full stack: ``POST /api/options/scan`` through the router's ``rules_config``
backfill into :class:`OptionScanner`, with the Schwab chain patched. Covers:

- The AC example (ticker F, basis $13.21): the $14.50 strike is rejected and
  names the $14.53 required strike; $15.00 is a candidate. ``T`` is
  backfilled from the catalog default (10).
- A below-basis strike reports a single rule (``fails_10pct_rule``), with no
  separate ``below_cost_basis`` double count.
- A per-request ``T`` flows into the human sentence.
- Cash-secured puts are unaffected by the call-distance rule.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.services.options_scanner import OptionScanner
from app.services.schwab_client import SchwabClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _approve_watchlist(client, ticker: str) -> None:
    """Seed the watchlist so the #322 gate lets a scan for ``ticker`` through."""
    client.post("/api/watchlist", json={"ticker": ticker})


def _contract(strike: float, *, delta: float, dte: int) -> dict:
    # A clean, liquid contract: only the strike-distance rules can fire.
    return {
        "strikePrice": strike,
        "bid": 0.30,
        "ask": 0.31,
        "mark": 0.305,
        "delta": delta,
        "gamma": 0.03,
        "theta": -0.02,
        "vega": 0.04,
        "openInterest": 1000,
        "totalVolume": 100,
        "volatility": 35.0,
        "daysToExpiration": dte,
    }


def _chain(strikes: list[float], *, side: str, price: float = 12.71, dte: int = 30):
    """Build a Schwab chain response with one expiration and ``strikes``."""
    exp_date = (datetime.now().date() + timedelta(days=dte)).strftime("%Y-%m-%d")
    delta = 0.25 if side == "call" else -0.25
    exp_map = {
        f"{exp_date}:{dte}": {
            str(s): [_contract(s, delta=delta, dte=dte)] for s in strikes
        }
    }
    return {
        "symbol": "F",
        "status": "SUCCESS",
        "underlying": {"last": price, "close": price, "totalVolume": 1_000_000},
        "callExpDateMap": exp_map if side == "call" else {},
        "putExpDateMap": exp_map if side == "put" else {},
    }


def _scan(client, chain: dict, body: dict) -> dict:
    _approve_watchlist(client, body["ticker"])
    with patch.object(OptionScanner, "_get_vix", return_value=None), patch(
        "app.services.options_scanner.get_next_earnings_date", return_value=None
    ), patch.object(SchwabClient, "get_option_chain", return_value=chain):
        resp = client.post("/api/options/scan", json=body)
    assert resp.status_code == 200
    return resp.json()


def _rejected_at(data: dict, strike: float) -> dict:
    matches = [r for r in data["rejected"] if r["strike"] == strike]
    assert matches, f"expected strike {strike} in rejected[]"
    return matches[0]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.tdd_red
def test_cc_scan_1321_basis_rejects_1450_accepts_1500(client):
    """AC1/AC7 — default T=10: $14.50 rejected naming $14.53; $15.00 passes."""
    data = _scan(
        client,
        _chain([14.50, 15.00], side="call"),
        {"ticker": "F", "strategy": "covered_call", "cost_basis": 13.21},
    )
    rejected = _rejected_at(data, 14.50)
    assert rejected["rejection_reasons"] == [
        "fails_10pct_rule: strike 9.8% above basis, requires 10.0% "
        "(strike $14.50, basis $13.21, min strike $14.53)"
    ]
    assert rejected["human_reasons"] == [
        "Strike $14.50 is 9.8% above your $13.21 basis. "
        "Your 10% rule needs a strike of at least $14.53."
    ]
    recs = [r for r in data["recommendations"] if r["strike"] == 15.00]
    assert recs, "expected $15.00 to be a candidate"
    assert recs[0]["rule_compliance"]["passes_10pct_rule"] is True


@pytest.mark.tdd_red
def test_cc_scan_below_basis_reports_single_rule(client):
    """AC3 — strike $14 on a $20 basis fails once, not twice."""
    data = _scan(
        client,
        _chain([14.0], side="call", price=14.0),
        {"ticker": "F", "strategy": "covered_call", "cost_basis": 20.0},
    )
    codes = _rejected_at(data, 14.0)["rejection_reasons"]
    assert any(c.startswith("fails_10pct_rule") for c in codes)
    assert not any(c.startswith("below_cost_basis") for c in codes)


@pytest.mark.tdd_red
def test_cc_scan_request_threshold_flows_into_human_reason(client):
    """AC2 — a per-request T=7.5 is the T named in the sentence."""
    data = _scan(
        client,
        _chain([14.00, 15.00], side="call"),
        {
            "ticker": "F",
            "strategy": "covered_call",
            "cost_basis": 13.21,
            "min_call_distance_pct": 7.5,
        },
    )
    human = _rejected_at(data, 14.00)["human_reasons"]
    assert human == [
        "Strike $14.00 is 6.0% above your $13.21 basis. "
        "Your 7.5% rule needs a strike of at least $14.20."
    ]


@pytest.mark.integration
def test_csp_scan_unchanged_by_default_bump(client):
    """AC5 — a CSP scan never emits covered-call distance codes."""
    data = _scan(
        client,
        _chain([12.00, 13.00], side="put"),
        {
            "ticker": "F",
            "strategy": "cash_secured_put",
            "capital_available": 5000.0,
            "cost_basis": 13.21,
            "min_call_distance_pct": 10.0,
        },
    )
    all_codes = [c for r in data["rejected"] for c in r["rejection_reasons"]]
    assert not any(c.startswith("fails_10pct_rule") for c in all_codes)
    assert not any(c.startswith("below_cost_basis") for c in all_codes)
    assert _rejected_at(data, 13.00)["rejection_reasons"] == [
        "itm_put: strike $13.00 > price $12.71"
    ]
    recs = [r for r in data["recommendations"] if r["strike"] == 12.00]
    assert recs, "expected the OTM $12.00 put to be a candidate"
    assert recs[0]["rule_compliance"]["passes_10pct_rule"] is True
