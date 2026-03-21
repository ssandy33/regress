import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from app.models.database import get_db
from app.models.schemas import (
    POSITION_STATUS,
    ImportPreviewResponse,
    ImportRequest,
    ImportResultResponse,
    PositionCreate,
    PositionListResponse,
    PositionResponse,
    PositionUpdate,
    TradeCreate,
    TradeResponse,
    TradeUpdate,
)
from app.services.journal import (
    create_position,
    create_trade,
    delete_trade,
    get_position,
    get_positions,
    update_position,
    update_trade,
)
from app.services.schwab_auth import SchwabAuthError
from app.services.schwab_client import SchwabClientError
from app.services.schwab_import import execute_import, preview_import

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/journal", tags=["journal"])


@router.get("/positions", response_model=PositionListResponse)
def list_positions(status: Optional[POSITION_STATUS] = None, db: DBSession = Depends(get_db)):
    """List all positions, optionally filtered by status."""
    results = get_positions(db, status=status)
    return PositionListResponse(positions=results)


@router.get("/positions/{position_id}", response_model=PositionResponse)
def get_position_by_id(position_id: str, db: DBSession = Depends(get_db)):
    """Get a single position with trade history and computed fields."""
    result = get_position(db, position_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Position not found")
    return result


@router.post("/positions", response_model=PositionResponse, status_code=201)
def create_new_position(req: PositionCreate, db: DBSession = Depends(get_db)):
    """Create a new position."""
    return create_position(db, req)


@router.put("/positions/{position_id}", response_model=PositionResponse)
def update_existing_position(position_id: str, req: PositionUpdate, db: DBSession = Depends(get_db)):
    """Update an existing position."""
    result = update_position(db, position_id, req)
    if result is None:
        raise HTTPException(status_code=404, detail="Position not found")
    return result


@router.post("/trades", response_model=TradeResponse, status_code=201)
def create_new_trade(req: TradeCreate, db: DBSession = Depends(get_db)):
    """Log a trade against a position."""
    result = create_trade(db, req)
    if result is None:
        raise HTTPException(status_code=404, detail="Position not found")
    return result


@router.put("/trades/{trade_id}", response_model=TradeResponse)
def update_existing_trade(trade_id: str, req: TradeUpdate, db: DBSession = Depends(get_db)):
    """Update an existing trade."""
    result = update_trade(db, trade_id, req)
    if result is None:
        raise HTTPException(status_code=404, detail="Trade not found")
    return result


@router.delete("/trades/{trade_id}", status_code=204)
def delete_existing_trade(trade_id: str, db: DBSession = Depends(get_db)):
    """Remove a trade."""
    if not delete_trade(db, trade_id):
        raise HTTPException(status_code=404, detail="Trade not found")


@router.get("/import/preview", response_model=ImportPreviewResponse)
def import_preview(start_date: str, end_date: str, db: DBSession = Depends(get_db)):
    """Preview Schwab transactions available for import."""
    if not _is_valid_date(start_date) or not _is_valid_date(end_date):
        raise HTTPException(status_code=422, detail="Dates must be in YYYY-MM-DD format")
    try:
        return preview_import(db, start_date, end_date)
    except SchwabAuthError as e:
        logger.warning("Schwab auth failed during import preview: %s", e)
        raise HTTPException(status_code=401, detail=_schwab_auth_detail(e)) from e
    except SchwabClientError:
        raise HTTPException(status_code=502, detail="Unable to fetch transactions from Schwab")
    except Exception:
        logger.exception("Unexpected error during import preview")
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


@router.post("/import", response_model=ImportResultResponse)
def import_transactions(req: ImportRequest, db: DBSession = Depends(get_db)):
    """Import Schwab transactions into the trade journal."""
    try:
        return execute_import(db, req.start_date, req.end_date, req.position_strategy)
    except SchwabAuthError as e:
        logger.warning("Schwab auth failed during import: %s", e)
        raise HTTPException(status_code=401, detail=_schwab_auth_detail(e)) from e
    except SchwabClientError:
        raise HTTPException(status_code=502, detail="Unable to fetch transactions from Schwab")
    except Exception:
        logger.exception("Unexpected error during import")
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


def _schwab_auth_detail(err: SchwabAuthError) -> str:
    """Return a user-friendly 401 detail based on the auth error."""
    msg = str(err).lower()
    if "expired" in msg:
        return "Schwab token has expired. Please re-authorize in Settings."
    if "no schwab refresh token" in msg:
        return "Schwab is not connected. Please authorize in Settings."
    if "not configured" in msg:
        return "Schwab app credentials are not configured. Please set up in Settings."
    return "Schwab authentication failed. Please re-authorize in Settings."


def _is_valid_date(date_str: str) -> bool:
    """Check if a string matches YYYY-MM-DD format."""
    import re
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", date_str))
