import logging
import os
import threading
from contextlib import asynccontextmanager

# Fix macOS SSL certificate issue
import certifi
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth import get_current_user
from app.config import settings as app_settings
from app.models.database import init_db, SessionLocal
from app.routers import assets, data, health, options, regression, sessions, settings
from app.services.backup import create_backup
from app.services.cache import CacheService
from app.services.data_fetcher import DataFetcher, DataFetchError, InvalidTickerError, DataAlignmentError
from app.services.options_scanner import OptionScannerError
from app.services.schwab_auth import SchwabAuthError

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

# CORS — restrict to configured origins (default: localhost dev servers)
# In production behind Caddy, requests are same-origin so CORS is not needed.
# Override with CORS_ORIGINS env var: CORS_ORIGINS="https://mysite.com,https://www.mysite.com"
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in app_settings.cors_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

# Include routers — health is public, all others require authentication
app.include_router(health.router)
app.include_router(assets.router, dependencies=[Depends(get_current_user)])
app.include_router(data.router, dependencies=[Depends(get_current_user)])
app.include_router(regression.router, dependencies=[Depends(get_current_user)])
app.include_router(sessions.router, dependencies=[Depends(get_current_user)])
app.include_router(settings.router, dependencies=[Depends(get_current_user)])
app.include_router(options.router, dependencies=[Depends(get_current_user)])


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


@app.exception_handler(OptionScannerError)
async def option_scanner_error_handler(request: Request, exc: OptionScannerError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(SchwabAuthError)
async def schwab_auth_error_handler(request: Request, exc: SchwabAuthError):
    return JSONResponse(status_code=401, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# --- Health check ---


@app.get("/api/health")
def health_check():
    return {"status": "ok"}
