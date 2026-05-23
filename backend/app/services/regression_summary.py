"""Plain-English summary generator for regression decomposition.

Implements the four-rule set from issue #280 design spec §4 Section E. The
output is a single sentence rendered verbatim by the frontend, kept under
the 120-character cap from the implementation plan §4.9.

The four rules (verbatim from the spec):

1. Identify the dominant factor (largest absolute contribution).
2. If dominant > 0.50: lead with "Mostly {factor}-driven".
   Else if dominant > 0.30: "Primarily {factor}-driven".
   Else: "Diversified driver mix".
3. Flag any factor with p < 0.05 AND |beta| > 0.5 AND contribution > 0.10
   as "meaningful". List the top 2 meaningful factors after the lead,
   with sign-aware language:
     - Negative beta on rates → "rate exposure is meaningful and negative"
     - Positive beta on sector → "sector exposure adds positively"
4. Append R² as a closing fact: "R²=0.83 over 252 trading days".

Author notes (ambiguities resolved by the implementer for parity with the
spec's four worked examples):

- The biotech example renders as "Mostly idiosyncratic — {pct}% of variance
  unexplained by market/sector/rates" — a distinct form from the other
  three when the dominant share is the unexplained residual. Handled as a
  special branch.
- The TLT example mentions a NON-meaningful secondary factor ("market
  exposure is minor"). Rule 3 only describes meaningful factors; the
  "minor" phrase is interpreted as a fallback when no other meaningful
  factor exists and the dominant factor is overwhelming — surface the
  next-biggest with a "minor" qualifier so the sentence has content beyond
  the lead.
"""

from __future__ import annotations

from typing import Literal, TypedDict


# --- Public types -----------------------------------------------------------


class SummaryFactor(TypedDict):
    """Structured factor input for the summary generator.

    ``name`` is one of ``"market"``, ``"sector"``, ``"rates"``, or
    ``"idiosyncratic"``. ``beta`` and ``p_value`` are ``None`` for the
    idiosyncratic residual. ``contribution`` is the share of explained
    variance (sums with idiosyncratic to ~1.0).
    """

    name: Literal["market", "sector", "rates", "idiosyncratic"]
    beta: float | None
    p_value: float | None
    contribution: float


# --- Thresholds (from spec §4 Section E rule set) ---------------------------

_DOMINANT_MOSTLY = 0.50
_DOMINANT_PRIMARILY = 0.30
_MEANINGFUL_P_MAX = 0.05
_MEANINGFUL_ABS_BETA_MIN = 0.5
_MEANINGFUL_CONTRIBUTION_MIN = 0.10
_MAX_MEANINGFUL_AFTER_LEAD = 2


# --- Phrase builders --------------------------------------------------------


def _factor_label(name: str) -> str:
    """Return the lead-phrase noun for a factor name."""
    return {
        "market": "market",
        "sector": "sector",
        "rates": "rate",
        "idiosyncratic": "idiosyncratic",
    }.get(name, name)


def _meaningful_clause(factor: SummaryFactor) -> str:
    """Build the sign-aware "meaningful factor" clause.

    Mirrors the spec's worked examples:
    - rates, negative beta → ``"rate exposure is meaningful and negative"``
    - rates, positive beta → ``"rate exposure is meaningful and positive"``
    - sector, positive beta → ``"sector exposure adds positively"``
    - sector, negative beta → ``"sector exposure detracts"``
    - market, negative beta → ``"market exposure is meaningful and negative"``
    - market, positive beta → ``"market exposure is meaningful and positive"``
    """
    beta = factor["beta"] or 0.0
    sign_positive = beta >= 0
    name = factor["name"]

    if name == "rates":
        return (
            "rate exposure is meaningful and positive"
            if sign_positive
            else "rate exposure is meaningful and negative"
        )
    if name == "sector":
        return (
            "sector exposure adds positively"
            if sign_positive
            else "sector exposure detracts"
        )
    # Default ("market" or anything else): use the meaningful-and-{sign} phrasing.
    label = _factor_label(name)
    return (
        f"{label} exposure is meaningful and positive"
        if sign_positive
        else f"{label} exposure is meaningful and negative"
    )


def _is_meaningful(factor: SummaryFactor) -> bool:
    """Apply the rule-3 meaningful-factor predicate.

    Idiosyncratic is never "meaningful" in this sense — it has no beta or
    p-value, and is handled by the dominant-factor branch instead.
    """
    if factor["name"] == "idiosyncratic":
        return False
    if factor["beta"] is None or factor["p_value"] is None:
        return False
    return (
        factor["p_value"] < _MEANINGFUL_P_MAX
        and abs(factor["beta"]) > _MEANINGFUL_ABS_BETA_MIN
        and factor["contribution"] > _MEANINGFUL_CONTRIBUTION_MIN
    )


def _lead_phrase(dominant: SummaryFactor) -> str:
    """Build the rule-2 lead phrase from the dominant factor's contribution."""
    share = dominant["contribution"]
    label = _factor_label(dominant["name"])
    if share > _DOMINANT_MOSTLY:
        return f"Mostly {label}-driven"
    if share > _DOMINANT_PRIMARILY:
        return f"Primarily {label}-driven"
    return "Diversified driver mix"


def _r_squared_clause(r_squared: float, sample_size: int) -> str:
    """Format the rule-4 closing R²/sample-size clause."""
    return f"R²={r_squared:.2f} over {sample_size} trading days"


def _format_pct(value: float) -> str:
    """Format a 0-1 share as an integer percent (e.g. 0.60 → ``'60%'``)."""
    return f"{round(value * 100)}%"


# --- Idiosyncratic-dominant special case -----------------------------------


def _idiosyncratic_lead(factor: SummaryFactor, sector_omitted: bool) -> str:
    """Lead phrase when idiosyncratic is the dominant share.

    Spec example: ``"Mostly idiosyncratic — 60% of variance unexplained by
    market/sector/rates"``. When the sector factor was omitted (no sector
    mapping for the underlying), the basket-list term drops "sector".
    """
    basket = "market/rates" if sector_omitted else "market/sector/rates"
    return (
        f"Mostly idiosyncratic — {_format_pct(factor['contribution'])} "
        f"of variance unexplained by {basket}"
    )


# --- Main entrypoint --------------------------------------------------------


def build_regression_summary(
    factors: list[SummaryFactor],
    r_squared: float,
    sample_size: int,
    sector_omitted: bool = False,
) -> str:
    """Compose a one-sentence plain-English summary of a regression decomposition.

    See module docstring for the four-rule set the output follows. The
    returned string is capped at 120 characters per the plan §4.9 contract;
    if the rule output would exceed the cap, the secondary clauses are
    trimmed (R² is preserved as the closing fact).

    Parameters
    ----------
    factors:
        Per-factor decomposition, including the idiosyncratic residual.
    r_squared:
        Coefficient of determination from the levels regression (0.0-1.0).
    sample_size:
        Number of observations used in the regression.
    sector_omitted:
        ``True`` when no sector factor was included (unmapped/missing
        sector); the summary then skips any sector clause.
    """
    if not factors:
        # Defensive: no factors means we have nothing to summarize.
        return f"Insufficient data — {_r_squared_clause(r_squared, sample_size)}."

    # Rule 1: identify the dominant factor by absolute contribution.
    dominant = max(factors, key=lambda f: abs(f["contribution"]))

    # Idiosyncratic-dominant special form (spec example 4).
    if dominant["name"] == "idiosyncratic":
        lead = _idiosyncratic_lead(dominant, sector_omitted)
        closing = _r_squared_clause(r_squared, sample_size)
        return f"{lead}. {closing}."

    # Rule 2: lead phrase.
    lead = _lead_phrase(dominant)

    # Rule 3: meaningful factors after the lead (excluding the dominant
    # itself and, if applicable, the omitted sector).
    candidates = [
        f
        for f in factors
        if f["name"] != dominant["name"]
        and f["name"] != "idiosyncratic"
        and not (sector_omitted and f["name"] == "sector")
        and _is_meaningful(f)
    ]
    # Order by contribution descending and cap at the spec's top-2.
    candidates.sort(key=lambda f: f["contribution"], reverse=True)
    meaningful = candidates[:_MAX_MEANINGFUL_AFTER_LEAD]

    clauses: list[str] = [lead]
    if meaningful:
        clauses.extend(_meaningful_clause(f) for f in meaningful)
    else:
        # Fallback (TLT example): if dominant overwhelmingly leads and no
        # other meaningful factor exists, surface the next-largest factor
        # with a "minor" qualifier so the sentence carries content beyond
        # the lead phrase.
        non_dominant = [
            f
            for f in factors
            if f["name"] != dominant["name"]
            and f["name"] != "idiosyncratic"
            and not (sector_omitted and f["name"] == "sector")
        ]
        if non_dominant and dominant["contribution"] > _DOMINANT_PRIMARILY:
            next_biggest = max(non_dominant, key=lambda f: f["contribution"])
            label = _factor_label(next_biggest["name"])
            clauses.append(f"{label} exposure is minor")

    # Assemble: "lead; clause1; clause2. R²=…"
    body = "; ".join(clauses)
    closing = _r_squared_clause(r_squared, sample_size)
    summary = f"{body}. {closing}."

    # 120-char cap (plan §4.9). If we are over the cap, trim secondary
    # clauses one at a time from the tail while keeping the closing R²
    # fact intact.
    if len(summary) > 120 and len(clauses) > 1:
        for cut in range(len(clauses) - 1, 0, -1):
            trimmed = "; ".join(clauses[:cut])
            summary = f"{trimmed}. {closing}."
            if len(summary) <= 120:
                break

    return summary
