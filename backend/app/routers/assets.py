import logging

from fastapi import APIRouter

from app.models.schemas import AssetInfo, AssetSearchResponse
from app.services.data_fetcher import ASSET_REGISTRY

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.get("/search", response_model=AssetSearchResponse)
def search_assets(q: str, offline: bool = False):
    """Search for assets by name, identifier, or category."""
    query = q.lower().strip()
    if not query:
        return AssetSearchResponse(results=[])

    results = []
    for asset in ASSET_REGISTRY:
        if (
            query in asset["identifier"].lower()
            or query in asset["name"].lower()
            or query in asset["category"].lower()
        ):
            results.append(AssetInfo(**asset))

    # If no match in registry, try yfinance validation (skip when offline)
    if not results and not offline:
        validated = False
        ticker_symbol = q.upper().strip()

        # Attempt 1: fast_info (lightweight, less likely to be rate-limited)
        try:
            import yfinance as yf
            ticker = yf.Ticker(ticker_symbol)
            fi = ticker.fast_info
            last_price = fi.get("lastPrice")
            if last_price is not None and last_price > 0:
                validated = True
                results.append(
                    AssetInfo(
                        identifier=ticker_symbol,
                        name=ticker_symbol,
                        source="yfinance",
                        category="stock",
                    )
                )
        except Exception:
            logger.debug(f"yfinance fast_info failed for '{q}'")

        # Attempt 2: ticker.info for name resolution
        if validated:
            try:
                info = ticker.info
                name = info.get("shortName") or info.get("longName")
                if name:
                    results[-1] = AssetInfo(
                        identifier=ticker_symbol,
                        name=name,
                        source="yfinance",
                        category="stock",
                    )
            except Exception:
                pass  # Keep the result from fast_info

        # Attempt 3: If both failed, still offer the ticker as unverified
        # so users can try it — actual validation happens at data fetch time
        if not validated and len(ticker_symbol) <= 6 and ticker_symbol.isalpha():
            results.append(
                AssetInfo(
                    identifier=ticker_symbol,
                    name=f"{ticker_symbol} (unverified)",
                    source="yfinance",
                    category="stock",
                )
            )

    # When offline and no registry match, offer ticker as unverified
    if not results and offline:
        ticker_symbol = q.upper().strip()
        if len(ticker_symbol) <= 6 and ticker_symbol.isalpha():
            results.append(
                AssetInfo(
                    identifier=ticker_symbol,
                    name=f"{ticker_symbol} (cached/unverified)",
                    source="yfinance",
                    category="stock",
                )
            )

    return AssetSearchResponse(results=results)


@router.get("/case-shiller")
def list_case_shiller():
    """List all Case-Shiller metro indices."""
    metros = [a for a in ASSET_REGISTRY if "Case-Shiller" in a["name"]]
    return {"metros": metros}


@router.get("/suggest")
def suggest_tickers(q: str):
    """Suggest similar tickers when a search fails."""
    query = q.upper().strip()
    suggestions = []

    # Check registry for close matches
    for asset in ASSET_REGISTRY:
        identifier = asset["identifier"].upper()
        name = asset["name"].upper()
        # Simple similarity: shared prefix or substring
        if (
            identifier.startswith(query[:2])
            or query[:3] in name
            or query in identifier
        ):
            suggestions.append(AssetInfo(**asset))

    return {"query": q, "suggestions": suggestions[:5]}
