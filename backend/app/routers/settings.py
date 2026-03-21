import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, quote, urlparse

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import func, text

from app.config import settings, get_fred_api_key
from app.services.schwab_auth import (
    SCHWAB_AUTHORIZE_URL,
    SCHWAB_REDIRECT_URI,
    SCHWAB_TOKEN_URL,
    SchwabTokenManager,
    _upsert_setting,
)
from app.models.database import AppSetting, CacheEntry, get_db
from app.models.schemas import CacheStatsResponse, SettingUpdate, SettingsResponse
from app.services.backup import create_backup, list_backups, restore_backup

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
def get_settings(db: DBSession = Depends(get_db)):
    """Get current application settings."""
    fred_key = get_fred_api_key()

    # Read optional DB settings with defaults
    def _get(key: str, default: str) -> str:
        entry = db.query(AppSetting).filter(AppSetting.key == key).first()
        return entry.value if entry else default

    schwab_mgr = SchwabTokenManager()
    return SettingsResponse(
        fred_api_key_set=bool(fred_key),
        cache_ttl_daily_hours=int(_get("cache_ttl_daily_hours", str(settings.cache_ttl_daily_hours))),
        cache_ttl_monthly_days=int(_get("cache_ttl_monthly_days", str(settings.cache_ttl_monthly_days))),
        default_date_range_years=int(_get("default_date_range_years", "5")),
        theme=_get("theme", "system"),
        schwab_configured=schwab_mgr.is_configured(),
        schwab_token_expires=schwab_mgr.get_refresh_token_expiry(),
    )


@router.put("")
def update_setting(req: SettingUpdate, db: DBSession = Depends(get_db)):
    """Update a single application setting."""
    entry = db.query(AppSetting).filter(AppSetting.key == req.key).first()
    if entry:
        entry.value = req.value
    else:
        entry = AppSetting(key=req.key, value=req.value)
        db.add(entry)
    db.commit()
    return {"status": "ok", "key": req.key}


@router.get("/cache", response_model=CacheStatsResponse)
def get_cache_stats(db: DBSession = Depends(get_db)):
    """Get cache statistics."""
    entries = db.query(CacheEntry).all()
    total_size = sum(len(e.data.encode()) for e in entries)

    entry_list = [
        {
            "asset_key": e.asset_key,
            "source": e.source_name,
            "frequency": e.source_frequency,
            "fetched_at": e.fetched_at,
            "size_bytes": len(e.data.encode()),
        }
        for e in entries
    ]

    return CacheStatsResponse(
        entry_count=len(entries),
        total_size_bytes=total_size,
        entries=entry_list,
    )


@router.delete("/cache")
def clear_cache(db: DBSession = Depends(get_db)):
    """Clear all cached data."""
    db.query(CacheEntry).delete()
    db.commit()
    return {"status": "ok", "message": "Cache cleared"}


@router.get("/health/fred")
def check_fred_key():
    """Check if FRED API key is configured and valid."""
    key = get_fred_api_key()
    if not key:
        return {"configured": False, "valid": False}

    try:
        from fredapi import Fred
        fred = Fred(api_key=key)
        fred.get_series("DGS10", observation_start="2024-01-01", observation_end="2024-01-02")
        return {"configured": True, "valid": True}
    except Exception:
        return {"configured": True, "valid": False}


@router.get("/health/schwab")
def check_schwab_connection():
    """Check if Schwab API is configured and token is valid."""
    schwab_mgr = SchwabTokenManager()
    if not schwab_mgr.is_configured():
        return {"configured": False, "valid": False, "error": None, "token_expiry": None}

    # Build token expiry info
    token_expiry = None
    expiry_str = schwab_mgr.get_refresh_token_expiry()
    if expiry_str:
        try:
            expires = datetime.fromisoformat(expiry_str)
            hours_remaining = (expires - datetime.now(timezone.utc)).total_seconds() / 3600
            token_expiry = {
                "refresh_token_expires": expiry_str,
                "hours_remaining": round(hours_remaining, 1),
                "warning": hours_remaining <= 48,
                "expired": hours_remaining <= 0,
            }
        except (ValueError, TypeError):
            pass

    try:
        import httpx
        token = schwab_mgr.get_access_token()
        resp = httpx.get(
            "https://api.schwabapi.com/marketdata/v1/markets?markets=equity",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        resp.raise_for_status()
        return {"configured": True, "valid": True, "error": None, "token_expiry": token_expiry}
    except httpx.HTTPStatusError as e:
        return {"configured": True, "valid": False, "error": f"HTTP {e.response.status_code}", "token_expiry": token_expiry}
    except httpx.RequestError:
        return {"configured": True, "valid": False, "error": "Connection failed", "token_expiry": token_expiry}
    except Exception as e:
        logger.debug("Schwab health check failed: %s", e)
        return {"configured": True, "valid": False, "error": "Validation failed", "token_expiry": token_expiry}


# --- Schwab OAuth Setup ---


class SchwabAuthUrlRequest(BaseModel):
    app_key: str


class SchwabCallbackRequest(BaseModel):
    app_key: str
    app_secret: str
    callback_url: str


@router.post("/schwab/auth-url")
def get_schwab_auth_url(req: SchwabAuthUrlRequest):
    """Generate the Schwab OAuth authorization URL."""
    if not req.app_key.strip():
        return JSONResponse(status_code=422, content={"detail": "App key is required"})

    auth_url = (
        f"{SCHWAB_AUTHORIZE_URL}"
        f"?response_type=code"
        f"&client_id={req.app_key.strip()}"
        f"&redirect_uri={quote(SCHWAB_REDIRECT_URI, safe='')}"
    )
    return {"auth_url": auth_url, "redirect_uri": SCHWAB_REDIRECT_URI}


@router.post("/schwab/callback")
def exchange_schwab_callback(req: SchwabCallbackRequest, db: DBSession = Depends(get_db)):
    """Exchange the OAuth callback URL for tokens and store them."""
    parsed = urlparse(req.callback_url.strip())
    qs = parse_qs(parsed.query)
    code = qs.get("code", [None])[0]
    if not code:
        return JSONResponse(
            status_code=422,
            content={"detail": "Could not extract authorization code from callback URL"},
        )

    app_key = req.app_key.strip()
    app_secret = req.app_secret.strip()

    try:
        resp = httpx.post(
            SCHWAB_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": SCHWAB_REDIRECT_URI,
            },
            auth=(app_key, app_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error("Schwab token exchange failed: %s", e)
        return JSONResponse(
            status_code=502,
            content={"detail": "Token exchange failed. Check your App Key and Secret."},
        )
    except httpx.RequestError:
        return JSONResponse(
            status_code=502,
            content={"detail": "Unable to reach Schwab API. Please try again."},
        )

    token_data = resp.json()
    if "access_token" not in token_data or "refresh_token" not in token_data:
        return JSONResponse(
            status_code=502,
            content={"detail": "Unexpected response from Schwab. Missing token fields."},
        )

    now = datetime.now(timezone.utc)
    access_expires = now.replace(microsecond=0) + timedelta(
        seconds=token_data.get("expires_in", 1800)
    )
    refresh_expires = now.replace(microsecond=0) + timedelta(days=7)

    _upsert_setting(db, "schwab_app_key", app_key)
    _upsert_setting(db, "schwab_app_secret", app_secret)
    _upsert_setting(db, "schwab_access_token", token_data["access_token"])
    _upsert_setting(db, "schwab_refresh_token", token_data["refresh_token"])
    _upsert_setting(db, "schwab_access_token_expires", access_expires.isoformat())
    _upsert_setting(db, "schwab_refresh_token_expires", refresh_expires.isoformat())
    db.commit()

    # Clear cached token in the singleton so it picks up the new one
    SchwabTokenManager().invalidate_token()

    logger.info("Schwab tokens stored via settings UI, access expires %s", access_expires.isoformat())
    return {
        "status": "ok",
        "access_token_expires": access_expires.isoformat(),
        "refresh_token_expires": refresh_expires.isoformat(),
    }


# --- Backups ---


@router.get("/backups")
def get_backups():
    """List available database backups."""
    return {"backups": list_backups()}


@router.post("/backups/restore")
def restore_from_backup(filename: str):
    """Restore database from a backup file. Live swap, no restart needed."""
    try:
        restore_backup(filename)
        return {"status": "ok", "message": f"Restored from {filename}"}
    except FileNotFoundError:
        return JSONResponse(
            status_code=404, content={"detail": f"Backup '{filename}' not found"}
        )
    except Exception as e:
        logger.error("Backup restore failed: %s", e)
        return JSONResponse(status_code=500, content={"detail": "Backup restore failed"})


# --- Cache Freshness ---


@router.get("/cache/freshness")
def get_cache_freshness(db: DBSession = Depends(get_db)):
    """Get detailed cache freshness for all cached assets."""
    entries = db.query(CacheEntry).all()
    now = datetime.now(timezone.utc)

    result = []
    for e in entries:
        try:
            fetched_at = datetime.fromisoformat(e.fetched_at)
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
            age_days = (now - fetched_at).days
        except (ValueError, TypeError):
            age_days = 999

        freshness = "fresh" if age_days < 30 else "stale" if age_days < 90 else "very_stale"

        result.append({
            "asset_key": e.asset_key,
            "source": e.source_name,
            "frequency": e.source_frequency,
            "fetched_at": e.fetched_at,
            "age_days": age_days,
            "size_bytes": len(e.data.encode()) if e.data else 0,
            "freshness": freshness,
        })

    return {"entries": result}


@router.post("/cache/refresh-all")
def refresh_all_cache(db: DBSession = Depends(get_db)):
    """Re-fetch all cached assets from their sources."""
    from app.services.cache import CacheService
    from app.services.data_fetcher import DataFetcher

    cache = CacheService(db)
    fetcher = DataFetcher(cache)
    entries = db.query(CacheEntry).all()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    results = []
    for e in entries:
        if e.asset_key == "zillow:__csv__":
            continue
        try:
            identifier = e.asset_key.split(":", 1)[1]
            db.delete(e)
            db.commit()
            fetcher.fetch(identifier, "2000-01-01", now_str)
            results.append({"asset_key": e.asset_key, "status": "refreshed"})
        except Exception as ex:
            logger.warning("Cache refresh failed for %s: %s", e.asset_key, ex)
            results.append({"asset_key": e.asset_key, "status": "failed", "error": "Refresh failed"})

    return {"results": results}


@router.post("/cache/refresh-stale")
def refresh_stale_cache(db: DBSession = Depends(get_db)):
    """Re-fetch only stale cached assets (>30 days old)."""
    from app.services.cache import CacheService
    from app.services.data_fetcher import DataFetcher

    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d")
    cache = CacheService(db)
    fetcher = DataFetcher(cache)
    entries = db.query(CacheEntry).all()

    results = []
    for e in entries:
        if e.asset_key == "zillow:__csv__":
            continue
        try:
            fetched_at = datetime.fromisoformat(e.fetched_at)
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
            age_days = (now - fetched_at).days
        except (ValueError, TypeError):
            age_days = 999

        if age_days < 30:
            continue

        try:
            identifier = e.asset_key.split(":", 1)[1]
            db.delete(e)
            db.commit()
            fetcher.fetch(identifier, "2000-01-01", now_str)
            results.append({"asset_key": e.asset_key, "status": "refreshed"})
        except Exception as ex:
            logger.warning("Stale cache refresh failed for %s: %s", e.asset_key, ex)
            results.append({"asset_key": e.asset_key, "status": "failed", "error": "Refresh failed"})

    return {"results": results}
