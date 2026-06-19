#!/bin/bash
set -euo pipefail

# ============================================================
# Regression Analysis Tool — Update Script
# ============================================================
#
# Disk reclamation (#369): this script prunes dangling images at the end
# (docker image prune -f). The CI deploy path additionally runs a bounded
# build-cache prune (docker builder prune -f --filter until=168h). For a manual
# full reclaim when the box is low on space, see deploy/RUNBOOK.md
# ("Disk reclamation") — break-glass is `docker builder prune -af`.

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
# Build cache is pruned by the CI deploy (docker builder prune --filter
# until=168h); for a manual full reclaim see deploy/RUNBOOK.md.
echo ">>> Pruning old Docker images..."
docker image prune -f
echo ""

echo "=== Update complete ==="
