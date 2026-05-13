"""Parse Schwab transaction CSV exports into journal-ready trade dicts.

Schwab.com's *Activity & Statements -> Transactions -> Export* feature produces a
CSV file with the following columns (any order, header row is required):

    Date, Action, Symbol, Description, Quantity, Price, Fees & Comm, Amount

Example option rows (taken from real Schwab exports):

    "03/27/2026", "Sell to Open", "F 03/27/2026 13.50 P", ...
    "03/20/2026", "Buy to Close", "SOFI 03/20/2026 31.00 C", ...
    "03/21/2026", "Assigned",     "AAPL 03/21/2026 150.00 P", ...

The exact symbol layout varies by account/export — older exports may use the
canonical OCC format (``AAPL240315P00185000``) instead of the human-readable
``TICKER MM/DD/YYYY STRIKE P|C`` form. Both shapes are handled here.

This module produces dicts in the **same shape** as
:func:`app.services.schwab_import.map_schwab_transaction`, so the existing
preview/execute import pipeline can consume them unchanged.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime

from app.services.schwab_import import _INSTRUCTION_MAP

logger = logging.getLogger(__name__)


# Map Schwab CSV "Action" column values to the (instruction, putCall) pair the
# rest of the import pipeline uses. The putCall component is filled in from the
# parsed Symbol; the keys below are case-insensitive and always trimmed.
#
# ``Expired`` is intentionally absent here — :func:`_map_csv_row` short-circuits
# the literal action ``"expired"`` to ``trade_type="expired"`` regardless of
# putCall. That fixes a Schwab CSV bug where an expired-worthless put would
# otherwise be mapped to ``RECEIVE_DELIVER`` → ``assignment``, incorrectly
# moving shares and broker basis on the position. See issue #127.
_ACTION_TO_INSTRUCTION: dict[str, str] = {
    "sell to open": "SELL_TO_OPEN",
    "buy to close": "BUY_TO_CLOSE",
    "assigned": "RECEIVE_DELIVER",
    # Schwab uses different phrasing for called-away exercises depending on
    # account type. Both map to RECEIVE_DELIVER on the call side.
    "exercised": "RECEIVE_DELIVER",
}

# CSV ``Action`` values that should bypass the (instruction, putCall) lookup
# because their journal trade_type is determined by the Action alone, not by
# the option side.
_ACTION_DIRECT_TRADE_TYPE: dict[str, str] = {
    "expired": "expired",
}


# Human-readable option symbol: "F 03/27/2026 13.50 P" / "AAPL 03/21/2026 150.00 P"
_HUMAN_SYMBOL_RE = re.compile(
    r"^\s*(?P<ticker>[A-Z][A-Z0-9.\-]{0,9})\s+"
    r"(?P<expiration>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<strike>\d+(?:\.\d+)?)\s+"
    r"(?P<putcall>[PCpc])\s*$"
)

# Canonical OCC option symbol: "AAPL  240315C00185000"
# Ticker (1-6 chars) + YYMMDD + C/P + strike-price * 1000 padded to 8 digits.
_OCC_SYMBOL_RE = re.compile(
    r"^\s*(?P<ticker>[A-Z][A-Z0-9.\-]{0,9})\s*"
    r"(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})"
    r"(?P<putcall>[CP])"
    r"(?P<strike>\d{8})\s*$"
)


def parse_schwab_csv(file_bytes: bytes) -> list[dict]:
    """Parse a Schwab transaction CSV export into journal trade dicts.

    Non-options rows (stock buys/sells, dividends, ACH transfers, etc.) and
    rows whose Action does not map to a known options instruction are silently
    skipped. Malformed rows that fail to parse are also skipped — the parser
    never raises on a single bad row, so a partially valid file still yields
    the rows that did parse.

    Args:
        file_bytes: Raw CSV file content. UTF-8 with BOM is tolerated; other
            encodings are best-effort decoded as latin-1 fallback.

    Returns:
        A list of dicts matching the shape of
        :func:`app.services.schwab_import.map_schwab_transaction`:

        ``ticker``, ``trade_type``, ``strike``, ``expiration`` (YYYY-MM-DD),
        ``premium`` (per-share, signed), ``fees``, ``quantity``, ``opened_at``.
    """
    text = _decode_csv_bytes(file_bytes)
    if not text.strip():
        return []

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []

    # Build a case-insensitive header lookup so subtle variations like
    # "Fees & Comm" vs "Fees & Comm." don't break parsing.
    header_map = {(h or "").strip().lower(): h for h in reader.fieldnames}
    required = {"date", "action", "symbol", "quantity", "amount"}
    if not required.issubset(header_map.keys()):
        logger.info("Schwab CSV missing required columns; got %s", reader.fieldnames)
        return []

    trades: list[dict] = []
    for raw_row in reader:
        try:
            mapped = _map_csv_row(raw_row, header_map)
        except Exception:  # noqa: BLE001 — defensive: never crash on a single row
            logger.debug("Skipping malformed CSV row", exc_info=True)
            continue
        if mapped is not None:
            trades.append(mapped)
    return trades


def _decode_csv_bytes(file_bytes: bytes) -> str:
    """Decode CSV bytes to text, tolerating BOM and non-UTF-8 inputs."""
    try:
        return file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return file_bytes.decode("latin-1", errors="replace")


def _map_csv_row(raw_row: dict, header_map: dict[str, str]) -> dict | None:
    """Map a single CSV row dict to a journal trade dict, or None to skip.

    Equity-leg rows that pair with an option assignment (e.g. ``Action="Buy"``
    on the underlying ticker) are silently skipped because their Action does
    not appear in :data:`_ACTION_TO_INSTRUCTION` / :data:`_ACTION_DIRECT_TRADE_TYPE`.
    Broker cost basis is therefore derived from the option's strike at the
    finalizer (see :mod:`app.services.positions`), not parsed from the equity
    row.
    """
    action_raw = (raw_row.get(header_map.get("action", ""), "") or "").strip().lower()

    # Action values whose journal trade_type is determined by the Action alone
    # (currently just "Expired"). These bypass the (instruction, putCall) lookup
    # because, for example, an expired-worthless put must NOT map to assignment.
    direct_trade_type = _ACTION_DIRECT_TRADE_TYPE.get(action_raw)
    instruction = _ACTION_TO_INSTRUCTION.get(action_raw) if direct_trade_type is None else None
    if direct_trade_type is None and instruction is None:
        return None

    symbol = (raw_row.get(header_map.get("symbol", ""), "") or "").strip()
    parsed = _parse_option_symbol(symbol)
    if parsed is None:
        return None

    ticker, expiration, strike, put_call = parsed
    if direct_trade_type is not None:
        trade_type: str | None = direct_trade_type
    else:
        trade_type = _INSTRUCTION_MAP.get((instruction, put_call))
    if trade_type is None:
        return None

    quantity = _parse_int(raw_row.get(header_map.get("quantity", ""), ""))
    if quantity is None or quantity <= 0:
        return None

    amount = _parse_float(raw_row.get(header_map.get("amount", ""), ""))
    fees = _parse_float(raw_row.get(header_map.get("fees & comm", ""), "")) or 0.0
    price = _parse_float(raw_row.get(header_map.get("price", ""), ""))

    if amount is None:
        amount = 0.0

    # Premium per share: prefer the per-share ``Price`` column when present —
    # Schwab's CSV exposes the gross premium there directly, which sidesteps
    # the fee-arithmetic that ``Amount`` is already net of. Fall back to
    # gross-up math (``abs(Amount) + fees``) when ``Price`` is missing or
    # unparseable — that path applies to assignment / expired rows that have
    # no Price column populated, where the fallback produces 0.0 from a 0.0
    # amount + 0.0 fees anyway. See issue #184.
    if price is not None and price > 0 and quantity > 0:
        premium_per_share = abs(price)
    elif quantity > 0:
        premium_per_share = (abs(amount) + abs(fees)) / (quantity * 100)
    else:
        premium_per_share = 0.0
    if instruction == "BUY_TO_CLOSE":
        premium_per_share = -premium_per_share

    opened_at = _normalize_csv_date(
        raw_row.get(header_map.get("date", ""), "")
    )
    if not opened_at:
        return None

    return {
        "ticker": ticker,
        "trade_type": trade_type,
        "strike": float(strike),
        "expiration": expiration,
        "premium": round(premium_per_share, 4),
        "fees": round(abs(fees), 2),
        "quantity": int(quantity),
        "opened_at": opened_at,
    }


def _parse_option_symbol(symbol: str) -> tuple[str, str, float, str] | None:
    """Parse a Schwab option symbol into (ticker, expiration, strike, putCall).

    Returns None if the symbol is empty, malformed, or not an option (e.g.
    plain equity tickers like "AAPL").
    """
    if not symbol:
        return None

    human = _HUMAN_SYMBOL_RE.match(symbol)
    if human:
        try:
            exp = datetime.strptime(human.group("expiration"), "%m/%d/%Y").strftime("%Y-%m-%d")
        except ValueError:
            return None
        return (
            human.group("ticker").upper(),
            exp,
            float(human.group("strike")),
            "PUT" if human.group("putcall").upper() == "P" else "CALL",
        )

    occ = _OCC_SYMBOL_RE.match(symbol)
    if occ:
        # OCC symbols encode year as 2 digits; we hardcode the 21st-century
        # prefix. Schwab journals containing options expiring in 2100+ would
        # need revisiting then.
        try:
            exp = datetime.strptime(
                f"20{occ.group('yy')}-{occ.group('mm')}-{occ.group('dd')}",
                "%Y-%m-%d",
            ).strftime("%Y-%m-%d")
        except ValueError:
            return None
        strike = int(occ.group("strike")) / 1000.0
        return (
            occ.group("ticker").upper(),
            exp,
            strike,
            "PUT" if occ.group("putcall") == "P" else "CALL",
        )

    return None


def _normalize_csv_date(date_str: str) -> str:
    """Normalize a Schwab CSV Date cell to YYYY-MM-DD.

    Schwab exports use ``MM/DD/YYYY``. Some rows include an action suffix in
    parentheses (e.g. ``"03/01/2026 as of 02/28/2026"``); we use the first
    parseable date in the cell.
    """
    if not date_str:
        return ""
    candidate = date_str.strip().split(" as of ")[0].strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(candidate, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _parse_int(value: str | None) -> int | None:
    """Parse an integer from a Schwab CSV cell. Returns None on failure."""
    if value is None:
        return None
    cleaned = str(value).replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def _parse_float(value: str | None) -> float | None:
    """Parse a float from a Schwab CSV cell, stripping ``$``/``,`` and parens.

    Schwab uses parentheses for negatives in some exports (``"($1,234.56)"``).
    Returns None on failure.
    """
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    negative = False
    if cleaned.startswith("(") and cleaned.endswith(")"):
        negative = True
        cleaned = cleaned[1:-1]
    cleaned = cleaned.replace("$", "").replace(",", "").strip()
    if not cleaned or cleaned == "-":
        return None
    try:
        result = float(cleaned)
    except ValueError:
        return None
    return -result if negative else result
