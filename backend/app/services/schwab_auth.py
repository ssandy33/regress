"""Schwab OAuth 2.0 token manager.

Thread-safe singleton that manages access/refresh token lifecycle.
Access tokens expire in 30 minutes, refresh tokens in 7 days.
"""

import logging
import threading
from datetime import datetime, timedelta, timezone

import httpx

from app.config import get_schwab_credentials

logger = logging.getLogger(__name__)

SCHWAB_TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
SCHWAB_AUTHORIZE_URL = "https://api.schwabapi.com/v1/oauth/authorize"
SCHWAB_REDIRECT_URI = "https://127.0.0.1:8089/callback"

# Refresh access token when it expires within this many seconds
ACCESS_TOKEN_REFRESH_BUFFER_SECONDS = 120


class SchwabAuthError(Exception):
    """Raised when Schwab authentication fails and re-auth is needed."""
    pass


class SchwabTokenManager:
    """Thread-safe singleton managing Schwab OAuth tokens."""

    _instance = None
    _init_lock = threading.Lock()

    def __new__(cls):
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._lock = threading.Lock()
        self._cached_access_token: str | None = None
        self._cached_access_token_expires: datetime | None = None
        self._initialized = True

    def is_configured(self) -> bool:
        """Check if Schwab tokens exist in DB."""
        try:
            from app.models.database import SessionLocal, AppSetting
            db = SessionLocal()
            try:
                token = db.query(AppSetting).filter(
                    AppSetting.key == "schwab_access_token"
                ).first()
                return token is not None and bool(token.value)
            finally:
                db.close()
        except Exception:
            return False

    def get_refresh_token_expiry(self) -> str | None:
        """Return the refresh token expiry as ISO string, or None."""
        try:
            from app.models.database import SessionLocal, AppSetting
            db = SessionLocal()
            try:
                entry = db.query(AppSetting).filter(
                    AppSetting.key == "schwab_refresh_token_expires"
                ).first()
                return entry.value if entry else None
            finally:
                db.close()
        except Exception:
            return None

    def get_access_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        with self._lock:
            now = datetime.now(timezone.utc)

            # Return cached token if still valid
            if (
                self._cached_access_token
                and self._cached_access_token_expires
                and (self._cached_access_token_expires - now).total_seconds()
                > ACCESS_TOKEN_REFRESH_BUFFER_SECONDS
            ):
                return self._cached_access_token

            # Try to load from DB
            from app.models.database import SessionLocal, AppSetting
            db = SessionLocal()
            try:
                access_entry = db.query(AppSetting).filter(
                    AppSetting.key == "schwab_access_token"
                ).first()
                expires_entry = db.query(AppSetting).filter(
                    AppSetting.key == "schwab_access_token_expires"
                ).first()

                if access_entry and expires_entry:
                    expires_dt = datetime.fromisoformat(expires_entry.value)
                    if (expires_dt - now).total_seconds() > ACCESS_TOKEN_REFRESH_BUFFER_SECONDS:
                        self._cached_access_token = access_entry.value
                        self._cached_access_token_expires = expires_dt
                        return self._cached_access_token

                # Need to refresh
                self._refresh_tokens(db)
                return self._cached_access_token
            finally:
                db.close()

    def _refresh_tokens(self, db):
        """Exchange refresh token for new access + refresh tokens."""
        from app.models.database import AppSetting

        refresh_entry = db.query(AppSetting).filter(
            AppSetting.key == "schwab_refresh_token"
        ).first()
        refresh_expires_entry = db.query(AppSetting).filter(
            AppSetting.key == "schwab_refresh_token_expires"
        ).first()

        if not refresh_entry or not refresh_entry.value:
            raise SchwabAuthError(
                "No Schwab refresh token found. "
                "Run 'python -m app.cli schwab-auth' to authorize."
            )

        # Check if refresh token itself is expired
        if refresh_expires_entry and refresh_expires_entry.value:
            refresh_expires = datetime.fromisoformat(refresh_expires_entry.value)
            if refresh_expires <= datetime.now(timezone.utc):
                raise SchwabAuthError(
                    "Schwab refresh token has expired. "
                    "Run 'python -m app.cli schwab-auth' to re-authorize."
                )

        app_key, app_secret = get_schwab_credentials()
        if not app_key or not app_secret:
            raise SchwabAuthError(
                "Schwab app key/secret not configured. "
                "Run 'python -m app.cli schwab-auth' to set up."
            )

        try:
            resp = httpx.post(
                SCHWAB_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_entry.value,
                },
                auth=(app_key, app_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise SchwabAuthError(
                    "Schwab token refresh failed (401). "
                    "Run 'python -m app.cli schwab-auth' to re-authorize."
                ) from e
            raise SchwabAuthError(f"Schwab token refresh failed: {e}") from e
        except httpx.RequestError as e:
            raise SchwabAuthError(f"Schwab token refresh request failed: {e}") from e

        token_data = resp.json()
        now = datetime.now(timezone.utc)
        access_expires = now.replace(microsecond=0) + timedelta(
            seconds=token_data.get("expires_in", 1800)
        )
        # Refresh tokens last 7 days from issuance
        refresh_expires = now.replace(microsecond=0) + timedelta(days=7)

        # Store in DB
        _upsert_setting(db, "schwab_access_token", token_data["access_token"])
        _upsert_setting(db, "schwab_refresh_token", token_data["refresh_token"])
        _upsert_setting(db, "schwab_access_token_expires", access_expires.isoformat())
        _upsert_setting(db, "schwab_refresh_token_expires", refresh_expires.isoformat())
        db.commit()

        # Update in-memory cache
        self._cached_access_token = token_data["access_token"]
        self._cached_access_token_expires = access_expires

        logger.info("Schwab tokens refreshed, access expires %s", access_expires.isoformat())


def _upsert_setting(db, key: str, value: str):
    """Insert or update an AppSetting row."""
    from app.models.database import AppSetting
    entry = db.query(AppSetting).filter(AppSetting.key == key).first()
    if entry:
        entry.value = value
    else:
        db.add(AppSetting(key=key, value=value))


def get_schwab_token_manager() -> SchwabTokenManager:
    """FastAPI dependency returning the singleton token manager."""
    return SchwabTokenManager()
