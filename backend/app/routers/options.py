import logging

import yfinance as yf
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DBSession

from app.models.database import get_db
from app.models.schemas import OptionScanRequest, OptionScanResponse
from app.services.cache import CacheService
from app.services.options_scanner import OptionScanner, OptionScannerError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/options", tags=["options"])


def _get_scanner(db: DBSession = Depends(get_db)) -> OptionScanner:
    return OptionScanner()


@router.post("/scan", response_model=OptionScanResponse)
def scan_options(
    req: OptionScanRequest,
    scanner: OptionScanner = Depends(_get_scanner),
):
    """Scan option chain for wheel strategy opportunities."""
    return scanner.scan(req)


@router.get("/earnings/{ticker}")
def get_earnings(ticker: str):
    """Get next earnings date for a ticker."""
    scanner = OptionScanner()
    ticker_obj = yf.Ticker(ticker)
    earnings_date = scanner._get_earnings_date(ticker_obj)
    return {"ticker": ticker, "earnings_date": earnings_date}


@router.get("/chain/{ticker}")
def get_option_chain(
    ticker: str,
    expiration: str = Query(None, description="Expiration date (YYYY-MM-DD)"),
):
    """Get raw option chain data for a ticker."""
    ticker_obj = yf.Ticker(ticker)

    try:
        expirations = ticker_obj.options
    except Exception:
        raise OptionScannerError(f"No options available for '{ticker}'")

    if not expirations:
        raise OptionScannerError(f"No options available for '{ticker}'")

    if expiration and expiration not in expirations:
        raise ValueError(
            f"Expiration {expiration} not available. "
            f"Available: {', '.join(expirations[:10])}"
        )

    target_exp = expiration or expirations[0]
    chain = ticker_obj.option_chain(target_exp)

    def _df_to_records(df):
        records = []
        for _, row in df.iterrows():
            records.append({
                "strike": float(row["strike"]),
                "bid": float(row.get("bid", 0) or 0),
                "ask": float(row.get("ask", 0) or 0),
                "volume": int(row.get("volume", 0) or 0),
                "openInterest": int(row.get("openInterest", 0) or 0),
                "impliedVolatility": float(row.get("impliedVolatility", 0) or 0),
            })
        return records

    return {
        "ticker": ticker,
        "expiration": target_exp,
        "available_expirations": list(expirations),
        "calls": _df_to_records(chain.calls),
        "puts": _df_to_records(chain.puts),
    }
