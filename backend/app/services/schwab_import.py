"""Import options trades from Schwab Trader API into the trade journal."""

import logging
import re

from sqlalchemy.orm import Session

from app.models.database import Position, Trade
from app.models.schemas import PositionCreate, TradeCreate
from app.services.journal import create_position, create_trade
from app.services.positions import recompute_position_state
from app.services.schwab_client import SchwabClient

logger = logging.getLogger(__name__)

# Schwab instruction + putCall → journal trade_type.
#
# Note: the API path does **not** currently emit ``"expired"`` — Schwab's API
# delivers expired-worthless options as a ``RECEIVE_DELIVER`` transaction with
# ``netAmount == 0``, which we still surface as ``assignment`` / ``called_away``.
# Distinguishing expired from assigned on the API path requires inspecting the
# paired equity transferItem and is deferred to a follow-up issue. The CSV path
# (see :mod:`app.services.schwab_csv`) uses the literal ``Action="Expired"`` and
# already maps to ``"expired"`` for both puts and calls.
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
    fees = _extract_fees(txn)

    # Premium per share: prefer the gross per-share price reported on the
    # transferItem when Schwab provides it; otherwise gross-up the post-fee
    # ``netAmount`` by adding the fee total back in before dividing. Schwab's
    # ``netAmount`` field is the *net* dollar movement after commissions and
    # exchange fees, so using it raw understates the premium by ``fees / (qty
    # * 100)`` per share (issue #184: a 1-contract sell put at $0.30 with
    # $0.66 in fees nets to $29.34, which rounds to $0.29 — the visible bug).
    #
    # Positive for sells (credits), negative for buys (debits).
    # For sells, |netAmount| = gross − fees → add fees back to recover gross.
    # For buys, |netAmount| = gross + fees → subtract fees.
    is_buy = instruction.startswith("BUY")
    fee_adjustment = -fees if is_buy else fees

    raw_price = item.get("price")
    if instruction == "RECEIVE_DELIVER":
        # Assignment / called-away are lifecycle events, not premium-bearing
        # trades. Any fees on these rows stay in ``fees`` only.
        premium_per_share = 0.0
    elif raw_price is not None:
        try:
            premium_per_share = abs(float(raw_price))
        except (TypeError, ValueError):
            premium_per_share = (
                max((abs(net_amount) + fee_adjustment) / (quantity * 100), 0.0)
                if quantity > 0
                else 0.0
            )
    elif quantity > 0:
        premium_per_share = max(
            (abs(net_amount) + fee_adjustment) / (quantity * 100), 0.0
        )
    else:
        premium_per_share = 0.0

    # Sign convention: positive for sells, negative for buys
    if instruction in ("BUY_TO_CLOSE",):
        premium_per_share = -premium_per_share

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


def build_preview(
    db: Session,
    mapped_trades: list[dict],
    account_number: str = "",
) -> dict:
    """Build a preview response from a list of pre-mapped trade dicts.

    Shared between the API preview path (``preview_import``) and the CSV
    preview path so both produce identical response shapes and apply the same
    duplicate-detection logic.
    """
    masked_account = (
        f"****{account_number[-4:]}" if len(account_number) >= 4 else account_number
    )
    trades: list[dict] = []
    duplicates = 0
    for mapped in mapped_trades:
        dup = is_duplicate(
            db,
            mapped["ticker"],
            mapped["strike"],
            mapped["expiration"],
            mapped["trade_type"],
            mapped["opened_at"],
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


def execute_mapped_import(
    db: Session,
    mapped_trades: list[dict],
) -> dict:
    """Persist a list of pre-mapped trade dicts to the journal.

    Inserts trades onto an existing open Position for the ticker, or creates a
    new Position with neutral initial state (``shares=0``, ``broker_cost_basis=0``)
    that the recomputer will overwrite. New positions are seeded with a
    ``"csp"`` placeholder strategy; the recomputer overwrites that with the
    correct derived label (csp / cc / wheel / holding) before this function
    returns — see issue #131 for the truth table.

    After all trades are inserted, the finalizer calls
    :func:`app.services.positions.recompute_position_state` once per touched
    ticker to derive ``status`` / ``shares`` / ``broker_cost_basis`` /
    ``closed_at`` / ``strategy`` from the trade ledger.

    Shared between the Schwab API import path and the CSV upload import path.
    """
    imported = 0
    skipped = 0
    positions_created = 0
    touched_position_ids: list[str] = []
    seen_position_ids: set[str] = set()

    for mapped in mapped_trades:
        if is_duplicate(
            db,
            mapped["ticker"],
            mapped["strike"],
            mapped["expiration"],
            mapped["trade_type"],
            mapped["opened_at"],
        ):
            skipped += 1
            continue

        position = (
            db.query(Position)
            .filter(Position.ticker == mapped["ticker"], Position.status == "open")
            .order_by(Position.opened_at.desc())
            .first()
        )
        if position is None:
            # Neutral initial state — the recomputer below overwrites these
            # from the trade ledger once the batch finishes inserting.
            # ``strategy`` is seeded with the journal-service default in
            # ``create_position`` and recomputed in the finalizer.
            pos_data = PositionCreate(
                ticker=mapped["ticker"],
                shares=1,  # ge=1 schema constraint; real value comes from recomputer
                broker_cost_basis=0.0,
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

        if position.id not in seen_position_ids:
            seen_position_ids.add(position.id)
            touched_position_ids.append(position.id)

    # Finalizer: recompute lifecycle state for every touched position so the
    # journal reflects the trade ledger we just appended (closed cycles flip
    # to status="closed", assignments set broker_cost_basis = strike * shares,
    # double assignments aggregate share counts, etc.). See
    # :mod:`app.services.positions` for the full state machine.
    for pos_id in touched_position_ids:
        recompute_position_state(db, pos_id)

    return {
        "imported": imported,
        "skipped_duplicates": skipped,
        "positions_created": positions_created,
    }


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

    transactions = client.get_transactions(account_hash, start_date, end_date)
    mapped_trades = [m for m in (map_schwab_transaction(t) for t in transactions) if m]
    return build_preview(db, mapped_trades, account_number=account_number)


def execute_import(db: Session, start_date: str, end_date: str) -> dict:
    """Import Schwab transactions into the journal.

    Creates positions as needed and logs trades. Strategy labels are derived
    by the recomputer (issue #131) — there is no per-import strategy override.
    """
    client = SchwabClient()
    account_numbers = client.get_account_numbers()

    if not account_numbers:
        return {"imported": 0, "skipped_duplicates": 0, "positions_created": 0}

    account = account_numbers[0]
    account_hash = account.get("hashValue", "")
    transactions = client.get_transactions(account_hash, start_date, end_date)
    mapped_trades = [m for m in (map_schwab_transaction(t) for t in transactions) if m]
    return execute_mapped_import(db, mapped_trades)
