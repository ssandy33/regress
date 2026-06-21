"""Lock the shape of the committed equity-import sample CSV fixture (#382).

The fixture ``backend/tests/fixtures/sample-equity-import.csv`` is the canonical
working example for the v1.8.0 Equity Transaction Import feature (PR #392). It
exercises every equity row shape the parser handles: stock buys at distinct
prices, qualified + cash dividends, a partial stock sell, a sell-to-open option
leg, and an unmatched equity sell.

These integration tests read the fixture bytes, run it through
:func:`app.services.schwab_csv.parse_schwab_csv`, and assert the parsed shape so
the fixture can never silently rot. The fixture is also POSTed through the
``/api/journal/import/csv/preview`` endpoint to prove the full upload→preview
pipeline counts every equity + option row (the unmatched ``T`` sell still
PREVIEWS — it is only skipped at execute time).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.schwab_csv import parse_schwab_csv

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample-equity-import.csv"


def _fixture_bytes() -> bytes:
    """Read the committed sample-equity-import.csv fixture as raw bytes."""
    return _FIXTURE_PATH.read_bytes()


def _by_trade_type(rows: list[dict], trade_type: str) -> list[dict]:
    """Return all parsed rows of the given ``trade_type``, preserving order."""
    return [r for r in rows if r["trade_type"] == trade_type]


@pytest.mark.integration
@pytest.mark.ac("382-AC1")
def test_sample_fixture_parses_to_seven_rows():
    """The fixture parses to exactly seven journal rows (no row silently drops)."""
    rows = parse_schwab_csv(_fixture_bytes())
    assert len(rows) == 7


@pytest.mark.integration
@pytest.mark.ac("382-AC1")
def test_sample_fixture_buy_stock_unit_amounts():
    """The two F buys carry per-share unit_amount 11.0 and 13.0."""
    rows = parse_schwab_csv(_fixture_bytes())
    buys = _by_trade_type(rows, "buy_stock")
    assert len(buys) == 2
    assert all(b["ticker"] == "F" for b in buys)
    assert all(b["quantity"] == 100 for b in buys)
    assert {b["unit_amount"] for b in buys} == {11.0, 13.0}


@pytest.mark.integration
@pytest.mark.ac("382-AC1")
def test_sample_fixture_dividends_shape():
    """The two dividends carry their raw Schwab sub-type, total $, and 0 qty."""
    rows = parse_schwab_csv(_fixture_bytes())
    dividends = _by_trade_type(rows, "dividend")
    assert len(dividends) == 2
    by_reason = {d["close_reason"]: d for d in dividends}
    assert by_reason.keys() == {"Qualified Dividend", "Cash Dividend"}
    assert by_reason["Qualified Dividend"]["unit_amount"] == 30.0
    assert by_reason["Cash Dividend"]["unit_amount"] == 12.0
    assert all(d["quantity"] == 0 for d in dividends)
    # Dividends move cash, not shares — no strike/expiration, zero premium.
    assert all(d["strike"] is None and d["expiration"] is None for d in dividends)
    assert all(d["premium"] == 0.0 for d in dividends)


@pytest.mark.integration
@pytest.mark.ac("382-AC1")
def test_sample_fixture_stock_sell_shape():
    """The F sell is a sell_stock of 50 shares at unit_amount 15.0."""
    rows = parse_schwab_csv(_fixture_bytes())
    f_sells = [r for r in _by_trade_type(rows, "sell_stock") if r["ticker"] == "F"]
    assert len(f_sells) == 1
    sell = f_sells[0]
    assert sell["quantity"] == 50
    assert sell["unit_amount"] == 15.0


@pytest.mark.integration
@pytest.mark.ac("382-AC1")
def test_sample_fixture_option_leg_is_sell_put():
    """The F option leg is a sell_put (sell-to-open) with a strike + expiration."""
    rows = parse_schwab_csv(_fixture_bytes())
    puts = _by_trade_type(rows, "sell_put")
    assert len(puts) == 1
    put = puts[0]
    assert put["ticker"] == "F"
    assert put["strike"] == 13.5
    assert put["expiration"] == "2026-03-27"


@pytest.mark.integration
@pytest.mark.ac("382-AC1")
def test_sample_fixture_unmatched_t_sell_present():
    """The unmatched T sell parses as a sell_stock — it is only skipped at execute."""
    rows = parse_schwab_csv(_fixture_bytes())
    t_sells = [r for r in _by_trade_type(rows, "sell_stock") if r["ticker"] == "T"]
    assert len(t_sells) == 1
    assert t_sells[0]["quantity"] == 100
    assert t_sells[0]["unit_amount"] == 18.0


@pytest.mark.integration
@pytest.mark.ac("382-AC1")
def test_sample_fixture_preview_counts_all_rows(client):
    """POSTing the fixture to /import/csv/preview counts all 7 equity+option rows.

    The unmatched T sell still PREVIEWS — preview reports every parsed row; the
    no-shares-to-draw-on skip happens only at execute time.
    """
    files = {
        "file": (
            "sample-equity-import.csv",
            _fixture_bytes(),
            "text/csv",
        )
    }
    resp = client.post("/api/journal/import/csv/preview", files=files)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 7
    assert len(body["trades"]) == 7
