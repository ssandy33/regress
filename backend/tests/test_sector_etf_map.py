"""Tests for the GICS-sector → SPDR sector ETF map (issue #280, W-A).

The map is a hardcoded module-level constant per plan §3.3 / §4.4. These
tests pin the 11-entry contract so a typo or accidental key rename is
caught at the unit-test layer rather than surfacing as a silent
regression-without-sector branch in production.
"""

from __future__ import annotations

import pytest

from app.services.sector_etf_map import SECTOR_ETF_MAP, resolve_sector_etf


# Frozen 11 entries — case-sensitive, verbatim from plan §3.3.
_EXPECTED: dict[str, str] = {
    "Financial Services": "XLF",
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Energy": "XLE",
    "Consumer Defensive": "XLP",
    "Consumer Cyclical": "XLY",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}


def test_sector_etf_map_has_eleven_entries():
    assert len(SECTOR_ETF_MAP) == 11


def test_sector_etf_map_matches_frozen_contract():
    """Every plan-§3.3 entry maps to the frozen ticker. No extra entries."""
    assert SECTOR_ETF_MAP == _EXPECTED


@pytest.mark.parametrize("sector,etf", list(_EXPECTED.items()))
def test_resolve_sector_etf_returns_etf_for_each_known_sector(
    sector: str, etf: str
):
    assert resolve_sector_etf(sector) == etf


def test_resolve_sector_etf_returns_none_for_unmapped_sector():
    """Unknown GICS sector → None so the regression service drops the factor."""
    assert resolve_sector_etf("Magical Cryptocurrencies") is None


def test_resolve_sector_etf_returns_none_for_missing_sector():
    """yfinance sometimes omits ``info.sector`` entirely → None propagates."""
    assert resolve_sector_etf(None) is None
    assert resolve_sector_etf("") is None


def test_resolve_sector_etf_is_case_sensitive():
    """Casing drift should NOT silently misclassify — caller falls back instead."""
    assert resolve_sector_etf("financial services") is None
    assert resolve_sector_etf("TECHNOLOGY") is None
