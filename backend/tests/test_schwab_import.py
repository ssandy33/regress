"""Unit tests for schwab_import mapping, fee extraction, and duplicate detection."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base, Position, Trade
from app.services.schwab_import import (
    map_schwab_transaction,
    is_duplicate,
    _extract_fees,
    execute_mapped_import,
    preview_import,
)


def _make_txn(instruction, put_call, ticker="AAPL", strike=150.0,
              expiration="2025-03-21T00:00:00.000+0000", net_amount=-300.0,
              amount=1, fees=None):
    """Build a minimal Schwab transaction dict."""
    txn = {
        "transactionDate": "2025-03-01T10:00:00Z",
        "netAmount": net_amount,
        "transferItems": [
            {
                "instruction": instruction,
                "amount": amount,
                "instrument": {
                    "assetType": "OPTION",
                    "underlyingSymbol": ticker,
                    "putCall": put_call,
                    "strikePrice": strike,
                    "expirationDate": expiration,
                },
            }
        ],
    }
    if fees is not None:
        txn["fees"] = fees
    return txn


# --- Mapping tests ---

class TestMapSchwabTransaction:
    @pytest.mark.unit
    def test_sell_to_open_put(self):
        txn = _make_txn("SELL_TO_OPEN", "PUT", net_amount=300.0)
        result = map_schwab_transaction(txn)
        assert result is not None
        assert result["trade_type"] == "sell_put"
        assert result["ticker"] == "AAPL"
        assert result["strike"] == 150.0
        assert result["expiration"] == "2025-03-21"
        assert result["premium"] == 3.0  # 300 / (1 * 100)
        assert result["quantity"] == 1

    @pytest.mark.unit
    def test_sell_to_open_call(self):
        txn = _make_txn("SELL_TO_OPEN", "CALL", net_amount=500.0)
        result = map_schwab_transaction(txn)
        assert result["trade_type"] == "sell_call"
        assert result["premium"] == 5.0

    @pytest.mark.unit
    def test_buy_to_close_put(self):
        txn = _make_txn("BUY_TO_CLOSE", "PUT", net_amount=-150.0)
        result = map_schwab_transaction(txn)
        assert result["trade_type"] == "buy_put_close"
        assert result["premium"] == -1.5  # negative for buys

    @pytest.mark.unit
    def test_buy_to_close_call(self):
        txn = _make_txn("BUY_TO_CLOSE", "CALL", net_amount=-200.0)
        result = map_schwab_transaction(txn)
        assert result["trade_type"] == "buy_call_close"
        assert result["premium"] == -2.0

    @pytest.mark.unit
    def test_receive_deliver_put_assignment(self):
        txn = _make_txn("RECEIVE_DELIVER", "PUT", net_amount=0)
        result = map_schwab_transaction(txn)
        assert result["trade_type"] == "assignment"

    @pytest.mark.unit
    def test_receive_deliver_call_called_away(self):
        txn = _make_txn("RECEIVE_DELIVER", "CALL", net_amount=0)
        result = map_schwab_transaction(txn)
        assert result["trade_type"] == "called_away"

    @pytest.mark.unit
    def test_non_option_returns_none(self):
        txn = {
            "transactionDate": "2025-03-01T10:00:00Z",
            "netAmount": -1000.0,
            "transferItems": [
                {
                    "instruction": "BUY",
                    "amount": 10,
                    "instrument": {
                        "assetType": "EQUITY",
                        "symbol": "AAPL",
                    },
                }
            ],
        }
        assert map_schwab_transaction(txn) is None

    @pytest.mark.unit
    def test_unknown_instruction_returns_none(self):
        txn = _make_txn("BUY_TO_OPEN", "PUT")
        assert map_schwab_transaction(txn) is None

    @pytest.mark.unit
    def test_no_transfer_items_returns_none(self):
        txn = {"transactionDate": "2025-03-01", "netAmount": 0, "transferItems": []}
        assert map_schwab_transaction(txn) is None

    @pytest.mark.unit
    def test_premium_calculation_multiple_contracts(self):
        txn = _make_txn("SELL_TO_OPEN", "PUT", net_amount=600.0, amount=2)
        result = map_schwab_transaction(txn)
        assert result["premium"] == 3.0  # 600 / (2 * 100)
        assert result["quantity"] == 2

    @pytest.mark.unit
    def test_fee_extraction(self):
        fees = {"commission": 0.65, "secFee": 0.02, "optRegFee": 0.04, "rFee": 0, "cdscFee": 0, "otherCharges": 0}
        txn = _make_txn("SELL_TO_OPEN", "PUT", net_amount=300.0, fees=fees)
        result = map_schwab_transaction(txn)
        assert result["fees"] == 0.71

    @pytest.mark.unit
    def test_fee_extraction_no_fees(self):
        txn = _make_txn("SELL_TO_OPEN", "PUT", net_amount=300.0)
        result = map_schwab_transaction(txn)
        assert result["fees"] == 0.0

    @pytest.mark.unit
    def test_premium_grossed_up_when_netamount_excludes_fees(self):
        """Sell-put net=$29.34 + $0.66 fees + qty=1 → gross premium $0.30, not $0.29.

        Schwab's ``netAmount`` is post-fees, so dividing it by ``qty*100``
        understates the premium by ``fees / (qty*100)``. Issue #184: that
        rounding error was the visible "0.29 instead of 0.30" symptom.
        """
        fees = {
            "commission": 0.65,
            "secFee": 0.01,
            "optRegFee": 0.0,
            "rFee": 0.0,
            "cdscFee": 0.0,
            "otherCharges": 0.0,
        }
        txn = _make_txn(
            "SELL_TO_OPEN",
            "PUT",
            ticker="F",
            strike=13.50,
            net_amount=29.34,
            amount=1,
            fees=fees,
        )
        result = map_schwab_transaction(txn)
        assert result is not None
        assert result["premium"] == pytest.approx(0.30, abs=1e-4)
        assert result["premium"] != pytest.approx(0.2934, abs=1e-4)

    @pytest.mark.unit
    def test_buy_to_close_premium_grossed_down_when_netamount_includes_fees(self):
        """Buy-to-close: |netAmount| = gross + fees, so subtract fees to recover gross.

        Mirrors the sell-side gross-up but in the opposite direction. Without
        flipping the fee sign on buys, the fallback would over-state the gross
        premium by ``2 * fees / (qty*100)`` per share.
        """
        fees = {
            "commission": 0.65,
            "secFee": 0.01,
            "optRegFee": 0.0,
            "rFee": 0.0,
            "cdscFee": 0.0,
            "otherCharges": 0.0,
        }
        txn = _make_txn(
            "BUY_TO_CLOSE",
            "PUT",
            ticker="F",
            strike=13.50,
            net_amount=-30.66,
            amount=1,
            fees=fees,
        )
        result = map_schwab_transaction(txn)
        assert result is not None
        assert result["premium"] == pytest.approx(-0.30, abs=1e-4)

    @pytest.mark.unit
    def test_receive_deliver_with_fees_emits_zero_premium(self):
        """Assignment / called-away rows are not premium-bearing trades.

        If Schwab reports a non-zero fee on a RECEIVE_DELIVER row and omits
        ``transferItem.price``, the fallback gross-up would otherwise turn the
        fee into a fabricated premium. Lifecycle rows must keep premium at 0.
        """
        fees = {
            "commission": 0.0,
            "secFee": 0.10,
            "optRegFee": 0.0,
            "rFee": 0.0,
            "cdscFee": 0.0,
            "otherCharges": 0.0,
        }
        put_txn = _make_txn(
            "RECEIVE_DELIVER", "PUT", net_amount=0.0, amount=1, fees=fees
        )
        result = map_schwab_transaction(put_txn)
        assert result["trade_type"] == "assignment"
        assert result["premium"] == 0.0
        assert result["fees"] == pytest.approx(0.10)

        call_txn = _make_txn(
            "RECEIVE_DELIVER", "CALL", net_amount=0.0, amount=1, fees=fees
        )
        result = map_schwab_transaction(call_txn)
        assert result["trade_type"] == "called_away"
        assert result["premium"] == 0.0
        assert result["fees"] == pytest.approx(0.10)

    @pytest.mark.unit
    def test_premium_prefers_transferitem_price_when_present(self):
        """If Schwab exposes ``transferItem.price`` use it directly as gross.

        Some API payloads include the per-share price on the option leg;
        prefer it over the netAmount gross-up arithmetic. The two approaches
        should agree but ``price`` is the canonical field.
        """
        fees = {"commission": 0.66}
        txn = _make_txn(
            "SELL_TO_OPEN",
            "PUT",
            net_amount=29.34,
            amount=1,
            fees=fees,
        )
        # Inject the price field on the transferItem.
        txn["transferItems"][0]["price"] = 0.30
        result = map_schwab_transaction(txn)
        assert result["premium"] == pytest.approx(0.30, abs=1e-4)

    @pytest.mark.unit
    def test_premium_preserves_subpenny_precision(self):
        """Gross-up math preserves sub-penny precision (e.g. $0.295).

        Sell put @ $0.295 gross × 1 contract = $29.50 gross, minus $0.66 fees
        = $28.84 net. The import path must recover $0.295 from those inputs.
        """
        fees = {"commission": 0.65, "secFee": 0.01}
        txn = _make_txn(
            "SELL_TO_OPEN",
            "PUT",
            net_amount=28.84,
            amount=1,
            fees=fees,
        )
        result = map_schwab_transaction(txn)
        assert result["premium"] == pytest.approx(0.295, abs=1e-4)


# --- Duplicate detection ---

@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestIsDuplicate:
    @pytest.mark.unit
    def test_no_match_returns_false(self, db_session):
        assert is_duplicate(db_session, "AAPL", 150.0, "2025-03-21", "sell_put", "2025-03-01T10:00:00Z") is False

    @pytest.mark.unit
    def test_exact_match_returns_true(self, db_session):
        pos = Position(id="p1", ticker="AAPL", shares=100, broker_cost_basis=15000, status="open", strategy="wheel", opened_at="2025-01-01")
        db_session.add(pos)
        trade = Trade(id="t1", position_id="p1", trade_type="sell_put", strike=150.0, expiration="2025-03-21",
                      premium=3.0, fees=0.0, quantity=1, opened_at="2025-03-01T10:00:00Z")
        db_session.add(trade)
        db_session.commit()

        assert is_duplicate(db_session, "AAPL", 150.0, "2025-03-21", "sell_put", "2025-03-01T10:00:00Z") is True

    @pytest.mark.unit
    def test_different_strike_returns_false(self, db_session):
        pos = Position(id="p1", ticker="AAPL", shares=100, broker_cost_basis=15000, status="open", strategy="wheel", opened_at="2025-01-01")
        db_session.add(pos)
        trade = Trade(id="t1", position_id="p1", trade_type="sell_put", strike=150.0, expiration="2025-03-21",
                      premium=3.0, fees=0.0, quantity=1, opened_at="2025-03-01T10:00:00Z")
        db_session.add(trade)
        db_session.commit()

        assert is_duplicate(db_session, "AAPL", 155.0, "2025-03-21", "sell_put", "2025-03-01T10:00:00Z") is False


# --- preview_import integration: RECEIVE_AND_DELIVER assignments surface as journal trades ---

class TestPreviewImportReceiveAndDeliver:
    """End-to-end mapping check that RECEIVE_AND_DELIVER transactions produce assignment rows.

    Covers issue #119 AC: assignment and called_away rows must appear in the preview
    when the Schwab response includes RECEIVE_AND_DELIVER transactions.
    """

    @pytest.mark.unit
    @patch("app.services.schwab_import.SchwabClient")
    def test_assignment_and_called_away_appear_in_preview(self, mock_client_cls, db_session):
        """RECEIVE_DELIVER PUT and CALL transactions map to assignment + called_away."""
        client = MagicMock()
        client.get_account_numbers.return_value = [
            {"hashValue": "hash-abc", "accountNumber": "12345678"}
        ]
        client.get_transactions.return_value = [
            # Assignment: RECEIVE_AND_DELIVER type, RECEIVE_DELIVER instruction, PUT
            {
                "type": "RECEIVE_AND_DELIVER",
                "transactionDate": "2025-03-15T13:30:00Z",
                "netAmount": 0,
                "transferItems": [
                    {
                        "instruction": "RECEIVE_DELIVER",
                        "amount": 1,
                        "instrument": {
                            "assetType": "OPTION",
                            "underlyingSymbol": "AAPL",
                            "putCall": "PUT",
                            "strikePrice": 150.0,
                            "expirationDate": "2025-03-21T00:00:00.000+0000",
                        },
                    }
                ],
            },
            # Called away: RECEIVE_AND_DELIVER type, RECEIVE_DELIVER instruction, CALL
            {
                "type": "RECEIVE_AND_DELIVER",
                "transactionDate": "2025-03-15T13:31:00Z",
                "netAmount": 0,
                "transferItems": [
                    {
                        "instruction": "RECEIVE_DELIVER",
                        "amount": 1,
                        "instrument": {
                            "assetType": "OPTION",
                            "underlyingSymbol": "MSFT",
                            "putCall": "CALL",
                            "strikePrice": 400.0,
                            "expirationDate": "2025-04-18T00:00:00.000+0000",
                        },
                    }
                ],
            },
        ]
        mock_client_cls.return_value = client

        result = preview_import(db_session, "2025-01-01", "2025-03-31")

        trade_types = sorted(t["trade_type"] for t in result["trades"])
        assert trade_types == ["assignment", "called_away"]
        assert result["total"] == 2
        assert result["new_count"] == 2
        assert result["account_number"] == "****5678"


# --- Position lifecycle integration (issue #127 acceptance criteria) --------


def _mapped(
    ticker: str,
    trade_type: str,
    strike: float,
    expiration: str,
    opened_at: str,
    *,
    quantity: int = 1,
    premium: float = 0.0,
    fees: float = 0.0,
) -> dict:
    """Build the dict shape that ``execute_mapped_import`` consumes.

    Mirrors the output of :func:`map_schwab_transaction` /
    :func:`app.services.schwab_csv.parse_schwab_csv` so these integration
    tests don't need to round-trip through the parsers.
    """
    return {
        "ticker": ticker,
        "trade_type": trade_type,
        "strike": strike,
        "expiration": expiration,
        "premium": premium,
        "fees": fees,
        "quantity": quantity,
        "opened_at": opened_at,
    }


class TestPositionLifecycleOnImport:
    """End-to-end coverage of issue #127's four acceptance criteria.

    Each test drives ``execute_mapped_import`` with a crafted mapped-trade
    list (no Schwab parsing involved) and asserts the resulting Position has
    the expected lifecycle state. The recomputer is invoked as part of the
    import finalizer.
    """

    @pytest.mark.unit
    def test_ac1_called_away_closes_position(self, db_session):
        """AC #1: full wheel cycle ending in called_away → status=closed."""
        mapped = [
            _mapped("MARA", "sell_put", 20.0, "2026-02-20", "2026-02-01"),
            _mapped("MARA", "assignment", 20.0, "2026-02-20", "2026-02-20"),
            _mapped("MARA", "sell_call", 22.0, "2026-03-20", "2026-02-25"),
            _mapped("MARA", "called_away", 22.0, "2026-03-20", "2026-03-20"),
        ]

        result = execute_mapped_import(db_session, mapped)

        assert result["imported"] == 4
        assert result["positions_created"] == 1
        position = db_session.query(Position).filter(Position.ticker == "MARA").first()
        assert position is not None
        assert position.status == "closed"
        assert position.shares == 0
        assert position.closed_at == "2026-03-20"

    @pytest.mark.unit
    def test_ac1_expired_closes_position(self, db_session):
        """AC #1: sell_put → expired → status=closed (no shares acquired)."""
        mapped = [
            _mapped("HPE", "sell_put", 18.0, "2026-04-17", "2026-03-15"),
            _mapped("HPE", "expired", 18.0, "2026-04-17", "2026-04-17"),
        ]

        result = execute_mapped_import(db_session, mapped)
        assert result["imported"] == 2

        position = db_session.query(Position).filter(Position.ticker == "HPE").first()
        assert position.status == "closed"
        assert position.shares == 0
        assert position.broker_cost_basis == 0.0
        assert position.closed_at == "2026-04-17"

    @pytest.mark.unit
    def test_ac2_assignment_sets_broker_cost_basis(self, db_session):
        """AC #2: after assignment, broker_cost_basis = strike * shares."""
        mapped = [
            _mapped("F", "sell_put", 13.50, "2026-03-27", "2026-03-01"),
            _mapped("F", "assignment", 13.50, "2026-03-27", "2026-03-27"),
        ]

        execute_mapped_import(db_session, mapped)

        position = db_session.query(Position).filter(Position.ticker == "F").first()
        assert position.status == "open"
        assert position.shares == 100
        assert position.broker_cost_basis == pytest.approx(13.50 * 100)

    @pytest.mark.unit
    def test_ac3_double_assignment_aggregates_shares_and_basis(self, db_session):
        """AC #3: a second assignment increments shares (no silent no-op)."""
        mapped = [
            _mapped("SOFI", "sell_put", 28.0, "2026-02-20", "2026-02-01"),
            _mapped("SOFI", "assignment", 28.0, "2026-02-20", "2026-02-20"),
            _mapped("SOFI", "sell_put", 30.0, "2026-03-20", "2026-03-01"),
            _mapped("SOFI", "assignment", 30.0, "2026-03-20", "2026-03-20"),
        ]

        execute_mapped_import(db_session, mapped)

        position = db_session.query(Position).filter(Position.ticker == "SOFI").first()
        assert position is not None
        assert position.status == "open"
        assert position.shares == 200
        assert position.broker_cost_basis == pytest.approx(2800.0 + 3000.0)

    @pytest.mark.unit
    def test_ac4_buy_to_close_closes_position(self, db_session):
        """AC #4: sell_put → buy_to_close (no reopen) → status=closed."""
        mapped = [
            _mapped("INTC", "sell_put", 25.0, "2026-04-17", "2026-03-15"),
            _mapped("INTC", "buy_put_close", 25.0, "2026-04-17", "2026-03-25"),
        ]

        execute_mapped_import(db_session, mapped)

        position = db_session.query(Position).filter(Position.ticker == "INTC").first()
        assert position.status == "closed"
        assert position.shares == 0
        assert position.closed_at == "2026-03-25"

    @pytest.mark.unit
    def test_reopen_after_close_creates_new_position(
        self, db_session, monkeypatch
    ):
        """A new sell_put on a previously-closed ticker creates a new Position.

        The closed cycle's history (trades, dates, P&L) must remain immutable.
        """
        # Freeze the recomputer's clock to before the second-cycle leg's
        # expiration so the #134 calendar fallback doesn't auto-close the
        # still-live 2026-04-17 leg.
        from datetime import date

        from app.services import positions as positions_module

        monkeypatch.setattr(positions_module, "_utc_today", lambda: date(2026, 4, 1))

        first_cycle = [
            _mapped("F", "sell_put", 13.50, "2026-03-27", "2026-03-01"),
            _mapped("F", "buy_put_close", 13.50, "2026-03-27", "2026-03-05"),
        ]
        execute_mapped_import(db_session, first_cycle)

        second_cycle = [
            _mapped("F", "sell_put", 13.50, "2026-04-17", "2026-04-01"),
        ]
        execute_mapped_import(db_session, second_cycle)

        positions = (
            db_session.query(Position)
            .filter(Position.ticker == "F")
            .order_by(Position.opened_at.asc())
            .all()
        )
        assert len(positions) == 2
        assert positions[0].status == "closed"
        assert positions[1].status == "open"

    @pytest.mark.unit
    def test_ghost_open_positions_no_longer_appear_after_called_away(self, db_session):
        """Regression for the real-world repro in issue #127 (Schwab ****885).

        Tickers MARA / HPE / INTC whose full cycles end in called_away or
        expired must NOT appear in ``status=open`` queries, and only F (still
        open with 100 shares from assignment) should remain.
        """
        mapped = [
            # F: assigned, still open with 100 shares.
            _mapped("F", "sell_put", 13.50, "2026-03-27", "2026-03-01"),
            _mapped("F", "assignment", 13.50, "2026-03-27", "2026-03-27"),
            # MARA: full wheel cycle ending in called_away.
            _mapped("MARA", "sell_put", 20.0, "2026-02-20", "2026-02-01"),
            _mapped("MARA", "assignment", 20.0, "2026-02-20", "2026-02-20"),
            _mapped("MARA", "sell_call", 22.0, "2026-03-20", "2026-02-25"),
            _mapped("MARA", "called_away", 22.0, "2026-03-20", "2026-03-20"),
            # HPE: expired worthless.
            _mapped("HPE", "sell_put", 18.0, "2026-04-17", "2026-03-15"),
            _mapped("HPE", "expired", 18.0, "2026-04-17", "2026-04-17"),
            # INTC: closed via buy-to-close.
            _mapped("INTC", "sell_put", 25.0, "2026-04-17", "2026-03-15"),
            _mapped("INTC", "buy_put_close", 25.0, "2026-04-17", "2026-03-25"),
        ]

        execute_mapped_import(db_session, mapped)

        open_positions = (
            db_session.query(Position).filter(Position.status == "open").all()
        )
        open_tickers = {p.ticker for p in open_positions}
        assert open_tickers == {"F"}

        f_position = next(p for p in open_positions if p.ticker == "F")
        assert f_position.shares == 100
        assert f_position.broker_cost_basis == pytest.approx(1350.0)
