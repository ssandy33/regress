import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session as DBSession

from app.models.database import TradeEntryCompliance, get_db
from app.models.schemas import (
    POSITION_STATUS,
    ClearJournalResponse,
    EntryComplianceResponse,
    ImportPreviewResponse,
    ImportRequest,
    ImportResultResponse,
    PositionCreate,
    PositionListResponse,
    PositionResponse,
    PositionUpdate,
    ReconcilePositionDiff,
    ReconcileRequest,
    ReconcileResponse,
    TradeCreate,
    TradeResponse,
    TradeUpdate,
)
from app.services.journal import (
    clear_all_journal_data,
    create_position,
    create_trade,
    delete_position,
    delete_trade,
    get_position,
    get_positions,
    update_position,
    update_trade,
)
from app.services.reconcile import reconcile as reconcile_journal_state
from app.services.schwab_auth import SchwabAuthCode, SchwabAuthError
from app.services.schwab_client import SchwabClientError
from app.services.schwab_csv import parse_schwab_csv
from app.services.schwab_import import (
    build_preview,
    execute_import,
    execute_mapped_import,
    preview_import,
)

# Maximum CSV upload size; chosen to comfortably hold a year of transactions
# for an active wheel trader (~5,000 rows averaging well under 1 KB each).
_MAX_CSV_BYTES = 5 * 1024 * 1024
_CSV_SIZE_DETAIL = "CSV file is larger than the 5 MB limit"
_CSV_EXT_DETAIL = "Only .csv files are accepted"
_CSV_EMPTY_DETAIL = "Uploaded file is empty"
_CSV_PARSE_DETAIL = "Could not parse the uploaded CSV file"

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


@router.delete("/positions/{position_id}", status_code=204)
def delete_existing_position(position_id: str, db: DBSession = Depends(get_db)):
    """Remove a position and all of its child trades (cascade)."""
    try:
        deleted = delete_position(db, position_id)
    except Exception:
        logger.exception("Unexpected error while deleting position")
        raise HTTPException(status_code=500, detail="An unexpected error occurred")
    if not deleted:
        raise HTTPException(status_code=404, detail="Position not found")


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


@router.get(
    "/trades/{trade_id}/compliance",
    response_model=EntryComplianceResponse,
)
def get_trade_compliance(trade_id: str, db: DBSession = Depends(get_db)):
    """Return the entry-rule compliance row for a single trade (issue #160).

    404 when the trade has no compliance row — this covers both the
    unknown-trade and the out-of-scope-trade-type case (e.g. a
    ``buy_put_close`` row, which the evaluator never writes). The trade-
    not-found vs no-compliance-row distinction is collapsed to a single
    404 because the compliance API is downstream of the trade itself —
    consumers checking the compliance endpoint already know the trade
    exists; if they don't, they look it up on ``GET /trades/{id}`` first.
    """
    row = (
        db.query(TradeEntryCompliance)
        .filter(TradeEntryCompliance.trade_id == trade_id)
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=404, detail="Compliance row not found for trade"
        )
    import json as _json

    return EntryComplianceResponse(
        trade_id=row.trade_id,
        evaluated_at=row.evaluated_at,
        dte_at_entry=row.dte_at_entry,
        delta_at_entry=row.delta_at_entry,
        monthly_return_pct=row.monthly_return_pct,
        earnings_buffer_days=row.earnings_buffer_days,
        compliant=bool(row.compliant),
        failed_rules=(
            _json.loads(row.failed_rules) if row.failed_rules else []
        ),
        entry_rules_snapshot=(
            _json.loads(row.entry_rules_snapshot)
            if row.entry_rules_snapshot
            else {}
        ),
    )


@router.delete("/all", response_model=ClearJournalResponse)
def clear_all_journal(db: DBSession = Depends(get_db)):
    """Hard-delete every position and trade in a single transaction.

    Returns the number of rows wiped from each table. Mirrored on the Settings
    "Danger Zone" UI behind a type-DELETE confirmation guard.
    """
    try:
        result = clear_all_journal_data(db)
    except Exception:
        logger.exception("Unexpected error while clearing journal data")
        raise HTTPException(status_code=500, detail="An unexpected error occurred")
    return ClearJournalResponse(**result)


@router.post("/reconcile", response_model=ReconcileResponse)
def reconcile_journal(
    req: ReconcileRequest | None = None,
    db: DBSession = Depends(get_db),
):
    """Re-derive every Position's lifecycle state from the trade ledger.

    Backs the Settings → Reconcile journal action (issue #139). When
    ``req.dry_run`` is True (default) the recompute pass is rolled back at
    the end so the database is byte-for-byte unchanged; the response is a
    "what would change" preview. When ``dry_run`` is False, changes are
    committed and the response reports the actual writes performed.
    """
    request = req or ReconcileRequest()
    try:
        result = reconcile_journal_state(db, apply=not request.dry_run)
    except Exception:
        logger.exception("Unexpected error during journal reconciliation")
        raise HTTPException(status_code=500, detail="An unexpected error occurred")

    per_position = [
        ReconcilePositionDiff(
            ticker=diff.ticker,
            status_before=diff.status_before,
            status_after=diff.status_after,
            shares_before=diff.shares_before,
            shares_after=diff.shares_after,
            basis_before=diff.basis_before,
            basis_after=diff.basis_after,
            strategy_before=diff.strategy_before,
            strategy_after=diff.strategy_after,
            closed_at_before=diff.closed_at_before,
            closed_at_after=diff.closed_at_after,
            legs_consumed=diff.legs_consumed,
        )
        for diff in result.per_position
    ]
    return ReconcileResponse(
        dry_run=request.dry_run,
        positions_processed=result.positions_processed,
        trades_stamped=result.trades_stamped,
        status_changes=result.status_changes,
        share_corrections=result.share_corrections,
        basis_corrections=result.basis_corrections,
        strategy_changes=result.strategy_changes,
        errors=result.errors,
        per_position=per_position,
    )


@router.get("/import/preview", response_model=ImportPreviewResponse)
def import_preview(start_date: str, end_date: str, db: DBSession = Depends(get_db)):
    """Preview Schwab transactions available for import."""
    if not _is_valid_date(start_date) or not _is_valid_date(end_date):
        raise HTTPException(status_code=422, detail="Dates must be in YYYY-MM-DD format")
    if _date_range_exceeds_limit(start_date, end_date):
        raise HTTPException(status_code=422, detail="Date range cannot exceed 1 year (365 days)")
    try:
        return preview_import(db, start_date, end_date)
    except SchwabAuthError as e:
        logger.warning("Schwab auth failed during import preview: %s", e)
        raise HTTPException(status_code=401, detail=_schwab_auth_detail(e)) from e
    except SchwabClientError as e:
        logger.error("Schwab client error during import preview: %s", e)
        raise HTTPException(status_code=502, detail="Unable to fetch transactions from Schwab")
    except Exception:
        logger.exception("Unexpected error during import preview")
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


@router.post("/import", response_model=ImportResultResponse)
def import_transactions(req: ImportRequest, db: DBSession = Depends(get_db)):
    """Import Schwab transactions into the trade journal."""
    if not _is_valid_date(req.start_date) or not _is_valid_date(req.end_date):
        raise HTTPException(status_code=422, detail="Dates must be in YYYY-MM-DD format")
    if _date_range_exceeds_limit(req.start_date, req.end_date):
        raise HTTPException(status_code=422, detail="Date range cannot exceed 1 year (365 days)")
    try:
        # ``req.position_strategy`` is accepted on the request body for
        # backwards compatibility with old clients but ignored — the
        # recomputer derives the label per issue #131.
        return execute_import(db, req.start_date, req.end_date)
    except SchwabAuthError as e:
        logger.warning("Schwab auth failed during import: %s", e)
        raise HTTPException(status_code=401, detail=_schwab_auth_detail(e)) from e
    except SchwabClientError as e:
        logger.error("Schwab client error during import: %s", e)
        raise HTTPException(status_code=502, detail="Unable to fetch transactions from Schwab")
    except Exception:
        logger.exception("Unexpected error during import")
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


@router.post("/import/csv/preview", response_model=ImportPreviewResponse)
async def import_csv_preview(
    file: UploadFile = File(...),
    db: DBSession = Depends(get_db),
):
    """Preview options trades from a Schwab transaction CSV export.

    Mirrors the Schwab API preview path but reads from an uploaded CSV file.
    Use this when historical transactions predate the developer-app creation
    date and are therefore not returned by ``/api/journal/import/preview``.
    """
    file_bytes = await _read_csv_upload(file)
    try:
        mapped = parse_schwab_csv(file_bytes)
    except Exception:
        logger.exception("Failed to parse uploaded Schwab CSV")
        raise HTTPException(status_code=422, detail=_CSV_PARSE_DETAIL) from None
    return build_preview(db, mapped, account_number="")


@router.post("/import/csv", response_model=ImportResultResponse)
async def import_csv(
    file: UploadFile = File(...),
    db: DBSession = Depends(get_db),
):
    """Import options trades from a Schwab transaction CSV export.

    Per issue #131 the previously-required ``position_strategy`` form field
    has been removed; the strategy label is derived from each position's
    state by the recomputer. Stale clients that still post the field are
    tolerated — FastAPI ignores unrecognized form parameters.
    """
    file_bytes = await _read_csv_upload(file)
    try:
        mapped = parse_schwab_csv(file_bytes)
    except Exception:
        logger.exception("Failed to parse uploaded Schwab CSV")
        raise HTTPException(status_code=422, detail=_CSV_PARSE_DETAIL) from None
    return execute_mapped_import(db, mapped)


async def _read_csv_upload(file: UploadFile) -> bytes:
    """Validate and read a CSV upload, enforcing size + extension limits.

    Raises ``HTTPException`` 422 with a generic, user-safe detail if the file
    is missing, has the wrong extension, or exceeds the 5 MB cap. Never logs
    or returns the raw filename or contents.
    """
    if file is None or not file.filename:
        raise HTTPException(status_code=422, detail=_CSV_EXT_DETAIL)
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=422, detail=_CSV_EXT_DETAIL)

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=422, detail=_CSV_EMPTY_DETAIL)
    if len(contents) > _MAX_CSV_BYTES:
        raise HTTPException(status_code=422, detail=_CSV_SIZE_DETAIL)
    return contents


_AUTH_DETAIL_MAP: dict[SchwabAuthCode, str] = {
    SchwabAuthCode.TOKEN_EXPIRED: "Schwab token has expired. Please re-authorize in Settings.",
    SchwabAuthCode.REFRESH_FAILED_401: "Schwab token has expired. Please re-authorize in Settings.",
    SchwabAuthCode.API_401: "Schwab token has expired. Please re-authorize in Settings.",
    SchwabAuthCode.TOKEN_MISSING: "Schwab is not connected. Please authorize in Settings.",
    SchwabAuthCode.NOT_CONFIGURED: "Schwab app credentials are not configured. Please set up in Settings.",
}
_AUTH_DETAIL_FALLBACK = "Schwab authentication failed. Please re-authorize in Settings."


def _schwab_auth_detail(err: SchwabAuthError) -> str:
    """Return a user-friendly 401 detail based on the auth error code."""
    return _AUTH_DETAIL_MAP.get(err.code, _AUTH_DETAIL_FALLBACK)


def _is_valid_date(date_str: str) -> bool:
    """Check if a string is a valid YYYY-MM-DD date."""
    import re
    from datetime import date
    if not isinstance(date_str, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        return False
    try:
        date.fromisoformat(date_str)
        return True
    except (ValueError, TypeError):
        return False


def _date_range_exceeds_limit(start_date: str, end_date: str, max_days: int = 365) -> bool:
    """Check if a date range exceeds the maximum allowed days."""
    from datetime import date
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except (ValueError, TypeError):
        return False
    return (end - start).days > max_days
