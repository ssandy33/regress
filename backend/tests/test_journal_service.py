"""Unit tests for journal computation functions."""

from types import SimpleNamespace

from app.services.journal import (
    compute_adjusted_basis,
    compute_min_cc_strike,
    compute_total_premiums,
)


def _make_trade(premium: float, quantity: int = 1) -> SimpleNamespace:
    """Create a minimal trade-like object for computation tests."""
    return SimpleNamespace(premium=premium, quantity=quantity)


def test_compute_total_premiums_sell_only():
    """Two sell_put trades should produce a positive total."""
    trades = [
        _make_trade(premium=1.50, quantity=1),  # 1.50 * 1 * 100 = 150
        _make_trade(premium=2.00, quantity=1),  # 2.00 * 1 * 100 = 200
    ]
    assert compute_total_premiums(trades) == 350.0


def test_compute_total_premiums_mixed():
    """Sells and buy-to-close should net out correctly."""
    trades = [
        _make_trade(premium=2.00, quantity=1),   # +200
        _make_trade(premium=-0.50, quantity=1),  # -50
    ]
    assert compute_total_premiums(trades) == 150.0


def test_compute_total_premiums_empty():
    """No trades should return 0.0."""
    assert compute_total_premiums([]) == 0.0


def test_compute_adjusted_basis():
    """broker_cost_basis 5000, premiums 350 -> 4650."""
    assert compute_adjusted_basis(5000.0, 350.0) == 4650.0


def test_compute_min_cc_strike():
    """adjusted 4650, 100 shares -> (4650/100)*1.10 = 51.15."""
    assert compute_min_cc_strike(4650.0, 100) == 51.15


def test_compute_min_cc_strike_rounding():
    """Verify result is rounded to 2 decimal places."""
    # 4777 / 100 = 47.77, * 1.10 = 52.547 -> 52.55
    result = compute_min_cc_strike(4777.0, 100)
    assert result == 52.55
    # Confirm it's actually rounded (string check)
    assert len(str(result).split(".")[-1]) <= 2
