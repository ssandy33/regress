#!/bin/sh
set -e

CADDYFILE_SRC="/etc/caddy/Caddyfile"
CADDYFILE="/tmp/Caddyfile"

# Copy the bind-mounted Caddyfile to a writable location
cp "$CADDYFILE_SRC" "$CADDYFILE"

# If basic auth credentials are set, inject basicauth block into Caddyfile
if [ -n "$BASIC_AUTH_USER" ] && [ -n "$BASIC_AUTH_PASS" ]; then
    # Hash the password for Caddy
    HASHED_PASS=$(caddy hash-password --plaintext "$BASIC_AUTH_PASS")

    # Build a temporary file with the basicauth block replacing the placeholder
    awk -v user="$BASIC_AUTH_USER" -v pass="$HASHED_PASS" '
    /# BASIC_AUTH_BLOCK/ {
        print "\tbasicauth * {"
        print "\t\t" user " " pass
        print "\t}"
        next
    }
    { print }
    ' "$CADDYFILE" > "${CADDYFILE}.tmp" && mv "${CADDYFILE}.tmp" "$CADDYFILE"

    echo "Basic auth enabled for user: $BASIC_AUTH_USER"
else
    # Remove the placeholder comment
    sed -i '/# BASIC_AUTH_BLOCK/d' "$CADDYFILE"
    echo "Basic auth disabled (no credentials set)"
fi

# Start Caddy with the processed Caddyfile
exec caddy run --config "$CADDYFILE" --adapter caddyfile
