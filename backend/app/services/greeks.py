"""Black-Scholes Greeks calculator — fallback when market Greeks are unavailable."""

import math
from scipy.stats import norm

# Default risk-free rate (approximate US Treasury yield)
DEFAULT_RISK_FREE_RATE = 0.045


def _d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    return (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))


def _d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
    return _d1(S, K, T, r, sigma) - sigma * math.sqrt(T)


def calculate_greeks(
    spot: float,
    strike: float,
    dte: int,
    iv: float,
    contract_type: str = "PUT",
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> dict:
    """Calculate Black-Scholes Greeks for an option contract.

    Args:
        spot: Current underlying price.
        strike: Option strike price.
        dte: Days to expiration.
        iv: Implied volatility as a decimal (e.g. 0.35 for 35%).
        contract_type: "CALL" or "PUT".
        risk_free_rate: Annualized risk-free rate.

    Returns:
        Dict with delta, gamma, theta (per day), and vega (per 1% IV move).
        Returns all None if inputs are insufficient for calculation.
    """
    if not all([spot > 0, strike > 0, dte > 0, iv and iv > 0]):
        return {"delta": None, "gamma": None, "theta": None, "vega": None}

    T = dte / 365.0
    sqrt_T = math.sqrt(T)

    d1 = _d1(spot, strike, T, risk_free_rate, iv)
    d2 = _d2(spot, strike, T, risk_free_rate, iv)

    gamma = norm.pdf(d1) / (spot * iv * sqrt_T)
    vega = spot * norm.pdf(d1) * sqrt_T / 100  # per 1% move

    if contract_type == "CALL":
        delta = norm.cdf(d1)
        theta = (
            -spot * norm.pdf(d1) * iv / (2 * sqrt_T)
            - risk_free_rate * strike * math.exp(-risk_free_rate * T) * norm.cdf(d2)
        ) / 365
    else:
        delta = norm.cdf(d1) - 1  # negative for puts
        theta = (
            -spot * norm.pdf(d1) * iv / (2 * sqrt_T)
            + risk_free_rate * strike * math.exp(-risk_free_rate * T) * norm.cdf(-d2)
        ) / 365

    return {
        "delta": round(delta, 6),
        "gamma": round(gamma, 6),
        "theta": round(theta, 6),
        "vega": round(vega, 6),
    }
