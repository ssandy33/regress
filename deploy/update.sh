#!/bin/bash
set -euo pipefail

# ============================================================
# Regression Analysis Tool — Update Script
# ============================================================

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

echo "=== Updating Regression Analysis Tool ==="
echo ""

# Pull latest code
echo ">>> Pulling latest changes..."
git pull
echo ""

# Rebuild containers
echo ">>> Building containers..."
docker compose -f docker-compose.prod.yml build
echo ""

# Restart with new images
echo ">>> Restarting services..."
docker compose -f docker-compose.prod.yml up -d
echo ""

# Restart Caddy so it re-resolves upstream DNS for the new containers
echo ">>> Restarting Caddy reverse proxy..."
docker compose -f docker-compose.prod.yml restart caddy
echo ""

# Show status
echo ">>> Container status:"
docker compose -f docker-compose.prod.yml ps
echo ""

# Clean up old images
echo ">>> Pruning old Docker images..."
docker image prune -f
echo ""

echo "=== Update complete ==="
