"""Trend Following API contracts."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class TrendFollowingRunRequest(BaseModel):
    market: Literal["CN", "US"] = "CN"
    trade_date: date | None = None


class TrendBreadthPoint(BaseModel):
    trade_date: date
    rankable_count: int | None
    trend_breadth: float | None
    deterioration_breadth: float | None
    participation: float | None
    inactive: float | None
    emerging: float | None
    healthy: float | None
    deteriorating: float | None
    state_counts: dict[str, int]
    coverage: float | None
    warning: str | None
    is_preview: bool


class TrendBreadthResponse(BaseModel):
    market: Literal["CN", "US"]
    dates: list[date]
    official_count: int
    preview_date: date | None
    preview_time: datetime | None
    generated_at: datetime | None
    points: list[TrendBreadthPoint]
    warnings: list[str]


TrendState = Literal["IDLE", "WATCHING", "CANDIDATE", "TRENDING", "WEAKENING", "BROKEN"]


class TrendDashboardHighlight(BaseModel):
    code: str
    name: str | None
    previous_state: TrendState
    current_state: TrendState


class TrendDashboardChanges(BaseModel):
    previous_trade_date: date | None
    state_counts: dict[str, int]
    highlights: list[TrendDashboardHighlight] = Field(max_length=3)


class TrendDashboardFeatures(BaseModel):
    lifecycle_counts: dict[str, int] | None
    high_fragility_count: int | None


class TrendDashboardResponse(BaseModel):
    market: Literal["CN", "US"]
    trade_date: date
    market_regime: Literal["RISK_ON", "NEUTRAL", "RISK_OFF"]
    market_score: float
    score_breakdown: dict[str, float | None]
    features: TrendDashboardFeatures
    changes: TrendDashboardChanges


class TrendTransition(BaseModel):
    code: str
    name: str
    previous_state: TrendState
    current_state: TrendState
    previous_date: date
    trade_date: date
    previous_rank: int
    current_rank: int
    rank_delta: int
    alpha_score: float | None
    fragility_score: float | None
    direction: Literal["strengthening", "deteriorating"]
    priority: int
    is_preview: bool


class TrendTransitionsResponse(BaseModel):
    market: Literal["CN", "US"]
    days: int
    official_count: int
    preview_date: date | None
    warnings: list[str]
    items: list[TrendTransition]


BoxState = Literal["NONE", "BOX_FORMING", "BOX_READY", "BOX_BREAKOUT"]


class TrendRankingFeatures(BaseModel):
    box_breakout_fresh: bool | None = None
    box_prior_breakout_confirmed: bool | None = None
    box_episode_consumed: bool | None = None
    box_episode_breakout_date: str | None = None
    mr_state: Literal["MR_NONE", "MR_OVERSOLD", "MR_REBOUND"] | None = None
    mr_episode_consumed: bool | None = None
    rsi14: float | None = None
    distance_from_ma20_atr: float | None = None
    return_3d: float | None = None
    mr_quality: float | None = None
    mr_oversold_quality: float | None = None
    mr_distance_quality: float | None = None
    mr_shock_quality: float | None = None
    mr_reversal_quality: float | None = None
    mr_previous_rsi14: float | None = None
    box_state: BoxState | None = None
    box_start_date: str | None = None
    box_end_date: str | None = None
    box_quality: float | None = None
    box_window_days: int | None = None
    box_high: float | None = None
    box_low: float | None = None
    box_mid: float | None = None
    box_width_pct: float | None = None
    box_slope: float | None = None
    box_slope_atr: float | None = None
    box_r_squared: float | None = None
    box_occupancy: float | None = None
    box_upper_touches: int | None = None
    box_lower_touches: int | None = None
    distance_to_box_high_pct: float | None = None
    distance_to_box_high_atr: float | None = None
    box_breakout_distance_atr: float | None = None
    box_atr20: float | None = None
    box_width_quality: float | None = None
    box_flatness_quality: float | None = None
    box_occupancy_quality: float | None = None
    box_compression_quality: float | None = None
    box_touch_quality: float | None = None

    atr_percent: float | None = None
    close_location_value: float | None = None
    raw_volume_ratio: float | None = None
    projected_volume_ratio: float | None = None
    volume_provisional: bool | None = None
    pullback_detected: bool | None = None
    ma10_reclaimed: bool | None = None
    return_5d: float | None = None
    return_10d: float | None = None
    return_20d: float | None = None
    volume_ratio: float | None = None
    distance_from_ma20: float | None = None
    alpha_version: int | None = None
    path_score: float | None = None
    setup_score: float | None = None
    weighted_r2: float | None = None
    positive_return_concentration: float | None = None
    atr_expansion_ratio: float | None = None
    downside_control_quality: float | None = None
    downside_upside_ratio: float | None = None
    raw_weighted_slope: float | None = None
    weighted_slope_percentile: float | None = None
    drawdown_20d: float | None = None
    rs_5d: float | None = None
    rs_10d: float | None = None
    rs_20d: float | None = None
    ma10: float | None = None
    ma20: float | None = None
    ma10_slope: float | None = None
    ma20_slope: float | None = None
    trend_acceleration: float | None = None
    signed_efficiency_ratio_10d: float | None = None
    trend_candidate: bool | None = None
    prior_compression: bool | None = None
    compression_breakout: bool | None = None
    trend_resume: bool | None = None
    r2_quality: float | None = None
    momentum_quality: float | None = None
    return_10d_quality: float | None = None
    return_20d_quality: float | None = None
    drawdown_quality: float | None = None
    rs_5d_quality: float | None = None
    rs_10d_quality: float | None = None
    rs_20d_quality: float | None = None
    breakout_quality: float | None = None
    extension_quality: float | None = None
    volume_quality: float | None = None
    compression_quality: float | None = None
    concentration_quality: float | None = None
    volatility_quality: float | None = None
    alpha_trend_contribution: float | None = None
    alpha_rs_contribution: float | None = None
    alpha_setup_contribution: float | None = None
    alpha_path_contribution: float | None = None


class TrendRankingItem(BaseModel):
    entry_score: float | None = None
    entry_type: Literal["BREAKOUT", "PULLBACK_RESUME", "NONE"] | None = None
    code: str
    name: str | None = None
    rank: int
    state: TrendState | None = None
    trend_duration_days: int | None = None
    trend_lifecycle: str | None = None
    fragility_score: float | None = None
    alpha_score: float
    trend_score: float | None = None
    rs_score: float | None = None
    breakout_score: float | None = None
    setup: str | None = None
    atr: float | None = None
    reference_price: float | None = None
    features: TrendRankingFeatures


StrategyKey = Literal["TREND_FOLLOWING", "BOX_BREAKOUT", "PULLBACK_RESUME", "MEAN_REVERSION"]
EvaluationStatus = Literal["pending", "missing", "available"]


class StudyCoverage(BaseModel):
    feature_coverage: float | None
    feature_snapshot_count: int
    snapshot_count: int
    status: Literal["complete", "insufficient_feature_history"]
    continuous_complete_since: date | None
    incomplete_dates: list[date]


class StudyStatistics(BaseModel):
    mean: float | None
    median: float | None


class StudyHorizonAggregate(BaseModel):
    days: int
    matured_count: int
    excess_matured_count: int
    pending_count: int
    missing_count: int
    mean_return: float | None
    median_return: float | None
    win_rate: float | None
    mean_excess_return: float | None
    median_excess_return: float | None
    excess_win_rate: float | None


class StudyGroup(StudyCoverage):
    strategy: StrategyKey
    regime: Literal["ALL", "RISK_ON", "NEUTRAL", "RISK_OFF"]
    event_count: int
    horizons: list[StudyHorizonAggregate]
    mfe20: StudyStatistics
    mae20: StudyStatistics
    excursion_count: int


class StudyHorizon(BaseModel):
    days: int
    target_date: date
    status: EvaluationStatus
    value: float | None
    benchmark_status: EvaluationStatus
    benchmark_return: float | None
    excess_status: EvaluationStatus
    excess_return: float | None


class StudyEvent(BaseModel):
    market: Literal["CN", "US"]
    trade_date: date
    code: str
    name: str | None
    strategy: StrategyKey
    regime: Literal["RISK_ON", "NEUTRAL", "RISK_OFF"]
    signal_price: float
    evaluation_base_price: float | None
    context: dict[str, float | str | None]
    horizons: list[StudyHorizon]
    excursion_status: EvaluationStatus
    observed_sessions: int
    missing_dates: list[date]
    mfe20: float | None
    mae20: float | None


class EventStudyResponse(BaseModel):
    market: Literal["CN", "US"]
    start_date: date
    end_date: date
    method: Literal["signal_close_v1"]
    benchmark: str
    evaluated_at: datetime
    snapshot_dates: list[date]
    missing_snapshot_dates: list[date]
    box_feature_coverage: StudyCoverage
    mr_feature_coverage: StudyCoverage
    groups: list[StudyGroup]
    event_count: int
    events: list[StudyEvent]
    offset: int
    limit: int
