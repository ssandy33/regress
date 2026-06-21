"""Unit + integration tests for Schwab CSV import (issue #104).

Covers ``app.services.schwab_csv.parse_schwab_csv`` and the matching
``POST /api/journal/import/csv/preview`` and ``POST /api/journal/import/csv``
endpoints. The fixtures here intentionally mirror real Schwab transaction
exports so any regression in symbol/date parsing is caught early.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.schwab_csv import parse_schwab_csv


# --- Fixtures ---------------------------------------------------------------


def _csv(rows: list[str]) -> bytes:
    """Build a Schwab-style CSV from a list of pre-formatted lines."""
    header = "Date,Action,Symbol,Description,Quantity,Price,Fees & Comm,Amount"
    return ("\n".join([header, *rows]) + "\n").encode("utf-8")


SELL_PUT_ROW = (
    '03/01/2026,Sell to Open,F 03/27/2026 13.50 P,'
    'PUT FORD MOTOR CO $13.50 EXP 03/27/26,1,0.30,0.65,29.35'
)
SELL_CALL_ROW = (
    '03/02/2026,Sell to Open,SOFI 03/20/2026 31.00 C,'
    'CALL SOFI TECHNOLOGIES INC $31 EXP 03/20/26,2,0.50,1.30,98.70'
)
BUY_TO_CLOSE_ROW = (
    '03/05/2026,Buy to Close,F 03/27/2026 13.50 P,'
    'PUT FORD MOTOR CO $13.50 EXP 03/27/26,1,0.10,0.65,(10.65)'
)
ASSIGNED_PUT_ROW = (
    '03/27/2026,Assigned,F 03/27/2026 13.50 P,'
    'PUT FORD MOTOR CO ASSIGNMENT,1,,0.00,0.00'
)
EXPIRED_CALL_ROW = (
    '03/20/2026,Expired,SOFI 03/20/2026 31.00 C,'
    'CALL SOFI EXPIRATION,2,,0.00,0.00'
)

# Non-options noise that must be silently skipped.
STOCK_BUY_ROW = '03/01/2026,Buy,AAPL,APPLE INC,100,150.00,0.00,(15000.00)'
DIVIDEND_ROW = '03/15/2026,Cash Dividend,AAPL,APPLE INC DIVIDEND,,,,25.00'
ACH_ROW = '03/01/2026,Funds Received,,ACH RECEIPT,,,,1000.00'

# Canonical OCC symbol — older Schwab exports use this layout.
OCC_SELL_PUT_ROW = (
    '03/10/2026,Sell to Open,AAPL  260315P00185000,'
    'PUT AAPL $185 EXP 03/15/26,1,1.20,0.65,119.35'
)


# --- parse_schwab_csv unit tests --------------------------------------------


class TestParseSchwabCsv:
    """Cover the happy-path mappings, skip rules, and malformed input."""

    @pytest.mark.unit
    def test_sell_to_open_put_human_symbol(self):
        result = parse_schwab_csv(_csv([SELL_PUT_ROW]))
        assert len(result) == 1
        row = result[0]
        assert row["ticker"] == "F"
        assert row["trade_type"] == "sell_put"
        assert row["strike"] == 13.50
        assert row["expiration"] == "2026-03-27"
        assert row["quantity"] == 1
        # Premium per share = gross Price column (0.30), not the post-fee
        # net (29.35 / 100 = 0.2935) — corrected after #184.
        assert row["premium"] == pytest.approx(0.30, abs=1e-4)
        assert row["fees"] == 0.65
        assert row["opened_at"] == "2026-03-01"

    @pytest.mark.unit
    def test_sell_to_open_call_multi_contract(self):
        result = parse_schwab_csv(_csv([SELL_CALL_ROW]))
        assert len(result) == 1
        row = result[0]
        assert row["ticker"] == "SOFI"
        assert row["trade_type"] == "sell_call"
        assert row["quantity"] == 2
        # Gross per-share Price column = 0.50 (was 98.70 / (2*100) = 0.4935
        # — the post-fee net — corrected after #184).
        assert row["premium"] == pytest.approx(0.50, abs=1e-4)

    @pytest.mark.unit
    def test_buy_to_close_premium_is_negative(self):
        result = parse_schwab_csv(_csv([BUY_TO_CLOSE_ROW]))
        assert len(result) == 1
        row = result[0]
        assert row["trade_type"] == "buy_put_close"
        # Gross per-share Price column = 0.10 (sign flipped for buy_to_close).
        # Pre-#184 this used post-fee net (-0.1065).
        assert row["premium"] == pytest.approx(-0.10, abs=1e-4)

    @pytest.mark.unit
    def test_assigned_maps_to_assignment(self):
        result = parse_schwab_csv(_csv([ASSIGNED_PUT_ROW]))
        assert len(result) == 1
        assert result[0]["trade_type"] == "assignment"

    @pytest.mark.unit
    def test_expired_call_maps_to_expired(self):
        """An expired call must map to ``trade_type="expired"``, not ``called_away``.

        Pre-#127, ``Action="Expired"`` was conflated with ``Assigned`` /
        ``Exercised`` and incorrectly moved shares + broker basis on the
        position. The recomputer treats ``expired`` as a leg-only close: no
        share movement, no basis change.
        """
        result = parse_schwab_csv(_csv([EXPIRED_CALL_ROW]))
        assert len(result) == 1
        assert result[0]["trade_type"] == "expired"

    @pytest.mark.unit
    def test_expired_put_maps_to_expired(self):
        """An expired put also maps to ``trade_type="expired"`` — not ``assignment``.

        This is the real-world repro from issue #127 (HPE / INTC / VZ on
        Schwab ****885): pre-fix, expired-worthless puts were silently
        recorded as assignments and moved nonexistent shares onto the position.
        """
        expired_put_row = (
            '03/20/2026,Expired,SOFI 03/20/2026 28.00 P,'
            'PUT SOFI EXPIRATION,1,,0.00,0.00'
        )
        result = parse_schwab_csv(_csv([expired_put_row]))
        assert len(result) == 1
        assert result[0]["trade_type"] == "expired"
        assert result[0]["ticker"] == "SOFI"

    @pytest.mark.unit
    def test_occ_format_symbol_parses(self):
        result = parse_schwab_csv(_csv([OCC_SELL_PUT_ROW]))
        assert len(result) == 1
        row = result[0]
        assert row["ticker"] == "AAPL"
        assert row["strike"] == 185.0
        assert row["expiration"] == "2026-03-15"
        assert row["trade_type"] == "sell_put"

    @pytest.mark.unit
    def test_full_mix_round_trip(self):
        rows = [
            SELL_PUT_ROW,
            SELL_CALL_ROW,
            BUY_TO_CLOSE_ROW,
            ASSIGNED_PUT_ROW,
            EXPIRED_CALL_ROW,
            STOCK_BUY_ROW,
            DIVIDEND_ROW,
            ACH_ROW,
        ]
        result = parse_schwab_csv(_csv(rows))
        # Bridge edit (issue #385): five options rows survive PLUS the stock
        # buy and dividend rows are now recognized as equity trades. Only the
        # ACH transfer is skipped silently.
        assert len(result) == 7
        trade_types = sorted(r["trade_type"] for r in result)
        # "Expired" maps to its own trade_type (issue #127); buy_stock and
        # dividend are the new equity types (issue #385).
        assert trade_types == [
            "assignment",
            "buy_put_close",
            "buy_stock",
            "dividend",
            "expired",
            "sell_call",
            "sell_put",
        ]

    @pytest.mark.unit
    def test_non_options_rows_skipped(self):
        # Bridge edit (issue #385): STOCK_BUY_ROW and DIVIDEND_ROW are now
        # recognized as equity/dividend trades. Only genuine non-equity noise
        # (ACH transfer) is still silently skipped.
        result = parse_schwab_csv(_csv([STOCK_BUY_ROW, DIVIDEND_ROW, ACH_ROW]))
        trade_types = sorted(r["trade_type"] for r in result)
        assert trade_types == ["buy_stock", "dividend"]

    @pytest.mark.unit
    def test_unknown_action_skipped(self):
        # "Journal" / "Wire Transfer" / etc. should never crash the parser.
        rows = [
            '03/01/2026,Journal,F 03/27/2026 13.50 P,JOURNAL,1,,0.00,0.00',
            '03/01/2026,Wire Transfer,,,,,,5000.00',
        ]
        assert parse_schwab_csv(_csv(rows)) == []

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "bad_symbol",
        [
            "F GARBAGE 13.50 P",   # wrong date layout
            "F 03/27/2026 P",       # missing strike
            "F 13/40/2026 13.50 P",  # invalid date
            "AAPL 99X9999P00000000",  # OCC-shaped but malformed
            "",                       # empty
        ],
    )
    def test_malformed_symbols_skipped(self, bad_symbol):
        row = (
            f'03/01/2026,Sell to Open,{bad_symbol},'
            f'JUNK,1,1.00,0.65,99.35'
        )
        assert parse_schwab_csv(_csv([row])) == []

    @pytest.mark.unit
    def test_missing_required_columns_returns_empty(self):
        # No "Symbol" column at all — entire file rejected.
        body = (
            "Date,Action,Quantity,Amount\n"
            "03/01/2026,Sell to Open,1,29.35\n"
        ).encode("utf-8")
        assert parse_schwab_csv(body) == []

    @pytest.mark.unit
    def test_empty_file_returns_empty(self):
        assert parse_schwab_csv(b"") == []
        assert parse_schwab_csv(b"\n") == []

    @pytest.mark.unit
    def test_utf8_bom_tolerated(self):
        body = b"\xef\xbb\xbf" + _csv([SELL_PUT_ROW])
        assert len(parse_schwab_csv(body)) == 1

    @pytest.mark.unit
    def test_zero_quantity_row_skipped(self):
        row = (
            '03/01/2026,Sell to Open,F 03/27/2026 13.50 P,'
            'JUNK,0,0.30,0.65,29.35'
        )
        assert parse_schwab_csv(_csv([row])) == []

    @pytest.mark.unit
    def test_amount_with_dollar_and_comma(self):
        # Schwab sometimes formats Amount as "$1,234.56".
        row = (
            '03/01/2026,Sell to Open,SOFI 03/20/2026 31.00 C,'
            'JUNK,2,5.00,1.30,"$998.70"'
        )
        result = parse_schwab_csv(_csv([row]))
        assert len(result) == 1
        # Gross per-share Price column = 5.00 (was 998.70 / (2*100) = 4.9935
        # — the post-fee net — corrected after #184).
        assert result[0]["premium"] == pytest.approx(5.00, abs=1e-4)


# --- API endpoint integration tests -----------------------------------------


def _csv_file(content: bytes, filename: str = "schwab.csv") -> dict:
    """Build the multipart `files` payload for TestClient.post."""
    return {"file": (filename, content, "text/csv")}


class TestImportCsvPreviewEndpoint:
    """Cover ``POST /api/journal/import/csv/preview`` validation + happy path."""

    @pytest.mark.integration
    def test_preview_rejects_wrong_extension(self, client):
        resp = client.post(
            "/api/journal/import/csv/preview",
            files=_csv_file(_csv([SELL_PUT_ROW]), filename="trades.txt"),
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "Only .csv files are accepted"

    @pytest.mark.integration
    def test_preview_rejects_oversized_file(self, client):
        # 6 MB synthetic body — header byte + filler. Body content is irrelevant
        # because size is checked before parsing.
        oversized = b"Date,Action,Symbol,Description,Quantity,Price,Fees & Comm,Amount\n"
        oversized += b"x" * (6 * 1024 * 1024)
        resp = client.post(
            "/api/journal/import/csv/preview",
            files=_csv_file(oversized),
        )
        assert resp.status_code == 422
        assert "5 MB" in resp.json()["detail"]

    @pytest.mark.integration
    def test_preview_rejects_empty_file(self, client):
        resp = client.post(
            "/api/journal/import/csv/preview",
            files=_csv_file(b""),
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "Uploaded file is empty"

    @pytest.mark.integration
    def test_preview_returns_correct_shape(self, client):
        # Bridge edit (issue #385): the equity STOCK_BUY_ROW is now recognized
        # alongside the two option rows, so the preview counts all three. The
        # equity row carries N/A (None) strike/expiration and a unit_amount.
        resp = client.post(
            "/api/journal/import/csv/preview",
            files=_csv_file(_csv([SELL_PUT_ROW, SELL_CALL_ROW, STOCK_BUY_ROW])),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["new_count"] == 3
        assert data["duplicates"] == 0
        # CSV path has no account number — UI handles the empty value.
        assert data["account_number"] == ""
        tickers = sorted(t["ticker"] for t in data["trades"])
        assert tickers == ["AAPL", "F", "SOFI"]
        for trade in data["trades"]:
            assert trade["is_duplicate"] is False
        equity = next(t for t in data["trades"] if t["trade_type"] == "buy_stock")
        assert equity["strike"] is None
        assert equity["expiration"] is None
        assert equity["unit_amount"] == 150.0

    @pytest.mark.integration
    def test_preview_counts_equity_and_ignores_transfers(self, client):
        # Bridge edit (issue #385): equity rows are no longer "non-options =
        # empty". A stock buy and a dividend are recognized and counted; a pure
        # cash transfer (ACH) is still ignored. Replaces the old
        # ``test_preview_with_only_non_options_returns_empty`` whose premise
        # (equity → empty) AC1a overturns.
        resp = client.post(
            "/api/journal/import/csv/preview",
            files=_csv_file(_csv([STOCK_BUY_ROW, DIVIDEND_ROW, ACH_ROW])),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["new_count"] == 2
        types = sorted(t["trade_type"] for t in data["trades"])
        assert types == ["buy_stock", "dividend"]

    @pytest.mark.integration
    def test_preview_does_not_leak_exception_message(self, client):
        # If parsing somehow crashes (defensive, since parse_schwab_csv catches
        # per-row errors), the endpoint must return a generic 422.
        with patch(
            "app.routers.journal.parse_schwab_csv",
            side_effect=RuntimeError("internal secret"),
        ):
            resp = client.post(
                "/api/journal/import/csv/preview",
                files=_csv_file(_csv([SELL_PUT_ROW])),
            )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "internal secret" not in detail
        assert detail == "Could not parse the uploaded CSV file"


class TestImportCsvEndpoint:
    """Cover ``POST /api/journal/import/csv`` write path + duplicate handling."""

    @pytest.mark.integration
    def test_import_creates_trades_and_positions(self, client):
        # Stale clients may still post `position_strategy`; the field is
        # ignored by FastAPI under #131 but the request must still succeed.
        resp = client.post(
            "/api/journal/import/csv",
            files=_csv_file(_csv([SELL_PUT_ROW, SELL_CALL_ROW])),
            data={"position_strategy": "wheel"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 2
        assert data["positions_created"] == 2
        assert data["skipped_duplicates"] == 0

        positions = client.get("/api/journal/positions").json()["positions"]
        tickers = {p["ticker"] for p in positions}
        assert tickers == {"F", "SOFI"}

    @pytest.mark.integration
    def test_import_derives_strategy_label(self, client, monkeypatch):
        # `position_strategy` form field is no longer accepted under #131.
        # The recomputer derives the label per position state. F has a single
        # short put with no shares → "csp". SOFI has a single short call
        # with no shares → "cc" (anomaly path; logged warning).
        #
        # The hard-coded 2026-03 expirations in SELL_*_ROW are already past
        # relative to wall-clock time, so freeze the recomputer's clock to
        # before those expirations — otherwise the #134 calendar fallback
        # would close both legs and flip the labels.
        from datetime import date

        from app.services import positions as positions_module

        monkeypatch.setattr(positions_module, "_utc_today", lambda: date(2026, 3, 1))
        resp = client.post(
            "/api/journal/import/csv",
            files=_csv_file(_csv([SELL_PUT_ROW, SELL_CALL_ROW])),
        )
        assert resp.status_code == 200
        positions = client.get("/api/journal/positions").json()["positions"]
        labels = {p["ticker"]: p["strategy"] for p in positions}
        assert labels["F"] == "csp"
        assert labels["SOFI"] == "cc"

    @pytest.mark.integration
    def test_import_skips_duplicates_on_second_upload(self, client):
        body = _csv([SELL_PUT_ROW, SELL_CALL_ROW])
        first = client.post("/api/journal/import/csv", files=_csv_file(body))
        assert first.json()["imported"] == 2

        second = client.post("/api/journal/import/csv", files=_csv_file(body))
        data = second.json()
        assert data["imported"] == 0
        assert data["skipped_duplicates"] == 2
        assert data["positions_created"] == 0

    @pytest.mark.integration
    def test_import_ignores_legacy_strategy_field(self, client):
        # Stale clients may still post `position_strategy`; under #131 the
        # field is no longer declared on the handler so FastAPI silently
        # ignores it. A bogus value must therefore *succeed*, not 422 — this
        # locks in the back-compat contract called out in the issue.
        resp = client.post(
            "/api/journal/import/csv",
            files=_csv_file(_csv([SELL_PUT_ROW])),
            data={"position_strategy": "not-a-strategy"},
        )
        assert resp.status_code == 200

    @pytest.mark.integration
    def test_import_rejects_oversized_file(self, client):
        oversized = b"Date,Action,Symbol,Description,Quantity,Price,Fees & Comm,Amount\n"
        oversized += b"x" * (6 * 1024 * 1024)
        resp = client.post(
            "/api/journal/import/csv",
            files=_csv_file(oversized),
        )
        assert resp.status_code == 422

    @pytest.mark.integration
    def test_import_does_not_leak_exception_message(self, client):
        with patch(
            "app.routers.journal.parse_schwab_csv",
            side_effect=RuntimeError("internal secret"),
        ):
            resp = client.post(
                "/api/journal/import/csv",
                files=_csv_file(_csv([SELL_PUT_ROW])),
            )
        assert resp.status_code == 422
        assert "internal secret" not in resp.json()["detail"]


# --- Equity / dividend parsing unit tests (issue #385) ----------------------
#
# L1 parser support for stock buys, stock sells, and dividends. Equity rows
# carry a plain ticker the option parser rejects; their mapped-dict shape is the
# frozen contract: premium is always 0.0 (money flows through ``unit_amount``),
# strike/expiration are None, and dividends stash the raw Schwab action verb in
# ``close_reason``. Appended at EOF per the parallel-execution convention.

# Equity-style CSV rows: Action is Buy/Sell/<dividend verb>, Symbol is a plain
# ticker. Columns: Date,Action,Symbol,Description,Quantity,Price,Fees & Comm,Amount
EQUITY_BUY_ROW = '03/01/2026,Buy,AAPL,APPLE INC,100,150.00,1.00,(15001.00)'
EQUITY_SELL_ROW = '03/05/2026,Sell,F,FORD MOTOR CO,200,13.25,0.50,2649.50'
EQUITY_BUY_NO_PRICE_ROW = '03/02/2026,Buy,MSFT,MICROSOFT CORP,10,,0.00,(4000.00)'
CASH_DIV_ROW = '03/15/2026,Cash Dividend,AAPL,APPLE INC,,,,25.00'
QUALIFIED_DIV_ROW = '03/16/2026,Qualified Dividend,F,FORD MOTOR CO,,,,12.34'
ORDINARY_DIV_ROW = '03/17/2026,Ordinary Dividend,MSFT,MICROSOFT CORP,,,,8.00'


class TestParseEquityRows:
    """Cover equity buy/sell + dividend mapping (issue #385, AC1a-AC1e, AC4a)."""

    @pytest.mark.unit
    def test_buy_stock_mapping(self):
        result = parse_schwab_csv(_csv([EQUITY_BUY_ROW]))
        assert len(result) == 1
        row = result[0]
        assert row["ticker"] == "AAPL"
        assert row["trade_type"] == "buy_stock"
        # Per-share price from the Price column.
        assert row["unit_amount"] == pytest.approx(150.00, abs=1e-4)
        assert row["quantity"] == 100
        # Equity money never flows through premium — it would corrupt the
        # position headline (premium x qty x 100 over all trades).
        assert row["premium"] == 0.0
        assert row["strike"] is None
        assert row["expiration"] is None
        assert row["close_reason"] is None
        assert row["fees"] == 1.00
        assert row["opened_at"] == "2026-03-01"

    @pytest.mark.unit
    def test_sell_stock_mapping(self):
        result = parse_schwab_csv(_csv([EQUITY_SELL_ROW]))
        assert len(result) == 1
        row = result[0]
        assert row["ticker"] == "F"
        assert row["trade_type"] == "sell_stock"
        assert row["unit_amount"] == pytest.approx(13.25, abs=1e-4)
        assert row["quantity"] == 200
        assert row["premium"] == 0.0
        assert row["strike"] is None
        assert row["expiration"] is None
        assert row["close_reason"] is None

    @pytest.mark.unit
    def test_buy_stock_price_missing_falls_back_to_amount(self):
        # No Price column value: unit_amount = abs(Amount) / quantity.
        result = parse_schwab_csv(_csv([EQUITY_BUY_NO_PRICE_ROW]))
        assert len(result) == 1
        row = result[0]
        assert row["trade_type"] == "buy_stock"
        # 4000.00 / 10 = 400.00 per share.
        assert row["unit_amount"] == pytest.approx(400.00, abs=1e-4)
        assert row["quantity"] == 10

    @pytest.mark.unit
    def test_dividend_mapping(self):
        result = parse_schwab_csv(_csv([CASH_DIV_ROW]))
        assert len(result) == 1
        row = result[0]
        assert row["ticker"] == "AAPL"
        assert row["trade_type"] == "dividend"
        # Dividend unit_amount is the TOTAL dollar amount, not per-share.
        assert row["unit_amount"] == pytest.approx(25.00, abs=1e-2)
        # A dividend moves no shares.
        assert row["quantity"] == 0
        assert row["premium"] == 0.0
        assert row["strike"] is None
        assert row["expiration"] is None
        # Raw Schwab sub-type verbatim for future tax-bucket reporting.
        assert row["close_reason"] == "Cash Dividend"

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "row,expected_reason",
        [
            (CASH_DIV_ROW, "Cash Dividend"),
            (QUALIFIED_DIV_ROW, "Qualified Dividend"),
            (ORDINARY_DIV_ROW, "Ordinary Dividend"),
        ],
    )
    def test_dividend_subtype_variants(self, row, expected_reason):
        # All dividend sub-types classify as dividend and preserve the raw verb.
        result = parse_schwab_csv(_csv([row]))
        assert len(result) == 1
        assert result[0]["trade_type"] == "dividend"
        assert result[0]["close_reason"] == expected_reason

    @pytest.mark.unit
    def test_dividend_contains_fallback_recognizes_unseen_verb(self):
        # A verb not in the explicit set but containing "dividend" still maps.
        row = '03/18/2026,Pr Yr Special Dividend,AAPL,APPLE INC,,,,5.00'
        result = parse_schwab_csv(_csv([row]))
        assert len(result) == 1
        assert result[0]["trade_type"] == "dividend"
        assert result[0]["close_reason"] == "Pr Yr Special Dividend"

    @pytest.mark.unit
    def test_equity_only_csv_returns_count_gt_zero(self):
        # AC1a: an all-equity CSV no longer parses to empty.
        result = parse_schwab_csv(_csv([EQUITY_BUY_ROW, EQUITY_SELL_ROW, CASH_DIV_ROW]))
        assert len(result) == 3
        assert sorted(r["trade_type"] for r in result) == [
            "buy_stock",
            "dividend",
            "sell_stock",
        ]

    @pytest.mark.unit
    def test_unrecognized_equity_verb_logs_and_skips(self, caplog):
        # AC1e: a plain-ticker row with a money Amount but an unclassifiable
        # verb must log a structured warning and be skipped — not crash, not
        # counted.
        # Plain ticker + a money Amount trips the equity-activity heuristic.
        row = '03/19/2026,Stock Split,AAPL,APPLE INC SPLIT,5,,0.00,500.00'
        with caplog.at_level("WARNING"):
            result = parse_schwab_csv(_csv([row]))
        assert result == []
        events = [
            rec for rec in caplog.records
            if getattr(rec, "event", None) == "equity_row.skipped"
        ]
        assert len(events) == 1
        assert events[0].ticker == "AAPL"
        assert events[0].outcome == "no_data"

    @pytest.mark.unit
    def test_mixed_options_and_equity_parses_both(self):
        # Options rows and equity rows both survive in one file.
        rows = [SELL_PUT_ROW, EQUITY_BUY_ROW, CASH_DIV_ROW, EXPIRED_CALL_ROW]
        result = parse_schwab_csv(_csv(rows))
        assert len(result) == 4
        by_type = sorted(r["trade_type"] for r in result)
        assert by_type == ["buy_stock", "dividend", "expired", "sell_put"]
        # The option row keeps its option shape (non-null strike/expiration).
        sell_put = next(r for r in result if r["trade_type"] == "sell_put")
        assert sell_put["strike"] == 13.50
        assert sell_put["expiration"] == "2026-03-27"

    @pytest.mark.unit
    def test_equity_buy_zero_quantity_logs_and_skips(self, caplog):
        # A share-moving row with no positive quantity is skipped with a warning
        # rather than emitting a divide-by-zero or a 0-share trade.
        row = '03/01/2026,Buy,AAPL,APPLE INC,0,150.00,0.00,0.00'
        with caplog.at_level("WARNING"):
            result = parse_schwab_csv(_csv([row]))
        assert result == []
        events = [
            rec for rec in caplog.records
            if getattr(rec, "event", None) == "equity_row.skipped"
        ]
        assert len(events) == 1
        assert events[0].ticker == "AAPL"
