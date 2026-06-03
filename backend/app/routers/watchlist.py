"""Watchlist router — the approved-underlying universe API (issue #321).

Three endpoints under ``/api/watchlist`` back PRD #213 R2–R4:

- ``GET  /api/watchlist``           — list the current watchlist.
- ``POST /api/watchlist``           — add a ticker (idempotent, normalized).
- ``DELETE /api/watchlist/{ticker}``— remove a ticker (idempotent).

Every route returns the full, current watchlist as :class:`WatchlistResponse`
so a caller never needs a follow-up read after a mutation. Per CLAUDE.md the
routes never surface ``str(e)`` — an unexpected persistence error is logged
via ``logger.exception`` and collapsed to a generic ``500``. Adding a duplicate
or removing a missing ticker is a documented no-op (returns ``200`` with the
unchanged list), not a ``409``/``404``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from app.models.database import get_db
from app.models.schemas import WatchlistAddRequest, WatchlistResponse
from app.services.watchlist import add_ticker, list_watchlist, remove_ticker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

# Generic 500 detail per CLAUDE.md — never leak ``str(e)``.
_GENERIC_500_DETAIL = "An unexpected error occurred"


@router.get("", response_model=WatchlistResponse)
def get_watchlist(db: DBSession = Depends(get_db)) -> WatchlistResponse:
    """Return the current watchlist of approved underlyings."""
    try:
        tickers = list_watchlist(db)
    except Exception:
        logger.exception("Unexpected error while listing watchlist")
        raise HTTPException(status_code=500, detail=_GENERIC_500_DETAIL)
    return WatchlistResponse(tickers=tickers)


@router.post("", response_model=WatchlistResponse)
def add_watchlist_ticker(
    req: WatchlistAddRequest, db: DBSession = Depends(get_db)
) -> WatchlistResponse:
    """Add a ticker to the watchlist; idempotent and uppercase-normalized.

    The ``ticker`` is normalized + validated by :class:`WatchlistAddRequest`,
    so a blank ticker is rejected with ``422`` before reaching this handler.
    """
    try:
        tickers = add_ticker(db, req.ticker)
    except Exception:
        logger.exception("Unexpected error while adding watchlist ticker")
        raise HTTPException(status_code=500, detail=_GENERIC_500_DETAIL)
    return WatchlistResponse(tickers=tickers)


@router.delete("/{ticker}", response_model=WatchlistResponse)
def delete_watchlist_ticker(
    ticker: str, db: DBSession = Depends(get_db)
) -> WatchlistResponse:
    """Remove a ticker from the watchlist; idempotent.

    The path parameter is normalized the same way as on add, so
    ``DELETE /api/watchlist/aapl`` removes ``AAPL``. Removing a ticker that is
    not present is a no-op that returns ``200`` with the unchanged list.
    """
    try:
        tickers = remove_ticker(db, ticker)
    except Exception:
        logger.exception("Unexpected error while removing watchlist ticker")
        raise HTTPException(status_code=500, detail=_GENERIC_500_DETAIL)
    return WatchlistResponse(tickers=tickers)
