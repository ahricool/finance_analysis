"""Static runtime configuration and market specifications for the streamer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from finance_analysis.config.env_parsing import env_str
from finance_analysis.database.config import get_database_config
from finance_analysis.stocks.markets import MarketType


@dataclass(frozen=True, slots=True)
class MarketSpec:
    timezone: ZoneInfo
    regular_sessions: tuple[tuple[time, time], ...]
    cache_gap_tolerance: timedelta = timedelta(minutes=2)


MARKET_SPECS: dict[MarketType, MarketSpec] = {
    "CN": MarketSpec(
        timezone=ZoneInfo("Asia/Shanghai"),
        regular_sessions=((time(9, 30), time(11, 30)), (time(13), time(15))),
    ),
    "HK": MarketSpec(
        timezone=ZoneInfo("Asia/Hong_Kong"),
        regular_sessions=((time(9, 30), time(12)), (time(13), time(16))),
    ),
    "US": MarketSpec(
        timezone=ZoneInfo("America/New_York"),
        regular_sessions=((time(9, 30), time(16)),),
    ),
}


def market_spec(market_type: MarketType) -> MarketSpec:
    return MARKET_SPECS[market_type]


def market_timezone(market_type: MarketType) -> ZoneInfo:
    return market_spec(market_type).timezone


def market_trading_date(value: datetime, market_type: MarketType) -> date:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("market datetime must be timezone-aware")
    return value.astimezone(market_timezone(market_type)).date()


def latest_completed_bar_time(value: datetime, market_type: MarketType) -> datetime | None:
    """Return the expected latest regular-session minute start in UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("market datetime must be timezone-aware")
    spec = market_spec(market_type)
    local = value.astimezone(spec.timezone)
    current_minute = local.replace(second=0, microsecond=0)
    latest: datetime | None = None
    for session_start, session_end in spec.regular_sessions:
        start = datetime.combine(local.date(), session_start, tzinfo=spec.timezone)
        end = datetime.combine(local.date(), session_end, tzinfo=spec.timezone)
        if local <= start:
            break
        if local < end:
            candidate = current_minute - timedelta(minutes=1)
            if candidate >= start:
                latest = min(candidate, end - timedelta(minutes=1))
            break
        latest = end - timedelta(minutes=1)
    return latest.astimezone(ZoneInfo("UTC")) if latest is not None else None


def completed_regular_minutes(value: datetime, market_type: MarketType) -> int:
    """Count completed regular-session minutes, excluding lunch recesses."""
    expected = latest_completed_bar_time(value, market_type)
    if expected is None:
        return 0
    spec = market_spec(market_type)
    expected_local = expected.astimezone(spec.timezone)
    completed = 0
    for session_start, session_end in spec.regular_sessions:
        start = datetime.combine(expected_local.date(), session_start, tzinfo=spec.timezone)
        end = datetime.combine(expected_local.date(), session_end, tzinfo=spec.timezone)
        if expected_local < start:
            break
        completed += int((min(expected_local + timedelta(minutes=1), end) - start).total_seconds() // 60)
        if expected_local < end:
            break
    return completed


@dataclass(frozen=True, slots=True)
class MarketStreamConfig:
    redis_url: str
    watchlist_poll_seconds: int = 5
    heartbeat_seconds: int = 5
    leader_lock_ttl_seconds: int = 30
    redis_flush_interval_ms: int = 250
    warmup_concurrency: int = 3
    bar_limit: int = 420
    minimum_history_bars: int = 15
    subscription_state_ttl_seconds: int = 60
    removed_symbol_cache_ttl_seconds: int = 2 * 3600
    event_queue_size: int = 10_000

    @property
    def heartbeat_ttl_seconds(self) -> int:
        return max(30, self.heartbeat_seconds * 3)

    def __post_init__(self) -> None:
        if self.subscription_state_ttl_seconds <= self.heartbeat_seconds * 2:
            raise ValueError("subscription_state_ttl_seconds must exceed heartbeat_seconds * 2")
        if self.bar_limit < self.minimum_history_bars:
            raise ValueError("bar_limit must be at least minimum_history_bars")
        if self.event_queue_size < 1:
            raise ValueError("event_queue_size must be positive")

    @classmethod
    def from_env(cls) -> "MarketStreamConfig":
        """Read only connection configuration; runtime tuning stays in this module."""
        database = get_database_config()
        redis_url = (env_str("REALTIME_REDIS_URL", "") or "").strip() or database.redis_url
        return cls(redis_url=redis_url)
