"""Router-shell tests for ``GET /api/positions/{id}/research/financials`` (#280, W).

Service-layer coverage lives in ``tests/test_research_financials.py``. This
module covers only the HTTP wiring Worker W added:

- Position not found → 404 with sanitized detail
- Service raises :class:`ResearchSourceUnavailable` → 502 with sanitized detail
- Happy path → 200 + payload that conforms to :class:`FinancialsResponse`
- Unexpected exception → 500 with the generic CLAUDE.md detail

Alpha Vantage and yfinance are never hit — both upstreams are patched at
the service-import seam.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import (
    alpha_vantage_client,
    research_cache,
    yfinance_client,
)


@pytest.fixture(autouse=True)
def _clear_research_cache():
    """Drop the in-memory research cache between tests."""
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


def _av_quarter(period: str = "2025-03-31") -> dict:
    """Build an Alpha Vantage ``quarterlyReports`` row (camelCase keys)."""
    return {
        "fiscalDateEnding": period,
        "totalRevenue": "645000000",
        "reportedEPS": "0.02",
        "grossProfit": "277350000",  # 43% of revenue
        "operatingIncome": "25800000",  # ~4% of revenue
    }


def test_get_financials_404_for_missing_position(client):
    """Unknown ``position_id`` → 404 with sanitized detail."""
    resp = client.get("/api/positions/does-not-exist/research/financials")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Position not found"}


def test_get_financials_200_returns_av_payload(client):
    """AV primary returns data → 200 with ``source=alphavantage``."""
    pid = _create_position(client)
    # Use real quarter-end dates so the fixture does not contain invalid
    # calendar dates (CR #7 — 2025-02-30 was producing impossible dates).
    quarter_ends = [
        "2025-03-31",
        "2024-12-31",
        "2024-09-30",
        "2024-06-30",
        "2024-03-31",
        "2023-12-31",
        "2023-09-30",
        "2023-06-30",
    ]
    av_quarters = [_av_quarter(d) for d in quarter_ends]

    with patch.object(
        alpha_vantage_client, "get_income_statement", return_value=av_quarters
    ):
        resp = client.get(f"/api/positions/{pid}/research/financials")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ticker"] == "SOFI"
    assert body["source"] == "alphavantage"
    assert isinstance(body["quarters"], list)
    assert len(body["quarters"]) == 8
    # Schema sanity — each quarter has the keys defined on FinancialQuarter.
    expected_keys = {
        "period_end",
        "revenue",
        "eps",
        "gross_margin",
        "operating_margin",
    }
    assert set(body["quarters"][0].keys()) == expected_keys
    # Derived margins computed from the AV quarter fixture.
    first = body["quarters"][0]
    assert first["revenue"] == 645000000.0
    assert first["eps"] == 0.02
    assert first["gross_margin"] is not None
    assert 0.42 < first["gross_margin"] < 0.44


def test_get_financials_200_falls_back_to_yfinance(client):
    """AV down + yfinance up → 200 with ``source=yfinance``."""
    pid = _create_position(client)
    yf_quarters = [
        {
            "fiscal_date_ending": "2025-03-31",
            "total_revenue": 645000000,
            "diluted_eps": 0.02,
            "gross_profit": 277350000,
            "operating_income": 25800000,
        }
    ]

    with (
        patch.object(alpha_vantage_client, "get_income_statement", return_value=None),
        patch.object(
            yfinance_client, "fetch_quarterly_income_stmt", return_value=yf_quarters
        ),
    ):
        resp = client.get(f"/api/positions/{pid}/research/financials")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "yfinance"
    assert len(body["quarters"]) == 1


def test_get_financials_502_when_both_sources_unavailable(client):
    """AV ``None`` + yfinance ``None`` → 502 with sanitized detail."""
    pid = _create_position(client)

    with (
        patch.object(alpha_vantage_client, "get_income_statement", return_value=None),
        patch.object(
            yfinance_client, "fetch_quarterly_income_stmt", return_value=None
        ),
    ):
        resp = client.get(f"/api/positions/{pid}/research/financials")

    assert resp.status_code == 502
    assert resp.json() == {"detail": "Financials source unavailable"}


def test_get_financials_500_on_unexpected_exception(client):
    """Unexpected service exception → 500 with the generic CLAUDE.md detail."""
    pid = _create_position(client)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("internal explosion that must NOT leak to clients")

    # Patch the router's bound name (the service function was imported
    # into the router namespace, so the service-module attribute is no
    # longer the live reference).
    with patch(
        "app.routers.research.build_financials_payload", side_effect=_boom
    ):
        resp = client.get(f"/api/positions/{pid}/research/financials")

    assert resp.status_code == 500
    body = resp.json()
    assert body == {"detail": "Failed to load research data. Please try again."}
    assert "explosion" not in body["detail"]
