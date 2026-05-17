"""Humanize options-scanner rejection codes into plain-English sentences.

The :mod:`app.services.options_scanner` module emits machine-readable rejection
strings (``"fails_10pct_rule: strike 645.7% above basis, requires 10.0%"``) so
the raw stream is greppable in tests and logs. Phase A (#190) layers a human
sentence on top of each raw code so the scanner UI can speak plain English to
less-experienced wheel traders.

This module is a *pure* mapper. It does not import the scanner, the schemas,
or anything from FastAPI — it takes a list of raw reason strings plus a
context dict (cost basis, current price, min/max delta, etc.) and returns a
parallel list of human sentences. Callers are responsible for providing the
context. Unknown codes fall back to the raw string unchanged so the user is
never blind to a real signal.

See ``frontend/design-specs/scanner-education-v0.5.7.md`` §5.3 for the
canonical sentence templates.
"""

from __future__ import annotations

import re
from typing import Optional, TypedDict

# Regex patterns are intentionally tolerant: they grab the floating-point or
# integer values out of the raw f-string output produced by
# ``OptionScanner._check_rejection`` and the inline ``return_*`` blocks in
# ``OptionScanner.scan``. If a pattern fails to match we fall back to the raw
# string — never crash.
_FAILS_10PCT_RE = re.compile(
    r"^fails_10pct_rule:\s*strike\s*(?P<pct>-?\d+(?:\.\d+)?)%\s*above basis,\s*"
    r"requires\s*(?P<min>-?\d+(?:\.\d+)?)%\s*$"
)
_ITM_PUT_RE = re.compile(
    r"^itm_put:\s*strike\s*\$(?P<strike>-?\d+(?:\.\d+)?)\s*>\s*"
    r"price\s*\$(?P<price>-?\d+(?:\.\d+)?)\s*$"
)
_DELTA_OUT_OF_RANGE_RE = re.compile(
    r"^delta_out_of_range:\s*\|(?P<delta>-?\d+(?:\.\d+)?)\|\s*not in\s*"
    r"\[(?P<min>-?\d+(?:\.\d+)?),\s*(?P<max>-?\d+(?:\.\d+)?)\]\s*$"
)
_LOW_OI_RE = re.compile(
    r"^low_open_interest:\s*(?P<oi>-?\d+)\s*<\s*(?P<min>-?\d+)\s*$"
)
_RETURN_BELOW_RE = re.compile(
    r"^return_below_target:\s*(?P<pct>-?\d+(?:\.\d+)?)%\s*<\s*"
    r"(?P<min>-?\d+(?:\.\d+)?)%\s*$"
)
_RETURN_ABOVE_RE = re.compile(
    r"^return_above_cap:\s*(?P<pct>-?\d+(?:\.\d+)?)%\s*>\s*"
    r"(?P<max>-?\d+(?:\.\d+)?)%\s*$"
)
_BELOW_COST_BASIS_RE = re.compile(
    r"^below_cost_basis:\s*strike\s*\$(?P<strike>-?\d+(?:\.\d+)?)\s*<\s*"
    r"floor\s*\$(?P<floor>-?\d+(?:\.\d+)?)\s*$"
)
_WIDE_SPREAD_RE = re.compile(
    r"^wide_bid_ask_spread:\s*(?P<pct>-?\d+(?:\.\d+)?)%\s*>\s*"
    r"(?P<max>-?\d+(?:\.\d+)?)%\s*$"
)
_IV_RANK_BELOW_RE = re.compile(
    r"^iv_rank_below_floor:\s*(?P<rank>-?\d+(?:\.\d+)?)\s*<\s*"
    r"(?P<min>-?\d+(?:\.\d+)?)\s*$"
)


class HumanizeContext(TypedDict, total=False):
    """Optional context passed into :func:`humanize_reasons`.

    Each field is optional — when a parameter is missing from the raw code
    string AND from the context, the sentence falls back to a value taken from
    the raw text. Templates never crash on missing context.
    """

    cost_basis: Optional[float]
    current_price: Optional[float]
    min_call_distance_pct: float
    min_delta: float
    max_delta: float
    min_return_pct: float
    max_return_pct: Optional[float]


def humanize_reasons(
    raw_reasons: list[str],
    context: Optional[HumanizeContext] = None,
) -> list[str]:
    """Convert a list of raw rejection strings into a list of human sentences.

    The output list always has the same length as ``raw_reasons`` and the
    order is preserved. Unknown codes pass through unchanged so a stale UI
    code path still sees *something* informative.

    Args:
        raw_reasons: The ``rejection_reasons`` list off a ``RejectedStrike``.
        context: Optional dict with extra context (cost basis, current price,
            scanner thresholds). Used to enrich sentences when the raw string
            does not embed every parameter (e.g. ``cost_basis`` is not in the
            raw ``fails_10pct_rule`` string but is needed for ``"above your
            $13.26 basis"``).

    Returns:
        A new list of plain-English sentences, one per raw reason.
    """
    ctx: HumanizeContext = context or {}
    return [_humanize_one(raw, ctx) for raw in raw_reasons]


def _humanize_one(raw: str, ctx: HumanizeContext) -> str:
    """Dispatch a single raw reason to its template, or return raw unchanged."""
    raw = raw.strip()

    if raw.startswith("fails_10pct_rule"):
        return _fmt_fails_10pct(raw, ctx)
    if raw.startswith("itm_put"):
        return _fmt_itm_put(raw, ctx)
    if raw.startswith("delta_out_of_range"):
        return _fmt_delta_out_of_range(raw, ctx)
    if raw.startswith("low_open_interest"):
        return _fmt_low_open_interest(raw, ctx)
    if raw == "zero_bid":
        return _fmt_zero_bid()
    if raw.startswith("return_below_target"):
        return _fmt_return_below_target(raw, ctx)
    if raw.startswith("return_above_cap"):
        return _fmt_return_above_cap(raw, ctx)
    if raw.startswith("below_cost_basis"):
        return _fmt_below_cost_basis(raw, ctx)
    if raw.startswith("wide_bid_ask_spread"):
        return _fmt_wide_bid_ask_spread(raw, ctx)
    if raw.startswith("iv_rank_below_floor"):
        return _fmt_iv_rank_below_floor(raw, ctx)

    # Unknown code — fall back so we never lose information.
    return raw


def _fmt_fails_10pct(raw: str, ctx: HumanizeContext) -> str:
    """Render ``fails_10pct_rule: strike X% above basis, requires Y%``."""
    match = _FAILS_10PCT_RE.match(raw)
    if not match:
        return raw
    pct = float(match.group("pct"))
    min_pct = float(match.group("min"))
    cost_basis = ctx.get("cost_basis")
    basis_clause = (
        f"your ${cost_basis:.2f} basis" if cost_basis is not None else "your cost basis"
    )
    return (
        f"Strike sits {pct:.1f}% above {basis_clause}, but the {min_pct:.1f}% "
        "rule requires at least that much room."
    )


def _fmt_itm_put(raw: str, ctx: HumanizeContext) -> str:
    """Render ``itm_put: strike $X > price $Y``."""
    match = _ITM_PUT_RE.match(raw)
    if not match:
        return raw
    strike = float(match.group("strike"))
    price = float(match.group("price"))
    return (
        f"Strike ${strike:.2f} is above the current price ${price:.2f} — "
        "that's in-the-money for a put, which the scanner skips."
    )


def _fmt_delta_out_of_range(raw: str, ctx: HumanizeContext) -> str:
    """Render ``delta_out_of_range: |X| not in [min, max]`` with sub-case."""
    match = _DELTA_OUT_OF_RANGE_RE.match(raw)
    if not match:
        return raw
    delta = float(match.group("delta"))
    min_delta = float(match.group("min"))
    max_delta = float(match.group("max"))
    abs_delta = abs(delta)

    # Sub-case: too close to the money (delta too high) or too far OTM (too low)
    if abs_delta > max_delta:
        why = (
            "too close to the money, higher chance of assignment than you've "
            "set as acceptable"
        )
    elif abs_delta < min_delta:
        why = (
            "too far out of the money — premium is likely too thin to justify "
            "the trade"
        )
    else:
        # Defensive: shouldn't happen if the scanner emitted this code, but
        # we keep a neutral fallback rather than crash.
        why = "outside your target band"

    return (
        f"Delta {delta:+.2f} is outside your {min_delta:.2f}–{max_delta:.2f} "
        f"range — {why}."
    )


def _fmt_low_open_interest(raw: str, ctx: HumanizeContext) -> str:
    """Render ``low_open_interest: N < 50``."""
    match = _LOW_OI_RE.match(raw)
    if not match:
        return raw
    oi = int(match.group("oi"))
    min_oi = int(match.group("min"))
    return (
        f"Only {oi} contracts open — too thin to trade comfortably "
        f"(the scanner requires at least {min_oi})."
    )


def _fmt_zero_bid() -> str:
    """Render the ``zero_bid`` code (no parameters)."""
    return (
        "No buyer is showing a bid right now, so there's no real market to "
        "sell into."
    )


def _fmt_return_below_target(raw: str, ctx: HumanizeContext) -> str:
    """Render ``return_below_target: X% < Y%``."""
    match = _RETURN_BELOW_RE.match(raw)
    if not match:
        return raw
    pct = float(match.group("pct"))
    min_pct = float(match.group("min"))
    return (
        f"Premium is only {pct:.2f}% of capital — below your "
        f"{min_pct:.1f}% target return."
    )


def _fmt_return_above_cap(raw: str, ctx: HumanizeContext) -> str:
    """Render ``return_above_cap: X% > Y%``."""
    match = _RETURN_ABOVE_RE.match(raw)
    if not match:
        return raw
    pct = float(match.group("pct"))
    max_pct = float(match.group("max"))
    return (
        f"Premium is {pct:.2f}% of capital — above your "
        f"{max_pct:.1f}% cap. Usually means the strike is too close to the "
        "money for the risk."
    )


def _fmt_below_cost_basis(raw: str, ctx: HumanizeContext) -> str:
    """Render ``below_cost_basis: strike $X < floor $Y``."""
    match = _BELOW_COST_BASIS_RE.match(raw)
    if not match:
        return raw
    strike = float(match.group("strike"))
    floor = float(match.group("floor"))
    return (
        f"Strike ${strike:.2f} is below your ${floor:.2f} cost-basis floor — "
        "if assigned, you'd lock in a loss on the shares."
    )


def _fmt_wide_bid_ask_spread(raw: str, ctx: HumanizeContext) -> str:
    """Render ``wide_bid_ask_spread: X% > Y%``."""
    match = _WIDE_SPREAD_RE.match(raw)
    if not match:
        return raw
    pct = float(match.group("pct"))
    max_pct = float(match.group("max"))
    return (
        f"The bid/ask spread is {pct:.1f}% of the mid price — wider than your "
        f"{max_pct:.1f}% limit, so entering and exiting would cost too much."
    )


def _fmt_iv_rank_below_floor(raw: str, ctx: HumanizeContext) -> str:
    """Render ``iv_rank_below_floor: X < Y``."""
    match = _IV_RANK_BELOW_RE.match(raw)
    if not match:
        return raw
    rank = float(match.group("rank"))
    min_rank = float(match.group("min"))
    return (
        f"IV rank is {rank:.0f} — below your {min_rank:.0f} floor, so the "
        "premium on offer is likely too thin for selling options."
    )
