"""Pure helpers for dashboard option-leg derivations.

These functions are intentionally side-effect-free so they can be unit tested
without touching the database or any external service. They power the
"Open option legs" and "Upcoming expirations" cards on the dashboard.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Literal

# A "leg-opening" trade type implies the leg is currently open *unless* the
# trade row has a non-null closed_at. Exit trades (buy-to-close, assignment,
# called_away) are not legs themselves — they close prior open legs.
LEG_OPENING_TRADE_TYPES: frozenset[str] = frozenset({"sell_put", "sell_call"})

# Maps an opening trade_type to the option_type carried on the leg.
TRADE_TYPE_TO_OPTION_TYPE: dict[str, Literal["put", "call"]] = {
    "sell_put": "put",
    "sell_call": "call",
}

MoneynessState = Literal["ITM", "ATM", "OTM"]
DecisionTag = Literal["roll-or-assign", "manage", "watch", "hold"]


def compute_dte(expiration_iso: str, today: date | None = None) -> int:
    """Return whole calendar days from `today` to the option's expiration.

    Negative values mean the option has already expired. The expiration is
    parsed leniently — accepts `YYYY-MM-DD` or any ISO date prefix.
    Returns 9999 if parsing fails so the row sorts to the bottom and is not
    flagged for action.
    """
    today = today or date.today()
    try:
        # Accept "2026-05-08" or "2026-05-08T..." (Schwab payloads sometimes
        # include time on expiration timestamps).
        exp = date.fromisoformat(expiration_iso[:10])
    except (TypeError, ValueError):
        return 9999
    return (exp - today).days


def compute_moneyness(
    option_type: Literal["put", "call"],
    strike: float,
    current_price: float | None,
) -> dict | None:
    """Return moneyness state, signed-distance fraction, and dollar distance.

    For the *option seller* perspective (the only one this app supports):
    - A short put is ITM when `current_price < strike` (assignment risk).
    - A short call is ITM when `current_price > strike` (called-away risk).

    `distance_pct` and `distance_dollars` are absolute (unsigned) — the
    frontend formats the leading "ITM by $X.XX" / "OTM 4.1%" label using
    the `state` field. Strikes equal to price are treated as ATM.

    Returns None when no live price is available so the caller can render `—`.
    """
    if current_price is None:
        return None

    if option_type == "put":
        if current_price < strike:
            state: MoneynessState = "ITM"
        elif current_price == strike:
            state = "ATM"
        else:
            state = "OTM"
    else:  # call
        if current_price > strike:
            state = "ITM"
        elif current_price == strike:
            state = "ATM"
        else:
            state = "OTM"

    distance_dollars = abs(current_price - strike)
    distance_pct = distance_dollars / strike if strike else 0.0
    return {
        "state": state,
        "distance_pct": distance_pct,
        "distance_dollars": distance_dollars,
    }


def compute_decision_tag(
    dte: int,
    moneyness_state: str | None,
) -> DecisionTag:
    """Map (DTE, moneyness) to one of four action buckets.

    Heuristic per spec §5.3 / Q5:
    - dte <= 7 AND ITM       -> "roll-or-assign" (red, highest priority)
    - dte <= 7 AND not ITM   -> "manage"        (yellow)
    - dte <= 14 AND ITM      -> "watch"         (yellow)
    - everything else        -> "hold"          (neutral)

    ATM is treated as "not ITM" — the close call goes the safer way; the
    frontend can still surface the strike's proximity via the moneyness
    distance fields. When moneyness is unknown (no live price), we fall back
    to "hold" so the dashboard never recommends an action it can't justify.
    """
    if moneyness_state is None:
        return "hold"
    is_itm = moneyness_state == "ITM"
    if dte <= 7 and is_itm:
        return "roll-or-assign"
    if dte <= 7:
        return "manage"
    if dte <= 14 and is_itm:
        return "watch"
    return "hold"


def format_decision_reason(
    moneyness: dict | None,
    dte: int,
) -> str:
    """Build the human-readable single-line reason rendered under the leg.

    Examples: "ITM by $0.42", "OTM 4.1%", "3 DTE - awaiting price".
    """
    if moneyness is None:
        return f"{dte} DTE — awaiting price"
    state = moneyness["state"]
    if state == "ITM":
        return f"ITM by ${moneyness['distance_dollars']:.2f}"
    if state == "ATM":
        return "At the money"
    return f"OTM {moneyness['distance_pct'] * 100:.1f}%"


def derive_open_legs(
    positions: Iterable[dict],
    quotes_by_ticker: dict[str, float | None],
    today: date | None = None,
) -> list[dict]:
    """Flatten open option legs across the given positions.

    A leg is "open" when it was an opening trade (`sell_put` / `sell_call`)
    AND its `closed_at` is None on the trade row. Each leg is enriched with
    DTE and moneyness using `quotes_by_ticker` (per-ticker live price).

    Returns a list ordered by (dte ASC, ticker ASC) — callers that need
    other orderings should re-sort.
    """
    today = today or date.today()
    legs: list[dict] = []
    for position in positions:
        ticker = position["ticker"]
        position_id = position["id"]
        current_price = quotes_by_ticker.get(ticker)
        for trade in position.get("trades", []):
            if trade.get("trade_type") not in LEG_OPENING_TRADE_TYPES:
                continue
            if trade.get("closed_at"):
                continue
            option_type = TRADE_TYPE_TO_OPTION_TYPE[trade["trade_type"]]
            strike = float(trade["strike"])
            dte = compute_dte(trade["expiration"], today=today)
            moneyness = compute_moneyness(option_type, strike, current_price)
            legs.append(
                {
                    "id": trade["id"],
                    "ticker": ticker,
                    "type": option_type,
                    "strike": strike,
                    "expiration": trade["expiration"],
                    "dte": dte,
                    "moneyness": moneyness,
                    "position_id": position_id,
                }
            )
    legs.sort(key=lambda x: (x["dte"], x["ticker"]))
    return legs


def filter_upcoming(
    legs: list[dict],
    horizon_days: int = 14,
) -> list[dict]:
    """Return legs expiring within `horizon_days` (inclusive), enriched
    with `decision_tag` and `decision_reason`.

    Sort order: DTE ascending, ITM before OTM within the same DTE.
    """
    upcoming: list[dict] = []
    for leg in legs:
        if leg["dte"] > horizon_days:
            continue
        moneyness_state = leg["moneyness"]["state"] if leg["moneyness"] else None
        leg_with_tag = {
            **leg,
            "decision_tag": compute_decision_tag(leg["dte"], moneyness_state),
            "decision_reason": format_decision_reason(leg["moneyness"], leg["dte"]),
        }
        upcoming.append(leg_with_tag)
    # ITM before OTM within the same DTE — encode "ITM" as 0, others as 1.
    upcoming.sort(
        key=lambda x: (
            x["dte"],
            0 if (x["moneyness"] and x["moneyness"]["state"] == "ITM") else 1,
            x["ticker"],
        )
    )
    return upcoming


def parse_iso_to_utc(value: str | None) -> datetime | None:
    """Best-effort ISO timestamp parser used for activity sort keys.

    Returns a timezone-aware datetime in UTC, or None if parsing fails.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        from datetime import timezone

        dt = dt.replace(tzinfo=timezone.utc)
    return dt
