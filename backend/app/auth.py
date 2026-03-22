import logging

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

_auth_warning_logged = False


def _get_allowed_users() -> list[str]:
    """Parse ALLOWED_USERS into a lowercase list, filtering blanks."""
    if not settings.allowed_users:
        return []
    return [
        u for u in (u.strip().lower() for u in settings.allowed_users.split(",")) if u
    ]


def is_auth_configured() -> bool:
    """Return True when NEXTAUTH_SECRET is set.

    The backend only needs NEXTAUTH_SECRET to verify JWTs issued by NextAuth.
    GitHub OAuth credentials (GITHUB_ID/GITHUB_SECRET) are only needed by
    the frontend and should not be exposed to the backend container.
    """
    return bool(settings.nextauth_secret)


def _is_partially_configured() -> bool:
    """Return True when NEXTAUTH_SECRET is set but empty or whitespace-only.

    Since auth now depends only on NEXTAUTH_SECRET, partial configuration
    means the variable exists but is blank. This is kept for forward
    compatibility if additional required vars are added later.
    """
    # With only one required var, partial config is not meaningfully possible.
    # Always return False — auth is either configured or not.
    return False


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    """Validate the JWT from the Authorization header.

    Returns a dict with user info (sub, username).
    Raises 401 if the token is missing, expired, or invalid.

    Auth is opt-in: requires NEXTAUTH_SECRET to be set. When not set,
    anonymous access is allowed.
    """
    global _auth_warning_logged
    if not is_auth_configured():
        if not _auth_warning_logged:
            if _is_partially_configured():
                logger.warning(
                    "Auth partially configured — NEXTAUTH_SECRET is required. "
                    "Running without auth."
                )
            else:
                logger.info(
                    "Auth env vars not set — auth disabled, allowing anonymous access"
                )
            _auth_warning_logged = True
        return {"sub": "anonymous", "username": "anonymous"}

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
