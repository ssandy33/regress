"""Integration tests for the ``GET /api/dashboard`` cache-control header (#367).

The dashboard is fetched client-side via axios and proxied to this route by
Next's ``rewrites()``. Without a cache directive the Next standalone proxy and
the browser were free to serve a stale body after a QA reseed (issue #367). The
fix sets ``Cache-Control: no-store`` on the backend response. These tests prove
the header is present (D-1) and that adding it did not change the response body
schema (D-2) — i.e. it is a header-only change requiring no OpenAPI regen.

Both tests run against the full FastAPI stack + in-memory SQLite (the
``client`` fixture in ``conftest.py``) and so are integration-tier.
"""

import pytest

from app.models.schemas import DashboardResponse


def _patch_status(monkeypatch, *, schwab_configured: bool = False, fred_key: str = "") -> None:
    """Stub Schwab/FRED status helpers so the route needs no real credentials."""

    class _Mgr:
        def is_configured(self) -> bool:
            return schwab_configured

        def get_refresh_token_expiry(self) -> str | None:
            return None

    monkeypatch.setattr("app.services.dashboard.SchwabTokenManager", lambda: _Mgr())
    monkeypatch.setattr("app.services.dashboard.get_fred_api_key", lambda: fred_key)


@pytest.mark.integration
def test_dashboard_response_sets_no_store(client, monkeypatch):
    """GET /api/dashboard returns ``Cache-Control: no-store`` (D-1, #367 AC1)."""
    _patch_status(monkeypatch)

    resp = client.get("/api/dashboard")

    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store"


@pytest.mark.integration
def test_dashboard_no_store_does_not_change_body_schema(client, monkeypatch):
    """Response body still validates against ``DashboardResponse`` (D-2, #367 AC1).

    Guards that the ``no-store`` header is a header-only change: the payload
    shape is unchanged, so no OpenAPI snapshot regen is required.
    """
    _patch_status(monkeypatch)

    resp = client.get("/api/dashboard")

    assert resp.status_code == 200
    # Raises ValidationError if the body drifted from the contract.
    DashboardResponse.model_validate(resp.json())
