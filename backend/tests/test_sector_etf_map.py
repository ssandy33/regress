"""Tests for the GICS-sector → SPDR sector ETF map (issue #280).

The map is a hardcoded module-level constant per plan §3.3 / §4.4. These
tests pin the 11-entry contract so a typo or accidental key rename is
caught at the unit-test layer rather than surfacing as a silent
regression-without-sector branch in production.

This file is the union of Worker A's tests (``resolve_sector_etf``) and
Worker D's tests (``lookup_sector_etf``). Both function names resolve to
the same callable in the module under test; both styles are exercised
here so neither side's contract regresses after the v1.1.0 merge.
"""

from __future__ import annotations

import pytest

from app.services.sector_etf_map import (
    SECTOR_ETF_MAP,
    lookup_sector_etf,
    resolve_sector_etf,
)


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


# ---------------------------------------------------------------------------
# Worker A's contract — ``resolve_sector_etf`` + frozen-map shape
# ---------------------------------------------------------------------------


def test_sector_etf_map_has_eleven_entries():
    assert len(SECTOR_ETF_MAP) == 11


def test_sector_etf_map_matches_frozen_contract():
    """Every plan-§3.3 entry maps to the frozen ticker. No extra entries."""
    assert SECTOR_ETF_MAP == _EXPECTED


@pytest.mark.parametrize(("sector", "etf"), list(_EXPECTED.items()))
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


# ---------------------------------------------------------------------------
# Worker D's contract — ``lookup_sector_etf`` + edge-case hardening
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sector", "expected_etf"),
    [
        ("Financial Services", "XLF"),
        ("Technology", "XLK"),
        ("Healthcare", "XLV"),
        ("Energy", "XLE"),
        ("Consumer Defensive", "XLP"),
        ("Consumer Cyclical", "XLY"),
        ("Industrials", "XLI"),
        ("Basic Materials", "XLB"),
        ("Utilities", "XLU"),
        ("Real Estate", "XLRE"),
        ("Communication Services", "XLC"),
    ],
)
def test_all_eleven_gics_sectors_map_to_spdr_etfs(sector: str, expected_etf: str) -> None:
    """Every yfinance GICS sector returns the corresponding SPDR ticker."""
    assert lookup_sector_etf(sector) == expected_etf


def test_map_has_exactly_eleven_entries() -> None:
    """The map covers all 11 GICS sectors — no extras, no omissions."""
    assert len(SECTOR_ETF_MAP) == 11


def test_unknown_sector_returns_none() -> None:
    """An unmapped sector string returns ``None`` (sector-omitted branch)."""
    assert lookup_sector_etf("Telecommunications") is None
    assert lookup_sector_etf("Crypto") is None


def test_none_returns_none() -> None:
    """``None`` input (missing sector) returns ``None``."""
    assert lookup_sector_etf(None) is None


def test_empty_string_returns_none() -> None:
    """Empty / whitespace-only sector strings return ``None``."""
    assert lookup_sector_etf("") is None
    assert lookup_sector_etf("   ") is None


def test_lookup_is_case_sensitive() -> None:
    """yfinance returns canonical-cased strings; we don't lower-case lookups."""
    assert lookup_sector_etf("financial services") is None
    assert lookup_sector_etf("FINANCIAL SERVICES") is None


def test_surrounding_whitespace_is_tolerated() -> None:
    """Defensive: a stray space around a known sector still resolves."""
    assert lookup_sector_etf("  Technology  ") == "XLK"


def test_non_string_input_returns_none() -> None:
    """Non-string inputs (e.g. a yfinance None-coerced int) return None."""
    assert lookup_sector_etf(123) is None  # type: ignore[arg-type]
    assert lookup_sector_etf(["Technology"]) is None  # type: ignore[arg-type]


def test_all_etf_values_are_xl_prefixed() -> None:
    """All values follow the SPDR ``XL*`` naming convention."""
    for etf in SECTOR_ETF_MAP.values():
        assert etf.startswith("XL"), f"{etf} does not look like a SPDR sector ETF"
