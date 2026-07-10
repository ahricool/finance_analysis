"""Configuration for the scheduled A-share pre-close review."""

from __future__ import annotations

from dataclasses import dataclass

TASK_TYPE = "scheduled_a_share_pre_close_review"
CALENDAR_TYPE = TASK_TYPE


@dataclass(frozen=True)
class PreCloseReviewConfig:
    """Business limits kept together so call volume and fallbacks are auditable."""

    max_quote_age_seconds: int = 8 * 60
    critical_quote_age_seconds: int = 20 * 60
    minimum_market_rows: int = 1000
    minimum_index_count: int = 2
    minimum_sector_count: int = 3
    history_days: int = 60
    minute_bar_count: int = 90
    minimum_minute_bars: int = 20
    max_strong_sectors: int = 5
    sector_ranking_scan_limit: int = 100
    max_candidates: int = 6
    max_board_lookups: int = 20
    max_news_entities: int = 10
    max_news_items_per_entity: int = 3
    web_llm_timeout_seconds: int = 180
    web_llm_attempts: int = 2
    task_time_limit_seconds: int = 10 * 60
    task_completion_reserve_seconds: int = 30
    recent_result_count: int = 3


DEFAULT_CONFIG = PreCloseReviewConfig()

# Daily proxies provide recent trend context without confusing index codes with
# same-numbered A-share stocks in generic historical-data APIs.
MARKET_TREND_PROXIES = {
    "510300": "沪深300ETF",
    "159915": "创业板ETF",
    "510500": "中证500ETF",
}

MAIN_INDEX_CODES = {
    "000001": "上证指数",
    "399001": "深证成指",
    "399006": "创业板指",
    "000300": "沪深300",
    "000688": "科创50",
}

ALLOWED_HOLDING_ACTIONS = {
    "maintain",
    "watch",
    "reduce",
    "add_on_condition",
    "exit_or_large_reduce",
}

ACTION_LABELS = {
    "maintain": "维持",
    "watch": "观察",
    "reduce": "降低",
    "add_on_condition": "条件满足后增加",
    "exit_or_large_reduce": "退出或大幅降低",
}

SECTOR_CONTINUITY_LABELS = {
    "breakout": "可延续突破",
    "trend": "趋势延续",
    "one_day_pulse": "一日脉冲",
    "surge_fade": "冲高回落",
    "high_divergence": "高位分歧",
    "uncertain": "待确认",
}
