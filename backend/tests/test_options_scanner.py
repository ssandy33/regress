import math
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

import pandas as pd
import pytest

from app.models.schemas import OptionScanRequest
from app.services.options_scanner import OptionScanner, OptionScannerError, _normalize_val, calculate_greeks


def _make_chain_df(strikes, bids, asks, deltas, ois, volumes, ivs):
    """Helper to build an option chain DataFrame matching yfinance format."""
    return pd.DataFrame({
        "strike": strikes,
        "bid": bids,
        "ask": asks,
        "delta": deltas,
        "gamma": [0.03] * len(strikes),
        "theta": [-0.02] * len(strikes),
        "vega": [0.04] * len(strikes),
        "openInterest": ois,
        "volume": volumes,
        "impliedVolatility": ivs,
    })


@pytest.fixture()
def scanner():
    return OptionScanner()


@pytest.fixture()
def cc_request():
    return OptionScanRequest(
        ticker="TEST",
        strategy="covered_call",
        cost_basis=15.00,
        shares_held=300,
        min_dte=25,
        max_dte=50,
        min_return_pct=0.5,
        min_call_distance_pct=10.0,
        max_delta=0.35,
        min_delta=0.15,
    )


@pytest.fixture()
def csp_request():
    return OptionScanRequest(
        ticker="TEST",
        strategy="cash_secured_put",
        capital_available=5000.0,
        min_dte=25,
        max_dte=50,
        min_return_pct=0.5,
        max_delta=0.35,
        min_delta=0.15,
    )


class TestValidation:
    def test_invalid_strategy(self, scanner):
        req = OptionScanRequest(ticker="X", strategy="butterfly", cost_basis=10.0)
        with pytest.raises(ValueError, match="Invalid strategy"):
            scanner._validate_request(req)

    def test_cc_requires_cost_basis(self, scanner):
        req = OptionScanRequest(ticker="X", strategy="covered_call")
        with pytest.raises(ValueError, match="cost_basis"):
            scanner._validate_request(req)

    def test_csp_requires_capital(self, scanner):
        req = OptionScanRequest(ticker="X", strategy="cash_secured_put")
        with pytest.raises(ValueError, match="capital_available"):
            scanner._validate_request(req)


class TestRejectionFilters:
    def test_10pct_rule_rejects_close_strike(self, scanner, cc_request):
        # Strike $16 is only 6.7% above $15 cost basis, needs 10%
        reasons = scanner._check_rejection(
            cc_request, strike=16.0, current_price=14.0,
            delta=-0.20, oi=100, bid=0.30, mid=0.35, dte=30,
        )
        assert any("fails_10pct_rule" in r for r in reasons)

    def test_10pct_rule_passes_far_strike(self, scanner, cc_request):
        # Strike $17 is 13.3% above $15 cost basis
        reasons = scanner._check_rejection(
            cc_request, strike=17.0, current_price=14.0,
            delta=-0.20, oi=100, bid=0.30, mid=0.35, dte=30,
        )
        assert not any("fails_10pct_rule" in r for r in reasons)

    def test_delta_out_of_range_rejected(self, scanner, cc_request):
        reasons = scanner._check_rejection(
            cc_request, strike=17.0, current_price=14.0,
            delta=-0.05, oi=100, bid=0.30, mid=0.35, dte=30,
        )
        assert any("delta_out_of_range" in r for r in reasons)

    def test_delta_in_range_passes(self, scanner, cc_request):
        reasons = scanner._check_rejection(
            cc_request, strike=17.0, current_price=14.0,
            delta=-0.25, oi=100, bid=0.30, mid=0.35, dte=30,
        )
        assert not any("delta_out_of_range" in r for r in reasons)

    def test_missing_delta_not_rejected(self, scanner, cc_request):
        reasons = scanner._check_rejection(
            cc_request, strike=17.0, current_price=14.0,
            delta=None, oi=100, bid=0.30, mid=0.35, dte=30,
        )
        assert not any("delta" in r for r in reasons)

    def test_low_oi_rejected(self, scanner, cc_request):
        reasons = scanner._check_rejection(
            cc_request, strike=17.0, current_price=14.0,
            delta=-0.20, oi=10, bid=0.30, mid=0.35, dte=30,
        )
        assert any("low_open_interest" in r for r in reasons)

    def test_zero_bid_rejected(self, scanner, cc_request):
        reasons = scanner._check_rejection(
            cc_request, strike=17.0, current_price=14.0,
            delta=-0.20, oi=100, bid=0.0, mid=0.10, dte=30,
        )
        assert any("zero_bid" in r for r in reasons)

    def test_itm_put_rejected(self, scanner, csp_request):
        # Put strike $15 > current price $14
        reasons = scanner._check_rejection(
            csp_request, strike=15.0, current_price=14.0,
            delta=-0.50, oi=100, bid=1.50, mid=1.60, dte=30,
        )
        assert any("itm_put" in r for r in reasons)

    def test_otm_put_passes(self, scanner, csp_request):
        # Put strike $13 < current price $14
        reasons = scanner._check_rejection(
            csp_request, strike=13.0, current_price=14.0,
            delta=-0.25, oi=100, bid=0.30, mid=0.35, dte=30,
        )
        assert not any("itm_put" in r for r in reasons)


class TestMetricCalculations:
    def test_covered_call_metrics(self, scanner, cc_request):
        metrics = scanner._calculate_metrics(
            cc_request, strike=17.0, current_price=14.0, mid=0.45, dte=34,
        )
        # total_premium = 0.45 * 100 * (300/100) = 135.0
        assert metrics["total_premium"] == 135.0
        # return = 135 / (15*300) * 100 = 3.0%
        assert metrics["return_on_capital_pct"] == 3.0
        # annualized = 3.0 * (365/34)
        assert metrics["annualized_return_pct"] == round(3.0 * 365 / 34, 2)
        # distance_from_basis = (17-15)/15 * 100 = 13.33%
        assert abs(metrics["distance_from_basis_pct"] - 13.33) < 0.1
        # max_profit = 135 + (17-15)*300 = 135 + 600 = 735
        assert metrics["max_profit"] == 735.0
        # 50% target = 135 * 0.5 = 67.5
        assert metrics["fifty_pct_profit_target"] == 67.5

    def test_cash_secured_put_metrics(self, scanner, csp_request):
        metrics = scanner._calculate_metrics(
            csp_request, strike=13.0, current_price=14.0, mid=0.40, dte=30,
        )
        # premium_per_contract = 0.40 * 100 = 40.0
        assert metrics["premium_per_contract"] == 40.0
        # capital_at_risk = 13 * 100 = 1300
        # num_contracts = int(5000 / 1300) = 3
        # total_premium = 40 * 3 = 120
        assert metrics["total_premium"] == 120.0
        # return = 40 / 1300 * 100 = 3.0769%
        assert abs(metrics["return_on_capital_pct"] - 3.0769) < 0.01
        # breakeven = 13 - 0.40 = 12.60
        assert metrics["breakeven"] == 12.60
        # distance = (14-13)/14 * 100 = 7.14%
        assert abs(metrics["distance_from_price_pct"] - 7.14) < 0.1


class TestRanking:
    def test_ranking_order(self, scanner):
        """Higher return and distance should rank better."""
        from app.models.schemas import RuleCompliance, StrikeRecommendation

        compliance = RuleCompliance(
            passes_10pct_rule=True, passes_dte_range=True,
            passes_delta_range=True, passes_earnings_check=True,
            passes_return_target=True,
        )

        # Candidate A: high return, high distance
        a = StrikeRecommendation(
            rank=0, strike=17.0, expiration="2026-04-01", dte=30,
            bid=0.40, ask=0.50, mid=0.45, delta=-0.20,
            open_interest=1000, volume=300,
            premium_per_contract=45, total_premium=135,
            return_on_capital_pct=3.0, annualized_return_pct=36.5,
            distance_from_price_pct=15.0, max_profit=735,
            fifty_pct_profit_target=67.5, rule_compliance=compliance,
        )

        # Candidate B: lower return, lower distance
        b = StrikeRecommendation(
            rank=0, strike=16.0, expiration="2026-04-01", dte=30,
            bid=0.60, ask=0.70, mid=0.65, delta=-0.30,
            open_interest=500, volume=100,
            premium_per_contract=65, total_premium=195,
            return_on_capital_pct=1.0, annualized_return_pct=12.2,
            distance_from_price_pct=5.0, max_profit=495,
            fifty_pct_profit_target=97.5, rule_compliance=compliance,
        )

        ranked = scanner._rank_strikes([a, b])
        assert ranked[0].strike == 17.0
        assert ranked[0].rank == 1
        assert ranked[1].rank == 2

    def test_single_candidate(self, scanner):
        from app.models.schemas import RuleCompliance, StrikeRecommendation

        compliance = RuleCompliance(
            passes_10pct_rule=True, passes_dte_range=True,
            passes_delta_range=True, passes_earnings_check=True,
            passes_return_target=True,
        )
        c = StrikeRecommendation(
            rank=0, strike=17.0, expiration="2026-04-01", dte=30,
            bid=0.40, ask=0.50, mid=0.45, delta=-0.20,
            open_interest=1000, volume=300,
            premium_per_contract=45, total_premium=135,
            return_on_capital_pct=3.0, annualized_return_pct=36.5,
            distance_from_price_pct=15.0, max_profit=735,
            fifty_pct_profit_target=67.5, rule_compliance=compliance,
        )
        ranked = scanner._rank_strikes([c])
        assert len(ranked) == 1
        assert ranked[0].rank == 1

    def test_empty_candidates(self, scanner):
        ranked = scanner._rank_strikes([])
        assert ranked == []


class TestNormalization:
    def test_normalize_normal(self):
        assert _normalize_val(5, [0, 5, 10]) == 0.5

    def test_normalize_min(self):
        assert _normalize_val(0, [0, 5, 10]) == 0.0

    def test_normalize_max(self):
        assert _normalize_val(10, [0, 5, 10]) == 1.0

    def test_normalize_equal_values(self):
        assert _normalize_val(5, [5, 5, 5]) == 0.5


class TestExpirationFiltering:
    def test_dte_range_filter(self, scanner):
        today = datetime.now().date()
        mock_ticker = MagicMock()
        mock_ticker.options = [
            (today + timedelta(days=10)).strftime("%Y-%m-%d"),  # too soon
            (today + timedelta(days=30)).strftime("%Y-%m-%d"),  # in range
            (today + timedelta(days=45)).strftime("%Y-%m-%d"),  # in range
            (today + timedelta(days=60)).strftime("%Y-%m-%d"),  # too far
        ]

        valid = scanner._get_valid_expirations(mock_ticker, 25, 50, None, 5)
        assert len(valid) == 2

    def test_earnings_buffer_filter(self, scanner):
        today = datetime.now().date()
        earnings = (today + timedelta(days=35)).strftime("%Y-%m-%d")
        mock_ticker = MagicMock()
        mock_ticker.options = [
            (today + timedelta(days=30)).strftime("%Y-%m-%d"),  # within 5 days of earnings
            (today + timedelta(days=33)).strftime("%Y-%m-%d"),  # within 5 days of earnings
            (today + timedelta(days=45)).strftime("%Y-%m-%d"),  # outside buffer
        ]

        valid = scanner._get_valid_expirations(mock_ticker, 25, 50, earnings, 5)
        assert len(valid) == 1
        assert valid[0] == (today + timedelta(days=45)).strftime("%Y-%m-%d")

    def test_no_options_raises(self, scanner):
        mock_ticker = MagicMock()
        mock_ticker.options = []
        mock_ticker.ticker = "NOOPT"

        with pytest.raises(OptionScannerError, match="No options"):
            scanner._get_valid_expirations(mock_ticker, 25, 50, None, 5)


class TestCalculateGreeks:
    """Black-Scholes Greeks calculation tests."""

    def test_otm_call_delta(self):
        # $24 call on $21.70 stock, 33 DTE, 62% IV
        greeks = calculate_greeks(S=21.70, K=24.0, T=33/365, sigma=0.62, option_type="call")
        assert 0.10 < greeks["delta"] < 0.45
        assert greeks["gamma"] > 0
        assert greeks["theta"] < 0
        assert greeks["vega"] > 0

    def test_atm_call_delta_near_half(self):
        greeks = calculate_greeks(S=100.0, K=100.0, T=30/365, sigma=0.30, option_type="call")
        assert 0.45 < greeks["delta"] < 0.60

    def test_put_delta_negative(self):
        greeks = calculate_greeks(S=100.0, K=95.0, T=30/365, sigma=0.30, option_type="put")
        assert greeks["delta"] < 0

    def test_zero_time_returns_none(self):
        greeks = calculate_greeks(S=100.0, K=100.0, T=0, sigma=0.30, option_type="call")
        assert greeks["delta"] is None

    def test_zero_iv_returns_none(self):
        greeks = calculate_greeks(S=100.0, K=100.0, T=30/365, sigma=0.0, option_type="call")
        assert greeks["delta"] is None
