"""Research router — per-position stock research endpoints (issue #280).

Shared prefix ``/api/positions/{position_id}/research/...``. This file
houses the five GET endpoints + one PUT endpoint that compose Sections
A–F of the research page (PRD #282 / CTO plan
``backend/design-specs/issue-280-stock-research-plan.md``).

**Worker DAG convention.** v1.1.0 fans the page out across four parallel
backend workers (A/B/D/F) plus a bridging worker (W). Each worker
appends *its own* endpoint(s) at end-of-file in the order the CTO plan
freezes — A first, then B, D, F, then W's reconciliation pass. The
top-of-file imports stay alphabetized; the ``router`` object is shared.

Per CLAUDE.md every endpoint returns ``{"detail": "<sanitized message>"}``
on non-2xx and never propagates ``str(e)``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session as DBSession

from app.models.database import get_db
from app.services.research_price_history import (
    DEFAULT_WINDOW,
    SUPPORTED_WINDOWS,
    InvalidWindowError,
    PriceHistoryResponse,
    PriceSourceUnavailableError,
    build_price_history,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/positions", tags=["research"])


# Generic 500 detail per CLAUDE.md — never leak ``str(e)``.
_GENERIC_500_DETAIL = "Failed to load research data. Please try again."


# ---------------------------------------------------------------------------
# Section B + C — Price history with basis lines + trade markers + earnings
# (Worker B — issue #280)
# ---------------------------------------------------------------------------


@router.get(
    "/{position_id}/research/price-history",
    response_model=PriceHistoryResponse,
)
def get_price_history(
    position_id: str,
    window: str = Query(
        DEFAULT_WINDOW,
        description=(
            "Lookback window. v1 only renders 1Y; 6M and 2Y are accepted for "
            "forwards-compatibility with the deferred picker."
        ),
    ),
    db: DBSession = Depends(get_db),
):
    """Compose the research price-history payload for one position.

    Combines four sources into a single payload (see CTO plan §3.5):

    - Daily close prices over the window from the existing data fetcher
    - Broker + adjusted basis lines from the Position row + journal recompute
    - User-recorded trade events from the position's ledger
    - Past earnings reporting dates from Alpha Vantage's ``EARNINGS`` function

    Cached in-process for 15 minutes (NFR-7).

    Error mapping:

    - ``404`` — position not found
    - ``422`` — unsupported ``window`` value
    - ``502`` — price source (Schwab/yfinance) unavailable
    - ``500`` — unexpected internal error (generic detail, sanitized log)
    """
    try:
        response = build_price_history(db, position_id, window)
    except InvalidWindowError:
        # Detail intentionally lists the supported set so the frontend
        # (and curl users) can self-correct without reading server logs.
        return JSONResponse(
            status_code=422,
            content={
                "detail": (
                    f"Unsupported window. Supported values: "
                    f"{sorted(SUPPORTED_WINDOWS)}"
                )
            },
        )
    except PriceSourceUnavailableError:
        # The service layer logged the underlying cause at WARNING.
        return JSONResponse(
            status_code=502,
            content={"detail": "Price source unavailable"},
        )
    except Exception as exc:  # noqa: BLE001 — generic 500 per CLAUDE.md
        logger.error(
            "Research price-history composition failed for position=%s "
            "window=%s: %s",
            position_id,
            window,
            exc,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": _GENERIC_500_DETAIL},
        )

    if response is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Position not found"},
        )

    return response


# ---------------------------------------------------------------------------
# Section A — Business snapshot (Worker A — issue #280)
# ---------------------------------------------------------------------------
# Section D — Financial scorecard (Worker A — issue #280)
# ---------------------------------------------------------------------------
# Section E — Regression decomposition (Worker D — issue #280)
# ---------------------------------------------------------------------------
# Section F — Thesis note (Worker F — issue #280)
# ---------------------------------------------------------------------------
#
# Sibling workers append their endpoints below in the order shown above.
# Top-of-file imports stay alphabetized.
