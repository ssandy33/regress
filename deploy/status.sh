#!/bin/bash
set -euo pipefail

# ============================================================
# Regression Analysis Tool — Status Script
# ============================================================

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

echo "=== Regression Analysis Tool — Status ==="
echo ""

# Container status
echo ">>> Container Status:"
docker compose -f docker-compose.prod.yml ps
echo ""

# Resource usage
echo ">>> Resource Usage:"
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" \
    $(docker compose -f docker-compose.prod.yml ps -q 2>/dev/null) 2>/dev/null || echo "  No running containers."
echo ""

# Disk usage for volumes
echo ">>> Volume Disk Usage:"
docker system df -v 2>/dev/null | grep -A 50 "VOLUME NAME" | head -10 || echo "  Unable to retrieve volume info."
echo ""

# HTTPS cert expiry
echo ">>> HTTPS Certificate:"
DOMAIN=$(grep "^DOMAIN=" .env 2>/dev/null | cut -d= -f2 || echo "")
if [ -n "$DOMAIN" ]; then
    CERT_EXPIRY=$(echo | openssl s_client -servername "$DOMAIN" -connect "$DOMAIN:443" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2 || true)
    if [ -n "$CERT_EXPIRY" ]; then
        echo "  Domain:  $DOMAIN"
        echo "  Expires: $CERT_EXPIRY"
    else
        echo "  Could not check cert for $DOMAIN (may not be accessible from this machine)"
    fi
else
    echo "  No DOMAIN found in .env"
fi
echo ""

# Health check
echo ">>> Health Check:"
if [ -n "$DOMAIN" ]; then
    HEALTH_URL="https://${DOMAIN}/api/health"
else
    HEALTH_URL="http://localhost:8000/api/health"
fi

HEALTH_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL" --max-time 5 2>/dev/null || echo "000")
if [ "$HEALTH_RESPONSE" = "200" ]; then
    echo "  $HEALTH_URL -> OK (200)"
else
    echo "  $HEALTH_URL -> $HEALTH_RESPONSE"
    # Try internal health check via docker
    echo "  Trying internal health check..."
    docker compose -f docker-compose.prod.yml exec -T backend \
        python -c "import urllib.request; r=urllib.request.urlopen('http://localhost:8000/api/health'); print('  Internal:', r.read().decode())" 2>/dev/null || echo "  Internal health check failed."
fi
echo ""

# Backend logs
echo ">>> Backend Logs (last 20 lines):"
docker compose -f docker-compose.prod.yml logs --tail=20 backend 2>/dev/null || echo "  No logs available."
echo ""
