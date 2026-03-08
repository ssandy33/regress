import logging

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


def _get_allowed_users() -> list[str]:
    """Parse ALLOWED_USERS into a lowercase list, filtering blanks."""
    if not settings.allowed_users:
        return []
    return [u for u in (u.strip().lower() for u in settings.allowed_users.split(",")) if u]


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    """Validate the JWT from the Authorization header.

    Returns a dict with user info (sub, username).
    Raises 401 if the token is missing, expired, or invalid.

    Fail-closed: requires NEXTAUTH_SECRET unless DEV_AUTH_BYPASS=true.
    """
    if not settings.nextauth_secret:
        if settings.dev_auth_bypass:
            return {"sub": "anonymous", "username": "anonymous"}
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication not configured",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.nextauth_secret,
            algorithms=["HS256"],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username = payload.get("username", "")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing username",
            headers={"WWW-Authenticate": "Bearer"},
        )

    allowed = _get_allowed_users()
    if allowed and username.lower() not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not authorized",
        )

    return {
        "sub": payload.get("sub", ""),
        "username": username,
    }
