"""Pure helpers for dashboard option-leg derivations.

These functions are intentionally side-effect-free so they can be unit tested
without touching the database or any external service. They power the
"Open option legs" and "Upcoming expirations" cards on the dashboard.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Literal

from app.services.rule_monitor import evaluate_leg_rules
from app.utils.parsing import to_float

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
AssignmentRisk = Literal["high", "watch", "low"]
SuggestedAction = Literal["roll", "close", "hold", "manage"]
ProfitTargetState = Literal["captured_50", "in_progress", "underwater", "unknown"]

# Maps the four existing decision-tag buckets to the V0.5 suggested-action
# vocabulary. Spec §14.5 locks this mapping; "close" is intentionally absent
# because emitting it as the styled ACTION verdict is still design-gated
# (issue #240). The 50%-profit signal itself is now live — see
# build_profit_target_status — but the verdict column that consumes it is not.
_DECISION_TAG_TO_SUGGESTED_ACTION: dict[DecisionTag, SuggestedAction] = {
    "roll-or-assign": "roll",
    "manage": "manage",
    "watch": "hold",
    "hold": "hold",
}


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


def compute_assignment_risk(
    dte: int,
    moneyness_state: str | None,
) -> AssignmentRisk:
    """Classify the short option's assignment risk into three buckets.

    Per spec §14.5:
    - ``dte <= 7 AND ITM``  → ``"high"`` (acute risk; review today)
    - ``dte <= 14 AND ITM`` → ``"watch"`` (watch the next 1–2 sessions)
    - otherwise             → ``"low"``

    Non-ITM legs and legs with unknown moneyness (no live price) collapse to
    ``"low"`` so the dashboard never flags a risk it cannot justify.
    """
    if moneyness_state != "ITM":
        return "low"
    if dte <= 7:
        return "high"
    if dte <= 14:
        return "watch"
    return "low"


def compute_suggested_action(decision_tag: DecisionTag) -> SuggestedAction:
    """Map an existing decision tag to a V0.5 suggested-action label.

    Per spec §14.5 the V0.5 vocabulary is ``"roll" | "hold" | "manage"``.
    The ``"close"`` value is intentionally never emitted here because the
    styled ACTION verdict that would surface a 50%-profit-target hit is
    still design-gated (issue #240).
    """
    return _DECISION_TAG_TO_SUGGESTED_ACTION.get(decision_tag, "hold")


def build_profit_target_status(
    premium: float | None,
    current_mid: float | None,
    dte: int = 9999,
    profit_review_pct: float = 50.0,
) -> dict:
    """Return the per-leg profit-target status payload (the ``% CAPT`` signal).

    Computes ``captured_pct = (premium - current_mid) / premium`` — the
    fraction of the credit a short option seller has already captured by
    the option decaying toward zero. The ratio is per-share and therefore
    quantity-invariant, so ``quantity`` is deliberately not a parameter.

    Args:
        premium: The credit received per share when the leg was opened
            (``Trade.premium``). Must be a positive credit to be meaningful.
        current_mid: The current option mid price per share, from a live
            Schwab option chain. ``None`` when no live mark is available.
        dte: Days to expiration. An expired leg (``dte < 0``) yields
            ``unknown`` — there is no live management decision once expired.
        profit_review_pct: The user's profit-target threshold as a percent
            (``rules.management.profit_review_pct``, default 50).

    Returns:
        ``{"captured_pct": float | None, "state": ProfitTargetState}``.
        Degrades to ``{"captured_pct": None, "state": "unknown"}`` when an
        input is missing or non-credit so the dashboard never shows a
        signal it cannot justify.
    """
    if premium is None or current_mid is None or premium <= 0 or dte < 0:
        return {"captured_pct": None, "state": "unknown"}
    captured_pct = round((premium - current_mid) / premium, 4)
    if captured_pct >= profit_review_pct / 100:
        state: ProfitTargetState = "captured_50"
    elif captured_pct < 0:
        state = "underwater"
    else:
        state = "in_progress"
    return {"captured_pct": captured_pct, "state": state}


def build_option_mark_index(
    chains_by_ticker: dict[str, dict],
) -> dict[tuple, float]:
    """Flatten raw Schwab option-chain responses into a flat mid-price index.

    Schwab ``callExpDateMap`` / ``putExpDateMap`` are nested two levels deep:
    ``{exp_key: {strike_str: [contract, ...]}}`` where ``exp_key`` looks like
    ``"2026-06-26:38"`` (expiration date plus DTE). This helper flattens them
    into ``{(ticker, type, round(strike, 4), exp_date): mid}`` so a leg can be
    matched with a single dict lookup.

    The mid is ``contract["mark"]`` when present, otherwise ``(bid + ask) / 2``
    (mirrors :mod:`app.services.options_scanner`). Entries with a falsy mid are
    skipped — a leg with no usable mark degrades to ``unknown`` rather than a
    misleading 0.

    The function is tolerant of malformed nodes: a single bad contract,
    missing key, or non-dict entry is skipped and never aborts the index.
    """
    index: dict[tuple, float] = {}
    for ticker, chain in (chains_by_ticker or {}).items():
        if not isinstance(chain, dict):
            continue
        for option_type, map_key in (("call", "callExpDateMap"), ("put", "putExpDateMap")):
            exp_date_map = chain.get(map_key)
            if not isinstance(exp_date_map, dict):
                continue
            for exp_key, strikes_map in exp_date_map.items():
                if not isinstance(strikes_map, dict):
                    continue
                # exp_key is "YYYY-MM-DD:DTE"; the prefix is the expiration.
                exp_date = str(exp_key).split(":")[0][:10]
                for contracts in strikes_map.values():
                    if not contracts:
                        continue
                    contract = contracts[0]
                    if not isinstance(contract, dict):
                        continue
                    strike = to_float(contract.get("strikePrice"), None)
                    if strike is None:
                        continue
                    bid = to_float(contract.get("bid"))
                    ask = to_float(contract.get("ask"))
                    mid = to_float(contract.get("mark")) or round((bid + ask) / 2, 4)
                    if not mid:
                        continue
                    index[(ticker, option_type, round(strike, 4), exp_date)] = mid
    return index


def compute_earnings_in_window(
    ticker: str,
    dte: int,
    earnings_lookup,
    today: date | None = None,
) -> bool:
    """Determine whether a cached earnings date falls inside the leg's DTE window.

    ``earnings_lookup`` is a callable ``(ticker: str) -> str | None`` that
    must NEVER make a network call — typically
    :func:`app.services.alpha_vantage_client.get_cached_next_earnings_date`.

    ``today`` is injected so the rest of the dashboard pipeline can stay
    deterministic; when omitted it falls back to :func:`date.today`.

    Returns ``False`` when:
    - the lookup returns ``None`` (cache miss),
    - the cached date cannot be parsed,
    - the DTE is non-positive (the leg has already expired or expires today),
    - the cached earnings date falls outside ``[today, today + dte]``.

    The window is intentionally inclusive on both ends.
    """
    if dte <= 0:
        return False
    earnings_iso = earnings_lookup(ticker)
    if not earnings_iso:
        return False
    try:
        earnings_date = date.fromisoformat(str(earnings_iso)[:10])
    except (TypeError, ValueError):
        return False
    today_d = today or date.today()
    delta_days = (earnings_date - today_d).days
    return 0 <= delta_days <= dte


def derive_open_legs(
    positions: Iterable[dict],
    quotes_by_ticker: dict[str, float | None],
    today: date | None = None,
    earnings_lookup=None,
    option_marks: dict | None = None,
    profit_review_pct: float = 50.0,
    dte_review_days: int = 21,
    expiration_warning_days: int = 7,
) -> list[dict]:
    """Flatten open option legs across the given positions.

    A leg is "open" when it was an opening trade (`sell_put` / `sell_call`)
    AND its `closed_at` is None on the trade row. Each leg is enriched with
    DTE, moneyness, and the per-leg signal fields:
    ``profit_target_status`` (the ``% CAPT`` signal — a real ``captured_pct``
    when a live mark is available, else ``state="unknown"``),
    ``assignment_risk``, ``suggested_action``, ``earnings_in_window``, and the
    §R6 rule-monitor verdict layer (issue #240): ``verdict``,
    ``verdict_label``, ``reasoning``, and ``triggered_rules``.

    ``earnings_lookup`` is an optional callable used to populate
    ``earnings_in_window``. It MUST be cache-hit-only — defaults to a
    sentinel that returns ``None`` so the dashboard never blocks on
    Alpha Vantage in the request path.

    ``option_marks`` is the flat ``{(ticker, type, strike, exp): mid}`` index
    produced by :func:`build_option_mark_index`. It is optional — a missing
    index (or a leg absent from it) degrades that leg's ``profit_target_status``
    to ``state="unknown"``. ``profit_review_pct``, ``dte_review_days``, and
    ``expiration_warning_days`` are the user's ManagementTriggers §R6
    thresholds (``rules.management.*``).

    Returns a list ordered by (dte ASC, ticker ASC) — callers that need
    other orderings should re-sort.
    """
    today = today or date.today()
    if earnings_lookup is None:
        # Defensive default: cache miss-only sentinel. Never trigger network.
        earnings_lookup = lambda _ticker: None  # noqa: E731 — small inline default
    if option_marks is None:
        # Defensive default: no live marks → every leg's % CAPT is unknown.
        option_marks = {}
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
            moneyness_state = moneyness["state"] if moneyness else None
            decision_tag = compute_decision_tag(dte, moneyness_state)
            # Match this leg against the live option-chain mid index. A key
            # absent from the index → current_mid=None → % CAPT "unknown".
            mark_key = (
                ticker,
                option_type,
                round(strike, 4),
                str(trade["expiration"])[:10],
            )
            current_mid = option_marks.get(mark_key)
            profit_target_status = build_profit_target_status(
                premium=trade.get("premium"),
                current_mid=current_mid,
                dte=dte,
                profit_review_pct=profit_review_pct,
            )
            assignment_risk = compute_assignment_risk(dte, moneyness_state)
            # §R6 rule-monitor verdict layer (issue #240). Pure — derives the
            # verdict from values already on this leg; no I/O, no DB.
            verdict, verdict_label, reasoning, triggered_rules = evaluate_leg_rules(
                dte=dte,
                moneyness_state=moneyness_state,
                profit_target_status=profit_target_status,
                premium=trade.get("premium"),
                current_mid=current_mid,
                profit_review_pct=profit_review_pct,
                dte_review_days=dte_review_days,
                expiration_warning_days=expiration_warning_days,
                assignment_risk=assignment_risk,
            )
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
                    "premium": trade.get("premium"),
                    "quantity": int(trade.get("quantity") or 1),
                    # Raw matched option mid (None when no live mark) — consumed
                    # by the BTC detail endpoint (issue #244). The dashboard
                    # ignores this key, so it cannot regress #240.
                    "current_mid": current_mid,
                    "profit_target_status": profit_target_status,
                    "assignment_risk": assignment_risk,
                    "suggested_action": compute_suggested_action(decision_tag),
                    "earnings_in_window": compute_earnings_in_window(
                        ticker, dte, earnings_lookup, today=today
                    ),
                    "verdict": verdict,
                    "verdict_label": verdict_label,
                    "reasoning": reasoning,
                    "triggered_rules": triggered_rules,
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
