"""Research router — per-position stock research page (issue #280).

This file is shared across the four backend workers in the v1.1.0
fan-out (A: business + financials, B: price history + earnings,
D: regression, F: thesis). Each worker appends its own endpoints
here without modifying its siblings'. Worker W performs the final
wire-up in :mod:`app.main` after all sibling workers merge.

Worker F (this commit) owns the thesis endpoints:

- ``GET  /api/positions/{position_id}/research/thesis``
- ``PUT  /api/positions/{position_id}/research/thesis``

Both error contracts follow CLAUDE.md: never leak ``str(e)`` — sanitized
``{"detail": "..."}`` payloads only.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from app.models.database import get_db
from app.models.schemas import ThesisPutRequest, ThesisResponse
from app.services.research_thesis import (
    PositionNotFoundError,
    ThesisTooLongError,
    get_thesis,
    put_thesis,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/positions", tags=["research"])


# Generic 500 detail per CLAUDE.md — never leak ``str(e)``.
_GENERIC_500_DETAIL = "Failed to load research data. Please try again."


@router.get(
    "/{position_id}/research/thesis",
    response_model=ThesisResponse,
)
def read_thesis(
    position_id: str, db: DBSession = Depends(get_db)
) -> ThesisResponse:
    """Return the saved thesis for a position or the empty-state shape.

    Empty state (``thesis=None``, ``version=0``) is returned when the
    position exists but no thesis has been written yet — the frontend
    renders the editor immediately rather than a 404. A truly missing
    position id still returns ``404`` with a sanitized message.
    """
    try:
        return get_thesis(db, position_id)
    except PositionNotFoundError:
        raise HTTPException(status_code=404, detail="Position not found")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error reading thesis for %s", position_id)
        raise HTTPException(status_code=500, detail=_GENERIC_500_DETAIL)


@router.put(
    "/{position_id}/research/thesis",
    response_model=ThesisResponse,
)
def write_thesis(
    position_id: str,
    payload: ThesisPutRequest,
    db: DBSession = Depends(get_db),
) -> ThesisResponse:
    """Upsert the thesis body and return the new row.

    Version is incremented on every successful write. Pydantic enforces
    the 4000-character cap on the request model; the service layer
    re-validates and the router translates the overflow to ``422``.
    Position-not-found maps to ``404``.
    """
    try:
        return put_thesis(db, position_id, payload.thesis)
    except PositionNotFoundError:
        raise HTTPException(status_code=404, detail="Position not found")
    except ThesisTooLongError:
        # Sanitized — never leak str(e). The cap is part of the public
        # contract; surfacing it in the detail message is intentional.
        raise HTTPException(
            status_code=422,
            detail="Thesis exceeds 4000 character limit",
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error writing thesis for %s", position_id)
        raise HTTPException(status_code=500, detail=_GENERIC_500_DETAIL)
