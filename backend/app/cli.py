"""CLI commands for the regression tool backend.

Usage: python -m app.cli schwab-auth [--app-key KEY] [--app-secret SECRET]
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, quote, urlparse

import httpx

from app.services.schwab_auth import (
    SCHWAB_AUTHORIZE_URL,
    SCHWAB_REDIRECT_URI,
    SCHWAB_TOKEN_URL,
    _upsert_setting,
)


def schwab_auth(args):
    """Run the one-time Schwab OAuth authorization flow."""
    app_key = args.app_key or os.environ.get("SCHWAB_APP_KEY") or ""
    app_secret = args.app_secret or os.environ.get("SCHWAB_APP_SECRET") or ""

    if not app_key:
        app_key = input("Schwab App Key: ").strip()
    if not app_secret:
        app_secret = input("Schwab App Secret: ").strip()

    if not app_key or not app_secret:
        print("Error: App key and secret are required.", file=sys.stderr)
        sys.exit(1)

    # Build authorization URL
    auth_url = (
        f"{SCHWAB_AUTHORIZE_URL}"
        f"?response_type=code"
        f"&client_id={app_key}"
        f"&redirect_uri={quote(SCHWAB_REDIRECT_URI, safe='')}"
    )

    print("\n--- Schwab OAuth Authorization ---\n")
    print("1. Open this URL in your browser:\n")
    print(f"   {auth_url}\n")
    print("2. Log in to Schwab and authorize the application.")
    print("3. After authorization, you will be redirected to a URL starting with:")
    print(f"   {SCHWAB_REDIRECT_URI}")
    print("\n4. Copy the FULL URL from your browser's address bar and paste it below.\n")

    callback_url = input("Paste the callback URL: ").strip()
    if not callback_url:
        print("Error: No URL provided.", file=sys.stderr)
        sys.exit(1)

    # Extract authorization code
    parsed = urlparse(callback_url)
    qs = parse_qs(parsed.query)
    code = qs.get("code", [None])[0]
    if not code:
        print("Error: Could not extract 'code' parameter from URL.", file=sys.stderr)
        sys.exit(1)

    # Exchange code for tokens
    print("\nExchanging authorization code for tokens...")
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
        print(f"Error: Token exchange failed ({e.response.status_code}): {e.response.text}", file=sys.stderr)
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"Error: Request failed: {e}", file=sys.stderr)
        sys.exit(1)

    token_data = resp.json()
    if "access_token" not in token_data or "refresh_token" not in token_data:
        print("Error: Unexpected token response format. Missing required fields.", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc)
    access_expires = now.replace(microsecond=0) + timedelta(
        seconds=token_data.get("expires_in", 1800)
    )
    refresh_expires = now.replace(microsecond=0) + timedelta(days=7)

    # Store in database
    from app.models.database import init_db, SessionLocal
    init_db()
    db = SessionLocal()
    try:
        _upsert_setting(db, "schwab_app_key", app_key)
        _upsert_setting(db, "schwab_app_secret", app_secret)
        _upsert_setting(db, "schwab_access_token", token_data["access_token"])
        _upsert_setting(db, "schwab_refresh_token", token_data["refresh_token"])
        _upsert_setting(db, "schwab_access_token_expires", access_expires.isoformat())
        _upsert_setting(db, "schwab_refresh_token_expires", refresh_expires.isoformat())
        db.commit()
    finally:
        db.close()

    print("\nSuccess! Schwab tokens stored in database.")
    print(f"  Access token expires:  {access_expires.isoformat()}")
    print(f"  Refresh token expires: {refresh_expires.isoformat()}")
    print("\nThe server will automatically refresh the access token before it expires.")
    print("You will need to re-authorize when the refresh token expires (7 days).")

    from app.services.encryption import get_encryption_key
    if not get_encryption_key():
        print("\nWarning: SCHWAB_ENCRYPTION_KEY not set — tokens stored in plaintext.")
        print("Set this env var for production deployments.")
        print("Generate a key: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
    else:
        print("\nTokens encrypted at rest with SCHWAB_ENCRYPTION_KEY.")


def main():
    parser = argparse.ArgumentParser(prog="app.cli", description="Regression Tool CLI")
    subparsers = parser.add_subparsers(dest="command")

    schwab_parser = subparsers.add_parser("schwab-auth", help="Authorize with Schwab API")
    schwab_parser.add_argument("--app-key", default=None, help="Schwab app key")
    schwab_parser.add_argument("--app-secret", default=None, help="Schwab app secret")


    args = parser.parse_args()
    if args.command == "schwab-auth":
        schwab_auth(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
