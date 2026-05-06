"""Dashboard router — single endpoint that composes the unified landing payload."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from app.models.database import get_db
from app.models.schemas import DashboardResponse
from app.services.dashboard import build_dashboard_payload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
def get_dashboard(db: DBSession = Depends(get_db)) -> DashboardResponse:
    """Return the composed dashboard payload in a single round-trip.

    Per CLAUDE.md, exception details are never echoed to clients — a generic
    500 message is returned and the underlying error is logged server-side.
    """
    try:
        return build_dashboard_payload(db)
    except Exception:  # noqa: BLE001 — last-resort wrapper before HTTP 500
        logger.exception("Failed to build dashboard payload")
        raise HTTPException(
            status_code=500,
            detail="Failed to load dashboard. Please try again.",
        )
