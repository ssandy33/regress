import math
import pytest
from app.services.greeks import calculate_greeks


class TestBlackScholesGreeks:
    """Validate Black-Scholes Greeks calculations against known values."""

    def test_atm_put_delta_near_minus_half(self):
        result = calculate_greeks(spot=100, strike=100, dte=30, iv=0.30, contract_type="PUT")
        assert result["delta"] is not None
        assert -0.6 < result["delta"] < -0.4

    def test_atm_call_delta_near_half(self):
        result = calculate_greeks(spot=100, strike=100, dte=30, iv=0.30, contract_type="CALL")
        assert result["delta"] is not None
        assert 0.4 < result["delta"] < 0.6

    def test_deep_otm_put_delta_near_zero(self):
        result = calculate_greeks(spot=100, strike=70, dte=30, iv=0.30, contract_type="PUT")
        assert -0.05 < result["delta"] < 0

    def test_deep_itm_call_delta_near_one(self):
        result = calculate_greeks(spot=100, strike=70, dte=30, iv=0.30, contract_type="CALL")
        assert result["delta"] > 0.95

    def test_gamma_is_positive(self):
        result = calculate_greeks(spot=100, strike=100, dte=30, iv=0.30, contract_type="PUT")
        assert result["gamma"] > 0

    def test_put_theta_is_negative(self):
        result = calculate_greeks(spot=100, strike=100, dte=30, iv=0.30, contract_type="PUT")
        assert result["theta"] < 0

    def test_vega_is_positive(self):
        result = calculate_greeks(spot=100, strike=100, dte=30, iv=0.30, contract_type="PUT")
        assert result["vega"] > 0

    def test_call_put_delta_parity(self):
        """Call delta - put delta should equal ~1."""
        call = calculate_greeks(spot=100, strike=100, dte=30, iv=0.30, contract_type="CALL")
        put = calculate_greeks(spot=100, strike=100, dte=30, iv=0.30, contract_type="PUT")
        assert abs(call["delta"] - put["delta"] - 1.0) < 0.01

    def test_call_put_same_gamma(self):
        call = calculate_greeks(spot=100, strike=100, dte=30, iv=0.30, contract_type="CALL")
        put = calculate_greeks(spot=100, strike=100, dte=30, iv=0.30, contract_type="PUT")
        assert abs(call["gamma"] - put["gamma"]) < 0.0001

    def test_returns_none_when_iv_missing(self):
        result = calculate_greeks(spot=100, strike=100, dte=30, iv=None, contract_type="PUT")
        assert result == {"delta": None, "gamma": None, "theta": None, "vega": None}

    def test_returns_none_when_dte_zero(self):
        result = calculate_greeks(spot=100, strike=100, dte=0, iv=0.30, contract_type="PUT")
        assert result == {"delta": None, "gamma": None, "theta": None, "vega": None}

    def test_returns_none_when_spot_zero(self):
        result = calculate_greeks(spot=0, strike=100, dte=30, iv=0.30, contract_type="PUT")
        assert result == {"delta": None, "gamma": None, "theta": None, "vega": None}

    def test_realistic_csp_scenario(self):
        """F stock at $12.15, $11 put, 30 DTE, 35% IV."""
        result = calculate_greeks(spot=12.15, strike=11.0, dte=30, iv=0.35, contract_type="PUT")
        assert result["delta"] is not None
        assert -0.40 < result["delta"] < -0.05
        assert result["gamma"] > 0
        assert result["theta"] < 0
        assert result["vega"] > 0
