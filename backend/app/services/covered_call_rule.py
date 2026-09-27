"""Covered-call distance rule — the single source of truth (issue TBD).

The rule: a covered-call strike must satisfy
``strike >= cost_basis * (1 + T / 100)`` where ``T`` is
``min_call_distance_pct`` (the "10% rule" at the default ``T = 10``).

This module owns everything the three consumers need so they cannot drift:

- :func:`required_call_strike` / :func:`meets_call_distance` — the decision,
  evaluated at cent precision with exact decimal arithmetic.
- :func:`fails_10pct_raw` — the machine-readable rejection string the scanner
  emits; :data:`FAILS_10PCT_RE` / :func:`parse_fails_10pct` read it back
  (``rejection_messages`` and ``rejection_relax``).
- :func:`fails_10pct_sentence` — the canonical plain-English sentence, mirrored
  by ``formatFails10pctSentence`` in
  ``frontend/components/options/scannerRejectionLabels.js``.

Pure and stdlib-only, so it is safe to import from ``options_scanner``,
``rejection_messages`` and ``rejection_relax`` without circular imports.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, TypedDict

_CENT = Decimal("0.01")

# The prefix up to ``requires {T}%`` is byte-for-byte the pre-issue format; the
# optional parenthetical suffix carries the dollar context. Legacy strings (no
# suffix) still match, with the dollar groups ``None``.
FAILS_10PCT_RE = re.compile(
    r"^fails_10pct_rule:\s*strike\s*(?P<pct>-?\d+(?:\.\d+)?)%\s*above basis,\s*"
    r"requires\s*(?P<min>-?\d+(?:\.\d+)?)%"
    r"(?:\s*\(strike\s*\$(?P<strike>-?\d+(?:\.\d+)?),\s*basis\s*\$(?P<basis>-?\d+(?:\.\d+)?),\s*"
    r"min strike\s*\$(?P<min_strike>-?\d+(?:\.\d+)?)\))?\s*$"
)


class Fails10pctParts(TypedDict):
    """Values parsed out of a ``fails_10pct_rule`` raw string."""

    pct: float
    min: float
    strike: Optional[float]
    basis: Optional[float]
    min_strike: Optional[float]


def required_call_strike(cost_basis: float, distance_pct: float) -> float:
    """Return the lowest acceptable strike, rounded half-up to the cent.

    Uses exact decimal arithmetic on the inputs' string forms, so
    ``13.21 * 1.10`` is ``14.531`` (→ ``$14.53``) and ``10.00 * 1.10`` is
    exactly ``11.00`` — no binary-float drift.

    Why half-up rather than ceiling: the sentence tells the user "needs a
    strike of at least $Z", so a strike of exactly ``$Z`` must pass or the
    product contradicts itself. The sub-cent under-shoot (true floor 14.531
    vs. 14.53) is immaterial because listed strikes move in $0.50 / $1
    increments.
    """
    z = Decimal(str(cost_basis)) * (
        Decimal(1) + Decimal(str(distance_pct)) / Decimal(100)
    )
    return float(z.quantize(_CENT, rounding=ROUND_HALF_UP))


def meets_call_distance(strike: float, cost_basis: float, distance_pct: float) -> bool:
    """Return ``True`` iff ``strike`` clears the rule at cent precision."""
    strike_cents = Decimal(str(strike)).quantize(_CENT, rounding=ROUND_HALF_UP)
    return strike_cents >= Decimal(str(required_call_strike(cost_basis, distance_pct)))


def format_threshold_pct(value: float) -> str:
    """Format a percent threshold for display: at most two decimals, no
    trailing zeros (``10.0`` → ``"10"``, ``7.5`` → ``"7.5"``,
    ``7.25`` → ``"7.25"``). Mirrors ``formatThresholdPct`` in the frontend.
    """
    # ``+ 0.0`` normalizes a negative zero so it never renders as "-0".
    return f"{float(value) + 0.0:.2f}".rstrip("0").rstrip(".")


def fails_10pct_raw(strike: float, cost_basis: float, distance_pct: float) -> str:
    """Build the raw ``fails_10pct_rule`` rejection string.

    ``requires {T}%`` keeps Python's default float repr (``10.0``) exactly as
    before; the suffix carries strike, basis and the required strike computed
    from the full-precision basis.
    """
    distance = ((strike - cost_basis) / cost_basis) * 100
    min_strike = required_call_strike(cost_basis, distance_pct)
    return (
        f"fails_10pct_rule: strike {distance:.1f}% above basis, "
        f"requires {distance_pct}% "
        f"(strike ${strike:.2f}, basis ${cost_basis:.2f}, "
        f"min strike ${min_strike:.2f})"
    )


def parse_fails_10pct(raw: str) -> Optional[Fails10pctParts]:
    """Parse a raw ``fails_10pct_rule`` string (new or legacy format).

    Returns ``None`` when the string does not match. Legacy strings have
    ``strike`` / ``basis`` / ``min_strike`` set to ``None``.
    """
    match = FAILS_10PCT_RE.match(raw.strip())
    if not match:
        return None

    def _opt(name: str) -> Optional[float]:
        value = match.group(name)
        return float(value) if value is not None else None

    return {
        "pct": float(match.group("pct")),
        "min": float(match.group("min")),
        "strike": _opt("strike"),
        "basis": _opt("basis"),
        "min_strike": _opt("min_strike"),
    }


def fails_10pct_sentence(
    strike: Optional[float],
    cost_basis: Optional[float],
    distance_pct: float,
    pct: float,
    min_strike: Optional[float],
) -> str:
    """Render the canonical human sentence for a ``fails_10pct_rule`` reason.

    ``pct`` is the strike's distance from basis in percent (negative when the
    strike is below basis). The below/above word is chosen on the value
    rounded to one decimal, so a tiny negative never renders "-0.0% below".

    Degrades gracefully: without a basis and required strike (legacy raw with
    no context) the sentence drops the dollar figures; without a strike it
    drops only the strike figure.
    """
    rounded = round(pct, 1) + 0.0
    word = "below" if rounded < 0 else "above"
    magnitude = f"{abs(rounded):.1f}%"
    threshold = format_threshold_pct(distance_pct)

    if cost_basis is None or min_strike is None:
        return (
            f"Strike is {magnitude} {word} your cost basis. "
            f"Your {threshold}% rule needs more room above your basis."
        )
    lead = f"Strike ${strike:.2f} is" if strike is not None else "Strike is"
    return (
        f"{lead} {magnitude} {word} your ${cost_basis:.2f} basis. "
        f"Your {threshold}% rule needs a strike of at least ${min_strike:.2f}."
    )


__all__ = [
    "FAILS_10PCT_RE",
    "Fails10pctParts",
    "fails_10pct_raw",
    "fails_10pct_sentence",
    "format_threshold_pct",
    "meets_call_distance",
    "parse_fails_10pct",
    "required_call_strike",
]
