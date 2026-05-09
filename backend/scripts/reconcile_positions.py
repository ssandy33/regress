"""One-shot reconciliation tool: re-derive every Position's lifecycle state.

Walks the entire ``positions`` table and runs
:func:`app.services.positions.recompute_position_state` against each row, then
prints a per-ticker before/after diff. Provides a fix path for journals that
were imported before issue #127 was fixed (every imported position stuck at
``status="open"``, ``shares=100``, ``broker_cost_basis=0.0``) and for journals
imported before issue #131 (every imported position stuck on the
batch-applied strategy label rather than a derived one).

Usage::

    python -m scripts.reconcile_positions               # dry run (default)
    python -m scripts.reconcile_positions --apply       # commit changes
    make reconcile-positions ARGS=--apply               # via Makefile

The script is **opt-in** — it is never invoked automatically. Running it with
``--apply`` rewrites the ``status`` / ``shares`` / ``broker_cost_basis`` /
``closed_at`` / ``strategy`` columns of every Position; review the dry-run
diff first.

Exit codes:
    0  success (or dry-run completed)
    1  one or more positions raised during recomputation; details logged
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.database import Position, SessionLocal
from app.services.positions import recompute_position_state

logger = logging.getLogger(__name__)


@dataclass
class _Snapshot:
    """Capture of a Position's derived state at a point in time."""

    status: str
    shares: int
    broker_cost_basis: float
    closed_at: str | None
    strategy: str


def _snapshot(position: Position) -> _Snapshot:
    """Capture the derived columns of a Position into a comparable record."""
    return _Snapshot(
        status=position.status,
        shares=int(position.shares or 0),
        broker_cost_basis=float(position.broker_cost_basis or 0.0),
        closed_at=position.closed_at,
        strategy=position.strategy or "",
    )


def _format_diff(ticker: str, before: _Snapshot, after: _Snapshot) -> str | None:
    """Return a one-line diff string, or None if the snapshots are equal."""
    if before == after:
        return None
    parts: list[str] = []
    if before.status != after.status:
        parts.append(f"status {before.status} -> {after.status}")
    if before.shares != after.shares:
        parts.append(f"shares {before.shares} -> {after.shares}")
    if before.broker_cost_basis != after.broker_cost_basis:
        parts.append(
            f"basis ${before.broker_cost_basis:.2f} -> ${after.broker_cost_basis:.2f}"
        )
    if before.closed_at != after.closed_at:
        parts.append(f"closed_at {before.closed_at!r} -> {after.closed_at!r}")
    if before.strategy != after.strategy:
        parts.append(f"strategy {before.strategy} -> {after.strategy}")
    return f"  {ticker:<8} {', '.join(parts)}"


def reconcile_all(db: Session, apply: bool) -> tuple[int, int, int]:
    """Recompute every Position and report changes.

    Args:
        db: SQLAlchemy session bound to the journal database.
        apply: If True, commit all changes. If False, roll back at the end so
            the database is untouched.

    Returns:
        ``(total, changed, errors)`` — count of positions walked, count whose
        derived state differed from before, and count that raised during
        recomputation.
    """
    positions = db.query(Position).all()
    total = len(positions)
    changed = 0
    errors = 0

    print(f"Reconciling {total} positions{' (DRY RUN)' if not apply else ''}...")

    for position in positions:
        ticker = position.ticker
        before = _snapshot(position)
        try:
            recompute_position_state(db, position.id, commit=apply)
        except Exception:
            errors += 1
            logger.exception(
                "Failed to recompute position %s (%s)", position.id, ticker
            )
            continue
        # In dry-run mode the recomputer left the changes uncommitted on the
        # ORM object; we can read them directly. In apply mode it already
        # refreshed the row.
        after = _snapshot(position)
        diff = _format_diff(ticker, before, after)
        if diff is not None:
            changed += 1
            print(diff)

    if apply:
        print(f"\n{total} positions, {changed} changed, {errors} errors. Applied.")
    else:
        # Discard all uncommitted in-memory mutations so the database is
        # untouched. Each recompute call set position.shares / .status / ...
        # without committing — rollback drops them.
        db.rollback()
        print(
            f"\n{total} positions, {changed} would change, {errors} errors.\n"
            "Re-run with --apply to commit."
        )
    return total, changed, errors


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Re-derive Position lifecycle state (status / shares / "
            "broker_cost_basis / closed_at) from the trade ledger."
        )
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--apply",
        action="store_true",
        help="Commit changes. Without this flag, the script runs in dry-run mode.",
    )
    group.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Default. Print diff without committing.",
    )
    args = parser.parse_args(argv)

    apply = bool(args.apply)

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    db = SessionLocal()
    try:
        _total, _changed, errors = reconcile_all(db, apply=apply)
    finally:
        db.close()
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
