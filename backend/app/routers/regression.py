from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from app.models.database import get_db
import numpy as np
from scipy import stats

from app.models.schemas import (
    AssetCompareStats,
    CompareRequest,
    CompareResponse,
    LinearRegressionRequest,
    LinearRegressionResponse,
    MultiFactorRequest,
    MultiFactorResponse,
    RollingRegressionRequest,
    RollingRegressionResponse,
)
import logging

from app.services.cache import CacheService
from app.services.data_fetcher import DataFetcher, DataAlignmentError, DataMeta, detect_source
from app.services.regression import (
    compute_linear_regression,
    compute_multifactor_ols,
    compute_rolling_regression,
)
from app.utils.transforms import align_datasets

router = APIRouter(prefix="/api/regression", tags=["regression"])


def _get_fetcher(db: DBSession = Depends(get_db)) -> DataFetcher:
    return DataFetcher(CacheService(db))


@router.post("/linear", response_model=LinearRegressionResponse)
def linear_regression(
    req: LinearRegressionRequest,
    fetcher: DataFetcher = Depends(_get_fetcher),
):
    """Compute linear regression (price vs time trend) for a single asset."""
    df, meta = fetcher.fetch(req.asset, req.start_date, req.end_date)

    dates = [idx.strftime("%Y-%m-%d") for idx in df.index]
    values = df["value"].tolist()

    result = compute_linear_regression(dates, values)
    result["data_meta"] = meta

    # Fetch earnings dates for yfinance tickers
    if detect_source(req.asset) in ("yfinance", "schwab"):
        try:
            import yfinance as yf
            ticker = yf.Ticker(req.asset)
            ed = ticker.get_earnings_dates(limit=40)
            if ed is not None and not ed.empty:
                start = df.index.min()
                end = df.index.max()
                ed_dates = ed.index.normalize()
                in_range = ed_dates[(ed_dates >= start) & (ed_dates <= end)]
                result["earnings_dates"] = sorted(set(d.strftime("%Y-%m-%d") for d in in_range))
        except Exception:
            logging.getLogger(__name__).debug(f"Could not fetch earnings dates for {req.asset}")

    return LinearRegressionResponse(**result)


@router.post("/multi-factor", response_model=MultiFactorResponse)
def multi_factor_regression(
    req: MultiFactorRequest,
    fetcher: DataFetcher = Depends(_get_fetcher),
):
    """Run multi-factor OLS regression with automatic data alignment."""
    # Fetch all datasets
    all_identifiers = [req.dependent] + req.independents
    datasets = {}
    metas: list[DataMeta] = []

    for identifier in all_identifiers:
        df, meta = fetcher.fetch(identifier, req.start_date, req.end_date)
        datasets[identifier] = df
        metas.append(meta)

    # Align datasets
    try:
        aligned, notes = align_datasets(datasets)
    except Exception as e:
        raise DataAlignmentError(f"Failed to align datasets: {e}")

    if len(aligned) < len(req.independents) + 2:
        raise DataAlignmentError(
            f"Insufficient aligned data: {len(aligned)} observations for "
            f"{len(req.independents)} factors (need at least {len(req.independents) + 2})"
        )

    dates = [idx.strftime("%Y-%m-%d") for idx in aligned.index]
    y = aligned[req.dependent].tolist()
    x_dict = {name: aligned[name].tolist() for name in req.independents}

    result = compute_multifactor_ols(dates, y, x_dict)
    result["data_meta"] = [m.model_dump() for m in metas]
    result["alignment_notes"] = notes

    return MultiFactorResponse(**result)


@router.post("/rolling", response_model=RollingRegressionResponse)
def rolling_regression(
    req: RollingRegressionRequest,
    fetcher: DataFetcher = Depends(_get_fetcher),
):
    """Compute rolling linear regression for a single asset."""
    df, meta = fetcher.fetch(req.asset, req.start_date, req.end_date)

    dates = [idx.strftime("%Y-%m-%d") for idx in df.index]
    values = df["value"].tolist()

    result = compute_rolling_regression(dates, values, req.window_size)
    result["data_meta"] = meta

    return RollingRegressionResponse(**result)


@router.post("/compare", response_model=CompareResponse)
def compare_assets(
    req: CompareRequest,
    fetcher: DataFetcher = Depends(_get_fetcher),
):
    """Compare multiple assets normalized to a common base (100 at start)."""
    if len(req.assets) < 2 or len(req.assets) > 5:
        raise ValueError("Compare mode requires 2-5 assets")

    datasets = {}
    metas: list[DataMeta] = []

    for identifier in req.assets:
        df, meta = fetcher.fetch(identifier, req.start_date, req.end_date)
        datasets[identifier] = df
        metas.append(meta)

    # Align datasets
    try:
        aligned, notes = align_datasets(datasets)
    except Exception as e:
        raise DataAlignmentError(f"Failed to align datasets: {e}")

    if len(aligned) < 3:
        raise DataAlignmentError(f"Insufficient aligned data: {len(aligned)} observations")

    dates = [idx.strftime("%Y-%m-%d") for idx in aligned.index]

    # Normalize each series to base 100
    series = {}
    asset_stats = []

    for name in req.assets:
        values = aligned[name].values
        base = values[0]
        normalized = (values / base * 100).tolist()
        series[name] = normalized

        # Compute per-asset stats
        n = len(values)
        t = np.arange(n, dtype=float)
        result = stats.linregress(t, values)
        r_squared = float(result.rvalue ** 2)

        # Annualized return (using the normalized series)
        total_return = (values[-1] / values[0]) - 1
        years = n / 252 if metas[req.assets.index(name)].frequency == "daily" else n / 12
        annualized = (1 + total_return) ** (1 / max(years, 0.1)) - 1

        # Volatility (annualized std dev of returns)
        returns = np.diff(values) / values[:-1]
        factor = np.sqrt(252) if metas[req.assets.index(name)].frequency == "daily" else np.sqrt(12)
        volatility = float(np.std(returns) * factor)

        asset_stats.append(AssetCompareStats(
            identifier=name,
            annualized_return=float(annualized),
            volatility=volatility,
            r_squared=r_squared,
        ))

    return CompareResponse(
        dates=dates,
        series=series,
        stats=asset_stats,
        data_meta=[m.model_dump() for m in metas],
        alignment_notes=notes,
    )
