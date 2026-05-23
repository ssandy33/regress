"""Router-shell tests for ``GET /api/positions/{id}/research/business`` (#280, W).

The service layer (:mod:`app.services.research_business`) is already covered
exhaustively in ``tests/test_research_business.py``. This module covers only
the HTTP wiring Worker W added:

- Position not found → 404 with sanitized detail
- Service raises :class:`ResearchSourceUnavailable` → 502 with sanitized detail
- Happy path → 200 + payload that conforms to :class:`BusinessResponse`
- Unexpected exception → 500 with the generic CLAUDE.md detail

yfinance is never hit. We patch the service-level upstream by injecting a
test ``fetcher`` via :func:`app.services.research_business.build_business_payload`
through a tiny monkey-patch on the module-global default — the same hook
the service tests use.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import research_cache, yfinance_client


@pytest.fixture(autouse=True)
def _clear_research_cache():
    """Drop the in-memory research cache between tests (mirrors service tests)."""
    research_cache.clear()
    yield
    research_cache.clear()


def _create_position(client, ticker: str = "SOFI") -> str:
    """POST a minimal position and return its id."""
    resp = client.post(
        "/api/journal/positions",
        json={
            "ticker": ticker,
            "shares": 100,
            "broker_cost_basis": 2856.0,
            "opened_at": "2026-01-15T10:00:00Z",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _fake_info() -> dict:
    """Build a yfinance-shaped business info dict (mirrors service-test fixture)."""
    return {
        "name": "SoFi Technologies, Inc.",
        "long_business_summary": "SoFi is a personal finance company.",
        "sector": "Financial Services",
        "industry": "Credit Services",
        "market_cap": 18230000000,
        "employees": 4900,
    }


def test_get_business_404_for_missing_position(client):
    """Unknown ``position_id`` → 404 with sanitized detail (never str(e))."""
    resp = client.get("/api/positions/does-not-exist/research/business")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Position not found"}


def test_get_business_200_returns_payload(client):
    """yfinance returns full info → 200 with the BusinessResponse shape."""
    pid = _create_position(client)
    with patch.object(yfinance_client, "fetch_business_info", return_value=_fake_info()):
        resp = client.get(f"/api/positions/{pid}/research/business")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ticker"] == "SOFI"
    assert body["name"] == "SoFi Technologies, Inc."
    assert body["summary"].startswith("SoFi is")
    assert body["sector"] == "Financial Services"
    assert body["industry"] == "Credit Services"
    assert body["market_cap"] == 18230000000
    assert body["employees"] == 4900
    assert body["source"] == "yfinance"
    # ISO-8601 with trailing Z per PRD example
    assert isinstance(body["fetched_at"], str)
    assert body["fetched_at"].endswith("Z")


def test_get_business_502_on_source_unavailable(client):
    """yfinance hard-fail + empty cache → 502 with sanitized detail."""
    pid = _create_position(client)
    # When the service raises ResearchSourceUnavailable the router maps to 502.
    with patch.object(yfinance_client, "fetch_business_info", return_value=None):
        resp = client.get(f"/api/positions/{pid}/research/business")

    assert resp.status_code == 502
    # The detail string is the pre-sanitized service-layer value — never
    # the underlying yfinance exception's str().
    assert resp.json() == {"detail": "Source unavailable"}


def test_get_business_500_on_unexpected_exception(client):
    """Unexpected service exception → 500 with the generic CLAUDE.md detail."""
    pid = _create_position(client)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("internal explosion that must NOT leak to clients")

    # The router imports ``build_business_payload`` by name into its own
    # namespace; patch the binding in the router module (not the service
    # module) so the substitution is visible from the request path.
    with patch(
        "app.routers.research.build_business_payload", side_effect=_boom
    ):
        resp = client.get(f"/api/positions/{pid}/research/business")

    assert resp.status_code == 500
    body = resp.json()
    # Generic detail per CLAUDE.md — must NOT contain the original exception text.
    assert body == {"detail": "Failed to load research data. Please try again."}
    assert "explosion" not in body["detail"]
