"""Per-position regression decomposition service (issue #280, Section E).

Composes the ``GET /api/positions/{id}/research/regression`` response by:

1. Resolving the position's ticker (and optionally the sector via the
   yfinance client, if Worker A's wrapper is available).
2. Selecting a sector ETF for the regression basket via
   :mod:`app.services.sector_etf_map`. Falls back to a SPY+DGS10-only
   basket when no sector can be resolved.
3. Fetching daily price series for the ticker + factors and the FRED 10Y
   yield (``DGS10``) over the 1Y window using the existing
   :class:`app.services.data_fetcher.DataFetcher`.
4. Computing daily log returns, aligning on the common date index, and
   handing the aligned data to the existing multi-factor OLS engine in
   :func:`app.services.regression.compute_multifactor_ols`.
5. Translating the engine's output into the contract-frozen response
   shape (factors + summary + donut shares) per the plan §4.2.

Cache TTL is 5 minutes per NFR-7 (key ``research:regression:{position_id}:{window}``).
The cache is process-local: a single in-memory dict guarded by ISO
timestamps. Server restarts evict the cache harmlessly because each
response can be rebuilt from fresh data in seconds.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from app.services.data_fetcher import (
    DataAlignmentError,
    DataFetcher,
    DataFetchError,
    InvalidTickerError,
)
from app.services.regression import compute_multifactor_ols
from app.services.regression_summary import SummaryFactor, build_regression_summary
from app.services.sector_etf_map import lookup_sector_etf
from app.utils.transforms import align_datasets

logger = logging.getLogger(__name__)


# --- Public errors ---------------------------------------------------------


class InsufficientRegressionDataError(Exception):
    """Raised when fewer than ``MIN_OBSERVATIONS`` aligned trading days exist."""


class RegressionSourceUnavailableError(Exception):
    """Raised when an upstream data source (Schwab / FRED / sector ETF) fails."""


# --- Pydantic response models (frozen per plan §4.2) ----------------------


class RegressionFactorPayload(BaseModel):
    """Per-factor row in the regression response.

    ``name`` is one of ``"market"``, ``"sector"``, ``"rates"``, or
    ``"idiosyncratic"``. ``beta`` and ``p_value`` are ``None`` for the
    idiosyncratic residual. ``contribution`` is the share of variance
    (factors + idiosyncratic sum to ~1.0).
    """

    model_config = ConfigDict(strict=True)

    name: Literal["market", "sector", "rates", "idiosyncratic"]
    ticker: str | None
    beta: float | None
    p_value: float | None
    contribution: float


class ResearchRegressionResponse(BaseModel):
    """``/research/regression`` response payload (issue #280, Section E)."""

    model_config = ConfigDict(strict=True)

    position_id: str
    ticker: str
    window: str
    basket: list[str]
    sector_omitted: bool
    factors: list[RegressionFactorPayload]
    r_squared: float
    idiosyncratic_share: float
    sample_size: int
    summary: str
    as_of: str


# --- Constants -------------------------------------------------------------


MIN_OBSERVATIONS = 60
DEFAULT_WINDOW = "1Y"
WINDOW_TO_DAYS: dict[str, int] = {"1Y": 365}
CACHE_TTL_SECONDS = 5 * 60
SUPPORTED_WINDOWS: frozenset[str] = frozenset({"1Y"})


# --- In-memory cache --------------------------------------------------------


_cache: dict[str, tuple[float, ResearchRegressionResponse]] = {}


def _cache_key(position_id: str, window: str) -> str:
    """Build the contract-frozen cache key for this endpoint."""
    return f"research:regression:{position_id}:{window}"


def _cache_get(key: str) -> ResearchRegressionResponse | None:
    """Return a cached response if still fresh; evict if expired."""
    entry = _cache.get(key)
    if entry is None:
        return None
    timestamp, value = entry
    if (time.monotonic() - timestamp) > CACHE_TTL_SECONDS:
        _cache.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: ResearchRegressionResponse) -> None:
    """Store a response in the process-local cache."""
    _cache[key] = (time.monotonic(), value)


def clear_cache() -> None:
    """Evict every cached entry; intended for tests and admin tooling."""
    _cache.clear()


# --- Sector resolution ------------------------------------------------------


def _resolve_sector_for_ticker(ticker: str) -> str | None:
    """Look up the position's sector via Worker A's yfinance wrapper, if present.

    The yfinance client is owned by Worker A in the v1.1.0 fan-out and may
    not exist on this branch in isolation. The import is intentionally
    defensive so this worker is testable independently and so the endpoint
    degrades gracefully (sector-omitted branch) when the wrapper is absent
    or yfinance itself raises.
    """
    try:
        from app.services import yfinance_client  # type: ignore[attr-defined]
    except ImportError:
        return None
    try:
        info = yfinance_client.fetch_business_info(ticker)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — defensive: any yfinance error
        logger.warning("yfinance lookup failed for %s; omitting sector", ticker)
        return None
    if not info:
        return None
    sector = info.get("sector") if isinstance(info, dict) else None
    if sector is None or not isinstance(sector, str) or not sector.strip():
        return None
    return sector.strip()


# --- Window helpers ---------------------------------------------------------


def _window_date_range(window: str) -> tuple[str, str]:
    """Return ``(start_date, end_date)`` ISO strings for a regression window."""
    days = WINDOW_TO_DAYS[window]
    end = datetime.now(timezone.utc).date()
    # Pad the start by ~30 days so post-alignment we still have enough
    # trading days after weekends/holidays are dropped.
    start = end - timedelta(days=days + 30)
    return start.isoformat(), end.isoformat()


def validate_window(window: str) -> str:
    """Validate the ``window`` query param.

    Raises :class:`ValueError` with a sanitized message when the value is
    not in :data:`SUPPORTED_WINDOWS`. Callers should translate this into
    an HTTP 422.
    """
    if window not in SUPPORTED_WINDOWS:
        raise ValueError("Unsupported window value")
    return window


# --- Returns helpers --------------------------------------------------------


def _log_returns(series: pd.Series) -> pd.Series:
    """Compute daily log returns from a price/level series.

    NaN-safe: an all-zero or non-positive input would generate inf/NaN
    rows which :func:`align_datasets` drops downstream.
    """
    return np.log(series).diff()


def _build_factor_payloads(
    coefficients: dict[str, float],
    p_values: dict[str, float],
    contributions: dict[str, float],
    idiosyncratic_share: float,
    factor_name_to_ticker: dict[str, str],
    basket_names: list[str],
) -> list[RegressionFactorPayload]:
    """Assemble the ``factors`` array for the response, including the residual."""
    payloads: list[RegressionFactorPayload] = []
    # Render factors in a stable, frontend-friendly order: market → sector → rates.
    canonical_order = ["market", "sector", "rates"]
    for name in canonical_order:
        if name not in basket_names:
            continue
        ticker = factor_name_to_ticker.get(name)
        payloads.append(
            RegressionFactorPayload(
                name=name,  # type: ignore[arg-type]
                ticker=ticker,
                beta=float(coefficients[name]),
                p_value=float(p_values[name]),
                contribution=float(contributions[name]),
            )
        )
    payloads.append(
        RegressionFactorPayload(
            name="idiosyncratic",
            ticker=None,
            beta=None,
            p_value=None,
            contribution=float(idiosyncratic_share),
        )
    )
    return payloads


def _compute_contributions(
    coefficients: dict[str, float],
    factor_returns: pd.DataFrame,
    r_squared: float,
) -> dict[str, float]:
    """Compute each factor's share of the explained variance.

    Uses ``(beta_i * std(x_i))^2`` normalized so the explained shares sum
    to ``r_squared``. The idiosyncratic share (``1 - r_squared``) is
    appended by the caller so factors + idiosyncratic sum to ~1.0.
    """
    raw: dict[str, float] = {}
    for name in factor_returns.columns:
        std = float(factor_returns[name].std(ddof=1))
        raw[name] = (coefficients[name] * std) ** 2
    total = sum(raw.values())
    if total <= 0:
        # Degenerate fallback: distribute evenly so the donut still renders.
        n = len(raw)
        return {name: r_squared / n for name in raw}
    return {name: (val / total) * r_squared for name, val in raw.items()}


# --- Core composition ------------------------------------------------------


def compose_regression_response(
    *,
    position_id: str,
    ticker: str,
    window: str,
    fetcher: DataFetcher,
    sector: str | None,
) -> ResearchRegressionResponse:
    """Pure composition function: fetch series, run regression, build response.

    Separated from the cache wrapper so tests can exercise the full
    pipeline with a stubbed ``DataFetcher`` without touching the cache.

    Raises:
      InsufficientRegressionDataError — fewer than 60 aligned trading days.
      RegressionSourceUnavailableError — Schwab/FRED/sector ETF failed.
    """
    validate_window(window)
    sector_etf = lookup_sector_etf(sector)
    sector_omitted = sector_etf is None

    start, end = _window_date_range(window)

    # Build the factor list: SPY always, sector ETF when known, plus DGS10.
    factor_name_to_ticker: dict[str, str] = {"market": "SPY", "rates": "DGS10"}
    if sector_etf is not None:
        factor_name_to_ticker["sector"] = sector_etf

    basket_names = list(factor_name_to_ticker.keys())
    basket_tickers = [factor_name_to_ticker[n] for n in basket_names]

    # Fetch every series. Any failure → 502 via RegressionSourceUnavailableError.
    series_by_ticker: dict[str, pd.Series] = {}
    fetch_order = [ticker, *basket_tickers]
    for ident in fetch_order:
        try:
            df, _ = fetcher.fetch(ident, start, end)
        except (InvalidTickerError, DataFetchError, Exception) as exc:
            # Sanitize: never propagate str(e) to the client. Logged for ops.
            logger.warning(
                "Regression fetch failed for %s: %s", ident, exc.__class__.__name__
            )
            raise RegressionSourceUnavailableError(
                f"Source unavailable for {ident}"
            ) from exc
        if "value" not in df.columns or len(df) == 0:
            raise RegressionSourceUnavailableError(
                f"Source returned empty data for {ident}"
            )
        series_by_ticker[ident] = df["value"]

    # Compute log returns for prices (ticker + ETFs). DGS10 is a yield in
    # percent — use first differences so the regression interprets it on
    # the same "daily change" scale as the equity returns.
    returns_by_name: dict[str, pd.Series] = {}
    ticker_returns = _log_returns(series_by_ticker[ticker]).dropna()
    returns_by_name["__ticker__"] = ticker_returns
    for factor_name, factor_ticker in factor_name_to_ticker.items():
        s = series_by_ticker[factor_ticker]
        if factor_name == "rates":
            r = s.diff().dropna()
        else:
            r = _log_returns(s).dropna()
        returns_by_name[factor_name] = r

    # Reuse the project's align_datasets helper for inner-join + ffill semantics.
    datasets: dict[str, pd.DataFrame] = {
        name: pd.DataFrame({"value": s}) for name, s in returns_by_name.items()
    }
    try:
        aligned, _ = align_datasets(datasets)
    except Exception as exc:  # noqa: BLE001 — wrap into a typed error
        logger.warning("Alignment failed for position %s: %s", position_id, exc)
        raise InsufficientRegressionDataError(
            "Insufficient data for regression"
        ) from exc

    if len(aligned) < MIN_OBSERVATIONS:
        raise InsufficientRegressionDataError("Insufficient data for regression")

    dates = [idx.strftime("%Y-%m-%d") for idx in aligned.index]
    y = aligned["__ticker__"].tolist()
    x_df_dict = {name: aligned[name].tolist() for name in basket_names}

    try:
        result = compute_multifactor_ols(dates, y, x_df_dict)
    except Exception as exc:  # noqa: BLE001 — near-singular factor matrix, etc.
        logger.warning(
            "Regression engine failed for position %s: %s",
            position_id,
            exc.__class__.__name__,
        )
        raise InsufficientRegressionDataError(
            "Regression failed: factor matrix could not be fit"
        ) from exc

    r_squared = float(result["r_squared"])
    coefficients: dict[str, float] = {k: float(v) for k, v in result["coefficients"].items()}
    p_values: dict[str, float] = {k: float(v) for k, v in result["p_values"].items()}

    contributions = _compute_contributions(
        coefficients,
        aligned[basket_names],
        r_squared,
    )
    idiosyncratic_share = max(0.0, 1.0 - r_squared)

    factors = _build_factor_payloads(
        coefficients=coefficients,
        p_values=p_values,
        contributions=contributions,
        idiosyncratic_share=idiosyncratic_share,
        factor_name_to_ticker=factor_name_to_ticker,
        basket_names=basket_names,
    )

    summary_factors: list[SummaryFactor] = [
        {
            "name": f.name,
            "beta": f.beta,
            "p_value": f.p_value,
            "contribution": f.contribution,
        }
        for f in factors
    ]
    summary = build_regression_summary(
        factors=summary_factors,
        r_squared=r_squared,
        sample_size=int(result["sample_size"]),
        sector_omitted=sector_omitted,
    )

    return ResearchRegressionResponse(
        position_id=position_id,
        ticker=ticker,
        window=window,
        basket=basket_tickers,
        sector_omitted=sector_omitted,
        factors=factors,
        r_squared=r_squared,
        idiosyncratic_share=idiosyncratic_share,
        sample_size=int(result["sample_size"]),
        summary=summary,
        as_of=datetime.now(timezone.utc).isoformat(),
    )


def get_regression_for_position(
    *,
    position_id: str,
    ticker: str,
    window: str,
    fetcher: DataFetcher,
    sector: str | None = None,
) -> ResearchRegressionResponse:
    """Cache-aware wrapper around :func:`compose_regression_response`.

    Looks up the sector via the yfinance wrapper when not provided, then
    returns either a cached response (TTL :data:`CACHE_TTL_SECONDS`) or a
    freshly composed one.
    """
    key = _cache_key(position_id, window)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    resolved_sector = sector if sector is not None else _resolve_sector_for_ticker(ticker)

    response = compose_regression_response(
        position_id=position_id,
        ticker=ticker,
        window=window,
        fetcher=fetcher,
        sector=resolved_sector,
    )
    _cache_set(key, response)
    return response


__all__ = [
    "DEFAULT_WINDOW",
    "InsufficientRegressionDataError",
    "MIN_OBSERVATIONS",
    "RegressionSourceUnavailableError",
    "RegressionFactorPayload",
    "ResearchRegressionResponse",
    "SUPPORTED_WINDOWS",
    "clear_cache",
    "compose_regression_response",
    "get_regression_for_position",
    "validate_window",
]
