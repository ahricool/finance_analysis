# -*- coding: utf-8 -*-
"""Redis-backed execution locks for US intraday analysis."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from .config import (
    US_INTRADAY_RUNNING_LOCK_TTL_SECONDS,
    US_INTRADAY_WINDOW_LOCK_TTL_SECONDS,
)

logger = logging.getLogger(__name__)

RUNNING_LOCK_KEY = "us_intraday:running"

_MEMORY_LOCKS: Dict[str, Tuple[str, float]] = {}


@dataclass
class USIntradayExecutionLock:
    """Lock token for a running lock and a time-window lock."""

    running_key: str
    window_key: str
    running_token: str
    window_token: str
    client: Any = None
    uses_redis: bool = True


def build_window_lock_key(trading_date: str, window_time: str) -> str:
    return f"us_intraday:window:{trading_date}:{window_time}"


def try_acquire_us_intraday_lock(
    *,
    trading_date: str,
    window_time: str,
    client: Any = None,
) -> Optional[USIntradayExecutionLock]:
    """Acquire running and window locks, returning ``None`` on contention."""
    redis_client = client if client is not None else _redis_client()
    window_key = build_window_lock_key(trading_date, window_time)
    running_token = uuid.uuid4().hex
    window_token = uuid.uuid4().hex
    uses_redis = redis_client is not None

    if uses_redis:
        acquired_running = _redis_acquire(
            redis_client,
            RUNNING_LOCK_KEY,
            running_token,
            US_INTRADAY_RUNNING_LOCK_TTL_SECONDS,
        )
        if not acquired_running:
            return None
        acquired_window = _redis_acquire(
            redis_client,
            window_key,
            window_token,
            US_INTRADAY_WINDOW_LOCK_TTL_SECONDS,
        )
        if not acquired_window:
            _redis_release(redis_client, RUNNING_LOCK_KEY, running_token)
            return None
        return USIntradayExecutionLock(
            running_key=RUNNING_LOCK_KEY,
            window_key=window_key,
            running_token=running_token,
            window_token=window_token,
            client=redis_client,
            uses_redis=True,
        )

    acquired_running = _memory_acquire(
        RUNNING_LOCK_KEY,
        running_token,
        US_INTRADAY_RUNNING_LOCK_TTL_SECONDS,
    )
    if not acquired_running:
        return None
    acquired_window = _memory_acquire(window_key, window_token, US_INTRADAY_WINDOW_LOCK_TTL_SECONDS)
    if not acquired_window:
        _memory_release(RUNNING_LOCK_KEY, running_token)
        return None
    return USIntradayExecutionLock(
        running_key=RUNNING_LOCK_KEY,
        window_key=window_key,
        running_token=running_token,
        window_token=window_token,
        client=None,
        uses_redis=False,
    )


def release_us_intraday_running_lock(lock_token: Optional[USIntradayExecutionLock]) -> None:
    """Release only the running lock after checking the token."""
    if lock_token is None:
        return
    if lock_token.uses_redis:
        _redis_release(lock_token.client, lock_token.running_key, lock_token.running_token)
    else:
        _memory_release(lock_token.running_key, lock_token.running_token)


def _redis_client() -> Any:
    try:
        import redis

        from finance_analysis.database.config import get_database_config

        return redis.Redis.from_url(get_database_config().redis_url)
    except Exception as exc:
        logger.warning("无法创建 Redis 客户端用于美股盘中任务锁，降级为进程内锁: %s", exc)
        return None


def _redis_acquire(client: Any, key: str, token: str, ttl_seconds: int) -> bool:
    try:
        return bool(client.set(key, token, nx=True, ex=ttl_seconds))
    except Exception as exc:
        logger.warning("获取 Redis 锁失败 %s: %s", key, exc)
        return False


def _redis_release(client: Any, key: str, token: str) -> None:
    script = """
    if redis.call("GET", KEYS[1]) == ARGV[1] then
        return redis.call("DEL", KEYS[1])
    end
    return 0
    """
    try:
        client.eval(script, 1, key, token)
    except Exception as exc:
        logger.warning("释放 Redis 锁失败 %s: %s", key, exc)


def _memory_acquire(key: str, token: str, ttl_seconds: int) -> bool:
    now = time.monotonic()
    existing = _MEMORY_LOCKS.get(key)
    if existing is not None and existing[1] > now:
        return False
    _MEMORY_LOCKS[key] = (token, now + ttl_seconds)
    return True


def _memory_release(key: str, token: str) -> None:
    existing = _MEMORY_LOCKS.get(key)
    if existing is not None and existing[0] == token:
        _MEMORY_LOCKS.pop(key, None)
