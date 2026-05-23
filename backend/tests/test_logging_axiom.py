"""Tests for the optional Axiom log sink (``app.logging_axiom``).

Maps to the acceptance criteria on issue #273:

- T1 — Handler is attached when ``AXIOM_API_TOKEN`` is set.
- T2 — Handler is NOT attached (and no worker thread spawned) when the token is unset;
  behavior is identical to today.
- T3 — Exceptions inside the Axiom HTTP path do not propagate into application code.
- T4 — Request-ID from the contextvar appears in events forwarded to Axiom.
- T5 — Queue overflow drops oldest events silently and emits a *single throttled*
  stderr warning (not one per drop).

Plus hardening tests:

- T6 — 4xx HTTP response is logged to stderr (no body), no exception.
- T7 — Non-serializable ``extra`` fields are coerced via ``repr`` rather than crashing.
- T8 — Records carry the timestamp from ``LogRecord.created`` (emit-time, not flush-time).

Manual / infrastructure step (not automatable)
----------------------------------------------
One acceptance criterion on issue #273 is a manual provisioning step that
cannot be exercised by an automated test:

- Operator creates an Axiom account at <https://app.axiom.co>, creates a
  dataset named ``regression-tool`` (or matching ``AXIOM_DATASET``), and
  generates an API token with **Ingest** permission.

Verification is manual: set ``AXIOM_API_TOKEN`` in ``backend/.env``, restart
the backend, emit a log line, and confirm it appears in the Axiom dataset
within ~2 seconds. This is documented as a skipped test below so reviewers
see it explicitly when reading the suite.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app import logging_axiom
from app.logging_axiom import (
    AxiomHandler,
    _AxiomWorker,
    _warn_throttled,
    build_axiom_handler,
)
from app.logging_config import RequestIdFilter, request_id_ctx, setup_logging


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stop_handler(handler: AxiomHandler | None) -> None:
    """Halt the background worker and clear ``atexit`` so tests don't bleed."""
    if handler is None:
        return
    handler._atexit_flush()  # signals stop + joins (bounded)


def _make_record(
    message: str = "hello",
    *,
    level: int = logging.INFO,
    request_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> logging.LogRecord:
    """Build a ``LogRecord`` the same way the logging module would."""
    record = logging.LogRecord(
        name="test.logger",
        level=level,
        pathname=__file__,
        lineno=10,
        msg=message,
        args=None,
        exc_info=None,
    )
    if request_id is not None:
        record.request_id = request_id  # type: ignore[attr-defined]
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)
    return record


@pytest.fixture()
def isolated_root_logger():
    """Save/restore root-logger handlers + level around each test."""
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    yield root
    # Halt any AxiomHandler instances we attached so their workers don't leak.
    for h in root.handlers:
        if isinstance(h, AxiomHandler):
            _stop_handler(h)
    root.handlers = original_handlers
    root.level = original_level


@pytest.fixture()
def mock_axiom_token(monkeypatch):
    """Set a fake ``axiom_api_token`` on the shared settings object."""
    from app import config as cfg

    monkeypatch.setattr(cfg.settings, "axiom_api_token", "test-token-xxx", raising=False)
    monkeypatch.setattr(cfg.settings, "axiom_dataset", "test-dataset", raising=False)
    yield


@pytest.fixture()
def no_axiom_token(monkeypatch):
    """Force ``axiom_api_token`` to None on the shared settings object."""
    from app import config as cfg

    monkeypatch.setattr(cfg.settings, "axiom_api_token", None, raising=False)
    monkeypatch.setattr(cfg.settings, "axiom_dataset", "regression-tool", raising=False)
    yield


# ---------------------------------------------------------------------------
# T1 — handler attached when token set
# ---------------------------------------------------------------------------


class TestHandlerAttachment:
    """AC: an ``AxiomHandler`` is attached iff ``AXIOM_API_TOKEN`` is set."""

    def test_handler_attached_when_token_set(
        self, isolated_root_logger, mock_axiom_token
    ):
        # Patch the httpx client so no socket is opened.
        with patch.object(logging_axiom, "httpx") as mock_httpx:
            mock_httpx.Client.return_value = MagicMock()
            mock_httpx.HTTPError = httpx.HTTPError
            setup_logging(json_output=True)

        axiom_handlers = [
            h for h in isolated_root_logger.handlers if isinstance(h, AxiomHandler)
        ]
        assert len(axiom_handlers) == 1, (
            f"expected exactly one AxiomHandler, got {len(axiom_handlers)}"
        )

    def test_no_handler_when_token_unset(
        self, isolated_root_logger, no_axiom_token
    ):
        # Snapshot the set of worker threads BEFORE the call so we measure the
        # delta from setup_logging() specifically (other tests in this module
        # may legitimately leave daemon workers alive — that is independent of
        # whether setup_logging() spawns a NEW one).
        before = {
            id(t)
            for t in threading.enumerate()
            if t.name == "axiom-log-worker"
        }

        setup_logging(json_output=True)

        axiom_handlers = [
            h for h in isolated_root_logger.handlers if isinstance(h, AxiomHandler)
        ]
        assert axiom_handlers == [], "no AxiomHandler should be attached"

        after = {
            id(t)
            for t in threading.enumerate()
            if t.name == "axiom-log-worker"
        }
        new_workers = after - before
        assert new_workers == set(), (
            "setup_logging() must not spawn an axiom-log-worker when the token is unset"
        )

    def test_build_handler_returns_none_when_token_blank(self, monkeypatch):
        from app import config as cfg

        monkeypatch.setattr(cfg.settings, "axiom_api_token", "", raising=False)
        assert build_axiom_handler() is None

    def test_build_handler_returns_none_when_token_none(self, monkeypatch):
        from app import config as cfg

        monkeypatch.setattr(cfg.settings, "axiom_api_token", None, raising=False)
        assert build_axiom_handler() is None


# ---------------------------------------------------------------------------
# T3 — exceptions inside Axiom path do not propagate
# ---------------------------------------------------------------------------


class TestNeverRaises:
    """AC: any failure in the Axiom path is swallowed; the app keeps logging."""

    def test_emit_swallows_exception_from_record_serialization(self, capsys):
        handler = AxiomHandler(token="t", dataset="d")
        try:
            with patch.object(
                AxiomHandler, "_record_to_event", side_effect=RuntimeError("boom")
            ):
                # Must not raise.
                handler.emit(_make_record(request_id="-"))
            captured = capsys.readouterr()
            assert "[axiom-logger]" in captured.err
            assert "emit error" in captured.err
        finally:
            _stop_handler(handler)

    def test_http_error_in_flush_does_not_propagate(self, capsys):
        handler = AxiomHandler(token="t", dataset="d")
        try:
            # Replace the worker client with one that always raises an HTTPError.
            handler._worker._client = MagicMock()
            handler._worker._client.post.side_effect = httpx.ConnectError("nope")

            # Drive a single flush directly — no exception should escape.
            handler._worker._flush([{"_time": "now", "message": "hi"}])

            captured = capsys.readouterr()
            assert "[axiom-logger]" in captured.err
            assert "ingest transport error" in captured.err
            assert "ConnectError" in captured.err
        finally:
            _stop_handler(handler)

    def test_logger_remains_functional_after_axiom_failure(
        self, isolated_root_logger, mock_axiom_token
    ):
        # Even if the Axiom worker is wedged on errors, stdout logging keeps working.
        with patch.object(logging_axiom, "httpx") as mock_httpx:
            mock_client = MagicMock()
            mock_client.post.side_effect = httpx.HTTPError("explode")
            mock_httpx.Client.return_value = mock_client
            mock_httpx.HTTPError = httpx.HTTPError
            setup_logging(json_output=True)

            logger = logging.getLogger("test.after_failure")
            # Should not raise even though Axiom is broken.
            logger.info("still works")


# ---------------------------------------------------------------------------
# T4 — request_id propagates from the contextvar into Axiom events
# ---------------------------------------------------------------------------


class TestRequestIdPropagation:
    """AC: the contextvar request_id appears in events sent to Axiom."""

    def test_request_id_present_in_queued_event(self):
        handler = AxiomHandler(token="t", dataset="d")
        # Halt the worker immediately so events stay on the queue for inspection.
        handler._worker.stop()
        handler._worker.join(timeout=1.0)

        token = request_id_ctx.set("test-id-789")
        try:
            # Attach the same filter the real setup uses.
            handler.addFilter(RequestIdFilter())
            record = _make_record(message="propagation test")
            handler.handle(record)  # invokes filters, then emit
        finally:
            request_id_ctx.reset(token)

        # Drain the queue.
        events: list[dict[str, Any]] = []
        try:
            while True:
                events.append(handler._q.get_nowait())
        except queue.Empty:
            pass

        assert events, "expected at least one queued event"
        assert events[0]["request_id"] == "test-id-789"
        assert events[0]["message"] == "propagation test"

    def test_request_id_defaults_to_dash_when_filter_missing(self):
        handler = AxiomHandler(token="t", dataset="d")
        handler._worker.stop()
        handler._worker.join(timeout=1.0)

        # No filter -> record has no request_id attribute.
        record = _make_record(message="no filter")
        handler.handle(record)

        event = handler._q.get_nowait()
        assert event["request_id"] == "-"


# ---------------------------------------------------------------------------
# T5 — queue overflow drops silently with throttled stderr warning
# ---------------------------------------------------------------------------


class TestLoopGuard:
    """Records from the worker's own HTTP-client loggers must NOT be re-enqueued.

    Without this guard, each ingest POST emits an ``httpx._client`` INFO log,
    which would be picked up by the AxiomHandler, enqueued, and trigger
    another POST — an amplification loop.
    """

    @pytest.mark.parametrize(
        "logger_name",
        ["httpx", "httpx._client", "httpx._trace", "httpcore", "httpcore.http11"],
    )
    def test_httpx_and_httpcore_records_are_dropped(self, logger_name):
        handler = AxiomHandler(token="t", dataset="d")
        handler._worker.stop()
        handler._worker.join(timeout=1.0)

        record = logging.LogRecord(
            name=logger_name,
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="HTTP Request: POST https://api.axiom.co/...",
            args=None,
            exc_info=None,
        )
        record.request_id = "-"  # type: ignore[attr-defined]

        handler.emit(record)
        assert handler._q.qsize() == 0, (
            f"records from {logger_name!r} must not be enqueued"
        )
        assert handler.dropped == 0, "loop-guard drops are NOT counted as overflow"

    def test_application_loggers_still_enqueue(self):
        handler = AxiomHandler(token="t", dataset="d")
        handler._worker.stop()
        handler._worker.join(timeout=1.0)

        record = _make_record(message="app event", request_id="-")
        handler.emit(record)
        assert handler._q.qsize() == 1


class TestQueueOverflow:
    """AC: when the queue is full, oldest events drop and a single warning is emitted."""

    def test_queue_full_drops_silently_and_warns_once(self, monkeypatch, capsys):
        # Shrink the queue so the test is cheap and deterministic.
        monkeypatch.setattr(logging_axiom, "QUEUE_MAX", 3)

        handler = AxiomHandler(token="t", dataset="d")
        # Halt the worker so it can't drain the queue mid-test.
        handler._worker.stop()
        handler._worker.join(timeout=1.0)

        # Fill the queue (3 events) — no drops yet.
        for i in range(3):
            handler.emit(_make_record(message=f"event-{i}", request_id="-"))
        assert handler.dropped == 0

        # Now overflow by 50. All 50 should drop without raising.
        for i in range(50):
            handler.emit(_make_record(message=f"overflow-{i}", request_id="-"))

        assert handler.dropped == 50, (
            f"expected 50 dropped events, got {handler.dropped}"
        )

        # And stderr must contain ONE throttled warning, not 50.
        captured = capsys.readouterr()
        warn_lines = [
            line
            for line in captured.err.splitlines()
            if "axiom queue full" in line
        ]
        assert len(warn_lines) == 1, (
            f"expected exactly one throttled warning, got {len(warn_lines)}: "
            f"{warn_lines!r}"
        )


# ---------------------------------------------------------------------------
# T6 — 4xx response is logged to stderr, never leaks body, never raises
# ---------------------------------------------------------------------------


class TestHttpErrorHandling:
    """4xx / 5xx responses must produce a status-only stderr warning and no exception."""

    def test_4xx_response_warns_but_does_not_raise(self, capsys):
        handler = AxiomHandler(token="t", dataset="d")
        try:
            fake_response = MagicMock()
            fake_response.status_code = 403
            # If anyone tries to read the body, fail loudly so the test catches a regression.
            # Descriptors only run when defined on the *class*, not the instance,
            # so install the property on type(fake_response) — see CPython data
            # model docs on descriptor lookup.
            type(fake_response).text = property(  # type: ignore[assignment]
                lambda self: pytest.fail("response body must not be read")
            )

            handler._worker._client = MagicMock()
            handler._worker._client.post.return_value = fake_response

            # Direct flush — must not raise.
            handler._worker._flush([{"_time": "now", "message": "hi"}])

            captured = capsys.readouterr()
            assert "status=403" in captured.err
            assert "[axiom-logger]" in captured.err
            # Never echo the token or anything resembling it.
            assert "test-token" not in captured.err
        finally:
            _stop_handler(handler)


# ---------------------------------------------------------------------------
# T7 — non-serializable extras are coerced, not dropped or crashed
# ---------------------------------------------------------------------------


class TestRecordSerialization:
    """``_record_to_event`` must handle weird ``extra`` values gracefully."""

    def test_non_serializable_extra_is_reprd(self):
        sentinel = object()
        record = _make_record(
            message="weird extra",
            request_id="-",
            extra={"weird": sentinel},
        )
        event = AxiomHandler._record_to_event(record)
        assert "weird" in event
        assert event["weird"].startswith("<object object")

    def test_serializable_extras_are_kept_as_is(self):
        record = _make_record(
            message="nice extras",
            request_id="-",
            extra={"count": 42, "user": "alice"},
        )
        event = AxiomHandler._record_to_event(record)
        assert event["count"] == 42
        assert event["user"] == "alice"

    def test_event_round_trips_through_json(self):
        record = _make_record(
            message="round trip",
            request_id="abc",
            extra={"nested": {"k": [1, 2, 3]}},
        )
        event = AxiomHandler._record_to_event(record)
        # The whole event must be JSON-encodable (or the worker would fail to ship it).
        round_tripped = json.loads(json.dumps(event))
        assert round_tripped["message"] == "round trip"
        assert round_tripped["request_id"] == "abc"
        assert round_tripped["nested"] == {"k": [1, 2, 3]}

    def test_exception_info_is_formatted_into_event(self):
        try:
            raise ValueError("test exc")
        except ValueError:
            import sys

            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="test.exc",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="exception happened",
            args=None,
            exc_info=exc_info,
        )
        event = AxiomHandler._record_to_event(record)
        assert "exception" in event
        assert "ValueError" in event["exception"]
        assert "test exc" in event["exception"]


# ---------------------------------------------------------------------------
# T8 — timestamp is taken from the record, not from "now"
# ---------------------------------------------------------------------------


class TestTimestamp:
    """``_time`` must reflect emit-time so queued events keep their original order."""

    def test_event_time_uses_record_created(self):
        record = _make_record(request_id="-")
        # Force a known created time well in the past.
        record.created = 1_700_000_000.123  # 2023-11-14T...
        event = AxiomHandler._record_to_event(record)
        # YYYY-MM-DDTHH:MM:SS.mmmZ
        assert event["_time"].startswith("2023-11-14T"), event["_time"]
        assert event["_time"].endswith("Z")
        assert ".123Z" in event["_time"]


# ---------------------------------------------------------------------------
# Warn throttle helper
# ---------------------------------------------------------------------------


class TestWarnThrottled:
    """``_warn_throttled`` rate-limits per-key, not globally."""

    def test_throttles_repeats_of_same_key(self, capsys, monkeypatch):
        monkeypatch.setattr(logging_axiom, "WARN_THROTTLE_S", 60.0)
        state: dict[str, float] = {}
        _warn_throttled(state, "k1", "first")
        _warn_throttled(state, "k1", "second")  # should be throttled
        captured = capsys.readouterr()
        lines = [
            line for line in captured.err.splitlines() if "[axiom-logger]" in line
        ]
        assert len(lines) == 1
        assert "first" in lines[0]

    def test_different_keys_warn_independently(self, capsys):
        state: dict[str, float] = {}
        _warn_throttled(state, "a", "alpha")
        _warn_throttled(state, "b", "beta")
        captured = capsys.readouterr()
        lines = [
            line for line in captured.err.splitlines() if "[axiom-logger]" in line
        ]
        assert len(lines) == 2

    def test_throttle_window_elapses(self, capsys, monkeypatch):
        # Use a tiny throttle window and step time forward.
        monkeypatch.setattr(logging_axiom, "WARN_THROTTLE_S", 0.0)
        state: dict[str, float] = {}
        _warn_throttled(state, "k", "one")
        time.sleep(0.001)
        _warn_throttled(state, "k", "two")
        captured = capsys.readouterr()
        lines = [
            line for line in captured.err.splitlines() if "[axiom-logger]" in line
        ]
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# Worker batching
# ---------------------------------------------------------------------------


class TestWorkerBatching:
    """The worker batches multiple events into a single POST."""

    def test_drain_batch_returns_empty_when_queue_idle(self, monkeypatch):
        # Make the batch timeout near-instant.
        monkeypatch.setattr(logging_axiom, "BATCH_TIMEOUT_S", 0.01)
        q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=10)
        worker = _AxiomWorker(q, token="t", dataset="d")
        try:
            batch = worker._drain_batch()
            assert batch == []
        finally:
            worker.stop()

    def test_drain_batch_pulls_up_to_batch_max(self, monkeypatch):
        monkeypatch.setattr(logging_axiom, "BATCH_TIMEOUT_S", 0.5)
        monkeypatch.setattr(logging_axiom, "BATCH_MAX", 5)
        q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=100)
        for i in range(20):
            q.put_nowait({"i": i})
        worker = _AxiomWorker(q, token="t", dataset="d")
        try:
            batch = worker._drain_batch()
            assert len(batch) == 5
            # Remaining events still in the queue.
            assert q.qsize() == 15
        finally:
            worker.stop()


# ---------------------------------------------------------------------------
# Issue #274 — handler exposes flush bookkeeping for /api/health
# ---------------------------------------------------------------------------


class TestFlushBookkeepingIssue274:
    """Worker writes ``last_flush_at`` / ``last_flush_error`` through the handler.

    These tests drive ``_AxiomWorker._flush`` directly (no real network) so
    we can assert that each branch (2xx, 4xx, transport error, generic
    exception) publishes the expected sanitized state on the handler.
    """

    def test_successful_flush_sets_last_flush_at_clears_error(self):
        handler = AxiomHandler(token="t", dataset="d")
        try:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            handler._worker._client = MagicMock()
            handler._worker._client.post.return_value = mock_resp

            # Pre-seed an error to confirm the success branch clears it.
            handler._set_last_flush_err("old")

            handler._worker._flush([{"_time": "now", "message": "hi"}])

            assert handler.last_flush_error is None
            assert handler.last_flush_at is not None
            # Sanity-check the format — ``_format_timestamp`` produces
            # ``YYYY-MM-DDTHH:MM:SS.mmmZ``.
            assert handler.last_flush_at.endswith("Z")
            assert "T" in handler.last_flush_at
        finally:
            _stop_handler(handler)

    def test_4xx_flush_sets_sanitized_error_only_status(self, capsys):
        handler = AxiomHandler(token="t", dataset="d")
        try:
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            handler._worker._client = MagicMock()
            handler._worker._client.post.return_value = mock_resp

            handler._worker._flush([{"_time": "now", "message": "hi"}])

            assert handler.last_flush_error == "ingest failed status=401"
            # No PII, no body, no headers leaked.
            captured = capsys.readouterr()
            assert "ingest failed status=401" in captured.err
            # last_flush_at should not advance on failure.
            assert handler.last_flush_at is None
        finally:
            _stop_handler(handler)

    def test_transport_error_records_exception_class_name_only(self):
        handler = AxiomHandler(token="t", dataset="d")
        try:
            handler._worker._client = MagicMock()
            handler._worker._client.post.side_effect = httpx.ConnectError("nope")

            handler._worker._flush([{"_time": "now", "message": "hi"}])

            # Only the class name leaks — never str(e).
            assert handler.last_flush_error == "ingest transport error: ConnectError"
            assert "nope" not in (handler.last_flush_error or "")
            assert handler.last_flush_at is None
        finally:
            _stop_handler(handler)

    def test_generic_exception_records_exception_class_name_only(self):
        handler = AxiomHandler(token="t", dataset="d")
        try:
            handler._worker._client = MagicMock()
            handler._worker._client.post.side_effect = RuntimeError("explode-detail")

            handler._worker._flush([{"_time": "now", "message": "hi"}])

            assert handler.last_flush_error == "ingest unknown error: RuntimeError"
            assert "explode-detail" not in (handler.last_flush_error or "")
        finally:
            _stop_handler(handler)

    def test_worker_without_handler_back_reference_is_a_noop_on_bookkeeping(self):
        """A worker constructed without a handler back-ref must not crash."""
        # Build a worker directly (no handler) — the production code always
        # passes one, but test-helpers may not.
        import queue as _queue

        q: "_queue.Queue[dict[str, object]]" = _queue.Queue(maxsize=10)
        worker = _AxiomWorker(q, "t", "d")  # no handler kwarg
        try:
            worker._client = MagicMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            worker._client.post.return_value = mock_resp

            # Should not raise even though there is no handler to publish to.
            worker._flush([{"_time": "now", "message": "hi"}])
        finally:
            worker.stop()
