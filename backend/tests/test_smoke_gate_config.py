"""Tests for the post-deploy smoke gate (issue #343 / SUB-4 of #324).

ADR Discussion #338 §5 ratifies a post-deploy smoke gate: the deploy job must
fail with a non-zero exit if the app does not serve after ``docker compose up
-d`` — a broken image or crash-looping container surfaces as a red Action
rather than a silently-live broken deploy (the v1.0.0 #229 outage class).

These are static-config assertions on ``.github/workflows/_deploy-ssh.yml`` —
there is no FastAPI app, no TestClient, no DB session, and no network — so they
are ``@pytest.mark.unit``. Following the precedent in
``test_qa_compose_config.py``, the workflow is parsed directly with PyYAML
rather than shelling out to the docker CLI (unavailable in the unit runner).

The smoke gate's live behavior (deliberately break a QA deploy and confirm the
Action goes red) cannot run in CI; it is recorded below as a skipped test with a
rationale, mirroring ``TestQaManualInfraACs`` — the run-log is pasted into the
PR description.

Target endpoint: ``/auth/signin`` — the #232-fixed meaningful frontend signal
(a rendered, middleware-excluded page; a 200 proves the render pipeline produced
HTML, unlike the old bare ``/`` probe whose 307 redirect passed the instant
Next.js was merely listening).
"""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY_SSH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "_deploy-ssh.yml"

# The meaningful endpoint from #232's fix — the frozen smoke target (D4).
SMOKE_ENDPOINT = "/auth/signin"


@pytest.fixture
def deploy_ssh_yaml() -> dict:
    """Parse _deploy-ssh.yml — proves the workflow stays valid YAML."""
    return yaml.safe_load(DEPLOY_SSH_WORKFLOW.read_text())


@pytest.fixture
def deploy_script() -> str:
    """The remote bash heredoc body of the `Deploy via SSH` step.

    The smoke gate lives inside the single-quoted ``<<'ENDSSH'`` heredoc that
    runs on the box, which PyYAML hands back as the step's ``command`` string.
    Asserting against that string keeps the gate's shell logic under test
    without shelling out to docker.
    """
    config = yaml.safe_load(DEPLOY_SSH_WORKFLOW.read_text())
    steps = config["jobs"]["deploy"]["steps"]
    deploy_step = next(s for s in steps if s.get("name") == "Deploy via SSH")
    return deploy_step["with"]["command"]


class TestSmokeGate:
    """Static-config assertions for the #343 post-deploy smoke gate."""

    @pytest.mark.unit
    def test_deploy_ssh_has_post_deploy_smoke_step(self, deploy_script: str) -> None:
        """A smoke step runs after `docker compose up -d` (AC 1).

        The gate must probe the app only once the containers are up, so the
        smoke logic has to appear AFTER the `up -d` invocation in the script.
        """
        assert "up -d" in deploy_script, "expected `docker compose up -d` in the deploy script"
        assert "Smoke gate" in deploy_script, "expected a post-deploy smoke gate block"
        up_idx = deploy_script.index("up -d")
        smoke_idx = deploy_script.index("Smoke gate")
        assert smoke_idx > up_idx, "smoke gate must run AFTER `docker compose up -d`"

    @pytest.mark.unit
    def test_smoke_step_fails_deploy_on_non_serving(self, deploy_script: str) -> None:
        """On a non-serving app the smoke step exits non-zero (AC 3).

        The core principle: the gate FAILS THE DEPLOY (red Action), it is not
        alert-only. There must be an `exit 1` reachable from the smoke block,
        and it must be emitted as a GitHub Actions error annotation.
        """
        # The smoke block lives after the gate banner; assert the failure path
        # exists within it (not merely the unrelated empty-git-ref guard above).
        smoke_block = deploy_script[deploy_script.index("Post-deploy smoke gate"):]
        assert "exit 1" in smoke_block, "smoke gate must `exit 1` to fail the deploy"
        assert "Smoke gate FAILED" in smoke_block, "failure message must be clear/surfaced"
        assert "::error::" in smoke_block, "failure must be a surfaced GitHub Actions error"

    @pytest.mark.unit
    def test_smoke_step_retries_before_failing(self, deploy_script: str) -> None:
        """The smoke probe retries with backoff before declaring failure (AC 2).

        A freshly-started container needs a moment to begin serving; the gate
        must not flap on the first attempt. There must be a retry loop and a
        sleep/backoff between attempts.
        """
        smoke_block = deploy_script[deploy_script.index("Post-deploy smoke gate"):]
        assert "for attempt in" in smoke_block, "smoke gate must retry across attempts"
        assert "sleep" in smoke_block, "smoke gate must back off (sleep) between retries"

    @pytest.mark.unit
    def test_smoke_target_is_meaningful_endpoint(self, deploy_script: str) -> None:
        """The smoke probe hits the #232-fixed endpoint, not a bare `/` redirect (AC 2).

        `/auth/signin` is a rendered, middleware-excluded page (a 200 proves the
        render pipeline produced HTML). The old bare `/` probe's 307 redirect
        passed the instant Next.js was merely listening — exactly the false
        healthy this gate exists to prevent.
        """
        smoke_block = deploy_script[deploy_script.index("Post-deploy smoke gate"):]
        assert SMOKE_ENDPOINT in smoke_block, f"smoke gate must target {SMOKE_ENDPOINT}"

    @pytest.mark.unit
    def test_smoke_step_preserves_ps_and_image_prune(self, deploy_script: str) -> None:
        """The existing `ps` and `image prune` steps are preserved (AC 4).

        The smoke step is ADDED between them, not a replacement — a regression
        guard so SUB-4 does not drop SUB-2's deploy housekeeping.
        """
        assert "docker compose -f ${{ inputs.compose_file }} ps" in deploy_script
        assert "docker image prune -f" in deploy_script

    @pytest.mark.unit
    def test_smoke_step_preserves_pull_and_login(self, deploy_script: str) -> None:
        """SUB-2's GHCR login + pull-by-digest swap stays intact (regression guard).

        SUB-4 must not disturb the login/pull/digest logic SUB-2 set up.
        """
        assert "docker login ghcr.io" in deploy_script, "SUB-2 GHCR login must survive"
        assert "docker compose -f ${{ inputs.compose_file }} pull" in deploy_script
        assert "build --no-cache" not in deploy_script, "must stay pull-not-build (SUB-2)"

    @pytest.mark.unit
    def test_deploy_ssh_is_valid_yaml_with_smoke_step(self, deploy_ssh_yaml: dict) -> None:
        """_deploy-ssh.yml still parses and the Deploy step is intact.

        Guards against the smoke edit breaking the single-quoted heredoc /
        positional-arg structure SUB-2 set up.
        """
        steps = deploy_ssh_yaml["jobs"]["deploy"]["steps"]
        deploy_step = next(s for s in steps if s.get("name") == "Deploy via SSH")
        assert deploy_step["uses"] == "nick-fields/retry@v4"
        assert "Smoke gate" in deploy_step["with"]["command"]


class TestSmokeGateManualInfraACs:
    """Live smoke-gate ACs that cannot run in CI — recorded as skipped per CLAUDE.md.

    Keeps the AC<->verification mapping complete. Verified manually on the QA
    stack; the run-log is pasted into the PR description (mirrors
    ``TestQaManualInfraACs`` in test_qa_compose_config.py).
    """

    @pytest.mark.unit
    @pytest.mark.skip(
        reason="LIVE: deliberately break a QA deploy (bad digest / forcibly kill "
        "qa-frontend), confirm the smoke step makes the Action go RED. Needs a "
        "real GHCR pull + docker on the VPS — run-log pasted into the PR (#343 AC 5)."
    )
    def test_smoke_gate_blocks_bad_deploy_live(self) -> None:  # pragma: no cover
        ...
