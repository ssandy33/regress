"""Dashboard router — single endpoint that composes the unified landing payload."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session as DBSession

from app.models.database import get_db
from app.models.schemas import DashboardResponse
from app.services.dashboard import build_dashboard_payload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
def get_dashboard(
    response: Response,
    db: DBSession = Depends(get_db),
) -> DashboardResponse:
    """Return the composed dashboard payload in a single round-trip.

    Per CLAUDE.md, exception details are never echoed to clients — a generic
    500 message is returned and the underlying error is logged server-side.
    """
    # Issue #367 — set ``Cache-Control: no-store`` so the Next standalone proxy
    # and the browser never serve a previously-fetched body. The dashboard is
    # fetched client-side via axios and proxied to this route by Next's
    # ``rewrites()``; without this header the proxy/browser were free to return
    # a stale payload after a QA reseed. The header is the canonical fix; the
    # deploy-time ``qa-frontend`` restart (ADR #359 D4) is now redundant
    # belt-and-suspenders, retained intentionally and removable in a future
    # cleanup. Header-only change — the response body and ``response_model``
    # are unchanged, so no OpenAPI snapshot regen is needed (kept out of the
    # docstring on purpose: FastAPI emits docstrings into the OpenAPI snapshot).
    response.headers["Cache-Control"] = "no-store"
    try:
        return build_dashboard_payload(db)
    except Exception:  # noqa: BLE001 — last-resort wrapper before HTTP 500
        logger.exception("Failed to build dashboard payload")
        raise HTTPException(
            status_code=500,
            detail="Failed to load dashboard. Please try again.",
        )
