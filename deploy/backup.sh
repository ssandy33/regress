#!/bin/bash
set -euo pipefail

# ============================================================
# Regression Analysis Tool — Backup Script
# ============================================================

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$APP_DIR/backups"
BACKUP_FILE="regression_tool_${TIMESTAMP}.db"

mkdir -p "$BACKUP_DIR"

echo "=== Regression Analysis Tool — Backup ==="
echo ""

# Stop backend to ensure clean SQLite copy
echo ">>> Stopping backend container..."
docker compose -f docker-compose.prod.yml stop backend
echo ""

# Copy the database from the Docker volume
echo ">>> Copying SQLite database..."
CONTAINER_NAME=$(docker compose -f docker-compose.prod.yml ps -q backend 2>/dev/null || true)

# Use a temporary container to access the volume
docker run --rm \
    -v "$(docker volume ls -q | grep sqlite_data | head -1)":/data \
    -v "$BACKUP_DIR":/backup \
    alpine:latest \
    cp /data/regression_tool.db "/backup/${BACKUP_FILE}" 2>/dev/null || {
        # Fallback: try docker cp if volume approach fails
        echo ">>> Trying alternative backup method..."
        docker compose -f docker-compose.prod.yml start backend
        sleep 5
        docker compose -f docker-compose.prod.yml exec -T backend \
            cp /app/data/regression_tool.db /app/data/backups/"${BACKUP_FILE}"
        docker compose -f docker-compose.prod.yml cp \
            backend:/app/data/backups/"${BACKUP_FILE}" "$BACKUP_DIR/${BACKUP_FILE}"
    }

# Restart backend
echo ">>> Restarting backend container..."
docker compose -f docker-compose.prod.yml start backend
echo ""

# Show result
if [ -f "$BACKUP_DIR/$BACKUP_FILE" ]; then
    FILESIZE=$(du -h "$BACKUP_DIR/$BACKUP_FILE" | cut -f1)
    echo "=== Backup complete ==="
    echo ""
    echo "  File:     $BACKUP_DIR/$BACKUP_FILE"
    echo "  Size:     $FILESIZE"
    echo ""
    echo "To copy to your local machine:"
    echo "  scp root@YOUR_SERVER_IP:$BACKUP_DIR/$BACKUP_FILE ./"
    echo ""
else
    echo "WARNING: Backup file not found. Check container logs."
fi

# List recent backups
echo "Recent backups:"
ls -lh "$BACKUP_DIR"/*.db 2>/dev/null | tail -5 || echo "  No backups found."
echo ""
