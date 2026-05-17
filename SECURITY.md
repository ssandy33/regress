# Security & Deployment Hardening

This document describes the security requirements for running the Financial
Regression Analysis Tool in production. It is written for operators deploying
the application to a VPS or other internet-facing host.

Every item in the **Pre-deployment checklist** below is a hard requirement for
a production deployment, not an optional recommendation. The application stores
encrypted Schwab OAuth tokens and other credentials in its SQLite database, so a
weak host configuration can expose live brokerage credentials.

## Pre-deployment checklist

- [ ] SQLite database file is `chmod 600` and owned by the app service account.
- [ ] Application processes run as a dedicated **non-root** user.
- [ ] SQLite database file lives **outside** any web-accessible directory.
- [ ] FastAPI port 8000 is **never** published to the public internet.
- [ ] A reverse proxy (Caddy or nginx) terminates HTTPS in front of the app.
- [ ] The host firewall allows only ports 80 and 443 from the internet.

The `deploy/` scripts and `docker-compose.prod.yml` in this repository already
satisfy these requirements. The sections below explain each requirement so that
operators can verify, audit, or reproduce the hardened configuration on other
infrastructure.

---

## 1. Database file permissions and service account

The SQLite database (`regression_tool.db`) holds the application's most
sensitive data, including **encrypted Schwab OAuth tokens** (see issue #14) and
application settings. Anyone who can read this file can attempt to extract or
brute-force those credentials offline.

### Requirements

1. The database file must have permission mode `600` (`rw-------`): readable and
   writable only by its owner, with **no group or world access**.
2. The database file must be **owned by the dedicated app service account** —
   the same non-root user the application process runs as (see section 2).
   It must not be owned by `root` or by a shared/login user.

### How to apply

For a host-managed (non-Docker) deployment where the app runs as the `appuser`
service account and the database lives at `/opt/regression-tool/data/regression_tool.db`:

```bash
# Restrict permissions to owner-only
sudo chmod 600 /opt/regression-tool/data/regression_tool.db

# Transfer ownership to the app service account
sudo chown appuser:appuser /opt/regression-tool/data/regression_tool.db

# Lock down the containing directory as well
sudo chmod 700 /opt/regression-tool/data
sudo chown appuser:appuser /opt/regression-tool/data
```

Apply the same `chmod 600` / `chown` treatment to any database backups created
by `deploy/backup.sh`, since a backup of the database is just as sensitive as
the live file.

For the Docker deployment, the database lives in the `sqlite_data` named volume
and is created and owned by the in-container `appuser` (UID 1000), so these
permissions are handled automatically. Operators copying the volume contents to
the host for backup or migration should re-apply `chmod 600` afterwards.

### Built-in startup check

The backend verifies database file permissions at startup. The function
`check_db_file_permissions()` in
[`backend/app/services/encryption.py`](backend/app/services/encryption.py)
inspects the database file's mode and logs a warning if any group or world
permission bit is set, for example:

```
Database file ./data/regression_tool.db has permissions 0o644 —
recommend 'chmod 600 ./data/regression_tool.db' for production
```

This check is a safety net, not a substitute for correct configuration: it
**warns** but does not change permissions or block startup. If you see this
warning in the backend logs, fix the file mode and ownership immediately using
the commands above.

---

## 2. Run as a dedicated non-root user

Production application processes must run as a **dedicated, unprivileged
(non-root) service account**. Running as `root` means that any code-execution
vulnerability in the application — or in one of its many third-party
dependencies — immediately grants full control of the host.

### Requirements

1. The backend and frontend processes must run as a non-root user.
2. The SQLite database path must **not** be under a web-accessible directory
   (for example, never inside `nginx`/Caddy document roots or anything the
   reverse proxy can serve as a static file). A misconfigured proxy or path
   traversal must not be able to hand the raw database to a client.

### How this is enforced

**Container images.** Both Docker images already drop privileges:

- `backend/Dockerfile` creates `appuser` (UID 1000, `/usr/sbin/nologin` shell)
  and ends with `USER appuser`.
- `frontend/Dockerfile` ends with `USER node` (the non-root user shipped in the
  Node base image).

**Compose `user:` directive.** `docker-compose.prod.yml` additionally sets an
explicit `user:` directive on the `backend` and `frontend` services. This pins
the runtime UID/GID even if a future base-image change alters the default user,
and makes the non-root requirement visible and auditable directly in the
deployment manifest rather than buried in the Dockerfiles.

**Database path.** In production the database lives in the `sqlite_data` Docker
volume mounted at `/app/data` inside the backend container. This path is private
to the backend container — neither the frontend nor Caddy mounts it, and it is
not part of any served document root. For host-managed deployments, keep the
database under a private directory such as `/opt/regression-tool/data` (mode
`700`, owned by the service account) and never under a web server's static root.

### Verifying

```bash
# Backend container should NOT report uid=0(root)
docker compose -f docker-compose.prod.yml exec backend id
# expected: uid=1000(appuser) gid=1000(appuser) ...

# Frontend container should NOT report uid=0(root)
docker compose -f docker-compose.prod.yml exec frontend id
# expected: uid=1000(node) gid=1000(node) ...
```

---

## 3. Reverse proxy and network exposure

A reverse proxy that terminates HTTPS is a **security requirement** for
production, not merely an architectural convenience. The FastAPI backend speaks
plain HTTP and is not designed to be a hardened, internet-facing edge service.

### Requirements

1. FastAPI **port 8000 must never be exposed directly to the internet.** It
   serves unencrypted HTTP and has no rate limiting, no TLS, and an
   automatically generated interactive API explorer at `/docs`. Exposing it
   directly leaks traffic in cleartext and offers an unauthenticated attack
   surface.
2. A **reverse proxy (Caddy or nginx) with HTTPS is required** for any
   production deployment. The proxy is responsible for TLS termination, HTTP→
   HTTPS redirection, security headers, HSTS, and (optionally) basic auth.

### How this is enforced

In `docker-compose.prod.yml`:

- The `backend` and `frontend` services declare **no `ports:` mapping**, so
  Docker does not publish them to the host. They are reachable only on Docker's
  internal network — and only by the `caddy` service.
- Only the `caddy` service publishes ports, and only `80` and `443`.

The resulting production topology:

```
Internet → Caddy (HTTPS, :80/:443)
              ├── /api/*  → Backend (FastAPI :8000, internal Docker network only)
              └── /*      → Frontend (Next.js :8080, internal Docker network only)
```

[`deploy/Caddyfile`](deploy/Caddyfile) implements the required edge behavior:

- Automatic HTTPS certificates from Let's Encrypt.
- `Strict-Transport-Security` (HSTS) with a one-year `max-age`.
- `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`,
  `Permissions-Policy`, and a `Content-Security-Policy`.
- Optional HTTP basic auth, conditionally injected by
  `deploy/caddy-entrypoint.sh`.

The `deploy/deploy.sh` script configures the host firewall (UFW) to allow only
ports 80 and 443 inbound, which keeps port 8000 unreachable even if a future
change accidentally publishes it.

### If you do not use the bundled Caddy setup

Operators using their own nginx, an external load balancer, or a managed proxy
must reproduce the same guarantees:

- Bind the backend to `127.0.0.1:8000` (or an internal-only network), never to
  `0.0.0.0` on a public interface.
- Restrict port 8000 with a host firewall so it is unreachable from the
  internet.
- Terminate HTTPS at the proxy and redirect all HTTP traffic to HTTPS.
- Forward `X-Forwarded-For` / `X-Forwarded-Proto` headers so the backend sees
  the correct client IP and scheme.

---

## Reporting a vulnerability

If you discover a security issue, please open a private report rather than a
public GitHub issue, so it can be addressed before disclosure.
