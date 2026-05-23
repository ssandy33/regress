"""In-memory TTL cache helper for the research endpoints (issue #280).

A small, dependency-free, process-local cache used by every
``/api/positions/{id}/research/*`` endpoint per the V1 contract freeze in
``backend/design-specs/issue-280-stock-research-plan.md`` §3.5.

Design notes
------------

- This is *only* the in-memory tier. The 24h-TTL endpoints (business,
  financials) ALSO persist to ``app_settings`` keyed by ticker; that
  durable tier is implemented inline in the per-endpoint services so a
  server restart does not burn the Alpha Vantage daily quota. The 15min
  (price-history) and 5min (regression) caches are in-memory only — a
  restart evicts them harmlessly.
- The cache stores arbitrary Python objects (typically the already-built
  response payload as a ``dict``). Each entry carries the timestamp it was
  written; ``get(key, ttl)`` returns ``None`` when the entry is missing or
  has aged out.
- Not thread-safe by design — FastAPI's default worker model is a single
  event loop per process, and the only writes happen on the request path.
  If we ever switch to a multi-threaded worker we can wrap the dict in a
  lock; the public API does not have to change.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

# Module-level store: ``{cache_key: (value, written_at_utc)}``. Keys follow
# the formats frozen in the plan §4.6 (e.g. ``yf_business:AAPL``).
_store: dict[str, tuple[Any, datetime]] = {}


def get(key: str, ttl: timedelta) -> Any | None:
    """Return the cached value for ``key`` when still fresh, else ``None``.

    A "fresh" entry is one whose age (now − written_at) is strictly less
    than ``ttl``. Expired entries are NOT proactively evicted by this
    function — callers either overwrite them via :func:`set` or the entry
    is silently superseded on the next successful upstream fetch. This
    keeps the read path lock-free and predictable.
    """
    entry = _store.get(key)
    if entry is None:
        return None
    value, written_at = entry
    if datetime.now(timezone.utc) - written_at < ttl:
        return value
    return None


def set(key: str, value: Any) -> None:  # noqa: A001 — mirrors dict API
    """Write ``value`` into the cache under ``key`` with the current UTC time.

    Overwrites any existing entry. ``value`` is stored by reference, so
    callers should pass an already-built immutable payload (typically a
    ``dict`` they no longer mutate).
    """
    _store[key] = (value, datetime.now(timezone.utc))


def invalidate(key: str) -> None:
    """Remove ``key`` from the cache. No-op when the key is absent."""
    _store.pop(key, None)


def clear() -> None:
    """Drop every entry. Test-only — never called on the request path."""
    _store.clear()
