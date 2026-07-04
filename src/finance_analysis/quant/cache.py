"""Best-effort Redis cache for latest results; PostgreSQL remains authoritative."""

from __future__ import annotations

import json
import logging

import redis

from finance_analysis.database.config import get_database_config
from finance_analysis.quant.config import get_quant_config

logger = logging.getLogger(__name__)


class QuantLatestCache:
    def __init__(self, client=None):
        self.client = client or redis.Redis.from_url(get_database_config().redis_url, decode_responses=True)
        self.ttl = get_quant_config().cache_ttl_seconds

    def set(self, key: str, value: dict | list) -> bool:
        try:
            self.client.setex(key, self.ttl, json.dumps(value, default=str, ensure_ascii=False)); return True
        except redis.RedisError as exc:
            logger.warning("Quant cache write failed: key=%s error=%s", key, exc); return False

    def get(self, key: str):
        try:
            value=self.client.get(key); return json.loads(value) if value else None
        except (redis.RedisError, json.JSONDecodeError) as exc:
            logger.warning("Quant cache read failed: key=%s error=%s", key, exc); return None


def cache_keys(market: str, universe: str | None = None, code: str | None = None) -> dict:
    result={"market_regime":f"quant:market_regime:{market}:latest","sector_ranking":f"quant:sector_ranking:{market}:latest"}
    if universe: result.update({"ranking":f"quant:ranking:{market}:{universe}:latest","portfolio":f"quant:portfolio:{market}:{universe}:latest"})
    if code: result.update({"signal":f"quant:signal:{market}:{code}:latest","intraday":f"quant:intraday_confirmation:{market}:{code}:latest"})
    return result
