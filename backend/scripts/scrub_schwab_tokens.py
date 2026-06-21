"""Pre-start Schwab-token scrub for QA (root-cause fix for #379).

QA runs with ``SCHWAB_ENCRYPTION_KEY`` unset. The backend's fail-closed startup
check (:func:`app.main._run_security_checks`) refuses to boot when the sensitive
``schwab_*`` token rows exist in ``app_settings`` without the key — crash-looping
the container and taking all QA ``/api/*`` to 502 behind Caddy (#379).

The #380 scrub lives in :func:`app.services.seed_qa._full_reset`, which runs via
``docker compose exec qa-backend ...`` — and ``exec`` needs a *running*
container. Once the tokens are present the backend cannot stay up, so the
exec-based scrub can never fire: a deadlock. This module breaks it. It is
invoked from a one-off container BEFORE ``compose up -d`` (see
``deploy/qa-scrub-schwab-tokens.sh``), connects straight to the SQLite file via
stdlib ``sqlite3``, and never imports the FastAPI app or triggers the security
check — so it works even when the long-running backend cannot boot.

The key list is :data:`app.services.encryption.ENCRYPTED_SETTING_KEYS` — the same
source of truth as the startup check and the #380 seed scrub, so the three can
never drift.

Idempotent: a missing ``app_settings`` table (a fresh QA volume, before the
backend's ``init_db`` has run) or zero matching rows is a no-op that returns 0.

Usage (inside the backend container, cwd ``/app``):
    python -m scripts.scrub_schwab_tokens [db_path]
"""

from __future__ import annotations

import sqlite3
import sys

from app.services.encryption import ENCRYPTED_SETTING_KEYS

# The QA volume mounts the SQLite DB here (docker-compose.qa.yml:
# DATABASE_URL=sqlite:///./data/regression_tool.db, WORKDIR /app).
DEFAULT_DB_PATH = "/app/data/regression_tool.db"


def scrub_schwab_tokens(db_path: str = DEFAULT_DB_PATH) -> int:
    """Delete the sensitive ``schwab_*`` token rows from ``app_settings``.

    Returns the number of rows deleted. A missing ``app_settings`` table is
    treated as "nothing to scrub" (returns 0) so the scrub is safe to run
    against a freshly-created QA volume before the backend's ``init_db``.

    Only the keys in :data:`ENCRYPTED_SETTING_KEYS` are removed —
    ``schwab_*_expires`` / ``schwab_account_value`` and all other settings are
    preserved (they do not trip the startup security check).
    """
    conn = sqlite3.connect(db_path)
    try:
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='app_settings'"
        ).fetchone()
        if not table_exists:
            return 0
        keys = sorted(ENCRYPTED_SETTING_KEYS)
        placeholders = ",".join("?" for _ in keys)
        cur = conn.execute(
            f"DELETE FROM app_settings WHERE key IN ({placeholders})", keys
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    db_path = args[0] if args else DEFAULT_DB_PATH
    deleted = scrub_schwab_tokens(db_path)
    print(f"Scrubbed {deleted} Schwab token row(s) from {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
