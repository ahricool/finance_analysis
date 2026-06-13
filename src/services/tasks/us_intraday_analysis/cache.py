# -*- coding: utf-8 -*-
"""Redis-backed caching of intraday bars/metrics and signal de-duplication."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional, Sequence

from .bars import aggregate_bars
from .config import REDIS_TTL_SECONDS, SIGNAL_DEDUP_TTL_SECONDS, US_EASTERN

logger = logging.getLogger(__name__)


class IntradayCache:
    """Thin wrapper over Redis that degrades gracefully when unavailable."""

    def __init__(self, redis_client: Optional[Any]) -> None:
        self.redis = redis_client

    @classmethod
    def from_config(cls, config: Any) -> "IntradayCache":
        return cls(cls._create_redis_client(config))

    @staticmethod
    def _create_redis_client(config: Any) -> Optional[Any]:
        try:
            import redis

            return redis.Redis.from_url(
                getattr(config, "redis_url", "redis://localhost:6379/0"),
                decode_responses=True,
            )
        except Exception as exc:
            logger.warning("Redis 初始化失败，美股盘中缓存/去重将降级: %s", exc)
            return None

    def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        if self.redis is None:
            return None
        try:
            raw = self.redis.get(key)
            if not raw:
                return None
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except Exception as exc:
            logger.debug("Redis get json failed %s: %s", key, exc)
            return None

    def set_json(self, key: str, value: Any, *, ex: int) -> None:
        if self.redis is None:
            return
        try:
            self.redis.set(key, json.dumps(value, ensure_ascii=False), ex=ex)
        except Exception as exc:
            logger.debug("Redis set json failed %s: %s", key, exc)

    def cache_bars(self, symbol: str, trade_date: str, bars_1m: Sequence[Dict[str, Any]]) -> None:
        if self.redis is None:
            return
        for interval, bars in (
            (1, list(bars_1m)),
            (5, aggregate_bars(bars_1m, 5)),
            (15, aggregate_bars(bars_1m, 15)),
        ):
            self.set_json(
                f"intraday:bars:US:{symbol}:{trade_date}:{interval}m",
                bars,
                ex=REDIS_TTL_SECONDS,
            )

    def cache_latest(self, symbol: str, metrics: Dict[str, Any], trade_date: str) -> None:
        payload = {
            **metrics,
            "trade_date": trade_date,
            "cached_at": datetime.now(US_EASTERN).isoformat(),
        }
        self.set_json(f"intraday:latest:US:{symbol}", payload, ex=REDIS_TTL_SECONDS)

    def reserve_signal(self, symbol: str, signal_type: str) -> bool:
        """Atomically claim a signal slot; ``True`` means not seen recently."""
        if self.redis is None:
            return True
        key = f"intraday:dedup:US:{symbol}:{signal_type}"
        try:
            return bool(self.redis.set(key, "1", ex=SIGNAL_DEDUP_TTL_SECONDS, nx=True))
        except Exception as exc:
            logger.warning("Redis 信号去重失败，允许继续: %s", exc)
            return True
