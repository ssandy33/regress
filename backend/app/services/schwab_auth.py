"""Schwab OAuth 2.0 token manager.

Thread-safe singleton that manages access/refresh token lifecycle.
Access tokens expire in 30 minutes, refresh tokens in 7 days.
"""

import logging
import threading
from datetime import datetime, timedelta, timezone

import httpx

from app.config import get_schwab_credentials
from app.services.encryption import (
    ENCRYPTED_SETTING_KEYS, decrypt_value, encrypt_value, get_encryption_key,
)

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
            from app.models.database import SessionLocal
            db = SessionLocal()
            try:
                value = _read_setting(db, "schwab_access_token")
                return value is not None and bool(value)
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

    def invalidate_token(self):
        """Clear cached access token to force refresh on next call."""
        with self._lock:
            self._cached_access_token = None
            self._cached_access_token_expires = None

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
                access_value = _read_setting(db, "schwab_access_token")
                expires_entry = db.query(AppSetting).filter(
                    AppSetting.key == "schwab_access_token_expires"
                ).first()

                if access_value and expires_entry:
                    expires_dt = datetime.fromisoformat(expires_entry.value)
                    if (expires_dt - now).total_seconds() > ACCESS_TOKEN_REFRESH_BUFFER_SECONDS:
                        self._cached_access_token = access_value
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

        refresh_value = _read_setting(db, "schwab_refresh_token")
        refresh_expires_entry = db.query(AppSetting).filter(
            AppSetting.key == "schwab_refresh_token_expires"
        ).first()

        if not refresh_value:
            raise SchwabAuthError(
                "No Schwab refresh token found. "
                "Run 'python -m app.cli schwab-auth' to authorize."
            )

        # Check if refresh token itself is expired
        if refresh_expires_entry and refresh_expires_entry.value:
            refresh_expires = datetime.fromisoformat(refresh_expires_entry.value)
            now_utc = datetime.now(timezone.utc)
            if refresh_expires <= now_utc:
                raise SchwabAuthError(
                    "Schwab refresh token has expired. "
                    "Run 'python -m app.cli schwab-auth' to re-authorize."
                )
            # Warn if refresh token expires within 48 hours
            hours_remaining = (refresh_expires - now_utc).total_seconds() / 3600
            if hours_remaining <= 48:
                logger.warning(
                    "Schwab refresh token expires in %.1f hours — "
                    "re-authorization needed soon",
                    hours_remaining,
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
                    "refresh_token": refresh_value,
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
            logger.error("Schwab token refresh HTTP error: %s", e)
            raise SchwabAuthError(
                "Schwab token refresh failed. "
                "Run 'python -m app.cli schwab-auth' to re-authorize."
            ) from e
        except httpx.RequestError as e:
            logger.error("Schwab token refresh request error: %s", e)
            raise SchwabAuthError(
                "Unable to reach Schwab API for token refresh. Please try again later."
            ) from e

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


def _read_setting(db, key: str) -> str | None:
    """Read an AppSetting value, decrypting if needed."""
    from cryptography.fernet import InvalidToken
    from app.models.database import AppSetting
    entry = db.query(AppSetting).filter(AppSetting.key == key).first()
    if not entry or not entry.value:
        return None
    if key in ENCRYPTED_SETTING_KEYS and get_encryption_key():
        try:
            return decrypt_value(entry.value)
        except InvalidToken:
            # Only fall back for legacy unprefixed (plaintext) rows.
            # If the value has the ENC: prefix, the key is wrong — fail fast.
            if not entry.value.startswith("ENC:"):
                logger.warning("Failed to decrypt %s — returning raw value", key)
                return entry.value
            raise
    return entry.value


def _upsert_setting(db, key: str, value: str):
    """Insert or update an AppSetting row, encrypting sensitive keys."""
    from app.models.database import AppSetting
    store_value = value
    if key in ENCRYPTED_SETTING_KEYS and get_encryption_key():
        store_value = encrypt_value(value)
    entry = db.query(AppSetting).filter(AppSetting.key == key).first()
    if entry:
        entry.value = store_value
    else:
        db.add(AppSetting(key=key, value=store_value))


def get_schwab_token_manager() -> SchwabTokenManager:
    """FastAPI dependency returning the singleton token manager."""
    return SchwabTokenManager()
