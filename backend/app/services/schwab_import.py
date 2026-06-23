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


# Equity / dividend trade types. These rows carry ``strike=None`` and
# ``expiration=None``, so the option dedup 5-tuple (ticker, strike, expiration,
# trade_type, opened_at) collapses to (ticker, trade_type, opened_at) for them —
# two same-day buys at different prices or quantities would dedup to one. The
# equity dedup key is therefore widened with a discriminator (issue #388).
_EQUITY_TRADE_TYPES = frozenset({"buy_stock", "sell_stock", "dividend"})


def is_duplicate(
    db: Session,
    ticker: str,
    strike: float | None,
    expiration: str | None,
    trade_type: str,
    opened_at: str,
    unit_amount: float | None = None,
    quantity: int | None = None,
    close_reason: str | None = None,
) -> bool:
    """Check if a matching trade already exists in the journal.

    Option rows dedup on the historical 5-tuple ``(ticker, strike, expiration,
    trade_type, opened_at)`` — byte-for-byte unchanged.

    Equity / dividend rows (``trade_type`` in :data:`_EQUITY_TRADE_TYPES`) carry
    ``strike=None`` / ``expiration=None``, so that 5-tuple collapses to
    ``(ticker, trade_type, opened_at)`` and would wrongly merge two same-day
    buys at different prices/quantities, or a same-day cash + qualified dividend.
    For those rows the key is widened with a V1-freeze discriminator —
    ``unit_amount + quantity + close_reason`` — because no Schwab transaction-id
    column exists on the ``trades`` table to dedup on (PRD #384, confirmed).
    NULL columns are matched with ``IS NULL`` (``.is_(None)``) rather than
    ``== None`` so SQLAlchemy emits the correct predicate.
    """
    query = (
        db.query(Trade)
        .join(Position, Trade.position_id == Position.id)
        .filter(
            Position.ticker == ticker,
            Trade.trade_type == trade_type,
            Trade.opened_at == opened_at,
        )
    )

    # Strike / expiration: ``.is_(None)`` when absent (equity rows), else ``==``.
    query = query.filter(
        Trade.strike.is_(None) if strike is None else Trade.strike == strike
    )
    query = query.filter(
        Trade.expiration.is_(None)
        if expiration is None
        else Trade.expiration == expiration
    )

    if trade_type in _EQUITY_TRADE_TYPES:
        # Equity discriminator: keeps AC6a (different price), AC6b (different
        # quantity), and AC6c (same-day cash vs qualified dividend, which differ
        # only by close_reason) from collapsing.
        query = query.filter(
            Trade.unit_amount.is_(None)
            if unit_amount is None
            else Trade.unit_amount == unit_amount
        )
        query = query.filter(
            Trade.quantity.is_(None)
            if quantity is None
            else Trade.quantity == quantity
        )
        query = query.filter(
            Trade.close_reason.is_(None)
            if close_reason is None
            else Trade.close_reason == close_reason
        )

    return query.first() is not None


def _detect_unmatched_sells(db: Session, mapped_trades: list[dict]) -> set[int]:
    """Return the indices of ``mapped_trades`` that are equity sells with no
    shares to draw on.

    Replays the same per-ticker running-share simulation
    :func:`execute_mapped_import` uses, so the preview and the execute path
    AGREE on exactly which ``sell_stock`` rows will be skipped as unmatched
    (AC3c / PRD #384 Q2). Seeds each ticker from its existing open position so a
    sell can legitimately draw on already-owned/assigned shares; buys earlier in
    the same import grow the balance; duplicate rows are already reflected in the
    existing share count and do not move the balance.

    The simulation walks rows in **chronological order** (by ``opened_at``), not
    file order: Schwab CSV exports are often newest-first, so a sell can be
    listed *above* the buy that covers it. Walking by date prevents falsely
    flagging such a sell as unmatched. Returned indices are into the ORIGINAL
    ``mapped_trades`` list so callers can match by position. (The recomputer
    re-sorts the ledger on replay regardless, so insertion order is unaffected.)
    """
    running: dict[str, int] = {}
    unmatched: set[int] = set()

    def _seed(ticker: str) -> int:
        if ticker not in running:
            existing = (
                db.query(Position)
                .filter(Position.ticker == ticker, Position.status == "open")
                .order_by(Position.opened_at.desc())
                .first()
            )
            running[ticker] = existing.shares if existing else 0
        return running[ticker]

    # Stable chronological order; ties keep original file order (ascending index).
    chronological = sorted(
        range(len(mapped_trades)),
        key=lambda i: mapped_trades[i].get("opened_at") or "",
    )
    for idx in chronological:
        mapped = mapped_trades[idx]
        ticker = mapped["ticker"]
        trade_type = mapped["trade_type"]
        quantity = mapped.get("quantity") or 0
        if is_duplicate(
            db,
            ticker,
            mapped.get("strike"),
            mapped.get("expiration"),
            trade_type,
            mapped["opened_at"],
            unit_amount=mapped.get("unit_amount"),
            quantity=mapped.get("quantity"),
            close_reason=mapped.get("close_reason"),
        ):
            continue
        if trade_type == "buy_stock":
            running[ticker] = _seed(ticker) + quantity
        elif trade_type == "sell_stock":
            available = _seed(ticker)
            if quantity > available:
                unmatched.add(idx)
                continue
            running[ticker] = available - quantity
    return unmatched


def build_preview(
    db: Session,
    mapped_trades: list[dict],
    account_number: str = "",
) -> dict:
    """Build a preview response from a list of pre-mapped trade dicts.

    Shared between the API preview path (``preview_import``) and the CSV
    preview path so both produce identical response shapes and apply the same
    duplicate-detection logic. Equity sells that cannot be covered are flagged
    ``is_unmatched`` (and excluded from ``new_count``) so the user sees, before
    confirming, that they will be skipped — matching what
    :func:`execute_mapped_import` actually does (AC3c / PRD #384 Q2).
    """
    masked_account = (
        f"****{account_number[-4:]}" if len(account_number) >= 4 else account_number
    )
    unmatched_indices = _detect_unmatched_sells(db, mapped_trades)
    trades: list[dict] = []
    duplicates = 0
    unmatched = 0
    for idx, mapped in enumerate(mapped_trades):
        dup = is_duplicate(
            db,
            mapped["ticker"],
            mapped.get("strike"),
            mapped.get("expiration"),
            mapped["trade_type"],
            mapped["opened_at"],
            unit_amount=mapped.get("unit_amount"),
            quantity=mapped.get("quantity"),
            close_reason=mapped.get("close_reason"),
        )
        is_unmatched = idx in unmatched_indices
        if dup:
            duplicates += 1
        elif is_unmatched:
            unmatched += 1
        trades.append({**mapped, "is_duplicate": dup, "is_unmatched": is_unmatched})

    return {
        "account_number": masked_account,
        "trades": trades,
        "total": len(trades),
        "duplicates": duplicates,
        "unmatched": unmatched,
        "new_count": len(trades) - duplicates - unmatched,
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

    Equity sells that have no shares to draw on (the running balance of existing
    open-position shares plus buys earlier in the same import cannot cover them)
    are skipped at import time rather than inserted (issue #388 / PRD #384 AC3c).
    This is the user-visible half of the recomputer's defensive
    ``shares_sold > shares`` guard: the skipped rows are returned in
    ``skipped_unmatched`` so the UI can surface the warning.

    Shared between the Schwab API import path and the CSV upload import path.
    """
    imported = 0
    skipped = 0
    positions_created = 0
    touched_position_ids: list[str] = []
    seen_position_ids: set[str] = set()
    skipped_unmatched: list[dict] = []

    # Unmatched-sell pre-check (AC3c): equity sells with no shares to draw on
    # are skipped and recorded, never inserted (prevents negative shares at the
    # user-visible layer). Computed once here from the SAME simulation
    # ``build_preview`` uses, so the preview's "will skip" flag and what we
    # actually skip can never drift.
    unmatched_indices = _detect_unmatched_sells(db, mapped_trades)

    for idx, mapped in enumerate(mapped_trades):
        ticker = mapped["ticker"]
        trade_type = mapped["trade_type"]

        if is_duplicate(
            db,
            ticker,
            mapped.get("strike"),
            mapped.get("expiration"),
            trade_type,
            mapped["opened_at"],
            unit_amount=mapped.get("unit_amount"),
            quantity=mapped.get("quantity"),
            close_reason=mapped.get("close_reason"),
        ):
            skipped += 1
            continue

        if idx in unmatched_indices:
            logger.warning(
                "Skipping unmatched equity sell with no shares to draw on",
                extra={
                    "event": "equity_import.unmatched_sell",
                    "outcome": "no_data",
                    "ticker": ticker,
                },
            )
            skipped_unmatched.append(
                {
                    "ticker": ticker,
                    "opened_at": mapped["opened_at"],
                    "quantity": mapped.get("quantity") or 0,
                }
            )
            continue

        position = (
            db.query(Position)
            .filter(Position.ticker == ticker, Position.status == "open")
            .order_by(Position.opened_at.desc())
            .first()
        )
        if position is None:
            # Neutral initial state — the recomputer below overwrites these
            # from the trade ledger once the batch finishes inserting.
            # ``strategy`` is seeded with the journal-service default in
            # ``create_position`` and recomputed in the finalizer.
            pos_data = PositionCreate(
                ticker=ticker,
                shares=1,  # ge=1 schema constraint; real value comes from recomputer
                broker_cost_basis=0.0,
                opened_at=mapped["opened_at"],
            )
            pos_result = create_position(db, pos_data)
            position = db.query(Position).filter(Position.id == pos_result["id"]).first()
            positions_created += 1

        trade_data = TradeCreate(
            position_id=position.id,
            trade_type=trade_type,
            strike=mapped.get("strike"),
            expiration=mapped.get("expiration"),
            premium=mapped["premium"],
            # Gap #2 (issue #388): equity per-unit money and the dividend
            # sub-type were previously dropped on import. Plumb them through so
            # buy_stock/sell_stock round-trip ``unit_amount`` and dividend rows
            # round-trip ``close_reason`` (the raw Schwab sub-type).
            unit_amount=mapped.get("unit_amount"),
            fees=mapped["fees"],
            quantity=mapped["quantity"],
            opened_at=mapped["opened_at"],
            close_reason=mapped.get("close_reason"),
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
        "skipped_unmatched": skipped_unmatched,
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
