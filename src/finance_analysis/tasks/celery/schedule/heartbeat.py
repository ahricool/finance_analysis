# -*- coding: utf-8 -*-
"""Redis heartbeat used by Celery Beat and the task center."""

from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

HEARTBEAT_KEY = "finance_analysis:celery:beat:heartbeat"
HEARTBEAT_INTERVAL_SECONDS = 30
HEARTBEAT_TTL_SECONDS = 90

_heartbeat_thread: Optional[threading.Thread] = None
_heartbeat_stop = threading.Event()


def _redis_client():
    try:
        import redis

        from finance_analysis.database.config import get_database_config

        return redis.Redis.from_url(get_database_config().redis_url)
    except Exception as exc:  # pragma: no cover - defensive connection guard
        logger.warning("无法创建 Redis 客户端用于 Beat 心跳: %s", exc)
        return None


def write_beat_heartbeat(client=None) -> bool:
    from finance_analysis.core.time import utc_isoformat, utc_now

    client = client or _redis_client()
    if client is None:
        return False
    try:
        client.set(HEARTBEAT_KEY, utc_isoformat(utc_now()) or "", ex=HEARTBEAT_TTL_SECONDS)
        return True
    except Exception as exc:  # pragma: no cover - network guard
        logger.warning("写入 Beat 心跳失败: %s", exc)
        return False


def read_beat_status(client=None) -> str:
    client = client or _redis_client()
    if client is None:
        return "unavailable"
    try:
        return "active" if client.get(HEARTBEAT_KEY) is not None else "unavailable"
    except Exception as exc:  # pragma: no cover - network guard
        logger.warning("读取 Beat 心跳失败: %s", exc)
        return "unavailable"


def _heartbeat_loop() -> None:
    client = _redis_client()
    write_beat_heartbeat(client)
    while not _heartbeat_stop.wait(HEARTBEAT_INTERVAL_SECONDS):
        if client is None:
            client = _redis_client()
        write_beat_heartbeat(client)


def start_beat_heartbeat() -> None:
    global _heartbeat_thread
    if _heartbeat_thread is not None and _heartbeat_thread.is_alive():
        return
    _heartbeat_stop.clear()
    _heartbeat_thread = threading.Thread(
        target=_heartbeat_loop,
        name="celery-beat-heartbeat",
        daemon=True,
    )
    _heartbeat_thread.start()
    logger.info("Beat 心跳线程已启动 (interval=%ss ttl=%ss)", HEARTBEAT_INTERVAL_SECONDS, HEARTBEAT_TTL_SECONDS)


def stop_beat_heartbeat() -> None:
    _heartbeat_stop.set()


__all__ = [
    "HEARTBEAT_INTERVAL_SECONDS",
    "HEARTBEAT_KEY",
    "HEARTBEAT_TTL_SECONDS",
    "read_beat_status",
    "start_beat_heartbeat",
    "stop_beat_heartbeat",
    "write_beat_heartbeat",
]
