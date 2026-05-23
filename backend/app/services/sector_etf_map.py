"""GICS sector → SPDR sector ETF mapping.

Module-level constant mapping the 11 GICS sectors yfinance returns verbatim
in ``Ticker.info["sector"]`` to their corresponding SPDR sector ETF tickers.
Used by the per-position regression decomposition (issue #280) to pick a
sector factor when the position's underlying has a known GICS sector.

Frozen by issue #280 plan §3.3 / §4.4. If a sector is missing or unmapped,
:func:`lookup_sector_etf` returns ``None`` and the caller is expected to
run the regression with ``SPY + DGS10`` only (sector factor omitted).
"""

from __future__ import annotations

SECTOR_ETF_MAP: dict[str, str] = {
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


def lookup_sector_etf(sector: str | None) -> str | None:
    """Return the SPDR sector ETF ticker for a GICS sector string.

    Lookup is case-sensitive against the exact yfinance strings (see
    ``SECTOR_ETF_MAP``). Returns ``None`` when the sector is ``None``,
    an empty/whitespace-only string, or not present in the map — the
    caller must handle the sector-omitted branch.
    """
    if sector is None:
        return None
    if not isinstance(sector, str):
        return None
    key = sector.strip()
    if not key:
        return None
    return SECTOR_ETF_MAP.get(key)
