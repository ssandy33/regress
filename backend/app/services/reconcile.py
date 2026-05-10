"""Structured-result reconciliation service.

Walks every Position, calls
:func:`app.services.positions.recompute_position_state` against each row, and
returns a structured before/after diff suitable for both:

* the CLI (``backend/scripts/reconcile_positions.py``), which renders the
  diffs to stdout; and
* the HTTP route (``POST /api/journal/reconcile``), which serializes the
  diff to JSON for the Settings UI (issue #139).

The recomputer is idempotent — calling :func:`reconcile` twice on the same
ledger yields the same final state — which is what makes the dry-run /
apply distinction safe to expose.

When ``apply=False`` the function calls ``db.rollback()`` at the end so any
in-memory mutations made by ``recompute_position_state(..., commit=False)``
are discarded; the database is byte-for-byte unchanged. The HTTP layer
relies on this behavior to support the Preview action without persisting
anything (issue #139, AC-1).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.database import Position, Trade
from app.services.positions import recompute_position_state

logger = logging.getLogger(__name__)


@dataclass
class ReconcilePositionDiff:
    """Per-position before/after snapshot of the recompute pass."""

    ticker: str
    status_before: str
    status_after: str
    shares_before: int
    shares_after: int
    basis_before: float
    basis_after: float
    strategy_before: str
    strategy_after: str
    closed_at_before: str | None
    closed_at_after: str | None
    # Number of ``Trade.closed_at`` writes performed by *this* invocation
    # against this position. Counts the delta of Trades whose ``closed_at``
    # was None before and is non-None after (issue #139 — "delta of unstamped
    # legs on this run only", per the CTO plan).
    legs_consumed: int


@dataclass
class ReconcileResult:
    """Aggregate counts plus per-position diffs returned by :func:`reconcile`."""

    positions_processed: int = 0
    trades_stamped: int = 0
    status_changes: int = 0
    share_corrections: int = 0
    basis_corrections: int = 0
    strategy_changes: int = 0
    errors: int = 0
    per_position: list[ReconcilePositionDiff] = field(default_factory=list)

    @property
    def changed(self) -> int:
        """Count of positions whose derived state differed from before.

        Used by the CLI to render its existing one-line summary; not
        exposed on the HTTP response (the per-field aggregates are richer).
        """
        return sum(
            1
            for diff in self.per_position
            if (
                diff.status_before != diff.status_after
                or diff.shares_before != diff.shares_after
                or diff.basis_before != diff.basis_after
                or diff.strategy_before != diff.strategy_after
                or diff.closed_at_before != diff.closed_at_after
            )
        )


def _trade_closes_snapshot(position: Position) -> dict[str, str | None]:
    """Capture each Trade's ``closed_at`` value for the position.

    Used to count how many Trade rows had ``closed_at`` written by this
    recompute pass — the ``legs_consumed`` semantics defined in #139.
    """
    return {trade.id: trade.closed_at for trade in position.trades}


def reconcile(db: Session, apply: bool) -> ReconcileResult:
    """Recompute every Position and return a structured before/after summary.

    Args:
        db: SQLAlchemy session bound to the journal database.
        apply: If True, commit all changes. If False, roll back at the end so
            the database is untouched and the caller can render the result
            as a "what would change" preview.

    Returns:
        :class:`ReconcileResult` with aggregate counts and a per-position
        diff list. ``ReconcileResult.errors`` is non-zero if any position
        raised during recomputation; the helper continues across the rest of
        the journal so a single bad row doesn't block the whole pass.
    """
    positions = db.query(Position).all()
    result = ReconcileResult(positions_processed=len(positions))

    for position in positions:
        ticker = position.ticker
        # Snapshot before-state.
        before_status = position.status
        before_shares = int(position.shares or 0)
        before_basis = float(position.broker_cost_basis or 0.0)
        before_strategy = position.strategy or ""
        before_closed_at = position.closed_at
        before_trade_closes = _trade_closes_snapshot(position)

        try:
            # ``commit=apply`` keeps dry-run mutations in-memory; the
            # rollback at the end discards them.
            recompute_position_state(db, position.id, commit=apply)
        except Exception:
            result.errors += 1
            logger.exception(
                "Failed to recompute position %s (%s)", position.id, ticker
            )
            continue

        # Snapshot after-state. In dry-run mode the recomputer leaves changes
        # uncommitted on the ORM object; in apply mode it has already
        # refreshed the row.
        after_status = position.status
        after_shares = int(position.shares or 0)
        after_basis = float(position.broker_cost_basis or 0.0)
        after_strategy = position.strategy or ""
        after_closed_at = position.closed_at

        # Count Trade.closed_at writes performed by this invocation: a row
        # whose closed_at went from None to a value. ``position.trades`` is
        # the same collection both before and after recompute — the trades'
        # ``closed_at`` attributes are mutated in place.
        legs_consumed = 0
        for trade in position.trades:
            before_value = before_trade_closes.get(trade.id)
            after_value = trade.closed_at
            if before_value is None and after_value is not None:
                legs_consumed += 1

        diff = ReconcilePositionDiff(
            ticker=ticker,
            status_before=before_status,
            status_after=after_status,
            shares_before=before_shares,
            shares_after=after_shares,
            basis_before=before_basis,
            basis_after=after_basis,
            strategy_before=before_strategy,
            strategy_after=after_strategy,
            closed_at_before=before_closed_at,
            closed_at_after=after_closed_at,
            legs_consumed=legs_consumed,
        )
        result.per_position.append(diff)

        # Update aggregates.
        result.trades_stamped += legs_consumed
        if before_status != after_status:
            result.status_changes += 1
        if before_shares != after_shares:
            result.share_corrections += 1
        if before_basis != after_basis:
            result.basis_corrections += 1
        if before_strategy != after_strategy:
            result.strategy_changes += 1

    if apply:
        # ``recompute_position_state(commit=True)`` already committed each
        # row individually; nothing extra to do here. Calling commit again
        # is a no-op but kept defensively in case future code paths add
        # post-loop writes.
        db.commit()
    else:
        # Discard all uncommitted in-memory mutations so the database is
        # untouched. Each recompute call set position.shares / .status /
        # Trade.closed_at without committing — rollback drops them.
        db.rollback()

    return result
