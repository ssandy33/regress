"""Tests for the QA environment configuration (issue #330).

Validates the structure of ``docker-compose.qa.yml``, the QA ``deploy/Caddyfile``
site block, and the snapshot-selection helper used by ``deploy/qa-refresh-db.sh``.
These are static-config / pure-logic assertions — there is no FastAPI app, no
TestClient, no DB session, and no network — so they are ``@pytest.mark.unit``.

Following the established pattern in ``test_observability_configs.py``, the
compose file is parsed directly with PyYAML rather than shelling out to
``docker compose config`` (the docker CLI is not available in the unit-test
runner). The CI ``qa-compose-validate`` step in ``.github/workflows/ci.yml``
runs ``docker compose -f docker-compose.qa.yml config -q`` as the live
schema-validation gate (the dynamic mirror of these static assertions).

Live infrastructure ACs that cannot run in CI are recorded as skipped tests with
a rationale (DNS, TLS issuance, OAuth-app registration, on-VPS refresh run,
degraded-mode smoke) so the AC↔verification mapping stays complete.
"""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY_DIR = REPO_ROOT / "deploy"
QA_COMPOSE_FILE = REPO_ROOT / "docker-compose.qa.yml"
PROD_COMPOSE_FILE = REPO_ROOT / "docker-compose.prod.yml"
CADDYFILE = DEPLOY_DIR / "Caddyfile"

# Documented QA memory cap (4 GB box, comfortable tier). Sum of per-service
# limits must not exceed this. See the PR body / plan Resource Budget.
QA_MEMORY_CAP_MB = 576


def _mem_limit_to_mb(value: str) -> int:
    """Parse a compose memory limit string (e.g. '384M', '1G') to MB."""
    value = value.strip().upper()
    if value.endswith("G"):
        return int(float(value[:-1]) * 1024)
    if value.endswith("M"):
        return int(float(value[:-1]))
    # Bare bytes
    return int(value) // (1024 * 1024)


@pytest.fixture
def qa_config() -> dict:
    """Load and parse docker-compose.qa.yml."""
    return yaml.safe_load(QA_COMPOSE_FILE.read_text())


@pytest.fixture
def prod_config() -> dict:
    """Load and parse docker-compose.prod.yml."""
    return yaml.safe_load(PROD_COMPOSE_FILE.read_text())


@pytest.fixture
def caddyfile_content() -> str:
    """Load the Caddyfile content."""
    return CADDYFILE.read_text()


class TestQaComposeServices:
    """Service-set and per-service env invariants of the QA compose."""

    @pytest.mark.unit
    def test_qa_compose_parses_and_has_backend_frontend_only(self, qa_config: dict) -> None:
        """QA defines exactly backend + frontend — no loki/grafana/caddy."""
        assert set(qa_config["services"].keys()) == {"backend", "frontend"}

    @pytest.mark.unit
    def test_qa_compose_no_host_port_mappings(self, qa_config: dict) -> None:
        """QA exposes no host ports (reached only via prod Caddy)."""
        for svc in qa_config["services"].values():
            assert "ports" not in svc

    @pytest.mark.unit
    def test_qa_compose_volumes_are_qa_prefixed(self, qa_config: dict) -> None:
        """Top-level volume is qa_-prefixed; no bare prod-style sqlite_data."""
        assert "qa_sqlite_data" in qa_config["volumes"]
        assert "sqlite_data" not in qa_config["volumes"]

    @pytest.mark.unit
    def test_qa_compose_backend_mounts_qa_volume(self, qa_config: dict) -> None:
        """Backend mounts the qa_sqlite_data volume at /app/data."""
        volumes = qa_config["services"]["backend"]["volumes"]
        assert "qa_sqlite_data:/app/data" in volumes

    @pytest.mark.unit
    def test_qa_compose_memory_limits_set_on_all_services(self, qa_config: dict) -> None:
        """Each service carries its documented cap (backend 384M, frontend 192M); sum <= cap."""
        expected_mb = {"backend": 384, "frontend": 192}
        total = 0
        for name, svc in qa_config["services"].items():
            mem = _mem_limit_to_mb(svc["deploy"]["resources"]["limits"]["memory"])
            assert mem == expected_mb[name]
            total += mem
        assert total <= QA_MEMORY_CAP_MB

    @pytest.mark.unit
    def test_qa_compose_omits_schwab_encryption_key(self, qa_config: dict) -> None:
        """Schwab vars absent — QA runs in degraded (no-Schwab) mode."""
        env = qa_config["services"]["backend"]["environment"]
        env_keys = {item.split("=", 1)[0] for item in env}
        assert "SCHWAB_ENCRYPTION_KEY" not in env_keys

    @pytest.mark.unit
    def test_qa_compose_no_loki_logging_driver(self, qa_config: dict) -> None:
        """Neither service uses the loki log driver (QA has no Loki)."""
        for svc in qa_config["services"].values():
            logging_block = svc.get("logging", {})
            assert logging_block.get("driver") != "loki"

    @pytest.mark.unit
    def test_qa_compose_axiom_dataset_is_qa(self, qa_config: dict) -> None:
        """Backend routes Axiom logs to the dedicated regression-tool-qa dataset."""
        env = qa_config["services"]["backend"]["environment"]
        dataset_line = next(e for e in env if e.startswith("AXIOM_DATASET="))
        assert "regression-tool-qa" in dataset_line

    @pytest.mark.unit
    def test_qa_compose_nextauth_url_is_qa_subdomain(self, qa_config: dict) -> None:
        """Frontend NEXTAUTH_URL targets the qa. subdomain."""
        env = qa_config["services"]["frontend"]["environment"]
        url_line = next(e for e in env if e.startswith("NEXTAUTH_URL="))
        assert "qa." in url_line.split("=", 1)[1]

    @pytest.mark.unit
    def test_qa_compose_frontend_api_origin_targets_qa_backend(self, qa_config: dict) -> None:
        """Frontend talks to qa-backend, not the prod backend alias."""
        env = qa_config["services"]["frontend"]["environment"]
        origin_line = next(e for e in env if e.startswith("INTERNAL_API_ORIGIN="))
        assert "qa-backend" in origin_line


class TestQaComposeNetwork:
    """Shared external caddy_net wiring."""

    @pytest.mark.unit
    def test_qa_compose_joins_external_caddy_net(self, qa_config: dict) -> None:
        """caddy_net is declared external and both services attach to it."""
        net = qa_config["networks"]["caddy_net"]
        assert net["external"] is True
        for name in ("backend", "frontend"):
            assert "caddy_net" in qa_config["services"][name]["networks"]

    @pytest.mark.unit
    def test_qa_compose_service_aliases(self, qa_config: dict) -> None:
        """Services publish the qa-backend / qa-frontend aliases on caddy_net."""
        backend_net = qa_config["services"]["backend"]["networks"]["caddy_net"]
        frontend_net = qa_config["services"]["frontend"]["networks"]["caddy_net"]
        assert "qa-backend" in backend_net["aliases"]
        assert "qa-frontend" in frontend_net["aliases"]


class TestProdComposeNetwork:
    """The prod compose must also join caddy_net so its Caddy can reach QA."""

    @pytest.mark.unit
    def test_prod_compose_declares_external_caddy_net(self, prod_config: dict) -> None:
        """Prod declares caddy_net as an external network."""
        assert prod_config["networks"]["caddy_net"]["external"] is True

    @pytest.mark.unit
    def test_prod_caddy_joins_caddy_net(self, prod_config: dict) -> None:
        """The prod caddy service attaches to caddy_net to route to QA."""
        assert "caddy_net" in prod_config["services"]["caddy"]["networks"]


class TestQaCaddyfile:
    """QA site block in the shared Caddyfile."""

    @pytest.mark.unit
    def test_caddyfile_has_qa_site_block(self, caddyfile_content: str) -> None:
        """A qa.{$DOMAIN} site block exists."""
        assert "qa.{$DOMAIN} {" in caddyfile_content

    @pytest.mark.unit
    def test_qa_block_routes_to_qa_aliases(self, caddyfile_content: str) -> None:
        """The QA block reverse-proxies to qa-backend / qa-frontend."""
        qa_start = caddyfile_content.index("qa.{$DOMAIN} {")
        qa_block = caddyfile_content[qa_start:]
        assert "qa-backend:8000" in qa_block
        assert "qa-frontend:8080" in qa_block

    @pytest.mark.unit
    def test_qa_block_has_no_grafana_handler(self, caddyfile_content: str) -> None:
        """QA block has no /grafana handler (QA has no Grafana)."""
        qa_start = caddyfile_content.index("qa.{$DOMAIN} {")
        qa_block = caddyfile_content[qa_start:]
        assert "/grafana" not in qa_block

    @pytest.mark.unit
    def test_qa_block_has_no_basic_auth_placeholder(self, caddyfile_content: str) -> None:
        """QA block omits the BASIC_AUTH placeholder (prod-only injection)."""
        qa_start = caddyfile_content.index("qa.{$DOMAIN} {")
        qa_block = caddyfile_content[qa_start:]
        assert "BASIC_AUTH_BLOCK" not in qa_block

    @pytest.mark.unit
    def test_prod_caddy_block_unchanged(self, caddyfile_content: str) -> None:
        """The prod {$DOMAIN} block still proxies to backend/frontend, not qa-*."""
        # The prod block is the leading site block, before the QA section
        # header comment. Slicing on that sentinel avoids matching the literal
        # "{$DOMAIN} {" that also appears inside "qa.{$DOMAIN} {".
        prod_block = caddyfile_content.split("# QA site block", 1)[0]
        assert prod_block.startswith("{$DOMAIN} {")
        assert "backend:8000" in prod_block
        assert "frontend:8080" in prod_block
        assert "qa-backend" not in prod_block
        assert "qa-frontend" not in prod_block


class TestQaSnapshotSelection:
    """Pure-logic tests for the refresh-script snapshot selection helper."""

    @pytest.mark.unit
    def test_qa_refresh_db_selects_newest_snapshot(self, tmp_path: Path) -> None:
        """select_newest_snapshot picks the most recently modified snapshot."""
        from scripts.qa_snapshot import select_newest_snapshot

        old = tmp_path / "regression_tool_20260101_000000.db"
        new = tmp_path / "regression_tool_20260201_000000.db"
        old.write_bytes(b"old")
        new.write_bytes(b"new")
        # Force a clear mtime ordering regardless of write order.
        import os

        os.utime(old, (1000, 1000))
        os.utime(new, (2000, 2000))

        assert select_newest_snapshot(tmp_path) == new.resolve()

    @pytest.mark.unit
    def test_qa_refresh_db_idempotent_overwrite(self, tmp_path: Path) -> None:
        """Re-selecting yields the same single snapshot (no duplication)."""
        from scripts.qa_snapshot import select_newest_snapshot

        snap = tmp_path / "regression_tool_20260201_000000.db"
        snap.write_bytes(b"data")

        first = select_newest_snapshot(tmp_path)
        second = select_newest_snapshot(tmp_path)
        assert first == second == snap.resolve()
        # Only one snapshot present — selection never created copies.
        assert len(list(tmp_path.glob("regression_tool_*.db"))) == 1

    @pytest.mark.unit
    def test_qa_refresh_db_no_snapshot_raises(self, tmp_path: Path) -> None:
        """Empty backup dir raises a clear FileNotFoundError."""
        from scripts.qa_snapshot import select_newest_snapshot

        with pytest.raises(FileNotFoundError):
            select_newest_snapshot(tmp_path)

    @pytest.mark.unit
    def test_qa_refresh_db_missing_dir_raises(self, tmp_path: Path) -> None:
        """Nonexistent backup dir raises a clear FileNotFoundError."""
        from scripts.qa_snapshot import select_newest_snapshot

        with pytest.raises(FileNotFoundError):
            select_newest_snapshot(tmp_path / "does-not-exist")


class TestOpsScriptInvariants:
    """Text invariants on deploy scripts for the #332 rollout fixes."""

    @pytest.mark.unit
    def test_backup_sh_targets_exact_prod_volume(self) -> None:
        """backup.sh resolves the prod volume by exact name, not a loose grep.

        With the QA stack deployed, `grep sqlite_data | head -1` matches
        `regress-qa_qa_sqlite_data` first (`-` sorts before `_`) and would
        silently back up the QA database (#332).
        """
        content = (DEPLOY_DIR / "backup.sh").read_text()
        assert 'PROD_VOLUME="regress_sqlite_data"' in content
        assert 'grep -qx "$PROD_VOLUME"' in content
        assert "grep sqlite_data | head -1" not in content

    @pytest.mark.unit
    def test_qa_refresh_db_scrubs_all_encrypted_setting_keys(self) -> None:
        """qa-refresh-db.sh scrubs every ENCRYPTED_SETTING_KEYS row post-restore.

        QA has no SCHWAB_ENCRYPTION_KEY; the backend's fail-closed startup
        check refuses to boot while these rows exist (#332). The script's
        DELETE must cover the canonical key list from app.services.encryption
        so the two can't drift.
        """
        from app.services.encryption import ENCRYPTED_SETTING_KEYS

        content = (DEPLOY_DIR / "qa-refresh-db.sh").read_text()
        assert "DELETE FROM app_settings" in content
        for key in ENCRYPTED_SETTING_KEYS:
            assert f"'{key}'" in content

    @pytest.mark.unit
    def test_qa_refresh_db_uses_python3_on_host(self) -> None:
        """Host-side snapshot selection calls python3 — the VPS has no bare python (#332)."""
        content = (DEPLOY_DIR / "qa-refresh-db.sh").read_text()
        assert "python3 -m scripts.qa_snapshot" in content


class TestQaManualInfraACs:
    """Live-infra ACs that cannot run in CI — recorded as skipped per CLAUDE.md.

    These keep the AC↔verification mapping complete. They are verified manually
    on the VPS and documented in deploy/qa/README.md; the run-log is pasted into
    the PR description.
    """

    @pytest.mark.unit
    @pytest.mark.skip(reason="M1: DNS A record qa.<domain> is external infra — verify with `dig qa.<domain>`.")
    def test_qa_dns_a_record_resolves(self) -> None:  # pragma: no cover
        ...

    @pytest.mark.unit
    @pytest.mark.skip(reason="M2: qa.<domain> auto-TLS depends on live Caddy + DNS — verify with `curl -I https://qa.<domain>`.")
    def test_qa_serves_valid_tls_cert(self) -> None:  # pragma: no cover
        ...

    @pytest.mark.unit
    @pytest.mark.skip(reason="M3: GitHub OAuth app registration is a manual console step — cannot register in CI.")
    def test_qa_github_oauth_app_login(self) -> None:  # pragma: no cover
        ...

    @pytest.mark.unit
    @pytest.mark.skip(reason="M4: qa-refresh-db.sh end-to-end needs the real prod volume + docker on the VPS — run-log pasted into PR.")
    def test_qa_refresh_db_live_run(self) -> None:  # pragma: no cover
        ...

    @pytest.mark.unit
    @pytest.mark.skip(reason="M5: degraded-mode (no-Schwab) live smoke — verify with `curl https://qa.<domain>/api/health` post-deploy.")
    def test_qa_starts_in_degraded_mode(self) -> None:  # pragma: no cover
        ...
