"""Tests for observability infrastructure configuration files (Loki + Grafana).

These tests validate the structure and content of Docker Compose, Loki,
Grafana provisioning, and Caddyfile configurations. They ensure that
all required services, volumes, dashboards, and alerting rules are
properly defined before deployment.

Note: Actual service health and connectivity are infrastructure concerns
that cannot be tested in a unit test environment. Those are verified
during deployment via Docker healthchecks.
"""

import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY_DIR = REPO_ROOT / "deploy"
COMPOSE_FILE = REPO_ROOT / "docker-compose.prod.yml"


@pytest.fixture
def compose_config() -> dict:
    """Load and parse docker-compose.prod.yml."""
    return yaml.safe_load(COMPOSE_FILE.read_text())


@pytest.fixture
def loki_config() -> dict:
    """Load and parse Loki configuration."""
    return yaml.safe_load((DEPLOY_DIR / "loki-config.yml").read_text())


class TestDockerComposeServices:
    """Verify docker-compose.prod.yml has required Loki and Grafana services."""

    def test_loki_service_exists(self, compose_config: dict) -> None:
        """Loki service is defined in docker-compose."""
        assert "loki" in compose_config["services"]

    def test_loki_uses_official_image(self, compose_config: dict) -> None:
        """Loki service uses the official Grafana Loki image."""
        loki = compose_config["services"]["loki"]
        assert loki["image"] == "grafana/loki:3.4.2"

    def test_loki_has_healthcheck(self, compose_config: dict) -> None:
        """Loki service has a healthcheck configured."""
        loki = compose_config["services"]["loki"]
        assert "healthcheck" in loki

    def test_loki_memory_limit(self, compose_config: dict) -> None:
        """Loki service respects the 256MB memory budget."""
        loki = compose_config["services"]["loki"]
        memory = loki["deploy"]["resources"]["limits"]["memory"]
        assert memory == "256M"

    def test_loki_exposes_port_3100_on_loopback(self, compose_config: dict) -> None:
        """Loki exposes port 3100 bound to 127.0.0.1 for the Docker log driver."""
        loki = compose_config["services"]["loki"]
        assert "ports" in loki
        ports = loki["ports"]
        assert any("3100" in str(p) for p in ports)
        # Verify it binds to loopback only (not externally accessible)
        assert any("127.0.0.1" in str(p) for p in ports)

    def test_grafana_service_exists(self, compose_config: dict) -> None:
        """Grafana service is defined in docker-compose."""
        assert "grafana" in compose_config["services"]

    def test_grafana_uses_official_image(self, compose_config: dict) -> None:
        """Grafana service uses the official Grafana image."""
        grafana = compose_config["services"]["grafana"]
        assert grafana["image"] == "grafana/grafana:11.5.2"

    def test_grafana_has_healthcheck(self, compose_config: dict) -> None:
        """Grafana service has a healthcheck configured."""
        grafana = compose_config["services"]["grafana"]
        assert "healthcheck" in grafana

    def test_grafana_memory_limit(self, compose_config: dict) -> None:
        """Grafana service respects the 128MB memory budget."""
        grafana = compose_config["services"]["grafana"]
        memory = grafana["deploy"]["resources"]["limits"]["memory"]
        assert memory == "128M"

    def test_grafana_depends_on_loki(self, compose_config: dict) -> None:
        """Grafana depends on Loki being healthy."""
        grafana = compose_config["services"]["grafana"]
        assert "loki" in grafana["depends_on"]

    def test_grafana_data_volume_persisted(self, compose_config: dict) -> None:
        """Grafana data volume is defined for persistence across restarts."""
        assert "grafana_data" in compose_config["volumes"]
        grafana = compose_config["services"]["grafana"]
        volume_mounts = grafana["volumes"]
        assert any("grafana_data" in str(v) for v in volume_mounts)

    def test_loki_data_volume_persisted(self, compose_config: dict) -> None:
        """Loki data volume is defined for persistence."""
        assert "loki_data" in compose_config["volumes"]

    def test_grafana_auth_disabled_anonymous(self, compose_config: dict) -> None:
        """Grafana has anonymous access disabled."""
        grafana = compose_config["services"]["grafana"]
        env_list = grafana["environment"]
        assert "GF_AUTH_ANONYMOUS_ENABLED=false" in env_list

    def test_grafana_signup_disabled(self, compose_config: dict) -> None:
        """Grafana has user sign-up disabled."""
        grafana = compose_config["services"]["grafana"]
        env_list = grafana["environment"]
        assert "GF_USERS_ALLOW_SIGN_UP=false" in env_list

    def test_grafana_serve_from_subpath(self, compose_config: dict) -> None:
        """Grafana is configured to serve from a subpath (/grafana/)."""
        grafana = compose_config["services"]["grafana"]
        env_list = grafana["environment"]
        assert "GF_SERVER_SERVE_FROM_SUB_PATH=true" in env_list

    def test_grafana_password_requires_env_var(self, compose_config: dict) -> None:
        """Grafana admin password must be set via env var with no weak default."""
        grafana = compose_config["services"]["grafana"]
        env_list = grafana["environment"]
        password_entry = next(
            e for e in env_list if e.startswith("GF_SECURITY_ADMIN_PASSWORD=")
        )
        # Must use :? syntax to fail if unset, must NOT have a weak fallback
        assert "changeme" not in password_entry
        assert ":?" in password_entry or "?Set" in password_entry


class TestDockerLogDriver:
    """Verify backend and frontend containers ship logs to Loki."""

    @pytest.mark.parametrize("service", ["backend", "frontend"])
    def test_service_has_loki_log_driver(
        self, compose_config: dict, service: str
    ) -> None:
        """Service uses Loki Docker log driver."""
        svc = compose_config["services"][service]
        assert svc["logging"]["driver"] == "loki"

    @pytest.mark.parametrize("service", ["backend", "frontend"])
    def test_service_log_driver_has_loki_url(
        self, compose_config: dict, service: str
    ) -> None:
        """Service log driver points to Loki push endpoint."""
        svc = compose_config["services"][service]
        loki_url = svc["logging"]["options"]["loki-url"]
        assert "/loki/api/v1/push" in loki_url


class TestLokiConfig:
    """Verify Loki configuration file structure and settings."""

    def test_loki_config_file_exists(self) -> None:
        """Loki config file exists in deploy directory."""
        assert (DEPLOY_DIR / "loki-config.yml").is_file()

    def test_retention_period_14_days(self, loki_config: dict) -> None:
        """Loki retention is configured for 14 days (336 hours)."""
        retention = loki_config["limits_config"]["retention_period"]
        assert retention == "336h"

    def test_compactor_retention_enabled(self, loki_config: dict) -> None:
        """Loki compactor has retention enabled."""
        assert loki_config["compactor"]["retention_enabled"] is True

    def test_local_filesystem_storage(self, loki_config: dict) -> None:
        """Loki uses local filesystem storage (not S3/GCS)."""
        storage = loki_config["common"]["storage"]["filesystem"]
        assert "chunks_directory" in storage

    def test_analytics_disabled(self, loki_config: dict) -> None:
        """Loki analytics/telemetry is disabled."""
        assert loki_config["analytics"]["reporting_enabled"] is False

    def test_single_instance_replication(self, loki_config: dict) -> None:
        """Loki is configured for single-instance (replication_factor=1)."""
        assert loki_config["common"]["replication_factor"] == 1


class TestGrafanaProvisioning:
    """Verify Grafana provisioning files for datasources and dashboards."""

    def test_loki_datasource_file_exists(self) -> None:
        """Loki datasource provisioning file exists."""
        path = DEPLOY_DIR / "grafana/provisioning/datasources/loki.yml"
        assert path.is_file()

    def test_loki_datasource_configured(self) -> None:
        """Loki datasource points to the Loki service."""
        path = DEPLOY_DIR / "grafana/provisioning/datasources/loki.yml"
        config = yaml.safe_load(path.read_text())
        datasources = config["datasources"]
        assert len(datasources) >= 1
        loki_ds = datasources[0]
        assert loki_ds["type"] == "loki"
        assert "loki" in loki_ds["url"]
        assert loki_ds["isDefault"] is True

    def test_dashboard_provider_file_exists(self) -> None:
        """Dashboard provisioning config exists."""
        path = DEPLOY_DIR / "grafana/provisioning/dashboards/dashboards.yml"
        assert path.is_file()

    def test_application_logs_dashboard_exists(self) -> None:
        """Application Logs dashboard JSON exists."""
        path = DEPLOY_DIR / "grafana/provisioning/dashboards/application-logs.json"
        assert path.is_file()

    def test_errors_dashboard_exists(self) -> None:
        """Errors dashboard JSON exists."""
        path = DEPLOY_DIR / "grafana/provisioning/dashboards/errors.json"
        assert path.is_file()


class TestApplicationLogsDashboard:
    """Verify the Application Logs dashboard content."""

    @pytest.fixture
    def dashboard(self) -> dict:
        """Load the Application Logs dashboard JSON."""
        path = DEPLOY_DIR / "grafana/provisioning/dashboards/application-logs.json"
        return json.loads(path.read_text())

    def test_dashboard_title(self, dashboard: dict) -> None:
        """Dashboard has correct title."""
        assert dashboard["title"] == "Application Logs"

    def test_has_template_variables(self, dashboard: dict) -> None:
        """Dashboard has container, level, and module template variables."""
        var_names = [v["name"] for v in dashboard["templating"]["list"]]
        assert "container" in var_names
        assert "level" in var_names
        assert "module" in var_names

    def test_has_log_panel(self, dashboard: dict) -> None:
        """Dashboard includes a logs panel."""
        panel_types = [p["type"] for p in dashboard["panels"]]
        assert "logs" in panel_types

    def test_has_unique_uid(self, dashboard: dict) -> None:
        """Dashboard has a stable UID for provisioning."""
        assert dashboard["uid"] == "app-logs"


class TestErrorsDashboard:
    """Verify the Errors dashboard content."""

    @pytest.fixture
    def dashboard(self) -> dict:
        """Load the Errors dashboard JSON."""
        path = DEPLOY_DIR / "grafana/provisioning/dashboards/errors.json"
        return json.loads(path.read_text())

    def test_dashboard_title(self, dashboard: dict) -> None:
        """Dashboard has correct title."""
        assert dashboard["title"] == "Errors"

    def test_filters_error_warning_levels(self, dashboard: dict) -> None:
        """Dashboard queries filter for ERROR and WARNING levels."""
        log_panel = next(p for p in dashboard["panels"] if p["type"] == "logs")
        expr = log_panel["targets"][0]["expr"]
        assert "ERROR" in expr
        assert "WARNING" in expr

    def test_has_stat_panels(self, dashboard: dict) -> None:
        """Dashboard has stat panels for error/warning counts."""
        stat_panels = [p for p in dashboard["panels"] if p["type"] == "stat"]
        assert len(stat_panels) >= 2

    def test_has_unique_uid(self, dashboard: dict) -> None:
        """Dashboard has a stable UID for provisioning."""
        assert dashboard["uid"] == "errors"


class TestAlertingConfig:
    """Verify Grafana alerting provisioning."""

    @pytest.fixture
    def alert_config(self) -> dict:
        """Load the alerting provisioning YAML."""
        path = DEPLOY_DIR / "grafana/provisioning/alerting/alerts.yml"
        return yaml.safe_load(path.read_text())

    def test_alerting_file_exists(self) -> None:
        """Alerting provisioning file exists."""
        path = DEPLOY_DIR / "grafana/provisioning/alerting/alerts.yml"
        assert path.is_file()

    def test_contact_point_configured(self, alert_config: dict) -> None:
        """At least one contact point is configured."""
        assert len(alert_config["contactPoints"]) >= 1

    def test_contact_point_type(self, alert_config: dict) -> None:
        """Contact point uses Slack webhook."""
        cp = alert_config["contactPoints"][0]
        receiver = cp["receivers"][0]
        assert receiver["type"] == "slack"

    def test_alert_rule_exists(self, alert_config: dict) -> None:
        """At least one alert rule group is defined."""
        assert len(alert_config["groups"]) >= 1

    def test_error_rate_alert_threshold(self, alert_config: dict) -> None:
        """Error rate alert has a threshold > 5 errors."""
        rule = alert_config["groups"][0]["rules"][0]
        assert rule["title"] == "High Error Rate"
        # Find the threshold condition
        threshold_data = next(d for d in rule["data"] if d["refId"] == "C")
        threshold_value = threshold_data["model"]["conditions"][0]["evaluator"]["params"][0]
        assert threshold_value == 5

    def test_notification_policy_exists(self, alert_config: dict) -> None:
        """A notification policy routes alerts to the contact point."""
        policies = alert_config["policies"]
        assert len(policies) >= 1
        assert policies[0]["receiver"] == "slack-webhook"


class TestCaddyfileGrafanaRoute:
    """Verify Caddyfile has Grafana reverse proxy route."""

    @pytest.fixture
    def caddyfile_content(self) -> str:
        """Load the Caddyfile content."""
        return (DEPLOY_DIR / "Caddyfile").read_text()

    def test_grafana_route_exists(self, caddyfile_content: str) -> None:
        """Caddyfile has a /grafana route."""
        assert "/grafana/" in caddyfile_content

    def test_grafana_proxies_to_service(self, caddyfile_content: str) -> None:
        """Caddyfile proxies /grafana to the grafana service on port 3000."""
        assert "grafana:3000" in caddyfile_content

    def test_grafana_route_before_catch_all(self, caddyfile_content: str) -> None:
        """Grafana route is defined before the frontend catch-all handler."""
        grafana_pos = caddyfile_content.index("/grafana/")
        catchall_pos = caddyfile_content.index("handle {")
        assert grafana_pos < catchall_pos

    def test_grafana_route_clears_csp_header(self, caddyfile_content: str) -> None:
        """Grafana handler clears the global CSP so Grafana can manage its own."""
        # Find the grafana handler block and check it contains CSP clearing
        grafana_block_start = caddyfile_content.index("handle_path /grafana/*")
        grafana_block = caddyfile_content[grafana_block_start:grafana_block_start + 300]
        assert 'Content-Security-Policy ""' in grafana_block


@pytest.mark.skip(
    reason="Docker service health requires running containers — verified during deployment"
)
class TestLokiServiceHealth:
    """Loki service health verification (requires running Docker environment)."""

    def test_loki_ready_endpoint(self) -> None:
        """Loki /ready endpoint returns 200."""

    def test_grafana_health_endpoint(self) -> None:
        """Grafana /api/health endpoint returns 200."""

    def test_log_ingestion(self) -> None:
        """Logs from backend container appear in Loki."""
