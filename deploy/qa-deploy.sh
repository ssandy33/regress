#!/bin/bash
set -euo pipefail

# ============================================================
# QA environment — deploy / redeploy the QA stack (issue #330)
# ============================================================
# First-time or repeat deploy of the QA stack (project: regress-qa). Run
# manually over SSH from the QA clone at /root/regress-qa — there is no CI for
# QA.
#
# Prerequisites (see deploy/qa/README.md):
#   - qa.<domain> DNS A record resolves to the VPS IP
#   - /root/regress-qa/.env created from deploy/qa/.env.template (QA OAuth app,
#     fresh NEXTAUTH_SECRET, AXIOM_DATASET=regression-tool-qa, no Schwab key)
#   - The prod stack has been deployed at least once with the qa.{$DOMAIN}
#     Caddy block + caddy_net attachment (so the prod Caddy can route to QA)
#
# Usage:
#   bash deploy/qa-deploy.sh

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

COMPOSE="docker compose -p regress-qa -f docker-compose.qa.yml"

echo "=== QA stack deploy ==="
echo ""

# --------------------------------------------------
# 1. Ensure the shared external network exists
# --------------------------------------------------
echo ">>> Ensuring caddy_net exists..."
docker network create caddy_net 2>/dev/null || true
echo ""

# --------------------------------------------------
# 2. Pull latest QA code
# --------------------------------------------------
echo ">>> Pulling latest changes..."
git pull
echo ""

# --------------------------------------------------
# 3. Build and start the QA stack
# --------------------------------------------------
echo ">>> Building and starting QA containers..."
$COMPOSE up -d --build
echo ""

# --------------------------------------------------
# 4. Wait for services to become healthy (mirrors deploy.sh step 11)
# --------------------------------------------------
echo ">>> Waiting for QA services to become healthy..."
sleep 10

# Success is BOTH services reporting (healthy) — not merely the absence of
# "unhealthy|starting" output. A container that exited or is restart-looping
# must fail the deploy, not print a false green.
EXPECTED_HEALTHY=2
MAX_RETRIES=12
RETRY_COUNT=0
while [ "$RETRY_COUNT" -lt "$MAX_RETRIES" ]; do
    HEALTHY_COUNT=$($COMPOSE ps | grep -c "(healthy)" || true)
    if [ "$HEALTHY_COUNT" -ge "$EXPECTED_HEALTHY" ]; then
        break
    fi
    echo "  Waiting for services... ($(( RETRY_COUNT + 1 ))/${MAX_RETRIES})"
    sleep 10
    RETRY_COUNT=$(( RETRY_COUNT + 1 ))
done
echo ""

# --------------------------------------------------
# 5. Status
# --------------------------------------------------
echo ">>> QA container status:"
$COMPOSE ps
echo ""

HEALTHY_COUNT=$($COMPOSE ps | grep -c "(healthy)" || true)
if [ "$HEALTHY_COUNT" -lt "$EXPECTED_HEALTHY" ]; then
    echo "ERROR: QA deploy failed — only ${HEALTHY_COUNT}/${EXPECTED_HEALTHY} services are healthy." >&2
    echo "       Inspect with: $COMPOSE ps && $COMPOSE logs --tail=100" >&2
    exit 1
fi

echo "=========================================="
echo ""
echo "  QA stack started. Once DNS + prod Caddy are in place it serves at"
echo "  https://qa.\${DOMAIN}"
echo ""
echo "=========================================="
echo ""
echo "Next steps:"
echo "  Seed QA DB:  bash deploy/qa-refresh-db.sh"
echo "  Verify:      curl -I https://qa.<domain> && curl https://qa.<domain>/api/health"
echo "  Logs:        docker compose -p regress-qa -f docker-compose.qa.yml logs -f"
echo ""
