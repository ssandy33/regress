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
    strike: float
    expiration: str
    rejection_reasons: list[str]


class MarketContext(BaseModel):
    vix: Optional[float] = None
    beta: Optional[float] = None
    fifty_two_week_high: Optional[float] = None
    fifty_two_week_low: Optional[float] = None
    daily_volume: Optional[int] = None


class OptionScanRequest(BaseModel):
    ticker: str
    strategy: str  # "cash_secured_put" | "covered_call"
    cost_basis: Optional[float] = None
    capital_available: Optional[float] = None
    shares_held: Optional[int] = 100
    min_dte: int = 25
    max_dte: int = 50
    min_return_pct: float = 1.0
    max_return_pct: Optional[float] = None
    min_call_distance_pct: float = 10.0
    max_delta: float = 0.35
    min_delta: float = 0.15
    exclude_earnings_dte: int = 5


class OptionScanResponse(BaseModel):
    ticker: str
    current_price: float
    strategy: str
    scan_time: str
    earnings_date: Optional[str] = None
    iv_rank: Optional[float] = None
    recommendations: list[StrikeRecommendation]
    rejected: list[RejectedStrike]
    market_context: MarketContext


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
DASHBOARD_DECISION_TAG = Literal["roll-or-assign", "manage", "watch", "hold"]
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
]
DASHBOARD_ACTION_PRIORITY = Literal["P0", "P1", "P2"]
DASHBOARD_ACTION_CTA_KIND = Literal["link", "inline"]


class DashboardSchwabStatus(BaseModel):
    configured: bool
    valid: bool
    expires_at: Optional[str] = None


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


class DashboardUpcomingExpiration(DashboardOpenLeg):
    decision_tag: DASHBOARD_DECISION_TAG
    decision_reason: str


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
    upcoming_expirations: list[DashboardUpcomingExpiration]
    recent_activity: list[DashboardActivity]
    data_meta: DashboardDataMeta
    # New in V0.5.4 — server-side ranked action engine output. See
    # decision-dashboard-v05.md §2.2 / §14.7.
    next_actions: list[DashboardNextAction] = []
