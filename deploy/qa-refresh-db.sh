#!/bin/bash
set -euo pipefail

# ============================================================
# QA environment — on-demand DB refresh (issue #330)
# ============================================================
# Seeds the QA SQLite volume from the newest prod backup snapshot written by
# deploy/backup.sh (../regress/backups/regression_tool_<timestamp>.db).
#
# The restore is an IN-PLACE overwrite of the single regression_tool.db inside
# the QA volume — it never accumulates copies (the box runs disk-constrained).
# Re-running is idempotent.
#
# Usage (on the VPS, from the QA clone at /root/regress-qa):
#   bash deploy/qa-refresh-db.sh
#
# Overrides:
#   BACKUP_DIR=/path/to/backups  bash deploy/qa-refresh-db.sh
#   SNAPSHOT=/path/to/snap.db    bash deploy/qa-refresh-db.sh   # skip selection

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

COMPOSE="docker compose -p regress-qa -f docker-compose.qa.yml"

# Prod backups live alongside the prod clone (../regress/backups by default).
BACKUP_DIR="${BACKUP_DIR:-$APP_DIR/../regress/backups}"

# Fully-qualified QA volume name. NOTE: must match `regress-qa_qa_sqlite_data`
# exactly — a bare `grep sqlite_data` would also match the prod volume
# `regress_sqlite_data` and risk clobbering prod (see plan risk #5).
QA_VOLUME="regress-qa_qa_sqlite_data"

echo "=== QA DB refresh ==="
echo ""

# --------------------------------------------------
# 1. Select the source snapshot
# --------------------------------------------------
if [ -n "${SNAPSHOT:-}" ]; then
    SOURCE_SNAPSHOT="$SNAPSHOT"
    if [ ! -f "$SOURCE_SNAPSHOT" ]; then
        echo "ERROR: SNAPSHOT override not found: $SOURCE_SNAPSHOT" >&2
        exit 1
    fi
else
    echo ">>> Selecting newest snapshot in $BACKUP_DIR ..."
    # Pure-Python selection (unit-tested via backend/scripts/qa_snapshot.py).
    # python3 explicitly — the VPS has no bare `python` (issue #332).
    SOURCE_SNAPSHOT="$(cd "$APP_DIR/backend" && python3 -m scripts.qa_snapshot "$BACKUP_DIR")" || {
        echo "ERROR: no snapshot found. Run deploy/backup.sh on prod first." >&2
        exit 1
    }
fi

SNAP_SIZE=$(du -h "$SOURCE_SNAPSHOT" | cut -f1)
SNAP_TIME=$(date -r "$SOURCE_SNAPSHOT" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "unknown")
echo "    Source:    $SOURCE_SNAPSHOT"
echo "    Size:      $SNAP_SIZE"
echo "    Modified:  $SNAP_TIME"
echo ""

# --------------------------------------------------
# 2. Resolve the QA volume exactly (collision-safe)
# --------------------------------------------------
RESOLVED_VOLUME=$(docker volume ls -q | grep -x "$QA_VOLUME" || true)
if [ -z "$RESOLVED_VOLUME" ]; then
    echo "ERROR: QA volume '$QA_VOLUME' not found. Deploy the QA stack first" >&2
    echo "       (bash deploy/qa-deploy.sh)." >&2
    exit 1
fi

# --------------------------------------------------
# 3. Stop qa-backend for a clean SQLite copy (WAL/lock safety)
# --------------------------------------------------
echo ">>> Stopping qa-backend..."
$COMPOSE stop backend
echo ""

# From here on qa-backend is down. Restart it on ANY exit so a failed restore
# can't leave QA offline; the happy path clears the trap before its own restart.
trap '$COMPOSE start backend || true' EXIT

# --------------------------------------------------
# 4. Overwrite the DB in the QA volume via a throwaway alpine container
#    (same volume-access pattern as deploy/backup.sh). In-place, no temp copies.
# --------------------------------------------------
echo ">>> Restoring snapshot into $QA_VOLUME (in place)..."
SNAP_BASENAME="$(basename "$SOURCE_SNAPSHOT")"
# chown to the qa-backend runtime user (1000:1000 in docker-compose.qa.yml) —
# the copy runs as root, and a root-owned DB breaks the backend's first write.
# Stale -wal/-shm sidecars from the previous DB are removed so SQLite can't
# replay an old WAL against the freshly restored file.
docker run --rm \
    -v "$RESOLVED_VOLUME":/data \
    -v "$(cd "$(dirname "$SOURCE_SNAPSHOT")" && pwd)":/snapshot:ro \
    alpine:latest \
    sh -c "rm -f /data/regression_tool.db-wal /data/regression_tool.db-shm \
        && cp /snapshot/'$SNAP_BASENAME' /data/regression_tool.db \
        && chown 1000:1000 /data/regression_tool.db"
echo ""

# --------------------------------------------------
# 5. Scrub Schwab tokens from the restored snapshot (issue #332)
# --------------------------------------------------
# Prod snapshots carry encrypted Schwab tokens in app_settings. QA has no
# SCHWAB_ENCRYPTION_KEY by design, and the backend's fail-closed startup check
# (app/main.py _run_security_checks) refuses to boot when tokens exist without
# the key — so an unscrubbed restore puts qa-backend in a restart loop. The
# key list mirrors ENCRYPTED_SETTING_KEYS in app/services/encryption.py.
echo ">>> Scrubbing Schwab tokens (QA runs without SCHWAB_ENCRYPTION_KEY)..."
$COMPOSE run --rm --no-deps backend python -c "
import sqlite3
conn = sqlite3.connect('/app/data/regression_tool.db')
cur = conn.execute(
    \"DELETE FROM app_settings WHERE key IN \"
    \"('schwab_access_token','schwab_refresh_token','schwab_app_key','schwab_app_secret')\"
)
conn.commit()
print(f'    Scrubbed {cur.rowcount} Schwab token row(s)')
"
echo ""

# --------------------------------------------------
# 6. Restart qa-backend (re-opens the fresh DB)
# --------------------------------------------------
echo ">>> Restarting qa-backend..."
trap - EXIT
$COMPOSE start backend
echo ""

echo "=== QA DB refresh complete ==="
echo "    Restored from: $SOURCE_SNAPSHOT ($SNAP_SIZE, $SNAP_TIME)"
echo "    Into volume:   $QA_VOLUME -> /app/data/regression_tool.db"
echo ""
