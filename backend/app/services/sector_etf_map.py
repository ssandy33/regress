"""GICS-sector → SPDR-sector-ETF mapping (issue #280, plan §3.3 / §4.4).

Hardcoded constants module used by the regression endpoint
(``/api/positions/{id}/research/regression``) to pick the sector factor
for the multifactor decomposition. yfinance returns the 11 GICS sector
strings verbatim in ``Ticker.info["sector"]``; this module maps each one
to the matching SPDR sector-ETF ticker.

If yfinance returns a sector string we have not mapped (rare — GICS
reclassifies sectors a handful of times per decade), or if the field is
missing entirely (some foreign listings), :func:`resolve_sector_etf`
returns ``None`` and the regression service falls back to a 2-factor
basket (SPY + DGS10) per plan §3.3.
"""

from __future__ import annotations

# Eleven GICS sectors. yfinance returns these strings verbatim; the map
# is keyed by the exact spelling and casing.
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


def resolve_sector_etf(sector: str | None) -> str | None:
    """Return the SPDR sector ETF ticker for ``sector`` or ``None``.

    ``None`` is returned when the input is falsy (``None``, empty string)
    or when the sector string is not in :data:`SECTOR_ETF_MAP`. The lookup
    is case-sensitive on purpose: yfinance is consistent, so a casing
    mismatch is a real signal that the upstream string format has drifted
    and the caller should fall back to a sector-less basket rather than
    silently misclassify the position.
    """
    if not sector:
        return None
    return SECTOR_ETF_MAP.get(sector)
