#!/bin/bash
set -euo pipefail

# ============================================================
# QA pre-start Schwab-token scrub (root-cause fix for #379)
# ============================================================
# QA runs with SCHWAB_ENCRYPTION_KEY unset. The backend's fail-closed startup
# check (app/main.py _run_security_checks) refuses to boot when the 4 sensitive
# schwab_* token rows exist in app_settings without the key — crash-looping the
# container and taking all QA /api/* to 502 behind Caddy (#379).
#
# The #380 scrub lives in seed_qa._full_reset(), which runs via
# `docker compose exec qa-backend ...` — and `exec` needs a RUNNING container.
# Once the tokens are present the backend can't stay up, so the exec-based scrub
# can never fire: a deadlock. This script breaks it by running the scrub from a
# ONE-OFF container (`compose run --no-deps`, command overridden to a bare
# `python -m scripts.scrub_schwab_tokens`) that connects straight to the SQLite
# file and never imports the FastAPI app / triggers the security check. Mirrors
# the qa-refresh-db.sh #332 scrub, but on the synthetic-seed deploy path and
# BEFORE the long-running backend starts.
#
# MUST run BEFORE `docker compose up -d`. Idempotent: deleting 0 rows (or a
# fresh volume with no app_settings table yet) is a clean no-op. The key list
# lives in app.services.encryption.ENCRYPTED_SETTING_KEYS — single source of
# truth shared with the startup check and the #380 seed scrub.
#
# Usage (from the QA clone at /root/regress-qa):
#   bash deploy/qa-scrub-schwab-tokens.sh
#
# Overrides (used by the CI deploy path, .github/workflows/_deploy-ssh.yml):
#   COMPOSE_FILE=docker-compose.qa.yml PROJECT=regress-qa \
#     bash deploy/qa-scrub-schwab-tokens.sh

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.qa.yml}"
PROJECT="${PROJECT:-regress-qa}"
COMPOSE="docker compose -p ${PROJECT} -f ${COMPOSE_FILE}"

# Resolve the backend service from the compose file (handles `qa-backend`).
BACKEND_SVC=$($COMPOSE config --services | grep -E '(^|-)backend$' | head -1)
if [ -z "$BACKEND_SVC" ]; then
    echo "ERROR: qa-scrub: could not resolve a backend service from ${COMPOSE_FILE}." >&2
    exit 1
fi

echo ">>> Pre-start Schwab-token scrub (QA boots without SCHWAB_ENCRYPTION_KEY)..."
# --no-deps: don't pull up qa-frontend etc. --rm: leave no stray container.
# The overridden command (`python -m ...`) bypasses the uvicorn CMD, so the
# fail-closed lifespan check never runs — this works even mid-crash-loop.
# -T (no TTY) + </dev/null: when this runs from the deploy heredoc (ssh pipes
# the whole script to `bash -s`), an attached stdin makes `compose run` consume
# the REST of the heredoc as the container's input — silently swallowing the
# subsequent `up -d` / seed / digest-assert steps (the QA stale-container
# incident). Detach stdin so only this scrub runs in the one-off container.
$COMPOSE run --rm --no-deps -T "$BACKEND_SVC" python -m scripts.scrub_schwab_tokens </dev/null
