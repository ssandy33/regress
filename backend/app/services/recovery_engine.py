"""Recovery Plan path engine — deterministic forward-path enumeration.

Given an underwater position, the engine enumerates four candidate forward
paths and emits a deterministic scenario per path:

- ``sell-redeploy`` — accept realized loss, redeploy freed capital in a
  fresh CSP at the configured target yield.
- ``wheel-cc`` — grind monthly premium against the unrealized loss using
  the V0.5.8 1.5%/month wheel-premium heuristic.
- ``average-down`` — buy more shares at the current price; suppressed when
  the resulting capital tied up exceeds the per-position sizing cap.
- ``hold-monitor`` — no action; track the position with no new capital
  committed.

The engine is a **pure function**: every input is plain in-memory data and
every output dict is byte-identical for the same input. No DB, no network,
no LLM. The scoring layer (``recovery_scoring.py``) consumes only the
fields emitted here plus OKR settings.

V0.5.8 design decisions locked in the issue body + spec:

- ``months_to_breakeven`` is a ``{best, expected, worst}`` range, never a
  single point estimate, because the engine surfaces the uncertainty
  explicitly. Each component may be ``None`` (hold-monitor in particular).
- ``opportunity_cost_vs_baseline`` is a signed dollar value; sell-redeploy
  is the baseline and emits ``0``.
- Suppressed paths stay in ``paths[]`` so the frontend can render them with
  a de-emphasized treatment plus the ``suppression_reason``.
- ``narration`` is reserved for V0.6 (#181) and stays ``None`` here.

No ``irr`` field anywhere — the older v0.5.6 plan emitted one; the
recommendation-layer rewrite dropped it.
"""

from __future__ import annotations

import math

# --- Constants --------------------------------------------------------------

# Wheel-path monthly premium heuristic (% of strike, per issue AC). The
# scanner integration in V0.7 (#183) replaces this with live option-chain
# premium; until then the assumption is rendered verbatim in the UI.
WHEEL_MONTHLY_PREMIUM_PCT: float = 0.015

# Best/expected/worst multipliers applied to the deterministic
# expected-months estimate to materialize the range the engine emits.
# Best case: premium runs 25% higher than the heuristic (faster grind);
# worst case: 30% lower (slower grind).
WHEEL_BE_MULTIPLIERS: tuple[float, float, float] = (0.8, 1.0, 1.3)

# Canonical display labels. Stable per slug; rendered verbatim by the
# frontend.
_PATH_LABELS: dict[str, str] = {
    "sell-redeploy": "Sell & redeploy",
    "wheel-cc": "Wheel covered calls",
    "average-down": "Average down",
    "hold-monitor": "Hold & monitor",
}

# Canonical emission order. The engine always returns paths in this order
# so consumers (scoring, frontend) can index without sorting.
_PATH_ORDER: tuple[str, ...] = (
    "sell-redeploy",
    "wheel-cc",
    "average-down",
    "hold-monitor",
)


# --- Helpers ----------------------------------------------------------------


def _empty_range() -> dict:
    """Helper returning the ``{best, expected, worst}`` null-range dict."""
    return {"best": None, "expected": None, "worst": None}


def _format_dollar(amount: float) -> str:
    """Render a positive dollar amount with comma grouping (no sign)."""
    return f"${amount:,.0f}"


def _format_pct(pct: float) -> str:
    """Render a yield as ``N%`` with no decimal (e.g. ``18%``)."""
    return f"{pct * 100:.0f}%"


# --- Path builders ----------------------------------------------------------


def _sell_redeploy_path(
    *,
    realized_loss: float,
    freed_capital: float,
    target_yield: float | None,
) -> dict:
    """Build the ``sell-redeploy`` path scenario.

    Sell-redeploy is the **baseline** against which other paths' opportunity
    cost is computed, so its own ``opportunity_cost_vs_baseline`` is ``0``.
    Suppressed when ``target_yield`` is ``None`` because the breakeven
    estimate has no anchor without a target yield.
    """
    if target_yield is None:
        return {
            "path_id": "sell-redeploy",
            "label": _PATH_LABELS["sell-redeploy"],
            "eligibility": "suppressed",
            "suppression_reason": "Target yield not configured",
            "capital_tied_up": None,
            "months_to_breakeven": _empty_range(),
            "opportunity_cost_vs_baseline": None,
            "assumptions": [
                "Sell & redeploy requires a target yield from Settings → OKRs.",
            ],
            "narration": None,
        }

    # Annual expected return on freed capital, in dollars.
    annual_return = max(freed_capital, 0.0) * target_yield
    if annual_return <= 0 or realized_loss <= 0:
        # Without a positive annual return there's no breakeven horizon.
        months_range = _empty_range()
    else:
        # Months to earn back the realized loss at the configured yield.
        expected_months = (realized_loss / annual_return) * 12.0
        months_range = {
            "best": round(expected_months * 0.8, 1),
            "expected": round(expected_months, 1),
            "worst": round(expected_months * 1.3, 1),
        }

    assumptions = [
        f"Assumes redeployed capital earns {_format_pct(target_yield)} target yield.",
        f"Freed capital after sale: {_format_dollar(max(freed_capital, 0.0))}.",
    ]

    return {
        "path_id": "sell-redeploy",
        "label": _PATH_LABELS["sell-redeploy"],
        "eligibility": "eligible",
        "suppression_reason": None,
        "capital_tied_up": round(max(freed_capital, 0.0), 2),
        "months_to_breakeven": months_range,
        # Baseline: the engine pins this to exactly 0 so the rest of the
        # paths' deltas are well-defined.
        "opportunity_cost_vs_baseline": 0.0,
        "assumptions": assumptions,
        "narration": None,
    }


def _wheel_cc_path(
    *,
    realized_loss: float,
    current_price: float,
    shares: int,
    target_yield: float | None,
) -> dict:
    """Build the ``wheel-cc`` path scenario.

    Premium math: ``monthly_premium_dollars = WHEEL_MONTHLY_PREMIUM_PCT *
    strike_proxy * shares`` where ``strike_proxy = current_price`` (ATM
    short-call assumption — honest in absence of option-chain data).
    """
    strike_proxy = max(current_price, 0.0)
    monthly_premium = WHEEL_MONTHLY_PREMIUM_PCT * strike_proxy * max(shares, 0)
    capital_tied_up = round(strike_proxy * max(shares, 0), 2)

    if monthly_premium <= 0 or realized_loss <= 0:
        months_range = _empty_range()
    else:
        # ceil(loss / premium * multiplier). Best case: premium runs higher
        # (faster grind, fewer months). Worst case: premium runs lower
        # (slower grind, more months).
        best = math.ceil((realized_loss / monthly_premium) * WHEEL_BE_MULTIPLIERS[0])
        expected = math.ceil((realized_loss / monthly_premium) * WHEEL_BE_MULTIPLIERS[1])
        worst = math.ceil((realized_loss / monthly_premium) * WHEEL_BE_MULTIPLIERS[2])
        months_range = {"best": best, "expected": expected, "worst": worst}

    # Opportunity cost: capital tied up in shares could have earned the
    # target yield in a fresh CSP minus the premium income the wheel
    # generates. We surface gross annual premium foregone as the rough
    # baseline-comparison signal until the V0.7 chain integration.
    annual_premium = monthly_premium * 12.0
    if target_yield is None:
        opp_cost = None
    else:
        baseline_annual = capital_tied_up * target_yield
        opp_cost = round(baseline_annual - annual_premium, 2)

    assumptions = [
        (
            f"Assumes {WHEEL_MONTHLY_PREMIUM_PCT * 100:.1f}%/month premium on "
            f"${strike_proxy:,.2f} strike (V0.5.8 heuristic, see #183)."
        ),
    ]
    if target_yield is not None:
        assumptions.append(
            f"Opportunity cost compares to {_format_pct(target_yield)} target yield baseline."
        )

    return {
        "path_id": "wheel-cc",
        "label": _PATH_LABELS["wheel-cc"],
        "eligibility": "eligible",
        "suppression_reason": None,
        "capital_tied_up": capital_tied_up,
        "months_to_breakeven": months_range,
        "opportunity_cost_vs_baseline": opp_cost,
        "assumptions": assumptions,
        "narration": None,
    }


def _average_down_path(
    *,
    shares: int,
    current_price: float,
    adjusted_cost_basis: float,
    target_yield: float | None,
    sizing_cap_pct: float,
    total_capital: float | None,
) -> dict:
    """Build the ``average-down`` path scenario.

    The sizing cap is stored as a percentage of total trading capital
    (issue #234 v1 contract — ``sizing_cap_pct`` is whole-percent, e.g.
    ``25.0`` means 25%, NOT 0.25). The dollar ceiling is resolved at
    evaluation time against the connected Schwab account's
    net-liquidation value supplied as ``total_capital``.

    - When ``total_capital`` is known, the resolved cap is
      ``sizing_cap_pct * total_capital / 100``. The path is suppressed
      when ``capital_tied_up`` exceeds that resolved ceiling.
    - When ``total_capital is None`` (Schwab unavailable / cache empty),
      the cap CANNOT be resolved to a dollar amount. Per the §6.2
      "eligible-with-unenforceable" contract the path stays eligible
      but the assumption text names the unenforceable state explicitly
      so the user is never silently let through an oversized position.

    Suppressed paths stay in the response (frontend renders the
    de-emphasized treatment) so the user can see *why* it isn't
    recommended.
    """
    additional_capital = max(current_price, 0.0) * max(shares, 0)
    new_basis_total = max(adjusted_cost_basis, 0.0) + additional_capital
    capital_tied_up = round(new_basis_total, 2)

    # Resolve the percent cap to a dollar ceiling at evaluation time
    # against the supplied total trading capital. ``None`` means the
    # connected Schwab account value was unavailable — see the
    # "cap unenforceable" branch below.
    cap_resolved: float | None = (
        sizing_cap_pct * total_capital / 100 if total_capital is not None else None
    )

    # Sizing cap gate. Per design spec §3.3 the reason text contains the
    # word "sizing cap" so the frontend CTA mapper routes the user to
    # the Settings → Trading Rules tab (/settings?tab=rules) — the sizing
    # cap is a Trading Rule (issue #156 / #234), not an OKR.
    if cap_resolved is not None and capital_tied_up > cap_resolved:
        return {
            "path_id": "average-down",
            "label": _PATH_LABELS["average-down"],
            "eligibility": "suppressed",
            "suppression_reason": (
                f"Exceeds your {sizing_cap_pct:.0f}% per-position sizing cap "
                f"(≈ {_format_dollar(cap_resolved)})."
            ),
            "capital_tied_up": None,
            "months_to_breakeven": _empty_range(),
            "opportunity_cost_vs_baseline": None,
            "assumptions": [
                (
                    f"Sizing cap from Settings → Trading Rules: "
                    f"{sizing_cap_pct:.0f}% of your trading capital."
                ),
                (
                    f"Adding {_format_dollar(additional_capital)} would tie up "
                    f"{_format_dollar(capital_tied_up)} total."
                ),
            ],
            "narration": None,
        }

    # New cost basis per share after doubling the position.
    total_shares = max(shares, 0) * 2
    if total_shares > 0:
        new_basis_per_share = new_basis_total / total_shares
        # Breakeven projection: grind wheel-CC premium against the remaining
        # unrealized loss measured against the NEW blended basis. Mirrors
        # _wheel_cc_path's 1.5%/month heuristic, but premium accrues on the
        # *doubled* share count since the user now holds total_shares.
        # Deterministic — no price-recovery model required (see #237).
        remaining_loss = max(new_basis_total - current_price * total_shares, 0.0)
        monthly_premium = (
            WHEEL_MONTHLY_PREMIUM_PCT * max(current_price, 0.0) * total_shares
        )
        if monthly_premium > 0 and remaining_loss > 0:
            base_months = remaining_loss / monthly_premium
            months_range = {
                "best": math.ceil(base_months * WHEEL_BE_MULTIPLIERS[0]),
                "expected": math.ceil(base_months * WHEEL_BE_MULTIPLIERS[1]),
                "worst": math.ceil(base_months * WHEEL_BE_MULTIPLIERS[2]),
            }
        else:
            # No breakeven gap to project: current_price == 0 (monthly_premium
            # collapses to 0) or the position is already at/above the new
            # blended basis (remaining_loss == 0).
            months_range = _empty_range()
    else:
        # shares == 0 — no position to average down.
        new_basis_per_share = 0.0
        months_range = _empty_range()

    if target_yield is None:
        opp_cost = None
    else:
        # Capital that could have earned the target yield in a fresh CSP.
        opp_cost = round(additional_capital * target_yield, 2)

    # Cap-status assumption. When the cap resolved to dollars, name both
    # the % and the resolved $ ceiling so the user sees the math; when
    # the connected Schwab account value was unavailable, surface the
    # unenforceable state explicitly per the §6.2 contract.
    if cap_resolved is not None:
        cap_assumption = (
            f"Within your {sizing_cap_pct:.0f}% sizing cap "
            f"(≈ {_format_dollar(cap_resolved)})."
        )
    else:
        cap_assumption = (
            "Sizing cap is currently unenforceable — Schwab account value "
            "unavailable. The recovery path is shown without sizing "
            "enforcement; reconnect Schwab to enforce."
        )

    assumptions = [
        (
            f"Adds {_format_dollar(additional_capital)} at "
            f"${current_price:,.2f}/share — new basis {_format_dollar(new_basis_per_share)} "
            "per share."
        ),
        cap_assumption,
        (
            f"Breakeven projects {WHEEL_MONTHLY_PREMIUM_PCT * 100:.1f}%/month "
            "wheel-CC premium on the doubled position against the remaining loss."
        ),
    ]

    return {
        "path_id": "average-down",
        "label": _PATH_LABELS["average-down"],
        "eligibility": "eligible",
        "suppression_reason": None,
        "capital_tied_up": capital_tied_up,
        "months_to_breakeven": months_range,
        "opportunity_cost_vs_baseline": opp_cost,
        "assumptions": assumptions,
        "narration": None,
    }


def _hold_monitor_path(
    *,
    shares: int,
    current_price: float,
    adjusted_cost_basis: float,
    target_yield: float | None,
) -> dict:
    """Build the ``hold-monitor`` path scenario.

    Hold takes no action, so:
    - ``capital_tied_up`` is the current notional (no new money committed),
    - ``months_to_breakeven`` is all ``None`` (no action → no breakeven),
    - ``opportunity_cost_vs_baseline`` is the full annual yield foregone on
      freed capital, when target yield is known.
    """
    freed_capital = max(current_price, 0.0) * max(shares, 0)
    capital_tied_up = round(max(adjusted_cost_basis, 0.0), 2)

    if target_yield is None:
        opp_cost = None
    else:
        opp_cost = round(freed_capital * target_yield, 2)

    assumptions = [
        "Tracks the position at current price; no new capital committed.",
    ]
    if target_yield is not None:
        assumptions.append(
            f"Annual opportunity cost = {_format_dollar(freed_capital)} × "
            f"{_format_pct(target_yield)} target yield."
        )

    return {
        "path_id": "hold-monitor",
        "label": _PATH_LABELS["hold-monitor"],
        "eligibility": "eligible",
        "suppression_reason": None,
        "capital_tied_up": capital_tied_up,
        "months_to_breakeven": _empty_range(),
        "opportunity_cost_vs_baseline": opp_cost,
        "assumptions": assumptions,
        "narration": None,
    }


# --- Public surface ---------------------------------------------------------


def compute_recovery_paths(
    *,
    position: dict,
    current_price: float,
    target_yield: float | None,
    sizing_cap_pct: float,
    total_capital: float | None,
) -> list[dict]:
    """Compute the four candidate recovery paths for a flagged position.

    Pure function: same inputs → byte-identical output. No DB, no network,
    no LLM calls.

    Args:
        position: Plain dict with at least ``shares`` and either
            ``adjusted_cost_basis`` or ``broker_cost_basis``.
        current_price: Live (or last-known) price per share.
        target_yield: OKR target yield as a fraction (e.g. ``0.18``).
            ``None`` suppresses the sell-redeploy path and zeroes out
            opportunity-cost columns that depend on it.
        sizing_cap_pct: Per-position sizing cap as a whole-percent of
            trading capital (issue #234 v1 contract — ``25.0`` means
            25%, NOT 0.25). The caller resolves it from
            ``rules_config.position.sizing_cap_pct``.
        total_capital: Connected Schwab account net-liquidation value in
            dollars, supplied by the caller from the cached account-value
            service. ``None`` when the Schwab account value is unavailable
            (disconnected / expired / error); the average-down path
            handles ``None`` by staying eligible with the explicit
            "cap unenforceable" assumption per the §6.2 contract.

    Returns:
        Four-element list in canonical order (sell-redeploy, wheel-cc,
        average-down, hold-monitor).
    """
    shares = int(position.get("shares") or 0)
    adjusted_cost_basis = float(position.get("adjusted_cost_basis") or 0.0)
    # Adjusted cost basis is the authoritative input — broker_cost_basis is
    # only used when adjusted is missing (e.g. zero-trade positions).
    if adjusted_cost_basis <= 0:
        adjusted_cost_basis = float(position.get("broker_cost_basis") or 0.0)

    current_price = max(float(current_price or 0.0), 0.0)
    pct = float(sizing_cap_pct)
    capital = float(total_capital) if total_capital is not None else None

    # Realized loss for the sell-redeploy / wheel projections. If the
    # position is above water we still emit paths (the user can audit) but
    # the breakeven range collapses to ``None``.
    current_notional = current_price * max(shares, 0)
    realized_loss = max(adjusted_cost_basis - current_notional, 0.0)
    freed_capital = current_notional

    paths = [
        _sell_redeploy_path(
            realized_loss=realized_loss,
            freed_capital=freed_capital,
            target_yield=target_yield,
        ),
        _wheel_cc_path(
            realized_loss=realized_loss,
            current_price=current_price,
            shares=shares,
            target_yield=target_yield,
        ),
        _average_down_path(
            shares=shares,
            current_price=current_price,
            adjusted_cost_basis=adjusted_cost_basis,
            target_yield=target_yield,
            sizing_cap_pct=pct,
            total_capital=capital,
        ),
        _hold_monitor_path(
            shares=shares,
            current_price=current_price,
            adjusted_cost_basis=adjusted_cost_basis,
            target_yield=target_yield,
        ),
    ]
    # Defensive: enforce canonical order so the scoring layer can index by
    # position rather than slug-search.
    by_slug = {p["path_id"]: p for p in paths}
    return [by_slug[slug] for slug in _PATH_ORDER]


def canonical_path_labels() -> dict[str, str]:
    """Return a copy of the slug→label mapping for callers that need it."""
    return dict(_PATH_LABELS)


def canonical_path_order() -> tuple[str, ...]:
    """Return the canonical emission order as a tuple of slugs."""
    return _PATH_ORDER


__all__ = [
    "WHEEL_MONTHLY_PREMIUM_PCT",
    "WHEEL_BE_MULTIPLIERS",
    "compute_recovery_paths",
    "canonical_path_labels",
    "canonical_path_order",
]
