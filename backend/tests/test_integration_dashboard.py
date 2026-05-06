"""Integration tests for GET /api/dashboard.

Mirrors the AC scenarios in issue #114:
- empty journal
- populated journal
- Schwab disconnected
- stale cache

Plus a CLAUDE.md-required scenario asserting that 500 responses do not leak
raw exception strings.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.database import CacheEntry, Position, Session as SessionModel, Trade
from app.services import dashboard as dashboard_service


# -- Helpers -----------------------------------------------------------------


def _patch_status(monkeypatch, *, schwab_configured=False, fred_key=""):
    """Stub Schwab/FRED status helpers so tests don't require real credentials."""
    monkeypatch.setattr(
        "app.services.dashboard.SchwabTokenManager",
        _make_schwab_mgr(configured=schwab_configured),
    )
    monkeypatch.setattr(
        "app.services.dashboard.get_fred_api_key",
        lambda: fred_key,
    )


def _make_schwab_mgr(*, configured: bool, expires_at: str | None = None):
    class _Mgr:
        def is_configured(self):
            return configured

        def get_refresh_token_expiry(self):
            return expires_at

    def _ctor():
        return _Mgr()

    return _ctor


def _seed_position(client, **overrides) -> str:
    """Create a position via the API and return its id."""
    payload = {
        "ticker": "AAPL",
        "shares": 100,
        "broker_cost_basis": 17000.0,
        "strategy": "wheel",
        "opened_at": "2026-04-01T10:00:00Z",
    }
    payload.update(overrides)
    resp = client.post("/api/journal/positions", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed_trade(client, position_id: str, **overrides) -> str:
    payload = {
        "position_id": position_id,
        "trade_type": "sell_put",
        "strike": 175.0,
        "expiration": "2026-05-08",
        "premium": 2.25,
        "fees": 0.65,
        "quantity": 1,
        "opened_at": "2026-04-30T10:00:00Z",
    }
    payload.update(overrides)
    resp = client.post("/api/journal/trades", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# -- Tests -------------------------------------------------------------------


def test_dashboard_empty_journal(client, monkeypatch):
    """No positions, no sessions, no Schwab/FRED, empty cache."""
    _patch_status(monkeypatch, schwab_configured=False, fred_key="")

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"]["schwab"]["configured"] is False
    assert data["status"]["fred"]["configured"] is False
    assert data["status"]["cache"]["total"] == 0
    assert data["status"]["journal"]["positions_count"] == 0

    assert data["kpis"]["open_positions"] == 0
    assert data["kpis"]["open_legs"] == 0
    assert data["kpis"]["unrealized_pl"] is None

    assert data["positions"] == []
    assert data["open_legs"] == []
    assert data["upcoming_expirations"] == []
    assert data["recent_activity"] == []

    assert data["data_meta"]["is_stale"] is False
    assert data["data_meta"]["sources_unavailable"] == []


def test_dashboard_populated(client, monkeypatch):
    """Two positions, several open legs incl. one ITM ≤ 7 DTE, Schwab connected."""
    _patch_status(monkeypatch, schwab_configured=True, fred_key="abc123")

    # Mock Schwab quotes — one ITM put (AAPL @ 174 vs strike 175) and one OTM call.
    quote_responses = {
        "AAPL": {"lastPrice": 174.0},
        "TSLA": {"lastPrice": 230.0},
    }

    def fake_get_quote(self, ticker):
        return quote_responses[ticker]

    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote", fake_get_quote
    )

    # Pin "today" so DTE math is deterministic.
    today = datetime(2026, 5, 5, tzinfo=timezone.utc).date()
    monkeypatch.setattr(
        "app.services.dashboard.date",
        type("D", (), {"today": staticmethod(lambda: today)}),
    )

    aapl_id = _seed_position(client, ticker="AAPL", broker_cost_basis=17000.0)
    tsla_id = _seed_position(
        client,
        ticker="TSLA",
        broker_cost_basis=20000.0,
        shares=100,
        strategy="cc",
    )

    # AAPL short put 175 expires in 3 days → ITM → roll-or-assign
    _seed_trade(
        client,
        aapl_id,
        trade_type="sell_put",
        strike=175.0,
        expiration="2026-05-08",
    )
    # TSLA short call 240 expires in 10 days → OTM → hold
    _seed_trade(
        client,
        tsla_id,
        trade_type="sell_call",
        strike=240.0,
        expiration="2026-05-15",
    )
    # Closed leg should be excluded from open_legs
    _seed_trade(
        client,
        aapl_id,
        trade_type="sell_put",
        strike=170.0,
        expiration="2026-04-15",
        closed_at="2026-04-30T15:00:00Z",
        close_reason="fifty_pct_target",
    )

    # Save a session so recent_activity has both event kinds
    session_resp = client.post(
        "/api/sessions", json={"name": "AAPL vs DGS10 5y", "config": {"asset": "AAPL"}}
    )
    assert session_resp.status_code in (200, 201), session_resp.text

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"]["schwab"]["configured"] is True
    assert data["status"]["fred"]["configured"] is True
    assert data["status"]["journal"]["positions_count"] == 2

    assert data["kpis"]["open_positions"] == 2
    assert data["kpis"]["open_legs"] == 2
    assert data["kpis"]["open_legs_breakdown"] == {"puts": 1, "calls": 1}

    # Unrealized P/L is computed because both quotes resolved.
    assert data["kpis"]["unrealized_pl"] is not None

    # AAPL leg is in upcoming with the right tag.
    upcoming_tickers = {leg["ticker"] for leg in data["upcoming_expirations"]}
    assert "AAPL" in upcoming_tickers
    aapl_upcoming = next(
        leg for leg in data["upcoming_expirations"] if leg["ticker"] == "AAPL"
    )
    assert aapl_upcoming["decision_tag"] == "roll-or-assign"
    assert aapl_upcoming["dte"] == 3

    # Recent activity contains both the trade and the session.
    kinds = {event["kind"] for event in data["recent_activity"]}
    assert "session_saved" in kinds
    assert "trade_added" in kinds

    assert data["data_meta"]["sources_unavailable"] == []
    # Cache is empty so no stale flag from cache; quotes succeeded.
    assert data["data_meta"]["is_stale"] is False


def test_dashboard_schwab_disconnected(client, monkeypatch):
    """Positions exist but Schwab is not configured."""
    _patch_status(monkeypatch, schwab_configured=False, fred_key="")

    aapl_id = _seed_position(client, ticker="AAPL", broker_cost_basis=17000.0)
    _seed_trade(
        client,
        aapl_id,
        trade_type="sell_put",
        strike=175.0,
        expiration="2026-05-08",
    )

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"]["schwab"]["configured"] is False
    assert data["status"]["journal"]["positions_count"] == 1

    # No prices means no notional / P/L.
    assert all(row["current_price"] is None for row in data["positions"])
    assert all(row["notional"] is None for row in data["positions"])
    assert data["kpis"]["unrealized_pl"] is None
    assert data["kpis"]["notional_value"] == 0

    # Open legs render but moneyness is None.
    assert len(data["open_legs"]) == 1
    assert data["open_legs"][0]["moneyness"] is None


def test_dashboard_schwab_quote_failure(client, monkeypatch):
    """When Schwab is configured but a quote call raises, mark sources_unavailable."""
    from app.services.schwab_client import SchwabClientError

    _patch_status(monkeypatch, schwab_configured=True, fred_key="")

    def fake_get_quote(self, ticker):
        raise SchwabClientError("simulated outage")

    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote", fake_get_quote
    )

    pid = _seed_position(client, ticker="AAPL", broker_cost_basis=17000.0)
    _seed_trade(
        client,
        pid,
        trade_type="sell_put",
        strike=175.0,
        expiration="2026-05-08",
    )

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert "schwab" in data["data_meta"]["sources_unavailable"]
    assert data["data_meta"]["is_stale"] is True


def test_dashboard_unexpected_quote_exception_does_not_500(client, monkeypatch):
    """A non-Schwab exception escaping a per-ticker quote call must not 500.

    Regression guard for PR #116 review item: previously the worker only
    caught SchwabClientError/SchwabAuthError, so any other exception (httpx
    timeout escaping tenacity, malformed payload causing KeyError, etc.)
    would propagate out of ThreadPoolExecutor.map and surface as a 500.
    """
    _patch_status(monkeypatch, schwab_configured=True, fred_key="")

    aapl_id = _seed_position(client, ticker="AAPL", broker_cost_basis=17000.0)
    _seed_trade(
        client,
        aapl_id,
        trade_type="sell_put",
        strike=175.0,
        expiration="2026-05-08",
    )
    msft_id = _seed_position(client, ticker="MSFT", broker_cost_basis=30000.0)
    _seed_trade(
        client,
        msft_id,
        trade_type="sell_call",
        strike=320.0,
        expiration="2026-05-15",
    )

    def fake_get_quote(self, ticker):
        if ticker == "AAPL":
            # A non-Schwab exception escaping the client (e.g. httpx timeout
            # that exhausted tenacity retries, or a KeyError from a malformed
            # payload). Must be swallowed by the worker.
            raise RuntimeError("synthetic unexpected failure")
        return {"lastPrice": 318.5}

    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote", fake_get_quote
    )

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Failed ticker shows a None price; the dashboard still rendered.
    rows_by_ticker = {row["ticker"]: row for row in data["positions"]}
    assert rows_by_ticker["AAPL"]["current_price"] is None
    assert rows_by_ticker["AAPL"]["notional"] is None
    # Healthy ticker still has its price.
    assert rows_by_ticker["MSFT"]["current_price"] == 318.5

    # And the failure is surfaced on data_meta so the UI can flag it.
    assert "schwab" in data["data_meta"]["sources_unavailable"]
    assert data["data_meta"]["is_stale"] is True


def test_dashboard_stale_cache(client, monkeypatch):
    """Cache contains entries >30 days old → flagged stale."""
    _patch_status(monkeypatch, schwab_configured=False, fred_key="")

    # Insert a stale CacheEntry directly via the test session.
    from app.main import app
    from app.models.database import get_db

    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        sixty_days_ago = (
            datetime.now(timezone.utc) - timedelta(days=60)
        ).isoformat()
        db.add(
            CacheEntry(
                asset_key="schwab:AAPL",
                data="[]",
                fetched_at=sixty_days_ago,
                source_frequency="daily",
                source_name="schwab",
            )
        )
        db.commit()
    finally:
        try:
            next(db_gen)
        except StopIteration:
            pass

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"]["cache"]["stale"] >= 1
    assert data["data_meta"]["is_stale"] is True


def test_dashboard_500_does_not_leak_exception(client, monkeypatch):
    """CLAUDE.md: API responses must not include raw exception messages."""
    _patch_status(monkeypatch, schwab_configured=False, fred_key="")

    secret = "PRIVATE TRACEBACK SHOULD NOT APPEAR"

    def explode(_db):
        raise RuntimeError(secret)

    monkeypatch.setattr(
        "app.routers.dashboard.build_dashboard_payload", explode
    )

    resp = client.get("/api/dashboard")
    assert resp.status_code == 500
    body = resp.text
    assert secret not in body
    assert "Failed to load dashboard" in body
