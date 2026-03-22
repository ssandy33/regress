"""Slack webhook notification service for operational events."""

import logging
from datetime import datetime, timezone

import httpx

from app.config import get_slack_webhook_url

logger = logging.getLogger(__name__)

# Timeout for outbound Slack webhook requests (seconds)
_WEBHOOK_TIMEOUT = 10.0


class SlackNotifier:
    """Sends formatted messages to a Slack incoming webhook.

    Gracefully no-ops when no webhook URL is configured.
    """

    def __init__(self, webhook_url: str | None = None) -> None:
        self._webhook_url = webhook_url

    @property
    def webhook_url(self) -> str:
        """Resolve the webhook URL, falling back to config if not provided."""
        if self._webhook_url is not None:
            return self._webhook_url
        return get_slack_webhook_url()

    @property
    def is_configured(self) -> bool:
        """Return True if a webhook URL is available."""
        return bool(self.webhook_url)

    def _send(self, payload: dict) -> bool:
        """Post a JSON payload to the Slack webhook.

        Returns True on success, False on failure. Never raises.
        """
        url = self.webhook_url
        if not url:
            logger.debug("Slack webhook not configured, skipping notification")
            return False
        try:
            resp = httpx.post(url, json=payload, timeout=_WEBHOOK_TIMEOUT)
            if resp.status_code != 200:
                logger.warning(
                    "Slack webhook returned HTTP %d", resp.status_code
                )
                return False
            return True
        except httpx.HTTPError:
            logger.warning("Slack webhook request failed")
            return False

    def notify_startup(self) -> bool:
        """Send a deploy/startup notification."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "Application Started",
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Regression Tool backend started at *{now}*.",
                    },
                },
            ]
        }
        return self._send(payload)

    def notify_health_degraded(self, source: str, error: str | None) -> bool:
        """Send a notification when a health check reports degraded status.

        Args:
            source: Name of the degraded data source (e.g. 'fred', 'schwab').
            error: Brief error description, or None.
        """
        detail = error or "unknown error"
        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "Health Check Degraded",
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{source}* is unavailable: {detail}",
                    },
                },
            ]
        }
        return self._send(payload)


# Module-level singleton for convenience
_default_notifier: SlackNotifier | None = None


def get_slack_notifier() -> SlackNotifier:
    """Return the module-level SlackNotifier singleton."""
    global _default_notifier
    if _default_notifier is None:
        _default_notifier = SlackNotifier()
    return _default_notifier
