"""Integration tests for ``GET /api/positions/{id}/research/regression`` (issue #280).

Covers Worker D's contract: success path with all 3 factors, sector-omitted
branch, insufficient-data 422, upstream-failure 502, and the 5-minute cache.
The existing multi-factor OLS engine is exercised end-to-end with synthetic
return series; the upstream fetchers are mocked so tests are hermetic.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from app.models.schemas import DataMeta, DateRange
from app.services import research_regression
from app.services.data_fetcher import DataFetcher, DataFetchError


# --- Fixtures --------------------------------------------------------------


def _meta(n: int = 260) -> DataMeta:
    """Build a stub DataMeta with realistic counts."""
    return DataMeta(
        source="schwab",
        frequency="daily",
        fetched_at="2024-06-01T00:00:00+00:00",
        is_stale=False,
        record_count=n,
        date_range=DateRange(start="2023-01-01", end="2023-12-31"),
    )


def _price_series(n: int, seed: int, drift: float = 0.0005, vol: float = 0.015) -> pd.DataFrame:
    """Generate a synthetic daily-close price series as a single-column DataFrame."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-02", periods=n, freq="B")
    returns = rng.normal(drift, vol, n)
    prices = 100.0 * np.cumprod(1 + returns)
    df = pd.DataFrame({"value": prices}, index=dates)
    df.index.name = "date"
    return df


def _yield_series(n: int, seed: int) -> pd.DataFrame:
    """Generate a synthetic DGS10 yield series (percent levels)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-02", periods=n, freq="B")
    yields = 4.0 + np.cumsum(rng.normal(0.0, 0.02, n))
    df = pd.DataFrame({"value": yields}, index=dates)
    df.index.name = "date"
    return df


def _create_position(client, ticker: str = "AAPL") -> str:
    """POST a position via the journal API; return the new position id."""
    resp = client.post(
        "/api/journal/positions",
        json={
            "ticker": ticker,
            "shares": 100,
            "broker_cost_basis": 5000.0,
            "opened_at": "2024-01-15T10:00:00Z",
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def _three_factor_fetch_side_effect(
    ticker: str,
    *,
    n: int = 252,
    correlated_factors: bool = False,
):
    """Build a DataFetcher.fetch side-effect that returns 4 distinct series.

    The 4 series mimic ticker + SPY + sector ETF + DGS10. Schwab/FRED-style
    returns are emulated with synthetic random walks. By default the four
    series are statistically independent; ``correlated_factors=True`` makes
    SPY and the sector ETF nearly identical (VIF blow-up scenario).
    """
    spy = _price_series(n, seed=1)
    sector = spy.copy() if correlated_factors else _price_series(n, seed=2)
    target = _price_series(n, seed=3, drift=0.0007)
    dgs10 = _yield_series(n, seed=4)
    rates_map = {
        ticker: target,
        "SPY": spy,
        "DGS10": dgs10,
    }
    sector_etfs = {"XLF", "XLK", "XLV", "XLE", "XLP", "XLY", "XLI", "XLB", "XLU", "XLRE", "XLC"}

    def _side_effect(identifier: str, start: str, end: str):
        if identifier == ticker:
            return target, _meta(n)
        if identifier == "SPY":
            return spy, _meta(n)
        if identifier == "DGS10":
            return dgs10, _meta(n)
        if identifier in sector_etfs:
            return sector, _meta(n)
        raise AssertionError(f"Unexpected fetch identifier: {identifier}")

    return _side_effect


@pytest.fixture(autouse=True)
def _clear_regression_cache():
    """Clear the process-local response cache between tests."""
    research_regression.clear_cache()
    yield
    research_regression.clear_cache()


# --- Success path with all 3 factors --------------------------------------


def test_success_with_all_three_factors(client):
    """Financial Services position → basket includes SPY + XLF + DGS10."""
    position_id = _create_position(client, ticker="JPM")

    with patch.object(
        research_regression,
        "_resolve_sector_for_ticker",
        return_value="Financial Services",
    ), patch.object(
        DataFetcher,
        "fetch",
        side_effect=_three_factor_fetch_side_effect("JPM"),
    ):
        resp = client.get(
            f"/api/positions/{position_id}/research/regression"
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["position_id"] == position_id
    assert body["ticker"] == "JPM"
    assert body["window"] == "1Y"
    assert body["sector_omitted"] is False
    assert set(body["basket"]) == {"SPY", "XLF", "DGS10"}

    factor_names = [f["name"] for f in body["factors"]]
    assert factor_names == ["market", "sector", "rates", "idiosyncratic"]

    # Idiosyncratic has no beta/p-value; explicit None in payload.
    idio = [f for f in body["factors"] if f["name"] == "idiosyncratic"][0]
    assert idio["beta"] is None
    assert idio["p_value"] is None

    # Variance shares (factors + idio) should sum to ~1.0.
    total = sum(f["contribution"] for f in body["factors"])
    assert total == pytest.approx(1.0, abs=0.05)

    # Summary is a single short sentence — frozen 120-char cap.
    assert isinstance(body["summary"], str)
    assert body["summary"].endswith("trading days.")
    assert len(body["summary"]) <= 120


# --- Sector-omitted branch -------------------------------------------------


def test_sector_unknown_drops_to_two_factor_basket(client):
    """Unmapped sector → basket is SPY + DGS10 only and sector_omitted=True."""
    position_id = _create_position(client, ticker="ZZZX")

    with patch.object(
        research_regression,
        "_resolve_sector_for_ticker",
        return_value=None,  # unmapped / missing sector
    ), patch.object(
        DataFetcher,
        "fetch",
        side_effect=_three_factor_fetch_side_effect("ZZZX"),
    ):
        resp = client.get(
            f"/api/positions/{position_id}/research/regression"
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sector_omitted"] is True
    assert body["basket"] == ["SPY", "DGS10"]

    factor_names = [f["name"] for f in body["factors"]]
    assert factor_names == ["market", "rates", "idiosyncratic"]
    assert all(f["name"] != "sector" for f in body["factors"])


# --- Insufficient-data branch ---------------------------------------------


def test_insufficient_sample_size_returns_422(client):
    """Fewer than 60 aligned trading days → 422 with sanitized message."""
    position_id = _create_position(client, ticker="AAPL")

    short_series = _price_series(n=30, seed=10)
    short_yield = _yield_series(n=30, seed=11)

    def _short_side_effect(identifier: str, start: str, end: str):
        if identifier == "DGS10":
            return short_yield, _meta(30)
        return short_series, _meta(30)

    with patch.object(
        research_regression,
        "_resolve_sector_for_ticker",
        return_value="Technology",
    ), patch.object(DataFetcher, "fetch", side_effect=_short_side_effect):
        resp = client.get(
            f"/api/positions/{position_id}/research/regression"
        )

    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"] == "Insufficient data for regression"
    # Sanitized — never contains raw exception text or stack frames.
    assert "Traceback" not in body["detail"]


# --- Upstream-source failure ----------------------------------------------


def test_upstream_fetch_failure_returns_502(client):
    """Any upstream fetch raising → 502 with generic source message."""
    position_id = _create_position(client, ticker="AAPL")

    def _failing_fetch(identifier: str, start: str, end: str):
        raise DataFetchError("internal Schwab error with secret details")

    with patch.object(
        research_regression,
        "_resolve_sector_for_ticker",
        return_value="Technology",
    ), patch.object(DataFetcher, "fetch", side_effect=_failing_fetch):
        resp = client.get(
            f"/api/positions/{position_id}/research/regression"
        )

    assert resp.status_code == 502
    body = resp.json()
    assert body["detail"] == "Source unavailable for regression"
    # CLAUDE.md: never leak str(e) to the client.
    assert "secret" not in body["detail"]


# --- Position not found ---------------------------------------------------


def test_unknown_position_returns_404(client):
    """A position id that does not exist → 404."""
    resp = client.get(
        "/api/positions/does-not-exist/research/regression"
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Position not found"


# --- Window validation -----------------------------------------------------


def test_invalid_window_returns_422(client):
    """Any ``window`` value other than ``1Y`` → 422."""
    position_id = _create_position(client, ticker="AAPL")
    resp = client.get(
        f"/api/positions/{position_id}/research/regression?window=5Y"
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Unsupported window value"


# --- Cache behavior --------------------------------------------------------


def test_cache_hit_on_second_call_within_ttl(client):
    """Second call within TTL serves the cached response without fetching."""
    position_id = _create_position(client, ticker="JPM")
    side_effect = _three_factor_fetch_side_effect("JPM")
    call_log: list[str] = []

    def _logging_side_effect(identifier: str, start: str, end: str):
        call_log.append(identifier)
        return side_effect(identifier, start, end)

    with patch.object(
        research_regression,
        "_resolve_sector_for_ticker",
        return_value="Financial Services",
    ), patch.object(DataFetcher, "fetch", side_effect=_logging_side_effect):
        first = client.get(
            f"/api/positions/{position_id}/research/regression"
        )
        calls_after_first = len(call_log)
        second = client.get(
            f"/api/positions/{position_id}/research/regression"
        )

    assert first.status_code == 200
    assert second.status_code == 200
    # Second call must not touch the fetcher at all.
    assert calls_after_first > 0
    assert len(call_log) == calls_after_first
    # Both responses are byte-identical (deterministic from the cache).
    assert first.json() == second.json()


# --- Factor variance share normalization ----------------------------------


def test_factor_contributions_sum_to_approximately_one(client):
    """Sanity check: factor + idiosyncratic shares sum to ~1.0 (donut-ready)."""
    position_id = _create_position(client, ticker="JPM")

    with patch.object(
        research_regression,
        "_resolve_sector_for_ticker",
        return_value="Financial Services",
    ), patch.object(
        DataFetcher,
        "fetch",
        side_effect=_three_factor_fetch_side_effect("JPM"),
    ):
        resp = client.get(
            f"/api/positions/{position_id}/research/regression"
        )

    body: dict[str, Any] = resp.json()
    total = sum(f["contribution"] for f in body["factors"])
    assert 0.95 <= total <= 1.05
    assert 0.0 <= body["r_squared"] <= 1.0
    assert 0.0 <= body["idiosyncratic_share"] <= 1.0
