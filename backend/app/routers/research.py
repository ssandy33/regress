"""Research router — per-position stock research endpoints (issue #280).

Shared prefix ``/api/positions/{position_id}/research/...``. This file
houses the GET endpoints + one PUT endpoint that compose Sections A–F
of the research page (PRD #282 / CTO plan
``backend/design-specs/issue-280-stock-research-plan.md``).

**Worker DAG convention.** v1.1.0 fans the page out across four parallel
backend workers (A/B/D/F) plus a bridging worker (W). Each worker
appends *its own* endpoint(s) at end-of-file in the order the CTO plan
freezes — A first, then B, D, F, then W's reconciliation pass. The
top-of-file imports stay alphabetized; the ``router`` object is shared.

Per CLAUDE.md every endpoint returns ``{"detail": "<sanitized message>"}``
on non-2xx and never propagates ``str(e)``. Thesis endpoints re-raise
``HTTPException`` directly (FastAPI emits the same sanitized shape);
other endpoints prefer ``JSONResponse`` so the response body shape is
uniform across error paths.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session as DBSession

from app.models.database import get_db
from app.models.schemas import ThesisPutRequest, ThesisResponse
from app.services import journal
from app.services.cache import CacheService
from app.services.data_fetcher import DataFetcher
from app.services.research_price_history import (
    DEFAULT_WINDOW,
    SUPPORTED_WINDOWS,
    InvalidWindowError,
    PriceHistoryResponse,
    PriceSourceUnavailableError,
    build_price_history,
)
from app.services.research_regression import (
    DEFAULT_WINDOW as REGRESSION_DEFAULT_WINDOW,
    InsufficientRegressionDataError,
    RegressionSourceUnavailableError,
    ResearchRegressionResponse,
    get_regression_for_position,
    validate_window as validate_regression_window,
)
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


def _get_fetcher(db: DBSession = Depends(get_db)) -> DataFetcher:
    """Construct a :class:`DataFetcher` bound to this request's DB session."""
    return DataFetcher(CacheService(db))


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
# Section F — Thesis note (Worker F — issue #280)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Section E — Regression decomposition (Worker D — issue #280)
# ---------------------------------------------------------------------------


@router.get(
    "/{position_id}/research/regression",
    response_model=ResearchRegressionResponse,
)
def research_regression(
    position_id: str,
    window: str = Query(default=REGRESSION_DEFAULT_WINDOW),
    db: DBSession = Depends(get_db),
    fetcher: DataFetcher = Depends(_get_fetcher),
):
    """Compose the regression decomposition for a single position.

    Pulls 1-year daily prices for the position's ticker, SPY, the position's
    sector ETF (if mappable), and the FRED 10-year yield, then runs the
    existing multi-factor OLS engine and returns the factor betas, p-values,
    variance shares, R², and a plain-English summary string.

    Status codes:

    - ``200`` — success
    - ``404`` — position not found
    - ``422`` — ``window`` invalid OR fewer than 60 aligned trading days
    - ``502`` — an upstream price/yield source was unavailable
    - ``500`` — unexpected internal error (sanitized message per CLAUDE.md)
    """
    # Validate the window query param first — produces a 422 with a
    # sanitized message rather than a 500 if a caller passes garbage.
    try:
        validate_regression_window(window)
    except ValueError:
        return JSONResponse(
            status_code=422,
            content={"detail": "Unsupported window value"},
        )

    position = journal.get_position(db, position_id)
    if position is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Position not found"},
        )

    ticker = position["ticker"]

    try:
        response = get_regression_for_position(
            position_id=position_id,
            ticker=ticker,
            window=window,
            fetcher=fetcher,
        )
    except InsufficientRegressionDataError:
        return JSONResponse(
            status_code=422,
            content={"detail": "Insufficient data for regression"},
        )
    except RegressionSourceUnavailableError:
        return JSONResponse(
            status_code=502,
            content={"detail": "Source unavailable for regression"},
        )
    except Exception:  # noqa: BLE001 — generic 500 per CLAUDE.md
        logger.exception(
            "Unexpected error composing regression for position %s", position_id
        )
        return JSONResponse(
            status_code=500,
            content={"detail": _GENERIC_500_DETAIL},
        )

    return response


# ---------------------------------------------------------------------------
# Section A — Business snapshot (Worker A — issue #280)
# ---------------------------------------------------------------------------
# Section D — Financial scorecard (Worker A — issue #280)
# ---------------------------------------------------------------------------
#
# Worker A landed service modules (research_business / research_financials)
# in this release without router shells. Worker W is responsible for adding
# the matching ``GET /research/business`` and ``GET /research/financials``
# endpoints that wire those services to the prefix above.
