"""Unit tests for the Slack webhook notification service."""

from unittest.mock import patch, MagicMock

import httpx
import pytest

from app.services.slack_notifier import SlackNotifier, get_slack_notifier


class TestSlackNotifierConfigured:
    """Tests for SlackNotifier when a webhook URL is provided."""

    def test_is_configured_with_url(self):
        """Notifier reports configured when URL is provided."""
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        assert notifier.is_configured is True

    def test_is_configured_empty_url(self):
        """Notifier reports not configured when URL is empty."""
        notifier = SlackNotifier(webhook_url="")
        assert notifier.is_configured is False

    @patch("app.services.slack_notifier.httpx.post")
    def test_notify_startup_sends_post(self, mock_post):
        """Startup notification sends POST to webhook URL."""
        mock_post.return_value = MagicMock(status_code=200)
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")

        result = notifier.notify_startup()

        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs.args[0] == "https://hooks.slack.com/test"
        payload = call_kwargs.kwargs["json"]
        assert payload["blocks"][0]["text"]["text"] == "Application Started"

    @patch("app.services.slack_notifier.httpx.post")
    def test_notify_health_degraded_sends_post(self, mock_post):
        """Health degraded notification sends POST with source details."""
        mock_post.return_value = MagicMock(status_code=200)
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")

        result = notifier.notify_health_degraded("fred", "API key not configured")

        assert result is True
        payload = mock_post.call_args.kwargs["json"]
        text_block = payload["blocks"][1]["text"]["text"]
        assert "fred" in text_block
        assert "API key not configured" in text_block

    @patch("app.services.slack_notifier.httpx.post")
    def test_notify_health_degraded_none_error(self, mock_post):
        """Health degraded notification handles None error gracefully."""
        mock_post.return_value = MagicMock(status_code=200)
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")

        result = notifier.notify_health_degraded("schwab", None)

        assert result is True
        payload = mock_post.call_args.kwargs["json"]
        assert "unknown error" in payload["blocks"][1]["text"]["text"]

    @patch("app.services.slack_notifier.httpx.post")
    def test_send_returns_false_on_http_error(self, mock_post):
        """Returns False when webhook returns non-200 status."""
        mock_post.return_value = MagicMock(status_code=403)
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")

        result = notifier.notify_startup()

        assert result is False

    @patch("app.services.slack_notifier.httpx.post")
    def test_send_returns_false_on_exception(self, mock_post):
        """Returns False and does not raise when HTTP request fails."""
        mock_post.side_effect = httpx.ConnectError("connection refused")
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")

        result = notifier.notify_startup()

        assert result is False


class TestSlackNotifierNotConfigured:
    """Tests for graceful degradation when webhook is not configured."""

    def test_no_url_skips_notification(self):
        """Notification is a no-op when URL is empty."""
        notifier = SlackNotifier(webhook_url="")

        result = notifier.notify_startup()

        assert result is False

    def test_no_url_health_degraded_skips(self):
        """Health degraded notification is a no-op when URL is empty."""
        notifier = SlackNotifier(webhook_url="")

        result = notifier.notify_health_degraded("fred", "some error")

        assert result is False

    @patch("app.services.slack_notifier.httpx.post")
    def test_no_http_call_when_not_configured(self, mock_post):
        """No HTTP call is made when webhook URL is absent."""
        notifier = SlackNotifier(webhook_url="")
        notifier.notify_startup()
        notifier.notify_health_degraded("fred", "error")

        mock_post.assert_not_called()


class TestSlackNotifierFallback:
    """Tests for config fallback behavior."""

    @patch("app.services.slack_notifier.get_slack_webhook_url", return_value="")
    def test_fallback_to_config_empty(self, mock_get_url):
        """Notifier falls back to config when no URL is provided."""
        notifier = SlackNotifier()
        assert notifier.is_configured is False

    @patch(
        "app.services.slack_notifier.get_slack_webhook_url",
        return_value="https://hooks.slack.com/from-config",
    )
    def test_fallback_to_config_with_url(self, mock_get_url):
        """Notifier uses config URL when no explicit URL is provided."""
        notifier = SlackNotifier()
        assert notifier.is_configured is True
        assert notifier.webhook_url == "https://hooks.slack.com/from-config"


class TestGetSlackNotifier:
    """Tests for the module-level singleton getter."""

    @patch("app.services.slack_notifier._default_notifier", None)
    def test_returns_singleton(self):
        """get_slack_notifier returns a SlackNotifier instance."""
        notifier = get_slack_notifier()
        assert isinstance(notifier, SlackNotifier)

    @patch("app.services.slack_notifier._default_notifier", None)
    def test_returns_same_instance(self):
        """get_slack_notifier returns the same instance on repeated calls."""
        first = get_slack_notifier()
        second = get_slack_notifier()
        assert first is second
