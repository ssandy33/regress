import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DBSession

from app.models.database import get_db
from app.models.schemas import OptionScanRequest, OptionScanResponse
from app.services.options_scanner import OptionScanner, OptionScannerError
from app.services.schwab_client import SchwabClient, SchwabClientError
from app.services.schwab_auth import SchwabAuthError
from app.utils.parsing import to_float, to_int

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
    earnings_date = scanner.get_earnings_date(ticker)
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
    except SchwabAuthError:
        raise
    except SchwabClientError:
        raise  # preserve fetch failures as-is

    call_map = chain_data.get("callExpDateMap", {})
    put_map = chain_data.get("putExpDateMap", {})

    # Determine available expirations
    all_exps = sorted(set(
        k.split(":")[0] for k in list(call_map.keys()) + list(put_map.keys())
    ))

    if not all_exps:
        raise OptionScannerError(f"No options available for '{ticker}'")

    target_exp = expiration or all_exps[0]
    if expiration and expiration not in all_exps:
        raise OptionScannerError(
            f"Expiration '{expiration}' not found for '{ticker}'. "
            f"Available: {', '.join(all_exps[:5])}{'...' if len(all_exps) > 5 else ''}"
        )

    def _map_to_records(exp_date_map: dict, target: str) -> list[dict]:
        records = []
        for exp_key, strikes_map in exp_date_map.items():
            if not exp_key.startswith(target):
                continue
            for _strike_str, contracts in strikes_map.items():
                if not contracts:
                    continue
                c = contracts[0]
                vol_raw = to_float(c.get("volatility"), None)
                records.append({
                    "strike": to_float(c.get("strikePrice")),
                    "bid": to_float(c.get("bid")),
                    "ask": to_float(c.get("ask")),
                    "volume": to_int(c.get("totalVolume")),
                    "openInterest": to_int(c.get("openInterest")),
                    "impliedVolatility": vol_raw / 100.0 if vol_raw else 0,
                    "delta": to_float(c.get("delta")),
                    "gamma": to_float(c.get("gamma")),
                    "theta": to_float(c.get("theta")),
                    "vega": to_float(c.get("vega")),
                })
        return sorted(records, key=lambda r: r["strike"])

    return {
        "ticker": ticker,
        "expiration": target_exp,
        "available_expirations": all_exps,
        "calls": _map_to_records(call_map, target_exp),
        "puts": _map_to_records(put_map, target_exp),
    }
