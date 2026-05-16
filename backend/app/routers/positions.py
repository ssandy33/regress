"""Positions router — Recovery Plan endpoint (issue #182).

Single route: ``POST /api/positions/{position_id}/recovery-plan``. Composes
the position fetch + live quote + OKR settings + path engine + scoring
layer into the unified ``RecoveryPlanResponse`` shape.

Branch shape:

- 404 — ``Position not found``
- ``state == "not-applicable"`` — option-only positions (``shares == 0``)
  or closed positions; engine never runs.
- ``state == "not-flagged"`` — position above the review threshold (-5% or
  -$1,000); engine never runs. Returned with the position summary so the
  frontend can render the EmptyState.
- ``state == "populated"`` — full payload with paths + recommendation.
- 500 — Schwab quote failure. Generic detail message per CLAUDE.md; no
  ``str(e)`` leaks.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session as DBSession

from app.models.database import AppSetting, get_db
from app.models.schemas import RecoveryPlanResponse
from app.services import journal
from app.services.recovery_engine import (
    DEFAULT_SIZING_CAP_DOLLARS,
    WHEEL_MONTHLY_PREMIUM_PCT,
    compute_recovery_paths,
)
from app.services.recovery_scoring import DISCLAIMER_TEXT, score_recovery_paths
from app.services.schwab_client import SchwabClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/positions", tags=["positions"])

# Largest-loser flag thresholds — must mirror
# :mod:`app.services.action_engine` so the dashboard CTA and the recovery
# page agree on what "flagged" means.
LARGE_LOSER_PCT_THRESHOLD: float = -0.05
LARGE_LOSER_DOLLAR_THRESHOLD: float = -1000.0

# Cost-basis-zero positions can't be meaningfully underwater (recovery
# math divides by basis-derived inputs); short-circuit to not-applicable.
MIN_COST_BASIS_FOR_RECOVERY: float = 0.01

# Generic 500 detail per CLAUDE.md — never leak ``str(e)``.
GENERIC_RECOVERY_500_DETAIL = (
    "Failed to build recovery plan. Please try again."
)


def _get_app_setting(db: DBSession, key: str) -> str | None:
    """Read a single ``app_settings`` row by key. ``None`` when missing."""
    entry = db.query(AppSetting).filter(AppSetting.key == key).first()
    return entry.value if entry else None


def _read_okr_settings(db: DBSession) -> dict[str, Any]:
    """Read OKR scoring inputs from ``app_settings`` with defaults.

    Keys live alongside the existing ``cache_ttl_*`` keys and are
    populated by #156/#157 when that work lands. Defaults documented in the
    plan §5:

    - ``okr_target_yield`` → ``None`` (suppresses sell-redeploy)
    - ``okr_sizing_cap_dollars`` → :data:`DEFAULT_SIZING_CAP_DOLLARS`
    - ``okr_strategy_preference`` → ``None`` (dormant bonus row in V0.5.8)
    """
    target_raw = _get_app_setting(db, "okr_target_yield")
    cap_raw = _get_app_setting(db, "okr_sizing_cap_dollars")
    pref_raw = _get_app_setting(db, "okr_strategy_preference")

    target_yield: float | None
    sizing_cap: float

    try:
        target_yield = float(target_raw) if target_raw not in (None, "") else None
    except (TypeError, ValueError):
        target_yield = None

    try:
        sizing_cap = (
            float(cap_raw) if cap_raw not in (None, "") else DEFAULT_SIZING_CAP_DOLLARS
        )
    except (TypeError, ValueError):
        sizing_cap = DEFAULT_SIZING_CAP_DOLLARS

    strategy_preference = pref_raw if pref_raw not in (None, "") else None

    return {
        "target_yield": target_yield,
        "sizing_cap_dollars": sizing_cap,
        "strategy_preference": strategy_preference,
    }


def _build_position_summary(
    position: dict,
    current_price: float | None,
    *,
    cost_basis: float | None = None,
) -> dict:
    """Compute the header summary the frontend renders above the cards.

    ``cost_basis`` is the effective basis the caller resolved (adjusted
    basis with a ``broker_cost_basis`` fallback). When omitted, the same
    fallback is applied here so the P/L math never silently drops to
    ``None`` for a position that has only a broker basis.
    """
    shares = int(position.get("shares") or 0)
    if cost_basis is not None:
        effective_basis = float(cost_basis)
    else:
        effective_basis = float(
            position.get("adjusted_cost_basis")
            or position.get("broker_cost_basis")
            or 0.0
        )
    notional = (current_price or 0.0) * shares
    if shares > 0 and effective_basis > 0:
        unrealized_pl = notional - effective_basis
        pl_pct = unrealized_pl / effective_basis
    else:
        unrealized_pl = None
        pl_pct = None
    return {
        "id": position["id"],
        "ticker": position["ticker"],
        "shares": shares,
        "adjusted_cost_basis": effective_basis,
        "current_price": current_price,
        "unrealized_pl": unrealized_pl,
        "pl_pct": pl_pct,
    }


def _is_flagged(unrealized_pl: float | None, pl_pct: float | None) -> bool:
    """Mirror the action-engine flag rule: either threshold trips it."""
    if unrealized_pl is None:
        return False
    if unrealized_pl <= LARGE_LOSER_DOLLAR_THRESHOLD:
        return True
    if pl_pct is not None and pl_pct <= LARGE_LOSER_PCT_THRESHOLD:
        return True
    return False


def _format_pct(value: float | None) -> str:
    if value is None:
        return "Not set"
    return f"{value * 100:.0f}%"


def _format_dollar(value: float | None) -> str:
    if value is None:
        return "Not set"
    return f"${value:,.0f}"


def _build_assumptions_panel(
    okr: dict[str, Any],
    current_price: float | None,
) -> list[dict]:
    """Build the 6-row Assumptions audit panel from the response inputs."""
    price_str = (
        f"${current_price:,.2f}" if isinstance(current_price, (int, float)) else "Unknown"
    )
    return [
        {
            "label": "Premium rate (Wheel)",
            "value": f"{WHEEL_MONTHLY_PREMIUM_PCT * 100:.1f}% / month",
            "source": "V0.5.8 heuristic (#183 V0.7)",
        },
        {
            "label": "Target yield (Sell & redeploy)",
            "value": _format_pct(okr.get("target_yield")),
            "source": "Settings → OKRs",
        },
        {
            "label": "Sizing cap (Average down)",
            "value": _format_dollar(okr.get("sizing_cap_dollars")),
            "source": "Settings → OKRs",
        },
        {
            "label": "Strategy preference",
            "value": okr.get("strategy_preference") or "Not set",
            "source": "Settings → OKRs (V0.6)",
        },
        {
            "label": "Current price",
            "value": price_str,
            "source": "Schwab quote",
        },
        {
            "label": "Tax / wash sale",
            "value": "Not modeled",
            "source": "User responsibility",
        },
    ]


@router.post("/{position_id}/recovery-plan", response_model=RecoveryPlanResponse)
def build_recovery_plan(
    position_id: str,
    db: DBSession = Depends(get_db),
):
    """Compose the Recovery Plan response for a single position.

    Wires the deterministic engine + scoring pieces together. No LLM,
    single Schwab quote, generic error message on failure.
    """
    position = journal.get_position(db, position_id)
    if position is None:
        return JSONResponse(
            status_code=404, content={"detail": "Position not found"}
        )

    as_of = datetime.now(timezone.utc).isoformat()

    # Branch: option-only / closed / zero-cost-basis → not-applicable.
    shares = int(position.get("shares") or 0)
    cost_basis = float(position.get("adjusted_cost_basis") or 0.0)
    if cost_basis <= MIN_COST_BASIS_FOR_RECOVERY:
        cost_basis = float(position.get("broker_cost_basis") or 0.0)
    if (
        shares <= 0
        or position.get("status") == "closed"
        or cost_basis <= MIN_COST_BASIS_FOR_RECOVERY
    ):
        return RecoveryPlanResponse(
            position_id=position_id,
            as_of=as_of,
            state="not-applicable",
            position=None,
            inputs=None,
            paths=[],
            recommendation=None,
            assumptions=[],
            disclaimer=DISCLAIMER_TEXT,
        )

    # Live quote — broad-exception guard so we never propagate ``str(e)``
    # to the client per CLAUDE.md.
    try:
        quote = SchwabClient().get_quote(position["ticker"])
        current_price_raw = quote.get("lastPrice")
        if current_price_raw is None or float(current_price_raw) <= 0:
            raise ValueError("Schwab quote missing usable lastPrice")
        current_price = float(current_price_raw)
    except Exception as exc:  # noqa: BLE001 — generic 500 per CLAUDE.md
        logger.error(
            "Recovery plan quote fetch failed for %s (%s): %s",
            position_id,
            position.get("ticker"),
            exc,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": GENERIC_RECOVERY_500_DETAIL},
        )

    summary = _build_position_summary(position, current_price, cost_basis=cost_basis)
    if not _is_flagged(summary["unrealized_pl"], summary["pl_pct"]):
        return RecoveryPlanResponse(
            position_id=position_id,
            as_of=as_of,
            state="not-flagged",
            position=summary,
            inputs=None,
            paths=[],
            recommendation=None,
            assumptions=[],
            disclaimer=DISCLAIMER_TEXT,
        )

    okr = _read_okr_settings(db)

    paths = compute_recovery_paths(
        position=position,
        current_price=current_price,
        target_yield=okr["target_yield"],
        sizing_cap_dollars=okr["sizing_cap_dollars"],
    )
    recommendation = score_recovery_paths(paths, okr)
    assumptions = _build_assumptions_panel(okr, current_price)

    return RecoveryPlanResponse(
        position_id=position_id,
        as_of=as_of,
        state="populated",
        position=summary,
        inputs={
            "current_price": current_price,
            "cost_basis": cost_basis,
            "shares": shares,
            "okr": okr,
        },
        paths=paths,
        recommendation=recommendation,
        assumptions=assumptions,
        disclaimer=DISCLAIMER_TEXT,
    )
