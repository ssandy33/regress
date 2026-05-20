"""Rejection-relax preview service (issue #258, v1.0.8).

Backs the **stateless** ``POST /api/options/scan/relax`` endpoint that answers
the user's question: "If I loosened rule X a little, how many of the strikes
the scanner just rejected would come back?" The answer is computed purely
from the ``rejected[]`` payload the client echoes from the most recent scan —
the server **never re-fetches market data**.

V1 contract (v1.0.8 freeze, see ``plans/have-the-cto-review-bubbly-orbit.md``):

- 7 **relaxable** rule families, each with a locked relax recipe:

  =================  ===================================================
  Rule               Relax recipe
  =================  ===================================================
  delta_out_of_range Widen the band by ±0.05 on each side
  low_open_interest  Floor ÷ 2
  wide_bid_ask_spread Cap × 1.5
  fails_10pct_rule   Required distance − 5 percentage points
  below_cost_basis   Cost-basis floor − 5 percentage points
  return_below_target Target − 1 percentage point
  return_above_cap   Cap + 50 percentage points
  =================  ===================================================

- 2 **binary** rule families (``itm_put``, ``zero_bid``) — no meaningful
  relaxation exists; the router raises ``HTTPException(400)`` with the
  generic detail ``"rule not relaxable"``.

The recovered set
-----------------
A strike "recovers" iff its ``rejection_reasons`` set:

1. contains the relaxed rule, **and**
2. **after** the relaxed threshold is re-applied, no longer trips that rule,
   **and**
3. has no *other* rejection reason (i.e. the relaxed rule was the **only**
   rule it was failing — single-rule recovery).

This third condition is what the spec calls "would actually come back if I
loosened that rule a little." A strike failing two rules is not freed by
relaxing one of them.

Threshold text strings
----------------------
The endpoint returns pre-formatted ``current_threshold_text`` and
``relaxed_threshold_text`` so the frontend does not need to know each rule's
unit (count, percent, ratio, dollars). The two strings are pinned per rule
in :data:`_THRESHOLD_FORMATTERS`.

Generic-error discipline
------------------------
Per CLAUDE.md, raw exception messages never leak. The router maps any
unexpected internal failure to a generic 500 ``"Failed to compute relax
preview"``. Binary rules are surfaced as the generic 400 ``"rule not
relaxable"`` — never the original code or the raw rule name.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from pydantic import BaseModel, Field

from app.models.schemas import RejectedStrike
from app.services.rules_config import RulesConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public Pydantic shapes (the router's request and response bodies)
# ---------------------------------------------------------------------------


class RelaxPreviewRequest(BaseModel):
    """Request body for ``POST /api/options/scan/relax``.

    The client echoes the ``rejected`` array from the most recent scan; the
    server never re-fetches market data. ``ticker`` and ``strategy`` are
    carried for completeness / logging but are not required to compute the
    recovered set.
    """

    ticker: str
    strategy: str
    rule: str
    rejected: list[RejectedStrike] = Field(default_factory=list)


class RecoveredStrike(BaseModel):
    """A strike that would recover at the relaxed threshold."""

    strike: float
    expiration: str


class RelaxPreviewResponse(BaseModel):
    """Response body for ``POST /api/options/scan/relax``."""

    rule: str
    current_threshold_text: str
    relaxed_threshold_text: str
    recovered_count: int
    recovered_strikes: list[RecoveredStrike]


# ---------------------------------------------------------------------------
# Rule classification
# ---------------------------------------------------------------------------


# The 7 rule families whose threshold has a meaningful "relax to X" recipe.
RELAXABLE_RULES: frozenset[str] = frozenset(
    {
        "delta_out_of_range",
        "low_open_interest",
        "wide_bid_ask_spread",
        "fails_10pct_rule",
        "below_cost_basis",
        "return_below_target",
        "return_above_cap",
    }
)

# The 2 binary rule families — no relaxation exists. Surfaced by the router
# as a generic 400 ``"rule not relaxable"``.
BINARY_RULES: frozenset[str] = frozenset({"itm_put", "zero_bid"})


class NotRelaxableError(ValueError):
    """Raised when the requested rule is binary / unknown. Mapped by the
    router to a generic 400 with the canonical message.
    """


# ---------------------------------------------------------------------------
# Regexes for parsing the raw rejection-reason strings emitted by
# ``OptionScanner._check_rejection`` and ``rejection_messages``.
# ---------------------------------------------------------------------------


_FAILS_10PCT_RE = re.compile(
    r"^fails_10pct_rule:\s*strike\s*(?P<pct>-?\d+(?:\.\d+)?)%\s*above basis,\s*"
    r"requires\s*(?P<min>-?\d+(?:\.\d+)?)%\s*$"
)
_BELOW_COST_BASIS_RE = re.compile(
    r"^below_cost_basis:\s*strike\s*\$(?P<strike>-?\d+(?:\.\d+)?)\s*<\s*"
    r"floor\s*\$(?P<floor>-?\d+(?:\.\d+)?)\s*$"
)
_DELTA_OUT_OF_RANGE_RE = re.compile(
    r"^delta_out_of_range:\s*\|(?P<delta>-?\d+(?:\.\d+)?)\|\s*not in\s*"
    r"\[(?P<min>-?\d+(?:\.\d+)?),\s*(?P<max>-?\d+(?:\.\d+)?)\]\s*$"
)
_LOW_OI_RE = re.compile(
    r"^low_open_interest:\s*(?P<oi>-?\d+)\s*<\s*(?P<min>-?\d+)\s*$"
)
_WIDE_SPREAD_RE = re.compile(
    r"^wide_bid_ask_spread:\s*(?P<pct>-?\d+(?:\.\d+)?)%\s*>\s*"
    r"(?P<max>-?\d+(?:\.\d+)?)%\s*$"
)
_RETURN_BELOW_RE = re.compile(
    r"^return_below_target:\s*(?P<pct>-?\d+(?:\.\d+)?)%\s*<\s*"
    r"(?P<min>-?\d+(?:\.\d+)?)%\s*$"
)
_RETURN_ABOVE_RE = re.compile(
    r"^return_above_cap:\s*(?P<pct>-?\d+(?:\.\d+)?)%\s*>\s*"
    r"(?P<max>-?\d+(?:\.\d+)?)%\s*$"
)


def _extract_rule_family(raw: str) -> Optional[str]:
    """Return the rule family — the prefix up to the first colon.

    Mirrors the frontend's ``extractRuleFamily`` in
    ``scannerRejectionLabels.js``. Returns ``None`` for empty/unparseable
    strings. The ``zero_bid`` family is emitted as a literal code (no
    colon); we handle that branch explicitly.
    """
    if not raw:
        return None
    if raw == "zero_bid" or raw.startswith("zero_bid"):
        return "zero_bid"
    match = re.match(r"^([a-z0-9_]+)", raw, flags=re.IGNORECASE)
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# Per-rule "would this still fire at the relaxed threshold?" predicates
# ---------------------------------------------------------------------------
#
# Each predicate parses the raw rejection-reason string the scanner emitted,
# extracts the observed value, and returns ``True`` iff the rule would
# still fire under the relaxed threshold. Unparseable strings default to
# ``True`` (still rejecting) — defensive: never claim a strike recovered
# without proof.


def _still_fails_fails_10pct(raw: str) -> bool:
    match = _FAILS_10PCT_RE.match(raw)
    if not match:
        return True
    pct = float(match.group("pct"))
    requires = float(match.group("min"))
    relaxed_requires = requires - 5.0  # -5pp
    return pct < relaxed_requires


def _still_fails_below_cost_basis(raw: str) -> bool:
    match = _BELOW_COST_BASIS_RE.match(raw)
    if not match:
        return True
    strike = float(match.group("strike"))
    floor = float(match.group("floor"))
    # Relax floor by -5 percentage points of *the floor itself*. Per V1
    # contract: "floor -5pp" — the floor is a percent-margin threshold; the
    # scanner persists it as a dollar floor that already encodes the
    # percent. Drop the dollar floor by 5% of the original floor value
    # (i.e. floor * (1 - 0.05) is the relaxed dollar floor, which is the
    # spec's "5pp" applied to a 0-anchored percentage rule).
    #
    # Rationale: ``below_cost_basis`` is the bare at-or-above-basis floor
    # gated by ``min_call_distance_from_cost_basis_pct`` (default 0). The
    # raw rejection text gives us the resolved dollar floor; the only
    # consistent way to translate "-5pp" into a dollar relaxation is to
    # drop the floor by 5% of itself.
    relaxed_floor = floor * (1.0 - 0.05)
    return strike < relaxed_floor


def _still_fails_delta(raw: str) -> bool:
    match = _DELTA_OUT_OF_RANGE_RE.match(raw)
    if not match:
        return True
    delta = abs(float(match.group("delta")))
    min_d = float(match.group("min"))
    max_d = float(match.group("max"))
    # Widen the band by ±0.05 on each side.
    relaxed_min = max(0.0, min_d - 0.05)
    relaxed_max = min(1.0, max_d + 0.05)
    return delta < relaxed_min or delta > relaxed_max


def _still_fails_low_oi(raw: str) -> bool:
    match = _LOW_OI_RE.match(raw)
    if not match:
        return True
    oi = int(match.group("oi"))
    min_oi = int(match.group("min"))
    relaxed_min = max(0, min_oi // 2)
    return oi < relaxed_min


def _still_fails_wide_spread(raw: str) -> bool:
    match = _WIDE_SPREAD_RE.match(raw)
    if not match:
        return True
    pct = float(match.group("pct"))
    max_pct = float(match.group("max"))
    relaxed_max = max_pct * 1.5
    return pct > relaxed_max


def _still_fails_return_below(raw: str) -> bool:
    match = _RETURN_BELOW_RE.match(raw)
    if not match:
        return True
    pct = float(match.group("pct"))
    min_pct = float(match.group("min"))
    relaxed_min = min_pct - 1.0  # -1pp
    return pct < relaxed_min


def _still_fails_return_above(raw: str) -> bool:
    match = _RETURN_ABOVE_RE.match(raw)
    if not match:
        return True
    pct = float(match.group("pct"))
    max_pct = float(match.group("max"))
    relaxed_max = max_pct + 50.0  # +50pp
    return pct > relaxed_max


_STILL_FAILS_PREDICATES = {
    "fails_10pct_rule": _still_fails_fails_10pct,
    "below_cost_basis": _still_fails_below_cost_basis,
    "delta_out_of_range": _still_fails_delta,
    "low_open_interest": _still_fails_low_oi,
    "wide_bid_ask_spread": _still_fails_wide_spread,
    "return_below_target": _still_fails_return_below,
    "return_above_cap": _still_fails_return_above,
}


# ---------------------------------------------------------------------------
# Threshold formatters — return ``(current_text, relaxed_text)`` for the rule,
# resolved against the persisted rules config.
# ---------------------------------------------------------------------------


def _fmt_pct(value: float) -> str:
    """Format a whole-percent value compactly (drops trailing ``.0``)."""
    if value == int(value):
        return f"{int(value)}%"
    return f"{value:.1f}%"


def _fmt_int(value: int) -> str:
    return f"{int(value)}"


def _fmt_band(min_v: float, max_v: float) -> str:
    return f"{min_v:.2f}–{max_v:.2f}"  # en-dash separator


def _thresholds_fails_10pct(rules: RulesConfig) -> tuple[str, str]:
    current = float(rules.entry.min_call_distance_pct)
    relaxed = current - 5.0
    return _fmt_pct(current), _fmt_pct(relaxed)


def _thresholds_below_cost_basis(rules: RulesConfig) -> tuple[str, str]:
    current = float(rules.entry.min_call_distance_from_cost_basis_pct)
    relaxed = current - 5.0
    return _fmt_pct(current), _fmt_pct(relaxed)


def _thresholds_delta(rules: RulesConfig) -> tuple[str, str]:
    # CSP is the default scan band; the popover does not (yet) know which
    # delta band fired. The chosen band is informational text only — the
    # actual recovered-set re-evaluation parses the raw rejection string
    # which already carries the firing band's bounds.
    band = rules.entry.delta_range_csp
    current = _fmt_band(float(band.min), float(band.max))
    relaxed_min = max(0.0, float(band.min) - 0.05)
    relaxed_max = min(1.0, float(band.max) + 0.05)
    relaxed = _fmt_band(relaxed_min, relaxed_max)
    return current, relaxed


def _thresholds_low_oi(rules: RulesConfig) -> tuple[str, str]:
    current = int(rules.universe.min_open_interest)
    relaxed = max(0, current // 2)
    return _fmt_int(current), _fmt_int(relaxed)


def _thresholds_wide_spread(rules: RulesConfig) -> tuple[str, str]:
    current = float(rules.universe.max_bid_ask_spread_pct)
    relaxed = current * 1.5
    return _fmt_pct(current), _fmt_pct(relaxed)


def _thresholds_return_below(rules: RulesConfig) -> tuple[str, str]:
    current = float(rules.entry.min_monthly_return_pct)
    relaxed = current - 1.0
    return _fmt_pct(current), _fmt_pct(relaxed)


def _thresholds_return_above(rules: RulesConfig) -> tuple[str, str]:
    # The scanner has no persisted "max monthly return cap" — the
    # ``return_above_cap`` rejection text carries the cap inline. Use the
    # rejection text's cap when available; fall back to a "—" placeholder
    # when no strike emitted the rule (the popover only opens for rules
    # that have at least one rejection chip, so this fallback is defensive).
    return ("—", "—")


_THRESHOLD_FORMATTERS = {
    "fails_10pct_rule": _thresholds_fails_10pct,
    "below_cost_basis": _thresholds_below_cost_basis,
    "delta_out_of_range": _thresholds_delta,
    "low_open_interest": _thresholds_low_oi,
    "wide_bid_ask_spread": _thresholds_wide_spread,
    "return_below_target": _thresholds_return_below,
    "return_above_cap": _thresholds_return_above,
}


def _threshold_texts_for_return_above(
    rejected: list[RejectedStrike],
) -> tuple[str, str]:
    """Special-case ``return_above_cap`` — read the cap from a raw reason.

    The scanner does not persist a "max monthly return cap" in
    :class:`RulesConfig` (today). Pull the cap from the first matching
    rejection string and apply ``+50pp``. Falls back to a ``"—"`` placeholder
    when no parseable string is present.
    """
    for r in rejected:
        for raw in r.rejection_reasons or []:
            match = _RETURN_ABOVE_RE.match(raw)
            if match:
                cap = float(match.group("max"))
                return _fmt_pct(cap), _fmt_pct(cap + 50.0)
    return ("—", "—")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def preview_relax(
    req: RelaxPreviewRequest, rules: RulesConfig
) -> RelaxPreviewResponse:
    """Compute the recovered set under the relaxed threshold.

    Args:
        req: The request body — carries ``ticker``, ``strategy``, ``rule``,
            and the ``rejected`` array echoed from the most recent scan.
        rules: The persisted :class:`RulesConfig` — used to format the
            ``current_threshold_text`` per rule.

    Returns:
        :class:`RelaxPreviewResponse` with the recovered count and (up to
        the full set of) recovered strikes. Frontend truncates for display.

    Raises:
        :class:`NotRelaxableError`: when ``req.rule`` is in
            :data:`BINARY_RULES` or unknown. The router maps this to a
            generic 400.
    """
    rule = req.rule

    if rule in BINARY_RULES or rule not in RELAXABLE_RULES:
        raise NotRelaxableError("rule not relaxable")

    predicate = _STILL_FAILS_PREDICATES[rule]

    # Threshold-text resolution. ``return_above_cap`` reads its cap from the
    # rejection-reason payload (no persisted config field) — handled
    # explicitly so the formatter signature stays uniform.
    if rule == "return_above_cap":
        current_text, relaxed_text = _threshold_texts_for_return_above(
            req.rejected
        )
    else:
        current_text, relaxed_text = _THRESHOLD_FORMATTERS[rule](rules)

    recovered: list[RecoveredStrike] = []
    for r in req.rejected:
        reasons = r.rejection_reasons or []
        if not reasons:
            continue
        # The strike must be failing the requested rule.
        families = {_extract_rule_family(raw) for raw in reasons}
        families.discard(None)
        if rule not in families:
            continue
        # The strike must be failing ONLY that rule (single-reason
        # recovery; multi-reason rows still fail the other rules even when
        # we relax this one).
        if len(reasons) != 1 or len(families) != 1:
            continue
        raw = reasons[0]
        if not predicate(raw):
            recovered.append(
                RecoveredStrike(strike=r.strike, expiration=r.expiration)
            )

    # Canonical sort: strike asc, expiration asc. Stable so equal strikes
    # surface in payload order within the expiration tier.
    recovered.sort(key=lambda s: (s.strike, s.expiration))

    return RelaxPreviewResponse(
        rule=rule,
        current_threshold_text=current_text,
        relaxed_threshold_text=relaxed_text,
        recovered_count=len(recovered),
        recovered_strikes=recovered,
    )


__all__ = [
    "BINARY_RULES",
    "RELAXABLE_RULES",
    "NotRelaxableError",
    "RecoveredStrike",
    "RelaxPreviewRequest",
    "RelaxPreviewResponse",
    "preview_relax",
]
