"""Integration + unit tests for the research price-history endpoint.

Covers ``GET /api/positions/{id}/research/price-history`` (issue #280 /
v1.1.0 — Worker B).

Test plan (from the CTO plan §6.1 and the worker prompt):

- Success path with mocked Schwab + mocked AV + fixture trades
- AV-down → empty earnings_events with 200 (graceful degradation)
- Schwab-down → 502
- Cache-hit on second call (15-minute TTL — no second fetch)
- Position not found → 404
- Empty position (no trades) → 200 with basis but empty trade_events
- Window param parsing: default ``1Y``; ``6M``, ``2Y`` accepted; other → 422

Pattern: integration tests use the in-memory SQLite ``client`` fixture
from ``conftest.py`` and patch the *named* dependencies of the service
module (``DataFetcher.fetch`` for prices, ``get_historical_earnings``
for AV). Unit tests for the trade-event mapper exercise the
private helper directly.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from app.models.database import Position, Trade
from app.models.schemas import DataMeta, DateRange
from app.services import research_price_history as svc


# ---------------------------------------------------------------------------
# Fixtures + seeders
# ---------------------------------------------------------------------------

_POS_ID = "pos-sofi"
_TICKER = "SOFI"
_BROKER_BASIS = 2856.0  # 100 shares @ 28.56
_SHARES = 100

# Time-relative trade timestamps so DTE-style assertions don't rot when the
# suite is run on a different day (matches the BTC detail tests' approach).
_OPEN_DATE = (date.today() - timedelta(days=120)).isoformat()
_CLOSE_DATE = (date.today() - timedelta(days=60)).isoformat()


def _db(client):
    """Pull a DB session from the FastAPI override."""
    from app.main import app
    from app.models.database import get_db

    override = app.dependency_overrides[get_db]
    return next(override())


def _seed_position_with_trades(
    client,
    *,
    pos_id: str = _POS_ID,
    ticker: str = _TICKER,
    shares: int = _SHARES,
    broker_basis: float = _BROKER_BASIS,
    with_trades: bool = True,
) -> str:
    """Seed one open position with two representative trades.

    The trades produce one ``sell_put`` event and one ``buy_close`` event
    (the latter exercises the legacy ``buy_put_close`` → ``buy_close``
    normalization). Skipped when ``with_trades=False`` so callers can
    test the "no trades" edge case.
    """
    db = _db(client)
    try:
        db.add(
            Position(
                id=pos_id,
                ticker=ticker,
                shares=shares,
                broker_cost_basis=broker_basis,
                status="open",
                strategy="csp",
                opened_at=_OPEN_DATE,
            )
        )
        if with_trades:
            # Premium 0.50 collected when sell_put opened; closed for 0.10
            # (net +0.40 → adjusted basis goes down).
            db.add(
                Trade(
                    id=f"{pos_id}-sp1",
                    position_id=pos_id,
                    trade_type="sell_put",
                    strike=28.0,
                    expiration=(date.today() - timedelta(days=80)).isoformat(),
                    premium=0.50,
                    fees=0.0,
                    quantity=1,
                    opened_at=_OPEN_DATE,
                    closed_at=_CLOSE_DATE,
                    close_reason="closed_early",
                )
            )
            db.add(
                Trade(
                    id=f"{pos_id}-bp1",
                    position_id=pos_id,
                    trade_type="buy_put_close",
                    strike=28.0,
                    expiration=(date.today() - timedelta(days=80)).isoformat(),
                    premium=-0.10,
                    fees=0.0,
                    quantity=1,
                    opened_at=_CLOSE_DATE,
                )
            )
        db.commit()
    finally:
        db.close()
    return pos_id


def _price_df(n: int = 60, base: float = 25.0) -> pd.DataFrame:
    """Build a minimal daily-close DataFrame in DataFetcher's contract.

    The fetcher returns a ``DatetimeIndex`` + a ``value`` column; the
    composition layer iterates rows in order and emits ``{date, close}``.
    """
    today = date.today()
    idx = pd.date_range(end=today, periods=n, freq="D")
    values = [base + i * 0.05 for i in range(n)]
    df = pd.DataFrame({"value": values}, index=idx)
    df.index.name = "date"
    return df


def _price_meta(n: int = 60) -> DataMeta:
    today = date.today()
    return DataMeta(
        source="schwab",
        frequency="daily",
        fetched_at=today.isoformat() + "T00:00:00+00:00",
        is_stale=False,
        record_count=n,
        date_range=DateRange(
            start=(today - timedelta(days=n)).isoformat(),
            end=today.isoformat(),
        ),
    )


@pytest.fixture(autouse=True)
def _clear_price_history_cache():
    """The composition cache is process-global; isolate each test."""
    svc.clear_cache()
    yield
    svc.clear_cache()


# ---------------------------------------------------------------------------
# Service-layer unit tests
# ---------------------------------------------------------------------------


class TestTradeEventMapping:
    """:func:`_trade_events_from_position` correctly normalizes legacy types."""

    @pytest.mark.integration
    def test_normalizes_buy_put_close_to_buy_close(self):
        events = svc._trade_events_from_position(
            {
                "id": "p",
                "trades": [
                    {
                        "trade_type": "buy_put_close",
                        "strike": 26.0,
                        "opened_at": "2025-02-15T10:00:00Z",
                    }
                ],
            }
        )
        assert len(events) == 1
        assert events[0].type == "buy_close"
        assert events[0].date == "2025-02-15"
        assert events[0].strike == 26.0

    @pytest.mark.integration
    def test_normalizes_buy_call_close_to_buy_close(self):
        events = svc._trade_events_from_position(
            {
                "id": "p",
                "trades": [
                    {
                        "trade_type": "buy_call_close",
                        "strike": 30.0,
                        "opened_at": "2025-03-15",
                    }
                ],
            }
        )
        assert events[0].type == "buy_close"

    @pytest.mark.integration
    def test_passes_through_v1_vocabulary_unchanged(self):
        for raw in ("sell_put", "sell_call", "assignment", "called_away", "expired"):
            events = svc._trade_events_from_position(
                {
                    "id": "p",
                    "trades": [
                        {
                            "trade_type": raw,
                            "strike": 10.0,
                            "opened_at": "2025-01-01",
                        }
                    ],
                }
            )
            assert events and events[0].type == raw, raw

    @pytest.mark.integration
    def test_skips_unknown_trade_types(self):
        events = svc._trade_events_from_position(
            {
                "id": "p",
                "trades": [
                    {
                        "trade_type": "mystery",
                        "strike": 10.0,
                        "opened_at": "2025-01-01",
                    },
                    {
                        "trade_type": "sell_put",
                        "strike": 10.0,
                        "opened_at": "2025-01-02",
                    },
                ],
            }
        )
        assert [e.type for e in events] == ["sell_put"]

    @pytest.mark.integration
    def test_skips_rows_without_opened_at(self):
        events = svc._trade_events_from_position(
            {
                "id": "p",
                "trades": [{"trade_type": "sell_put", "strike": 10.0}],
            }
        )
        assert events == []

    @pytest.mark.integration
    def test_sorts_events_by_date(self):
        events = svc._trade_events_from_position(
            {
                "id": "p",
                "trades": [
                    {"trade_type": "sell_put", "strike": 10.0, "opened_at": "2025-03-01"},
                    {"trade_type": "sell_call", "strike": 12.0, "opened_at": "2025-01-15"},
                    {"trade_type": "expired", "strike": 12.0, "opened_at": "2025-02-15"},
                ],
            }
        )
        assert [e.date for e in events] == ["2025-01-15", "2025-02-15", "2025-03-01"]


class TestWindowResolution:
    """:func:`_window_dates` returns a sensible (start, end) range."""

    @pytest.mark.integration
    def test_default_window_is_one_year(self):
        start, end = svc._window_dates("1Y")
        # The window is 365 days; allow ±1 day for the day-boundary edge.
        delta = (date.fromisoformat(end) - date.fromisoformat(start)).days
        assert 364 <= delta <= 366

    @pytest.mark.integration
    @pytest.mark.parametrize("window,min_days,max_days", [
        ("6M", 182, 184),
        ("1Y", 364, 366),
        ("2Y", 729, 731),
    ])
    def test_supported_windows_have_correct_lookback(self, window, min_days, max_days):
        start, end = svc._window_dates(window)
        delta = (date.fromisoformat(end) - date.fromisoformat(start)).days
        assert min_days <= delta <= max_days

    @pytest.mark.integration
    def test_unsupported_window_raises(self):
        with pytest.raises(svc.InvalidWindowError):
            svc._window_dates("3D")


# ---------------------------------------------------------------------------
# Integration tests — full endpoint behavior
# ---------------------------------------------------------------------------


# Patch targets — keep them in one place so a refactor finds them all.
_FETCH_PATCH = "app.services.research_price_history.DataFetcher.fetch"
_AV_PATCH = "app.services.research_price_history.get_historical_earnings"


class TestPriceHistoryEndpoint:
    """End-to-end behavior of ``GET /research/price-history``."""

    @pytest.mark.integration
    def test_success_path_with_trades_and_earnings(self, client):
        _seed_position_with_trades(client)
        earnings = [
            (date.today() - timedelta(days=90)).isoformat(),
            (date.today() - timedelta(days=10)).isoformat(),
        ]
        with patch(_FETCH_PATCH, return_value=(_price_df(), _price_meta())), \
             patch(_AV_PATCH, return_value=earnings):
            resp = client.get(
                f"/api/positions/{_POS_ID}/research/price-history"
            )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["ticker"] == _TICKER
        assert payload["window"] == "1Y"
        # Prices: 60 daily rows from the fixture
        assert len(payload["prices"]) == 60
        assert all("date" in p and "close" in p for p in payload["prices"])
        # Basis lines present, broker matches seed
        assert payload["basis"]["broker"] == _BROKER_BASIS
        # adjusted_cost_basis is journal-computed (broker - premiums after
        # netting); we only assert the field is present and a float here —
        # the journal's own tests own the exact-value coverage.
        assert isinstance(payload["basis"]["adjusted"], (int, float))
        # Trade events from two seeded trades
        trade_types = [e["type"] for e in payload["trade_events"]]
        assert "sell_put" in trade_types
        assert "buy_close" in trade_types
        # Earnings events came from the mocked AV
        assert {e["date"] for e in payload["earnings_events"]} == set(earnings)
        for e in payload["earnings_events"]:
            assert e["label"] == "Earnings"

    @pytest.mark.integration
    def test_empty_position_returns_basis_and_empty_trade_events(self, client):
        _seed_position_with_trades(client, with_trades=False)
        with patch(_FETCH_PATCH, return_value=(_price_df(), _price_meta())), \
             patch(_AV_PATCH, return_value=[]):
            resp = client.get(
                f"/api/positions/{_POS_ID}/research/price-history"
            )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["trade_events"] == []
        assert payload["basis"]["broker"] == _BROKER_BASIS
        # No trades → adjusted basis equals broker basis (no premium offset).
        assert payload["basis"]["adjusted"] == _BROKER_BASIS

    @pytest.mark.integration
    def test_av_failure_degrades_to_empty_earnings_with_200(self, client):
        """AV unavailable must NOT fail the whole payload (NFR-3)."""
        _seed_position_with_trades(client)
        with patch(_FETCH_PATCH, return_value=(_price_df(), _price_meta())), \
             patch(_AV_PATCH, return_value=[]):
            resp = client.get(
                f"/api/positions/{_POS_ID}/research/price-history"
            )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["earnings_events"] == []
        assert len(payload["prices"]) > 0  # primary signal still rendered

    @pytest.mark.integration
    def test_av_raises_unexpected_exception_still_degrades_to_empty(self, client):
        """Even if the AV client raises, the endpoint must stay 200."""
        _seed_position_with_trades(client)
        with patch(_FETCH_PATCH, return_value=(_price_df(), _price_meta())), \
             patch(_AV_PATCH, side_effect=RuntimeError("AV exploded")):
            resp = client.get(
                f"/api/positions/{_POS_ID}/research/price-history"
            )
        assert resp.status_code == 200
        assert resp.json()["earnings_events"] == []

    @pytest.mark.integration
    def test_price_source_failure_returns_502(self, client):
        _seed_position_with_trades(client)
        with patch(_FETCH_PATCH, side_effect=RuntimeError("schwab kaboom")), \
             patch(_AV_PATCH, return_value=[]):
            resp = client.get(
                f"/api/positions/{_POS_ID}/research/price-history"
            )
        assert resp.status_code == 502
        body = resp.json()
        assert body["detail"] == "Price source unavailable"
        # CLAUDE.md: no raw exception messages in API responses.
        assert "kaboom" not in body["detail"]

    @pytest.mark.integration
    def test_position_not_found_returns_404(self, client):
        with patch(_FETCH_PATCH, return_value=(_price_df(), _price_meta())), \
             patch(_AV_PATCH, return_value=[]):
            resp = client.get(
                "/api/positions/does-not-exist/research/price-history"
            )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Position not found"

    @pytest.mark.integration
    def test_default_window_is_one_year(self, client):
        _seed_position_with_trades(client)
        with patch(_FETCH_PATCH, return_value=(_price_df(), _price_meta())), \
             patch(_AV_PATCH, return_value=[]):
            resp = client.get(
                f"/api/positions/{_POS_ID}/research/price-history"
            )
        assert resp.status_code == 200
        assert resp.json()["window"] == "1Y"

    @pytest.mark.integration
    @pytest.mark.parametrize("window", ["6M", "1Y", "2Y"])
    def test_supported_windows_accepted(self, client, window):
        _seed_position_with_trades(client)
        with patch(_FETCH_PATCH, return_value=(_price_df(), _price_meta())), \
             patch(_AV_PATCH, return_value=[]):
            resp = client.get(
                f"/api/positions/{_POS_ID}/research/price-history?window={window}"
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["window"] == window

    @pytest.mark.integration
    def test_lowercase_window_accepted(self, client):
        """The service uppercases ``window`` before validating."""
        _seed_position_with_trades(client)
        with patch(_FETCH_PATCH, return_value=(_price_df(), _price_meta())), \
             patch(_AV_PATCH, return_value=[]):
            resp = client.get(
                f"/api/positions/{_POS_ID}/research/price-history?window=1y"
            )
        assert resp.status_code == 200
        assert resp.json()["window"] == "1Y"

    @pytest.mark.integration
    def test_unsupported_window_returns_422(self, client):
        _seed_position_with_trades(client)
        with patch(_FETCH_PATCH, return_value=(_price_df(), _price_meta())), \
             patch(_AV_PATCH, return_value=[]):
            resp = client.get(
                f"/api/positions/{_POS_ID}/research/price-history?window=3D"
            )
        assert resp.status_code == 422
        # Detail must enumerate the supported set so callers can self-correct.
        detail = resp.json()["detail"]
        for w in ("6M", "1Y", "2Y"):
            assert w in detail

    @pytest.mark.integration
    def test_cache_hit_skips_second_fetch_within_ttl(self, client):
        """Second call within 15 min should NOT re-fetch prices or earnings."""
        _seed_position_with_trades(client)
        with patch(_FETCH_PATCH, return_value=(_price_df(), _price_meta())) as fetch_mock, \
             patch(_AV_PATCH, return_value=[]) as av_mock:
            r1 = client.get(
                f"/api/positions/{_POS_ID}/research/price-history"
            )
            r2 = client.get(
                f"/api/positions/{_POS_ID}/research/price-history"
            )
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json() == r2.json()
        # Each upstream is called exactly once over the two HTTP requests.
        assert fetch_mock.call_count == 1
        assert av_mock.call_count == 1

    @pytest.mark.integration
    def test_cache_key_is_per_window(self, client):
        """Different window params get separate cache entries."""
        _seed_position_with_trades(client)
        with patch(_FETCH_PATCH, return_value=(_price_df(), _price_meta())) as fetch_mock, \
             patch(_AV_PATCH, return_value=[]):
            client.get(
                f"/api/positions/{_POS_ID}/research/price-history?window=1Y"
            )
            client.get(
                f"/api/positions/{_POS_ID}/research/price-history?window=6M"
            )
        # Two distinct windows → two upstream fetches.
        assert fetch_mock.call_count == 2
