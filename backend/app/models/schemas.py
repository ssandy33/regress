from typing import Literal, Optional

import re

from pydantic import BaseModel, Field, field_validator


class DateRange(BaseModel):
    start: str
    end: str


class DataMeta(BaseModel):
    source: str
    frequency: str
    fetched_at: str
    is_stale: bool
    record_count: int
    date_range: DateRange


class DataPoint(BaseModel):
    date: str
    value: float


class HistoricalDataResponse(BaseModel):
    data: list[DataPoint]
    data_meta: DataMeta


# --- Regression Requests ---


class LinearRegressionRequest(BaseModel):
    asset: str
    start_date: str
    end_date: str


class MultiFactorRequest(BaseModel):
    dependent: str
    independents: list[str]
    start_date: str
    end_date: str


class RollingRegressionRequest(BaseModel):
    asset: str
    start_date: str
    end_date: str
    window_size: int = 30


# --- Statistical Safeguard Models ---


class StationarityResult(BaseModel):
    adf_statistic: float
    p_value: float
    is_stationary: bool


class DifferencedResult(BaseModel):
    dates: list[str]
    dependent_values: list[float]
    predicted_values: list[float]
    coefficients: dict[str, float]
    intercept: float
    r_squared: float
    adjusted_r_squared: float
    p_values: dict[str, float]
    f_statistic: float
    residuals: list[float]
    durbin_watson: float


# --- Regression Responses ---


class LinearRegressionResponse(BaseModel):
    dates: list[str]
    actual_values: list[float]
    predicted_values: list[float]
    slope: float
    intercept: float
    r_squared: float
    p_value: float
    confidence_interval_upper: list[float]
    confidence_interval_lower: list[float]
    std_error: float
    data_meta: DataMeta
    durbin_watson: Optional[float] = None
    sample_size: Optional[int] = None
    earnings_dates: Optional[list[str]] = None


class MultiFactorResponse(BaseModel):
    dates: list[str]
    dependent_values: list[float]
    predicted_values: list[float]
    coefficients: dict[str, float]
    intercept: float
    r_squared: float
    adjusted_r_squared: float
    p_values: dict[str, float]
    f_statistic: float
    residuals: list[float]
    data_meta: list[DataMeta]
    alignment_notes: list[str]
    durbin_watson: Optional[float] = None
    vif: Optional[dict[str, float]] = None
    stationarity: Optional[dict[str, StationarityResult]] = None
    differenced: Optional[DifferencedResult] = None
    sample_size: Optional[int] = None


class RollingRegressionResponse(BaseModel):
    dates: list[str]
    slope_over_time: list[float]
    r_squared_over_time: list[float]
    actual_values: list[float]
    data_meta: DataMeta


# --- Sessions ---


class SessionCreate(BaseModel):
    name: str
    config: dict


class SessionResponse(BaseModel):
    id: str
    name: str
    config: dict
    results: dict | None = None
    created_at: str
    updated_at: str


class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]


# --- Assets ---


class AssetInfo(BaseModel):
    identifier: str
    name: str
    source: str
    category: str


class AssetSearchResponse(BaseModel):
    results: list[AssetInfo]


# --- Comparison ---


class CompareRequest(BaseModel):
    assets: list[str]
    start_date: str
    end_date: str


class AssetCompareStats(BaseModel):
    identifier: str
    annualized_return: float
    volatility: float
    r_squared: float


class CompareResponse(BaseModel):
    dates: list[str]
    series: dict[str, list[float]]  # {asset: [normalized values]}
    stats: list[AssetCompareStats]
    data_meta: list[DataMeta]
    alignment_notes: list[str]


# --- Settings ---


class SettingUpdate(BaseModel):
    key: str
    value: str


class SettingsResponse(BaseModel):
    fred_api_key_set: bool
    cache_ttl_daily_hours: int
    cache_ttl_monthly_days: int
    default_date_range_years: int
    theme: str
    schwab_configured: bool = False
    schwab_token_expires: Optional[str] = None
    # Target yield drives the Recovery Plan's Sell & redeploy path (#207).
    # Stored as a fraction (e.g. 0.12 == 12%); the frontend converts to/from
    # whole-percent. Flat key for the V1.0.3 stopgap — migrates into the typed
    # okr_config namespace in V1.1 (ADR-001 / Discussion #210).
    okr_target_yield: Optional[float] = None


class CacheStatsResponse(BaseModel):
    entry_count: int
    total_size_bytes: int
    entries: list[dict]


# --- Option Scanner ---


class RuleCompliance(BaseModel):
    passes_10pct_rule: bool
    passes_dte_range: bool
    passes_delta_range: bool
    passes_earnings_check: bool
    passes_return_target: bool


class StrikeRecommendation(BaseModel):
    rank: int
    strike: float
    expiration: str
    dte: int
    bid: float
    ask: float
    mid: float
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    iv: Optional[float] = None
    open_interest: int
    volume: int
    premium_per_contract: float
    total_premium: float
    return_on_capital_pct: float
    annualized_return_pct: float
    distance_from_price_pct: float
    distance_from_basis_pct: Optional[float] = None
    max_profit: float
    breakeven: Optional[float] = None
    fifty_pct_profit_target: float
    rule_compliance: RuleCompliance
    greeks_source: str = "market"
    flags: list[str] = []


class RejectedStrike(BaseModel):
    """A strike the scanner skipped, with raw codes and human sentences.

    ``rejection_reasons`` preserves the machine-readable codes the scanner
    emits (used by tests and internal debugging). ``human_reasons`` is the
    plain-English render produced by
    :func:`app.services.rejection_messages.humanize_reasons` — populated
    server-side per issue #190 so the frontend can display sentences without
    duplicating the mapper logic.
    """

    strike: float
    expiration: str
    rejection_reasons: list[str]
    human_reasons: list[str] = Field(default_factory=list)


class MarketContext(BaseModel):
    vix: Optional[float] = None
    beta: Optional[float] = None
    fifty_two_week_high: Optional[float] = None
    fifty_two_week_low: Optional[float] = None
    daily_volume: Optional[int] = None


class OptionScanRequest(BaseModel):
    """Request body for ``POST /api/options/scan``.

    Rule fields default to ``None`` and are backfilled by the scan router
    from the persisted ``rules_config`` (see
    :func:`app.services.rules_config.load_rules_config`). An explicit
    non-``None`` value on the request still wins — per-request override is
    preserved. Omitting a rule field is the common case; the resolved value
    comes from the trader's configured Trading Rules.
    """

    ticker: str
    strategy: str  # "cash_secured_put" | "covered_call"
    cost_basis: Optional[float] = None
    capital_available: Optional[float] = None
    shares_held: Optional[int] = 100
    # Entry-rule fields — None means "resolve from rules_config" (issue #156).
    min_dte: Optional[int] = None
    max_dte: Optional[int] = None
    min_return_pct: Optional[float] = None
    max_return_pct: Optional[float] = None
    min_call_distance_pct: Optional[float] = None
    max_delta: Optional[float] = None
    min_delta: Optional[float] = None
    exclude_earnings_dte: Optional[int] = None
    # Universe-rule fields — also resolved from rules_config when None.
    min_open_interest: Optional[int] = None
    max_bid_ask_spread_pct: Optional[float] = None
    min_iv_rank: Optional[float] = None
    # Covered-call cost-basis floor toggle. When True (default), a CC strike
    # below the cost-basis floor is flagged with a ``below_cost_basis``
    # rejection reason; the candidate is never dropped.
    cost_basis_floor_enabled: bool = True
    # Covered-call at-or-above-cost-basis floor margin, whole-percent — None
    # means resolve from rules_config (entry.min_call_distance_from_cost_basis_pct).
    min_call_distance_from_cost_basis_pct: Optional[float] = None


class OptionScanResponse(BaseModel):
    """Response for ``POST /api/options/scan``.

    The watchlist gate (issue #322 / PRD #213 R5) runs upstream of the chain
    fetch: a scan for a ticker the trader has not approved returns zero
    candidates with an explanatory ``empty_reason`` and a ``200`` — never an
    error. ``watchlist_filtered`` records that the approved-universe gate was
    applied to this scan; ``empty_reason`` is populated only when the gate
    produced the empty result (it is ``None`` on a normal scan, including a
    normal scan that legitimately found no strikes).
    """

    ticker: str
    current_price: float
    strategy: str
    scan_time: str
    earnings_date: Optional[str] = None
    iv_rank: Optional[float] = None
    recommendations: list[StrikeRecommendation]
    rejected: list[RejectedStrike]
    market_context: MarketContext
    # Watchlist gate (issue #322 / PRD #213 R5). Additive + defaulted, so a
    # pre-#322 client ignores them and the change is non-breaking.
    watchlist_filtered: bool = True
    empty_reason: Optional[str] = None


# --- Journal ---


# Strategy values are *derived* from a position's lifecycle state by
# :func:`app.services.positions.recompute_position_state` (see issue #131).
# ``"holding"`` joins the original {csp, cc, wheel} set to label positions
# that hold shares with no open option legs. The literal still drives request
# validation on legacy back-compat fields (e.g. ``ImportRequest``) but is no
# longer accepted on position-create or position-update payloads.
STRATEGY_TYPES = Literal["csp", "cc", "wheel", "holding"]
POSITION_STATUS = Literal["open", "closed"]
TRADE_TYPES = Literal[
    "sell_put",
    "buy_put_close",
    "assignment",
    "sell_call",
    "buy_call_close",
    "called_away",
    "expired",
]
CLOSE_REASONS = Literal["fifty_pct_target", "full_expiration", "rolled", "closed_early", "assigned", "called_away"]


class PositionCreate(BaseModel):
    """Payload for creating a position.

    Per issue #131 the strategy label is derived from the position's
    lifecycle state by ``recompute_position_state`` and is no longer
    accepted from the client. New positions are seeded with ``"csp"``
    server-side; the recomputer overwrites that as soon as the first
    trade is logged.
    """

    ticker: str
    shares: int = Field(default=100, ge=1)
    broker_cost_basis: float
    opened_at: str
    notes: Optional[str] = None


class PositionUpdate(BaseModel):
    """Partial-update payload for a position.

    Per issue #131 ``strategy`` is no longer accepted — the recomputer is
    authoritative. Status / closed_at / notes / shares / broker_cost_basis
    can still be patched directly for manual corrections.
    """

    status: Optional[POSITION_STATUS] = None
    closed_at: Optional[str] = None
    notes: Optional[str] = None
    broker_cost_basis: Optional[float] = None
    shares: Optional[int] = Field(default=None, ge=1)


class TradeCreate(BaseModel):
    position_id: str
    trade_type: TRADE_TYPES
    strike: float
    expiration: str
    premium: float
    fees: float = 0.0
    quantity: int = Field(default=1, ge=1)
    opened_at: str
    closed_at: Optional[str] = None
    close_reason: Optional[CLOSE_REASONS] = None
    # Entry-compliance hints (issue #160 / Quality v1 Wave 3). All three are
    # optional and default to None for back-compat — Schwab-imported trades
    # never carry them. When provided on a sell_put / sell_call trade they
    # are used verbatim by the entry-compliance evaluator. The ``_hint``
    # suffix is deliberate: these are user-asserted snapshots, not computed
    # values; the evaluator records them as the historical truth.
    #
    # Bounds (CodeRabbit triage on PR #301):
    # - DTE / earnings-buffer hints reject negatives — the evaluator clamps
    #   DTE to 1 for monthly-return math, which would inflate the return on
    #   a negative input.
    # - Delta hint rejects non-finite floats (NaN / +-inf) — they bypass the
    #   delta-band comparisons silently.
    dte_at_entry_hint: Optional[int] = Field(default=None, ge=0)
    delta_at_entry_hint: Optional[float] = Field(default=None, allow_inf_nan=False)
    earnings_buffer_days_hint: Optional[int] = Field(default=None, ge=0)


class TradeUpdate(BaseModel):
    trade_type: Optional[TRADE_TYPES] = None
    strike: Optional[float] = None
    expiration: Optional[str] = None
    premium: Optional[float] = None
    fees: Optional[float] = None
    quantity: Optional[int] = Field(default=None, ge=1)
    opened_at: Optional[str] = None
    closed_at: Optional[str] = None
    close_reason: Optional[CLOSE_REASONS] = None


class TradeResponse(BaseModel):
    id: str
    position_id: str
    trade_type: str
    strike: float
    expiration: str
    premium: float
    fees: float
    quantity: int
    opened_at: str
    closed_at: Optional[str] = None
    close_reason: Optional[str] = None


# --- compliance (issue #160 / Quality v1 Wave 3) ---
#
# Per-trade entry-rule compliance shapes. The producer side of KR-5; the OKR
# engine (#157, deferred) consumes these. See
# :mod:`app.services.entry_compliance` for the failed_rules vocabulary +
# evaluation logic locked in the Wave 3 plan §V1-Freeze-3.


class EntryComplianceResponse(BaseModel):
    """One trade's compliance row.

    ``entry_rules_snapshot`` is intentionally typed as a structural ``dict``
    (not a strongly-typed model) — the snapshot captures the EntryRules
    shape at evaluation time, so a future EntryRules field flows through
    automatically without a schema-bump.
    """

    trade_id: str
    evaluated_at: str
    dte_at_entry: int
    delta_at_entry: float | None
    monthly_return_pct: float
    earnings_buffer_days: int | None
    compliant: bool
    failed_rules: list[str]
    entry_rules_snapshot: dict


class EntryComplianceSummary(BaseModel):
    """Rolling-window KR-5 summary.

    ``compliant_pct`` is ``None`` when ``(total - unknown_only) == 0`` — the
    OKR engine renders that as the ``unknown`` status (#157 will close the
    loop on the consumer side).
    """

    window_days: int  # 30 for the V1 endpoint
    total: int
    compliant: int
    unknown_only: int  # excluded from denominator
    compliant_pct: float | None


class EntryComplianceListResponse(BaseModel):
    """Response shape for ``GET /api/okrs/entry-compliance`` (rolling 30d)."""

    summary: EntryComplianceSummary
    non_compliant: list[EntryComplianceResponse]


class PositionResponse(BaseModel):
    id: str
    ticker: str
    shares: int
    broker_cost_basis: float
    status: str
    strategy: str
    opened_at: str
    closed_at: Optional[str] = None
    notes: Optional[str] = None
    total_premiums: float
    adjusted_cost_basis: float
    # Per-share basis (issue #320): round(total / shares, 4), null when
    # shares == 0. Mirrors the covered-call/action-engine convention
    # (covered_call.py:276) so per-share rounding has a single source of truth.
    broker_cost_basis_per_share: Optional[float] = None
    adjusted_cost_basis_per_share: Optional[float] = None
    min_compliant_cc_strike: float
    trades: list[TradeResponse] = []


class PositionListResponse(BaseModel):
    positions: list[PositionResponse]


# --- Schwab Import ---


class ImportPreviewTrade(BaseModel):
    ticker: str
    trade_type: TRADE_TYPES
    strike: float
    expiration: str
    premium: float
    fees: float
    quantity: int
    opened_at: str
    is_duplicate: bool


class ImportPreviewResponse(BaseModel):
    account_number: str  # masked "****1234"
    trades: list[ImportPreviewTrade]
    total: int
    duplicates: int
    new_count: int


class ImportRequest(BaseModel):
    """Request body for ``POST /api/journal/import``.

    ``position_strategy`` is **deprecated** as of issue #131 — the recomputer
    derives the displayed label from each position's state. The field is
    retained on the request schema so older clients that still send it do
    not 422; the value is silently ignored by the handler.
    """

    start_date: str
    end_date: str
    position_strategy: Optional[STRATEGY_TYPES] = None  # deprecated; ignored

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v):
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError("Date must be in YYYY-MM-DD format")
        return v


class ImportResultResponse(BaseModel):
    imported: int
    skipped_duplicates: int
    positions_created: int


class ClearJournalResponse(BaseModel):
    """Pre-delete row counts returned by ``DELETE /api/journal/all``."""

    deleted_positions: int
    deleted_trades: int


# --- Reconcile journal (issue #139) ---


class ReconcileRequest(BaseModel):
    """Request body for ``POST /api/journal/reconcile``.

    ``dry_run`` defaults to ``True`` so an accidental empty body never
    mutates state — the user must opt in to ``apply=True`` semantics by
    setting ``dry_run=False``.
    """

    dry_run: bool = True


class ReconcilePositionDiff(BaseModel):
    """Per-position before/after snapshot for the reconcile result.

    Field shape mirrors :class:`app.services.reconcile.ReconcilePositionDiff`
    so the route handler can do a trivial dataclass→model conversion.
    """

    ticker: str
    status_before: str
    status_after: str
    shares_before: int
    shares_after: int
    basis_before: float
    basis_after: float
    strategy_before: str
    strategy_after: str
    closed_at_before: Optional[str] = None
    closed_at_after: Optional[str] = None
    legs_consumed: int


class ReconcileResponse(BaseModel):
    """Response body for ``POST /api/journal/reconcile``."""

    dry_run: bool
    positions_processed: int
    trades_stamped: int
    status_changes: int
    share_corrections: int
    basis_corrections: int
    strategy_changes: int
    errors: int
    per_position: list[ReconcilePositionDiff] = []


# --- Dashboard ---


DASHBOARD_OPTION_TYPE = Literal["put", "call"]
DASHBOARD_MONEYNESS_STATE = Literal["ITM", "ATM", "OTM"]
DASHBOARD_ACTIVITY_KIND = Literal["session_saved", "trade_added"]
DASHBOARD_PROFIT_TARGET_STATE = Literal[
    "captured_50", "in_progress", "underwater", "unknown"
]
DASHBOARD_ASSIGNMENT_RISK = Literal["high", "watch", "low"]
# Per spec §14.5: V0.5 never emits "close" (live option-chain integration
# deferred). Frontend renders "—" when state == "unknown". The Literal
# enumerates every legal value the field may eventually carry.
DASHBOARD_SUGGESTED_ACTION = Literal["roll", "close", "hold", "manage"]
DASHBOARD_WHEEL_STATUS = Literal["CSP", "CC", "Wheel", "Holding"]
DASHBOARD_ACTION_ID = Literal[
    "data.schwab_disconnected",
    "data.cache_very_stale",
    "data.schwab_token_expiring",
    "position.large_loser",
    "expiration.itm_short_dte",
    "expiration.short_dte",
    "position.cc_candidate",
    "journal.no_open_legs",
    # New in V1.0.4 (#240) — the §R6 rule-monitor action cards.
    "leg.profit_take_review",
    "leg.dte_review",
]
DASHBOARD_ACTION_PRIORITY = Literal["P0", "P1", "P2"]
DASHBOARD_ACTION_CTA_KIND = Literal["link", "inline"]
# New in V1.0.4 (#240) — the per-leg §R6 rule-monitor verdict layer.
DASHBOARD_VERDICT = Literal[
    "hold", "profit_take_review", "dte_review", "expiration", "assignment"
]
DASHBOARD_RULE_STATUS = Literal["triggered", "not_yet", "no"]
DASHBOARD_RULE_ID = Literal[
    "profit_review", "dte_review", "expiration_warning", "assignment_risk"
]
# Card valence — `priority` ranks urgency, `tone` carries valence (§4.3 Q6).
DASHBOARD_ACTION_TONE = Literal["opportunity", "warning"]


class DashboardSchwabStatus(BaseModel):
    configured: bool
    valid: bool
    expires_at: Optional[str] = None
    # Issue #277: non-null when live Schwab calls (quotes / option chains)
    # failed during this dashboard load. The frontend uses this as a
    # discriminator to render "Schwab calls failing" vs the legacy
    # "Schwab token expiring" warn label. Optional + defaulted so older
    # callers / tests that omit the field still validate.
    error: Optional[str] = None


class DashboardFredStatus(BaseModel):
    configured: bool
    valid: bool


class DashboardCacheStatus(BaseModel):
    fresh: int
    stale: int
    very_stale: int
    total: int


class DashboardJournalStatus(BaseModel):
    positions_count: int


class DashboardStatus(BaseModel):
    schwab: DashboardSchwabStatus
    fred: DashboardFredStatus
    cache: DashboardCacheStatus
    journal: DashboardJournalStatus


class DashboardOpenPositionsBreakdown(BaseModel):
    """Open-positions count split by derived strategy label.

    ``stock`` is a vestigial bucket from before #131 that is never
    incremented (no position has ``strategy="stock"``); kept here for
    response-shape stability while the frontend consumers are tracked into
    a follow-up. ``holding`` was added in #131 for positions that hold
    shares with no open option legs.
    """

    stock: int
    csp: int
    cc: int
    wheel: int
    holding: int


class DashboardOpenLegsBreakdown(BaseModel):
    puts: int
    calls: int


class DashboardKpiLargestRisk(BaseModel):
    """Tile payload for the "Largest risk" KPI (worst unrealized loser)."""

    ticker: str
    unrealized_pl: float
    unrealized_pl_pct: Optional[float] = None


class DashboardKpiLargestLoser(BaseModel):
    """Tile payload for the largest realized loser across closed positions."""

    ticker: str
    realized_pl: float
    realized_pl_pct: Optional[float] = None


class DashboardKpis(BaseModel):
    open_positions: int
    open_positions_breakdown: DashboardOpenPositionsBreakdown
    notional_value: float
    notional_change_pct: Optional[float] = None
    open_legs: int
    open_legs_breakdown: DashboardOpenLegsBreakdown
    unrealized_pl: Optional[float] = None
    unrealized_pl_pct: Optional[float] = None
    # New in V0.5.4 — see decision-dashboard-v05.md §2.3 / §14.4
    largest_risk: Optional[DashboardKpiLargestRisk] = None
    largest_loser: Optional[DashboardKpiLargestLoser] = None
    premium_collected_total: float = 0.0
    premium_collected_ytd: float = 0.0
    premium_collected_trades: int = 0
    realized_pl: float = 0.0
    realized_pl_pct: Optional[float] = None


class DashboardPositionRow(BaseModel):
    id: str
    ticker: str
    shares: int
    strategy: str
    adjusted_cost_basis: float
    current_price: Optional[float] = None
    notional: Optional[float] = None
    unrealized_pl: Optional[float] = None
    open_legs_count: int
    # New in V0.5.4 — see decision-dashboard-v05.md §14.6
    wheel_status: DASHBOARD_WHEEL_STATUS
    next_suggested_action: str = "hold"
    pl_pct: Optional[float] = None
    # New in V0.5.4 (#151) — exposes broker basis for the dual-line
    # cost-basis cell ("line 1: broker; line 2: adjusted, muted").
    # Optional because cash-secured-put rows have no broker basis yet.
    broker_cost_basis: Optional[float] = None
    # New in v1.7.0 (#320) — per-share basis so the cost-basis cell aligns
    # 1:1 with the per-share Current column. round(total / shares, 4); null
    # when shares == 0 (cash-secured rows render "cash-secured", not a divide).
    broker_cost_basis_per_share: Optional[float] = None
    adjusted_cost_basis_per_share: Optional[float] = None


class DashboardMoneyness(BaseModel):
    state: DASHBOARD_MONEYNESS_STATE
    distance_pct: float
    distance_dollars: float


class DashboardProfitTargetStatus(BaseModel):
    """Per-leg profit-target signal.

    V0.5 always sets ``state == "unknown"`` because live option-chain data
    is not yet integrated. The field shape ships so frontend renderers and
    the V0.7 live-chain work have a stable contract.
    """

    captured_pct: Optional[float] = None
    state: DASHBOARD_PROFIT_TARGET_STATE


class DashboardRuleEvaluation(BaseModel):
    """One §R6 management rule evaluated against an open leg (issue #240).

    Emitted fired and not-fired alike — the inspect panel renders every rule,
    including the ones that did not fire, so the table reads as a monitor and
    not just an alert list. ``reasoning`` is present only on the single
    governing (highest-precedence triggered) rule.
    """

    rule_id: DASHBOARD_RULE_ID
    metric_label: str
    value_display: str
    rule_display: str
    status: DASHBOARD_RULE_STATUS
    is_governing: bool = False
    reasoning: Optional[str] = None


class DashboardOpenLeg(BaseModel):
    id: str
    ticker: str
    type: DASHBOARD_OPTION_TYPE
    strike: float
    expiration: str
    dte: int
    moneyness: Optional[DashboardMoneyness] = None
    position_id: str
    # New in V0.5.4 — see decision-dashboard-v05.md §14.5
    profit_target_status: DashboardProfitTargetStatus
    assignment_risk: DASHBOARD_ASSIGNMENT_RISK
    suggested_action: DASHBOARD_SUGGESTED_ACTION
    earnings_in_window: bool = False
    # Contract count for the leg. Strict `int = 1` (not Optional) — the dict
    # pass-through at `dashboard_legs.py:479` already coerces via
    # `int(trade.get("quantity") or 1)`. Logically part of the core leg shape;
    # predates the V1.0.6 economics block below. Made explicit in V1.0.8 (#252)
    # so the InspectPanel `Credit received` line can scale by quantity.
    quantity: int = 1
    # New in V1.0.4 (#240) — the §R6 rule-monitor verdict layer. All four
    # fields default so older payloads / tests that omit them still validate.
    verdict: DASHBOARD_VERDICT = "hold"
    verdict_label: str = "Hold"
    reasoning: str = "No management rule has triggered for this leg yet."
    triggered_rules: list[DashboardRuleEvaluation] = []
    # New in V1.0.6 (#246) — coverage severity + dollar economics. All four
    # default so older payloads / tests that omit them still validate.
    # coverage: "covered" / "partial" / "naked" for a short call by
    # Position.shares vs. quantity × 100; None for a short put. premium is
    # the per-share credit booked at open. pnl_dollars / cost_to_close are
    # whole-position dollars (per-share value × 100 × quantity); both None
    # whenever % CAPT is unavailable. ``partial`` (V1.0.8 / #251) covers the
    # 0 < shares < quantity × 100 range — see dashboard_legs.derive_leg_economics.
    coverage: Optional[Literal["covered", "partial", "naked"]] = None
    premium: Optional[float] = None
    pnl_dollars: Optional[float] = None
    cost_to_close: Optional[float] = None


class DashboardNextActionSubject(BaseModel):
    """Structured subject identifier for a Next Action card.

    Both fields are optional — the engine emits whichever signals are
    available for the action type. ``amount`` is a preformatted display
    string (e.g. ``"-$1,420 (-7.2%)"``) so the frontend renders it verbatim.
    """

    ticker: Optional[str] = None
    amount: Optional[str] = None


class DashboardNextActionCta(BaseModel):
    """CTA on a Next Action card.

    ``kind == "link"`` navigates to ``href``; ``kind == "inline"`` invokes
    a known client-side handler keyed by ``action_id`` (e.g. cache-refresh).
    """

    label: str
    href: str
    kind: DASHBOARD_ACTION_CTA_KIND = "link"


class DashboardNextAction(BaseModel):
    """One entry in the dashboard's ranked action engine output."""

    id: str  # stable React key, derived from "{action_id}.{subject_id}"
    action_id: DASHBOARD_ACTION_ID
    priority: DASHBOARD_ACTION_PRIORITY
    title: str
    subject: DashboardNextActionSubject = DashboardNextActionSubject()
    reason: str
    cta: DashboardNextActionCta
    # New in V1.0.4 (#240). ``tone`` defaults to "warning" so every existing
    # card (expiration.*, data.*, position.*, journal.*) is schema-valid and
    # visually unchanged. ``triggered_rules`` is the §R6 evaluation payload
    # carried by the two leg.* cards (empty for every other card type).
    tone: DASHBOARD_ACTION_TONE = "warning"
    triggered_rules: list[DashboardRuleEvaluation] = []


class DashboardActivity(BaseModel):
    kind: DASHBOARD_ACTIVITY_KIND
    timestamp: str
    # session_saved
    session_name: Optional[str] = None
    session_id: Optional[str] = None
    # trade_added
    ticker: Optional[str] = None
    trade_type: Optional[str] = None
    position_id: Optional[str] = None


class DashboardDataMeta(BaseModel):
    is_stale: bool
    fetched_at: str
    sources_unavailable: list[str] = []


class DashboardResponse(BaseModel):
    generated_at: str
    status: DashboardStatus
    kpis: DashboardKpis
    positions: list[DashboardPositionRow]
    open_legs: list[DashboardOpenLeg]
    recent_activity: list[DashboardActivity]
    data_meta: DashboardDataMeta
    # New in V0.5.4 — server-side ranked action engine output. See
    # decision-dashboard-v05.md §2.2 / §14.7.
    next_actions: list[DashboardNextAction] = []


# --- Recovery Plan (V0.5.8, issue #182) ---

RECOVERY_PLAN_STATE = Literal["populated", "not-applicable", "not-flagged"]
RECOVERY_PATH_SLUG = Literal[
    "sell-redeploy",
    "wheel-cc",
    "average-down",
    "hold-monitor",
]
RECOVERY_PATH_ELIGIBILITY = Literal["eligible", "suppressed"]
RECOVERY_SCORING_CRITERION = Literal[
    "fastest_breakeven",
    "lowest_additional_capital",
    "lowest_opportunity_cost",
    "strategy_preference_bonus",
]


class RecoveryMonthsRange(BaseModel):
    """Three-point breakeven uncertainty range emitted per path.

    Every component may be ``None`` (e.g. hold-monitor has no breakeven
    because it takes no action).
    """

    best: Optional[float] = None
    expected: Optional[float] = None
    worst: Optional[float] = None


class RecoveryPath(BaseModel):
    """One forward path the engine emits for an underwater position.

    Suppressed paths remain in ``paths[]`` but are never selected as the
    recommended path. Frontend renders them with a de-emphasized treatment.
    """

    path_id: RECOVERY_PATH_SLUG
    label: str
    eligibility: RECOVERY_PATH_ELIGIBILITY
    suppression_reason: Optional[str] = None
    capital_tied_up: Optional[float] = None
    months_to_breakeven: RecoveryMonthsRange
    opportunity_cost_vs_baseline: Optional[float] = None
    assumptions: list[str] = Field(default_factory=list)
    # V0.6 (#181) fills this slot; reserved as None in V0.5.8.
    narration: Optional[str] = None


class RecoveryPositionSummary(BaseModel):
    """Header summary the page chrome renders above the comparison cards."""

    id: str
    ticker: str
    shares: int
    adjusted_cost_basis: float
    current_price: Optional[float] = None
    unrealized_pl: Optional[float] = None
    pl_pct: Optional[float] = None


class RecoveryOkrInputs(BaseModel):
    """Snapshot of OKR settings consumed by the engine + scoring layer.

    Sizing cap (issue #234, V1 contract)
    ------------------------------------
    The sizing cap is no longer a stored dollar amount — it is a percent of
    total capital resolved at evaluation time against the connected Schwab
    account's net-liquidation value. The five sizing-cap fields below mirror
    the shape the recovery-engine + Settings UI consume:

    - ``sizing_cap_pct`` — whole-percent (e.g. ``25.0``).
    - ``total_capital`` — Schwab net-liquidation value (``None`` when the
      account-value cache is unavailable: disconnected / expired / error).
    - ``resolved_sizing_cap_dollars`` — ``sizing_cap_pct × total_capital ÷ 100``
      (``None`` when ``total_capital`` is unavailable).
    - ``account_id_masked`` — the selected account's masked id (``"…4471"``);
      ``None`` when no account is in use or the cache is unavailable.
    - ``capital_status`` — discriminator on the account-value resolution.
    """

    target_yield: Optional[float] = None
    strategy_preference: Optional[str] = None
    sizing_cap_pct: float = Field(
        ..., description="Sizing cap as percent of total capital"
    )
    total_capital: Optional[float] = Field(
        None,
        description="Resolved Schwab account net-liquidation value; None when unavailable",
    )
    resolved_sizing_cap_dollars: Optional[float] = Field(
        None,
        description="sizing_cap_pct × total_capital ÷ 100; None when capital unavailable",
    )
    account_id_masked: Optional[str] = Field(
        None,
        description="The selected account's masked id (e.g. '…4471'); None when no account in use",
    )
    capital_status: Literal["ok", "disconnected", "expired", "error"] = Field(
        "error",
        description="Schwab account value resolution status",
    )


class RecoveryInputs(BaseModel):
    """Echo of the deterministic inputs that drove the response."""

    current_price: Optional[float] = None
    cost_basis: Optional[float] = None
    shares: int
    okr: RecoveryOkrInputs


class RecoveryPathScoreCell(BaseModel):
    """One cell in the criterion × eligible-path matrix."""

    path_id: RECOVERY_PATH_SLUG
    raw_value: Optional[float] = None
    points: int
    rank: int


class RecoveryPathScoreRow(BaseModel):
    """One criterion row in the scoring matrix (one entry per criterion)."""

    criterion: RECOVERY_SCORING_CRITERION
    weight: int
    ranking: list[RecoveryPathScoreCell] = Field(default_factory=list)


class RecoveryRankedPath(BaseModel):
    """One entry in the recommendation's total-ranking list.

    Suppressed paths have ``score`` and ``rank`` of ``None`` and carry the
    ``suppression_reason`` straight from the engine.
    """

    path_id: RECOVERY_PATH_SLUG
    score: Optional[int] = None
    rank: Optional[int] = None
    suppression_reason: Optional[str] = None


class RecoveryRecommendation(BaseModel):
    """Deterministic recommendation object layered on top of the path list."""

    recommended_path_id: Optional[RECOVERY_PATH_SLUG] = None
    recommendation_label: str
    recommendation_reasons: list[str] = Field(default_factory=list)
    ranked_paths: list[RecoveryRankedPath] = Field(default_factory=list)
    path_scores: list[RecoveryPathScoreRow] = Field(default_factory=list)
    tie_epsilon: float = 1.0
    disclaimer: str


class RecoveryAssumptionRow(BaseModel):
    """One row in the Assumptions panel (audit surface)."""

    label: str
    value: str
    source: str


class RecoveryPlanResponse(BaseModel):
    """Top-level response for ``POST /api/positions/{id}/recovery-plan``.

    ``state == "populated"`` is the only state that carries paths +
    recommendation. The other two short-circuit before the engine runs.
    """

    position_id: str
    as_of: str
    state: RECOVERY_PLAN_STATE
    position: Optional[RecoveryPositionSummary] = None
    inputs: Optional[RecoveryInputs] = None
    paths: list[RecoveryPath] = Field(default_factory=list)
    recommendation: Optional[RecoveryRecommendation] = None
    assumptions: list[RecoveryAssumptionRow] = Field(default_factory=list)
    disclaimer: Optional[str] = None


# --- Buy-to-close leg detail (V1.0.6, issue #244) ---

# The two delivered states the BTC endpoint returns a 200 body for. The
# 'not-found' state is delivered as an HTTP 404 with no body.
BTC_DETAIL_STATE = Literal["populated", "no-rule-triggered"]


class BtcLeg(BaseModel):
    """The open option leg the buy-to-close review is scoped to."""

    id: str
    position_id: str
    ticker: str
    strike: float
    option_type: Literal["C", "P"]
    contracts: int
    expiration: str
    dte: int
    moneyness: str  # 'OTM' | 'ITM' | 'ATM' | 'Unknown'
    position_label: str


class BtcEconomics(BaseModel):
    """Buy-to-close economics for the leg.

    ``credit_received`` is always real (static, from the opening trade row).
    The pricing-dependent fields are ``None`` when no live option mark is
    available — the frontend renders the em-dash + "Pricing unavailable"
    treatment in that case (spec §5.3 Q4).
    """

    credit_received: float
    current_option_mid: Optional[float] = None
    cost_to_close: Optional[float] = None
    captured_pct: Optional[float] = None
    est_pl_if_closed: Optional[float] = None
    pricing_as_of: Optional[str] = None
    pricing_source: Literal["live", "stub", "unavailable"]


class BtcAnalysisScenario(BaseModel):
    """One assign-vs-buy-to-close scenario row (issue #319).

    All money figures are whole-position dollars (per-share × contracts × 100)
    to match the economics block convention. ``delta = btc_and_hold -
    let_assign``; ``winner`` is ``"btc"`` when ``delta > 0``, ``"assign"`` when
    ``delta < 0``, ``"tie"`` at exact breakeven.
    """

    underlying: float  # S_e — underlying at this expiration scenario
    label: str  # "−10%" | "Flat" | "+5%" | "+10%"
    let_assign: float  # K × n × 100  (whole-position $)
    btc_and_hold: float  # (S_e − O) × n × 100  (whole-position $)
    delta: float  # btc_and_hold − let_assign (signed; >0 ⇒ BTC wins)
    winner: Literal["btc", "assign", "tie"]


class BtcAnalysis(BaseModel):
    """BTC decision-math block: decomposition, breakeven, scenarios (issue #319).

    ``available`` gates the panel: ``False`` when neither a live option mid nor
    an underlying price is resolvable. When ``available`` is ``True`` but the
    option mid is missing (illiquid strike / greek-null), ``intrinsic`` is still
    populated while ``extrinsic`` / ``btc_breakeven`` / ``scenarios`` degrade to
    null / empty. Per-share figures (intrinsic / extrinsic / option_mid) are NOT
    scaled; the scenario dollars ARE (× contracts × 100).
    """

    available: bool
    intrinsic: Optional[float] = None
    extrinsic: Optional[float] = None
    extrinsic_pct_of_mid: Optional[float] = None
    option_mid: Optional[float] = None
    btc_breakeven: Optional[float] = None
    underlying: Optional[float] = None
    breakeven_delta: Optional[float] = None
    scenarios: list[BtcAnalysisScenario] = Field(default_factory=list)


class BtcDetailResponse(BaseModel):
    """Top-level response for ``GET /api/positions/{id}/legs/{legId}/btc``.

    Composes the leg identity, the §R6 rule-monitor verdict + audit (reused
    verbatim from :func:`app.services.rule_monitor.evaluate_leg_rules` via
    ``derive_open_legs``), the buy-to-close economics block, and the BTC
    decision-math analysis block (issue #319). A 404 with
    ``{"detail": "Leg not found"}`` is returned for an unknown / closed leg.
    """

    state: BTC_DETAIL_STATE
    leg: BtcLeg
    verdict: DASHBOARD_VERDICT
    economics: BtcEconomics
    analysis: BtcAnalysis
    triggered_rules: list[DashboardRuleEvaluation] = Field(default_factory=list)
    disclaimer: Optional[str] = None


# --- Combined covered-call P&L + if-assigned (V1.0.6, issue #247) ---

# The four states the covered-call endpoint can resolve a position into. The
# "covered_call" bucket carries real today/if-assigned blocks; the three
# not_applicable_* buckets carry empty blocks and drive the screen's
# EmptyState rendering (spec §7).
COVERED_CALL_APPLICABILITY = Literal[
    "covered_call",
    "not_applicable_no_shares",
    "not_applicable_no_short_call",
    "not_applicable_closed",
]


class CoveredCallPositionSummary(BaseModel):
    """Position-identity block on the covered-call response (spec §5.2).

    ``broker_cost_basis`` here is **per-share** — the screen divides the
    stored total by ``shares`` so the downstream consumers can multiply by
    share count again without surprises. ``current_price`` is ``None`` in
    the no-live-quote degraded path; the timestamp goes ``None`` in lockstep.
    """

    id: str
    ticker: str
    shares: int
    broker_cost_basis: float
    current_price: Optional[float] = None
    current_price_stale: bool = False
    current_price_as_of: Optional[str] = None


class CoveredCallToday(BaseModel):
    """The "today — unrealized" block (spec §3.2 left card).

    Each field degrades to ``None`` per spec §5.5: ``stock_pnl`` when
    ``current_price`` is missing, ``options_pnl`` when any open leg's
    ``pnl_dollars`` is missing, ``combined_pnl`` when either side is missing.
    """

    stock_pnl: Optional[float] = None
    options_pnl: Optional[float] = None
    combined_pnl: Optional[float] = None


class CoveredCallIfAssignedLeg(BaseModel):
    """One open-short-call leg's if-assigned projection (spec §5.2 / §7).

    ``shares_called`` is capped at the position's available shares by
    :func:`app.services.covered_call._allocate_shares_called` —
    earliest-expiring-first (Q6) when multiple legs exist. ``premium_kept``
    is independent of ``shares_called``: the credit booked at open stays
    with the seller whether or not THIS leg's shares end up called.
    ``if_assigned_pnl`` is ``None`` when premium is missing or the leg has
    already expired (those legs are excluded from the array).
    """

    leg_id: str
    strike: float
    premium: float
    qty: int
    shares_called: int
    share_pnl: float
    premium_kept: float
    if_assigned_pnl: Optional[float] = None


class CoveredCallLegBreakdown(BaseModel):
    """One row of the per-leg breakdown table (spec §3.3).

    Mirrors the dashboard's `DashboardOpenLeg` fields the breakdown table
    reuses — ``coverage`` and ``pnl_dollars`` from #246 — plus the per-leg
    ``if_assigned_pnl`` (``None`` for a non-short-call leg, an expired leg,
    or a leg with no booked premium).
    """

    leg_id: str
    ticker: str
    strike: float
    type: Literal["call", "put"]
    dte: int
    coverage: Optional[Literal["covered", "partial", "naked"]] = None
    pnl_dollars: Optional[float] = None
    if_assigned_pnl: Optional[float] = None


class CoveredCallView(BaseModel):
    """Top-level response for ``GET /api/positions/{id}/covered-call``.

    Composes the position summary, the today block, the if-assigned per-leg
    projections, the per-leg breakdown rows, and the applicability flag the
    frontend keys its state machine off. The disclaimer sentence (spec §3.6)
    is shipped in the payload so the frontend renders the house framing
    rule verbatim.
    """

    position: CoveredCallPositionSummary
    combined_today: CoveredCallToday
    if_assigned: list[CoveredCallIfAssignedLeg] = Field(default_factory=list)
    per_leg_breakdown: list[CoveredCallLegBreakdown] = Field(
        default_factory=list
    )
    applicability: COVERED_CALL_APPLICABILITY
    disclaimer: Optional[str] = None


# --- Research (#280) ---


# Maximum thesis body length per the issue #280 plan §4.3 (locked decision 4
# from the user). Enforced both via the Pydantic field constraint on the PUT
# request and on the response-shaping path so the cap is never side-stepped.
THESIS_MAX_BODY_LENGTH: int = 4000


class ThesisPutRequest(BaseModel):
    """Request body for ``PUT /api/positions/{id}/research/thesis``.

    ``thesis`` is the freeform note body. Empty strings are explicitly
    allowed (they clear the note) — the plan does not forbid empty bodies.
    Pydantic enforces the 4000-character ceiling at request validation
    time; oversize bodies return ``422`` automatically. The router layer
    re-validates server-side for defence in depth, so callers that bypass
    the model still get a sanitized 422.
    """

    thesis: str = Field(default="", max_length=THESIS_MAX_BODY_LENGTH)


class ThesisResponse(BaseModel):
    """Response shape for thesis GET + PUT (issue #280 PRD §F).

    When no row exists yet the endpoint returns ``thesis=None``,
    ``updated_at=None``, and ``version=0`` — the spec calls for an
    empty-state shape rather than a 404 so the frontend can render the
    editor immediately.
    """

    thesis: Optional[str] = None
    updated_at: Optional[str] = None
    version: int = 0

class BusinessResponse(BaseModel):
    """Response shape for ``GET /api/positions/{id}/research/business``.

    The payload is composed by :func:`app.services.research_business.
    build_business_payload`. Every yfinance field is ``Optional`` because the
    upstream is known for missing keys on foreign listings / newly-listed
    tickers (plan §8 risk #1). The router never propagates a yfinance error
    string — see :class:`app.services.research_business.
    ResearchSourceUnavailable` for the sanitized 502 detail.
    """

    ticker: str
    name: Optional[str] = None
    summary: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[float] = None
    employees: Optional[int] = None
    source: str
    fetched_at: str


class FinancialQuarter(BaseModel):
    """One quarter of normalized fundamentals on the Section D scorecard.

    Margins (``gross_margin`` / ``operating_margin``) are derived ratios in
    [0, 1]; ``revenue`` and ``eps`` flow through verbatim from the upstream.
    Any individual field can be ``None`` when the source omits the underlying
    value — the frontend renders ``—`` rather than fabricating a zero
    (per :func:`app.services.research_financials._safe_float`).
    """

    period_end: Optional[str] = None
    revenue: Optional[float] = None
    eps: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None


class FinancialsResponse(BaseModel):
    """Response shape for ``GET /api/positions/{id}/research/financials``.

    ``source`` is ``"alphavantage"`` on the primary path and ``"yfinance"``
    on the fallback path. The frontend renders provenance via Section D's
    source caption ("Source: alphavantage · refreshed …" or "Source:
    yfinance (alphavantage rate-limited) · refreshed …"). Up to 8 quarters
    are returned, newest first — see plan §4.2.
    """

    ticker: str
    quarters: list[FinancialQuarter] = Field(default_factory=list)
    source: str
    fetched_at: str


# --- watchlist ---


class WatchlistResponse(BaseModel):
    """Response shape for every watchlist endpoint (issue #321 / PRD #213 R4).

    All three routes — ``GET``, ``POST``, ``DELETE`` — return the full,
    current watchlist so the caller never has to issue a follow-up read after
    a mutation. ``tickers`` is uppercase-normalized and returned in a stable
    order (oldest-added first). Defaults to an empty list, which is the
    correct representation of "the trader hasn't approved any names yet"
    (PRD #213: an empty watchlist is a valid state, not an error).
    """

    tickers: list[str] = Field(default_factory=list)


class WatchlistAddRequest(BaseModel):
    """Request body for ``POST /api/watchlist`` (issue #321 / PRD #213 R2).

    ``ticker`` is normalized to uppercase and stripped of surrounding
    whitespace at this boundary, so the service layer can trust it is a
    non-empty uppercase symbol. A blank or whitespace-only ticker is rejected
    with ``422`` (the validator raises before the request reaches the route).
    """

    ticker: str = Field(..., description="Ticker symbol to add; normalized to uppercase.")

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, v: str) -> str:
        """Strip + uppercase the ticker; reject blank/whitespace-only input."""
        normalized = v.strip().upper()
        if not normalized:
            raise ValueError("ticker must not be empty")
        return normalized

