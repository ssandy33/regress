"""Tests for the dashboard account-summary + options-in-totals slice (#420).

Covers PRD #415 R1 (account value reconciliation), R2 (cash as a first-class
figure sourced from the broker balance), R4 (open option legs rolled into the
portfolio value + unrealized-P/L aggregates), and the #419 realized-P/L
contamination guard.

Layer split (PRD #261 R3): pure-function composition + extraction are
``@pytest.mark.unit``; full-stack ``GET /api/dashboard`` wiring is
``@pytest.mark.integration``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services.dashboard import (
    _build_account_summary,
    _build_kpis,
    _compute_option_totals,
    _reconciles,
)
from app.services.schwab_account_value import (
    AccountValueResult,
    _extract_cash,
    _extract_option_market_value,
    _sanitise_accounts,
)


# -- Helpers -----------------------------------------------------------------


def _leg(**overrides) -> dict:
    base = {
        "id": "l1",
        "ticker": "AAPL",
        "type": "put",
        "strike": 175.0,
        "expiration": "2026-05-08",
        "dte": 10,
        "position_id": "p1",
        "pnl_dollars": None,
        "cost_to_close": None,
    }
    base.update(overrides)
    return base


def _row(*, notional=None, unrealized_pl=None, ticker="AAPL") -> dict:
    return {
        "id": "p1",
        "ticker": ticker,
        "shares": 100,
        "strategy": "csp",
        "adjusted_cost_basis": 17000.0,
        "current_price": None,
        "notional": notional,
        "unrealized_pl": unrealized_pl,
        "open_legs_count": 0,
        "wheel_status": "Holding",
        "next_suggested_action": "hold",
        "pl_pct": None,
    }


def _open_position(**overrides) -> dict:
    base = {
        "id": "p1",
        "ticker": "AAPL",
        "strategy": "csp",
        "adjusted_cost_basis": 17000.0,
        "total_premiums": 0.0,
        "trades": [],
        "realized_equity_pl": 0.0,
    }
    base.update(overrides)
    return base


def _account_result(**overrides) -> AccountValueResult:
    # Default ``cached_at`` is "now" so the broker value is fresh within the
    # reconcile window (#429) unless a test overrides it with a stale timestamp.
    base = dict(
        status="ok",
        total_capital=10000.0,
        cash=1365.26,
        cached_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return AccountValueResult(**base)


# -- R4: option totals -------------------------------------------------------


class TestComputeOptionTotals:
    @pytest.mark.unit
    def test_option_mv_short_leg_is_negative(self):
        # A short leg is a liability: MV = -cost_to_close (Risk #5).
        option_mv, _pnl, includes = _compute_option_totals(
            [_leg(cost_to_close=4.50, pnl_dollars=1.0)]
        )
        assert option_mv == pytest.approx(-4.50)
        assert includes is True

    @pytest.mark.unit
    def test_option_unrealized_uses_signed_pnl_dollars(self):
        _mv, option_pnl, _incl = _compute_option_totals(
            [_leg(cost_to_close=0.90, pnl_dollars=135.0)]
        )
        assert option_pnl == pytest.approx(135.0)

    @pytest.mark.unit
    def test_includes_options_flag_false_when_no_legs(self):
        option_mv, option_pnl, includes = _compute_option_totals([])
        assert option_mv == 0.0
        assert option_pnl == 0.0
        assert includes is False

    @pytest.mark.unit
    def test_includes_options_false_when_marks_unavailable(self):
        # Legs present but every mark unavailable → equity-only for this load.
        _mv, _pnl, includes = _compute_option_totals(
            [_leg(cost_to_close=None, pnl_dollars=None)]
        )
        assert includes is False


class TestKpisRollOptions:
    @pytest.mark.unit
    def test_kpis_notional_includes_option_mv(self):
        rows = [_row(notional=17400.0, unrealized_pl=400.0)]
        legs = [_leg(cost_to_close=4.50)]
        kpis = _build_kpis(
            rows,
            legs,
            [_open_position()],
            closed_positions=[],
            today=date(2026, 5, 1),
        )
        # 17400 equity + (-4.50) short option MV.
        assert kpis["notional_value"] == pytest.approx(17400.0 - 4.50)
        assert kpis["includes_options"] is True

    @pytest.mark.unit
    def test_kpis_unrealized_includes_option_pnl(self):
        rows = [_row(notional=17400.0, unrealized_pl=400.0)]
        legs = [_leg(cost_to_close=0.90, pnl_dollars=135.0)]
        kpis = _build_kpis(
            rows,
            legs,
            [_open_position()],
            closed_positions=[],
            today=date(2026, 5, 1),
        )
        assert kpis["unrealized_pl"] == pytest.approx(400.0 + 135.0)

    @pytest.mark.unit
    def test_kpis_no_legs_leaves_equity_only_totals(self):
        rows = [_row(notional=17400.0, unrealized_pl=400.0)]
        kpis = _build_kpis(
            rows, [], [_open_position()], closed_positions=[], today=date(2026, 5, 1)
        )
        assert kpis["notional_value"] == pytest.approx(17400.0)
        assert kpis["unrealized_pl"] == pytest.approx(400.0)
        assert kpis["includes_options"] is False


# -- R1/R2: account summary --------------------------------------------------


class TestReconcilesPredicate:
    @pytest.mark.unit
    def test_reconciles_true_within_tolerance(self):
        # $2 drift on a $10k account is within max($5, 0.1%·10k=$10).
        assert _reconciles(10002.0, 10000.0) is True

    @pytest.mark.unit
    def test_reconciles_false_outside_tolerance(self):
        # $50 drift on a $10k account exceeds the $10 pct tolerance.
        assert _reconciles(10050.0, 10000.0) is False

    @pytest.mark.unit
    def test_reconciles_abs_floor_on_tiny_account(self):
        # $4 drift on a $100 account is within the $5 absolute floor.
        assert _reconciles(104.0, 100.0) is True


class TestBuildAccountSummary:
    @pytest.mark.unit
    def test_account_value_sums_equity_option_cash(self):
        rows = [_row(notional=9166.0)]
        legs = [_leg(cost_to_close=4.50)]  # option_mv = -4.50
        with patch(
            "app.services.dashboard.get_account_value",
            return_value=_account_result(cash=1365.26, total_capital=10526.76),
        ):
            summary = _build_account_summary(
                db=None, position_rows=rows, open_legs=legs, schwab_configured=True
            )
        assert summary["equity_mv"] == pytest.approx(9166.0)
        assert summary["option_mv"] == pytest.approx(-4.50)
        assert summary["cash"] == pytest.approx(1365.26)
        assert summary["account_value"] == pytest.approx(9166.0 - 4.50 + 1365.26)

    @pytest.mark.unit
    def test_reconciles_true_within_tolerance_e2e(self):
        rows = [_row(notional=9166.0)]
        legs = [_leg(cost_to_close=4.50)]
        # broker net-liq matches the composed value exactly.
        with patch(
            "app.services.dashboard.get_account_value",
            return_value=_account_result(cash=1365.26, total_capital=9166.0 - 4.50 + 1365.26),
        ):
            summary = _build_account_summary(
                db=None, position_rows=rows, open_legs=legs, schwab_configured=True
            )
        assert summary["reconciles"] is True

    @pytest.mark.unit
    def test_reconciles_false_outside_tolerance(self):
        rows = [_row(notional=9166.0)]
        legs = []
        # broker reports a value $500 off the composed equity+cash.
        with patch(
            "app.services.dashboard.get_account_value",
            return_value=_account_result(cash=1365.26, total_capital=9166.0 + 1365.26 + 500.0),
        ):
            summary = _build_account_summary(
                db=None, position_rows=rows, open_legs=legs, schwab_configured=True
            )
        assert summary["reconciles"] is False

    @pytest.mark.unit
    def test_account_summary_empty_when_schwab_disconnected(self):
        # schwab_configured False + live pricing → no balance source → empty state.
        summary = _build_account_summary(
            db=None, position_rows=[_row(notional=9166.0)], open_legs=[], schwab_configured=False
        )
        assert summary["account_value"] is None
        assert summary["cash"] is None
        assert summary["reconciles"] is False
        assert summary["day_state"] == "no_prior_close"

    @pytest.mark.unit
    def test_account_summary_empty_when_cash_absent(self):
        # Connected but the broker balance carried no parseable cash → empty.
        with patch(
            "app.services.dashboard.get_account_value",
            return_value=_account_result(cash=None, total_capital=10000.0),
        ):
            summary = _build_account_summary(
                db=None, position_rows=[_row(notional=9166.0)], open_legs=[], schwab_configured=True
            )
        assert summary["cash"] is None
        assert summary["account_value"] is None

    @pytest.mark.unit
    def test_cash_sourced_from_balance_not_inferred(self):
        # Cash comes straight from the broker balance, never derived from math.
        rows = [_row(notional=9166.0)]
        with patch(
            "app.services.dashboard.get_account_value",
            return_value=_account_result(cash=42.42, total_capital=9166.0 + 42.42),
        ):
            summary = _build_account_summary(
                db=None, position_rows=rows, open_legs=[], schwab_configured=True
            )
        assert summary["cash"] == pytest.approx(42.42)


# -- R2: defensive cash / option-MV extraction -------------------------------


def _securities_account(**balances) -> dict:
    return {"accountNumber": "12344471", "type": "CASH", "currentBalances": balances}


class TestBalanceExtraction:
    @pytest.mark.unit
    def test_extract_cash_candidate_key_chain(self):
        # cash = cashBalance + moneyMarketFund.
        sec = _securities_account(cashBalance=1300.0, moneyMarketFund=65.26)
        assert _extract_cash(sec) == pytest.approx(1365.26)

    @pytest.mark.unit
    def test_extract_cash_none_when_cash_balance_absent(self):
        # Missing cashBalance → None (not a silent 0 from a stray sweep field).
        sec = _securities_account(moneyMarketFund=65.26)
        assert _extract_cash(sec) is None

    @pytest.mark.unit
    def test_extract_cash_sweep_optional(self):
        sec = _securities_account(cashBalance=1365.26)
        assert _extract_cash(sec) == pytest.approx(1365.26)

    @pytest.mark.unit
    def test_option_mv_short_leg_negative_from_balances(self):
        # short option MV marks negative (liability); long + short combine.
        sec = _securities_account(longOptionMarketValue=0.0, shortOptionMarketValue=-6.5)
        assert _extract_option_market_value(sec) == pytest.approx(-6.5)

    @pytest.mark.unit
    def test_option_mv_none_when_absent(self):
        sec = _securities_account(cashBalance=1000.0)
        assert _extract_option_market_value(sec) is None

    @pytest.mark.unit
    def test_sanitise_accounts_threads_parity_addends(self):
        raw = [
            {
                "securitiesAccount": _securities_account(
                    liquidationValue=10755.28,
                    cashBalance=1365.26,
                    longMarketValue=9396.52,
                    shortOptionMarketValue=-6.5,
                )
            }
        ]
        [account] = _sanitise_accounts(raw)
        assert account["cash"] == pytest.approx(1365.26)
        assert account["equity_market_value"] == pytest.approx(9396.52)
        assert account["option_market_value"] == pytest.approx(-6.5)
        # Live reconciliation identity (parity plan §Verified field contract).
        assert account["net_liquidation"] == pytest.approx(
            account["cash"] + account["equity_market_value"] + account["option_market_value"]
        )


# -- Integration: full-stack GET /api/dashboard wiring -----------------------


def _make_schwab_mgr(*, configured: bool):
    class _Mgr:
        def is_configured(self):
            return configured

        def get_refresh_token_expiry(self):
            return None

    return lambda: _Mgr()


def _patch_status(monkeypatch, *, schwab_configured):
    monkeypatch.setattr(
        "app.services.dashboard.SchwabTokenManager",
        _make_schwab_mgr(configured=schwab_configured),
    )
    monkeypatch.setattr("app.services.dashboard.get_fred_api_key", lambda: "")


def _seed_position(client, **overrides) -> str:
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


@pytest.mark.integration
def test_dashboard_payload_has_account_summary(client, monkeypatch):
    """R1/R2 wiring: the payload carries a populated account_summary block."""
    _patch_status(monkeypatch, schwab_configured=True)
    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote",
        lambda self, ticker: {"lastPrice": 175.0},
    )
    monkeypatch.setattr(
        "app.services.dashboard.get_account_value",
        lambda db: _account_result(cash=1365.26, total_capital=17500.0 + 1365.26),
    )
    _seed_position(client)

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    summary = resp.json()["account_summary"]
    assert summary["cash"] == pytest.approx(1365.26)
    assert summary["equity_mv"] == pytest.approx(17500.0)  # 100 shares @ 175
    assert summary["account_value"] == pytest.approx(17500.0 + 1365.26)
    assert summary["reconciles"] is True
    assert summary["reconcile_state"] == "reconciled"


@pytest.mark.integration
def test_dashboard_account_summary_empty_when_disconnected(client, monkeypatch):
    """R1/R2 empty state: no Schwab → the strip renders null, not a false $0."""
    _patch_status(monkeypatch, schwab_configured=False)
    _seed_position(client)

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    summary = resp.json()["account_summary"]
    assert summary["account_value"] is None
    assert summary["cash"] is None
    assert summary["reconciles"] is False
    assert summary["reconcile_state"] == "unavailable"


@pytest.mark.integration
def test_dashboard_kpis_roll_options_end_to_end(client, monkeypatch):
    """R4 wiring: an open short put with a live mark rolls into the KPI totals."""
    _patch_status(monkeypatch, schwab_configured=True)
    # Future expiry (parameterized off today, per CLAUDE.md now()-relative rule)
    # so the leg is live and its economics resolve.
    expiration = (date.today() + timedelta(days=30)).isoformat()
    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote",
        lambda self, ticker: {"lastPrice": 174.0},
    )
    # A live mark of 0.90 on the 2.25-credit short put → the leg has economics.
    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_option_chain",
        lambda self, ticker, *a, **k: {
            "putExpDateMap": {
                f"{expiration}:30": {"175.0": [{"strikePrice": 175.0, "mark": 0.90}]}
            }
        },
    )
    monkeypatch.setattr(
        "app.services.dashboard.get_account_value",
        lambda db: _account_result(cash=0.0, total_capital=17400.0),
    )
    pid = _seed_position(client)
    _seed_trade(client, pid, expiration=expiration)

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    kpis = resp.json()["kpis"]
    assert kpis["includes_options"] is True
    # Portfolio value now nets the short-option liability (-cost_to_close).
    equity_notional = 174.0 * 100
    assert kpis["notional_value"] < equity_notional


@pytest.mark.integration
def test_realized_pl_sourced_from_journal_only(client, monkeypatch):
    """#419 guard: realized P/L is journal/closed-sourced, not contaminated by
    an open position's unrealized value."""
    _patch_status(monkeypatch, schwab_configured=True)
    # A live quote well above cost basis → a large POSITIVE unrealized value.
    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote",
        lambda self, ticker: {"lastPrice": 300.0},
    )
    monkeypatch.setattr(
        "app.services.dashboard.get_account_value",
        lambda db: _account_result(cash=0.0, total_capital=30000.0),
    )
    _seed_position(client)  # open, no closed positions, no realized events

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    kpis = resp.json()["kpis"]
    # Unrealized is large and positive …
    assert kpis["unrealized_pl"] is not None and kpis["unrealized_pl"] > 10000.0
    # … but realized P/L stays 0: no closed premium, no equity realized P&L.
    assert kpis["realized_pl"] == pytest.approx(0.0)
    assert kpis["realized_pl_pct"] is None


# -- #429: tri-state reconcile against a freshness-bounded broker value -------
#
# The 2026-07-19 bug: a live-computed account value reconciled against a
# 15-min-cached (stale) broker ``liquidationValue`` false-positived
# ``reconciles=false`` on ~$11 of cache drift. Fixed by gating the reconcile on
# broker-value freshness (``RECONCILE_FRESH_WINDOW``) and a tri-state verdict:
# fresh+near → ``reconciled``; fresh+far → ``mismatch``; stale/unresolved →
# ``unavailable`` (never a false ``mismatch``).

# Prod evidence numbers (issue #429):
_EVID_EQUITY = 8519.89
_EVID_OPTION_CTC = 42.00  # short leg → option_mv = -42.00
_EVID_CASH = 1398.59
_EVID_COMPUTED = _EVID_EQUITY - _EVID_OPTION_CTC + _EVID_CASH  # 9876.48
_EVID_BROKER_LIVE = 9874.59  # Schwab live/close → gap $1.89 (within tolerance)
_EVID_BROKER_STALE = 9865.59  # 15-min-cached → gap ~$10.89 (the false negative)


class TestReconcileStatePredicate:
    @pytest.mark.unit
    def test_state_reconciled_when_fresh_and_within_tolerance(self):
        from app.services.dashboard import _reconcile_state

        assert _reconcile_state(10002.0, 10000.0, broker_value_fresh=True) == "reconciled"

    @pytest.mark.unit
    def test_state_mismatch_when_fresh_and_outside_tolerance(self):
        from app.services.dashboard import _reconcile_state

        assert _reconcile_state(10500.0, 10000.0, broker_value_fresh=True) == "mismatch"

    @pytest.mark.unit
    def test_state_unavailable_when_stale_even_if_within_tolerance(self):
        # A stale broker value never reconciles OR mismatches — it's unknown.
        from app.services.dashboard import _reconcile_state

        assert _reconcile_state(10000.0, 10000.0, broker_value_fresh=False) == "unavailable"

    @pytest.mark.unit
    def test_state_unavailable_when_stale_even_if_far_apart(self):
        from app.services.dashboard import _reconcile_state

        assert _reconcile_state(10500.0, 10000.0, broker_value_fresh=False) == "unavailable"


class TestBrokerValueFreshness:
    @pytest.mark.unit
    def test_fresh_within_window(self):
        from app.services.dashboard import _broker_value_is_fresh

        now = datetime.now(timezone.utc)
        result = _account_result(cached_at=now - timedelta(seconds=30))
        assert _broker_value_is_fresh(result, now) is True

    @pytest.mark.unit
    def test_stale_beyond_window(self):
        from app.services.dashboard import _broker_value_is_fresh

        now = datetime.now(timezone.utc)
        result = _account_result(cached_at=now - timedelta(minutes=20))
        assert _broker_value_is_fresh(result, now) is False

    @pytest.mark.unit
    def test_missing_cached_at_is_not_fresh(self):
        from app.services.dashboard import _broker_value_is_fresh

        result = _account_result(cached_at=None)
        assert _broker_value_is_fresh(result) is False


class TestBuildAccountSummaryReconcileState:
    @pytest.mark.unit
    def test_reconciled_on_fresh_within_tolerance_regression(self):
        # AC1 — the 2026-07-19 numbers reconcile against a FRESH broker value:
        # computed $9,876.48 vs live $9,874.59 = $1.89 gap, within tolerance.
        rows = [_row(notional=_EVID_EQUITY)]
        legs = [_leg(cost_to_close=_EVID_OPTION_CTC)]
        with patch(
            "app.services.dashboard.get_account_value",
            return_value=_account_result(
                cash=_EVID_CASH, total_capital=_EVID_BROKER_LIVE
            ),
        ):
            summary = _build_account_summary(
                db=None, position_rows=rows, open_legs=legs, schwab_configured=True
            )
        assert summary["account_value"] == pytest.approx(_EVID_COMPUTED)
        assert summary["reconcile_state"] == "reconciled"
        assert summary["reconciles"] is True

    @pytest.mark.unit
    def test_unavailable_on_stale_broker_not_mismatch_regression(self):
        # AC2 — the exact false-negative: computed $9,876.48 vs STALE cached
        # $9,865.59 is ~$11 apart (beyond tolerance), but because the broker
        # value is stale the verdict is "unavailable", NOT "mismatch"/False.
        rows = [_row(notional=_EVID_EQUITY)]
        legs = [_leg(cost_to_close=_EVID_OPTION_CTC)]
        stale = datetime.now(timezone.utc) - timedelta(minutes=20)
        with patch(
            "app.services.dashboard.get_account_value",
            return_value=_account_result(
                cash=_EVID_CASH, total_capital=_EVID_BROKER_STALE, cached_at=stale
            ),
        ):
            summary = _build_account_summary(
                db=None, position_rows=rows, open_legs=legs, schwab_configured=True
            )
        assert summary["reconcile_state"] == "unavailable"
        assert summary["reconcile_state"] != "mismatch"
        assert summary["reconciles"] is False
        # Headline account value is still the computed sum (ties to positions).
        assert summary["account_value"] == pytest.approx(_EVID_COMPUTED)

    @pytest.mark.unit
    def test_mismatch_on_fresh_beyond_tolerance(self):
        # AC3 — a genuine discrepancy on FRESH data reads "mismatch" (alarming).
        rows = [_row(notional=_EVID_EQUITY)]
        legs = []
        with patch(
            "app.services.dashboard.get_account_value",
            return_value=_account_result(
                cash=_EVID_CASH, total_capital=_EVID_EQUITY + _EVID_CASH + 500.0
            ),
        ):
            summary = _build_account_summary(
                db=None, position_rows=rows, open_legs=legs, schwab_configured=True
            )
        assert summary["reconcile_state"] == "mismatch"
        assert summary["reconciles"] is False


class TestReconcileNoRoundTripWhenFresh:
    @pytest.mark.unit
    def test_no_schwab_roundtrip_when_fresh_cached(self, monkeypatch):
        # AC4 — a fresh cached broker value is used as-is; the Schwab client is
        # never invoked (no needless round-trip).
        from app.services import schwab_account_value as sav
        from app.services.dashboard import _resolve_account_balances

        sav.clear_cache()
        now = datetime.now(timezone.utc)
        sav._cache["__default__"] = AccountValueResult(
            status="ok",
            total_capital=_EVID_BROKER_LIVE,
            cash=_EVID_CASH,
            cached_at=now,
        )
        calls = {"n": 0}

        class _SpyClient:
            def get_accounts(self):
                calls["n"] += 1
                return []

        monkeypatch.setattr(sav, "SchwabClient", _SpyClient)
        try:
            balances = _resolve_account_balances(db=None, schwab_configured=True)
        finally:
            sav.clear_cache()

        assert balances is not None
        assert balances["broker_value_fresh"] is True
        assert calls["n"] == 0


@pytest.mark.integration
def test_dashboard_reconcile_unavailable_when_broker_stale(client, monkeypatch):
    """#429 wiring: a stale broker net-liq surfaces reconcile_state=unavailable
    end-to-end — the headline account value still renders, but the parity check
    is honestly 'can't confirm', not a red mismatch."""
    _patch_status(monkeypatch, schwab_configured=True)
    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote",
        lambda self, ticker: {"lastPrice": 175.0},
    )
    stale = datetime.now(timezone.utc) - timedelta(minutes=20)
    # Accept the force_refresh kwarg (the stale path retries with it) but keep
    # returning a stale value so the reconcile stays unavailable.
    monkeypatch.setattr(
        "app.services.dashboard.get_account_value",
        lambda db, **kw: _account_result(
            cash=1365.26, total_capital=17500.0 + 1365.26 - 250.0, cached_at=stale
        ),
    )
    _seed_position(client)

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    summary = resp.json()["account_summary"]
    assert summary["reconcile_state"] == "unavailable"
    assert summary["reconciles"] is False
    assert summary["account_value"] is not None


@pytest.mark.integration
def test_dashboard_reconcile_reconciled_when_broker_fresh(client, monkeypatch):
    """#429 wiring: a fresh broker net-liq within tolerance surfaces
    reconcile_state=reconciled end-to-end."""
    _patch_status(monkeypatch, schwab_configured=True)
    monkeypatch.setattr(
        "app.services.dashboard.SchwabClient.get_quote",
        lambda self, ticker: {"lastPrice": 175.0},
    )
    monkeypatch.setattr(
        "app.services.dashboard.get_account_value",
        lambda db, **kw: _account_result(
            cash=1365.26, total_capital=17500.0 + 1365.26
        ),
    )
    _seed_position(client)

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    summary = resp.json()["account_summary"]
    assert summary["reconcile_state"] == "reconciled"
    assert summary["reconciles"] is True
