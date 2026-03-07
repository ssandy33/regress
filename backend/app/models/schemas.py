from typing import Optional

from pydantic import BaseModel


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
    delta: float
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
    avg_volume: Optional[int] = None


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
