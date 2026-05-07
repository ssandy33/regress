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

    def test_sell_to_open_call(self):
        txn = _make_txn("SELL_TO_OPEN", "CALL", net_amount=500.0)
        result = map_schwab_transaction(txn)
        assert result["trade_type"] == "sell_call"
        assert result["premium"] == 5.0

    def test_buy_to_close_put(self):
        txn = _make_txn("BUY_TO_CLOSE", "PUT", net_amount=-150.0)
        result = map_schwab_transaction(txn)
        assert result["trade_type"] == "buy_put_close"
        assert result["premium"] == -1.5  # negative for buys

    def test_buy_to_close_call(self):
        txn = _make_txn("BUY_TO_CLOSE", "CALL", net_amount=-200.0)
        result = map_schwab_transaction(txn)
        assert result["trade_type"] == "buy_call_close"
        assert result["premium"] == -2.0

    def test_receive_deliver_put_assignment(self):
        txn = _make_txn("RECEIVE_DELIVER", "PUT", net_amount=0)
        result = map_schwab_transaction(txn)
        assert result["trade_type"] == "assignment"

    def test_receive_deliver_call_called_away(self):
        txn = _make_txn("RECEIVE_DELIVER", "CALL", net_amount=0)
        result = map_schwab_transaction(txn)
        assert result["trade_type"] == "called_away"

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

    def test_unknown_instruction_returns_none(self):
        txn = _make_txn("BUY_TO_OPEN", "PUT")
        assert map_schwab_transaction(txn) is None

    def test_no_transfer_items_returns_none(self):
        txn = {"transactionDate": "2025-03-01", "netAmount": 0, "transferItems": []}
        assert map_schwab_transaction(txn) is None

    def test_premium_calculation_multiple_contracts(self):
        txn = _make_txn("SELL_TO_OPEN", "PUT", net_amount=600.0, amount=2)
        result = map_schwab_transaction(txn)
        assert result["premium"] == 3.0  # 600 / (2 * 100)
        assert result["quantity"] == 2

    def test_fee_extraction(self):
        fees = {"commission": 0.65, "secFee": 0.02, "optRegFee": 0.04, "rFee": 0, "cdscFee": 0, "otherCharges": 0}
        txn = _make_txn("SELL_TO_OPEN", "PUT", net_amount=300.0, fees=fees)
        result = map_schwab_transaction(txn)
        assert result["fees"] == 0.71

    def test_fee_extraction_no_fees(self):
        txn = _make_txn("SELL_TO_OPEN", "PUT", net_amount=300.0)
        result = map_schwab_transaction(txn)
        assert result["fees"] == 0.0


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
    def test_no_match_returns_false(self, db_session):
        assert is_duplicate(db_session, "AAPL", 150.0, "2025-03-21", "sell_put", "2025-03-01T10:00:00Z") is False

    def test_exact_match_returns_true(self, db_session):
        pos = Position(id="p1", ticker="AAPL", shares=100, broker_cost_basis=15000, status="open", strategy="wheel", opened_at="2025-01-01")
        db_session.add(pos)
        trade = Trade(id="t1", position_id="p1", trade_type="sell_put", strike=150.0, expiration="2025-03-21",
                      premium=3.0, fees=0.0, quantity=1, opened_at="2025-03-01T10:00:00Z")
        db_session.add(trade)
        db_session.commit()

        assert is_duplicate(db_session, "AAPL", 150.0, "2025-03-21", "sell_put", "2025-03-01T10:00:00Z") is True

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
