"""Redis cache for the latest Trend Following intraday preview. Never writes PostgreSQL."""  # pragma: allowlist secret

from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime
from typing import Any

from finance_analysis.core.time import utc_isoformat  # pragma: allowlist secret
from finance_analysis.trend_following.universe import normalize_market  # pragma: allowlist secret

logger = logging.getLogger(__name__)

PREVIEW_KEY_TEMPLATE = "trend_following:preview:{market}"
PREVIEW_TTL_SECONDS = 24 * 60 * 60


def preview_cache_key(market: str) -> str:
    return PREVIEW_KEY_TEMPLATE.format(market=normalize_market(market))


def json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if isinstance(value, datetime):
        return utc_isoformat(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    return str(value)


def save_preview(market: str, payload: dict[str, Any], *, client: Any | None = None) -> None:
    body = json.dumps(json_ready(payload), ensure_ascii=False, separators=(",", ":"))
    redis_client = client if client is not None else _redis_client()
    if redis_client is None:
        logger.error("market=%s job=trend_following_preview cache_write_failed redis_unavailable", market)
        raise RuntimeError(f"Trend Following preview Redis unavailable for {market}")
    try:
        redis_client.set(preview_cache_key(market), body, ex=PREVIEW_TTL_SECONDS)
    except Exception as exc:
        logger.exception("market=%s job=trend_following_preview cache_write_failed", market)
        raise RuntimeError(f"Failed to save Trend Following preview for {market}") from exc


def load_preview(market: str, *, client: Any | None = None) -> dict[str, Any] | None:
    redis_client = client if client is not None else _redis_client()
    if redis_client is None:
        return None
    try:
        raw = redis_client.get(preview_cache_key(market))
    except Exception:
        logger.exception("market=%s job=trend_following_preview cache_read_failed", market)
        return None
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    payload = json.loads(raw)
    return payload if isinstance(payload, dict) else None


def _redis_client() -> Any | None:
    try:
        import redis

        from finance_analysis.database.config import get_database_config  # pragma: allowlist secret

        return redis.Redis.from_url(get_database_config().redis_url, decode_responses=True)
    except Exception:
        logger.exception("job=trend_following_preview redis_client_failed")
        return None


__all__ = [
    "PREVIEW_KEY_TEMPLATE",
    "PREVIEW_TTL_SECONDS",
    "json_ready",
    "load_preview",
    "preview_cache_key",
    "save_preview",
]
