"""QA DB-snapshot selection helper (issue #330).

The QA refresh script (``deploy/qa-refresh-db.sh``) seeds the QA SQLite volume
from the newest prod backup snapshot written by ``deploy/backup.sh``
(``backups/regression_tool_<timestamp>.db``). The snapshot-selection logic
lives here as a pure function so it is unit-testable without docker or a real
volume — the shell script is a thin wrapper that shells out to
``python -m scripts.qa_snapshot <backup_dir>`` and uses the printed path.

The restore itself is intentionally an *in-place overwrite* of the single
``regression_tool.db`` file inside the QA volume — it never accumulates copies
(the box runs disk-constrained). Re-running is idempotent: the same snapshot
selection yields the same source, and the copy clobbers rather than appends.

Usage::

    python -m scripts.qa_snapshot /root/regress/backups
    # prints the absolute path of the newest regression_tool_*.db, or exits 1
"""

from __future__ import annotations

import sys
from pathlib import Path

SNAPSHOT_GLOB = "regression_tool_*.db"


def select_newest_snapshot(backup_dir: str | Path) -> Path:
    """Return the newest ``regression_tool_*.db`` snapshot in ``backup_dir``.

    "Newest" is by filesystem mtime (the timestamp embedded in the filename is
    monotonic with mtime in practice, but mtime is the authoritative ordering
    and is robust to clock-format changes in ``backup.sh``).

    Raises:
        FileNotFoundError: if ``backup_dir`` does not exist or contains no
            matching snapshot. The caller (shell script) surfaces this as a
            clear "no snapshot found — run deploy/backup.sh first" error.
    """
    directory = Path(backup_dir)
    if not directory.is_dir():
        raise FileNotFoundError(f"Backup directory does not exist: {directory}")

    snapshots = sorted(
        directory.glob(SNAPSHOT_GLOB),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not snapshots:
        raise FileNotFoundError(
            f"No {SNAPSHOT_GLOB} snapshot found in {directory} "
            "— run deploy/backup.sh first."
        )
    return snapshots[0].resolve()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m scripts.qa_snapshot <backup_dir>", file=sys.stderr)
        return 2
    try:
        print(select_newest_snapshot(args[0]))
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
