"""Regression guard for the QA pre-start Schwab-token scrub wiring (#379).

The scrub (``scripts/scrub_schwab_tokens``, wrapped by
``deploy/qa-scrub-schwab-tokens.sh``) only fixes the #379 crash-loop deadlock if
it runs BEFORE the backend container starts. These static-text assertions pin
that ordering in both deploy paths — the CI workflow
(``.github/workflows/_deploy-ssh.yml``) and the manual ``deploy/qa-deploy.sh`` —
so a future edit can't silently move the scrub after ``up -d`` (which would
re-deadlock: the backend would crash-loop before the scrub could run).

Pure file-text assertions — no app, no TestClient, no DB session, no network —
so ``@pytest.mark.unit``, matching ``test_qa_compose_config.py``.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY_SSH_WF = REPO_ROOT / ".github" / "workflows" / "_deploy-ssh.yml"
QA_DEPLOY_SH = REPO_ROOT / "deploy" / "qa-deploy.sh"
SCRUB_SH = REPO_ROOT / "deploy" / "qa-scrub-schwab-tokens.sh"

SCRUB_SCRIPT_REF = "deploy/qa-scrub-schwab-tokens.sh"


@pytest.mark.unit
def test_scrub_script_exists_and_invokes_the_python_module():
    text = SCRUB_SH.read_text()
    # The scrub COMMAND must use a one-off `run --no-deps` container (overrides
    # the uvicorn CMD so the fail-closed lifespan check never runs), NOT
    # `compose exec` (which needs a running container — the very thing the
    # tokens prevent). Assert the exact command shape rather than the absence of
    # the word "exec" (which legitimately appears in the explanatory header).
    assert 'run --rm --no-deps "$BACKEND_SVC" python -m scripts.scrub_schwab_tokens' in text


@pytest.mark.unit
def test_ci_deploy_runs_scrub_before_up():
    text = DEPLOY_SSH_WF.read_text()
    assert SCRUB_SCRIPT_REF in text, "CI deploy must invoke the pre-start scrub"
    scrub_idx = text.index(SCRUB_SCRIPT_REF)
    # Anchor on the actual command, not the several `up -d` mentions in comments.
    up_idx = text.index("docker compose -f ${{ inputs.compose_file }} up -d")
    assert scrub_idx < up_idx, "scrub must run BEFORE `up -d` or the deadlock returns"


@pytest.mark.unit
def test_ci_deploy_scrub_is_qa_only():
    """Prod legitimately holds Schwab tokens + the key — the scrub must be
    guarded behind environment == qa so it never strips prod's tokens."""
    text = DEPLOY_SSH_WF.read_text()
    scrub_idx = text.index(SCRUB_SCRIPT_REF)
    guard_idx = text.rindex('inputs.environment }}" = "qa"', 0, scrub_idx)
    # The qa guard opens shortly before the scrub invocation (same if-block).
    assert 0 <= scrub_idx - guard_idx < 600


@pytest.mark.unit
def test_manual_qa_deploy_runs_scrub_before_up():
    text = QA_DEPLOY_SH.read_text()
    assert SCRUB_SCRIPT_REF in text, "qa-deploy.sh must invoke the pre-start scrub"
    scrub_idx = text.index(SCRUB_SCRIPT_REF)
    up_idx = text.index("$COMPOSE up -d")
    assert scrub_idx < up_idx, "scrub must run BEFORE `up -d` or the deadlock returns"
