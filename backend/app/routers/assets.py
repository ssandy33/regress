import logging

import requests as _requests
from fastapi import APIRouter

from app.models.schemas import AssetInfo, AssetSearchResponse
from app.services.data_fetcher import ASSET_REGISTRY, detect_source

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assets", tags=["assets"])

_YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


def _validate_ticker_yahoo(symbol: str) -> dict | None:
    """Validate a ticker via Yahoo Finance chart API. Returns {symbol, name} or None."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
        resp = _requests.get(url, headers=_YAHOO_HEADERS, timeout=5)
        if resp.status_code != 200:
            return None
        data = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return None
        meta = result[0].get("meta", {})
        if not meta.get("regularMarketPrice"):
            return None
        name = meta.get("shortName") or meta.get("longName") or symbol
        return {"symbol": meta.get("symbol", symbol), "name": name}
    except Exception:
        logger.debug(f"Yahoo chart validation failed for '{symbol}'")
        return None


def _search_yahoo(query: str) -> list[dict]:
    """Search Yahoo Finance for tickers matching a query string. Returns list of {symbol, name}."""
    try:
        url = "https://query2.finance.yahoo.com/v1/finance/search"
        params = {"q": query, "quotesCount": 5, "newsCount": 0, "listsCount": 0}
        resp = _requests.get(url, params=params, headers=_YAHOO_HEADERS, timeout=5)
        if resp.status_code != 200:
            return []
        data = resp.json()
        results = []
        for quote in data.get("quotes", []):
            symbol = quote.get("symbol")
            name = quote.get("shortname") or quote.get("longname") or symbol
            if symbol:
                results.append({"symbol": symbol, "name": name})
        return results
    except Exception:
        logger.debug(f"Yahoo search failed for '{query}'")
        return []


@router.get("/search", response_model=AssetSearchResponse)
def search_assets(q: str, offline: bool = False):
    """Search for assets by name, identifier, or category."""
    query = q.lower().strip()
    if not query:
        return AssetSearchResponse(results=[])

    results = []
    seen_identifiers = set()

    # 1. Registry matches
    for asset in ASSET_REGISTRY:
        if (
            query in asset["identifier"].lower()
            or query in asset["name"].lower()
            or query in asset["category"].lower()
        ):
            results.append(AssetInfo(**asset))
            seen_identifiers.add(asset["identifier"].upper())

    if offline:
        # When offline, offer raw query as unverified ticker if no registry match
        ticker_symbol = q.upper().strip()
        if ticker_symbol not in seen_identifiers and len(ticker_symbol) <= 6 and ticker_symbol.isalpha():
            results.append(
                AssetInfo(
                    identifier=ticker_symbol,
                    name=f"{ticker_symbol} (cached/unverified)",
                    source=detect_source(ticker_symbol),
                    category="stock",
                )
            )
        return AssetSearchResponse(results=results)

    # 2. Always try to validate the raw query as a ticker symbol
    ticker_symbol = q.upper().strip()
    if ticker_symbol not in seen_identifiers and len(ticker_symbol) <= 6 and ticker_symbol.isalnum():
        validated = _validate_ticker_yahoo(ticker_symbol)
        if validated:
            results.insert(0, AssetInfo(
                identifier=validated["symbol"],
                name=validated["name"],
                source=detect_source(validated["symbol"]),
                category="stock",
            ))
            seen_identifiers.add(validated["symbol"].upper())

    # 3. Search Yahoo Finance for company name -> ticker resolution
    #    (e.g. "Ford" -> "F", "Apple" -> "AAPL")
    if len(query) >= 2:
        search_results = _search_yahoo(q.strip())
        for sr in search_results:
            if sr["symbol"].upper() not in seen_identifiers:
                results.append(AssetInfo(
                    identifier=sr["symbol"],
                    name=sr["name"],
                    source=detect_source(sr["symbol"]),
                    category="stock",
                ))
                seen_identifiers.add(sr["symbol"].upper())

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
