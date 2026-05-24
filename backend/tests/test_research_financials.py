"""Tests for Section D — Financial scorecard service (issue #280, W-A).

Covers :func:`app.services.research_financials.build_financials_payload`
including the AV-primary success path, the AV-rate-limit → yfinance
fallback path, the both-fail → sanitized 502 path, the 8-quarter
projection / margin math, source attribution, and the cache-hit path.

No real Alpha Vantage or yfinance traffic — both upstreams are patched
via the explicit fetcher hooks on the service function.

The "position not found → 404" acceptance criterion in the worker brief
is HTTP-layer behavior that lives on the router (owned by Worker W).
That test belongs alongside the router code; see the skipped placeholder
at the bottom of this file for the audit trail.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.models.database import AppSetting
from app.services import (
    alpha_vantage_client,
    research_cache,
    research_financials,
)
from app.services.research_business import ResearchSourceUnavailable


@pytest.fixture(autouse=True)
def _clear_caches():
    """Drop both the research cache and the AV client's hot caches."""
    research_cache.clear()
    alpha_vantage_client.clear_cache()
    alpha_vantage_client.clear_income_cache()
    yield
    research_cache.clear()
    alpha_vantage_client.clear_cache()
    alpha_vantage_client.clear_income_cache()


def _db_session(client):
    """Pull a session bound to the in-memory test DB."""
    from app.main import app
    from app.models.database import get_db

    override = app.dependency_overrides[get_db]
    return next(override())


def _av_quarter(
    *,
    period: str,
    revenue: str = "645000000",
    gross_profit: str = "277350000",
    operating_income: str = "25800000",
    net_income: str = "10000000",
    eps: str = "0.02",
) -> dict[str, Any]:
    """Build one AV ``quarterlyReports`` entry in the wire format."""
    return {
        "fiscalDateEnding": period,
        "totalRevenue": revenue,
        "grossProfit": gross_profit,
        "operatingIncome": operating_income,
        "netIncome": net_income,
        "reportedEPS": eps,
    }


def _yf_quarter(
    *,
    period: str,
    revenue: float = 645000000.0,
    gross_profit: float = 277350000.0,
    operating_income: float = 25800000.0,
    net_income: float = 10000000.0,
    eps: float = 0.02,
) -> dict[str, Any]:
    """Build one yfinance-shaped quarter (snake_case normalized keys)."""
    return {
        "fiscal_date_ending": period,
        "total_revenue": revenue,
        "gross_profit": gross_profit,
        "operating_income": operating_income,
        "net_income": net_income,
        "diluted_eps": eps,
    }


def _ten_av_quarters() -> list[dict[str, Any]]:
    """Return 10 AV quarters newest-first so the 8-quarter slice is tested."""
    quarters = []
    for i in range(10):
        # 2025-03-31, 2024-12-31, 2024-09-30, ...
        year = 2025 - (i // 4)
        month_day = ["03-31", "12-31", "09-30", "06-30"][i % 4]
        quarters.append(_av_quarter(period=f"{year}-{month_day}"))
    return quarters


# ---------------------------------------------------------------------------
# Success path — Alpha Vantage primary
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_build_financials_payload_av_primary_success(client):
    """AV returns 10 quarters → response carries 8, source=alphavantage."""
    db = _db_session(client)
    av_fetcher = MagicMock(return_value=_ten_av_quarters())
    yf_fetcher = MagicMock(return_value=None)

    payload = research_financials.build_financials_payload(
        db, "SOFI", av_fetcher=av_fetcher, yf_fetcher=yf_fetcher
    )

    assert payload["ticker"] == "SOFI"
    assert payload["source"] == "alphavantage"
    assert len(payload["quarters"]) == 8
    # Sliced to 8 newest-first; yfinance never invoked
    av_fetcher.assert_called_once_with("SOFI", 8)
    yf_fetcher.assert_not_called()


@pytest.mark.integration
def test_av_quarter_projection_computes_margins(client):
    """gross_margin = gross_profit / total_revenue; operating_margin same shape."""
    db = _db_session(client)
    av_fetcher = MagicMock(
        return_value=[
            _av_quarter(
                period="2025-03-31",
                revenue="1000",
                gross_profit="430",
                operating_income="40",
                eps="0.02",
            )
        ]
    )

    payload = research_financials.build_financials_payload(
        db, "SOFI", av_fetcher=av_fetcher, yf_fetcher=MagicMock()
    )

    q = payload["quarters"][0]
    assert q["period_end"] == "2025-03-31"
    assert q["revenue"] == 1000.0
    assert q["eps"] == 0.02
    assert q["gross_margin"] == pytest.approx(0.43)
    assert q["operating_margin"] == pytest.approx(0.04)


@pytest.mark.integration
def test_av_quarter_with_missing_fields_surfaces_none_margins(client):
    """Missing numerator/denominator → margins are JSON null, not 0."""
    db = _db_session(client)
    av_fetcher = MagicMock(
        return_value=[
            {
                "fiscalDateEnding": "2025-03-31",
                "totalRevenue": "None",  # AV stringifies "None"
                "grossProfit": "100",
                "operatingIncome": "10",
                "reportedEPS": "0.02",
            }
        ]
    )

    payload = research_financials.build_financials_payload(
        db, "SOFI", av_fetcher=av_fetcher, yf_fetcher=MagicMock()
    )

    q = payload["quarters"][0]
    assert q["revenue"] is None
    assert q["gross_margin"] is None
    assert q["operating_margin"] is None
    # EPS still surfaces — independent field
    assert q["eps"] == 0.02


# ---------------------------------------------------------------------------
# AV rate-limit → yfinance fallback
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_av_rate_limited_falls_back_to_yfinance(client):
    """AV returns None → yfinance is called; source attribution flips."""
    db = _db_session(client)
    av_fetcher = MagicMock(return_value=None)
    yf_fetcher = MagicMock(
        return_value=[
            _yf_quarter(period="2025-03-31"),
            _yf_quarter(period="2024-12-31"),
        ]
    )

    payload = research_financials.build_financials_payload(
        db, "SOFI", av_fetcher=av_fetcher, yf_fetcher=yf_fetcher
    )

    av_fetcher.assert_called_once_with("SOFI", 8)
    yf_fetcher.assert_called_once_with("SOFI", 8)
    assert payload["source"] == "yfinance"
    assert len(payload["quarters"]) == 2
    assert payload["quarters"][0]["period_end"] == "2025-03-31"


@pytest.mark.integration
def test_yfinance_fallback_payload_is_persisted_to_app_settings(client):
    """yfinance fallback writes a durable yf_financials:{ticker} row."""
    db = _db_session(client)
    av_fetcher = MagicMock(return_value=None)
    yf_fetcher = MagicMock(
        return_value=[_yf_quarter(period="2025-03-31")]
    )

    research_financials.build_financials_payload(
        db, "SOFI", av_fetcher=av_fetcher, yf_fetcher=yf_fetcher
    )

    row = (
        db.query(AppSetting)
        .filter(AppSetting.key == "yf_financials:SOFI")
        .first()
    )
    assert row is not None
    _, _, json_part = row.value.partition("|")
    persisted = json.loads(json_part)
    assert persisted["source"] == "yfinance"
    assert persisted["quarters"][0]["period_end"] == "2025-03-31"


# ---------------------------------------------------------------------------
# Both sources fail → sanitized 502
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_both_sources_fail_raises_sanitized_error(client):
    """AV None + yfinance None → ResearchSourceUnavailable; no str(e) leak.

    Per issue #288 the Section D both-empty detail names the ticker
    and both upstreams explicitly so the user can act on it.
    """
    db = _db_session(client)
    av_fetcher = MagicMock(return_value=None)
    yf_fetcher = MagicMock(return_value=None)

    with pytest.raises(ResearchSourceUnavailable) as exc:
        research_financials.build_financials_payload(
            db, "SOFI", av_fetcher=av_fetcher, yf_fetcher=yf_fetcher
        )

    # CLAUDE.md: sanitized, generic detail; #288 locks the verbatim copy
    assert exc.value.detail == (
        "No financial data available for SOFI. "
        "Both Alpha Vantage and Yahoo Finance returned empty for this symbol."
    )
    assert "Exception" not in str(exc.value)


# ---------------------------------------------------------------------------
# Cache hit (in-memory)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cache_hit_skips_both_upstreams_on_second_call(client):
    """Second call within TTL serves the composed payload from research_cache."""
    db = _db_session(client)
    av_fetcher = MagicMock(return_value=_ten_av_quarters())
    yf_fetcher = MagicMock(return_value=None)

    first = research_financials.build_financials_payload(
        db, "SOFI", av_fetcher=av_fetcher, yf_fetcher=yf_fetcher
    )
    second = research_financials.build_financials_payload(
        db, "SOFI", av_fetcher=av_fetcher, yf_fetcher=yf_fetcher
    )

    assert first == second
    # Only the first call touched the AV upstream
    assert av_fetcher.call_count == 1


@pytest.mark.integration
def test_durable_yf_cache_serves_after_in_memory_eviction(client):
    """Pre-seeded yf_financials app_setting served when AV is unavailable."""
    db = _db_session(client)

    fixture_payload = {
        "ticker": "SOFI",
        "quarters": [
            {
                "period_end": "2025-03-31",
                "revenue": 645000000,
                "eps": 0.02,
                "gross_margin": 0.43,
                "operating_margin": 0.04,
            }
        ],
        "source": "yfinance",
        "fetched_at": "2026-05-22T17:30:00Z",
    }
    fetched_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.add(
        AppSetting(
            key="yf_financials:SOFI",
            value=f"{fetched_at.isoformat()}|{json.dumps(fixture_payload)}",
        )
    )
    db.commit()

    av_fetcher = MagicMock(return_value=None)
    yf_fetcher = MagicMock(return_value=None)

    payload = research_financials.build_financials_payload(
        db, "SOFI", av_fetcher=av_fetcher, yf_fetcher=yf_fetcher
    )

    # Durable cache served the row; yfinance not invoked again
    yf_fetcher.assert_not_called()
    assert payload["source"] == "yfinance"
    assert payload["quarters"][0]["period_end"] == "2025-03-31"


# ---------------------------------------------------------------------------
# Position not found — router-layer test placeholder
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skip(
    reason="Position-not-found returns 404 at the HTTP router layer; "
    "that test belongs alongside backend/app/routers/research.py "
    "(Worker W). The service layer never sees a position id — it "
    "only takes a ticker."
)
def test_position_not_found_returns_404_via_router():
    """See routers/research.py + test_research_router.py (Worker W)."""


# ---------------------------------------------------------------------------
# Issue #288 — Section D copy: both-empty names the ticker; throttled YF
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_section_d_both_sources_empty_includes_ticker_in_detail(client):
    """AV None + yfinance None → detail names the ticker + both sources verbatim."""
    db = _db_session(client)
    av_fetcher = MagicMock(return_value=None)
    yf_fetcher = MagicMock(return_value=None)

    with pytest.raises(ResearchSourceUnavailable) as exc:
        research_financials.build_financials_payload(
            db, "SOFI", av_fetcher=av_fetcher, yf_fetcher=yf_fetcher
        )

    assert exc.value.detail == (
        "No financial data available for SOFI. "
        "Both Alpha Vantage and Yahoo Finance returned empty for this symbol."
    )


@pytest.mark.integration
def test_section_d_av_empty_then_yfinance_throttled_raises_throttling(client):
    """AV None + yfinance throttled → ResearchSourceUnavailable with throttling copy."""
    from app.services.yfinance_client import YFinanceRateLimitedError

    db = _db_session(client)
    av_fetcher = MagicMock(return_value=None)

    def _raise_throttle(_ticker, _n):
        raise YFinanceRateLimitedError("Yahoo Finance rate-limited the request")

    with pytest.raises(ResearchSourceUnavailable) as exc:
        research_financials.build_financials_payload(
            db, "SOFI", av_fetcher=av_fetcher, yf_fetcher=_raise_throttle
        )

    assert exc.value.detail == (
        "Yahoo Finance is throttling us — try again in a few minutes."
    )
