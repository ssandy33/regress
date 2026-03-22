from unittest.mock import patch, MagicMock

from app.services.slack_notifier import SlackNotifier


class TestHealthEndpoints:
    def test_health_check(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_health_sources(self, client):
        with (
            patch("app.routers.health._check_alpha_vantage", return_value={"available": True, "error": None}),
            patch("app.routers.health._check_fred", return_value={"available": False, "error": "No key"}),
            patch("app.routers.health._check_zillow", return_value={"available": True, "error": None}),
        ):
            response = client.get("/api/health/sources")
            assert response.status_code == 200
            data = response.json()
            assert data["alpha_vantage"]["available"] is True
            assert data["fred"]["available"] is False
            assert data["zillow"]["available"] is True
            assert data["all_down"] is False

    def test_health_sources_includes_slack_when_configured(self, client):
        """Slack status appears in health response when webhook is configured."""
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        with (
            patch("app.routers.health._check_alpha_vantage", return_value={"available": True, "error": None}),
            patch("app.routers.health._check_fred", return_value={"available": True, "error": None}),
            patch("app.routers.health._check_zillow", return_value={"available": True, "error": None}),
            patch("app.routers.health._check_schwab", return_value={"available": True, "error": None}),
            patch("app.routers.health.get_slack_notifier", return_value=notifier),
        ):
            response = client.get("/api/health/sources")
            assert response.status_code == 200
            data = response.json()
            assert "slack" in data
            assert data["slack"]["available"] is True

    def test_health_sources_no_slack_when_not_configured(self, client):
        """Slack status is absent from health response when webhook is not configured."""
        notifier = SlackNotifier(webhook_url="")
        with (
            patch("app.routers.health._check_alpha_vantage", return_value={"available": True, "error": None}),
            patch("app.routers.health._check_fred", return_value={"available": True, "error": None}),
            patch("app.routers.health._check_zillow", return_value={"available": True, "error": None}),
            patch("app.routers.health._check_schwab", return_value={"available": True, "error": None}),
            patch("app.routers.health.get_slack_notifier", return_value=notifier),
        ):
            response = client.get("/api/health/sources")
            assert response.status_code == 200
            data = response.json()
            assert "slack" not in data

    def test_health_sources_sends_degraded_notifications(self, client):
        """Slack notifications are sent for degraded sources."""
        notifier = MagicMock(spec=SlackNotifier)
        notifier.is_configured = True
        with (
            patch("app.routers.health._check_alpha_vantage", return_value={"available": True, "error": None}),
            patch("app.routers.health._check_fred", return_value={"available": False, "error": "No key"}),
            patch("app.routers.health._check_zillow", return_value={"available": True, "error": None}),
            patch("app.routers.health._check_schwab", return_value={"available": False, "error": "Not configured"}),
            patch("app.routers.health.get_slack_notifier", return_value=notifier),
            patch("app.routers.health._check_slack", return_value={"available": True, "error": None}),
        ):
            response = client.get("/api/health/sources")
            assert response.status_code == 200
            # Two sources are degraded: fred and schwab
            assert notifier.notify_health_degraded.call_count == 2
            call_args = [c.args for c in notifier.notify_health_degraded.call_args_list]
            sources_notified = {args[0] for args in call_args}
            assert sources_notified == {"fred", "schwab"}
