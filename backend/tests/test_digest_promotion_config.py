"""Tests for digest promotion QA→prod (issue #342 / SUB-3, ADR #338).

Static-config assertions on ``.github/workflows/deploy.yml``. The prod
(release-published) path must PROMOTE the QA-validated image digest to the
release tag by a registry-side re-tag (``docker buildx imagetools create``) —
never a ``docker build`` / ``docker compose build`` and never a fresh source
re-resolution. The promoted digest (same ``@sha256:`` bytes QA validated) is
then handed to ``_deploy-ssh.yml`` for the prod pull.

These are pure static-config / text assertions — no FastAPI app, no
TestClient, no DB session, no network, no docker CLI — so they are
``@pytest.mark.unit``. Following the established pattern in
``test_qa_compose_config.py``, the workflow file is parsed directly with PyYAML
rather than shelling out to the docker/GitHub-Actions CLIs.

Live behaviour (prod digest == QA digest verified on a real release via
``docker buildx imagetools inspect`` / ``docker inspect``) cannot run in CI; it
is recorded as a skipped test with a rationale (mirroring
``TestQaManualInfraACs``) so the AC↔verification mapping stays complete.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy.yml"


@pytest.fixture
def deploy_workflow() -> dict:
    """Load and parse .github/workflows/deploy.yml."""
    return yaml.safe_load(DEPLOY_WORKFLOW.read_text())


@pytest.fixture
def deploy_workflow_text() -> str:
    """Raw text of deploy.yml for run-script (shell) assertions."""
    return DEPLOY_WORKFLOW.read_text()


def _job_step_run_text(job: dict) -> str:
    """Concatenate all `run:` script bodies of a job's steps."""
    return "\n".join(
        step.get("run", "") for step in job.get("steps", []) if isinstance(step, dict)
    )


class TestDigestPromotion:
    """The prod path promotes the recorded QA digest by registry re-tag."""

    @pytest.mark.unit
    def test_deploy_promotes_by_imagetools_create(self, deploy_workflow: dict) -> None:
        """Prod path uses `docker buildx imagetools create`, not a rebuild.

        The promote-prod job re-tags both the backend and frontend digests to
        the release tag via `imagetools create` — a registry-side manifest copy
        (ADR #338 §3, risk R2).
        """
        jobs = deploy_workflow["jobs"]
        assert "promote-prod" in jobs, "deploy.yml must define a promote-prod job"
        run_text = _job_step_run_text(jobs["promote-prod"])
        assert "docker buildx imagetools create" in run_text
        # Both images are promoted.
        assert "ghcr.io/ssandy33/regress-backend:" in run_text
        assert "ghcr.io/ssandy33/regress-frontend:" in run_text

    @pytest.mark.unit
    def test_promote_reads_recorded_qa_digest(self, deploy_workflow: dict) -> None:
        """Promote re-tags the RECORDED digest (@sha256:), not a fresh resolution.

        The `imagetools create` source argument references the recorded digest
        by `@${...DIGEST}`, and that digest is sourced from the CI build output
        (`needs.ci.outputs.*-digest`) rather than resolved from a bare tag /
        source at promote time.
        """
        promote = deploy_workflow["jobs"]["promote-prod"]
        run_text = _job_step_run_text(promote)
        # Source of the re-tag is a digest reference, not a bare tag.
        assert "ghcr.io/ssandy33/regress-backend@${BACKEND_DIGEST}" in run_text
        assert "ghcr.io/ssandy33/regress-frontend@${FRONTEND_DIGEST}" in run_text
        # The digest env vars are bound to the RECORDED CI build outputs.
        env = promote.get("env", {})
        assert env.get("BACKEND_DIGEST") == "${{ needs.ci.outputs.backend-digest }}"
        assert env.get("FRONTEND_DIGEST") == "${{ needs.ci.outputs.frontend-digest }}"

    @pytest.mark.unit
    def test_prod_path_has_no_build_step(self, deploy_workflow: dict) -> None:
        """Release→prod job path has no `docker build` / `docker compose build`.

        Silent-drift guard (ADR #338 risk R2): if the prod path rebuilt instead
        of re-tagging the recorded digest, prod could diverge from the
        QA-tested artifact. Scan every job that participates in the prod path
        for any build invocation.
        """
        jobs = deploy_workflow["jobs"]
        prod_path_jobs = ("promote-prod", "deploy-prod")
        for name in prod_path_jobs:
            assert name in jobs, f"deploy.yml must define the {name} job"
        # `docker build` but NOT `docker buildx` (the imagetools re-tag is fine).
        docker_build_re = re.compile(r"docker\s+build(?!x)")
        for name in prod_path_jobs:
            run_text = _job_step_run_text(jobs[name])
            assert not docker_build_re.search(run_text), (
                f"{name} must not run docker build"
            )
            assert "compose build" not in run_text, (
                f"{name} must not run docker compose build"
            )

    @pytest.mark.unit
    def test_promoted_digest_passed_to_prod_deploy(self, deploy_workflow: dict) -> None:
        """deploy-prod receives the PROMOTED digest, not a freshly built one.

        The prod deploy's image-digest inputs are wired from promote-prod's
        outputs (the recorded, re-tagged QA digest) — so the box pulls the
        identical @sha256: bytes QA validated (AC: promoted digest passed to
        _deploy-ssh.yml).
        """
        deploy_prod = deploy_workflow["jobs"]["deploy-prod"]
        # deploy-prod depends on promote-prod so the promotion runs first.
        assert "promote-prod" in deploy_prod["needs"]
        with_block = deploy_prod["with"]
        assert (
            with_block["backend_image_digest"]
            == "${{ needs.promote-prod.outputs.backend-digest }}"
        )
        assert (
            with_block["frontend_image_digest"]
            == "${{ needs.promote-prod.outputs.frontend-digest }}"
        )


class TestQaDigestRecording:
    """The QA-deployed digest is recorded as an auditable artifact (ADR #338 §3)."""

    @pytest.mark.unit
    def test_qa_digest_recorded_as_artifact(self, deploy_workflow: dict) -> None:
        """A record-qa-digest job uploads the QA-deployed digests as an artifact."""
        jobs = deploy_workflow["jobs"]
        assert "record-qa-digest" in jobs, "deploy.yml must record the QA digest"
        record = jobs["record-qa-digest"]
        # Runs after the QA deploy so it records what actually deployed.
        assert "deploy-qa" in record["needs"]
        uses = [
            step.get("uses", "")
            for step in record["steps"]
            if isinstance(step, dict)
        ]
        assert any("actions/upload-artifact" in u for u in uses), (
            "record-qa-digest must upload the recorded digests as a run artifact"
        )


class TestProdPathRegressionGuards:
    """Regression guards: prod gate + triggers preserved alongside SUB-3."""

    @pytest.mark.unit
    def test_prod_deploy_uses_production_environment(self, deploy_workflow: dict) -> None:
        """deploy-prod still routes through the production Environment gate.

        The Environment gate lives in _deploy-ssh.yml (passed `environment:
        production`); SUB-3 must not bypass it.
        """
        deploy_prod = deploy_workflow["jobs"]["deploy-prod"]
        assert deploy_prod["with"]["environment"] == "production"
        # Still delegates to the shared reusable SSH deploy.
        assert deploy_prod["uses"] == "./.github/workflows/_deploy-ssh.yml"

    @pytest.mark.unit
    def test_promote_only_on_release_or_prod_dispatch(self, deploy_workflow: dict) -> None:
        """Promotion is gated to the prod path (full release / prod dispatch only)."""
        condition = deploy_workflow["jobs"]["promote-prod"]["if"]
        assert "github.event.release.prerelease == false" in condition
        assert "inputs.environment == 'production'" in condition

    @pytest.mark.unit
    def test_triggers_preserved(self, deploy_workflow: dict) -> None:
        """All existing triggers survive (push, release:published, dispatch).

        PyYAML parses the bare `on:` key as the boolean True, so index by that.
        """
        triggers = deploy_workflow[True]
        assert "main" in triggers["push"]["branches"]
        assert "published" in triggers["release"]["types"]
        assert "workflow_dispatch" in triggers


class TestDigestPromotionLiveACs:
    """Live ACs that cannot run in CI — recorded as skipped per CLAUDE.md.

    These keep the AC↔verification mapping complete. They are verified on a real
    release and the run-log is pasted into the PR description (mirroring
    TestQaManualInfraACs in test_qa_compose_config.py).
    """

    @pytest.mark.unit
    @pytest.mark.skip(
        reason=(
            "Live: after a real release, `docker buildx imagetools inspect "
            "ghcr.io/ssandy33/regress-backend:<release-tag>` must show the same "
            "digest as the QA-deployed digest, and prod `docker inspect` must "
            "confirm the running image == QA digest (byte-for-byte). Needs live "
            "GHCR + a published release — run-log pasted into the PR."
        )
    )
    def test_digest_promotion_live(self) -> None:  # pragma: no cover
        ...
