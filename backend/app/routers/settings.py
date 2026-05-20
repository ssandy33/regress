import json
import logging
import math
import os
from dataclasses import asdict
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import func, text

from app.config import settings, get_fred_api_key
from app.services.schwab_auth import (
    SCHWAB_AUTHORIZE_URL,
    SCHWAB_OAUTH_SCOPE,
    SCHWAB_REDIRECT_URI,
    SCHWAB_TOKEN_URL,
    SchwabAuthError,
    SchwabTokenManager,
    store_schwab_tokens,
)
from app.services.schwab_client import SchwabClientError
from app.models.database import AppSetting, CacheEntry, get_db
from app.models.schemas import CacheStatsResponse, SettingUpdate, SettingsResponse
from app.services.backup import create_backup, list_backups, restore_backup
from app.services.rules_config import (
    RULES_CONFIG_KEY,
    RULES_CONFIG_SCHEMA_VERSION,
    SIZING_CAP_MIGRATION_KEY,
    RulesConfig,
    load_rules_config,
)
from app.services.schwab_account_value import (
    AccountValueResult,
    get_account_value,
    get_cached_account_value,
)

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

    # Target yield (#207). Stored as a fraction string in the flat
    # `okr_target_yield` app_settings row; parse defensively to float|None so a
    # malformed row never breaks the settings read (same pattern as
    # positions.py's OKR read). This flat key migrates into the typed
    # `okr_config` namespace in V1.1 (ADR-001 / Discussion #210).
    target_raw = _get("okr_target_yield", "")
    try:
        target_yield = float(target_raw) if target_raw not in (None, "") else None
    except (TypeError, ValueError):
        target_yield = None

    schwab_mgr = SchwabTokenManager()
    return SettingsResponse(
        fred_api_key_set=bool(fred_key),
        cache_ttl_daily_hours=int(_get("cache_ttl_daily_hours", str(settings.cache_ttl_daily_hours))),
        cache_ttl_monthly_days=int(_get("cache_ttl_monthly_days", str(settings.cache_ttl_monthly_days))),
        default_date_range_years=int(_get("default_date_range_years", "5")),
        theme=_get("theme", "system"),
        schwab_configured=schwab_mgr.is_configured(),
        schwab_token_expires=schwab_mgr.get_refresh_token_expiry(),
        okr_target_yield=target_yield,
    )


# Generic error copy for the okr_target_yield boundary check — never leak the
# raw parse exception (CLAUDE.md).
_TARGET_YIELD_ERROR = "Target yield must be between 0% and 100%."


@router.put("")
def update_setting(req: SettingUpdate, db: DBSession = Depends(get_db)):
    """Update a single application setting.

    The store is a generic `{key, value}` upsert. `okr_target_yield` (#207) is
    the one key with a value contract — it is a fraction in `0.0 < x <= 1.0`
    consumed by the Recovery Plan engine — so it gets a boundary check here.
    This flat key migrates into the typed `okr_config` namespace in V1.1
    (ADR-001 / Discussion #210).
    """
    if req.key == "okr_target_yield":
        try:
            value = float(req.value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=_TARGET_YIELD_ERROR)
        if math.isnan(value) or math.isinf(value):
            raise HTTPException(status_code=422, detail=_TARGET_YIELD_ERROR)
        if not (0.0 < value <= 1.0):
            raise HTTPException(status_code=422, detail=_TARGET_YIELD_ERROR)

    entry = db.query(AppSetting).filter(AppSetting.key == req.key).first()
    if entry:
        entry.value = req.value
    else:
        entry = AppSetting(key=req.key, value=req.value)
        db.add(entry)
    db.commit()
    return {"status": "ok", "key": req.key}


# --- Trading Rules config (issue #158 — edit surface for the #156 keystone) ---


# Generic, sanitised copy returned when a Schwab call fails out of the
# account-value endpoints. Per CLAUDE.md, no raw exception text reaches the
# client; the structured failure modes (disconnected / expired / error) are
# surfaced INSIDE the AccountValueResult payload, while an unexpected raise
# from the W-A service is mapped to a 503 with this detail.
_SCHWAB_UNAVAILABLE_DETAIL = "Schwab service unavailable"


def _read_sizing_cap_migration(db: DBSession) -> dict | None:
    """Read the one-time sizing-cap migration marker from ``app_settings``.

    Returns the decoded JSON payload (with ``previous_sizing_cap_dollars``,
    ``migrated_at``, ``dismissed_at`` keys) or ``None`` when no migration has
    happened on this DB. A malformed row is also treated as ``None`` —
    callers fall through to "no migration banner" rather than 500.
    """
    entry = (
        db.query(AppSetting)
        .filter(AppSetting.key == SIZING_CAP_MIGRATION_KEY)
        .first()
    )
    if entry is None or not entry.value:
        return None
    try:
        parsed = json.loads(entry.value)
    except (json.JSONDecodeError, ValueError, TypeError):
        logger.warning(
            "Stored %s row is not valid JSON; surfacing as no-migration.",
            SIZING_CAP_MIGRATION_KEY,
        )
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


@router.get("/rules")
def get_rules_config(db: DBSession = Depends(get_db)):
    """Get the Trading Rules config plus the sizing-cap migration status.

    Backed by :func:`app.services.rules_config.load_rules_config`, which
    merges any stored ``rules_config`` row over the typed defaults and never
    raises — so this endpoint always returns a complete, valid config.

    **S4 augmentation (issue #234 / V1 contract):** the response carries an
    extra ``migration`` sibling key alongside the existing flat
    :class:`RulesConfig` fields. The frontend banner that announces the
    v1 → v2 sizing-cap migration reads ``migration.sizing_cap`` to decide
    whether to render the dismissible "we changed dollars → percent"
    callout. The migration object is ``null`` when no migration has happened
    on this DB; otherwise it carries the previous dollar value, the
    migration timestamp, and the ``dismissed_at`` timestamp (or ``null``
    when the banner has not been dismissed yet).

    Shape::

        {
          "schema_version": 2,
          "universe": {...},
          "entry":    {...},
          "position": {...},
          "risk":     {...},
          "management": {...},
          "migration": {
            "sizing_cap": null | {
              "previous_sizing_cap_dollars": <float | null>,
              "migrated_at": "<iso8601>",
              "dismissed_at": "<iso8601>" | null
            }
          }
        }
    """
    rules = load_rules_config(db)
    migration = _read_sizing_cap_migration(db)
    payload = rules.model_dump()
    payload["migration"] = {"sizing_cap": migration}
    return payload


@router.put("/rules", response_model=RulesConfig)
def update_rules_config(config: RulesConfig, db: DBSession = Depends(get_db)):
    """Persist the Trading Rules config.

    FastAPI validates the body against :class:`RulesConfig` (the same Pydantic
    model the engines read), so out-of-range values are rejected with a 422
    before anything is written. The validated config is stored as a single
    JSON document in the ``app_settings`` row keyed ``rules_config``.
    """
    # Re-stamp the schema version so a client cannot persist a stale value.
    config = config.model_copy(update={"schema_version": RULES_CONFIG_SCHEMA_VERSION})
    payload = config.model_dump_json()

    entry = db.query(AppSetting).filter(AppSetting.key == RULES_CONFIG_KEY).first()
    if entry:
        entry.value = payload
    else:
        entry = AppSetting(key=RULES_CONFIG_KEY, value=payload)
        db.add(entry)
    db.commit()
    return config


@router.post("/rules/migration/sizing-cap/dismiss")
def dismiss_sizing_cap_migration(db: DBSession = Depends(get_db)):
    """Mark the sizing-cap migration banner as dismissed.

    Stamps the ``dismissed_at`` field on the one-time
    ``sizing_cap_migration`` marker row to ``datetime.utcnow().isoformat()``.
    Idempotent — a second call simply re-stamps ``dismissed_at`` to the new
    timestamp and returns the same migration object.

    Returns the updated migration object (the same shape carried by
    ``GET /api/settings/rules`` under ``migration.sizing_cap``). When no
    migration has happened on this DB at all the call is a no-op and
    returns ``{"sizing_cap": null}`` — the UI never asks to dismiss a
    banner that never existed, but we surface a 200 either way to keep the
    endpoint truly idempotent.
    """
    entry = (
        db.query(AppSetting)
        .filter(AppSetting.key == SIZING_CAP_MIGRATION_KEY)
        .first()
    )
    if entry is None or not entry.value:
        return {"sizing_cap": None}

    try:
        parsed = json.loads(entry.value)
    except (json.JSONDecodeError, ValueError, TypeError):
        # A malformed row is indistinguishable from "no marker" for the
        # banner; surface as no-op. We deliberately don't repair the row
        # here — load_rules_config already tolerates it as missing.
        logger.warning(
            "Stored %s row is not valid JSON; dismiss is a no-op.",
            SIZING_CAP_MIGRATION_KEY,
        )
        return {"sizing_cap": None}

    if not isinstance(parsed, dict):
        return {"sizing_cap": None}

    parsed["dismissed_at"] = datetime.now(timezone.utc).isoformat()
    entry.value = json.dumps(parsed)
    db.commit()
    return {"sizing_cap": parsed}


# --- Schwab account-value endpoints (issue #234 — V1 contract §6.3) ---


def _serialise_account_value(result: AccountValueResult) -> dict:
    """Project an :class:`AccountValueResult` into a JSON-ready dict.

    ``cached_at`` is a ``datetime``; FastAPI's default JSON encoder handles
    it, but we coerce to an ISO string explicitly so the response shape is
    identical whether we hand back ``asdict(result)`` or a dict assembled by
    other code paths.
    """
    payload = asdict(result)
    cached_at = result.cached_at
    if isinstance(cached_at, datetime):
        payload["cached_at"] = cached_at.isoformat()
    return payload


@router.get("/account-value")
def get_account_value_endpoint(db: DBSession = Depends(get_db)):
    """Return the cached Schwab account-value result.

    Reads ``rules.position.sizing_cap_account`` to pick the right cache
    bucket, then calls :func:`get_cached_account_value` (cache-hit-only;
    NEVER makes a network call). On a cold cache (first GET after a server
    restart) the implementation falls through to
    :func:`get_account_value` with ``force_refresh=False`` ONCE so the user
    doesn't have to hit "Refresh" to populate the very first read. Every
    subsequent GET hits the cache for free.

    Errors are sanitised per CLAUDE.md: a raised
    :class:`SchwabAuthError` / :class:`SchwabClientError` becomes a 503
    with a generic detail; the W-A service's structured failure modes
    (``status="disconnected" | "expired" | "error"``) are surfaced INSIDE
    the JSON body with a 200, because they are typed-success states that
    carry per-status UI affordances on the frontend.
    """
    rules = load_rules_config(db)
    sizing_cap_account = rules.position.sizing_cap_account

    try:
        cached = get_cached_account_value(db, sizing_cap_account=sizing_cap_account)
        if cached is not None:
            return _serialise_account_value(cached)
        # Cold cache fall-through: one ordinary fetch to warm both tiers.
        result = get_account_value(
            db,
            force_refresh=False,
            sizing_cap_account=sizing_cap_account,
        )
    except SchwabAuthError as exc:
        # The W-A service never raises on auth errors — every auth failure
        # is mapped to status="disconnected" / "expired" / "error" on the
        # returned dataclass. This branch exists as defence in depth: if a
        # future refactor lets one through we still degrade cleanly.
        logger.warning("Schwab auth error in /account-value: code=%s", exc.code)
        raise HTTPException(status_code=503, detail=_SCHWAB_UNAVAILABLE_DETAIL)
    except SchwabClientError:
        logger.warning("Schwab transport error in /account-value")
        raise HTTPException(status_code=503, detail=_SCHWAB_UNAVAILABLE_DETAIL)

    return _serialise_account_value(result)


@router.post("/account-value/refresh")
def refresh_account_value(db: DBSession = Depends(get_db)):
    """Force a fresh Schwab account-value fetch.

    Calls :func:`get_account_value` with ``force_refresh=True`` so the W-A
    service bypasses both the hot in-memory cache and the durable
    ``app_settings`` cache and makes a Schwab round-trip. Per refinement
    **S2** of the parallel-execution plan, the W-A service falls through
    to a fresh hot-cache entry with ``status="ok"`` when the network call
    fails BUT a fresh cached value still exists — this endpoint surfaces
    that exact result without remapping the status. The "Refresh"
    affordance never flips a good cache to "error" on a transient blip.

    Same error sanitisation as ``GET /account-value`` — a raised Schwab
    auth/client exception becomes a 503 with a generic detail; structured
    statuses ride inside the 200 body.
    """
    rules = load_rules_config(db)
    sizing_cap_account = rules.position.sizing_cap_account

    try:
        result = get_account_value(
            db,
            force_refresh=True,
            sizing_cap_account=sizing_cap_account,
        )
    except SchwabAuthError as exc:
        logger.warning("Schwab auth error in /account-value/refresh: code=%s", exc.code)
        raise HTTPException(status_code=503, detail=_SCHWAB_UNAVAILABLE_DETAIL)
    except SchwabClientError:
        logger.warning("Schwab transport error in /account-value/refresh")
        raise HTTPException(status_code=503, detail=_SCHWAB_UNAVAILABLE_DETAIL)

    return _serialise_account_value(result)


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
        f"&client_id={quote(req.app_key.strip(), safe='')}"
        f"&scope={SCHWAB_OAUTH_SCOPE}"
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

    logger.info("Schwab granted scope: %s", token_data.get("scope", "(none returned)"))
    result = store_schwab_tokens(db, app_key, app_secret, token_data)
    return {"status": "ok", **result}


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
