import pytest
import queue
from unittest.mock import patch, MagicMock

from app.services.slack_notifier import SlackNotifier


class TestHealthEndpoints:
    @pytest.mark.integration
    def test_health_check(self, client):
        """Top-level health probe returns ``status: ok`` and a logging block.

        Issue #274: bridge edit from the legacy ``{"status": "ok"}``
        equality check. The endpoint moved from an inline handler in
        ``app.main`` to ``app.routers.health`` and gained an additive
        ``logging`` self-monitoring subsection. The status-only contract
        is preserved as a substring assertion.
        """
        response = client.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert "logging" in body

    @pytest.mark.integration
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

    @pytest.mark.integration
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

    @pytest.mark.integration
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

    @pytest.mark.integration
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


# ---------------------------------------------------------------------------
# Issue #274 — /api/health logging self-monitoring block
# ---------------------------------------------------------------------------


class TestLoggingSelfMonitoring:
    """The ``/api/health`` body includes an Axiom-handler ``logging`` subsection.

    Schema is frozen by the v1.0.10 plan §2.3. These tests assert the
    field names + types + defaults exactly. Implementation-internal state
    (handler class, lock semantics) is intentionally not asserted.
    """

    _EXPECTED_KEYS = {
        "axiom_enabled",
        "queue_depth",
        "queue_capacity",
        "dropped_total",
        "last_flush_at",
        "last_flush_error",
    }

    @pytest.mark.integration
    def test_health_includes_logging_block_when_axiom_disabled(self, client):
        """No token → zero/null defaults, schema still present, HTTP 200."""
        with patch("app.routers.health._get_axiom_handler", return_value=None), \
             patch("app.config.settings.axiom_api_token", None, create=True):
            response = client.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert "logging" in body
        log = body["logging"]
        assert set(log.keys()) == self._EXPECTED_KEYS
        assert log == {
            "axiom_enabled": False,
            "queue_depth": 0,
            "queue_capacity": 1000,
            "dropped_total": 0,
            "last_flush_at": None,
            "last_flush_error": None,
        }

    @pytest.mark.integration
    def test_health_logging_block_when_axiom_enabled_zero_traffic(self, client):
        """Axiom attached but no flushes yet → ``axiom_enabled=true`` and nulls."""
        from app import logging_axiom
        from app.logging_axiom import AxiomHandler

        # Patch httpx at construction time so the worker has a fake client
        # and cannot touch the network before we stop() it.
        with patch.object(logging_axiom, "httpx") as mock_httpx:
            mock_httpx.Client.return_value = MagicMock()
            mock_httpx.HTTPError = Exception
            handler = AxiomHandler(token="t", dataset="d")
        # Halt the worker so it can't race with the request thread reading
        # last_flush_*; the test asserts pre-flush state only.
        handler._worker.stop()
        handler._worker.join(timeout=1.0)
        try:
            with patch("app.routers.health._get_axiom_handler", return_value=handler):
                response = client.get("/api/health")
            assert response.status_code == 200
            log = response.json()["logging"]
            assert set(log.keys()) == self._EXPECTED_KEYS
            assert log["axiom_enabled"] is True
            assert log["queue_depth"] == 0
            assert log["queue_capacity"] == 1000
            assert log["dropped_total"] == 0
            assert log["last_flush_at"] is None
            assert log["last_flush_error"] is None
        finally:
            handler._atexit_flush()

    @pytest.mark.integration
    def test_health_logging_dropped_total_reflects_overflow(self, client, monkeypatch):
        """Overflowing the handler's queue increments ``dropped_total``."""
        from app import logging_axiom
        from app.logging_axiom import AxiomHandler

        # Shrink the queue + the worker's blocking-get so ``stop() + join()``
        # actually halts the worker before our emit() loop races with it.
        monkeypatch.setattr(logging_axiom, "QUEUE_MAX", 2)
        monkeypatch.setattr(logging_axiom, "BATCH_TIMEOUT_S", 0.05)

        # Also patch ``httpx`` at construction time so the worker has a
        # fake client and cannot reach the network even if it briefly
        # drains an item before stopping.
        with patch.object(logging_axiom, "httpx") as mock_httpx:
            mock_httpx.Client.return_value = MagicMock()
            mock_httpx.HTTPError = Exception
            handler = AxiomHandler(token="t", dataset="d")
        # Wait for the worker to definitively exit. BATCH_TIMEOUT_S above is
        # 0.05s, so join(timeout=1.0) is ~20x the blocking window.
        handler._worker.stop()
        handler._worker.join(timeout=1.0)
        assert not handler._worker.is_alive(), "worker must be halted before emit"
        try:
            # Fill (2) then overflow by 3 → at least 3 drops.
            record = logging.LogRecord(
                name="test.health",
                level=logging.INFO,
                pathname=__file__,
                lineno=1,
                msg="msg",
                args=None,
                exc_info=None,
            )
            record.request_id = "-"  # type: ignore[attr-defined]
            # Drain whatever the worker may have pulled before stop() took
            # effect, so the dropped-count assertion below measures our
            # overflow delta only.
            while True:
                try:
                    handler._q.get_nowait()
                except queue.Empty:
                    break
            for _ in range(handler.queue_capacity + 3):
                handler.emit(record)
            assert handler.dropped >= 3

            with patch("app.routers.health._get_axiom_handler", return_value=handler):
                response = client.get("/api/health")
            assert response.status_code == 200
            log = response.json()["logging"]
            assert log["dropped_total"] >= 3
            assert log["queue_capacity"] == 2
            assert log["queue_depth"] == 2
        finally:
            handler._atexit_flush()

    @pytest.mark.integration
    def test_health_endpoint_makes_no_outbound_http(self, client):
        """The endpoint must never reach the network when answering."""
        # If anything inside /api/health tried to make an httpx call, this
        # patch on the axiom module's bound ``httpx`` would raise. The
        # endpoint must still return 200.
        with patch("app.logging_axiom.httpx") as mock_httpx:
            mock_httpx.Client.side_effect = AssertionError(
                "/api/health must not construct an httpx client"
            )
            mock_httpx.HTTPError = Exception
            response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    @pytest.mark.integration
    def test_health_returns_200_when_handler_attr_raises(self, client):
        """Defensive: a logging-internal hiccup must not 500 the health endpoint."""
        # Build a fake handler that raises on queue_depth read. The endpoint
        # should swallow the error and fall back to the documented default.
        class _ExplodingHandler:
            @property
            def queue_depth(self) -> int:
                raise RuntimeError("kaboom")

            @property
            def queue_capacity(self) -> int:
                return 1000

            @property
            def dropped(self) -> int:
                return 0

            @property
            def last_flush_at(self) -> str | None:
                return None

            @property
            def last_flush_error(self) -> str | None:
                return None

        with patch("app.routers.health._get_axiom_handler", return_value=_ExplodingHandler()):
            response = client.get("/api/health")
        assert response.status_code == 200
        log = response.json()["logging"]
        # Fallback default per the helper's docstring.
        assert log["queue_depth"] == 0
        # Other fields still resolve normally.
        assert log["queue_capacity"] == 1000
        assert log["axiom_enabled"] is True

    @pytest.mark.integration
    def test_health_logging_block_axiom_enabled_reflects_token_when_no_handler(self, client):
        """``axiom_enabled`` follows the token even when the handler is missing.

        Covers the edge case where the settings token is set but
        ``setup_logging()`` failed to attach a handler (init crash). The
        schema must still render and report the truthiness of the token so
        operators can distinguish "Axiom unconfigured" from "Axiom misconfigured".
        """
        from app import config as cfg

        with patch.object(cfg.settings, "axiom_api_token", "test-tok", create=True), \
             patch("app.routers.health._get_axiom_handler", return_value=None):
            response = client.get("/api/health")
        assert response.status_code == 200
        log = response.json()["logging"]
        assert log["axiom_enabled"] is True
        assert log["queue_depth"] == 0
        assert log["queue_capacity"] == 1000


# ---------------------------------------------------------------------------
# Issue #274 — unit coverage on AxiomHandler last_flush_* bookkeeping
# ---------------------------------------------------------------------------


class TestAxiomHandlerFlushBookkeeping:
    """The handler exposes ``last_flush_at`` / ``last_flush_error`` written by the worker.

    These cover the new instance state plumbing — the actual end-to-end
    integration with the worker's HTTP path is covered by the test_logging_axiom
    suite. Here we drive the setters directly so we never hit the network.
    """

    @pytest.mark.unit
    def test_last_flush_ok_sets_timestamp_clears_error(self):
        from app.logging_axiom import AxiomHandler

        handler = AxiomHandler(token="t", dataset="d")
        try:
            handler._set_last_flush_err("ingest failed status=401")
            assert handler.last_flush_error == "ingest failed status=401"
            assert handler.last_flush_at is None

            handler._set_last_flush_ok("2026-05-22T12:00:00.000Z")
            assert handler.last_flush_at == "2026-05-22T12:00:00.000Z"
            assert handler.last_flush_error is None
        finally:
            handler._atexit_flush()

    @pytest.mark.unit
    def test_queue_depth_and_capacity_accessors(self, monkeypatch):
        from app import logging_axiom
        from app.logging_axiom import AxiomHandler

        monkeypatch.setattr(logging_axiom, "QUEUE_MAX", 7)
        handler = AxiomHandler(token="t", dataset="d")
        try:
            assert handler.queue_capacity == 7
            assert handler.queue_depth == 0
        finally:
            handler._atexit_flush()


# Required import for the new tests above — placed at file bottom because
# the existing imports are minimal; an in-file import keeps the bridge edit
# narrow and avoids reshuffling test_integration_health's header.
import logging  # noqa: E402
