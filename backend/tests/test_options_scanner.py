from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest

from app.models.schemas import OptionScanRequest, RuleCompliance, StrikeRecommendation
from app.services.options_scanner import OptionScanner, OptionScannerError, _normalize_val


def _make_schwab_contract(
    strike=17.0, bid=0.40, ask=0.50, mark=0.45,
    delta=-0.20, gamma=0.03, theta=-0.02, vega=0.04,
    oi=500, volume=100, volatility=35.0, dte=30,
):
    """Helper to build a Schwab-format option contract dict."""
    return {
        "strikePrice": strike,
        "bid": bid,
        "ask": ask,
        "mark": mark,
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega,
        "openInterest": oi,
        "totalVolume": volume,
        "volatility": volatility,
        "daysToExpiration": dte,
    }


def _make_schwab_chain_response(
    symbol="TEST",
    underlying_price=14.0,
    contracts=None,
    contract_type="call",
    exp_date=None,
    dte=30,
):
    """Build a Schwab chains API response fixture."""
    if exp_date is None:
        exp_date = (datetime.now().date() + timedelta(days=dte)).strftime("%Y-%m-%d")
    exp_key = f"{exp_date}:{dte}"

    if contracts is None:
        contracts = [_make_schwab_contract(dte=dte)]

    strikes_map = {}
    for c in contracts:
        strike_str = str(c["strikePrice"])
        strikes_map[strike_str] = [c]

    map_key = "callExpDateMap" if contract_type == "call" else "putExpDateMap"

    return {
        "symbol": symbol,
        "status": "SUCCESS",
        "underlying": {
            "last": underlying_price,
            "close": underlying_price,
            "fiftyTwoWeekHigh": underlying_price * 1.3,
            "fiftyTwoWeekLow": underlying_price * 0.7,
            "totalVolume": 5000000,
        },
        map_key: {
            exp_key: strikes_map,
        },
        # Include empty opposite map
        "putExpDateMap" if contract_type == "call" else "callExpDateMap": {},
    }


@pytest.fixture()
def scanner():
    return OptionScanner()


# Rule fields are explicit on these fixtures so the scanner can be exercised
# in isolation (these tests bypass the router that would otherwise backfill
# the universe rules from rules_config — see issue #156). The cost-basis
# floor is disabled so the existing fails_10pct_rule assertions are not
# perturbed by the new below_cost_basis rule.
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
        min_open_interest=50,
        max_bid_ask_spread_pct=10.0,
        min_iv_rank=30.0,
        cost_basis_floor_enabled=False,
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
        min_open_interest=50,
        max_bid_ask_spread_pct=10.0,
        min_iv_rank=30.0,
    )


class TestValidation:
    @pytest.mark.unit
    def test_invalid_strategy(self, scanner):
        req = OptionScanRequest(ticker="X", strategy="butterfly", cost_basis=10.0)
        with pytest.raises(ValueError, match="Invalid strategy"):
            scanner._validate_request(req)

    @pytest.mark.unit
    def test_cc_requires_cost_basis(self, scanner):
        req = OptionScanRequest(ticker="X", strategy="covered_call")
        with pytest.raises(ValueError, match="cost_basis"):
            scanner._validate_request(req)

    @pytest.mark.unit
    def test_csp_requires_capital(self, scanner):
        req = OptionScanRequest(ticker="X", strategy="cash_secured_put")
        with pytest.raises(ValueError, match="capital_available"):
            scanner._validate_request(req)


class TestRejectionFilters:
    @pytest.mark.unit
    def test_10pct_rule_rejects_close_strike(self, scanner, cc_request):
        # Strike $16 is only 6.7% above $15 cost basis, needs 10%
        reasons = scanner._check_rejection(
            cc_request, strike=16.0, current_price=14.0,
            delta=-0.20, oi=100, bid=0.30, ask=0.32, mid=0.35, dte=30,
        )
        assert any("fails_10pct_rule" in r for r in reasons)

    @pytest.mark.unit
    def test_10pct_rule_passes_far_strike(self, scanner, cc_request):
        # Strike $17 is 13.3% above $15 cost basis
        reasons = scanner._check_rejection(
            cc_request, strike=17.0, current_price=14.0,
            delta=-0.20, oi=100, bid=0.30, ask=0.32, mid=0.35, dte=30,
        )
        assert not any("fails_10pct_rule" in r for r in reasons)

    @pytest.mark.unit
    def test_delta_out_of_range_rejected(self, scanner, cc_request):
        reasons = scanner._check_rejection(
            cc_request, strike=17.0, current_price=14.0,
            delta=-0.05, oi=100, bid=0.30, ask=0.32, mid=0.35, dte=30,
        )
        assert any("delta_out_of_range" in r for r in reasons)

    @pytest.mark.unit
    def test_delta_in_range_passes(self, scanner, cc_request):
        reasons = scanner._check_rejection(
            cc_request, strike=17.0, current_price=14.0,
            delta=-0.25, oi=100, bid=0.30, ask=0.32, mid=0.35, dte=30,
        )
        assert not any("delta_out_of_range" in r for r in reasons)

    @pytest.mark.unit
    def test_missing_delta_not_rejected(self, scanner, cc_request):
        reasons = scanner._check_rejection(
            cc_request, strike=17.0, current_price=14.0,
            delta=None, oi=100, bid=0.30, ask=0.32, mid=0.35, dte=30,
        )
        assert not any("delta" in r for r in reasons)

    @pytest.mark.unit
    def test_low_oi_rejected(self, scanner, cc_request):
        reasons = scanner._check_rejection(
            cc_request, strike=17.0, current_price=14.0,
            delta=-0.20, oi=10, bid=0.30, ask=0.32, mid=0.35, dte=30,
        )
        assert any("low_open_interest" in r for r in reasons)

    @pytest.mark.unit
    def test_zero_bid_rejected(self, scanner, cc_request):
        reasons = scanner._check_rejection(
            cc_request, strike=17.0, current_price=14.0,
            delta=-0.20, oi=100, bid=0.0, ask=0.10, mid=0.10, dte=30,
        )
        assert any("zero_bid" in r for r in reasons)

    @pytest.mark.unit
    def test_itm_put_rejected(self, scanner, csp_request):
        # Put strike $15 > current price $14
        reasons = scanner._check_rejection(
            csp_request, strike=15.0, current_price=14.0,
            delta=-0.50, oi=100, bid=1.50, ask=1.55, mid=1.60, dte=30,
        )
        assert any("itm_put" in r for r in reasons)

    @pytest.mark.unit
    def test_otm_put_passes(self, scanner, csp_request):
        # Put strike $13 < current price $14
        reasons = scanner._check_rejection(
            csp_request, strike=13.0, current_price=14.0,
            delta=-0.25, oi=100, bid=0.30, ask=0.32, mid=0.35, dte=30,
        )
        assert not any("itm_put" in r for r in reasons)


class TestMetricCalculations:
    @pytest.mark.unit
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

    @pytest.mark.unit
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
    @pytest.mark.unit
    def test_ranking_order(self, scanner):
        """Higher return and distance should rank better."""
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

    @pytest.mark.unit
    def test_single_candidate(self, scanner):
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

    @pytest.mark.unit
    def test_empty_candidates(self, scanner):
        ranked = scanner._rank_strikes([])
        assert ranked == []


class TestNormalization:
    @pytest.mark.unit
    def test_normalize_normal(self):
        assert _normalize_val(5, [0, 5, 10]) == 0.5

    @pytest.mark.unit
    def test_normalize_min(self):
        assert _normalize_val(0, [0, 5, 10]) == 0.0

    @pytest.mark.unit
    def test_normalize_max(self):
        assert _normalize_val(10, [0, 5, 10]) == 1.0

    @pytest.mark.unit
    def test_normalize_equal_values(self):
        assert _normalize_val(5, [5, 5, 5]) == 0.5


class TestScanWithSchwabChain:
    """Integration-style tests for scan() using mocked Schwab chain responses."""

    @pytest.mark.unit
    @patch("app.services.options_scanner.get_next_earnings_date", return_value=None)
    @patch("app.services.options_scanner.SchwabClient")
    def test_covered_call_scan_returns_results(self, mock_client_cls, _mock_earnings, scanner, cc_request):
        dte = 30
        exp_date = (datetime.now().date() + timedelta(days=dte)).strftime("%Y-%m-%d")

        # Spread kept inside the 10% bid/ask rule so the new
        # wide_bid_ask_spread check (issue #156) does not reject the strike.
        contract = _make_schwab_contract(
            strike=17.0, bid=0.43, ask=0.47, mark=0.45,
            delta=-0.20, gamma=0.03, theta=-0.02, vega=0.04,
            oi=500, volume=100, volatility=35.0, dte=dte,
        )
        chain_resp = _make_schwab_chain_response(
            underlying_price=14.0,
            contracts=[contract],
            contract_type="call",
            exp_date=exp_date,
            dte=dte,
        )

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_option_chain.return_value = chain_resp
        mock_client.get_quote.return_value = {"lastPrice": 18.5}

        result = scanner.scan(cc_request)

        assert result["ticker"] == "TEST"
        assert result["current_price"] == 14.0
        assert result["strategy"] == "covered_call"
        assert len(result["recommendations"]) == 1
        rec = result["recommendations"][0]
        assert rec.strike == 17.0
        assert rec.greeks_source == "market"
        assert rec.flags == []
        assert rec.delta == -0.20
        assert rec.gamma == 0.03

    @pytest.mark.unit
    @patch("app.services.options_scanner.get_next_earnings_date", return_value=None)
    @patch("app.services.options_scanner.SchwabClient")
    def test_csp_scan_returns_results(self, mock_client_cls, _mock_earnings, scanner, csp_request):
        dte = 30
        exp_date = (datetime.now().date() + timedelta(days=dte)).strftime("%Y-%m-%d")

        # Spread kept inside the 10% bid/ask rule (issue #156).
        contract = _make_schwab_contract(
            strike=13.0, bid=0.38, ask=0.42, mark=0.40,
            delta=-0.25, gamma=0.02, theta=-0.01, vega=0.03,
            oi=200, volume=50, volatility=40.0, dte=dte,
        )
        chain_resp = _make_schwab_chain_response(
            underlying_price=14.0,
            contracts=[contract],
            contract_type="put",
            exp_date=exp_date,
            dte=dte,
        )

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_option_chain.return_value = chain_resp
        mock_client.get_quote.return_value = {"lastPrice": 18.5}

        result = scanner.scan(csp_request)

        assert result["ticker"] == "TEST"
        assert result["current_price"] == 14.0
        assert len(result["recommendations"]) == 1
        rec = result["recommendations"][0]
        assert rec.strike == 13.0
        assert rec.greeks_source == "market"
        assert rec.delta == -0.25

    @pytest.mark.unit
    @patch("app.services.options_scanner.get_next_earnings_date", return_value=None)
    @patch("app.services.options_scanner.SchwabClient")
    def test_scan_no_chains_returns_empty(self, mock_client_cls, _mock_earnings, scanner, cc_request):
        chain_resp = {
            "symbol": "TEST",
            "status": "SUCCESS",
            "underlying": {"last": 14.0, "close": 14.0},
            "callExpDateMap": {},
            "putExpDateMap": {},
        }

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_option_chain.return_value = chain_resp
        mock_client.get_quote.return_value = {"lastPrice": 18.5}

        result = scanner.scan(cc_request)

        assert result["recommendations"] == []

    @pytest.mark.unit
    @patch("app.services.options_scanner.get_next_earnings_date", return_value=None)
    @patch("app.services.options_scanner.SchwabClient")
    def test_greeks_source_market_when_available(self, mock_client_cls, _mock_earnings, scanner, cc_request):
        """Verify greeks_source is 'market' when Schwab provides valid Greeks."""
        dte = 30
        exp_date = (datetime.now().date() + timedelta(days=dte)).strftime("%Y-%m-%d")

        contracts = [
            _make_schwab_contract(strike=17.0, delta=-0.20, oi=500, dte=dte),
            _make_schwab_contract(strike=18.0, delta=-0.15, oi=300, dte=dte),
        ]
        chain_resp = _make_schwab_chain_response(
            underlying_price=14.0,
            contracts=contracts,
            contract_type="call",
            exp_date=exp_date,
            dte=dte,
        )

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_option_chain.return_value = chain_resp
        mock_client.get_quote.return_value = {"lastPrice": 18.5}

        result = scanner.scan(cc_request)

        for rec in result["recommendations"]:
            assert rec.greeks_source == "market"
            assert "missing_greeks" not in rec.flags

    @pytest.mark.unit
    @patch("app.services.options_scanner.get_next_earnings_date", return_value=None)
    @patch("app.services.options_scanner.SchwabClient")
    def test_schwab_sentinel_greeks_uses_calculated_fallback(self, mock_client_cls, _mock_earnings, scanner, csp_request):
        """Schwab -999 sentinel triggers Black-Scholes fallback for Greeks."""
        dte = 30
        exp_date = (datetime.now().date() + timedelta(days=dte)).strftime("%Y-%m-%d")

        contract = _make_schwab_contract(
            strike=13.0, bid=0.35, ask=0.45, mark=0.40,
            delta=-999.0, gamma=-999.0, theta=-999.0, vega=-999.0,
            oi=200, volume=50, volatility=40.0, dte=dte,
        )
        chain_resp = _make_schwab_chain_response(
            underlying_price=14.0,
            contracts=[contract],
            contract_type="put",
            exp_date=exp_date,
            dte=dte,
        )

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_option_chain.return_value = chain_resp
        mock_client.get_quote.return_value = {"lastPrice": 14.0}

        result = scanner.scan(csp_request)

        # Should not be rejected for delta_out_of_range
        rejected_reasons = [r.rejection_reasons for r in result["rejected"]]
        for reasons in rejected_reasons:
            assert not any("delta_out_of_range" in r for r in reasons), \
                "Sentinel -999 delta should not trigger delta_out_of_range rejection"

        # If strike passed filters, it should have calculated Greeks
        for rec in result["recommendations"]:
            assert rec.greeks_source == "calculated"
            assert "calculated_greeks" in rec.flags
            assert rec.delta is not None
            assert rec.gamma is not None
            assert rec.theta is not None
            assert rec.vega is not None

    @pytest.mark.unit
    @patch("app.services.options_scanner.SchwabClient")
    def test_schwab_error_raises_scanner_error(self, mock_client_cls, scanner, cc_request):
        from app.services.schwab_client import SchwabClientError

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_option_chain.side_effect = SchwabClientError("API down")

        with pytest.raises(OptionScannerError, match="Failed to fetch option chain"):
            scanner.scan(cc_request)

    @pytest.mark.unit
    @patch("app.services.options_scanner.SchwabClient")
    def test_schwab_client_error_does_not_leak_internals(self, mock_client_cls, scanner, cc_request):
        """Transport/HTTP errors must not expose raw details to the user."""
        from app.services.schwab_client import SchwabClientError

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_option_chain.side_effect = SchwabClientError(
            "HTTP 500: Internal Server Error at https://api.schwabapi.com/marketdata/v1/chains"
        )

        with pytest.raises(OptionScannerError, match="Please try again later") as exc_info:
            scanner.scan(cc_request)

        error_msg = str(exc_info.value)
        assert "HTTP 500" not in error_msg
        assert "schwabapi.com" not in error_msg
        assert "Internal Server Error" not in error_msg

    @pytest.mark.unit
    @patch("app.services.options_scanner.SchwabClient")
    def test_schwab_auth_error_returns_sanitized_message(self, mock_client_cls, scanner, cc_request):
        """No token configured error must not leak internal details (issue #41)."""
        from app.services.schwab_auth import SchwabAuthCode, SchwabAuthError

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_option_chain.side_effect = SchwabAuthError(
            "No Schwab refresh token found. Run 'python -m app.cli schwab-auth' to authorize.",
            code=SchwabAuthCode.TOKEN_MISSING,
        )

        with pytest.raises(OptionScannerError, match="Options scanning is unavailable") as exc_info:
            scanner.scan(cc_request)

        error_msg = str(exc_info.value)
        assert "refresh token" not in error_msg
        assert "python -m app.cli" not in error_msg
        assert "contact your administrator" in error_msg


class TestExpirationFiltering:
    @pytest.mark.unit
    def test_dte_range_filter(self, scanner):
        today = datetime.now().date()
        exp_date_map = {
            f"{(today + timedelta(days=10)).strftime('%Y-%m-%d')}:10": {},
            f"{(today + timedelta(days=30)).strftime('%Y-%m-%d')}:30": {},
            f"{(today + timedelta(days=45)).strftime('%Y-%m-%d')}:45": {},
            f"{(today + timedelta(days=60)).strftime('%Y-%m-%d')}:60": {},
        }

        valid = scanner._get_valid_expirations(exp_date_map, 25, 50, None, 5)
        assert len(valid) == 2

    @pytest.mark.unit
    def test_earnings_buffer_filter(self, scanner):
        today = datetime.now().date()
        earnings = (today + timedelta(days=35)).strftime("%Y-%m-%d")
        exp_date_map = {
            f"{(today + timedelta(days=30)).strftime('%Y-%m-%d')}:30": {},
            f"{(today + timedelta(days=33)).strftime('%Y-%m-%d')}:33": {},
            f"{(today + timedelta(days=45)).strftime('%Y-%m-%d')}:45": {},
        }

        valid = scanner._get_valid_expirations(exp_date_map, 25, 50, earnings, 5)
        assert len(valid) == 1
        assert valid[0] == (today + timedelta(days=45)).strftime("%Y-%m-%d")


class TestHumanReasonsPopulated:
    """Issue #190 — every ``RejectedStrike`` carries a parallel human_reasons list."""

    @pytest.mark.unit
    @patch("app.services.options_scanner.get_next_earnings_date", return_value=None)
    @patch("app.services.options_scanner.SchwabClient")
    def test_rejected_strikes_have_human_reasons(self, mock_client_cls, _earnings, scanner, cc_request):
        """The scanner populates ``human_reasons`` parallel to ``rejection_reasons``."""
        dte = 30
        exp_date = (datetime.now().date() + timedelta(days=dte)).strftime("%Y-%m-%d")

        # Mix of failing contracts to exercise multiple rejection codes.
        contracts = [
            # Fails 10pct rule — strike $15.5 only 3% above $15 cost basis
            _make_schwab_contract(
                strike=15.5, bid=0.30, ask=0.40, mark=0.35,
                delta=-0.30, oi=500, dte=dte,
            ),
            # Low OI — strike $17 (passes 10pct), OI=10 < 50
            _make_schwab_contract(
                strike=17.0, bid=0.30, ask=0.40, mark=0.35,
                delta=-0.25, oi=10, dte=dte,
            ),
            # Zero bid — strike $18 (passes 10pct), bid 0.0
            _make_schwab_contract(
                strike=18.0, bid=0.0, ask=0.40, mark=0.20,
                delta=-0.20, oi=500, dte=dte,
            ),
        ]
        chain_resp = _make_schwab_chain_response(
            underlying_price=14.0,
            contracts=contracts,
            contract_type="call",
            exp_date=exp_date,
            dte=dte,
        )

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_option_chain.return_value = chain_resp
        mock_client.get_quote.return_value = {"lastPrice": 14.0}

        result = scanner.scan(cc_request)

        assert len(result["rejected"]) >= 1, "Test fixture should have produced rejected strikes"
        for r in result["rejected"]:
            # human_reasons must mirror rejection_reasons 1:1 in length and order.
            assert len(r.human_reasons) == len(r.rejection_reasons)
            # Each sentence is non-empty and not a raw code (no ": " parameter tail).
            for sentence in r.human_reasons:
                assert sentence, "human_reasons entries must be non-empty"
                # Defensive: a raw code like "fails_10pct_rule: strike ..." would
                # contain the lowercase code prefix. Human sentences should not.
                assert "fails_10pct_rule" not in sentence
                assert "low_open_interest" not in sentence

    @pytest.mark.unit
    @patch("app.services.options_scanner.get_next_earnings_date", return_value=None)
    @patch("app.services.options_scanner.SchwabClient")
    def test_return_below_target_rejection_has_human_reason(self, mock_client_cls, _earnings, scanner, cc_request):
        """The inline ``return_below_target`` branch also populates human_reasons."""
        dte = 30
        exp_date = (datetime.now().date() + timedelta(days=dte)).strftime("%Y-%m-%d")

        # Strike $17 passes filters but premium yields tiny return (below
        # cc_request.min_return_pct=0.5). Spread kept inside the 10% bid/ask
        # rule so the new wide_bid_ask_spread check (#156) is not the reason.
        contract = _make_schwab_contract(
            strike=17.0, bid=0.0145, ask=0.0155, mark=0.015,
            delta=-0.20, oi=500, dte=dte,
        )
        chain_resp = _make_schwab_chain_response(
            underlying_price=14.0,
            contracts=[contract],
            contract_type="call",
            exp_date=exp_date,
            dte=dte,
        )

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_option_chain.return_value = chain_resp
        mock_client.get_quote.return_value = {"lastPrice": 14.0}

        result = scanner.scan(cc_request)

        return_below = [
            r for r in result["rejected"]
            if any("return_below_target" in raw for raw in r.rejection_reasons)
        ]
        assert return_below, "Fixture should have produced a return_below_target rejection"
        for r in return_below:
            assert len(r.human_reasons) == len(r.rejection_reasons)
            assert any("target return" in s for s in r.human_reasons)


# --- Watchlist gate (issue #322 / PRD #213 R5) ---
#
# Pure-unit coverage of the approved-universe gate: the set intersection
# ``{request.ticker} ∩ watchlist`` and the zero-candidate empty response. No
# DB, no app, no network — the gate logic and ``empty_response`` are exercised
# in isolation.

from app.services.options_scanner import (  # noqa: E402
    EMPTY_WATCHLIST_REASON,
    WatchlistGate,
    evaluate_watchlist_gate,
)


class TestWatchlistGate:
    @pytest.mark.unit
    def test_gate_allows_ticker_on_watchlist(self):
        """U1 (AC1) — a ticker on the watchlist passes the gate."""
        gate = evaluate_watchlist_gate("AAPL", ["AAPL", "MSFT"])
        assert gate == WatchlistGate(allowed=True, reason=None)

    @pytest.mark.unit
    def test_gate_allows_case_insensitive_match(self):
        """U2 (AC4) — a lowercase request matches an uppercase watchlist entry."""
        gate = evaluate_watchlist_gate("aapl", ["AAPL"])
        assert gate.allowed is True
        assert gate.reason is None

    @pytest.mark.unit
    def test_gate_blocks_ticker_not_on_watchlist(self):
        """U3 (AC1) — a non-member ticker is blocked with the off-list reason."""
        gate = evaluate_watchlist_gate("MSFT", ["AAPL"])
        assert gate.allowed is False
        assert gate.reason is not None
        assert "MSFT" in gate.reason
        assert "not on your watchlist" in gate.reason

    @pytest.mark.unit
    def test_gate_blocks_on_empty_watchlist(self):
        """U4 (AC2) — an empty watchlist blocks every scan with a clear reason."""
        gate = evaluate_watchlist_gate("AAPL", [])
        assert gate.allowed is False
        assert gate.reason == EMPTY_WATCHLIST_REASON

    @pytest.mark.unit
    def test_gate_empty_watchlist_reason_distinct_from_off_list(self):
        """U5 (AC2) — empty-watchlist and off-list explanations are different."""
        empty = evaluate_watchlist_gate("AAPL", [])
        off_list = evaluate_watchlist_gate("AAPL", ["MSFT"])
        assert empty.reason != off_list.reason
        assert empty.reason == EMPTY_WATCHLIST_REASON


class TestEmptyResponse:
    @pytest.mark.unit
    def test_empty_response_shape_is_zero_candidates(self):
        """U6 (AC2) — the gated empty response carries 0 recs/rejected + reason."""
        scanner = OptionScanner()
        req = OptionScanRequest(
            ticker="MSFT", strategy="covered_call", cost_basis=400.0
        )
        result = scanner.empty_response(req, EMPTY_WATCHLIST_REASON)
        assert result["recommendations"] == []
        assert result["rejected"] == []
        assert result["empty_reason"] == EMPTY_WATCHLIST_REASON
        assert result["watchlist_filtered"] is True

    @pytest.mark.unit
    def test_empty_response_echoes_ticker_and_strategy(self):
        """U7 (AC2) — the empty response preserves the request ticker + strategy."""
        scanner = OptionScanner()
        req = OptionScanRequest(
            ticker="NVDA", strategy="cash_secured_put", capital_available=5000.0
        )
        result = scanner.empty_response(req, "some reason")
        assert result["ticker"] == "NVDA"
        assert result["strategy"] == "cash_secured_put"
        assert result["empty_reason"] == "some reason"


# ---------------------------------------------------------------------------
# Covered-call distance rule — one threshold, cent precision, no double count
# (#456). Direct ``_check_rejection`` / ``_passes_10pct_rule`` calls.
# ---------------------------------------------------------------------------


def _cc_rule_request(
    cost_basis: float,
    *,
    min_call_distance_pct: float = 10.0,
    floor_enabled: bool = True,
    floor_pct: float = 0.0,
) -> OptionScanRequest:
    return OptionScanRequest(
        ticker="F",
        strategy="covered_call",
        cost_basis=cost_basis,
        shares_held=100,
        min_dte=21,
        max_dte=45,
        min_return_pct=0.5,
        min_call_distance_pct=min_call_distance_pct,
        min_delta=0.15,
        max_delta=0.35,
        min_open_interest=50,
        max_bid_ask_spread_pct=10.0,
        cost_basis_floor_enabled=floor_enabled,
        min_call_distance_from_cost_basis_pct=floor_pct,
    )


def _reasons_for(req: OptionScanRequest, strike: float, current_price: float = 12.71):
    # A clean contract — only the strike-distance rules can fire.
    return OptionScanner()._check_rejection(
        req, strike=strike, current_price=current_price,
        delta=0.25, oi=500, bid=0.30, ask=0.31, mid=0.305, dte=30,
    )


class TestCoveredCallDistanceRule:
    @pytest.mark.unit
    def test_check_rejection_1321_strike_1450_fails_with_min_strike_1453(self):
        reasons = _reasons_for(_cc_rule_request(13.21), 14.50)
        assert reasons == [
            "fails_10pct_rule: strike 9.8% above basis, requires 10.0% "
            "(strike $14.50, basis $13.21, min strike $14.53)"
        ]

    @pytest.mark.unit
    def test_check_rejection_1321_strike_1500_passes(self):
        assert _reasons_for(_cc_rule_request(13.21), 15.00) == []

    @pytest.mark.unit
    def test_check_rejection_exactly_110_not_rejected(self):
        # 10.0 * 1.10 == 11.000000000000002 in raw float math — a $11.00
        # strike must pass the 10% rule on a $10.00 basis.
        assert _reasons_for(_cc_rule_request(10.0), 11.00, current_price=10.5) == []

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "strike,basis,expected_pass",
        [
            (12.50, 13.21, False),
            (14.50, 13.21, False),
            (11.00, 10.00, True),
            (14.53, 13.21, True),
            (15.00, 13.21, True),
            (14.52, 13.21, False),
        ],
    )
    def test_passes_10pct_rule_agrees_with_check_rejection(
        self, strike, basis, expected_pass
    ):
        req = _cc_rule_request(basis)
        scanner = OptionScanner()
        fired = any(
            r.startswith("fails_10pct_rule") for r in _reasons_for(req, strike)
        )
        assert scanner._passes_10pct_rule(req, strike) is expected_pass
        assert fired is (not expected_pass)

    @pytest.mark.unit
    def test_fold_below_basis_emits_only_fails_10pct(self):
        reasons = _reasons_for(_cc_rule_request(13.21, floor_enabled=True), 12.50)
        assert len(reasons) == 1
        assert reasons[0].startswith("fails_10pct_rule")
        assert not any(r.startswith("below_cost_basis") for r in reasons)

    @pytest.mark.unit
    def test_floor_stricter_than_margin_still_emits_below_cost_basis(self):
        # T=0, floor=5% → margin strike $20.00, floor strike $21.00. A $20.50
        # strike clears the margin but sits in the [Z_margin, Z_floor) band.
        req = _cc_rule_request(
            20.0, min_call_distance_pct=0.0, floor_enabled=True, floor_pct=5.0
        )
        reasons = _reasons_for(req, 20.50, current_price=20.0)
        assert reasons == ["below_cost_basis: strike $20.50 < floor $21.00"]

    @pytest.mark.unit
    def test_floor_stricter_than_margin_not_hidden_by_margin_failure(self):
        # T=10, floor=15% → margin strike $22.00, floor strike $23.00. A
        # $19.00 strike fails both; the stricter floor must still surface so
        # its higher required strike (and relax recovery) isn't hidden.
        req = _cc_rule_request(
            20.0, min_call_distance_pct=10.0, floor_enabled=True, floor_pct=15.0
        )
        reasons = _reasons_for(req, 19.00, current_price=20.0)
        assert [r.split(":")[0] for r in reasons] == [
            "fails_10pct_rule",
            "below_cost_basis",
        ]
        assert reasons[1] == "below_cost_basis: strike $19.00 < floor $23.00"

    @pytest.mark.unit
    def test_floor_equal_to_margin_uses_cent_precision(self):
        # floor == margin == 10%: 10.0 * 1.10 is 11.000000000000002 in float,
        # but an $11.00 strike must pass both rules on a $10.00 basis.
        req = _cc_rule_request(
            10.0, min_call_distance_pct=10.0, floor_enabled=True, floor_pct=10.0
        )
        assert _reasons_for(req, 11.00, current_price=10.5) == []

    @pytest.mark.unit
    def test_csp_unaffected_by_call_distance(self):
        req = OptionScanRequest(
            ticker="F",
            strategy="cash_secured_put",
            capital_available=5000.0,
            cost_basis=10.0,
            min_call_distance_pct=10.0,
            min_delta=0.15,
            max_delta=0.35,
            min_open_interest=50,
            max_bid_ask_spread_pct=10.0,
        )
        scanner = OptionScanner()
        # Strike $10.50 is above the $10 basis and above the $10.25 price.
        reasons = _reasons_for(req, 10.50, current_price=10.25)
        assert scanner._passes_10pct_rule(req, 10.50) is True
        assert not any(r.startswith("fails_10pct_rule") for r in reasons)
        assert not any(r.startswith("below_cost_basis") for r in reasons)
        assert any(r.startswith("itm_put") for r in reasons)
