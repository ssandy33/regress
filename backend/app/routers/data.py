from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DBSession

from app.models.database import get_db
from app.models.schemas import DataPoint, HistoricalDataResponse
from app.services.cache import CacheService
from app.services.data_fetcher import DataFetcher

router = APIRouter(prefix="/api/data", tags=["data"])


def _get_fetcher(db: DBSession = Depends(get_db)) -> DataFetcher:
    return DataFetcher(CacheService(db))


@router.get("/zillow/{zip_code}", response_model=HistoricalDataResponse)
def get_zillow_data(
    zip_code: str,
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
    fetcher: DataFetcher = Depends(_get_fetcher),
):
    """Fetch Zillow ZHVI data for a zip code."""
    df, meta = fetcher.fetch_zillow(zip_code, start, end)

    data = [
        DataPoint(date=idx.strftime("%Y-%m-%d"), value=float(row["value"]))
        for idx, row in df.iterrows()
    ]

    return HistoricalDataResponse(data=data, data_meta=meta)


@router.get("/{ticker}", response_model=HistoricalDataResponse)
def get_historical_data(
    ticker: str,
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
    fetcher: DataFetcher = Depends(_get_fetcher),
):
    """Fetch historical data for a ticker. Auto-detects source (FRED or Schwab)."""
    df, meta = fetcher.fetch(ticker, start, end)

    data = [
        DataPoint(date=idx.strftime("%Y-%m-%d"), value=float(row["value"]))
        for idx, row in df.iterrows()
    ]

    return HistoricalDataResponse(data=data, data_meta=meta)
