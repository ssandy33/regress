"""Combined covered-call P&L + if-assigned projection service (issue #247).

Composes the per-position ``GET /api/positions/{position_id}/covered-call``
payload. The screen is the per-position analog of the per-leg buy-to-close
screen (#244) — it nets shares + every open option leg into one number and
projects what the position is worth if each open short call is assigned.

Reuse, not re-implementation (plan §Approach Summary):

- This service does **not** modify :func:`derive_leg_economics` or any
  existing helper. ``derive_open_legs`` is invoked and its per-leg
  ``pnl_dollars`` (#246's field) is summed — so the ``options_pnl`` line
  agrees with the dashboard's leg-row P&L by construction.
- The new compute is genuinely position-scoped: shares + Σ legs for the
  unrealized side, and per-short-call if-assigned with a `shares_called`
  cap. That cap requires knowing the leg's siblings (a single leg cannot
  derive its own allocation), which is why this lives in its own module
  rather than hanging off the leg-level helper.

Spec §5.5 degraded paths:

- ``current_price is None`` → ``stock_pnl`` and ``combined_pnl`` are ``None``;
  ``options_pnl`` and the if-assigned projections are unaffected.
- Any leg ``pnl_dollars is None`` → ``options_pnl`` and ``combined_pnl`` are
  ``None``; the if-assigned projections are unaffected (premium and strike
  are booked at trade time, not pricing-dependent).

Spec §7 multi-leg variant (Q6 — earliest-expiring-first):

- ``_allocate_shares_called`` walks the short-call legs in DTE-ascending
  order, claiming ``min(qty * 100, remaining_shares)`` per leg until the
  position's shares are exhausted. The later-expiring leg(s) get
  ``shares_called == 0`` but still keep their full ``premium_kept``.

The router owns the try/except and converts a Schwab failure to a generic
500 (no ``str(e)`` leak per CLAUDE.md).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Literal

from sqlalchemy.orm import Session as DBSession

from app.services import journal
from app.services.dashboard_legs import (
    OPTION_MULTIPLIER,
    build_option_mark_index,
    derive_open_legs,
)
from app.services.rules_config import load_rules_config
from app.services.schwab_client import SchwabClient

logger = logging.getLogger(__name__)

# Mandatory footer disclaimer (spec §3.6) — shipped in the payload so the
# frontend renders the project's house framing rule verbatim.
DISCLAIMER_TEXT: str = (
    "These figures report the position state; they do not recommend an "
    "action. Roll / hold / let-assign decisions remain with you."
)

# The four applicability buckets the frontend's state machine consumes.
Applicability = Literal[
    "covered_call",
    "not_applicable_no_shares",
    "not_applicable_no_short_call",
    "not_applicable_closed",
]


# ---------------------------------------------------------------------------
# Pure helpers — no DB, no Schwab. Unit-tested in test_covered_call_service.
# ---------------------------------------------------------------------------


def _compute_combined_today(
    shares: int,
    current_price: float | None,
    basis: float,
    legs: Iterable[dict],
) -> dict[str, float | None]:
    """Return ``{stock_pnl, options_pnl, combined_pnl}`` for the position.

    ``stock_pnl = shares * (current_price - basis_per_share)`` — degraded to
    ``None`` when ``current_price`` is missing. ``basis`` is the position's
    *per-share* cost basis (the canonical broker_cost_basis as the dashboard
    payload exposes it — per-share, not total).

    ``options_pnl`` sums every leg's ``pnl_dollars`` (#246's per-leg field).
    The sum degrades to ``None`` if any open leg's ``pnl_dollars`` is missing
    (the leg row already renders "—" in that case; the position-scoped
    aggregate must do the same to stay honest).

    ``combined_pnl`` is the sum, ``None`` if either side is ``None``.
    """
    if current_price is None:
        stock_pnl: float | None = None
    else:
        stock_pnl = round(shares * (current_price - basis), 2)

    leg_list = list(legs)
    if any(lg.get("pnl_dollars") is None for lg in leg_list):
        options_pnl: float | None = None
    else:
        options_pnl = round(sum(lg["pnl_dollars"] for lg in leg_list), 2)

    if stock_pnl is None or options_pnl is None:
        combined_pnl: float | None = None
    else:
        combined_pnl = round(stock_pnl + options_pnl, 2)

    return {
        "stock_pnl": stock_pnl,
        "options_pnl": options_pnl,
        "combined_pnl": combined_pnl,
    }


def _allocate_shares_called(
    short_call_legs: Iterable[dict],
    shares: int,
) -> dict[str, int]:
    """Allocate the position's shares across short-call legs.

    Returns ``{leg_id: shares_called}``. The allocation rule (Q6) is
    **earliest-expiring-first**: legs are processed in (dte ASC, ticker ASC)
    order — the same sort ``derive_open_legs`` already uses — and each leg
    claims ``min(qty * 100, remaining_shares)``. When the position has more
    contract-equivalent shares than actual shares, the later-expiring leg
    ends up with ``shares_called == 0`` (it still keeps its full premium).

    Stable secondary sort by leg id ensures determinism when two legs share
    the same (dte, ticker) — rare but possible with two contracts opened the
    same day on the same leg.
    """
    if shares <= 0:
        return {str(lg["id"]): 0 for lg in short_call_legs}

    ordered = sorted(
        short_call_legs,
        key=lambda lg: (
            int(lg.get("dte", 9999)),
            str(lg.get("ticker", "")),
            str(lg.get("id", "")),
        ),
    )
    allocation: dict[str, int] = {}
    remaining = shares
    for leg in ordered:
        leg_id = str(leg["id"])
        qty = int(leg.get("quantity") or 0)
        contract_shares = qty * OPTION_MULTIPLIER
        claim = min(contract_shares, remaining)
        if claim < 0:
            claim = 0
        allocation[leg_id] = claim
        remaining = max(0, remaining - claim)
    return allocation


def _build_if_assigned(
    short_call_legs: Iterable[dict],
    shares_called_map: dict[str, int],
    basis: float,
) -> list[dict[str, Any]]:
    """Build the per-leg if-assigned projection list.

    For each open short call:

    - ``shares_called`` is looked up from the allocation map (capped per
      :func:`_allocate_shares_called`).
    - ``share_pnl = shares_called * (strike - basis)`` — can be negative on a
      rolled-down covered call where the strike sits below the cost basis.
    - ``premium_kept = premium * OPTION_MULTIPLIER * qty`` — the credit
      remains the seller's whether or not shares end up called, so the value
      is independent of ``shares_called``.
    - ``if_assigned_pnl = share_pnl + premium_kept``.

    Spec edge: an already-expired leg (``dte < 0``) is **excluded** —
    projecting assignment on an option that has expired is meaningless. The
    per-leg breakdown table still surfaces the row (the caller carries the
    full leg list separately) but with ``if_assigned_pnl == None``.

    A leg whose ``premium`` is missing or non-positive degrades to a null
    projection so the screen never fabricates a payoff figure.
    """
    out: list[dict[str, Any]] = []
    for leg in short_call_legs:
        if int(leg.get("dte", 9999)) < 0:
            continue  # excluded — already expired

        leg_id = str(leg["id"])
        qty = int(leg.get("quantity") or 0)
        premium = leg.get("premium")
        strike = leg.get("strike")
        if premium is None or premium <= 0 or qty <= 0 or strike is None:
            # Degraded — surface the leg with null projection so the frontend
            # can render the row without a payoff value.
            out.append(
                {
                    "leg_id": leg_id,
                    "strike": float(strike) if strike is not None else 0.0,
                    "premium": float(premium) if premium is not None else 0.0,
                    "qty": qty,
                    "shares_called": shares_called_map.get(leg_id, 0),
                    "share_pnl": 0.0,
                    "premium_kept": 0.0,
                    "if_assigned_pnl": None,
                }
            )
            continue

        shares_called = shares_called_map.get(leg_id, 0)
        share_pnl = round(shares_called * (float(strike) - basis), 2)
        premium_kept = round(float(premium) * OPTION_MULTIPLIER * qty, 2)
        if_assigned_pnl = round(share_pnl + premium_kept, 2)
        out.append(
            {
                "leg_id": leg_id,
                "strike": float(strike),
                "premium": float(premium),
                "qty": qty,
                "shares_called": shares_called,
                "share_pnl": share_pnl,
                "premium_kept": premium_kept,
                "if_assigned_pnl": if_assigned_pnl,
            }
        )
    return out


def _classify_applicability(
    position: dict,
    short_call_legs: Iterable[dict],
) -> Applicability:
    """Map (position, short-calls) to the screen's applicability state.

    Order of checks is deliberate: a closed position short-circuits before
    everything else (the screen has nothing meaningful to say about it). A
    position with zero shares is "no shares" even when it has open puts —
    the if-assigned mechanic is a covered-call concept, not a CSP one.
    """
    status = str(position.get("status") or "").lower()
    if status == "closed":
        return "not_applicable_closed"

    shares = int(position.get("shares") or 0)
    if shares <= 0:
        return "not_applicable_no_shares"

    has_short_call = any(True for _ in short_call_legs)
    if not has_short_call:
        return "not_applicable_no_short_call"

    return "covered_call"


# ---------------------------------------------------------------------------
# Orchestrator — composes the helpers and the Schwab fetch.
# ---------------------------------------------------------------------------


def _build_position_summary(
    position: dict,
    current_price: float | None,
) -> dict[str, Any]:
    """Compose the response's ``position`` block — basis as per-share float."""
    shares = int(position.get("shares") or 0)
    broker_cost_basis = float(position.get("broker_cost_basis") or 0.0)
    # The DB column stores the total dollar basis on the position; the
    # screen needs per-share (so it can multiply by share count for the
    # stock-leg P&L). Divide here so every downstream consumer is consistent.
    basis_per_share = (
        broker_cost_basis / shares if shares > 0 else broker_cost_basis
    )
    return {
        "id": str(position.get("id") or ""),
        "ticker": str(position.get("ticker") or ""),
        "shares": shares,
        "broker_cost_basis": round(basis_per_share, 4),
        "current_price": (
            round(current_price, 4) if current_price is not None else None
        ),
        # The dashboard payload does not currently surface a per-quote stale
        # flag; we mirror it as ``False`` here for forward compatibility and
        # the timestamp is "as of now" when a live price came back.
        "current_price_stale": False,
        "current_price_as_of": (
            datetime.now(timezone.utc).isoformat()
            if current_price is not None
            else None
        ),
    }


def _build_per_leg_breakdown(
    legs: list[dict],
    if_assigned_by_leg_id: dict[str, float | None],
) -> list[dict[str, Any]]:
    """Project the open-leg list onto the breakdown-row shape."""
    out: list[dict[str, Any]] = []
    for leg in legs:
        leg_id = str(leg["id"])
        out.append(
            {
                "leg_id": leg_id,
                "ticker": str(leg.get("ticker") or ""),
                "strike": float(leg.get("strike") or 0.0),
                "type": "call" if leg.get("type") == "call" else "put",
                "dte": int(leg.get("dte") or 0),
                "coverage": leg.get("coverage"),
                "pnl_dollars": leg.get("pnl_dollars"),
                "if_assigned_pnl": if_assigned_by_leg_id.get(leg_id),
            }
        )
    return out


def build_covered_call_view(
    db: DBSession,
    position_id: str,
) -> dict[str, Any] | None:
    """Build the combined-P&L + if-assigned payload for one position.

    Returns the response dict on success, or ``None`` when the position
    cannot be resolved — the router converts ``None`` to a 404.

    Raises on a Schwab quote / option-chain failure; the router wraps that
    in a generic 500 (no ``str(e)`` leak per CLAUDE.md).
    """
    position = journal.get_position(db, position_id)
    if position is None:
        return None

    rules = load_rules_config(db)
    ticker = position["ticker"]

    # Resolve the live price + option chain for this position's ticker only.
    client = SchwabClient()
    quote = client.get_quote(ticker)
    current_price_raw = quote.get("lastPrice") if isinstance(quote, dict) else None
    if current_price_raw is None and isinstance(quote, dict):
        current_price_raw = quote.get("mark")
    current_price = (
        float(current_price_raw) if current_price_raw is not None else None
    )
    chain = client.get_option_chain(ticker)
    marks = build_option_mark_index(
        {ticker: chain} if isinstance(chain, dict) else {}
    )

    open_legs = derive_open_legs(
        [position],
        {ticker: current_price},
        option_marks=marks,
        profit_review_pct=rules.management.profit_review_pct,
        dte_review_days=rules.management.dte_review_days,
        expiration_warning_days=rules.management.expiration_warning_days,
    )

    short_call_legs = [lg for lg in open_legs if lg.get("type") == "call"]

    applicability = _classify_applicability(position, short_call_legs)
    summary = _build_position_summary(position, current_price)

    # Empty payloads for not-applicable states — the frontend keys off the
    # applicability flag and renders the matching EmptyState. The position
    # block is still present so the header line can render.
    if applicability != "covered_call":
        return {
            "position": summary,
            "combined_today": {
                "stock_pnl": None,
                "options_pnl": None,
                "combined_pnl": None,
            },
            "if_assigned": [],
            "per_leg_breakdown": [],
            "applicability": applicability,
            "disclaimer": DISCLAIMER_TEXT,
        }

    basis_per_share = float(summary["broker_cost_basis"])
    shares = int(summary["shares"])

    combined_today = _compute_combined_today(
        shares=shares,
        current_price=current_price,
        basis=basis_per_share,
        legs=open_legs,
    )

    shares_called_map = _allocate_shares_called(short_call_legs, shares)
    if_assigned = _build_if_assigned(
        short_call_legs, shares_called_map, basis_per_share
    )

    # Build a leg_id → if_assigned_pnl map for the breakdown table. Legs not
    # present (a non-call or an expired call) get ``None`` in the breakdown.
    if_assigned_by_leg_id: dict[str, float | None] = {
        entry["leg_id"]: entry.get("if_assigned_pnl")
        for entry in if_assigned
    }
    per_leg_breakdown = _build_per_leg_breakdown(
        open_legs, if_assigned_by_leg_id
    )

    return {
        "position": summary,
        "combined_today": combined_today,
        "if_assigned": if_assigned,
        "per_leg_breakdown": per_leg_breakdown,
        "applicability": applicability,
        "disclaimer": DISCLAIMER_TEXT,
    }


__all__ = [
    "build_covered_call_view",
    "DISCLAIMER_TEXT",
    "_compute_combined_today",
    "_allocate_shares_called",
    "_build_if_assigned",
    "_classify_applicability",
]
