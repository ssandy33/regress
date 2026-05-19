"""Legs router — the per-leg buy-to-close detail endpoint (issue #244).

Single route: ``GET /api/positions/{position_id}/legs/{leg_id}/btc``. Feeds
the dedicated buy-to-close (BTC) leg detail screen — the per-leg analog of
the per-position recovery screen.

Branch shape:

- 404 — ``Leg not found`` — unknown / closed leg, or a leg that belongs to a
  different position.
- 200 — :class:`BtcDetailResponse`. ``state == "no-rule-triggered"`` when the
  leg's §R6 verdict is ``hold``; ``state == "populated"`` when a rule fired.
- 500 — generic ``Failed to load buy-to-close detail. Please try again.`` on
  Schwab / option-chain failure. Never leaks ``str(e)`` (CLAUDE.md).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session as DBSession

from app.models.database import get_db
from app.models.schemas import BtcDetailResponse
from app.services.btc_detail import build_btc_detail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/positions", tags=["legs"])

# Generic 500 detail per CLAUDE.md — never leak ``str(e)``.
GENERIC_BTC_500_DETAIL = "Failed to load buy-to-close detail. Please try again."


@router.get(
    "/{position_id}/legs/{leg_id}/btc",
    response_model=BtcDetailResponse,
)
def get_btc_detail(
    position_id: str,
    leg_id: str,
    db: DBSession = Depends(get_db),
):
    """Return the buy-to-close detail payload for one open option leg.

    Composes the leg identity, the §R6 rule-monitor verdict + audit (reused
    verbatim from the dashboard's ``derive_open_legs`` path), and the
    buy-to-close economics block. 404 for an unknown / closed leg.
    """
    try:
        detail = build_btc_detail(db, position_id, leg_id)
    except Exception as exc:  # noqa: BLE001 — generic 500 per CLAUDE.md
        logger.error(
            "Buy-to-close detail build failed for position %s leg %s: %s",
            position_id,
            leg_id,
            exc,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": GENERIC_BTC_500_DETAIL},
        )

    if detail is None:
        return JSONResponse(
            status_code=404, content={"detail": "Leg not found"}
        )

    return detail
