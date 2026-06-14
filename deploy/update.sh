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

# Ensure the shared external caddy_net exists before `up -d` (issue #330).
# The prod compose now declares caddy_net as external; without this guard a
# prod-only operator would hit a "network not found" error. Idempotent.
echo ">>> Ensuring caddy_net exists..."
docker network create caddy_net 2>/dev/null || true
echo ""

# Pull the CI-built images by digest (#341/SUB-2, ADR #338): the prod compose
# references ghcr.io/ssandy33/regress-{backend,frontend}@${...DIGEST} instead of
# building from source — parity with the CI deploy path. For a manual run, export
# the digests CI emitted and `docker login ghcr.io` with a read:packages PAT first:
#   export BACKEND_IMAGE_DIGEST='sha256:...'  FRONTEND_IMAGE_DIGEST='sha256:...'
#   echo "$GHCR_PULL_TOKEN" | docker login ghcr.io -u <user> --password-stdin
echo ">>> Pulling images..."
docker compose -f docker-compose.prod.yml pull
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
