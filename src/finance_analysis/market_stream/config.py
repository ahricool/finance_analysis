"""Environment-owned configuration for the standalone market streamer."""

from __future__ import annotations

from dataclasses import dataclass

from finance_analysis.config.env_parsing import env_int, env_str
from finance_analysis.database.config import get_database_config


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

    @classmethod
    def from_env(cls) -> "MarketStreamConfig":
        database = get_database_config()
        return cls(
            redis_url=(env_str("REALTIME_REDIS_URL", "") or "").strip() or database.redis_url,
            watchlist_poll_seconds=env_int("MARKET_STREAM_WATCHLIST_POLL_SECONDS", 5, minimum=1),
            heartbeat_seconds=env_int("MARKET_STREAM_HEARTBEAT_SECONDS", 5, minimum=1),
            leader_lock_ttl_seconds=env_int("MARKET_STREAM_LEADER_LOCK_TTL_SECONDS", 30, minimum=10),
            redis_flush_interval_ms=env_int(
                "MARKET_STREAM_REDIS_FLUSH_INTERVAL_MS", 250, minimum=100, maximum=5000
            ),
            warmup_concurrency=env_int("MARKET_STREAM_WARMUP_CONCURRENCY", 3, minimum=1, maximum=20),
            bar_limit=env_int("MARKET_STREAM_BAR_LIMIT", 420, minimum=15, maximum=1000),
        )
