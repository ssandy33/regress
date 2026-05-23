"""Per-position research router (issue #280).

Hosts the ``/api/positions/{position_id}/research/...`` endpoints for the
new Stock Research page. Workers A/B/D/F contribute one endpoint each
(disjoint by section). This file is a multi-worker landing zone — each
worker appends its endpoint at the position locked by the implementation
plan. Worker W reconciles the response models into ``schemas.py`` at the
end of the fan-out.

Section ownership (plan §5):

- Section A (business)         → Worker A
- Section B+C (price history)  → Worker B
- Section D (financials)       → Worker A
- Section E (regression)       → Worker D  ← this file's contribution
- Section F (thesis)           → Worker F
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session as DBSession

from app.models.database import get_db
from app.services import journal
from app.services.cache import CacheService
from app.services.data_fetcher import DataFetcher
from app.services.research_regression import (
    DEFAULT_WINDOW,
    InsufficientRegressionDataError,
    RegressionSourceUnavailableError,
    ResearchRegressionResponse,
    get_regression_for_position,
    validate_window,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/positions", tags=["research"])


def _get_fetcher(db: DBSession = Depends(get_db)) -> DataFetcher:
    """Construct a :class:`DataFetcher` bound to this request's DB session."""
    return DataFetcher(CacheService(db))


# --- Section E — regression decomposition (Worker D) ----------------------


@router.get(
    "/{position_id}/research/regression",
    response_model=ResearchRegressionResponse,
)
def research_regression(
    position_id: str,
    window: str = Query(default=DEFAULT_WINDOW),
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
        validate_window(window)
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
            content={
                "detail": "Failed to load research data. Please try again."
            },
        )

    return response
