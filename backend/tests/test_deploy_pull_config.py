"""Static-config tests for image-pinned deploys (issue #341 / SUB-2, ADR #338).

SUB-2 swaps the build-on-host deploy for a pull-by-`@sha256:`-digest deploy:
the prod + QA compose files reference the CI-built GHCR images by digest, and
``.github/workflows/_deploy-ssh.yml`` logs into GHCR and runs ``docker compose
pull`` instead of ``docker compose build --no-cache``.

These are static-config / pure-logic assertions — no FastAPI app, no TestClient,
no DB session, no network — so they are ``@pytest.mark.unit``. Mirroring the
established pattern in ``test_qa_compose_config.py``, compose files are parsed
directly with PyYAML and the workflow YAML is asserted as both parsed structure
and raw text (the SSH heredoc body is a string blob, not addressable structure).

Live behaviour (the real GHCR push, pull-by-digest on the box, ``docker inspect``
digest match) is validated on the QA stack and recorded as a skipped test with a
run-log pasted into the PR — same precedent as ``TestQaManualInfraACs``.
"""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
DEPLOY_DIR = REPO_ROOT / "deploy"
PROD_COMPOSE_FILE = REPO_ROOT / "docker-compose.prod.yml"
QA_COMPOSE_FILE = REPO_ROOT / "docker-compose.qa.yml"
BASE_COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
DEPLOY_SSH_WORKFLOW = WORKFLOWS_DIR / "_deploy-ssh.yml"
DEPLOY_WORKFLOW = WORKFLOWS_DIR / "deploy.yml"

# Frozen contract (ADR #338 §1 + #341 plan): GHCR namespace + digest env vars.
GHCR_BACKEND = "ghcr.io/ssandy33/regress-backend"
GHCR_FRONTEND = "ghcr.io/ssandy33/regress-frontend"
BACKEND_DIGEST_VAR = "BACKEND_IMAGE_DIGEST"
FRONTEND_DIGEST_VAR = "FRONTEND_IMAGE_DIGEST"


@pytest.fixture
def prod_config() -> dict:
    """Load and parse docker-compose.prod.yml."""
    return yaml.safe_load(PROD_COMPOSE_FILE.read_text())


@pytest.fixture
def qa_config() -> dict:
    """Load and parse docker-compose.qa.yml."""
    return yaml.safe_load(QA_COMPOSE_FILE.read_text())


@pytest.fixture
def base_config() -> dict:
    """Load and parse the base docker-compose.yml (local dev)."""
    return yaml.safe_load(BASE_COMPOSE_FILE.read_text())


@pytest.fixture
def deploy_ssh_text() -> str:
    """Raw text of the reusable SSH deploy workflow."""
    return DEPLOY_SSH_WORKFLOW.read_text()


@pytest.fixture
def deploy_ssh_config() -> dict:
    """Parsed structure of the reusable SSH deploy workflow."""
    return yaml.safe_load(DEPLOY_SSH_WORKFLOW.read_text())


def _on_block(config: dict) -> dict:
    """Return the workflow `on:` block.

    PyYAML parses the bare `on:` key as the boolean ``True`` (YAML 1.1
    truthy literal), so it is not addressable as the string ``"on"``.
    """
    return config.get("on") or config[True]


class TestComposeImagePinning:
    """Prod + QA compose files pull by digest from GHCR (no build-on-host)."""

    @pytest.mark.unit
    def test_prod_compose_uses_image_not_build(self, prod_config: dict) -> None:
        """Prod backend + frontend use `image:`, with no `build:` key."""
        for svc in ("backend", "frontend"):
            service = prod_config["services"][svc]
            assert "image" in service, f"{svc} must declare image:"
            assert "build" not in service, f"{svc} must NOT declare build:"

    @pytest.mark.unit
    def test_qa_compose_uses_image_not_build(self, qa_config: dict) -> None:
        """QA qa-backend + qa-frontend use `image:`, with no `build:` key."""
        for svc in ("qa-backend", "qa-frontend"):
            service = qa_config["services"][svc]
            assert "image" in service, f"{svc} must declare image:"
            assert "build" not in service, f"{svc} must NOT declare build:"

    @pytest.mark.unit
    def test_prod_compose_image_pinned_by_digest(self, prod_config: dict) -> None:
        """Prod image refs are pinned by @${...DIGEST} digest, not a bare tag."""
        backend = prod_config["services"]["backend"]["image"]
        frontend = prod_config["services"]["frontend"]["image"]
        assert backend == f"{GHCR_BACKEND}@${{{BACKEND_DIGEST_VAR}}}"
        assert frontend == f"{GHCR_FRONTEND}@${{{FRONTEND_DIGEST_VAR}}}"
        # Digest form, never a bare `:tag` (ADR #338 §4 — `latest` is never a
        # deploy coordinate; deploys pin by digest).
        for ref in (backend, frontend):
            assert "@" in ref
            assert ":latest" not in ref

    @pytest.mark.unit
    def test_qa_compose_image_pinned_by_digest(self, qa_config: dict) -> None:
        """QA image refs are pinned by @${...DIGEST} digest, not a bare tag."""
        backend = qa_config["services"]["qa-backend"]["image"]
        frontend = qa_config["services"]["qa-frontend"]["image"]
        assert backend == f"{GHCR_BACKEND}@${{{BACKEND_DIGEST_VAR}}}"
        assert frontend == f"{GHCR_FRONTEND}@${{{FRONTEND_DIGEST_VAR}}}"
        for ref in (backend, frontend):
            assert "@" in ref
            assert ":latest" not in ref

    @pytest.mark.unit
    def test_compose_image_targets_ghcr(self, prod_config: dict, qa_config: dict) -> None:
        """All pinned image refs target the ghcr.io/ssandy33/regress-* namespace."""
        refs = [
            prod_config["services"]["backend"]["image"],
            prod_config["services"]["frontend"]["image"],
            qa_config["services"]["qa-backend"]["image"],
            qa_config["services"]["qa-frontend"]["image"],
        ]
        for ref in refs:
            assert ref.startswith("ghcr.io/ssandy33/regress-"), ref

    @pytest.mark.unit
    def test_local_base_compose_still_builds(self, base_config: dict) -> None:
        """Base docker-compose.yml keeps `build:` for local dev (decision D2).

        Only prod/qa pin to the registry; local dev must not depend on GHCR.
        """
        for svc in ("backend", "frontend"):
            service = base_config["services"][svc]
            assert service.get("build") == f"./{svc}"
            assert "image" not in service


class TestDeploySshPullByDigest:
    """`_deploy-ssh.yml` pulls from GHCR instead of building on the box."""

    @pytest.mark.unit
    def test_deploy_ssh_pulls_not_builds(self, deploy_ssh_text: str) -> None:
        """The deploy workflow runs `compose pull`, never `build --no-cache`."""
        assert "docker compose -f ${{ inputs.compose_file }} pull" in deploy_ssh_text
        assert "build --no-cache" not in deploy_ssh_text

    @pytest.mark.unit
    def test_deploy_ssh_logs_into_ghcr(self, deploy_ssh_text: str) -> None:
        """A `docker login ghcr.io` step uses the GHCR_PULL_TOKEN secret."""
        assert "docker login ghcr.io" in deploy_ssh_text
        assert "--password-stdin" in deploy_ssh_text
        assert "GHCR_PULL_TOKEN" in deploy_ssh_text
        # The token is declared as a required workflow_call secret.
        config = yaml.safe_load(deploy_ssh_text)
        secrets = _on_block(config)["workflow_call"]["secrets"]
        assert "GHCR_PULL_TOKEN" in secrets
        assert secrets["GHCR_PULL_TOKEN"]["required"] is True

    @pytest.mark.unit
    def test_deploy_ssh_threads_digest_inputs(self, deploy_ssh_config: dict) -> None:
        """The workflow accepts both digest values as workflow_call inputs."""
        inputs = _on_block(deploy_ssh_config)["workflow_call"]["inputs"]
        assert "backend_image_digest" in inputs
        assert "frontend_image_digest" in inputs
        assert inputs["backend_image_digest"]["required"] is True
        assert inputs["frontend_image_digest"]["required"] is True

    @pytest.mark.unit
    def test_deploy_ssh_exports_digest_env_before_pull(self, deploy_ssh_text: str) -> None:
        """Digest env vars are exported (for compose interpolation) before pull.

        The compose files reference `@${BACKEND_IMAGE_DIGEST}` /
        `@${FRONTEND_IMAGE_DIGEST}`; both must be exported in the box shell
        ahead of the `docker compose pull` that resolves them.
        """
        assert f"export {BACKEND_DIGEST_VAR}=" in deploy_ssh_text
        assert f"export {FRONTEND_DIGEST_VAR}=" in deploy_ssh_text
        export_idx = deploy_ssh_text.index(f"export {BACKEND_DIGEST_VAR}=")
        pull_idx = deploy_ssh_text.index(
            "docker compose -f ${{ inputs.compose_file }} pull"
        )
        assert export_idx < pull_idx, "digests must be exported before pull"

    @pytest.mark.unit
    def test_deploy_ssh_preserves_git_reset_and_caddy_logic(
        self, deploy_ssh_text: str
    ) -> None:
        """Regression guard: git reset, Caddy-conditional, up -d, prune intact."""
        assert "git reset --hard ${{ inputs.git_ref }}" in deploy_ssh_text
        # Caddy-conditional block (issue #337) preserved.
        assert "config --services | grep -qx caddy" in deploy_ssh_text
        assert 'if [ "$HAS_CADDY" = yes ]' in deploy_ssh_text
        # up -d, ps, and image prune preserved.
        assert "docker compose -f ${{ inputs.compose_file }} up -d" in deploy_ssh_text
        assert "docker image prune -f" in deploy_ssh_text
        # The production Environment gate + concurrency are untouched.
        assert "environment: ${{ inputs.environment }}" in deploy_ssh_text
        assert "group: deploy-${{ inputs.environment }}" in deploy_ssh_text

    @pytest.mark.unit
    def test_deploy_yml_threads_digests_to_both_paths(self) -> None:
        """deploy.yml threads pinned digests to QA + prod deploy calls.

        Bridge edit (SUB-3, #342): the prod path no longer reads the raw CI
        digest directly. SUB-3 inserted a ``promote-prod`` job that re-tags the
        recorded QA-validated digest, so ``deploy-prod`` consumes
        ``needs.promote-prod.outputs.*`` while ``deploy-qa`` still consumes the
        fresh ``needs.ci.outputs.*``. Both still pull by pinned digest with the
        GHCR pull token; only the digest *source* differs by environment.
        """
        config = yaml.safe_load(DEPLOY_WORKFLOW.read_text())
        digest_source = {
            "deploy-qa": "needs.ci.outputs",
            "deploy-prod": "needs.promote-prod.outputs",
        }
        for job, source in digest_source.items():
            spec = config["jobs"][job]
            # needs the upstream job so the digest outputs are available.
            assert "ci" in spec["needs"]
            with_block = spec["with"]
            assert (
                with_block["backend_image_digest"]
                == "${{ %s.backend-digest }}" % source
            )
            assert (
                with_block["frontend_image_digest"]
                == "${{ %s.frontend-digest }}" % source
            )
            assert "GHCR_PULL_TOKEN" in spec["secrets"]


class TestDeployScriptsPullParity:
    """Manual deploy scripts pull for parity with the CI path."""

    @pytest.mark.unit
    def test_qa_deploy_script_pulls_not_builds(self) -> None:
        """deploy/qa-deploy.sh uses `compose pull`, not `up -d --build`."""
        content = (DEPLOY_DIR / "qa-deploy.sh").read_text()
        assert "$COMPOSE pull" in content
        assert "$COMPOSE up -d --build" not in content
        # The regress-qa project name is preserved (R4 alignment).
        assert "docker compose -p regress-qa -f docker-compose.qa.yml" in content

    @pytest.mark.unit
    def test_update_script_pulls_not_builds(self) -> None:
        """deploy/update.sh pulls the prod images instead of building them."""
        content = (DEPLOY_DIR / "update.sh").read_text()
        assert "docker compose -f docker-compose.prod.yml pull" in content
        assert "docker compose -f docker-compose.prod.yml build" not in content


class TestDeployLiveAcs:
    """Live-infra ACs that cannot run in CI — recorded as skipped per CLAUDE.md.

    Verified manually on the QA stack first (ADR #338 QA-first cutover); the
    run-log is pasted into the PR description. Mirrors TestQaManualInfraACs.
    """

    @pytest.mark.unit
    @pytest.mark.skip(
        reason=(
            "L1: pull-by-digest needs the GHCR_PULL_TOKEN repo secret + a live "
            "GHCR push + the VPS. Validate on QA: trigger a QA deploy, confirm "
            "`docker compose pull` (not build) ran and `docker inspect` on the "
            "box shows the running digest matches the CI-emitted backend/frontend "
            "digest from build-and-push-images. Paste the run-log into the PR."
        )
    )
    def test_pull_by_digest_live(self) -> None:  # pragma: no cover
        ...
