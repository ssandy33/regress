"""OKR endpoints — V1 surface for the entry-compliance producer (#160).

This router is the API hand-off between the per-trade evaluator
(:mod:`app.services.entry_compliance`) and the future OKR engine (#157,
deferred). It ships with one route in V1 — the rolling-30d entry-compliance
summary — anticipating expansion when #157 lands.

Endpoint:

- ``GET /api/okrs/entry-compliance`` -> :class:`EntryComplianceListResponse`

Behavior:

- Returns the rolling-30-day window summary plus the non_compliant trades
  in that window.
- Never throws on an empty corpus (summary all zeros, ``compliant_pct=None``,
  ``non_compliant=[]``).
- Per CLAUDE.md API Contract: every route carries a ``response_model``;
  every response shape lives in :mod:`app.models.schemas`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from app.models.database import Trade, TradeEntryCompliance, get_db
from app.models.schemas import (
    EntryComplianceListResponse,
    EntryComplianceResponse,
)
from app.services.entry_compliance import compute_rolling_compliance
from app.services.rules_config import load_rules_config

router = APIRouter(prefix="/api/okrs", tags=["okrs"])

# Rolling window for the V1 endpoint. Pinned to 30 days per the Wave 3 plan
# §V1-Freeze-4 / §Edge-Cases-6; future expansion (7d / quarter) can come on
# query params without breaking the contract.
_ROLLING_WINDOW_DAYS: int = 30


def _row_to_response(row: TradeEntryCompliance) -> EntryComplianceResponse:
    """Translate a TradeEntryCompliance ORM row -> API response shape."""
    return EntryComplianceResponse(
        trade_id=row.trade_id,
        evaluated_at=row.evaluated_at,
        dte_at_entry=row.dte_at_entry,
        delta_at_entry=row.delta_at_entry,
        monthly_return_pct=row.monthly_return_pct,
        earnings_buffer_days=row.earnings_buffer_days,
        compliant=bool(row.compliant),
        failed_rules=json.loads(row.failed_rules) if row.failed_rules else [],
        entry_rules_snapshot=(
            json.loads(row.entry_rules_snapshot)
            if row.entry_rules_snapshot
            else {}
        ),
    )


@router.get("/entry-compliance", response_model=EntryComplianceListResponse)
def get_entry_compliance(db: DBSession = Depends(get_db)):
    """Rolling-30d entry-compliance summary + non-compliant trades.

    Captures ``now`` ONCE and threads it into both the summary computation and
    the non-compliant query so the two halves of the response always agree on
    the window boundary. Without this, a trade landing on the 30-day boundary
    can appear in ``non_compliant`` but not in the ``total`` denominator (or
    vice-versa) within the same response. CodeRabbit triage on PR #301.
    """
    rules = load_rules_config(db)
    now = datetime.now(timezone.utc)
    summary = compute_rolling_compliance(
        db, rules, window_days=_ROLLING_WINDOW_DAYS, now=now
    )
    # Non-compliant list = compliance rows in the same window with compliant=0.
    # We filter on Trade.opened_at + the compliant flag; failed_rules vs
    # unknown_only is implicit (compliant=1 covers both fully-compliant and
    # unknown-only verdicts per the evaluator's contract).
    cutoff_iso = (now - timedelta(days=_ROLLING_WINDOW_DAYS)).isoformat()
    now_iso = now.isoformat()
    non_compliant_rows = (
        db.query(TradeEntryCompliance)
        .join(Trade, TradeEntryCompliance.trade_id == Trade.id)
        .filter(Trade.opened_at >= cutoff_iso)
        .filter(Trade.opened_at <= now_iso)
        .filter(TradeEntryCompliance.compliant == 0)
        .all()
    )
    return EntryComplianceListResponse(
        summary=summary,
        non_compliant=[_row_to_response(r) for r in non_compliant_rows],
    )
