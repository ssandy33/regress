"""Buy-to-close leg detail service (issue #244).

Composes the per-leg buy-to-close (BTC) detail payload for the new
``GET /api/positions/{position_id}/legs/{leg_id}/btc`` endpoint. The screen
is the per-leg analog of the per-position recovery screen.

Reuse over re-implementation (plan §4.3):

- The §R6 rule audit is **not** re-evaluated here. This service reuses the
  whole :func:`app.services.dashboard_legs.derive_open_legs` path — the
  exact function the dashboard service calls — which itself calls
  :func:`app.services.rule_monitor.evaluate_leg_rules` per leg. The
  ``triggered_rules`` / ``verdict`` this endpoint returns are therefore
  byte-identical to what the dashboard renders for the same leg: no drift
  is possible by construction.
- The only genuinely new computation is the BTC economics block
  (:func:`_build_economics`) — and even there ``captured_pct`` is *lifted*
  from the leg's ``profit_target_status`` rather than recomputed, so it
  agrees with the dashboard ``% CAPT`` column.

The single Schwab fetch (one quote + one option chain for the position's
ticker) is fully guarded by the caller (the router) — this service raises on
fetch failure and the router converts it to a generic 500 per CLAUDE.md.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.services import journal
from app.services.dashboard_legs import build_option_mark_index, derive_open_legs
from app.services.rules_config import load_rules_config
from app.services.schwab_client import SchwabClient

logger = logging.getLogger(__name__)

# Persistent disclaimer footer copy — BTC-specific, shipped in the payload so
# the frontend renders it the same way the recovery screen renders its
# disclaimer (spec §6 / §4.2).
DISCLAIMER_TEXT: str = (
    "This buy-to-close review reports what your own Management Triggers said "
    "about this leg and the mechanical economics of closing it. It is not "
    "trading advice. Option mid prices are estimates, may be stale, and "
    "exclude commissions; the decision to buy to close is yours."
)

# Maps the position's derived strategy label to the human context phrase used
# in the leg header sub-line. Unknown strategies fall back to "position".
_STRATEGY_LABEL: dict[str, str] = {
    "csp": "cash-secured put",
    "cc": "covered call",
    "wheel": "wheel",
    "holding": "holding",
}


def _moneyness_label(leg: dict) -> str:
    """Return the leg's moneyness state, or 'Unknown' when no live price."""
    moneyness = leg.get("moneyness")
    if isinstance(moneyness, dict) and moneyness.get("state"):
        return str(moneyness["state"])
    return "Unknown"


def _position_label(position: dict) -> str:
    """Compose ``"{ticker} {strategy phrase}"`` for the header sub-line."""
    ticker = position.get("ticker", "")
    strategy = str(position.get("strategy") or "").lower()
    phrase = _STRATEGY_LABEL.get(strategy, "position")
    return f"{ticker} {phrase}".strip()


def _build_economics(leg: dict) -> dict[str, Any]:
    """Compute the buy-to-close economics block for one leg.

    All money figures are whole-position dollars (per-share value × contracts
    × 100). ``credit_received`` is always real; the pricing-dependent fields
    degrade to ``None`` when no live option mark is available (spec §5.3 Q4).

    ``captured_pct`` is lifted straight off ``profit_target_status`` — the
    identical value the dashboard ``% CAPT`` column shows — never recomputed.
    """
    contracts = int(leg.get("quantity") or 1)
    premium = leg.get("premium")  # per-share opening credit
    current_mid = leg.get("current_mid")  # per-share, None ⇒ no live mark

    # The opening credit is static — always real, even with no live pricing.
    credit_received = round(float(premium or 0.0) * contracts * 100, 2)

    if current_mid is None:
        return {
            "credit_received": credit_received,
            "current_option_mid": None,
            "cost_to_close": None,
            "captured_pct": None,
            "est_pl_if_closed": None,
            "pricing_as_of": None,
            "pricing_source": "unavailable",
        }

    cost_to_close = round(float(current_mid) * contracts * 100, 2)
    # Lift captured_pct from the already-computed % CAPT signal — agree by
    # construction with the dashboard column (spec §10 note 2).
    captured_pct = (leg.get("profit_target_status") or {}).get("captured_pct")
    est_pl_if_closed = round(credit_received - cost_to_close, 2)
    return {
        "credit_received": credit_received,
        "current_option_mid": round(float(current_mid), 4),
        "cost_to_close": cost_to_close,
        "captured_pct": captured_pct,
        "est_pl_if_closed": est_pl_if_closed,
        "pricing_as_of": datetime.now(timezone.utc).isoformat(),
        "pricing_source": "live",
    }


def _reshape_leg(leg: dict, position: dict) -> dict[str, Any]:
    """Reshape the internal ``derive_open_legs`` leg dict into the API ``leg``."""
    return {
        "id": str(leg["id"]),
        "position_id": str(leg["position_id"]),
        "ticker": leg["ticker"],
        "strike": float(leg["strike"]),
        "option_type": "P" if leg.get("type") == "put" else "C",
        "contracts": int(leg.get("quantity") or 1),
        "expiration": str(leg["expiration"])[:10],
        "dte": int(leg["dte"]),
        "moneyness": _moneyness_label(leg),
        "position_label": _position_label(position),
    }


def build_btc_detail(
    db: DBSession,
    position_id: str,
    leg_id: str,
) -> dict[str, Any] | None:
    """Build the buy-to-close detail payload for one open leg.

    Returns the response dict on success, or ``None`` when the leg cannot be
    resolved (unknown / closed leg, or a leg that belongs to a different
    position) — the router converts ``None`` to a 404.

    Raises on a Schwab quote / option-chain failure; the router wraps that in
    a generic 500 (no ``str(e)`` leak, per CLAUDE.md).
    """
    position = journal.get_position(db, position_id)
    if position is None:
        return None

    rules = load_rules_config(db)
    ticker = position["ticker"]

    # Resolve the live price + option chain for THIS position's ticker only.
    # A single quote + single chain — far cheaper than the dashboard fan-out.
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

    leg = next(
        (l for l in open_legs if str(l["id"]) == str(leg_id)), None
    )
    if leg is None:
        # Unknown leg, closed leg, or a leg that belongs to a different
        # position — derive_open_legs only yields open legs of this position.
        return None

    economics = _build_economics(leg)
    verdict = leg.get("verdict") or "hold"
    state = "no-rule-triggered" if verdict == "hold" else "populated"

    return {
        "state": state,
        "leg": _reshape_leg(leg, position),
        "verdict": verdict,
        "economics": economics,
        "triggered_rules": leg.get("triggered_rules") or [],
        "disclaimer": DISCLAIMER_TEXT,
    }


__all__ = ["build_btc_detail", "DISCLAIMER_TEXT"]
