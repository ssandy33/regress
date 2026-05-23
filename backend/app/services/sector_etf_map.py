"""GICS-sector → SPDR-sector-ETF mapping (issue #280, plan §3.3 / §4.4).

Hardcoded constants module used by the regression endpoint
(``/api/positions/{id}/research/regression``) to pick the sector factor
for the multifactor decomposition. yfinance returns the 11 GICS sector
strings verbatim in ``Ticker.info["sector"]``; this module maps each one
to the matching SPDR sector-ETF ticker.

If yfinance returns a sector string we have not mapped (rare — GICS
reclassifies sectors a handful of times per decade), or if the field is
missing entirely (some foreign listings), :func:`lookup_sector_etf`
returns ``None`` and the regression service falls back to a 2-factor
basket (SPY + DGS10) per plan §3.3.

Two callable names are exported for the same lookup so both Worker A
(``resolve_sector_etf``) and Worker D (``lookup_sector_etf``) callers
keep working after the v1.1.0 merge. The behaviour is identical; one
is an alias of the other.
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


def lookup_sector_etf(sector: str | None) -> str | None:
    """Return the SPDR sector ETF ticker for a GICS sector string.

    Lookup is case-sensitive against the exact yfinance strings (see
    :data:`SECTOR_ETF_MAP`). Returns ``None`` when the sector is ``None``,
    an empty/whitespace-only string, a non-string input, or not present
    in the map — the caller must handle the sector-omitted branch.

    Surrounding whitespace is tolerated (stripped before lookup). Casing
    drift is *not* tolerated: yfinance is consistent, so a casing mismatch
    is a real signal that the upstream string format has drifted and the
    caller should fall back to a sector-less basket rather than silently
    misclassify the position.
    """
    if sector is None:
        return None
    if not isinstance(sector, str):
        return None
    key = sector.strip()
    if not key:
        return None
    return SECTOR_ETF_MAP.get(key)


# Worker A authored callers (and tests) using ``resolve_sector_etf``;
# Worker D authored callers (and tests) using ``lookup_sector_etf``. Both
# names point at the same function so neither side breaks after the
# v1.1.0 integration merge.
resolve_sector_etf = lookup_sector_etf
