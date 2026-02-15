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


class CacheStatsResponse(BaseModel):
    entry_count: int
    total_size_bytes: int
    entries: list[dict]
