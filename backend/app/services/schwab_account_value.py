"""Schwab account-value service with two-tier TTL cache.

Wraps ``SchwabClient.get_accounts()`` for the per-position sizing-cap
percentage feature (issue #234). Surfaces the connected account's net
liquidation value as a typed ``AccountValueResult`` so consumers
(``recovery_engine``, the Settings UI) can resolve ``sizing_cap_pct ×
total_capital → dollar ceiling`` at request time.

Cache shape mirrors ``alpha_vantage_client``:

* **Tier 1** — module-level ``_cache: dict`` keyed by ``cache_key`` (the
  ``sizing_cap_account`` selection); stores the typed result + a
  ``cached_at`` UTC datetime.
* **Tier 2** — ``app_settings`` rows keyed ``"schwab_account_value:{cache_key}"``
  with a JSON-serialised result for cross-process / cross-restart durability.

TTL: 15 minutes. ``get_account_value`` writes both tiers on a successful
fetch; ``get_cached_account_value`` is **cache-hit-only** and never makes
a network call by contract — the recovery-evaluation request path relies
on that guarantee so it never blocks on a Schwab round-trip.

Per project convention (`CLAUDE.md`) this module never returns raw
exception text in ``error_detail``; only generic, sanitised strings.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Literal, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.database import AppSetting
from app.services.schwab_auth import SchwabAuthCode, SchwabAuthError
from app.services.schwab_client import SchwabClient, SchwabClientError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cache configuration
# ---------------------------------------------------------------------------

_CACHE_TTL = timedelta(minutes=15)
_DB_KEY_PREFIX = "schwab_account_value:"

# Status discriminator (V1 contract — mirrors the frontend failure-cause
# mapping documented in ``frontend/design-specs/issue-234-sizing-cap-pct-plan.md``
# §6.3). ``"stale"`` is reserved for forward compatibility — we never
# *write* it from this module but we tolerate reading it from a future
# version's persisted cache without raising.
AccountValueStatus = Literal["ok", "disconnected", "expired", "error", "stale"]

_OK_STATUSES: frozenset[str] = frozenset({"ok", "stale"})


@dataclass
class AccountValueResult:
    """Typed result returned by both ``get_account_value`` variants.

    Field order is part of the V1 contract — workers W-E / W-H / W-I all
    consume this shape. Don't reorder without bumping the contract.
    """

    status: AccountValueStatus
    total_capital: Optional[float] = None
    account_id_masked: Optional[str] = None
    account_type: Optional[str] = None
    accounts: Optional[list[dict]] = None
    cached_at: Optional[datetime] = None
    error_detail: Optional[str] = None


# Hot in-memory cache. Key is the ``sizing_cap_account`` selector value
# normalised by ``_cache_key`` so ``None`` and ``"sum"`` are independent
# entries.
_cache: dict[str, AccountValueResult] = {}


def _cache_key(sizing_cap_account: Optional[str]) -> str:
    """Normalise ``sizing_cap_account`` for use as a cache key.

    ``None`` (first/default account) is stored under ``"__default__"`` so
    the in-memory dict never has a ``None`` key.
    """
    return sizing_cap_account if sizing_cap_account else "__default__"


# ---------------------------------------------------------------------------
# Tier 2 — durable cache helpers (app_settings row)
# ---------------------------------------------------------------------------


def _serialise(result: AccountValueResult) -> str:
    """Encode an ``AccountValueResult`` for persistence."""
    payload = asdict(result)
    if isinstance(payload.get("cached_at"), datetime):
        payload["cached_at"] = result.cached_at.isoformat() if result.cached_at else None
    return json.dumps(payload)


def _deserialise(raw: str) -> Optional[AccountValueResult]:
    """Decode a previously persisted ``AccountValueResult`` row.

    Returns ``None`` if the row is malformed — callers treat that as a
    cache miss rather than raising.
    """
    try:
        payload = json.loads(raw)
        cached_at_raw = payload.get("cached_at")
        cached_at = datetime.fromisoformat(cached_at_raw) if cached_at_raw else None
        return AccountValueResult(
            status=payload.get("status", "error"),
            total_capital=payload.get("total_capital"),
            account_id_masked=payload.get("account_id_masked"),
            account_type=payload.get("account_type"),
            accounts=payload.get("accounts"),
            cached_at=cached_at,
            error_detail=payload.get("error_detail"),
        )
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.debug("Failed to decode schwab_account_value cache row: %s", exc)
        return None


def _read_db_cache(db: Session, cache_key: str) -> Optional[AccountValueResult]:
    """Read the durable cache row for ``cache_key`` from ``app_settings``."""
    try:
        entry = (
            db.query(AppSetting)
            .filter(AppSetting.key == f"{_DB_KEY_PREFIX}{cache_key}")
            .first()
        )
        if entry is None:
            return None
        return _deserialise(entry.value)
    except SQLAlchemyError as exc:
        logger.debug("Failed to read schwab_account_value cache row: %s", exc)
        return None


def _write_db_cache(db: Session, cache_key: str, result: AccountValueResult) -> None:
    """Persist a fresh ``AccountValueResult`` to ``app_settings``."""
    try:
        key = f"{_DB_KEY_PREFIX}{cache_key}"
        value = _serialise(result)
        entry = db.query(AppSetting).filter(AppSetting.key == key).first()
        if entry is None:
            db.add(AppSetting(key=key, value=value))
        else:
            entry.value = value
        db.commit()
    except SQLAlchemyError as exc:
        logger.debug("Failed to write schwab_account_value cache row: %s", exc)
        try:
            db.rollback()
        except SQLAlchemyError:
            pass


# ---------------------------------------------------------------------------
# Schwab response shape — defensive extraction
# ---------------------------------------------------------------------------

# CHAIN-UNVERIFIED — V0 capture failed (issue #234, refresh token expired 65d).
# Candidate-key chain is from the planner's spec, not verified against a live response.
# Release-manager checklist must include a live-verify step before v1.0.7 is tagged.
_LIQUIDATION_VALUE_KEYS: tuple[str, ...] = (
    "liquidationValue",
    "netLiquidation",
    "currentLiquidationValue",
)
_BALANCE_CONTAINERS: tuple[str, ...] = ("currentBalances", "aggregatedBalance")


def _extract_liquidation_value(securities_account: dict) -> Optional[float]:
    """Pull a ``liquidationValue``-equivalent number from a securitiesAccount.

    Tries the candidate-key chain against each candidate balance
    container. Returns ``None`` if nothing parseable is found so the
    caller can mark the account as ``error`` (per the §6.3 account-zero
    failure mapping).
    """
    # CHAIN-UNVERIFIED — V0 capture failed (issue #234, refresh token expired 65d).
    # Candidate-key chain is from the planner's spec, not verified against a live response.
    # Release-manager checklist must include a live-verify step before v1.0.7 is tagged.
    for container_key in _BALANCE_CONTAINERS:
        container = securities_account.get(container_key)
        if not isinstance(container, dict):
            continue
        for value_key in _LIQUIDATION_VALUE_KEYS:
            raw = container.get(value_key)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                return float(raw)
    return None


def _mask_account_number(account_number: Optional[str]) -> Optional[str]:
    """Format an account number as ``"…{last4}"`` (Unicode ellipsis).

    Returns ``None`` if the input is missing or shorter than 4 chars so
    the caller can decide whether to surface the account at all.
    """
    if not account_number or not isinstance(account_number, str):
        return None
    last4 = account_number[-4:]
    if len(last4) < 4:
        return None
    return f"…{last4}"


def _sanitise_accounts(raw_accounts: Iterable[Any]) -> list[dict]:
    """Project a raw ``get_accounts()`` response into the sanitised shape
    we expose to callers (the UI's multi-account selector consumes this).

    Drops anything we couldn't extract a ``net_liquidation`` from.
    """
    sanitised: list[dict] = []
    for raw in raw_accounts:
        if not isinstance(raw, dict):
            continue
        securities_account = raw.get("securitiesAccount")
        if not isinstance(securities_account, dict):
            continue
        net_liq = _extract_liquidation_value(securities_account)
        if net_liq is None:
            continue
        masked = _mask_account_number(securities_account.get("accountNumber"))
        if masked is None:
            continue
        account_type = securities_account.get("type")
        sanitised.append(
            {
                "account_id_masked": masked,
                "account_type": account_type if isinstance(account_type, str) else None,
                "net_liquidation": net_liq,
            }
        )
    return sanitised


# ---------------------------------------------------------------------------
# Account selection
# ---------------------------------------------------------------------------


def _select_account(
    sanitised: list[dict],
    sizing_cap_account: Optional[str],
) -> AccountValueResult:
    """Resolve the requested selection to a final ``AccountValueResult``.

    * ``None`` → first account in Schwab's response order.
    * ``"sum"`` → sum of all sanitised accounts' ``net_liquidation``.
    * Any other string → match against ``account_id_masked``; absent →
      ``status="error"``.

    A zero-summed result (or a single account with ``net_liquidation == 0``)
    is the "account-zero" failure cause from §6.3 → ``status="error"``.
    """
    now = datetime.now(timezone.utc)

    if not sanitised:
        return AccountValueResult(
            status="error",
            accounts=[],
            cached_at=now,
            error_detail="No usable accounts returned by Schwab",
        )

    if sizing_cap_account == "sum":
        total = sum(a["net_liquidation"] for a in sanitised)
        if total <= 0:
            return AccountValueResult(
                status="error",
                accounts=sanitised,
                cached_at=now,
                error_detail="Summed account value is zero",
            )
        return AccountValueResult(
            status="ok",
            total_capital=total,
            account_id_masked=None,
            account_type=None,
            accounts=sanitised,
            cached_at=now,
        )

    if sizing_cap_account in (None, "", "__default__"):
        chosen = sanitised[0]
    else:
        chosen = next(
            (a for a in sanitised if a["account_id_masked"] == sizing_cap_account),
            None,
        )
        if chosen is None:
            return AccountValueResult(
                status="error",
                accounts=sanitised,
                cached_at=now,
                error_detail="Selected account not found in Schwab response",
            )

    if chosen["net_liquidation"] <= 0:
        return AccountValueResult(
            status="error",
            account_id_masked=chosen["account_id_masked"],
            account_type=chosen["account_type"],
            accounts=sanitised,
            cached_at=now,
            error_detail="Account liquidation value is zero",
        )

    return AccountValueResult(
        status="ok",
        total_capital=chosen["net_liquidation"],
        account_id_masked=chosen["account_id_masked"],
        account_type=chosen["account_type"],
        accounts=sanitised,
        cached_at=now,
    )


# ---------------------------------------------------------------------------
# Schwab auth error → status mapping
# ---------------------------------------------------------------------------

_DISCONNECTED_CODES: frozenset[SchwabAuthCode] = frozenset(
    {SchwabAuthCode.TOKEN_MISSING, SchwabAuthCode.NOT_CONFIGURED}
)
_EXPIRED_CODES: frozenset[SchwabAuthCode] = frozenset(
    {
        SchwabAuthCode.TOKEN_EXPIRED,
        SchwabAuthCode.REFRESH_FAILED,
        SchwabAuthCode.REFRESH_FAILED_401,
        SchwabAuthCode.API_401,
    }
)


def _auth_error_to_status(exc: SchwabAuthError) -> AccountValueStatus:
    """Map a ``SchwabAuthError.code`` to the three-state failure enum."""
    if exc.code in _DISCONNECTED_CODES:
        return "disconnected"
    if exc.code in _EXPIRED_CODES:
        return "expired"
    # NETWORK_ERROR (and any future code we haven't mapped) → "error" —
    # callers render the amber "couldn't reach Schwab" panel.
    return "error"


# ---------------------------------------------------------------------------
# Cache freshness predicates
# ---------------------------------------------------------------------------


def _is_fresh(result: AccountValueResult, now: datetime) -> bool:
    """Return True iff ``result`` is within the TTL window."""
    if result.cached_at is None:
        return False
    return (now - result.cached_at) < _CACHE_TTL


def _hot_cache_lookup(cache_key: str, now: datetime) -> Optional[AccountValueResult]:
    """Return a fresh, ok-status hot cache entry or ``None``."""
    cached = _cache.get(cache_key)
    if cached is None:
        return None
    if cached.status not in _OK_STATUSES:
        return None
    if not _is_fresh(cached, now):
        return None
    return cached


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def get_cached_account_value(
    db: Session,
    sizing_cap_account: Optional[str] = None,
) -> Optional[AccountValueResult]:
    """Return a fresh cached account-value result without calling Schwab.

    Cache-hit-only by contract — this function **NEVER** makes a network
    round-trip. Callers that need a network-respecting fetch must use
    ``get_account_value`` instead.

    Returns ``None`` (not an ``AccountValueResult``) when no fresh entry
    exists so the caller can distinguish "no data" from "data with
    status != ok".
    """
    now = datetime.now(timezone.utc)
    cache_key = _cache_key(sizing_cap_account)

    hot = _hot_cache_lookup(cache_key, now)
    if hot is not None:
        return hot

    db_entry = _read_db_cache(db, cache_key)
    if db_entry is not None and db_entry.status in _OK_STATUSES and _is_fresh(db_entry, now):
        # Backfill the hot cache so subsequent lookups in the same process
        # avoid the DB hit. Mirrors the alpha_vantage_client pattern.
        _cache[cache_key] = db_entry
        return db_entry

    return None


def get_account_value(
    db: Session,
    force_refresh: bool = False,
    sizing_cap_account: Optional[str] = None,
) -> AccountValueResult:
    """Fetch (or cache-hit) the Schwab account-value result.

    Never raises — every exception path maps to a status discriminator
    on the returned ``AccountValueResult``. Status values:

    * ``"ok"`` — fresh data (either from cache or a successful fetch).
    * ``"disconnected"`` — ``SchwabAuthError(TOKEN_MISSING | NOT_CONFIGURED)``.
    * ``"expired"`` — ``SchwabAuthError(TOKEN_EXPIRED | REFRESH_FAILED |
      REFRESH_FAILED_401 | API_401)``.
    * ``"error"`` — every other failure mode (transport, malformed JSON,
      ``liquidationValue`` extraction failure, account-zero, etc.).

    **S2 fall-through (refinement S2 of the parallel-execution plan):**
    when ``force_refresh=True`` and the network call fails BUT a fresh
    hot-cache entry exists, the cached value is returned with
    ``status="ok"`` and a WARNING is logged. This keeps the user's UI
    from flipping to "error" on a transient refresh failure.
    """
    now = datetime.now(timezone.utc)
    cache_key = _cache_key(sizing_cap_account)

    if not force_refresh:
        cached = get_cached_account_value(db, sizing_cap_account=sizing_cap_account)
        if cached is not None:
            return cached

    # Snapshot any fresh hot-cache entry BEFORE we attempt the network
    # call so the S2 fall-through can return it without re-reading the
    # dict (which a partial failure path might already have updated).
    pre_fetch_hot = _hot_cache_lookup(cache_key, now)

    try:
        raw_accounts = SchwabClient().get_accounts()
    except SchwabAuthError as exc:
        status = _auth_error_to_status(exc)
        return _fall_through_or_failure(
            cache_key=cache_key,
            force_refresh=force_refresh,
            pre_fetch_hot=pre_fetch_hot,
            status=status,
            error_detail=_generic_auth_detail(status),
        )
    except SchwabClientError:
        return _fall_through_or_failure(
            cache_key=cache_key,
            force_refresh=force_refresh,
            pre_fetch_hot=pre_fetch_hot,
            status="error",
            error_detail="Schwab API error",
        )
    except Exception:  # noqa: BLE001 — defence in depth; never raise out of this module.
        logger.exception("Unexpected error fetching Schwab account value")
        return _fall_through_or_failure(
            cache_key=cache_key,
            force_refresh=force_refresh,
            pre_fetch_hot=pre_fetch_hot,
            status="error",
            error_detail="Unexpected error fetching Schwab account value",
        )

    if not isinstance(raw_accounts, list):
        logger.warning("Schwab get_accounts() returned non-list payload")
        return _fall_through_or_failure(
            cache_key=cache_key,
            force_refresh=force_refresh,
            pre_fetch_hot=pre_fetch_hot,
            status="error",
            error_detail="Malformed Schwab response",
        )

    sanitised = _sanitise_accounts(raw_accounts)
    if not sanitised:
        # All accounts failed liquidationValue extraction — log once and
        # treat as the account-zero failure cause.
        logger.warning(
            "Schwab get_accounts() returned %d entries but none had a parseable liquidationValue",
            len(raw_accounts),
        )
        return _fall_through_or_failure(
            cache_key=cache_key,
            force_refresh=force_refresh,
            pre_fetch_hot=pre_fetch_hot,
            status="error",
            error_detail="No parseable liquidationValue in Schwab response",
        )

    result = _select_account(sanitised, sizing_cap_account)
    # On a successful select, stamp the cached_at to "now" (overriding the
    # one _select_account chose) and persist.
    if result.status == "ok":
        result.cached_at = now
        _cache[cache_key] = result
        _write_db_cache(db, cache_key, result)
        return result

    # Selection failed (account-zero, unknown id, etc.) — apply the same
    # fall-through behaviour as a network failure for consistency.
    return _fall_through_or_failure(
        cache_key=cache_key,
        force_refresh=force_refresh,
        pre_fetch_hot=pre_fetch_hot,
        status=result.status,
        error_detail=result.error_detail,
    )


def _fall_through_or_failure(
    *,
    cache_key: str,
    force_refresh: bool,
    pre_fetch_hot: Optional[AccountValueResult],
    status: AccountValueStatus,
    error_detail: Optional[str],
) -> AccountValueResult:
    """Apply the S2 fall-through rule then return the final result.

    When ``force_refresh=True`` and a fresh hot-cache entry existed
    before the network attempt, the cached entry wins and we log a
    WARNING. Otherwise we return the failure with the supplied status.
    """
    if force_refresh and pre_fetch_hot is not None:
        logger.warning(
            "Schwab account-value refresh failed (%s); falling back to fresh cache entry",
            status,
        )
        return pre_fetch_hot

    # Don't pollute the cache with failure entries — leave any existing
    # fresh entry alone and just return the failure result.
    return AccountValueResult(
        status=status,
        cached_at=datetime.now(timezone.utc),
        error_detail=error_detail,
    )


def _generic_auth_detail(status: AccountValueStatus) -> str:
    """Generic, sanitised error_detail strings for auth failures.

    Never echoes ``str(exc)`` — per CLAUDE.md no raw exception text in
    consumer-facing fields.
    """
    if status == "disconnected":
        return "Schwab is not connected"
    if status == "expired":
        return "Schwab connection has expired"
    return "Schwab API error"


# ---------------------------------------------------------------------------
# Test hooks
# ---------------------------------------------------------------------------


def clear_cache() -> None:
    """Clear the in-memory cache (for testing)."""
    _cache.clear()
