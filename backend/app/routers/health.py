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
        "alpha_vantage": _check_alpha_vantage(),
        "fred": _check_fred(),
        "zillow": _check_zillow(),
        "schwab": _check_schwab(),
    }
    results["all_down"] = all(
        not v["available"] for k, v in results.items() if k != "all_down"
    )
    return results


def _check_alpha_vantage() -> dict:
    """Check Alpha Vantage API availability."""
    try:
        from app.services.alpha_vantage_client import get_alpha_vantage_api_key
        api_key = get_alpha_vantage_api_key()
        if not api_key:
            return {"available": False, "error": "API key not configured"}
        resp = _requests.get(
            "https://www.alphavantage.co/query",
            params={"function": "EARNINGS_CALENDAR", "symbol": "AAPL", "horizon": "3month", "apikey": api_key},
            timeout=10,
        )
        if resp.status_code != 200:
            return {"available": False, "error": f"HTTP {resp.status_code}"}
        # Alpha Vantage returns HTTP 200 with JSON error body on failures
        try:
            body = resp.json()
            error_msg = body.get("Error Message") or body.get("Note") or body.get("Information")
            if error_msg:
                return {"available": False, "error": error_msg}
        except ValueError:
            pass  # Not JSON — likely valid CSV response
        return {"available": True, "error": None}
    except Exception as e:
        logger.debug("Alpha Vantage health check failed: %s", e)
        return {"available": False, "error": "Connection failed"}


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
        logger.debug("FRED health check failed: %s", e)
        return {"available": False, "error": "Connection failed"}


def _check_schwab() -> dict:
    """Check Schwab API by testing market data endpoint."""
    try:
        from app.services.schwab_auth import SchwabTokenManager
        mgr = SchwabTokenManager()
        if not mgr.is_configured():
            return {"available": False, "error": "Not configured"}
        import httpx
        token = mgr.get_access_token()
        resp = httpx.get(
            "https://api.schwabapi.com/marketdata/v1/markets?markets=equity",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        return {"available": resp.status_code == 200, "error": None}
    except Exception as e:
        logger.debug("Schwab health check failed: %s", e)
        return {"available": False, "error": "Connection failed"}


def _check_zillow() -> dict:
    """Check Zillow CSV availability via HEAD request."""
    try:
        resp = _requests.head(
            "https://files.zillowstatic.com/research/public_csvs/zhvi/Zip_zhvi_uf_sm_sa_month.csv",
            timeout=10,
        )
        return {"available": resp.status_code == 200, "error": None}
    except Exception as e:
        logger.debug("Zillow health check failed: %s", e)
        return {"available": False, "error": "Connection failed"}
