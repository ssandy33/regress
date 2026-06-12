# QA Environment (issue #330)

A second Docker Compose project (`regress-qa`) on the **same VPS** as prod,
served at `qa.<domain>`. QA runs only `backend` + `frontend` — no Caddy, no
Loki, no Grafana. The **existing prod Caddy** terminates TLS for `qa.<domain>`
and reverse-proxies to the QA containers across a shared external Docker network
(`caddy_net`) using the `qa-backend` / `qa-frontend` aliases.

QA data is an on-demand restore of a prod backup snapshot. Observability is
Axiom-only, routed to a dedicated dataset (`AXIOM_DATASET=regression-tool-qa`);
`docker logs qa-backend` (json-file driver) is the fallback.

This is the same-VPS precursor to #324 — every artifact here is forward-portable
to a dedicated host.

---

## Architecture at a glance

| Component | Prod (`regress`) | QA (`regress-qa`) |
|---|---|---|
| Compose file | `docker-compose.prod.yml` | `docker-compose.qa.yml` |
| App dir on box | `/root/regress` | `/root/regress-qa` |
| Caddy | ✅ owns ports 80/443 | ❌ reuses prod Caddy |
| Loki + Grafana | ✅ | ❌ |
| TLS for | `<domain>` | `qa.<domain>` (via prod Caddy) |
| Volume | `regress_sqlite_data` | `regress-qa_qa_sqlite_data` |
| Axiom dataset | `regression-tool` | `regression-tool-qa` |
| Schwab | ✅ | ❌ degraded mode |
| Memory cap | backend 512M / frontend 256M | backend 384M / frontend 192M |

The only genuinely shared component is Caddy. Everything else is namespaced
under `qa-` / `qa_` + the `regress-qa` project prefix, so no collision is
possible.

---

## ⚠️ Two prod-impact warnings — read before deploying

1. **Adding the `qa.<domain>` Caddy block wipes ALL TLS certs on the next prod
   deploy.** `.github/workflows/deploy.yml` does, on *any* `deploy/Caddyfile`
   diff: `docker compose rm -sf caddy` + `docker volume rm regress_caddy_data`.
   So the first prod deploy after the QA block lands **re-issues every cert
   (prod + qa)**. Do it during low traffic, and make sure the `qa.<domain>` DNS
   A record already resolves so Caddy can issue the QA cert on first boot.
   Repeated re-issuance hits Let's Encrypt rate limits.

2. **Don't `docker network rm caddy_net` while either stack is up.** It is an
   `external: true` network — neither stack auto-creates it, and removing it
   with active endpoints errors. Create it once (below) and leave it.

---

## First-time setup (operator, on the VPS, in order)

1. **Create the DNS A record** `qa.<domain>` → VPS IP (`5.78.124.155`). Wait
   for it to resolve:

   ```bash
   dig +short qa.<domain>
   ```

2. **Register a dedicated GitHub OAuth app for QA**
   (<https://github.com/settings/developers>):
   - Homepage URL: `https://qa.<domain>`
   - Authorization callback URL: `https://qa.<domain>/api/auth/callback/github`
   - Copy the Client ID + Secret. Do **not** reuse the prod app — its callback
     points at the prod domain.

3. **Create the shared external network** (once):

   ```bash
   docker network create caddy_net
   ```

4. **Clone the repo to `/root/regress-qa`** and create its `.env`:

   ```bash
   git clone <repo-url> /root/regress-qa
   cp /root/regress-qa/deploy/qa/.env.template /root/regress-qa/.env
   chmod 600 /root/regress-qa/.env
   # then edit .env: QA OAuth creds, a FRESH NEXTAUTH_SECRET (openssl rand -base64 32),
   # reused FRED/AV/Axiom token, AXIOM_DATASET=regression-tool-qa, NO Schwab key.
   ```

5. **Deploy prod once** to activate the `qa.{$DOMAIN}` Caddy block + the
   `caddy_net` attachment (⚠️ see warning #1 — this re-issues certs; DNS must
   already be in place):

   ```bash
   cd /root/regress && bash deploy/update.sh
   ```

6. **Deploy the QA stack:**

   ```bash
   cd /root/regress-qa && bash deploy/qa-deploy.sh
   ```

7. **Seed the QA DB** from the latest prod snapshot (run `deploy/backup.sh` on
   prod first if there's no recent snapshot):

   ```bash
   cd /root/regress-qa && bash deploy/qa-refresh-db.sh
   ```

8. **Verify:**

   ```bash
   curl -I https://qa.<domain>            # valid auto-TLS cert
   curl https://qa.<domain>/api/health    # ok in degraded (no-Schwab) mode
   # then log into QA via the QA OAuth app
   ```

---

## Routine operations

**Refresh the QA DB from the latest prod snapshot** (idempotent, in-place
overwrite — never accumulates copies):

```bash
cd /root/regress-qa && bash deploy/qa-refresh-db.sh
# Overrides:
#   BACKUP_DIR=/path/to/backups bash deploy/qa-refresh-db.sh
#   SNAPSHOT=/path/to/snap.db   bash deploy/qa-refresh-db.sh
```

**Update QA to the latest code:**

```bash
cd /root/regress-qa && bash deploy/qa-deploy.sh
```

**Logs** (Axiom dataset `regression-tool-qa`, or local):

```bash
docker compose -p regress-qa -f docker-compose.qa.yml logs -f
docker logs qa-backend
```

**Tear down QA** (prod untouched; add `-v` to also drop the QA volume):

```bash
cd /root/regress-qa && docker compose -p regress-qa -f docker-compose.qa.yml down
```

---

## Notes / caveats

- **Shared Alpha Vantage key (25 req/day).** QA reuses prod's AV key. A QA soak
  that hammers earnings endpoints can exhaust prod's daily quota. Don't soak
  earnings-heavy flows on QA during prod-critical windows.
- **Degraded mode.** QA has no `SCHWAB_ENCRYPTION_KEY`; the app runs in its
  existing no-Schwab degraded mode. Live quotes/Schwab features are unavailable
  on QA by design.
- **External-network ordering.** On a full prod `down`, `caddy_net` survives
  because QA still references it. If both stacks are down, recreate it with
  `docker network create caddy_net` before bringing either back up.
- **Forward-compatibility (#324).** The compose file, env template, and refresh
  script are written to port cleanly to a dedicated QA host: only the Caddy
  routing and the `caddy_net` sharing are same-VPS-specific.
