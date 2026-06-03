import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from app.services.options_scanner import OptionScanner, OptionScannerError
from app.models.schemas import MarketContext, RuleCompliance, StrikeRecommendation


def _mock_scan_result():
    """Build a mock scan result dict."""
    compliance = RuleCompliance(
        passes_10pct_rule=True, passes_dte_range=True,
        passes_delta_range=True, passes_earnings_check=True,
        passes_return_target=True,
    )
    rec = StrikeRecommendation(
        rank=1, strike=17.0, expiration="2026-04-18", dte=34,
        bid=0.42, ask=0.48, mid=0.45, delta=-0.22,
        gamma=0.03, theta=-0.02, vega=0.04, iv=0.58,
        open_interest=1250, volume=340,
        premium_per_contract=45.0, total_premium=135.0,
        return_on_capital_pct=1.64, annualized_return_pct=17.6,
        distance_from_price_pct=14.7, distance_from_basis_pct=12.7,
        max_profit=735.0, fifty_pct_profit_target=67.5,
        rule_compliance=compliance,
    )
    return {
        "ticker": "SOFI",
        "current_price": 14.82,
        "strategy": "covered_call",
        "scan_time": datetime.now(timezone.utc).isoformat(),
        "earnings_date": "2026-05-05",
        "iv_rank": None,
        "recommendations": [rec],
        "rejected": [],
        "market_context": MarketContext(vix=18.5, beta=2.14),
    }


def _approve(client, *tickers):
    """Seed the watchlist via the public API so the #322 gate lets a scan pass.

    Bridge helper added with the watchlist gate (issue #322): the scan endpoint
    now short-circuits any ticker that is not on the watchlist to a ``200``
    empty result, so the downstream-behavior tests below must approve the
    ticker they scan before they reach ``OptionScanner.scan``.
    """
    for ticker in tickers:
        client.post("/api/watchlist", json={"ticker": ticker})


class TestScanEndpoint:
    @pytest.mark.integration
    def test_scan_covered_call_success(self, client):
        _approve(client, "SOFI")
        with patch.object(OptionScanner, "scan", return_value=_mock_scan_result()):
            response = client.post("/api/options/scan", json={
                "ticker": "SOFI",
                "strategy": "covered_call",
                "cost_basis": 15.50,
                "shares_held": 300,
            })
        assert response.status_code == 200
        data = response.json()
        assert data["ticker"] == "SOFI"
        assert data["strategy"] == "covered_call"
        assert len(data["recommendations"]) == 1
        assert data["recommendations"][0]["rank"] == 1

    @pytest.mark.integration
    def test_scan_csp_success(self, client):
        _approve(client, "SOFI")
        result = _mock_scan_result()
        result["strategy"] = "cash_secured_put"
        with patch.object(OptionScanner, "scan", return_value=result):
            response = client.post("/api/options/scan", json={
                "ticker": "SOFI",
                "strategy": "cash_secured_put",
                "capital_available": 5000,
            })
        assert response.status_code == 200
        assert response.json()["strategy"] == "cash_secured_put"

    @pytest.mark.integration
    def test_scan_no_options_404(self, client):
        _approve(client, "BRK.A")
        with patch.object(
            OptionScanner, "scan",
            side_effect=OptionScannerError("No options available for 'BRK.A'"),
        ):
            response = client.post("/api/options/scan", json={
                "ticker": "BRK.A",
                "strategy": "covered_call",
                "cost_basis": 500000,
            })
        assert response.status_code == 404
        assert "No options" in response.json()["detail"]

    @pytest.mark.integration
    def test_scan_invalid_strategy_400(self, client):
        _approve(client, "SOFI")
        with patch.object(
            OptionScanner, "scan",
            side_effect=ValueError("Invalid strategy: butterfly"),
        ):
            response = client.post("/api/options/scan", json={
                "ticker": "SOFI",
                "strategy": "butterfly",
            })
        assert response.status_code == 400


    @pytest.mark.integration
    def test_scan_schwab_auth_error_returns_sanitized_message(self, client):
        """Schwab auth errors must not leak internal details (issue #41)."""
        _approve(client, "F")
        with patch.object(
            OptionScanner, "scan",
            side_effect=OptionScannerError(
                "Options scanning is unavailable. Please contact your administrator "
                "to configure the Schwab API connection."
            ),
        ):
            response = client.post("/api/options/scan", json={
                "ticker": "F",
                "strategy": "covered_call",
                "cost_basis": 12.0,
            })
        assert response.status_code == 404
        detail = response.json()["detail"]
        assert "contact your administrator" in detail
        assert "refresh token" not in detail
        assert "python -m app.cli" not in detail

    @pytest.mark.integration
    def test_schwab_auth_error_global_handler_sanitized(self, client):
        """Global SchwabAuthError handler must not leak internal details (issue #41)."""
        from app.services.schwab_auth import SchwabAuthCode, SchwabAuthError

        _approve(client, "F")
        with patch.object(
            OptionScanner, "scan",
            side_effect=SchwabAuthError(
                "No Schwab refresh token found. Run 'python -m app.cli schwab-auth' to authorize.",
                code=SchwabAuthCode.TOKEN_MISSING,
            ),
        ):
            response = client.post("/api/options/scan", json={
                "ticker": "F",
                "strategy": "covered_call",
                "cost_basis": 12.0,
            })
        assert response.status_code == 401
        detail = response.json()["detail"]
        assert "refresh token" not in detail
        assert "python -m app.cli" not in detail
        assert "administrator" in detail


class TestEarningsEndpoint:
    @pytest.mark.integration
    def test_get_earnings(self, client):
        with patch("app.services.alpha_vantage_client.get_next_earnings_date", return_value="2026-05-05"):
            response = client.get("/api/options/earnings/SOFI")
        assert response.status_code == 200
        data = response.json()
        assert data["ticker"] == "SOFI"


class TestWatchlistGate:
    """Watchlist gate on the scan endpoint (issue #322 / PRD #213 R5).

    The watchlist is seeded through the real ``/api/watchlist`` API so these
    tests exercise the single source of truth (#321's ``WatchlistTicker`` +
    ``list_watchlist``) end-to-end — there is no second copy of the universe.
    """

    @pytest.mark.integration
    def test_scan_with_watchlisted_ticker_returns_candidates(self, client):
        """I1 (AC1) — a watchlisted ticker passes the gate and is scanned."""
        client.post("/api/watchlist", json={"ticker": "AAPL"})

        result = _mock_scan_result()
        result["ticker"] = "AAPL"
        with patch.object(OptionScanner, "scan", return_value=result) as scan_mock:
            response = client.post(
                "/api/options/scan",
                json={
                    "ticker": "AAPL",
                    "strategy": "covered_call",
                    "cost_basis": 200.0,
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data["ticker"] == "AAPL"
        assert len(data["recommendations"]) == 1
        assert data["empty_reason"] is None
        # The gate allowed the scan, so the (mocked) chain scan ran.
        scan_mock.assert_called_once()

    @pytest.mark.integration
    def test_scan_offlist_ticker_returns_empty_200_not_error(self, client):
        """I2 (AC1/AC2) — an off-watchlist ticker → 200 empty, scan never runs."""
        client.post("/api/watchlist", json={"ticker": "AAPL"})

        with patch.object(OptionScanner, "scan") as scan_mock:
            response = client.post(
                "/api/options/scan",
                json={
                    "ticker": "MSFT",
                    "strategy": "covered_call",
                    "cost_basis": 400.0,
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data["recommendations"] == []
        assert data["rejected"] == []
        assert data["empty_reason"] is not None
        assert "MSFT" in data["empty_reason"]
        assert "not on your watchlist" in data["empty_reason"]
        # The gate short-circuited before any chain fetch.
        scan_mock.assert_not_called()

    @pytest.mark.integration
    def test_scan_empty_watchlist_returns_explanatory_empty_200(self, client):
        """I3 (AC2) — empty watchlist → explanatory empty 200, not a 4xx/5xx."""
        with patch.object(OptionScanner, "scan") as scan_mock:
            response = client.post(
                "/api/options/scan",
                json={
                    "ticker": "AAPL",
                    "strategy": "covered_call",
                    "cost_basis": 200.0,
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data["recommendations"] == []
        assert data["empty_reason"] is not None
        assert "watchlist" in data["empty_reason"].lower()
        scan_mock.assert_not_called()

    @pytest.mark.integration
    def test_adding_ticker_changes_next_scan_universe_no_code_change(self, client):
        """I4 (AC3) — adding a ticker via the API changes the next scan's universe."""
        # Before: AAPL is not approved, so the scan is gated to empty.
        with patch.object(OptionScanner, "scan") as scan_mock:
            gated = client.post(
                "/api/options/scan",
                json={
                    "ticker": "AAPL",
                    "strategy": "covered_call",
                    "cost_basis": 200.0,
                },
            )
        assert gated.status_code == 200
        assert gated.json()["recommendations"] == []
        scan_mock.assert_not_called()

        # Approve AAPL via the watchlist API only — no code change.
        add = client.post("/api/watchlist", json={"ticker": "AAPL"})
        assert add.status_code == 200

        # After: the same scan now passes the gate and is scanned.
        result = _mock_scan_result()
        result["ticker"] = "AAPL"
        with patch.object(OptionScanner, "scan", return_value=result) as scan_mock:
            allowed = client.post(
                "/api/options/scan",
                json={
                    "ticker": "AAPL",
                    "strategy": "covered_call",
                    "cost_basis": 200.0,
                },
            )
        assert allowed.status_code == 200
        assert len(allowed.json()["recommendations"]) == 1
        scan_mock.assert_called_once()
