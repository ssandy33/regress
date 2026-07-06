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
    """Create a position via the API and return its id.

    Per issue #131 ``strategy`` is no longer accepted on PositionCreate;
    the recomputer derives the label from the trade ledger. Callers that
    need a specific strategy on the seeded row should add a trade after
    creation so the recomputer derives the desired label.
    """
    payload = {
        "ticker": "AAPL",
        "shares": 100,
        "broker_cost_basis": 17000.0,
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


@pytest.mark.integration
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
    assert data["recent_activity"] == []
    # Issue #248 — the Upcoming-expirations panel was retired; the field is
    # gone from the response and no consumer reads it.
    assert "upcoming_expirations" not in data

    assert data["data_meta"]["is_stale"] is False
    assert data["data_meta"]["sources_unavailable"] == []


@pytest.mark.integration
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

    # Mock Schwab option chains so the % CAPT (profit-target) signal resolves.
    # The AAPL short put 175 was opened for a 2.25 credit (the _seed_trade
    # default); a current mid of 0.90 → 60% of the credit captured.
    chain_responses = {
        "AAPL": {
            "putExpDateMap": {
                "2026-05-08:3": {
                    "175.0": [{"strikePrice": 175.0, "mark": 0.90}],
                }
            },
        },
        "TSLA": {
            "callExpDateMap": {
                "2026-05-15:10": {
                    "240.0": [{"strikePrice": 240.0, "mark": 1.10}],
                }
            },
        },
    }

    def fake_get_option_chain(self, ticker, *args, **kwargs):
        return chain_responses[ticker]

    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_option_chain",
        fake_get_option_chain,
    )

    # Pin "today" so DTE math is deterministic.
    today = datetime(2026, 5, 5, tzinfo=timezone.utc).date()
    monkeypatch.setattr(
        "app.services.dashboard.market_today",
        lambda: today,
    )

    aapl_id = _seed_position(client, ticker="AAPL", broker_cost_basis=17000.0)
    tsla_id = _seed_position(
        client,
        ticker="TSLA",
        broker_cost_basis=20000.0,
        shares=100,
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
    # Issue #131: ``holding`` is part of the additive breakdown shape.
    # Both seeded positions retain the create-time "csp" placeholder
    # because the manual trade flow does not invoke the recomputer.
    assert "holding" in data["kpis"]["open_positions_breakdown"]

    # Unrealized P/L is computed because both quotes resolved.
    assert data["kpis"]["unrealized_pl"] is not None

    # % CAPT is now a real value — AAPL short put 175 opened for 2.25, current
    # mid 0.90 → (2.25 - 0.90) / 2.25 = 0.60 captured, past the 50% target.
    aapl_leg = next(leg for leg in data["open_legs"] if leg["ticker"] == "AAPL")
    assert aapl_leg["profit_target_status"]["state"] == "captured_50"
    assert aapl_leg["profit_target_status"]["captured_pct"] == pytest.approx(0.60)

    # Recent activity contains both the trade and the session.
    kinds = {event["kind"] for event in data["recent_activity"]}
    assert "session_saved" in kinds
    assert "trade_added" in kinds

    assert data["data_meta"]["sources_unavailable"] == []
    # Cache is empty so no stale flag from cache; quotes succeeded.
    assert data["data_meta"]["is_stale"] is False


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
def test_dashboard_option_chain_failure_degrades_gracefully(client, monkeypatch):
    """A failed option-chain fetch flags `schwab` and degrades % CAPT to unknown.

    Quotes still succeed, so moneyness resolves; only the profit-target signal
    degrades. The dashboard must still return 200.
    """
    from app.services.schwab_client import SchwabClientError

    _patch_status(monkeypatch, schwab_configured=True, fred_key="")

    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote",
        lambda self, ticker: {"lastPrice": 174.0},
    )

    def fake_get_option_chain(self, ticker, *args, **kwargs):
        raise SchwabClientError("simulated chain outage")

    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_option_chain",
        fake_get_option_chain,
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

    # The chain failure is folded into the partial-outage flags.
    assert "schwab" in data["data_meta"]["sources_unavailable"]
    assert data["data_meta"]["is_stale"] is True

    # The leg renders, but % CAPT degrades to unknown (no live mark).
    assert len(data["open_legs"]) == 1
    assert data["open_legs"][0]["profit_target_status"] == {
        "captured_pct": None,
        "state": "unknown",
    }


@pytest.mark.integration
def test_dashboard_unexpected_chain_exception_does_not_500(client, monkeypatch):
    """A non-Schwab exception escaping a per-ticker chain call must not 500.

    Defense-in-depth: the chain-fetch worker catches broad Exception so a
    malformed payload or escaped timeout cannot propagate out of
    ThreadPoolExecutor.map and surface as a 500.
    """
    _patch_status(monkeypatch, schwab_configured=True, fred_key="")

    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote",
        lambda self, ticker: {"lastPrice": 174.0},
    )

    def fake_get_option_chain(self, ticker, *args, **kwargs):
        raise RuntimeError("synthetic unexpected chain failure")

    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_option_chain",
        fake_get_option_chain,
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
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Surfaced as a partial outage; the dashboard still rendered.
    assert "schwab" in data["data_meta"]["sources_unavailable"]
    assert data["open_legs"][0]["profit_target_status"]["state"] == "unknown"


@pytest.mark.integration
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


@pytest.mark.integration
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


# ---------------------------------------------------------------------------
# V0.5 contract — issue #146
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_dashboard_payload_schema_v05_keys(client, monkeypatch):
    """Snapshot test: assert every V0.5 top-level + nested key is present."""
    _patch_status(monkeypatch, schwab_configured=False, fred_key="")

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()

    # Top-level keys — `next_actions` is the V0.5 addition.
    # Issue #248 — `upcoming_expirations` was retired; assert its absence so a
    # future regression that resurrects the field is caught here.
    expected_top_level = {
        "generated_at",
        "status",
        "kpis",
        "positions",
        "open_legs",
        "recent_activity",
        "data_meta",
        "next_actions",
    }
    assert expected_top_level <= set(data.keys())
    assert "upcoming_expirations" not in data

    # KPI extensions per spec §14.4.
    kpi_keys = set(data["kpis"].keys())
    for new_field in (
        "largest_risk",
        "largest_loser",
        "premium_collected_total",
        "premium_collected_ytd",
        "premium_collected_trades",
        "realized_pl",
        "realized_pl_pct",
    ):
        assert new_field in kpi_keys, f"missing kpis.{new_field}"

    # Engine output is a list (empty on a fresh dashboard with no open legs
    # the scanner card still fires — but the field shape must exist).
    assert isinstance(data["next_actions"], list)


@pytest.mark.integration
def test_dashboard_position_row_includes_per_share_basis(client, monkeypatch):
    """Issue #320: dashboard rows carry per-share basis for the cost cell."""
    _patch_status(monkeypatch, schwab_configured=False, fred_key="")
    _seed_position(client, ticker="AAPL", shares=100, broker_cost_basis=2856.0)

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    row = next(r for r in resp.json()["positions"] if r["ticker"] == "AAPL")
    assert row["broker_cost_basis_per_share"] == 28.56
    # No trades → adjusted total == broker total → same per-share value.
    assert row["adjusted_cost_basis_per_share"] == 28.56


@pytest.mark.integration
def test_dashboard_scanner_card_when_no_open_legs(client, monkeypatch):
    """`journal.no_open_legs` emits even when there are zero positions."""
    _patch_status(monkeypatch, schwab_configured=True, fred_key="abc123")

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    ids = {a["action_id"] for a in data["next_actions"]}
    assert "journal.no_open_legs" in ids


@pytest.mark.integration
def test_dashboard_schwab_disconnected_action(client, monkeypatch):
    """`data.schwab_disconnected` fires when Schwab is not configured."""
    _patch_status(monkeypatch, schwab_configured=False, fred_key="")

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    ids = {a["action_id"] for a in data["next_actions"]}
    assert "data.schwab_disconnected" in ids


@pytest.mark.integration
def test_dashboard_itm_short_dte_action(client, monkeypatch):
    """An ITM ≤ 7 DTE leg triggers the per-leg expiration card."""
    _patch_status(monkeypatch, schwab_configured=True, fred_key="abc123")

    # Mock Schwab so the put is ITM (price 174 < strike 175).
    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote",
        lambda self, ticker: {"lastPrice": 174.0},
    )

    today = datetime(2026, 5, 5, tzinfo=timezone.utc).date()
    monkeypatch.setattr(
        "app.services.dashboard.market_today",
        lambda: today,
    )

    pid = _seed_position(client, ticker="AAPL", broker_cost_basis=17000.0)
    _seed_trade(
        client,
        pid,
        trade_type="sell_put",
        strike=175.0,
        expiration="2026-05-08",  # 3 DTE
    )

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    ids = {a["action_id"] for a in data["next_actions"]}
    assert "expiration.itm_short_dte" in ids


@pytest.mark.integration
def test_dashboard_per_leg_signals_present(client, monkeypatch):
    """Every open leg carries the V0.5 signal fields (issue #146 §14.5)."""
    _patch_status(monkeypatch, schwab_configured=True, fred_key="abc123")
    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote",
        lambda self, ticker: {"lastPrice": 174.0},
    )
    # Chain has no matching strike for the seeded leg → % CAPT stays unknown,
    # deterministically (independent of any locally configured Schwab token).
    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_option_chain",
        lambda self, ticker, *a, **kw: {
            "putExpDateMap": {
                "2099-12-31:99999": {
                    "999.0": [{"strikePrice": 999.0, "mark": 1.00}],
                }
            }
        },
    )

    pid = _seed_position(client, ticker="AAPL", broker_cost_basis=17000.0)
    _seed_trade(
        client,
        pid,
        trade_type="sell_put",
        strike=175.0,
        expiration="2099-12-31",  # far DTE so the card doesn't get truncated
    )

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["open_legs"], "expected at least one open leg"
    leg = data["open_legs"][0]
    # V0.5 contract: every leg carries these fields.
    assert leg["profit_target_status"] == {
        "captured_pct": None,
        "state": "unknown",
    }
    assert leg["assignment_risk"] in {"high", "watch", "low"}
    assert leg["suggested_action"] in {"roll", "hold", "manage"}
    # close is intentionally never emitted in V0.5.
    assert leg["suggested_action"] != "close"
    assert leg["earnings_in_window"] is False  # no AV cache hit in tests


@pytest.mark.integration
def test_dashboard_position_rows_have_v05_signals(client, monkeypatch):
    """Position rows include `wheel_status`, `next_suggested_action`, and `pl_pct`."""
    _patch_status(monkeypatch, schwab_configured=True, fred_key="abc123")
    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote",
        lambda self, ticker: {"lastPrice": 180.0},
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
    assert data["positions"], "expected at least one position row"
    row = data["positions"][0]
    assert row["wheel_status"] in {"CSP", "CC", "Wheel", "Holding"}
    assert "next_suggested_action" in row
    # pl_pct is None when no price OR when basis is zero — here we have both.
    assert "pl_pct" in row
    # #151 — broker_cost_basis is surfaced so the Positions card can render
    # the dual-line ("broker / adjusted") cost-basis cell.
    assert row["broker_cost_basis"] == 17000.0


@pytest.mark.integration
def test_dashboard_rule_monitor_verdict_layer_present(client, monkeypatch):
    """Every open leg carries the §R6 verdict layer fields (issue #240)."""
    _patch_status(monkeypatch, schwab_configured=True, fred_key="abc123")
    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote",
        lambda self, ticker: {"lastPrice": 200.0},
    )
    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_option_chain",
        lambda self, ticker, *a, **kw: {
            "putExpDateMap": {
                "2099-12-31:99999": {
                    "999.0": [{"strikePrice": 999.0, "mark": 1.00}],
                }
            }
        },
    )
    pid = _seed_position(client, ticker="AAPL", broker_cost_basis=17000.0)
    _seed_trade(client, pid, trade_type="sell_put", strike=175.0, expiration="2099-12-31")

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["open_legs"], "expected at least one open leg"
    leg = data["open_legs"][0]
    assert leg["verdict"] in {
        "hold", "profit_take_review", "dte_review", "expiration", "assignment"
    }
    assert isinstance(leg["verdict_label"], str)
    assert isinstance(leg["reasoning"], str)
    assert isinstance(leg["triggered_rules"], list)
    assert len(leg["triggered_rules"]) == 4


@pytest.mark.integration
def test_dashboard_profit_take_card_matches_leg_verdict(client, monkeypatch):
    """A leg past the profit-take threshold yields the verdict AND the card."""
    _patch_status(monkeypatch, schwab_configured=True, fred_key="abc123")
    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote",
        lambda self, ticker: {"lastPrice": 250.0},
    )
    # Live option mark of 0.40 against a premium of 1.00 → 60% captured.
    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_option_chain",
        lambda self, ticker, *a, **kw: {
            "putExpDateMap": {
                "2099-12-31:99999": {
                    "175.0": [{"strikePrice": 175.0, "mark": 0.40}],
                }
            }
        },
    )
    pid = _seed_position(client, ticker="AAPL", broker_cost_basis=17000.0)
    _seed_trade(
        client,
        pid,
        trade_type="sell_put",
        strike=175.0,
        expiration="2099-12-31",
        premium=1.00,
    )

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    leg = data["open_legs"][0]
    assert leg["verdict"] == "profit_take_review"
    assert leg["verdict_label"] == "Review · 50%"

    cards = [
        a for a in data["next_actions"]
        if a["action_id"] == "leg.profit_take_review"
    ]
    assert len(cards) == 1
    assert cards[0]["tone"] == "opportunity"
    assert cards[0]["priority"] == "P1"


# -- Issue #277: Schwab pill honesty -----------------------------------------
#
# The token-row check in ``_build_schwab_status`` cannot detect that *live*
# Schwab calls failed during this dashboard load. Issue #277 anchors the
# fix: ``build_dashboard_payload`` reconciles ``status.schwab`` with the
# ``schwab_failed`` flag already produced by ``_fetch_quotes_parallel`` and
# ``_fetch_option_chains_parallel``. These tests pin the new contract.


@pytest.mark.integration
def test_schwab_pill_downgrades_to_invalid_when_quotes_fail(client, monkeypatch):
    """When the live quote fan returns ``schwab_failed=True`` the dashboard
    must downgrade ``status.schwab.valid`` to ``False`` and surface the
    frozen ``error`` discriminator (issue #277).
    """
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

    schwab = data["status"]["schwab"]
    assert schwab["configured"] is True
    assert schwab["valid"] is False
    assert schwab["error"] == "Schwab API calls failing this load"


@pytest.mark.integration
def test_schwab_pill_stays_valid_on_success(client, monkeypatch):
    """Happy path: live calls succeed, ``status.schwab`` stays
    ``{valid: True, error: None}`` (issue #277 regression guard).
    """
    _patch_status(monkeypatch, schwab_configured=True, fred_key="")

    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote",
        lambda self, ticker: {"lastPrice": 174.0},
    )
    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_option_chain",
        lambda self, ticker, *args, **kwargs: {
            "putExpDateMap": {
                "2026-05-08:3": {
                    "175.0": [{"strikePrice": 175.0, "mark": 0.90}],
                }
            }
        },
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

    schwab = data["status"]["schwab"]
    assert schwab["configured"] is True
    assert schwab["valid"] is True
    assert schwab["error"] is None


@pytest.mark.integration
def test_schwab_pill_downgrades_when_chains_fail_but_quotes_succeed(
    client, monkeypatch
):
    """A failed option-chain fetch (quotes still OK) must still downgrade
    the pill to ``valid=False`` with the frozen error string (issue #277).
    The existing graceful-degradation behaviour (sources_unavailable) is
    preserved.
    """
    from app.services.schwab_client import SchwabClientError

    _patch_status(monkeypatch, schwab_configured=True, fred_key="")

    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote",
        lambda self, ticker: {"lastPrice": 174.0},
    )

    def fake_get_option_chain(self, ticker, *args, **kwargs):
        raise SchwabClientError("simulated chain outage")

    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_option_chain",
        fake_get_option_chain,
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

    schwab = data["status"]["schwab"]
    assert schwab["valid"] is False
    assert schwab["error"] == "Schwab API calls failing this load"
    # Existing graceful-degradation behaviour is preserved.
    assert "schwab" in data["data_meta"]["sources_unavailable"]
    assert data["data_meta"]["is_stale"] is True


@pytest.mark.integration
def test_schwab_pill_error_field_absent_when_schwab_not_configured(
    client, monkeypatch
):
    """When Schwab is not configured the pill stays in its existing
    ``not connected`` state and ``error`` is ``None`` (no live call was
    attempted, so no live failure to surface). Regression guard for
    issue #277.
    """
    _patch_status(monkeypatch, schwab_configured=False, fred_key="")

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()

    schwab = data["status"]["schwab"]
    assert schwab["configured"] is False
    assert schwab["valid"] is False
    assert schwab["error"] is None



# ---------------------------------------------------------------------------
# Issue #318 — assignment-risk depth-awareness (deep-ITM past 14 DTE)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_dashboard_leg_deep_itm_call_reports_high(client, monkeypatch):
    """AC1 — a deep-ITM short call past 14 DTE reports assignment_risk "high".

    The F reproduction: pre-fix this floored to "low" because 17 DTE is outside
    the 14-day Watch window. The chain carries a 0.93 delta → depth "deep" →
    independent-max escalates the leg to "high".
    """
    _patch_status(monkeypatch, schwab_configured=True, fred_key="abc123")
    # Price 20 > strike 15 → ITM short call.
    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote",
        lambda self, ticker: {"lastPrice": 20.0},
    )
    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_option_chain",
        lambda self, ticker, *a, **kw: {
            "callExpDateMap": {
                "2026-05-22:17": {
                    "15.0": [{"strikePrice": 15.0, "mark": 5.10, "delta": 0.93}],
                }
            }
        },
    )
    today = datetime(2026, 5, 5, tzinfo=timezone.utc).date()
    monkeypatch.setattr(
        "app.services.dashboard.market_today",
        lambda: today,
    )

    pid = _seed_position(client, ticker="F", shares=100, broker_cost_basis=1500.0)
    _seed_trade(
        client,
        pid,
        trade_type="sell_call",
        strike=15.0,
        expiration="2026-05-22",  # 17 DTE — past the 14-day timing floor
        premium=0.40,
    )

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["open_legs"], "expected at least one open leg"
    leg = data["open_legs"][0]
    assert leg["dte"] == 17
    assert leg["assignment_risk"] == "high"


@pytest.mark.integration
def test_dashboard_leg_delta_threads_from_chain(client, monkeypatch):
    """AC6 — the chain's delta surfaces on the derived dashboard leg.

    Proves the shared build_option_leg_index -> derive_open_legs wiring through
    the full service stack: a delta seeded on the chain node reaches the leg
    dict (the field #319 consumes), and current_mid stays a plain float.

    Asserted on the internal leg dict (captured via a spy on the real
    derive_open_legs), not the HTTP payload — per the #318 plan the wire shape
    is intentionally unchanged, so DashboardResponse strips these leg-internal
    fields. #319 will promote them onto the response model when it needs them.
    """
    _patch_status(monkeypatch, schwab_configured=True, fred_key="abc123")
    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote",
        lambda self, ticker: {"lastPrice": 20.0},
    )
    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_option_chain",
        lambda self, ticker, *a, **kw: {
            "callExpDateMap": {
                "2026-05-22:17": {
                    "15.0": [{"strikePrice": 15.0, "mark": 5.10, "delta": 0.91}],
                }
            }
        },
    )
    today = datetime(2026, 5, 5, tzinfo=timezone.utc).date()
    monkeypatch.setattr(
        "app.services.dashboard.market_today",
        lambda: today,
    )

    # Spy on the real derive_open_legs to capture the un-stripped leg dicts.
    captured: list[dict] = []
    real_derive = dashboard_service.derive_open_legs

    def _spy(*args, **kwargs):
        legs = real_derive(*args, **kwargs)
        captured.extend(legs)
        return legs

    monkeypatch.setattr("app.services.dashboard.derive_open_legs", _spy)

    pid = _seed_position(client, ticker="F", shares=100, broker_cost_basis=1500.0)
    _seed_trade(
        client,
        pid,
        trade_type="sell_call",
        strike=15.0,
        expiration="2026-05-22",
        premium=0.40,
    )

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    assert captured, "expected derive_open_legs to yield at least one leg"
    leg = captured[0]
    assert leg["delta"] == pytest.approx(0.91)
    assert leg["delta_source"] == "market"
    assert leg["assignment_depth"] == "deep"
    assert leg["current_mid"] == pytest.approx(5.10)
    assert isinstance(leg["current_mid"], float)


# ---------------------------------------------------------------------------
# Issue #375 — expiration cards route to the per-leg BTC decision screen
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_dashboard_expiration_cards_link_to_btc(client, monkeypatch):
    """C-8 — full stack: an ITM short-DTE leg and an OTM short-DTE aggregate
    both surface CTAs to the per-leg BTC route, with no `/journal?position=`
    dead-end (issue #375 AC1/AC2/AC3)."""
    import re

    _patch_status(monkeypatch, schwab_configured=True, fred_key="abc123")

    # AAPL put @ 175 with price 174 → ITM (per-leg `expiration.itm_short_dte`).
    # TSLA put @ 200 with price 230 → OTM (aggregate `expiration.short_dte`).
    quote_responses = {"AAPL": {"lastPrice": 174.0}, "TSLA": {"lastPrice": 230.0}}

    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote",
        lambda self, ticker: quote_responses[ticker],
    )

    today = datetime(2026, 5, 5, tzinfo=timezone.utc).date()
    monkeypatch.setattr(
        "app.services.dashboard.market_today",
        lambda: today,
    )

    aapl_id = _seed_position(client, ticker="AAPL", broker_cost_basis=17000.0)
    _seed_trade(
        client,
        aapl_id,
        trade_type="sell_put",
        strike=175.0,
        expiration="2026-05-08",  # 3 DTE → ITM short-DTE per-leg card
    )
    tsla_id = _seed_position(client, ticker="TSLA", broker_cost_basis=20000.0)
    _seed_trade(
        client,
        tsla_id,
        trade_type="sell_put",
        strike=200.0,
        expiration="2026-05-09",  # 4 DTE → OTM short-DTE aggregate card
    )

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()

    cards_by_id = {a["action_id"]: a for a in data["next_actions"]}
    assert "expiration.itm_short_dte" in cards_by_id
    assert "expiration.short_dte" in cards_by_id

    btc_route = re.compile(r"^/positions/[^/]+/legs/[^/]+/btc$")
    for action_id in ("expiration.itm_short_dte", "expiration.short_dte"):
        href = cards_by_id[action_id]["cta"]["href"]
        assert btc_route.match(href), f"{action_id} href not BTC route: {href!r}"
        assert "/journal?position=" not in href


# -- Issue #421 (PRD #415 R3): per-position + account-level day change --------
#
# The rich-quote threading refactor stops discarding the closePrice / netChange
# / netPercentChange fields Schwab already returns on the quote node, so the DAY
# column and the account-level day-change tile populate from the same fetch.


@pytest.mark.integration
def test_dashboard_positions_carry_day_change(client, monkeypatch):
    """A configured Schwab quote with netChange / netPercentChange populates the
    per-position day_change / day_change_pct / day_state fields (#421 R3)."""
    _patch_status(monkeypatch, schwab_configured=True, fred_key="")

    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote",
        lambda self, ticker: {
            "lastPrice": 12.5,
            "mark": 12.5,
            "closePrice": 12.07,
            "netChange": 0.43,
            "netPercentChange": 3.56,
        },
    )

    pid = _seed_position(client, ticker="NOK", broker_cost_basis=1207.0, shares=100)
    _seed_trade(
        client,
        pid,
        trade_type="sell_call",
        strike=15.0,
        expiration="2026-08-15",
    )

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()

    row = next(r for r in data["positions"] if r["ticker"] == "NOK")
    assert row["day_state"] == "populated"
    # 0.43 per-share × 100 shares = $43.00 equity day change.
    assert row["day_change"] == pytest.approx(43.0)
    # 3.56 (Schwab number) normalized to a fraction.
    assert row["day_change_pct"] == pytest.approx(0.0356)


@pytest.mark.integration
def test_dashboard_payload_has_account_summary(client, monkeypatch):
    """The payload carries an account_summary block whose day change sums the
    per-position equity day changes; reconciliation fields stay unavailable on
    the #421 spine (#421 R1/R2/R3 wiring)."""
    _patch_status(monkeypatch, schwab_configured=True, fred_key="")

    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote",
        lambda self, ticker: {
            "lastPrice": 12.5,
            "closePrice": 12.07,
            "netChange": 0.43,
            "netPercentChange": 3.56,
        },
    )

    pid = _seed_position(client, ticker="NOK", broker_cost_basis=1207.0, shares=100)
    _seed_trade(
        client,
        pid,
        trade_type="sell_call",
        strike=15.0,
        expiration="2026-08-15",
    )

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    summary = resp.json()["account_summary"]
    assert summary is not None
    assert summary["day_state"] == "populated"
    assert summary["day_change"] == pytest.approx(43.0)
    # Broker reconciliation is wired by a later worker — unavailable here.
    assert summary["account_value"] is None
    assert summary["cash"] is None
    assert summary["reconciles"] is False


@pytest.mark.integration
def test_dashboard_no_prior_close_state(client, monkeypatch):
    """A quote lacking closePrice / netChange yields the explicit no_prior_close
    state rather than a silent zero (#421 R3 empty state)."""
    _patch_status(monkeypatch, schwab_configured=True, fred_key="")

    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote",
        lambda self, ticker: {"lastPrice": 20.0},  # price only, no day fields
    )

    pid = _seed_position(client, ticker="AAPL", broker_cost_basis=1900.0, shares=100)
    _seed_trade(
        client,
        pid,
        trade_type="sell_call",
        strike=25.0,
        expiration="2026-08-15",
    )

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()

    row = next(r for r in data["positions"] if r["ticker"] == "AAPL")
    assert row["day_state"] == "no_prior_close"
    assert row["day_change"] is None
    assert row["day_change_pct"] is None
    assert data["account_summary"]["day_state"] == "no_prior_close"
