"""Disposable realtime view. Database history remains authoritative."""

import json
import logging

from datetime import datetime
from decimal import Decimal
from redis.asyncio import Redis

logger = logging.getLogger(__name__)
KEY = "crypto:BTCUSDT:realtime:v1"


def _json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Unsupported crypto cache value: {type(value).__name__}")


class CryptoRealtime:
    def __init__(self, client):
        self.client = client

    @classmethod
    def from_url(cls, url):
        return cls(Redis.from_url(url, decode_responses=True, socket_timeout=5, socket_connect_timeout=5))

    async def read(self):
        try:
            raw = await self.client.get(KEY)
            return json.loads(raw) if raw else {}
        except Exception:
            logger.warning("Crypto realtime cache unavailable", exc_info=True)
            return {}

    async def write(self, state):
        try:
            # Decimal values must remain strings across transport/cache boundaries.
            await self.client.set(KEY, json.dumps(state, default=_json_value), ex=180)
        except Exception:
            logger.warning("Crypto realtime cache write failed", exc_info=True)

    async def close(self):
        await self.client.aclose()
