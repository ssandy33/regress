"""Positions router — Recovery Plan endpoint (issue #182).

Single route: ``POST /api/positions/{position_id}/recovery-plan``. Composes
the position fetch + live quote + OKR settings + path engine + scoring
layer into the unified ``RecoveryPlanResponse`` shape.

Branch shape:

- 404 — ``Position not found``
- ``state == "not-applicable"`` — option-only positions (``shares == 0``)
  or closed positions; engine never runs.
- ``state == "not-flagged"`` — position above the review threshold; engine
  never runs. The percentage threshold is the configured
  ``rules_config.risk.loss_review_threshold_pct`` (Trading Rules Layer,
  issue #156); the -$1,000 dollar trigger is a retained absolute-loss floor.
  Returned with the position summary so the frontend can render the
  EmptyState.
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
    WHEEL_MONTHLY_PREMIUM_PCT,
    compute_recovery_paths,
)
from app.services.rules_config import RulesConfig, load_rules_config
from app.services.recovery_scoring import DISCLAIMER_TEXT, score_recovery_paths
from app.services.schwab_account_value import get_cached_account_value
from app.services.schwab_client import SchwabClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/positions", tags=["positions"])

# Largest-loser dollar flag threshold. The *percentage* side of the flag
# gate is the configured ``rules_config.risk.loss_review_threshold_pct``
# (Trading Rules Layer, issue #156) — resolved per-request and passed into
# :func:`_is_flagged`. This dollar threshold is an intentionally-retained
# absolute-loss secondary OR-trigger: PRD #209 §R5 models the loss-review
# rule as a percentage only, so a large-share position with a shallow
# percentage loss still flags on absolute dollars. It is a hardcoded
# heuristic, not a trader-facing rule (ADR-002), and must mirror
# :mod:`app.services.action_engine` so the dashboard CTA and the recovery
# page agree on what "flagged" means.
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


def _read_okr_settings(db: DBSession, rules: RulesConfig) -> dict[str, Any]:
    """Read the recovery-engine scoring inputs from settings.

    Two of these are OKR reads on flat ``app_settings`` keys (ADR-001: target
    yield and strategy preference are OKRs):

    - ``okr_target_yield`` → ``None`` (suppresses sell-redeploy)
    - ``okr_strategy_preference`` → ``None`` (dormant bonus row in V0.5.8)

    Sizing cap (issue #234, V1 contract)
    ------------------------------------
    The sizing cap is **no longer** a stored dollar amount and is **not** an
    ``okr_*`` flat key. Per ADR-001 it is a Trading Rule, so the percent
    (``rules.position.sizing_cap_pct``) and the multi-account selector
    (``rules.position.sizing_cap_account``) come from the resolved
    :class:`RulesConfig`.

    Resolving ``total_capital`` follows a three-tier precedence:

    1. ``okr_total_capital`` flat app-setting (W-D test-friendly override —
       lets fixture-driven tests pin a capital value without standing up the
       full Schwab account-value cache).
    2. :func:`get_cached_account_value` on the connected Schwab account —
       **cache-hit-only**: this function is on the hot path and never blocks
       on a Schwab round-trip. The GET ``/api/settings/account-value``
       endpoint owns the network fall-through.
    3. Catalog default of ``$20,000`` so the recovery engine has a
       resolvable ceiling on a fresh install before Schwab is connected.

    ``capital_status`` mirrors the cache result's status when resolved from
    the cache; the flat-setting / default paths emit ``"ok"`` so the
    recovery engine treats the cap as enforceable.
    """
    target_raw = _get_app_setting(db, "okr_target_yield")
    pref_raw = _get_app_setting(db, "okr_strategy_preference")

    target_yield: float | None
    try:
        target_yield = float(target_raw) if target_raw not in (None, "") else None
    except (TypeError, ValueError):
        target_yield = None

    strategy_preference = pref_raw if pref_raw not in (None, "") else None

    # Sizing cap comes from rules_config (issue #156 / #234), not an okr_*
    # flat key.
    sizing_cap_pct = rules.position.sizing_cap_pct
    sizing_cap_account = rules.position.sizing_cap_account

    total_capital: float | None = None
    account_id_masked: str | None = None
    capital_status: str = "ok"

    # Tier 1 — test-friendly flat app-setting override (see W-D contract).
    # Pin a capital value without standing up the Schwab account-value
    # cache; if the value is malformed we fall through to tier 2.
    flat_capital_raw = _get_app_setting(db, "okr_total_capital")
    if flat_capital_raw not in (None, ""):
        try:
            total_capital = float(flat_capital_raw)
        except (TypeError, ValueError):
            total_capital = None

    # Tier 2 — cached Schwab account value (cache-hit-only, no network).
    # ``None`` from the cache means "no fresh entry" (we never warmed it);
    # the GET /api/settings/account-value endpoint owns the network
    # fall-through. A non-ok ``AccountValueResult`` is the explicit
    # cap-unenforceable signal — surface its status so the assumption
    # panel can render the "account value unavailable" copy.
    if total_capital is None:
        account_value_result = get_cached_account_value(
            db, sizing_cap_account=sizing_cap_account
        )
        if account_value_result is not None:
            if account_value_result.status == "ok":
                total_capital = account_value_result.total_capital
                account_id_masked = account_value_result.account_id_masked
                capital_status = "ok"
            else:
                # disconnected / expired / error → cap unenforceable.
                account_id_masked = account_value_result.account_id_masked
                capital_status = account_value_result.status

    # Tier 3 — catalog default so a fresh install (no flat setting, no
    # cache row at all) still resolves to an enforceable ceiling. Only
    # applies when neither tier 1 nor tier 2 produced a value AND tier 2
    # didn't return an explicit failure status.
    if total_capital is None and capital_status == "ok":
        total_capital = 20000.0

    resolved_sizing_cap_dollars = (
        sizing_cap_pct * total_capital / 100 if total_capital is not None else None
    )

    return {
        "target_yield": target_yield,
        "strategy_preference": strategy_preference,
        "sizing_cap_pct": sizing_cap_pct,
        "total_capital": total_capital,
        "resolved_sizing_cap_dollars": resolved_sizing_cap_dollars,
        "account_id_masked": account_id_masked,
        "capital_status": capital_status,
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


def _is_flagged(
    unrealized_pl: float | None,
    pl_pct: float | None,
    loss_review_threshold_pct: float,
) -> bool:
    """Decide whether a position is flagged for a recovery plan.

    Mirrors the action-engine largest-loser rule: either trigger trips it.

    - ``loss_review_threshold_pct`` is the configured
      ``rules_config.risk.loss_review_threshold_pct`` — a *whole-percent*
      value (e.g. ``-15.0`` for −15%). ``pl_pct`` is a *fraction* (e.g.
      ``-0.15``), so the threshold is divided by 100 before comparison.
    - :data:`LARGE_LOSER_DOLLAR_THRESHOLD` is the retained absolute-loss
      secondary OR-trigger.
    """
    if unrealized_pl is None:
        return False
    if unrealized_pl <= LARGE_LOSER_DOLLAR_THRESHOLD:
        return True
    if pl_pct is not None and pl_pct <= loss_review_threshold_pct / 100.0:
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


def _format_sizing_cap(okr: dict[str, Any]) -> str:
    """Format the sizing-cap assumption-row value.

    Mirrors the recovery-engine assumption text (issue #234 §6.2 contract):

    - ``"ok"`` → ``"25% (≈ $5,000)"`` — percent and the resolved dollar
      ceiling so the user sees the math.
    - ``"disconnected" / "expired" / "error"`` → ``"25% — Schwab account
      value unavailable"`` — the cap-unenforceable state surfaced
      explicitly per the §6.2 contract.
    """
    pct = okr.get("sizing_cap_pct")
    if not isinstance(pct, (int, float)):
        return "Not set"
    if okr.get("capital_status") == "ok":
        resolved = okr.get("resolved_sizing_cap_dollars")
        return f"{pct:.0f}% (≈ {_format_dollar(resolved)})"
    return f"{pct:.0f}% — Schwab account value unavailable"


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
            "value": _format_sizing_cap(okr),
            "source": "Settings → Trading Rules",
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

    # Resolve the Trading Rules config once (issue #156) — the flag gate's
    # loss-review threshold and the sizing cap both come from it.
    rules = load_rules_config(db)

    summary = _build_position_summary(position, current_price, cost_basis=cost_basis)
    if not _is_flagged(
        summary["unrealized_pl"],
        summary["pl_pct"],
        rules.risk.loss_review_threshold_pct,
    ):
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

    okr = _read_okr_settings(db, rules)

    paths = compute_recovery_paths(
        position=position,
        current_price=current_price,
        target_yield=okr["target_yield"],
        sizing_cap_pct=okr["sizing_cap_pct"],
        total_capital=okr["total_capital"],
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
