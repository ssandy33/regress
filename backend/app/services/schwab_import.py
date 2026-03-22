"""Import options trades from Schwab Trader API into the trade journal."""

import logging
import re

from sqlalchemy.orm import Session

from app.models.database import Position, Trade
from app.models.schemas import TradeCreate
from app.services.journal import create_trade, create_position
from app.models.schemas import PositionCreate
from app.services.schwab_client import SchwabClient

logger = logging.getLogger(__name__)

# Schwab instruction + putCall → journal trade_type
_INSTRUCTION_MAP = {
    ("SELL_TO_OPEN", "PUT"): "sell_put",
    ("SELL_TO_OPEN", "CALL"): "sell_call",
    ("BUY_TO_CLOSE", "PUT"): "buy_put_close",
    ("BUY_TO_CLOSE", "CALL"): "buy_call_close",
    ("RECEIVE_DELIVER", "PUT"): "assignment",
    ("RECEIVE_DELIVER", "CALL"): "called_away",
}


def map_schwab_transaction(txn: dict) -> dict | None:
    """Map a Schwab transaction dict to journal trade fields.

    Returns None for non-option or unrecognized transactions.
    """
    transfer_items = txn.get("transferItems", [])
    if not transfer_items:
        return None

    item = transfer_items[0]
    instrument = item.get("instrument", {})

    if instrument.get("assetType") != "OPTION":
        return None

    instruction = item.get("instruction", "")
    put_call = instrument.get("putCall", "")

    trade_type = _INSTRUCTION_MAP.get((instruction, put_call))
    if trade_type is None:
        return None

    ticker = instrument.get("underlyingSymbol", "")
    if not ticker:
        return None

    strike = float(instrument.get("strikePrice", 0))

    # Normalize expiration to YYYY-MM-DD
    raw_expiration = instrument.get("expirationDate", "")
    expiration = _normalize_date(raw_expiration)

    quantity = abs(int(item.get("amount", 1)))
    net_amount = float(txn.get("netAmount", 0))

    # Premium per share: abs(netAmount) / (quantity * 100)
    # Positive for sells (credits), negative for buys (debits)
    if quantity > 0:
        premium_per_share = abs(net_amount) / (quantity * 100)
    else:
        premium_per_share = 0.0

    # Sign convention: positive for sells, negative for buys
    if instruction in ("BUY_TO_CLOSE",):
        premium_per_share = -premium_per_share

    fees = _extract_fees(txn)
    opened_at = txn.get("transactionDate", "")

    return {
        "ticker": ticker,
        "trade_type": trade_type,
        "strike": strike,
        "expiration": expiration,
        "premium": round(premium_per_share, 4),
        "fees": round(fees, 2),
        "quantity": quantity,
        "opened_at": opened_at,
    }


def _normalize_date(date_str: str) -> str:
    """Normalize a date string to YYYY-MM-DD."""
    if not date_str:
        return ""
    # Handle ISO datetime strings like "2024-03-15T00:00:00.000+0000"
    match = re.match(r"(\d{4}-\d{2}-\d{2})", date_str)
    if match:
        return match.group(1)
    return date_str


def _extract_fees(txn: dict) -> float:
    """Extract total fees from a Schwab transaction."""
    fees = txn.get("fees", {})
    if isinstance(fees, dict):
        total = 0.0
        for key in ("commission", "secFee", "optRegFee", "rFee", "cdscFee", "otherCharges"):
            total += float(fees.get(key, 0))
        return total
    return float(fees or 0)


def is_duplicate(
    db: Session,
    ticker: str,
    strike: float,
    expiration: str,
    trade_type: str,
    opened_at: str,
) -> bool:
    """Check if a matching trade already exists in the journal."""
    result = (
        db.query(Trade)
        .join(Position, Trade.position_id == Position.id)
        .filter(
            Position.ticker == ticker,
            Trade.strike == strike,
            Trade.expiration == expiration,
            Trade.trade_type == trade_type,
            Trade.opened_at == opened_at,
        )
        .first()
    )
    return result is not None


def preview_import(db: Session, start_date: str, end_date: str) -> dict:
    """Preview Schwab transactions for import.

    Returns dict with account info, trade list, and duplicate counts.
    """
    client = SchwabClient()
    account_numbers = client.get_account_numbers()

    if not account_numbers:
        return {
            "account_number": "",
            "trades": [],
            "total": 0,
            "duplicates": 0,
            "new_count": 0,
        }

    account = account_numbers[0]
    account_hash = account.get("hashValue", "")
    account_number = account.get("accountNumber", "")
    masked_account = f"****{account_number[-4:]}" if len(account_number) >= 4 else account_number

    transactions = client.get_transactions(account_hash, start_date, end_date)

    trades = []
    duplicates = 0
    for txn in transactions:
        mapped = map_schwab_transaction(txn)
        if mapped is None:
            continue

        dup = is_duplicate(
            db, mapped["ticker"], mapped["strike"], mapped["expiration"],
            mapped["trade_type"], mapped["opened_at"],
        )
        if dup:
            duplicates += 1

        trades.append({**mapped, "is_duplicate": dup})

    return {
        "account_number": masked_account,
        "trades": trades,
        "total": len(trades),
        "duplicates": duplicates,
        "new_count": len(trades) - duplicates,
    }


def execute_import(db: Session, start_date: str, end_date: str, position_strategy: str = "wheel") -> dict:
    """Import Schwab transactions into the journal.

    Creates positions as needed and logs trades.
    """
    client = SchwabClient()
    account_numbers = client.get_account_numbers()

    if not account_numbers:
        return {"imported": 0, "skipped_duplicates": 0, "positions_created": 0}

    account = account_numbers[0]
    account_hash = account.get("hashValue", "")
    transactions = client.get_transactions(account_hash, start_date, end_date)

    imported = 0
    skipped = 0
    positions_created = 0

    for txn in transactions:
        mapped = map_schwab_transaction(txn)
        if mapped is None:
            continue

        if is_duplicate(
            db, mapped["ticker"], mapped["strike"], mapped["expiration"],
            mapped["trade_type"], mapped["opened_at"],
        ):
            skipped += 1
            continue

        # Find or create position for this ticker
        position = (
            db.query(Position)
            .filter(Position.ticker == mapped["ticker"], Position.status == "open")
            .first()
        )
        if position is None:
            pos_data = PositionCreate(
                ticker=mapped["ticker"],
                shares=100,
                broker_cost_basis=0.0,
                strategy=position_strategy,
                opened_at=mapped["opened_at"],
            )
            pos_result = create_position(db, pos_data)
            position = db.query(Position).filter(Position.id == pos_result["id"]).first()
            positions_created += 1

        trade_data = TradeCreate(
            position_id=position.id,
            trade_type=mapped["trade_type"],
            strike=mapped["strike"],
            expiration=mapped["expiration"],
            premium=mapped["premium"],
            fees=mapped["fees"],
            quantity=mapped["quantity"],
            opened_at=mapped["opened_at"],
        )
        create_trade(db, trade_data)
        imported += 1

    return {
        "imported": imported,
        "skipped_duplicates": skipped,
        "positions_created": positions_created,
    }
