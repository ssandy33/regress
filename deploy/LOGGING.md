# Backend Logging — Axiom

The regression_tool backend supports optional centralized logging via [Axiom](https://axiom.co). When enabled, every Python `logging` event is shipped to an Axiom dataset in addition to the local stdout sink (which continues to feed Loki/Grafana in prod). Axiom is **additive** — disabling it leaves the existing observability stack untouched.

> Pattern source: this implementation mirrors the sibling project ado-pulse's `lib/logger.ts` (TypeScript). The Python adaptation uses a bounded `queue.Queue` + single daemon worker thread to keep `emit()` non-blocking on the request path. See `backend/app/logging_axiom.py`.

## Quick Setup

1. Create an Axiom account at <https://app.axiom.co>.
2. Create a dataset named `regression-tool` (or whatever you set `AXIOM_DATASET` to).
3. Create an API token with **Ingest** permission for that dataset.
4. Set the env vars:

   **Local dev** (`backend/.env`):

   ```bash
   AXIOM_API_TOKEN=xaat-xxxxxxxx
   AXIOM_DATASET=regression-tool
   ```

   **Production** (`.env` at repo root, consumed by `docker-compose.prod.yml`):

   ```bash
   AXIOM_API_TOKEN=xaat-xxxxxxxx
   AXIOM_DATASET=regression-tool
   ```

5. Restart the backend. Within ~2 seconds of the first log event you should see records in the Axiom dataset.

## Disabling

Unset `AXIOM_API_TOKEN` and restart. Behavior reverts to stdout-only — no Axiom code is exercised, no background thread is started.

## QA dataset (issue #330)

The QA stack (`docker-compose.qa.yml`) is the QA distinguisher for observability:
it reuses the **same** `AXIOM_API_TOKEN` as prod but routes every event to a
**dedicated dataset**, `AXIOM_DATASET=regression-tool-qa`, so prod and QA logs
never interleave. This is a zero-code-change distinguisher — `AXIOM_DATASET` is
already env-driven.

| | Prod | QA |
|---|---|---|
| `AXIOM_DATASET` | `regression-tool` | `regression-tool-qa` |
| Compose file | `docker-compose.prod.yml` | `docker-compose.qa.yml` |
| Container stdout | Loki driver → Loki/Grafana | default json-file (`docker logs qa-backend`) |

QA has **no Loki/Grafana** — the loki log driver is a host-wide plugin pointing
at `localhost:3100`, which QA doesn't run. The QA compose therefore omits the
`logging:` block entirely and uses Docker's default `json-file` driver. Axiom
carries the structured logs; `docker logs qa-backend` is the local fallback.
Create the `regression-tool-qa` dataset in the Axiom UI before first QA deploy.

## How it works

- `backend/app/logging_axiom.py` implements `AxiomHandler`, a `logging.Handler` subclass.
- On `emit()`, it converts the `LogRecord` to a JSON-safe dict (including the `request_id` injected by the existing `RequestIdFilter` middleware) and enqueues it on a bounded in-memory queue. The call returns immediately — no HTTP on the request path.
- A daemon thread named `axiom-log-worker` batches up to 100 events or 2 seconds and POSTs them to `https://api.axiom.co/v1/datasets/{dataset}/ingest` using the already-pinned `httpx` client.
- Any HTTP, queue-full, or serialization error is caught and reported via a throttled stderr warning (one per minute per error type, not one per event). The application never sees an exception from logging.

### Event schema

Each event sent to Axiom is a JSON object with at least:

| Field | Source |
|---|---|
| `_time` | RFC3339 timestamp with millisecond precision (from `LogRecord.created`) |
| `level` | `info`, `warning`, `error`, etc. (lower-cased `LogRecord.levelname`) |
| `service` | Always `regression-tool` |
| `module` | Python module name (`LogRecord.module`) |
| `logger` | Full logger name |
| `message` | Formatted log message |
| `request_id` | Request correlation ID (or `-` when not in a request context) |
| `exception` | Traceback text (only present when `exc_info` is set) |

Any additional `extra={...}` fields passed at the call site (e.g. `logger.info("synced", extra={"count": 42})`) are merged in. Non-JSON-serializable values are coerced via `repr()` rather than dropped.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No events in Axiom | Token unset or dataset name mismatch | Check `.env`, restart the backend container |
| Stderr `[axiom-logger] ingest failed status=401` | Bad token | Regenerate in Axiom UI (Settings → API Tokens) |
| Stderr `[axiom-logger] ingest failed status=404` | Dataset doesn't exist | Create it in Axiom UI, restart |
| Stderr `[axiom-logger] axiom queue full; dropped=...` | Log volume exceeds 1000 events buffered | Investigate the storm first — sustained drops usually mean a runaway logger, not an undersized queue. If genuinely needed, raising `QUEUE_MAX` is a **code change**: edit the constant in `backend/app/logging_axiom.py`, rebuild the backend image, and redeploy. Dropping events during a storm is the intended degradation. |
| Stderr `[axiom-logger] ingest transport error: ConnectError` | Network blocked / DNS failure | Check egress to `api.axiom.co:443` |

## Rollback

If Axiom integration causes a problem in prod (excess stderr noise, perceived latency, anything):

1. Edit `.env` on the prod host: comment out or remove `AXIOM_API_TOKEN`.
2. `cd /opt/regression_tool && docker compose -f docker-compose.prod.yml up -d --no-deps backend` — restarts only the backend container.
3. Within seconds the new process starts; `build_axiom_handler()` returns `None`; no Axiom handler, no worker thread.
4. Loki/Grafana stack is untouched and continues capturing container stdout.

No DB changes, no migrations, no external state to clean up. The Axiom dataset can stay populated.

## Follow-up: container-log shipping with Vector

This implementation covers in-process **application** logs from the Python backend. A separate, optional path — shipping Docker container stdout/stderr (including non-Python services like Caddy) to a `regression-tool-infra` Axiom dataset via [Vector](https://vector.dev) — is documented in the sibling ado-pulse project at `ado-pulse/deploy/LOGGING.md` (lines 16-54) as the template. That work is tracked separately and is NOT required for this rollout.

## Follow-up: `/api/health` enrichment

The handler tracks queue depth (`AxiomHandler._q.qsize()`) and a `dropped` counter (`AxiomHandler.dropped`). Surfacing these on `/api/health` for prod sanity-checks is a separate, deferred issue — not in scope here.
