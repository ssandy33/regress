"""Trading Rules Layer config — the ``rules_config`` keystone (issue #156).

This module is the **single source of truth** for the Trading Rules Layer.
Every Regress engine — options scanner, recovery engine, action engine, and the
future OKR engine — resolves its rule values from one configurable object
(:class:`RulesConfig`) instead of carrying its own hard-coded constants. That
is what structurally kills the documented DTE / delta / return / earnings-buffer
drift between engines.

Authoritative build spec: **ADR-002 (Discussion #216)**. Parent taxonomy
decision: **ADR-001 (#210)**. Source catalog: **PRD #209 (Trading Rules
Layer)**. The ``okr_config`` namespace and the OKR engine are explicitly out of
scope here — they are V1.1 (#157).

Persistence (ADR-001 Decision 2 / ADR-002 Option B)
---------------------------------------------------
``rules_config`` persists as a **single row** in the existing ``app_settings``
key/value table under the key :data:`RULES_CONFIG_KEY`. The ``value`` column
holds a JSON document carrying a :data:`RULES_CONFIG_SCHEMA_VERSION` integer.
There is **no new SQL table and no migration** — the row is created lazily on
first write; its absence means "all defaults". The ``Session.config``
JSON-in-Text column is the in-repo precedent for this pattern.

The schema and the five groups
------------------------------
:class:`RulesConfig` is composed of five nested rule groups, each sourced from a
section of PRD #209:

- :class:`UniverseRules` (PRD #209 §R2) — what is even tradeable: open-interest
  floor, bid/ask spread cap, IV-rank / IV-percentile floors.
- :class:`EntryRules` (PRD #209 §R3) — what makes a good entry: DTE band, delta
  bands, return target, earnings buffer, covered-call cost-basis rules.
- :class:`PositionRules` (PRD #209 §R4) — how much capital a position may use:
  per-position sizing cap, ticker-concentration cap, max open positions.
- :class:`RiskRules` (PRD #209 §R5) — when a losing position must be reviewed:
  loss-review threshold, hard stop, max consecutive rolls.
- :class:`ManagementTriggers` (PRD #209 §R6) — when an open position needs
  attention: profit-review %, DTE-review window, expiration warning window,
  assignment-risk review level.

Whole-percent convention
------------------------
**All percentage fields are whole-percent** — ``10.0`` means 10%, not 0.10 —
matching the existing ``OptionScanRequest`` convention. Delta values are bare
fractions in ``[0, 1]``. Dollar fields are plain dollar amounts. Day fields are
integer counts of calendar days.

Defaults and their PRD #209 source
----------------------------------
:data:`DEFAULT_RULES_CONFIG` is :class:`RulesConfig` instantiated with the
reconciled PRD #209 catalog values. Every field's default and its source
section is documented on the field below. The four PRD #209 "unset" rules
(``max_open_positions``, ``hard_max_loss_pct``, ``max_consecutive_rolls``,
``min_iv_percentile``) are modelled ``Optional`` and default ``None`` — they are
persisted and validated only; **no engine enforces a `None` value** (PRD #209
open question Q1 / ADR-002 OQ1).

The reader: merge-over-defaults, never raises
---------------------------------------------
:func:`load_rules_config` reads the single ``rules_config`` row, JSON-parses it,
and **merges it over the typed defaults**, so a partial / older / corrupt /
missing stored object always yields a complete, valid :class:`RulesConfig`. It
**never raises** to the caller:

- Missing row / empty value → :data:`DEFAULT_RULES_CONFIG` (one ``INFO`` log).
- Malformed JSON → :data:`DEFAULT_RULES_CONFIG` + a generic ``WARNING`` log
  (never ``str(e)`` — per CLAUDE.md).
- A single out-of-range stored field → that field falls back to its own default
  via :func:`_coerce_group`; the rest of the config is honored.

Per ADR-002, no rule is ever a hard blocker — a breach is surfaced as a
warning/flag. This module only stores and validates the thresholds; the engines
decide how to surface a breach.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator
from sqlalchemy.orm import Session as DBSession

from app.models.database import AppSetting

logger = logging.getLogger(__name__)

# The single ``app_settings`` key under which the Trading Rules config lives.
RULES_CONFIG_KEY = "rules_config"

# Schema version embedded in the persisted JSON document. Bump when the shape
# changes in a way an older reader could not merge-over-defaults safely.
RULES_CONFIG_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Nested value type — a min/max range
# ---------------------------------------------------------------------------


class RangeRule(BaseModel):
    """An inclusive ``[min, max]`` numeric range with a ``min < max`` invariant.

    Used for the DTE band and the delta bands in :class:`EntryRules`. A
    cross-field ``model_validator`` enforces ``min < max`` so an inverted stored
    range is rejected as a unit (and reverts as a unit via the per-field
    fallback in :func:`load_rules_config`).
    """

    model_config = ConfigDict(extra="forbid")

    min: float
    max: float

    @model_validator(mode="after")
    def _min_below_max(self) -> "RangeRule":
        """Reject an inverted or degenerate range (``min >= max``)."""
        if self.min >= self.max:
            raise ValueError("range min must be strictly less than max")
        return self


# ---------------------------------------------------------------------------
# Five rule groups
# ---------------------------------------------------------------------------


class UniverseRules(BaseModel):
    """Universe rules — what is even tradeable (PRD #209 §R2).

    These gate a strike on liquidity and volatility quality before any
    entry-quality rule is considered.
    """

    model_config = ConfigDict(extra="forbid")

    # Minimum open interest a strike must show to be considered liquid enough
    # to trade. PRD #209 §R2.
    min_open_interest: int = 500
    # Maximum bid/ask spread as a whole-percent of the mid price; wider spreads
    # mean a strike is too costly to enter/exit. PRD #209 §R2.
    max_bid_ask_spread_pct: float = 10.0
    # Minimum IV rank (whole-percent, 0-100) for selling premium to be worth it.
    # PRD #209 §R2.
    min_iv_rank: float = 30.0
    # Minimum IV percentile (whole-percent, 0-100). PRD #209 §R2 "unset" rule —
    # default None, no enforcement on None (PRD Q1 / ADR-002 OQ1).
    min_iv_percentile: float | None = None

    @field_validator("min_open_interest")
    @classmethod
    def _oi_non_negative(cls, v: int) -> int:
        """Open interest cannot be negative."""
        if v < 0:
            raise ValueError("min_open_interest must be >= 0")
        return v

    @field_validator("max_bid_ask_spread_pct")
    @classmethod
    def _spread_positive(cls, v: float) -> float:
        """A spread cap of zero or less would reject every strike."""
        if v <= 0:
            raise ValueError("max_bid_ask_spread_pct must be > 0")
        return v

    @field_validator("min_iv_rank", "min_iv_percentile")
    @classmethod
    def _percent_0_100(cls, v: float | None) -> float | None:
        """IV rank / percentile are whole-percents bounded to ``[0, 100]``."""
        if v is not None and not 0 <= v <= 100:
            raise ValueError("IV rank/percentile must be between 0 and 100")
        return v


class EntryRules(BaseModel):
    """Entry rules — what makes a good entry (PRD #209 §R3).

    Cost-basis-relative covered-call rules
    --------------------------------------
    This group carries **two distinct** covered-call cost-basis rules. They are
    independent rules (PRD #209 §R3 / ADR-002 D3) and both are measured from the
    position's adjusted **cost basis** — never from spot price. ADR-002's
    "One correction to PRD #209" established that the scanner already measures
    the covered-call distance rule from cost basis, not from current price.

    - ``min_call_distance_pct`` — a **percentage margin above cost basis**. A
      covered-call strike must sit at least this whole-percent *above* the
      adjusted cost basis to be a recommendation; otherwise the scanner emits
      the ``fails_10pct_rule`` rejection. The strike floor is
      ``cost_basis * (1 + min_call_distance_pct / 100)``. Default ``5.0`` →
      strike must be ≥ 5% above cost basis.

    - ``min_call_distance_from_cost_basis_pct`` — a **bare at-or-above-cost-basis
      floor**. A covered-call strike below
      ``cost_basis * (1 + min_call_distance_from_cost_basis_pct / 100)`` would
      lock in a capital loss on the shares if assigned, so the scanner emits the
      ``below_cost_basis`` rejection. Default ``0.0`` → the floor is exactly the
      cost basis (a strike at or above cost basis is acceptable).

    The two are not redundant: ``min_call_distance_pct`` is the *premium-quality*
    margin a trader wants on a good entry, while
    ``min_call_distance_from_cost_basis_pct`` is the *hard loss-avoidance* floor
    below which the trade is structurally bad. With the catalog defaults
    (``5.0`` and ``0.0``) the margin rule is the stricter of the two; a trader
    who lowers the margin still keeps the loss-avoidance floor.
    """

    model_config = ConfigDict(extra="forbid")

    # Days-to-expiration band for an entry. PRD #209 §R3 — reconciled catalog
    # value (resolves the scanner's prior 25-50 drift).
    dte_range: RangeRule = RangeRule(min=21, max=45)
    # Delta band for a cash-secured put. PRD #209 §R3 — reconciled catalog
    # value (resolves the scanner's prior 0.15-0.35 drift).
    delta_range_csp: RangeRule = RangeRule(min=0.20, max=0.30)
    # Delta band for a covered call. PRD #209 §R3.
    delta_range_cc: RangeRule = RangeRule(min=0.20, max=0.35)
    # Minimum monthly return on capital, whole-percent. PRD #209 §R3 —
    # reconciled catalog value (resolves the scanner's prior 1% drift).
    min_monthly_return_pct: float = 2.0
    # Calendar days of buffer to keep clear of an earnings date. PRD #209 §R3 —
    # reconciled catalog value (resolves the scanner's prior 5-day drift).
    earnings_buffer_days: int = 7
    # Covered-call premium-quality margin above cost basis, whole-percent. See
    # the class docstring. PRD #209 §R3.
    min_call_distance_pct: float = 5.0
    # Covered-call hard at-or-above-cost-basis floor, whole-percent. See the
    # class docstring. PRD #209 §R3.
    min_call_distance_from_cost_basis_pct: float = 0.0

    @field_validator("dte_range")
    @classmethod
    def _dte_non_negative(cls, v: RangeRule) -> RangeRule:
        """DTE cannot be negative."""
        if v.min < 0:
            raise ValueError("dte_range.min must be >= 0")
        return v

    @field_validator("delta_range_csp", "delta_range_cc")
    @classmethod
    def _delta_in_unit_interval(cls, v: RangeRule) -> RangeRule:
        """Delta bounds are bare fractions in ``[0, 1]``."""
        if not 0 <= v.min <= 1 or not 0 <= v.max <= 1:
            raise ValueError("delta range bounds must be between 0 and 1")
        return v

    @field_validator(
        "min_monthly_return_pct",
        "earnings_buffer_days",
        "min_call_distance_pct",
        "min_call_distance_from_cost_basis_pct",
    )
    @classmethod
    def _non_negative(cls, v: float) -> float:
        """Return target, earnings buffer, and call distances cannot be negative."""
        if v < 0:
            raise ValueError("value must be >= 0")
        return v


class PositionRules(BaseModel):
    """Position rules — how much capital a position may use (PRD #209 §R4)."""

    model_config = ConfigDict(extra="forbid")

    # Per-position capital cap in dollars. PRD #209 §R4. Consumed by the
    # recovery engine's average-down path.
    sizing_cap_dollars: float = 5000.0
    # Maximum share of the portfolio a single ticker may occupy, whole-percent.
    # PRD #209 §R4.
    max_ticker_concentration_pct: float = 25.0
    # Maximum number of concurrently open positions. PRD #209 §R4 "unset" rule —
    # default None, no enforcement on None (PRD Q1 / ADR-002 OQ1).
    max_open_positions: int | None = None

    @field_validator("sizing_cap_dollars")
    @classmethod
    def _cap_positive(cls, v: float) -> float:
        """A sizing cap of zero or less would suppress every sized path."""
        if v <= 0:
            raise ValueError("sizing_cap_dollars must be > 0")
        return v

    @field_validator("max_ticker_concentration_pct")
    @classmethod
    def _concentration_in_range(cls, v: float) -> float:
        """A concentration cap is a whole-percent in ``(0, 100]``."""
        if not 0 < v <= 100:
            raise ValueError("max_ticker_concentration_pct must be in (0, 100]")
        return v

    @field_validator("max_open_positions")
    @classmethod
    def _open_positions_positive(cls, v: int | None) -> int | None:
        """When set, the open-positions cap must be at least 1."""
        if v is not None and v < 1:
            raise ValueError("max_open_positions must be >= 1 when set")
        return v


class RiskRules(BaseModel):
    """Risk rules — when a losing position must be reviewed (PRD #209 §R5)."""

    model_config = ConfigDict(extra="forbid")

    # Unrealized-loss threshold, whole-percent, that flags a position for
    # review. Negative because it is a loss. PRD #209 §R5.
    loss_review_threshold_pct: float = -15.0
    # Hard maximum tolerated loss, whole-percent. PRD #209 §R5 "unset" rule —
    # default None, no enforcement on None (PRD Q1 / ADR-002 OQ1).
    hard_max_loss_pct: float | None = None
    # Maximum number of consecutive rolls before forcing a decision. PRD #209
    # §R5 "unset" rule — default None, no enforcement on None.
    max_consecutive_rolls: int | None = None

    @field_validator("loss_review_threshold_pct", "hard_max_loss_pct")
    @classmethod
    def _loss_non_positive(cls, v: float | None) -> float | None:
        """A loss threshold must be zero or negative — a loss is not a gain."""
        if v is not None and v > 0:
            raise ValueError("loss threshold must be <= 0")
        return v

    @field_validator("max_consecutive_rolls")
    @classmethod
    def _rolls_non_negative(cls, v: int | None) -> int | None:
        """When set, the consecutive-rolls cap cannot be negative."""
        if v is not None and v < 0:
            raise ValueError("max_consecutive_rolls must be >= 0 when set")
        return v


class ManagementTriggers(BaseModel):
    """Management triggers — when an open position needs attention (PRD #209 §R6)."""

    model_config = ConfigDict(extra="forbid")

    # Profit captured, whole-percent of max profit, that triggers a review to
    # close/roll early. PRD #209 §R6.
    profit_review_pct: float = 50.0
    # Days-to-expiration at which a roll/close/hold decision is reviewed.
    # PRD #209 §R6.
    dte_review_days: int = 21
    # Days-to-expiration inside which assignment mechanics dominate and an
    # expiration warning fires. PRD #209 §R6.
    expiration_warning_days: int = 7
    # Assignment-risk level at which a position is surfaced for review.
    # PRD #209 §R6.
    assignment_risk_review: Literal["High", "Medium", "Low"] = "High"

    @field_validator("profit_review_pct")
    @classmethod
    def _profit_in_range(cls, v: float) -> float:
        """The profit-review trigger is a whole-percent in ``(0, 100]``."""
        if not 0 < v <= 100:
            raise ValueError("profit_review_pct must be in (0, 100]")
        return v

    @field_validator("dte_review_days", "expiration_warning_days")
    @classmethod
    def _days_non_negative(cls, v: int) -> int:
        """Day windows cannot be negative."""
        if v < 0:
            raise ValueError("day window must be >= 0")
        return v


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------


class RulesConfig(BaseModel):
    """The complete Trading Rules Layer config — five nested rule groups.

    Persisted as one JSON document in the ``app_settings`` row keyed
    :data:`RULES_CONFIG_KEY`. :data:`DEFAULT_RULES_CONFIG` is this model
    instantiated with all PRD #209 catalog defaults.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = RULES_CONFIG_SCHEMA_VERSION
    universe: UniverseRules = UniverseRules()
    entry: EntryRules = EntryRules()
    position: PositionRules = PositionRules()
    risk: RiskRules = RiskRules()
    management: ManagementTriggers = ManagementTriggers()


# The model instantiated with all PRD #209 catalog defaults. Returned verbatim
# by :func:`load_rules_config` whenever no usable stored config is found.
DEFAULT_RULES_CONFIG = RulesConfig()

# The five nested-group attribute names, in document order. Drives the
# group-by-group merge and per-field fallback in :func:`load_rules_config`.
_GROUP_MODELS: dict[str, type[BaseModel]] = {
    "universe": UniverseRules,
    "entry": EntryRules,
    "position": PositionRules,
    "risk": RiskRules,
    "management": ManagementTriggers,
}


# ---------------------------------------------------------------------------
# The shared reader
# ---------------------------------------------------------------------------


def _get_rules_config_row(db: DBSession, key: str) -> str | None:
    """Read a single ``app_settings`` row by key. ``None`` when missing.

    Mirrors the ``_get_app_setting`` idiom in ``routers/positions.py`` — kept
    local so the keystone module has no router dependency.
    """
    entry = db.query(AppSetting).filter(AppSetting.key == key).first()
    return entry.value if entry else None


def _coerce_group(
    model_cls: type[BaseModel],
    group_dict: dict[str, Any],
    default_group: BaseModel,
) -> tuple[BaseModel, list[str]]:
    """Build a rule group, dropping any invalid field back to its default.

    A single out-of-range stored value must not poison the whole group:
    ``RulesConfig(**merged)`` would reject the entire object on one bad field.
    This helper instead validates the group, and on a :class:`ValidationError`
    walks the error locations, resets each offending field to the default
    group's value, and retries — bounded to one retry per field.

    A cross-field failure (e.g. an inverted :class:`RangeRule`) reports the
    *range field* as the offending location, so that whole sub-object reverts
    to its default as a unit, which is the intended behavior.

    Args:
        model_cls: The group model class to build.
        group_dict: The merged stored-over-default dict for this group.
        default_group: The all-defaults instance of this group.

    Returns:
        A ``(group, dropped_fields)`` tuple. ``group`` always validates.
        ``dropped_fields`` lists the field names that fell back to defaults
        (empty when the stored group was fully valid).
    """
    defaults = default_group.model_dump()
    working = dict(group_dict)
    dropped: list[str] = []

    # At most one retry per field plus a final all-default fallback.
    for _ in range(len(model_cls.model_fields) + 1):
        try:
            return model_cls(**working), dropped
        except ValidationError as exc:
            offending = {
                str(err["loc"][0])
                for err in exc.errors()
                if err.get("loc")
            }
            if not offending:
                # No locatable field — give up on the merged dict entirely.
                break
            for field in offending:
                if field in defaults:
                    working[field] = defaults[field]
                    if field not in dropped:
                        dropped.append(field)
                else:
                    # An unknown extra key the model forbids — drop it.
                    working.pop(field, None)

    # Bounded retries exhausted — fall back to the full default group.
    return default_group, sorted(_GROUP_MODELS) if not dropped else dropped


def load_rules_config(db: DBSession) -> RulesConfig:
    """Read and resolve the Trading Rules config — the single shared reader.

    Reads the one ``app_settings`` row keyed :data:`RULES_CONFIG_KEY`, parses
    its JSON, and **merges it over** :data:`DEFAULT_RULES_CONFIG` so a partial,
    older, corrupt, or missing stored object always yields a complete, valid
    :class:`RulesConfig`. This function **never raises** to the caller.

    Fallback behavior:

    - Missing row / empty value → :data:`DEFAULT_RULES_CONFIG` (``INFO`` log).
    - Malformed JSON → :data:`DEFAULT_RULES_CONFIG` + generic ``WARNING`` log.
    - A single out-of-range stored field → that field reverts to its default
      via :func:`_coerce_group`; the rest of the config is honored (``WARNING``
      log naming only the dropped field — never a leaked value).

    No exception text (``str(e)``) is ever logged or surfaced, per CLAUDE.md.

    Args:
        db: A SQLAlchemy session (request-scoped).

    Returns:
        A fully-populated, validated :class:`RulesConfig`.
    """
    raw = _get_rules_config_row(db, RULES_CONFIG_KEY)
    if raw is None or raw.strip() == "":
        logger.info("No %s setting found; using default trading rules.", RULES_CONFIG_KEY)
        return DEFAULT_RULES_CONFIG

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError, TypeError):
        logger.warning(
            "Stored %s is not valid JSON; falling back to default trading rules.",
            RULES_CONFIG_KEY,
        )
        return DEFAULT_RULES_CONFIG

    if not isinstance(parsed, dict):
        logger.warning(
            "Stored %s is not a JSON object; falling back to default trading rules.",
            RULES_CONFIG_KEY,
        )
        return DEFAULT_RULES_CONFIG

    # Merge-over-defaults at group + field granularity. Each group is validated
    # independently so a bad field in one group cannot poison the others.
    groups: dict[str, BaseModel] = {}
    dropped_any: list[str] = []
    for name, model_cls in _GROUP_MODELS.items():
        default_group = getattr(DEFAULT_RULES_CONFIG, name)
        stored_group = parsed.get(name)
        if not isinstance(stored_group, dict):
            # Missing or non-object group — take the default wholesale.
            groups[name] = default_group
            continue
        merged_group = {**default_group.model_dump(), **stored_group}
        group, dropped = _coerce_group(model_cls, merged_group, default_group)
        groups[name] = group
        dropped_any.extend(f"{name}.{field}" for field in dropped)

    if dropped_any:
        logger.warning(
            "Stored %s had invalid values for %s; those fields reverted to defaults.",
            RULES_CONFIG_KEY,
            ", ".join(sorted(dropped_any)),
        )

    return RulesConfig(
        schema_version=RULES_CONFIG_SCHEMA_VERSION,
        universe=groups["universe"],  # type: ignore[arg-type]
        entry=groups["entry"],  # type: ignore[arg-type]
        position=groups["position"],  # type: ignore[arg-type]
        risk=groups["risk"],  # type: ignore[arg-type]
        management=groups["management"],  # type: ignore[arg-type]
    )


__all__ = [
    "RULES_CONFIG_KEY",
    "RULES_CONFIG_SCHEMA_VERSION",
    "RangeRule",
    "UniverseRules",
    "EntryRules",
    "PositionRules",
    "RiskRules",
    "ManagementTriggers",
    "RulesConfig",
    "DEFAULT_RULES_CONFIG",
    "load_rules_config",
]
