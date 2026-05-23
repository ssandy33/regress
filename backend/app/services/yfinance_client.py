"""Thin defensive wrapper around yfinance for the research endpoints (#280).

Two public functions:

- :func:`fetch_business_info` — pulls the Section A payload from
  ``yfinance.Ticker.info``. Returns the picked fields as a dict, or
  ``None`` on any failure.
- :func:`fetch_quarterly_income_stmt` — pulls the Section D fallback
  payload from ``yfinance.Ticker.quarterly_income_stmt``. Returns up to
  ``n`` quarters as a list of dicts (newest first), or ``None``.

Defensive design (plan §4.11 + §8 Risk 1)
-----------------------------------------

- Every field access uses ``.get(name, default)`` — never bracket indexing.
- Every yfinance call is wrapped in a broad ``except`` that logs at
  WARNING and returns ``None``. Per CLAUDE.md, the API surface that
  consumes these functions converts ``None`` to a sanitized 502 detail —
  we never leak ``str(e)``.
- yfinance is imported lazily inside the functions so importing this
  module is cheap and does not pull yfinance's curl/protobuf transitive
  deps into the FastAPI worker until a research endpoint is actually hit.
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


def _coerce_optional_str(value: Any) -> str | None:
    """Return a non-empty string or ``None``.

    yfinance occasionally returns ``""`` or ``NaN`` instead of omitting a
    field; both should be normalized to ``None`` so downstream callers
    can branch cleanly.
    """
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str):
        return value if value.strip() else None
    return str(value)


def _coerce_optional_number(value: Any) -> float | int | None:
    """Coerce a yfinance numeric field, dropping NaNs and unconvertibles."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_business_info(ticker: str) -> dict[str, Any] | None:
    """Pull the Section A business-snapshot payload for ``ticker``.

    Returns a dict with keys ``long_business_summary``, ``sector``,
    ``industry``, ``market_cap``, ``employees`` — each value may be
    ``None`` when yfinance omits the field (foreign listings often skip
    ``sector``; private companies in the dataset skip employees). Returns
    ``None`` only when yfinance itself raises or returns an empty info
    payload, signalling a hard upstream failure.
    """
    try:
        import yfinance  # local import to keep module import cheap
    except ImportError:  # pragma: no cover — declared in requirements.txt
        logger.warning("yfinance not installed; business lookup unavailable")
        return None

    try:
        info = yfinance.Ticker(ticker).info or {}
    except Exception as exc:  # noqa: BLE001 — defensive per plan §4.11
        logger.warning("yfinance Ticker.info failed for %s: %s", ticker, exc)
        return None

    # An empty info dict means yfinance returned nothing useful — treat
    # the call as a hard failure so the caller surfaces a 502.
    if not isinstance(info, dict) or not info:
        logger.warning("yfinance Ticker.info empty for %s", ticker)
        return None

    # Company name: prefer ``longName`` (e.g. "SoFi Technologies, Inc.");
    # fall back to ``shortName`` (e.g. "SoFi Technologies Inc"). Both
    # may be missing on some foreign listings; the API contract surfaces
    # ``None`` in that case.
    name = _coerce_optional_str(info.get("longName")) or _coerce_optional_str(
        info.get("shortName")
    )
    return {
        "name": name,
        "long_business_summary": _coerce_optional_str(
            info.get("longBusinessSummary")
        ),
        "sector": _coerce_optional_str(info.get("sector")),
        "industry": _coerce_optional_str(info.get("industry")),
        "market_cap": _coerce_optional_number(info.get("marketCap")),
        "employees": _coerce_optional_number(info.get("fullTimeEmployees")),
    }


def fetch_quarterly_income_stmt(
    ticker: str, n: int = 8
) -> list[dict[str, Any]] | None:
    """Pull up to ``n`` quarters of income-statement data for ``ticker``.

    Used as the Section D fallback path when Alpha Vantage rate-limits.
    Returns a list of per-quarter dicts (newest first) with normalized
    keys ``fiscal_date_ending``, ``total_revenue``, ``gross_profit``,
    ``operating_income``, ``net_income``, ``diluted_eps``. Missing fields
    are surfaced as ``None`` (the API surface converts to JSON null);
    callers compute derived metrics (gross_margin, operating_margin) from
    the raw fields and surface ``None`` when a numerator or denominator
    is missing.

    Returns ``None`` only on a hard yfinance failure (call raised, empty
    DataFrame, or library not installed).
    """
    try:
        import pandas as pd
        import yfinance
    except ImportError:  # pragma: no cover — declared in requirements.txt
        logger.warning("yfinance not installed; financials fallback unavailable")
        return None

    try:
        ticker_obj = yfinance.Ticker(ticker)
        statement = ticker_obj.quarterly_income_stmt
    except Exception as exc:  # noqa: BLE001 — defensive per plan §4.11
        logger.warning(
            "yfinance quarterly_income_stmt failed for %s: %s", ticker, exc
        )
        return None

    if statement is None or not isinstance(statement, pd.DataFrame):
        logger.warning("yfinance returned non-DataFrame for %s", ticker)
        return None
    if statement.empty:
        logger.warning("yfinance quarterly_income_stmt empty for %s", ticker)
        return None

    # yfinance returns columns = quarter-end Timestamps (most-recent first
    # in 1.3.x, but order is documented as not guaranteed — sort to be
    # safe), and rows = field names like "Total Revenue", "Gross Profit".
    columns = sorted(statement.columns, reverse=True)[:n]

    field_map = {
        "total_revenue": ("Total Revenue", "TotalRevenue"),
        "gross_profit": ("Gross Profit", "GrossProfit"),
        "operating_income": ("Operating Income", "OperatingIncome"),
        "net_income": ("Net Income", "NetIncome"),
        "diluted_eps": ("Diluted EPS", "DilutedEPS", "Basic EPS"),
    }

    def _row_value(field_aliases: tuple[str, ...], column: Any) -> Any:
        for alias in field_aliases:
            if alias in statement.index:
                raw = statement.at[alias, column]
                return _coerce_optional_number(raw)
        return None

    quarters: list[dict[str, Any]] = []
    for column in columns:
        try:
            fiscal_date = column.strftime("%Y-%m-%d")
        except AttributeError:
            fiscal_date = str(column)
        quarters.append(
            {
                "fiscal_date_ending": fiscal_date,
                "total_revenue": _row_value(field_map["total_revenue"], column),
                "gross_profit": _row_value(field_map["gross_profit"], column),
                "operating_income": _row_value(
                    field_map["operating_income"], column
                ),
                "net_income": _row_value(field_map["net_income"], column),
                "diluted_eps": _row_value(field_map["diluted_eps"], column),
            }
        )
    return quarters
