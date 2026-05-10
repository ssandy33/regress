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

The looping/diff logic lives in :func:`app.services.reconcile.reconcile` so
the same pass backs the in-app Settings → Reconcile journal action (issue
#139). This module is a thin CLI wrapper that renders the structured
``ReconcileResult`` to stdout in the format users have come to expect.

Exit codes:
    0  success (or dry-run completed)
    1  one or more positions raised during recomputation; details logged
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy.orm import Session

from app.models.database import Position, SessionLocal
from app.services.reconcile import ReconcilePositionDiff, reconcile

logger = logging.getLogger(__name__)


def _format_diff(diff: ReconcilePositionDiff) -> str | None:
    """Return a one-line diff string, or None if before == after.

    Mirrors the pre-#139 stdout format so users (and the CLI tests) see the
    exact same output as before the service-layer extraction.
    """
    parts: list[str] = []
    if diff.status_before != diff.status_after:
        parts.append(f"status {diff.status_before} -> {diff.status_after}")
    if diff.shares_before != diff.shares_after:
        parts.append(f"shares {diff.shares_before} -> {diff.shares_after}")
    if diff.basis_before != diff.basis_after:
        parts.append(
            f"basis ${diff.basis_before:.2f} -> ${diff.basis_after:.2f}"
        )
    if diff.closed_at_before != diff.closed_at_after:
        parts.append(
            f"closed_at {diff.closed_at_before!r} -> {diff.closed_at_after!r}"
        )
    if diff.strategy_before != diff.strategy_after:
        parts.append(f"strategy {diff.strategy_before} -> {diff.strategy_after}")
    if not parts:
        return None
    return f"  {diff.ticker:<8} {', '.join(parts)}"


def reconcile_all(db: Session, apply: bool) -> tuple[int, int, int]:
    """Recompute every Position and report changes.

    Thin wrapper around :func:`app.services.reconcile.reconcile` that
    renders the structured result to stdout and returns the legacy tuple
    shape ``(total, changed, errors)`` so existing callers / tests continue
    to work unchanged.

    Args:
        db: SQLAlchemy session bound to the journal database.
        apply: If True, commit all changes. If False, the service rolls
            back at the end so the database is untouched.

    Returns:
        ``(total, changed, errors)`` — count of positions walked, count
        whose derived state differed from before, and count that raised
        during recomputation.
    """
    # Count positions up front so the header line ("Reconciling N
    # positions...") matches the historical output even though the loop
    # itself now lives in the service.
    total = db.query(Position).count()
    print(f"Reconciling {total} positions{' (DRY RUN)' if not apply else ''}...")

    result = reconcile(db, apply=apply)

    for diff in result.per_position:
        line = _format_diff(diff)
        if line is not None:
            print(line)

    changed = result.changed
    errors = result.errors

    if apply:
        print(
            f"\n{result.positions_processed} positions, {changed} changed, "
            f"{errors} errors. Applied."
        )
    else:
        print(
            f"\n{result.positions_processed} positions, {changed} would change, "
            f"{errors} errors.\n"
            "Re-run with --apply to commit."
        )
    return result.positions_processed, changed, errors


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
