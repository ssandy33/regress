import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DBSession

from app.models.database import get_db
from app.models.schemas import OptionScanRequest, OptionScanResponse
from app.services.options_scanner import OptionScanner, OptionScannerError
from app.services.schwab_client import SchwabClient, SchwabClientError
from app.services.schwab_auth import SchwabAuthError

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
    earnings_date = scanner._get_earnings_date(ticker)
    return {"ticker": ticker, "earnings_date": earnings_date}


@router.get("/chain/{ticker}")
def get_option_chain(
    ticker: str,
    expiration: str = Query(None, description="Expiration date (YYYY-MM-DD)"),
):
    """Get raw option chain data for a ticker via Schwab."""
    client = SchwabClient()
    try:
        chain_data = client.get_option_chain(
            ticker,
            contract_type="ALL",
            from_date=expiration,
            to_date=expiration,
        )
    except (SchwabClientError, SchwabAuthError) as e:
        raise OptionScannerError(f"No options available for '{ticker}'") from e

    call_map = chain_data.get("callExpDateMap", {})
    put_map = chain_data.get("putExpDateMap", {})

    # Determine available expirations
    all_exps = sorted(set(
        k.split(":")[0] for k in list(call_map.keys()) + list(put_map.keys())
    ))

    if not all_exps:
        raise OptionScannerError(f"No options available for '{ticker}'")

    target_exp = expiration or all_exps[0]

    def _map_to_records(exp_date_map: dict, target: str) -> list[dict]:
        records = []
        for exp_key, strikes_map in exp_date_map.items():
            if not exp_key.startswith(target):
                continue
            for _strike_str, contracts in strikes_map.items():
                if not contracts:
                    continue
                c = contracts[0]
                records.append({
                    "strike": float(c.get("strikePrice", 0)),
                    "bid": float(c.get("bid", 0)),
                    "ask": float(c.get("ask", 0)),
                    "volume": int(c.get("totalVolume", 0)),
                    "openInterest": int(c.get("openInterest", 0)),
                    "impliedVolatility": float(c.get("volatility", 0)) / 100.0 if c.get("volatility") else 0,
                    "delta": float(c.get("delta", 0)),
                    "gamma": float(c.get("gamma", 0)),
                    "theta": float(c.get("theta", 0)),
                    "vega": float(c.get("vega", 0)),
                })
        return records

    return {
        "ticker": ticker,
        "expiration": target_exp,
        "available_expirations": all_exps,
        "calls": _map_to_records(call_map, target_exp),
        "puts": _map_to_records(put_map, target_exp),
    }
