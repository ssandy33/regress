import logging

import requests as _requests
from fastapi import APIRouter

from app.config import get_fred_api_key
from app.services.slack_notifier import get_slack_notifier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/sources")
def check_sources():
    """Ping each data source and return status."""
    results = {
        "alpha_vantage": _check_alpha_vantage(),
        "fred": _check_fred(),
        "zillow": _check_zillow(),
        "schwab": _check_schwab(),
    }
    results["all_down"] = all(
        not v["available"] for k, v in results.items() if k != "all_down"
    )

    # Send Slack notifications for degraded sources
    notifier = get_slack_notifier()
    if notifier.is_configured:
        for source, status in results.items():
            if source == "all_down":
                continue
            if isinstance(status, dict) and not status.get("available"):
                notifier.notify_health_degraded(source, status.get("error"))
        results["slack"] = _check_slack()

    return results


@router.get("")
def health_check() -> dict:
    """Top-level health probe with optional Axiom logging self-monitoring.

    Replaces the legacy inline ``GET /api/health`` handler in ``app.main``
    (issue #274). The endpoint is intentionally cheap — no outbound HTTP,
    no Axiom API calls, no DB hits. It reads in-process state only.

    Response shape is unconditional: when Axiom is disabled, the
    ``logging`` block still renders with zeroed counters and ``null``
    timestamps so frontend/operator consumers see a stable schema.
    """
    return {"status": "ok", "logging": _build_logging_stats()}


def _get_axiom_handler():
    """Return the first :class:`AxiomHandler` attached to the root logger, or ``None``.

    Imported lazily to avoid pulling ``httpx`` (a transitive of
    :mod:`app.logging_axiom`) into the import graph of any caller that
    only needs the legacy ``/sources`` probe. Also avoids a circular
    import on cold start.
    """
    from app.logging_axiom import AxiomHandler

    for h in logging.getLogger().handlers:
        if isinstance(h, AxiomHandler):
            return h
    return None


def _safe_get(handler, attr: str, default):
    """Read ``handler.<attr>`` with a try/except fallback.

    A logging-internal hiccup (e.g. a non-thread-safe ``qsize()`` raising
    under contention on some platforms) must not be allowed to 500 the
    health endpoint. We log at debug level and fall back to the schema's
    documented default per #274.
    """
    try:
        return getattr(handler, attr)
    except Exception as e:  # noqa: BLE001 — health must never bubble logging errors
        logger.debug("axiom handler attr %s raised %s", attr, type(e).__name__)
        return default


def _build_logging_stats() -> dict:
    """Build the ``logging`` subsection of the ``/api/health`` payload.

    Schema is frozen by the v1.0.10 plan §2.3:

    - ``axiom_enabled`` — true iff ``settings.axiom_api_token`` is truthy.
    - ``queue_depth`` — current in-process queue depth (approximate per
      :py:meth:`queue.Queue.qsize`).
    - ``queue_capacity`` — configured max queue size (default 1000).
    - ``dropped_total`` — process-lifetime overflow count (handler.dropped).
    - ``last_flush_at`` — RFC3339 timestamp of the last 2xx ingest, or null.
    - ``last_flush_error`` — sanitized error message, or null.

    When the Axiom handler is not attached (token unset, init failure), the
    block renders with the same shape and zero/null defaults so consumers
    never need to branch on presence.
    """
    from app.config import settings

    handler = _get_axiom_handler()
    if handler is None:
        return {
            "axiom_enabled": bool(getattr(settings, "axiom_api_token", None)),
            "queue_depth": 0,
            "queue_capacity": 1000,
            "dropped_total": 0,
            "last_flush_at": None,
            "last_flush_error": None,
        }
    return {
        "axiom_enabled": True,
        "queue_depth": _safe_get(handler, "queue_depth", 0),
        "queue_capacity": _safe_get(handler, "queue_capacity", 1000),
        "dropped_total": _safe_get(handler, "dropped", 0),
        "last_flush_at": _safe_get(handler, "last_flush_at", None),
        "last_flush_error": _safe_get(handler, "last_flush_error", None),
    }


def _check_alpha_vantage() -> dict:
    """Check Alpha Vantage API availability."""
    try:
        from app.services.alpha_vantage_client import get_alpha_vantage_api_key
        api_key = get_alpha_vantage_api_key()
        if not api_key:
            return {"available": False, "error": "API key not configured"}
        resp = _requests.get(
            "https://www.alphavantage.co/query",
            params={"function": "EARNINGS_CALENDAR", "symbol": "AAPL", "horizon": "3month", "apikey": api_key},
            timeout=10,
        )
        if resp.status_code != 200:
            return {"available": False, "error": f"HTTP {resp.status_code}"}
        # Alpha Vantage returns HTTP 200 with JSON error body on failures
        try:
            body = resp.json()
            error_msg = body.get("Error Message") or body.get("Note") or body.get("Information")
            if error_msg:
                return {"available": False, "error": error_msg}
        except ValueError:
            pass  # Not JSON — likely valid CSV response
        return {"available": True, "error": None}
    except Exception as e:
        logger.debug("Alpha Vantage health check failed: %s", e)
        return {"available": False, "error": "Connection failed"}


def _check_fred() -> dict:
    """Check FRED API by fetching a single data point."""
    try:
        key = get_fred_api_key()
        if not key:
            return {"available": False, "error": "API key not configured"}
        from fredapi import Fred

        fred = Fred(api_key=key)
        fred.get_series("DGS10", observation_start="2024-01-01", observation_end="2024-01-05")
        return {"available": True, "error": None}
    except Exception as e:
        logger.debug("FRED health check failed: %s", e)
        return {"available": False, "error": "Connection failed"}


def _check_schwab() -> dict:
    """Check Schwab API by testing market data endpoint."""
    try:
        from app.services.schwab_auth import SchwabTokenManager
        mgr = SchwabTokenManager()
        if not mgr.is_configured():
            return {"available": False, "error": "Not configured"}
        import httpx
        token = mgr.get_access_token()
        resp = httpx.get(
            "https://api.schwabapi.com/marketdata/v1/markets?markets=equity",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        return {"available": resp.status_code == 200, "error": None}
    except Exception as e:
        logger.debug("Schwab health check failed: %s", e)
        return {"available": False, "error": "Connection failed"}


def _check_zillow() -> dict:
    """Check Zillow CSV availability via HEAD request."""
    try:
        resp = _requests.head(
            "https://files.zillowstatic.com/research/public_csvs/zhvi/Zip_zhvi_uf_sm_sa_month.csv",
            timeout=10,
        )
        return {"available": resp.status_code == 200, "error": None}
    except Exception as e:
        logger.debug("Zillow health check failed: %s", e)
        return {"available": False, "error": "Connection failed"}


def _check_slack() -> dict:
    """Check whether Slack webhook is configured."""
    notifier = get_slack_notifier()
    if notifier.is_configured:
        return {"available": True, "error": None}
    return {"available": False, "error": "Webhook URL not configured"}
