"""Static-config tests for the deploy-aware GHCR retention prune (SUB-5, #344).

Validates the structure of ``.github/workflows/ghcr-prune.yml`` — the scheduled
GitHub Action that prunes old GHCR image versions while preserving the live
digest, the N-1 / N-2 rollback candidates, and all release-tagged images
(ADR #338, parent epic #324).

These are static-config assertions: the workflow YAML is parsed directly with
PyYAML and asserted on structurally / by keyword. There is no FastAPI app, no
TestClient, no DB session, no network, and no docker CLI invocation — so every
test is ``@pytest.mark.unit``. This mirrors the established
``test_qa_compose_config.py`` precedent (parse the YAML, assert on structure).

The live behavior (a real dry-run prune showing the live digest in the
keep-list) is validated manually on the QA/prod GHCR namespace and recorded as
a skipped test with its run-log pasted into the PR, mirroring
``TestQaManualInfraACs``.
"""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PRUNE_WORKFLOW_FILE = REPO_ROOT / ".github" / "workflows" / "ghcr-prune.yml"

# Frozen contract (do not invent variants) — ADR #338 §1.
BACKEND_IMAGE = "ghcr.io/ssandy33/regress-backend"
FRONTEND_IMAGE = "ghcr.io/ssandy33/regress-frontend"


@pytest.fixture
def prune_text() -> str:
    """Raw text of the prune workflow (for keyword / ordering assertions)."""
    return PRUNE_WORKFLOW_FILE.read_text()


@pytest.fixture
def prune_config(prune_text: str) -> dict:
    """Parsed prune workflow YAML."""
    return yaml.safe_load(prune_text)


def _triggers(config: dict) -> dict:
    """Return the ``on:`` trigger block.

    PyYAML's ``safe_load`` coerces the bare ``on:`` key to the boolean ``True``
    (YAML 1.1 truthy-keyword rule), so accept either form.
    """
    if "on" in config:
        return config["on"]
    return config[True]


class TestGhcrPruneWorkflowExists:
    """AC: a scheduled prune workflow file is present and well-formed."""

    @pytest.mark.unit
    def test_ghcr_prune_workflow_exists(self, prune_config: dict) -> None:
        """The workflow file exists, parses, and declares jobs."""
        assert PRUNE_WORKFLOW_FILE.exists()
        assert prune_config.get("name")
        assert isinstance(prune_config.get("jobs"), dict)
        assert len(prune_config["jobs"]) >= 1

    @pytest.mark.unit
    def test_ghcr_prune_is_scheduled_and_manual(self, prune_config: dict) -> None:
        """Triggered on a weekly schedule AND workflow_dispatch (manual)."""
        triggers = _triggers(prune_config)
        assert "schedule" in triggers, "prune must run on a schedule (weekly cron)"
        # A cron expression is present.
        crons = [entry.get("cron") for entry in triggers["schedule"]]
        assert any(cron and len(cron.split()) == 5 for cron in crons)
        assert "workflow_dispatch" in triggers, "prune must be manually dispatchable"

    @pytest.mark.unit
    def test_ghcr_prune_dry_run_input_defaults_true(self, prune_config: dict) -> None:
        """workflow_dispatch exposes a dry_run input defaulting to true."""
        triggers = _triggers(prune_config)
        dispatch = triggers["workflow_dispatch"]
        dry_run = dispatch["inputs"]["dry_run"]
        # YAML ``default: true`` parses to a Python bool; accept the string form too.
        assert dry_run["default"] in (True, "true")

    @pytest.mark.unit
    def test_ghcr_prune_has_packages_write_permission(self, prune_config: dict) -> None:
        """packages: write is required to delete GHCR package versions."""
        perms = prune_config.get("permissions", {})
        assert perms.get("packages") == "write"

    @pytest.mark.unit
    def test_ghcr_prune_targets_both_image_namespaces(self, prune_text: str) -> None:
        """Prune governs both the backend and frontend GHCR repos."""
        # Frozen-contract image names appear (constructed from owner + package).
        assert "ssandy33" in prune_text
        assert "regress-backend" in prune_text
        assert "regress-frontend" in prune_text


class TestPruneExcludesReleaseTags:
    """AC: release-tagged images (:v*) are excluded from deletion."""

    @pytest.mark.unit
    def test_prune_excludes_release_tags(self, prune_text: str) -> None:
        """A release-tag (vX.Y.Z) exclusion exists and is a KEEP, not a delete."""
        # The release-tag exclusion matches a semver tag pattern and keeps it.
        assert "v[0-9]+\\.[0-9]+\\.[0-9]+" in prune_text
        assert "KEEP (release tag)" in prune_text


class TestPruneIsDeployAware:
    """AC: the prune reads the currently-deployed digest before any delete."""

    @pytest.mark.unit
    def test_prune_is_deploy_aware(self, prune_config: dict, prune_text: str) -> None:
        """A deploy-aware step reads deployed digests and is documented as such."""
        steps = prune_config["jobs"]["prune"]["steps"]
        step_ids = [s.get("id") for s in steps]
        assert "deployed" in step_ids, "expected a step that reads deployed digests"
        # The step exposes the deployed digests as an output the prune consumes.
        assert "deployed_digests" in prune_text
        # It is explicitly NOT age-only — it consults the Deploy run history.
        assert "deploy-aware" in prune_text.lower()
        assert "deploy.yml" in prune_text or "Deploy" in prune_text

    @pytest.mark.unit
    def test_deployed_step_runs_before_prune_step(self, prune_config: dict) -> None:
        """The deployed-digest read precedes the prune/delete step (ordering)."""
        steps = prune_config["jobs"]["prune"]["steps"]
        ids = [s.get("id") for s in steps]
        names = [s.get("name", "") for s in steps]
        deployed_idx = ids.index("deployed")
        # The delete step is the one whose name mentions pruning.
        prune_idx = next(i for i, n in enumerate(names) if "Prune" in n)
        assert deployed_idx < prune_idx, "must read deployed digests before deleting"


class TestPruneKeepsN1N2Digests:
    """AC: exclusion covers the live digest + N-1 + N-2 rollback candidates."""

    @pytest.mark.unit
    def test_prune_keeps_n1_n2_digests(self, prune_text: str) -> None:
        """Retention depth keeps the 3 most-recent deployed digests (live+N-1+N-2)."""
        # Depth of 3 = live + N-1 + N-2 is configured and referenced.
        assert "KEEP_DEPLOYED_DEPTH" in prune_text
        assert 'KEEP_DEPLOYED_DEPTH: "3"' in prune_text
        assert "N-1" in prune_text and "N-2" in prune_text
        # The deployed digests are an explicit KEEP in the delete loop.
        assert "KEEP (deployed live/N-1/N-2)" in prune_text


class TestPruneAgeRuleOnlyAfterExclusions:
    """AC: the 30-day age rule applies only after the exclusion list is checked."""

    @pytest.mark.unit
    def test_prune_age_threshold_is_30_days(self, prune_text: str) -> None:
        """The age threshold is 30 days for untagged + sha-tagged versions."""
        assert 'AGE_THRESHOLD_DAYS: "30"' in prune_text

    @pytest.mark.unit
    def test_prune_age_rule_only_after_exclusions(self, prune_text: str) -> None:
        """The age rule is gated behind both exclusions (lexical ordering)."""
        # Within the delete loop, release-tag and deployed-digest exclusions both
        # appear before the age-rule comparison. Each exclusion `continue`s the
        # loop, so a version only reaches the age check if it survived them.
        release_idx = prune_text.index("EXCLUSION 1: release-tagged")
        deployed_idx = prune_text.index("EXCLUSION 2: the live + N-1 + N-2")
        age_idx = prune_text.index("AGE RULE (applied ONLY after the exclusions")
        assert release_idx < age_idx, "release-tag exclusion must precede age rule"
        assert deployed_idx < age_idx, "deployed-digest exclusion must precede age rule"
        # The age comparison uses a cutoff derived from the threshold.
        assert "CUTOFF_EPOCH" in prune_text

    @pytest.mark.unit
    def test_prune_honors_dry_run(self, prune_text: str) -> None:
        """In dry-run mode the prune logs candidates and deletes nothing."""
        # dry-run branch logs "WOULD DELETE"; the live branch calls the GHCR
        # version-delete API. Both must be present so dry_run is genuinely honored.
        assert "WOULD DELETE" in prune_text
        assert 'if [ "${DRY_RUN}" = "true" ]' in prune_text
        assert "--method DELETE" in prune_text


class TestPruneLiveManualAC:
    """Live-validation AC that cannot run in CI — recorded as skipped per CLAUDE.md.

    Mirrors ``TestQaManualInfraACs``: keeps the AC↔verification mapping complete.
    Verified manually by running the workflow in dry-run mode and confirming the
    keep-list; the run-log is pasted into the PR.
    """

    @pytest.mark.unit
    @pytest.mark.skip(
        reason="Live: a dry-run prune against the real GHCR namespace must show "
        "the live digest + N-1 + N-2 + all release tags in the keep-list. "
        "Requires GHCR access + Deploy run history — run via workflow_dispatch "
        "(dry_run=true) and paste the keep-list output into the PR."
    )
    def test_prune_live(self) -> None:  # pragma: no cover
        ...
