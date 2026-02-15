import logging
import os
import threading
from contextlib import asynccontextmanager

# Fix macOS SSL certificate issue
import certifi
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.models.database import init_db, SessionLocal
from app.routers import assets, data, health, regression, sessions, settings
from app.services.backup import create_backup
from app.services.cache import CacheService
from app.services.data_fetcher import DataFetcher, DataFetchError, InvalidTickerError, DataAlignmentError

logger = logging.getLogger(__name__)

# Common assets to pre-cache on startup
PRE_CACHE_ASSETS = ["^GSPC", "GC=F", "DGS10", "CSUSHPINSA"]


def _pre_cache_common_assets():
    """Background task to pre-cache commonly used assets."""
    try:
        db = SessionLocal()
        cache = CacheService(db)
        fetcher = DataFetcher(cache)
        from datetime import datetime, timedelta
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")

        for asset in PRE_CACHE_ASSETS:
            try:
                fetcher.fetch(asset, start, end)
                logger.info(f"Pre-cached: {asset}")
            except Exception as e:
                logger.warning(f"Pre-cache failed for {asset}: {e}")
        db.close()
    except Exception as e:
        logger.warning(f"Pre-cache task failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    # Create startup backup
    try:
        backup_name = create_backup()
        if backup_name:
            logger.info(f"Startup backup created: {backup_name}")
    except Exception as e:
        logger.warning(f"Startup backup failed: {e}")

    yield


app = FastAPI(
    title="Financial Regression Analysis Tool",
    description="Backend API for financial data fetching, caching, and regression analysis",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(assets.router)
app.include_router(data.router)
app.include_router(regression.router)
app.include_router(sessions.router)
app.include_router(settings.router)
app.include_router(health.router)


# --- Exception handlers ---


@app.exception_handler(DataFetchError)
async def data_fetch_error_handler(request: Request, exc: DataFetchError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(InvalidTickerError)
async def invalid_ticker_error_handler(request: Request, exc: InvalidTickerError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(DataAlignmentError)
async def data_alignment_error_handler(request: Request, exc: DataAlignmentError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# --- Health check ---


@app.get("/api/health")
def health_check():
    return {"status": "ok"}
