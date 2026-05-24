"""Per-trade entry-rule compliance evaluator (issue #160 / Quality v1 Wave 3).

This module is the producer side of the OKR engine's KR-5 input. It evaluates
a single trade against the current :class:`app.services.rules_config.EntryRules`
config and emits a verdict — either compliant (no real-rule violations) or
non-compliant (one or more locked rule literals fired). Unknown-bucket markers
(``delta_unknown`` / ``earnings_buffer_unknown``) are surfaced in
``failed_rules`` for audit but do **not** count as non-compliant.

The failed_rules vocabulary
---------------------------
Locked in the Wave 3 plan §V1-Freeze-3. Worker A and the future OKR engine
consumer (#157) reference these strings by name — drift is wasted work.

- ``dte_too_low`` — DTE below ``rules.entry.dte_range.min``
- ``dte_too_high`` — DTE above ``rules.entry.dte_range.max``
- ``delta_too_low`` — known delta below the relevant band's min
- ``delta_too_high`` — known delta above the relevant band's max
- ``delta_unknown`` — ``delta_hint is None`` (does NOT block compliance)
- ``monthly_return_too_low`` — monthly return below ``min_monthly_return_pct``
- ``earnings_buffer_too_short`` — ``earnings_buffer_days`` below the rule
- ``earnings_buffer_unknown`` — ``earnings_buffer_hint is None`` (does NOT
  block compliance)

Compliance bool: True iff every entry in ``failed_rules`` is an
``*_unknown`` marker (or the list is empty).

Trade-type routing
------------------
``sell_put`` is evaluated against ``rules.entry.delta_range_csp``.
``sell_call`` is evaluated against ``rules.entry.delta_range_cc``. All other
trade_types are out of scope — :func:`record_trade_compliance` no-ops for
``buy_put_close``, ``buy_call_close``, ``assignment``, ``called_away``,
``expired`` and never writes a row for them.

Observability (ADR #292)
------------------------
- ``trade_entry_compliance.evaluated`` — emitted by
  :func:`record_trade_compliance` with ``outcome=success|degraded``,
  ``duration_ms``, ``compliant: bool``. ``degraded`` covers the
  unknown-only path (still records, but the trader cannot fully audit).
- ``okr.entry_compliance.computed`` — emitted by
  :func:`compute_rolling_compliance` with ``outcome=success|no_data``,
  ``duration_ms``, ``window_days``, ``total``, ``compliant_pct``.

We never log raw upstream payloads or the full ``entry_rules_snapshot`` JSON
(would bloat Axiom); only the ``schema_version`` integer travels in extras.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session as DBSession

from app.models.database import Trade, TradeEntryCompliance
from app.models.schemas import EntryComplianceSummary
from app.services.rules_config import RulesConfig

logger = logging.getLogger(__name__)

# Trade types this module evaluates. Anything else is silently skipped by
# :func:`record_trade_compliance` (no row written).
_EVALUATED_TRADE_TYPES: frozenset[str] = frozenset({"sell_put", "sell_call"})

# Average days per month, used to normalize a per-trade return to monthly. We
# pick 30 (calendar) instead of 30.44 (actual mean) because the
# ``min_monthly_return_pct`` config is itself a whole-percent rule of thumb
# (PRD #209 §R3), not a calendrically-precise threshold; the few-tenths-of-a-
# percent slack a leap-year-aware divisor would buy is irrelevant.
_DAYS_PER_MONTH: float = 30.0


def _classify_failed_rules(failed_rules: list[str]) -> tuple[bool, bool]:
    """Return ``(has_real_violation, has_unknown)`` for a failed_rules list.

    Shared by :func:`evaluate_trade_compliance` (for the compliant bool),
    :func:`record_trade_compliance` (for the success/degraded outcome), and
    :func:`compute_rolling_compliance` (for the unknown_only bucket). The
    ``*_unknown`` suffix convention is part of the locked vocabulary in plan
    §V1-Freeze-3 — keeping this single helper means the suffix rule lives in
    one place.
    """
    has_real_violation = any(not r.endswith("_unknown") for r in failed_rules)
    has_unknown = any(r.endswith("_unknown") for r in failed_rules)
    return has_real_violation, has_unknown


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_iso_date(value: str) -> date:
    """Parse an ISO date or datetime string into a ``date``.

    The codebase stores ``opened_at`` as ISO 8601 datetimes
    (``2026-01-15T10:00:00+00:00``) and ``expiration`` as bare YYYY-MM-DD.
    Both round-trip cleanly through :func:`datetime.fromisoformat` (Python
    3.11+ accepts trailing ``Z``; we strip it defensively).
    """
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).date()


def _compute_dte(opened_at: str, expiration: str) -> int:
    """Days-to-expiration at entry.

    Both fields are always present on :class:`Trade`; DTE is never unknown.
    """
    return (_parse_iso_date(expiration) - _parse_iso_date(opened_at)).days


def _compute_monthly_return_pct(premium: float, strike: float, dte: int) -> float:
    """Whole-percent monthly return on capital for one short option contract.

    ``premium`` is per-share; capital tied up per share is ``strike``. The
    per-share return fraction is ``premium / strike``; we normalize to a
    30-day month and multiply by 100 to match the ``min_monthly_return_pct``
    whole-percent convention.

    DTE 0 (same-day expiration) is treated as 1 to avoid divide-by-zero;
    the caller's data is degenerate either way.
    """
    if strike <= 0:
        return 0.0
    safe_dte = max(dte, 1)
    return (premium / strike) * 100.0 * (_DAYS_PER_MONTH / safe_dte)


def _snapshot_entry_rules(rules: RulesConfig) -> dict:
    """Slice the EntryRules group + schema_version into a plain-dict snapshot.

    The snapshot is structural (``dict``), not strongly-typed: storing it as
    a JSON object keeps the migration story simple — any future EntryRules
    field is captured automatically, and reading a snapshot from a future
    config version costs zero schema work.
    """
    entry = rules.entry.model_dump()
    return {
        "schema_version": rules.schema_version,
        "dte_range": entry["dte_range"],
        "delta_range_csp": entry["delta_range_csp"],
        "delta_range_cc": entry["delta_range_cc"],
        "min_monthly_return_pct": entry["min_monthly_return_pct"],
        "earnings_buffer_days": entry["earnings_buffer_days"],
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_trade_compliance(
    trade: Trade,
    rules: RulesConfig,
    *,
    dte_hint: int | None,
    delta_hint: float | None,
    earnings_buffer_hint: int | None,
) -> dict:
    """Pure-function evaluator: trade + rules + hints -> compliance dict.

    No DB writes; no side effects. The caller (typically
    :func:`record_trade_compliance`) is responsible for persistence.

    Args:
        trade: The :class:`Trade` ORM row being evaluated. Read-only.
        rules: The currently-resolved :class:`RulesConfig` (loaded via
            :func:`app.services.rules_config.load_rules_config`).
        dte_hint: Optional user-asserted DTE-at-entry override. When ``None``
            the value is computed from ``trade.opened_at`` + ``trade.expiration``.
        delta_hint: Optional user-asserted delta-at-entry. ``None`` triggers
            the ``delta_unknown`` marker (which is NOT a compliance violation).
        earnings_buffer_hint: Optional user-asserted earnings-buffer days.
            ``None`` triggers ``earnings_buffer_unknown`` (NOT a violation).

    Returns:
        Dict matching the :class:`TradeEntryCompliance` row shape plus
        ``compliant: bool`` and a structural ``entry_rules_snapshot: dict``.
    """
    entry = rules.entry
    failed_rules: list[str] = []

    # DTE — always derivable; hint overrides the derivation when present.
    dte = dte_hint if dte_hint is not None else _compute_dte(
        trade.opened_at, trade.expiration
    )
    if dte < entry.dte_range.min:
        failed_rules.append("dte_too_low")
    elif dte > entry.dte_range.max:
        failed_rules.append("dte_too_high")

    # Delta — band selection routes on trade_type. Out-of-scope trade types
    # are filtered upstream by record_trade_compliance; if we got here with a
    # different type, fall back to the CSP band (the conservative choice).
    if trade.trade_type == "sell_call":
        delta_band = entry.delta_range_cc
    else:
        delta_band = entry.delta_range_csp

    if delta_hint is None:
        failed_rules.append("delta_unknown")
    elif delta_hint < delta_band.min:
        failed_rules.append("delta_too_low")
    elif delta_hint > delta_band.max:
        failed_rules.append("delta_too_high")

    # Monthly return — always derivable from premium + strike + DTE.
    monthly_return_pct = _compute_monthly_return_pct(
        trade.premium, trade.strike, dte
    )
    if monthly_return_pct < entry.min_monthly_return_pct:
        failed_rules.append("monthly_return_too_low")

    # Earnings buffer — None is the unknown bucket; a known short buffer is
    # a real violation.
    if earnings_buffer_hint is None:
        failed_rules.append("earnings_buffer_unknown")
    elif earnings_buffer_hint < entry.earnings_buffer_days:
        failed_rules.append("earnings_buffer_too_short")

    # Compliance bool: True iff no real-rule violation fired (unknown markers
    # do not block compliance per plan §V1-Freeze-3).
    has_real_violation, _ = _classify_failed_rules(failed_rules)
    compliant = not has_real_violation

    return {
        "trade_id": trade.id,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "dte_at_entry": dte,
        "delta_at_entry": delta_hint,
        "monthly_return_pct": round(monthly_return_pct, 4),
        "earnings_buffer_days": earnings_buffer_hint,
        "compliant": compliant,
        "failed_rules": failed_rules,
        "entry_rules_snapshot": _snapshot_entry_rules(rules),
    }


def record_trade_compliance(
    db: DBSession,
    trade: Trade,
    rules: RulesConfig,
    *,
    dte_hint: int | None = None,
    delta_hint: float | None = None,
    earnings_buffer_hint: int | None = None,
) -> TradeEntryCompliance | None:
    """Evaluate ``trade`` and persist the resulting compliance row.

    Returns ``None`` when ``trade.trade_type`` is out of scope (the evaluator
    is restricted to ``sell_put`` / ``sell_call``).

    The row is one-shot: a second call for the same ``trade_id`` raises
    :class:`sqlalchemy.exc.IntegrityError` on commit (the primary-key
    constraint enforces snapshot non-retroactivity). Callers that need to
    re-evaluate should explicitly delete the existing row first; no
    re-evaluate endpoint ships in V1.

    Emits ``trade_entry_compliance.evaluated`` per ADR #292.
    """
    if trade.trade_type not in _EVALUATED_TRADE_TYPES:
        return None

    started = time.perf_counter()
    payload = evaluate_trade_compliance(
        trade,
        rules,
        dte_hint=dte_hint,
        delta_hint=delta_hint,
        earnings_buffer_hint=earnings_buffer_hint,
    )

    row = TradeEntryCompliance(
        trade_id=payload["trade_id"],
        evaluated_at=payload["evaluated_at"],
        dte_at_entry=payload["dte_at_entry"],
        delta_at_entry=payload["delta_at_entry"],
        monthly_return_pct=payload["monthly_return_pct"],
        earnings_buffer_days=payload["earnings_buffer_days"],
        compliant=1 if payload["compliant"] else 0,
        failed_rules=json.dumps(payload["failed_rules"]),
        entry_rules_snapshot=json.dumps(payload["entry_rules_snapshot"]),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    duration_ms = int((time.perf_counter() - started) * 1000)
    # Unknown-only is a degraded outcome from the trader's POV: the row was
    # recorded but they can't audit the verdict against real values yet.
    has_real_violation, has_unknown = _classify_failed_rules(
        payload["failed_rules"]
    )
    if has_unknown and not has_real_violation:
        outcome = "degraded"
    else:
        outcome = "success"
    logger.info(
        "trade_entry_compliance.evaluated",
        extra={
            "event": "trade_entry_compliance.evaluated",
            "outcome": outcome,
            "duration_ms": duration_ms,
            "trade_id": trade.id,
            "position_id": trade.position_id,
            "ticker": getattr(trade.position, "ticker", None) if trade.position else None,
        },
    )
    return row


def compute_rolling_compliance(
    db: DBSession,
    rules: RulesConfig,  # noqa: ARG001 — accepted for API symmetry; consumers may want rules-aware reads
    *,
    window_days: int = 30,
) -> EntryComplianceSummary:
    """Compute the rolling-window KR-5 summary.

    "Rolling N days" = trades whose ``opened_at`` falls within
    ``[now() - N days, now()]`` in UTC. We pick UTC explicitly for simplicity
    in this wave; #157 (OKR engine) will harmonize the timezone convention
    when it lands.

    Args:
        db: A SQLAlchemy session.
        rules: The currently-resolved :class:`RulesConfig`. Accepted for
            API symmetry with the evaluator and the future OKR engine; the
            current implementation does not branch on rules content.
        window_days: Rolling window length in days. Defaults to 30.

    Returns:
        :class:`EntryComplianceSummary` with ``compliant_pct`` set to
        ``None`` whenever the denominator (``total - unknown_only``) is 0.
    """
    started = time.perf_counter()
    now = datetime.now(timezone.utc)
    cutoff_iso = (now - timedelta(days=window_days)).isoformat()

    # Join compliance rows back to trades to filter by opened_at window. We
    # iterate (instead of a SQL aggregate) because the failed_rules JSON
    # text needs Python-side decoding for the unknown-only check.
    rows = (
        db.query(TradeEntryCompliance, Trade)
        .join(Trade, TradeEntryCompliance.trade_id == Trade.id)
        .filter(Trade.opened_at >= cutoff_iso)
        .all()
    )

    total = len(rows)
    compliant_count = 0
    unknown_only_count = 0
    for comp, _trade in rows:
        try:
            failed_rules = json.loads(comp.failed_rules)
        except (json.JSONDecodeError, TypeError):
            # Defensive: corrupt row counts toward total but not toward any
            # other bucket; the trader sees the discrepancy on the audit page.
            continue
        has_real_violation, has_unknown = _classify_failed_rules(failed_rules)
        if comp.compliant == 1 and not has_real_violation and has_unknown:
            unknown_only_count += 1
        if comp.compliant == 1 and not has_unknown and not has_real_violation:
            compliant_count += 1

    denominator = total - unknown_only_count
    compliant_pct: float | None
    if denominator <= 0:
        compliant_pct = None
    else:
        compliant_pct = round((compliant_count / denominator) * 100.0, 2)

    duration_ms = int((time.perf_counter() - started) * 1000)
    outcome = "no_data" if total == 0 else "success"
    logger.info(
        "okr.entry_compliance.computed",
        extra={
            "event": "okr.entry_compliance.computed",
            "outcome": outcome,
            "duration_ms": duration_ms,
        },
    )

    return EntryComplianceSummary(
        window_days=window_days,
        total=total,
        compliant=compliant_count,
        unknown_only=unknown_only_count,
        compliant_pct=compliant_pct,
    )


__all__ = [
    "evaluate_trade_compliance",
    "record_trade_compliance",
    "compute_rolling_compliance",
]
