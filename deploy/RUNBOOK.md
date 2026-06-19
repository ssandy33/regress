# Deploy Runbook

Operational reference for the regress VPS (prod + QA stacks on one box).

## Disk reclamation

The box accumulates Docker build cache and dangling images over time. The
deploy pipeline reclaims space automatically; this section documents the
signals and the manual break-glass.

### 85% pre-flight disk signal (#371)

Before every `docker compose pull`, the SSH deploy
(`.github/workflows/_deploy-ssh.yml`) runs a `df`-based pre-flight check on
`/`:

- Threshold: `DISK_WARN_PCT=85`.
- It always logs an informational line — `Disk headroom: / at N% (threshold 85%).` —
  and surfaces it to the run's Summary tab via the `::DISK_RESULT::` marker.
- If `/` is at or above 85%, it emits a `::warning::` annotation naming the
  host. **The warning is non-fatal by design** — it must not block the very
  deploy that reclaims space (see the builder prune below).

If you see the warning repeatedly, run the break-glass full reclaim below.

### 168h builder-prune bound (#369)

At the end of every deploy, after `docker image prune -f` (which removes only
dangling images), the deploy runs:

```
docker builder prune -f --filter until=168h
```

- `docker builder prune` removes dangling/unreferenced build cache by default.
- The `--filter until=168h` (7-day) age bound additionally preserves the last
  week of warm cache, so routine CI rebuilds stay fast.
- It never touches cache referenced by the currently-running prod + QA
  containers — running images are not build cache, and `docker image prune -f`
  only removes dangling images. Both prod and QA containers stay `Up`.

Verify after a deploy: `docker system df` shows reclaimed build cache;
`docker compose -f docker-compose.prod.yml ps` and the QA `ps` both show
containers `Up`.

### Break-glass: full reclaim

When the 85% warning persists or the box is critically low on space, run a
full, unbounded build-cache reclaim on the box:

```
docker builder prune -af
```

This removes **all** build cache (not just cache older than 168h), so the next
CI build will be a cold build. Use only when the bounded prune is not enough.
