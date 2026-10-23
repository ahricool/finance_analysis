"""Atomic latest-view publication; reads never trigger upstream requests."""

import json

from .config import CACHE_TTL_SECONDS


class HeatmapCache:
    def __init__(self, client=None):
        if client is None:
            import redis
            from finance_analysis.database.config import get_database_config

            client = redis.Redis.from_url(
                get_database_config().redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=3
            )
        self.client = client

    @staticmethod
    def key(market):
        return f"market_heatmap:v1:{market}"

    def read(self, market):
        raw = self.client.get(self.key(market))
        return json.loads(raw) if raw else None

    def write(self, market, payload):
        self.client.set(
            self.key(market), json.dumps(payload, ensure_ascii=False, allow_nan=False), ex=CACHE_TTL_SECONDS
        )
