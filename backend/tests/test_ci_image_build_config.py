"""Static-config tests for the GHCR build+push CI job (issue #340 / SUB-1).

Validates the ``build-and-push-images`` job added to ``.github/workflows/ci.yml``
by ADR Discussion #338 (registry-pinned deploys). These are static-config
assertions — the workflow YAML is parsed directly with PyYAML and asserted on
structurally; there is no docker CLI invocation, no FastAPI app, no DB session,
and no network — so they are ``@pytest.mark.unit``.

This mirrors the established pattern in ``test_qa_compose_config.py``: parse the
config, assert on structure, and record the one AC that can only be exercised
against live infrastructure (the real GHCR push) as a skipped test with a
rationale (``test_ghcr_push_live``), keeping the AC↔verification mapping
complete. That live AC is validated on the QA stack with the resulting digest
pasted into the PR.
"""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CI_WORKFLOW_FILE = REPO_ROOT / ".github" / "workflows" / "ci.yml"
FRONTEND_CLIENT_JS = REPO_ROOT / "frontend" / "api" / "client.js"

BUILD_JOB = "build-and-push-images"
GHCR_BACKEND = "ghcr.io/ssandy33/regress-backend"
GHCR_FRONTEND = "ghcr.io/ssandy33/regress-frontend"


@pytest.fixture
def ci_config() -> dict:
    """Load and parse .github/workflows/ci.yml."""
    return yaml.safe_load(CI_WORKFLOW_FILE.read_text())


@pytest.fixture
def build_job(ci_config: dict) -> dict:
    """The build-and-push-images job dict."""
    return ci_config["jobs"][BUILD_JOB]


def _job_text() -> str:
    """Raw text of the build job region — for grep-style assertions on
    expression strings that PyYAML normalises (e.g. ``${{ ... }}``)."""
    return CI_WORKFLOW_FILE.read_text()


def _steps_by_id(build_job: dict) -> dict:
    return {s["id"]: s for s in build_job["steps"] if "id" in s}


class TestCiBuildPushJob:
    """Structural assertions on the build-and-push-images job (SUB-1)."""

    @pytest.mark.unit
    def test_ci_has_build_push_images_job(self, ci_config: dict) -> None:
        """CI defines a build-and-push-images job."""
        assert BUILD_JOB in ci_config["jobs"]

    @pytest.mark.unit
    def test_build_job_has_packages_write_permission(self, build_job: dict) -> None:
        """Job carries permissions: { contents: read, packages: write } for GHCR push."""
        perms = build_job["permissions"]
        assert perms["packages"] == "write"
        assert perms["contents"] == "read"

    @pytest.mark.unit
    def test_build_job_targets_ghcr_namespace(self, build_job: dict) -> None:
        """metadata-action steps target the GHCR backend + frontend namespaces."""
        images = set()
        for step in build_job["steps"]:
            uses = step.get("uses", "")
            if uses.startswith("docker/metadata-action"):
                images.add(step["with"]["images"].strip())
        assert GHCR_BACKEND in images
        assert GHCR_FRONTEND in images

    @pytest.mark.unit
    def test_build_job_tags_with_sha_and_release(self, build_job: dict) -> None:
        """metadata emits a sha- prefixed tag always + the ref/tag on a release."""
        meta_steps = [
            s for s in build_job["steps"]
            if s.get("uses", "").startswith("docker/metadata-action")
        ]
        assert meta_steps, "expected at least one docker/metadata-action step"
        for step in meta_steps:
            tags = step["with"]["tags"]
            assert "type=sha,prefix=sha-" in tags
            # ref/tag on release events (release publishes a tag ref).
            assert "type=ref,event=tag" in tags

    @pytest.mark.unit
    def test_build_job_never_uses_latest_for_deploy(self, build_job: dict) -> None:
        """No :latest deploy coordinate — metadata-action latest flavor disabled,
        and no literal :latest tag is pushed."""
        for step in build_job["steps"]:
            uses = step.get("uses", "")
            if uses.startswith("docker/metadata-action"):
                assert "latest=false" in step["with"]["flavor"]
            if uses.startswith("docker/build-push-action"):
                tags = step["with"].get("tags", "")
                assert ":latest" not in tags
        # Belt-and-suspenders: no ``type=raw,value=latest`` style coordinate anywhere.
        assert "value=latest" not in _job_text()

    @pytest.mark.unit
    def test_build_job_single_arch_amd64(self, build_job: dict) -> None:
        """Both build-push steps target platforms: linux/amd64 (single-arch, ADR §1)."""
        build_steps = [
            s for s in build_job["steps"]
            if s.get("uses", "").startswith("docker/build-push-action")
        ]
        assert len(build_steps) >= 2, "expected backend + frontend build steps"
        for step in build_steps:
            assert step["with"]["platforms"] == "linux/amd64"

    @pytest.mark.unit
    def test_build_job_no_push_on_pull_request(self, build_job: dict) -> None:
        """push: is gated on event_name != 'pull_request' — fork PRs never push."""
        build_steps = [
            s for s in build_job["steps"]
            if s.get("uses", "").startswith("docker/build-push-action")
        ]
        assert build_steps, "expected build-push steps"
        for step in build_steps:
            push = str(step["with"]["push"])
            assert "github.event_name != 'pull_request'" in push

    @pytest.mark.unit
    def test_build_job_uses_gha_cache(self, build_job: dict) -> None:
        """Both build steps enable GHA layer caching (cache-from/to: type=gha)."""
        build_steps = [
            s for s in build_job["steps"]
            if s.get("uses", "").startswith("docker/build-push-action")
        ]
        for step in build_steps:
            assert step["with"]["cache-from"] == "type=gha"
            assert step["with"]["cache-to"] == "type=gha,mode=max"

    @pytest.mark.unit
    def test_build_job_emits_digest_outputs(self, build_job: dict) -> None:
        """Job emits backend-digest + frontend-digest sourced from each build
        step's ${{ steps.<id>.outputs.digest }}."""
        outputs = build_job["outputs"]
        steps = _steps_by_id(build_job)
        for key in ("backend-digest", "frontend-digest"):
            assert key in outputs
            value = outputs[key]
            assert ".outputs.digest" in value
            # The referenced step id must exist and be a build-push-action step.
            step_id = value.split("steps.")[1].split(".")[0]
            assert step_id in steps
            assert steps[step_id]["uses"].startswith("docker/build-push-action")

    @pytest.mark.unit
    def test_build_job_logs_into_ghcr(self, build_job: dict) -> None:
        """Job logs into ghcr.io via docker/login-action using the workflow token."""
        login_steps = [
            s for s in build_job["steps"]
            if s.get("uses", "").startswith("docker/login-action")
        ]
        assert login_steps, "expected a docker/login-action step"
        with_ = login_steps[0]["with"]
        assert with_["registry"] == "ghcr.io"
        assert "github.actor" in str(with_["username"])
        assert "secrets.GITHUB_TOKEN" in str(with_["password"])

    @pytest.mark.unit
    def test_frontend_env_agnostic_guard_present(self, build_job: dict) -> None:
        """A guard step fails CI on any new env-baked NEXT_PUBLIC_* beyond
        NEXT_PUBLIC_API_URL (ADR #338 env-agnostic frontend invariant)."""
        guard_steps = [
            s for s in build_job["steps"]
            if "NEXT_PUBLIC_" in s.get("name", "") + s.get("run", "")
        ]
        assert guard_steps, "expected an env-agnostic NEXT_PUBLIC_* guard step"
        run = guard_steps[0]["run"]
        # The known-safe var must be the allow-listed exception.
        assert "NEXT_PUBLIC_API_URL" in run
        # The guard must be able to fail the job.
        assert "exit 1" in run

    @pytest.mark.unit
    def test_frontend_client_api_url_unset_at_build(self) -> None:
        """frontend/api/client.js reads NEXT_PUBLIC_API_URL with a `|| ''`
        fallback, so it resolves to a relative URL when unset at build —
        the env-agnostic anchor the CI guard protects."""
        content = FRONTEND_CLIENT_JS.read_text()
        assert "process.env.NEXT_PUBLIC_API_URL || ''" in content


class TestCiBuildLiveACs:
    """Live-infra ACs that cannot run in CI — recorded as skipped per CLAUDE.md.

    These keep the AC↔verification mapping complete. They are verified on the
    QA stack and the resulting digest is pasted into the PR description (same
    pattern as ``TestQaManualInfraACs`` in test_qa_compose_config.py).
    """

    @pytest.mark.unit
    @pytest.mark.skip(
        reason="L1: real GHCR push needs the CI runner + GITHUB_TOKEN — "
        "validated on the QA stack; backend+frontend digests pasted into the PR."
    )
    def test_ghcr_push_live(self) -> None:  # pragma: no cover
        ...
