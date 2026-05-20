"""Covered-call router — the per-position combined-P&L endpoint (issue #247).

Single route: ``GET /api/positions/{position_id}/covered-call``. Feeds the
dedicated combined-P&L + if-assigned screen — the per-position analog of
the per-leg buy-to-close screen (#244, ``routers/legs.py``).

Branch shape:

- 404 — ``Position not found`` — unknown position id.
- 200 — :class:`CoveredCallView`. The ``applicability`` discriminator drives
  the frontend's state machine: ``"covered_call"`` for the populated view,
  the three ``not_applicable_*`` buckets for the EmptyState branches.
- 500 — generic ``Failed to load combined P&L. Please try again.`` on
  Schwab / option-chain failure. Never leaks ``str(e)`` (CLAUDE.md).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session as DBSession

from app.models.database import get_db
from app.models.schemas import CoveredCallView
from app.services.covered_call import build_covered_call_view

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/positions", tags=["covered_call"])

# Generic 500 detail per CLAUDE.md — never leak ``str(e)``.
GENERIC_COVERED_CALL_500_DETAIL = (
    "Failed to load combined P&L. Please try again."
)


@router.get(
    "/{position_id}/covered-call",
    response_model=CoveredCallView,
)
def get_covered_call_view(
    position_id: str,
    db: DBSession = Depends(get_db),
):
    """Return the combined-P&L + if-assigned payload for one position.

    Composes the position summary, the today (unrealized) block, the
    if-assigned per-leg projections, and the per-leg breakdown rows. The
    ``applicability`` discriminator distinguishes the populated view from
    the three not-applicable empty-state branches. 404 for an unknown
    position id.
    """
    try:
        view = build_covered_call_view(db, position_id)
    except Exception as exc:  # noqa: BLE001 — generic 500 per CLAUDE.md
        logger.error(
            "Covered-call view build failed for position %s: %s",
            position_id,
            exc,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": GENERIC_COVERED_CALL_500_DETAIL},
        )

    if view is None:
        return JSONResponse(
            status_code=404, content={"detail": "Position not found"}
        )

    return view
