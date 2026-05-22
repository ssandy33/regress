"""Optional Axiom log sink for the backend.

When ``AXIOM_API_TOKEN`` is set in the environment (read via ``app.config.settings``),
``build_axiom_handler()`` returns a :class:`AxiomHandler` that the root logger can
attach as a *sibling* of the existing JSON-to-stdout handler. When the token is
unset, ``build_axiom_handler()`` returns ``None`` and runtime behavior is
byte-for-byte identical to today — no background thread, no HTTP client, no
extra latency on the request path.

Design pattern is mirrored from the sibling ``ado-pulse`` project
(``ado-pulse/lib/logger.ts``) and adapted to Python with a bounded
``queue.Queue`` + single daemon worker thread that batches up to ``BATCH_MAX``
events or ``BATCH_TIMEOUT_S`` seconds before POSTing to the Axiom ingest
endpoint via the already-pinned ``httpx`` client.

Failure semantics
-----------------
The handler **never raises** into application code. Queue overflow, HTTP
errors, JSON-encode failures, and worker-loop crashes are all caught and
reported via :func:`_warn_throttled` to ``sys.stderr`` at most once per
``WARN_THROTTLE_S`` per error type. Drops are an acceptable observability
degradation; blocking the request thread is not.

Internal warnings go directly to ``sys.stderr`` and NOT through the standard
``logging`` module — that would loop through this same handler.
"""

from __future__ import annotations

import atexit
import json
import logging
import queue
import sys
import threading
import time
from typing import Any, Optional

import httpx

AXIOM_INGEST_URL = "https://api.axiom.co/v1/datasets/{dataset}/ingest"
SERVICE_NAME = "regression-tool"

# Logger-name prefixes whose records must NOT be shipped to Axiom — these are
# emitted by the worker's own httpx client and would otherwise create an
# amplification loop (each POST logs an INFO, which is enqueued, which triggers
# another POST). The leading "httpx" covers httpx._client, httpx._trace, etc.;
# "httpcore" covers the lower-level connection / SOCKS / SSL handshake logs.
_SUPPRESSED_LOGGER_PREFIXES: tuple[str, ...] = ("httpx", "httpcore")

# Tunables — module-level so tests can monkey-patch.
QUEUE_MAX = 1000
BATCH_MAX = 100
BATCH_TIMEOUT_S = 2.0
HTTP_TIMEOUT_S = 5.0
WARN_THROTTLE_S = 60.0
ATEXIT_FLUSH_TIMEOUT_S = 2.0

# Standard ``logging.LogRecord`` attributes we must NOT copy into the event
# payload (some are duplicated under nicer names; most are internal).
_RECORD_SKIP_ATTRS: frozenset[str] = frozenset(
    {
        "args",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "request_id",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


def _warn_throttled(state: dict[str, float], key: str, message: str) -> None:
    """Print ``message`` to stderr at most once per :data:`WARN_THROTTLE_S` per ``key``.

    ``state`` is a per-instance dict so each handler / worker keeps its own
    throttle window without leaking across instances or tests.
    """
    now = time.monotonic()
    last = state.get(key, 0.0)
    if now - last >= WARN_THROTTLE_S:
        state[key] = now
        print(f"[axiom-logger] {message}", file=sys.stderr, flush=True)


def _format_timestamp(created: float) -> str:
    """Format an epoch-seconds value as ``YYYY-MM-DDTHH:MM:SS.mmmZ`` (UTC).

    Axiom expects RFC3339 timestamps with millisecond precision. We round the
    fractional part rather than truncate so a record stamped with e.g.
    ``1700000000.123`` round-trips to ``.123Z`` instead of ``.122Z`` (float
    representation loses a hair of precision).
    """
    millis = round((created - int(created)) * 1000)
    # Rounding can overflow to 1000 on values like .9995 — normalize.
    seconds = int(created)
    if millis >= 1000:
        seconds += 1
        millis -= 1000
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(seconds)) + f".{millis:03d}Z"


class _AxiomWorker(threading.Thread):
    """Daemon thread that drains the queue and POSTs batches to Axiom."""

    def __init__(self, q: "queue.Queue[dict[str, Any]]", token: str, dataset: str) -> None:
        super().__init__(name="axiom-log-worker", daemon=True)
        self._q = q
        self._url = AXIOM_INGEST_URL.format(dataset=dataset)
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        # NOTE: named ``_stop_event`` (not ``_stop``) to avoid colliding with
        # ``threading.Thread._stop`` — that name has been used internally by
        # CPython in older versions and shadowing it on the subclass instance
        # is a footgun even if 3.13 no longer uses it during ``join()``.
        self._stop_event = threading.Event()
        self._warn_state: dict[str, float] = {}
        self._client = httpx.Client(timeout=HTTP_TIMEOUT_S)

    def stop(self) -> None:
        """Signal the worker loop to exit after the next batch flush."""
        self._stop_event.set()

    def _drain_batch(self) -> list[dict[str, Any]]:
        """Pull up to :data:`BATCH_MAX` events from the queue, blocking briefly for the first.

        Blocks for at most :data:`BATCH_TIMEOUT_S` waiting for the first event
        (so we don't busy-loop on an idle queue), then opportunistically pulls
        additional events without blocking until the batch is full or the
        queue empties.
        """
        batch: list[dict[str, Any]] = []
        try:
            first = self._q.get(timeout=BATCH_TIMEOUT_S)
            batch.append(first)
        except queue.Empty:
            return batch
        while len(batch) < BATCH_MAX:
            try:
                batch.append(self._q.get_nowait())
            except queue.Empty:
                break
        return batch

    def _flush(self, batch: list[dict[str, Any]]) -> None:
        """POST ``batch`` to the Axiom ingest endpoint, swallowing all errors."""
        if not batch:
            return
        try:
            resp = self._client.post(
                self._url, headers=self._headers, content=json.dumps(batch)
            )
            if resp.status_code >= 400:
                # Status code only — never echo response body or headers,
                # which may contain the token or other sensitive context.
                _warn_throttled(
                    self._warn_state,
                    "http_4xx_5xx",
                    f"ingest failed status={resp.status_code}",
                )
        except httpx.HTTPError as e:
            _warn_throttled(
                self._warn_state,
                "http_error",
                f"ingest transport error: {type(e).__name__}",
            )
        except Exception as e:  # noqa: BLE001 — last-resort safety net
            _warn_throttled(
                self._warn_state,
                "unknown",
                f"ingest unknown error: {type(e).__name__}",
            )

    def run(self) -> None:
        """Main worker loop — drain and flush until :meth:`stop` is signalled."""
        while not self._stop_event.is_set():
            try:
                batch = self._drain_batch()
                self._flush(batch)
            except Exception as e:  # noqa: BLE001 — thread must not die
                _warn_throttled(
                    self._warn_state,
                    "worker_loop",
                    f"worker loop error: {type(e).__name__}",
                )
        # Final drain on stop — best-effort, errors swallowed.
        try:
            self._flush(self._drain_batch())
        except Exception:  # noqa: BLE001
            pass


class AxiomHandler(logging.Handler):
    """``logging.Handler`` that enqueues records for async shipping to Axiom.

    ``emit()`` is O(1) from the caller's perspective: it converts the record
    to a JSON-safe dict and calls ``queue.put_nowait``. All HTTP I/O happens
    on the background :class:`_AxiomWorker` thread.
    """

    def __init__(self, token: str, dataset: str) -> None:
        super().__init__()
        self._q: "queue.Queue[dict[str, Any]]" = queue.Queue(maxsize=QUEUE_MAX)
        self._worker = _AxiomWorker(self._q, token, dataset)
        self._warn_state: dict[str, float] = {}
        self._dropped = 0
        self._worker.start()
        atexit.register(self._atexit_flush)

    @property
    def dropped(self) -> int:
        """Total number of events dropped due to a full queue since startup."""
        return self._dropped

    def _atexit_flush(self) -> None:
        """Best-effort flush on interpreter exit. Bounded by :data:`ATEXIT_FLUSH_TIMEOUT_S`."""
        self._worker.stop()
        self._worker.join(timeout=ATEXIT_FLUSH_TIMEOUT_S)

    def emit(self, record: logging.LogRecord) -> None:
        """Convert ``record`` to a dict and enqueue it. Never raises.

        Records from the worker's own HTTP-client loggers (``httpx``,
        ``httpcore``) are silently dropped here to prevent an amplification
        loop: each POST emits an ``INFO`` log line through the root logger,
        which would otherwise be enqueued and trigger another POST.
        """
        if record.name.split(".", 1)[0] in _SUPPRESSED_LOGGER_PREFIXES:
            return
        try:
            event = self._record_to_event(record)
            try:
                self._q.put_nowait(event)
            except queue.Full:
                self._dropped += 1
                _warn_throttled(
                    self._warn_state,
                    "queue_full",
                    f"axiom queue full; dropped={self._dropped}",
                )
        except Exception as e:  # noqa: BLE001 — logging must never raise into the app
            _warn_throttled(
                self._warn_state,
                "emit_error",
                f"emit error: {type(e).__name__}",
            )

    @staticmethod
    def _record_to_event(record: logging.LogRecord) -> dict[str, Any]:
        """Convert a ``LogRecord`` to a JSON-safe dict suitable for Axiom ingest.

        - ``_time`` uses the record's ``created`` epoch (not "now") so events
          are timestamped at emit-time, not at flush-time.
        - ``request_id`` is read off the record (already populated by
          :class:`app.logging_config.RequestIdFilter`).
        - Any ``extra`` fields set on the record are merged in; values that
          fail ``json.dumps`` are coerced to ``repr(v)`` rather than dropped.
        """
        event: dict[str, Any] = {
            "_time": _format_timestamp(record.created),
            "level": record.levelname.lower(),
            "service": SERVICE_NAME,
            "module": record.module,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "logger": record.name,
        }
        for k, v in record.__dict__.items():
            if k in _RECORD_SKIP_ATTRS or k in event:
                continue
            try:
                json.dumps(v)
                event[k] = v
            except (TypeError, ValueError):
                event[k] = repr(v)
        if record.exc_info:
            event["exception"] = logging.Formatter().formatException(record.exc_info)
        return event


def build_axiom_handler() -> Optional[AxiomHandler]:
    """Construct an :class:`AxiomHandler` if ``AXIOM_API_TOKEN`` is set, else ``None``.

    Reads from ``app.config.settings`` so values in ``.env`` and the runtime
    environment are both honored. Any failure during construction (import
    error, handler init crash) is caught and reported via stderr; the function
    returns ``None`` so the rest of ``setup_logging()`` proceeds unaffected.
    """
    try:
        from app.config import settings

        token = settings.axiom_api_token
        dataset = settings.axiom_dataset
    except Exception:  # noqa: BLE001 — settings import must not break logging
        return None
    if not token:
        return None
    try:
        return AxiomHandler(token=token, dataset=dataset)
    except Exception as e:  # noqa: BLE001
        print(
            f"[axiom-logger] failed to init: {type(e).__name__}",
            file=sys.stderr,
            flush=True,
        )
        return None
