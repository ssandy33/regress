import logging

import requests as _requests
from fastapi import APIRouter

from app.config import get_fred_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/sources")
def check_sources():
    """Ping each data source and return status."""
    results = {
        "yfinance": _check_yfinance(),
        "fred": _check_fred(),
        "zillow": _check_zillow(),
    }
    results["all_down"] = all(
        not v["available"] for k, v in results.items() if k != "all_down"
    )
    return results


def _check_yfinance() -> dict:
    """Check Yahoo Finance via direct API (avoids yfinance library rate limits)."""
    try:
        resp = _requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=1d&interval=1d",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        return {"available": resp.status_code == 200, "error": None}
    except Exception as e:
        logger.debug(f"yfinance health check failed: {e}")
        return {"available": False, "error": str(e)}


def _check_fred() -> dict:
    """Check FRED API by fetching a single data point."""
    try:
        key = get_fred_api_key()
        if not key:
            return {"available": False, "error": "API key not configured"}
        from fredapi import Fred

        fred = Fred(api_key=key)
        fred.get_series("DGS10", observation_start="2024-01-01", observation_end="2024-01-05")
        return {"available": True, "error": None}
    except Exception as e:
        logger.debug(f"FRED health check failed: {e}")
        return {"available": False, "error": str(e)}


def _check_zillow() -> dict:
    """Check Zillow CSV availability via HEAD request."""
    try:
        resp = _requests.head(
            "https://files.zillowstatic.com/research/public_csvs/zhvi/Zip_zhvi_uf_sm_sa_month.csv",
            timeout=10,
        )
        return {"available": resp.status_code == 200, "error": None}
    except Exception as e:
        logger.debug(f"Zillow health check failed: {e}")
        return {"available": False, "error": str(e)}
