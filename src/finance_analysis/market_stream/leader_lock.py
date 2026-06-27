"""Token-checked renewable Redis leader lock."""

from __future__ import annotations

import uuid
from typing import Any

from finance_analysis.integrations.market_data.realtime_state.keys import LEADER_LOCK_KEY

_RENEW_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class LeaderLock:
    def __init__(self, redis: Any, *, ttl_seconds: int, key: str = LEADER_LOCK_KEY) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds
        self.key = key
        self.token = uuid.uuid4().hex
        self.acquired = False

    async def acquire(self) -> bool:
        self.acquired = bool(await self.redis.set(self.key, self.token, nx=True, ex=self.ttl_seconds))
        return self.acquired

    async def renew(self) -> bool:
        if not self.acquired:
            return False
        self.acquired = bool(await self.redis.eval(_RENEW_SCRIPT, 1, self.key, self.token, self.ttl_seconds))
        return self.acquired

    async def release(self) -> bool:
        if not self.acquired:
            return False
        released = bool(await self.redis.eval(_RELEASE_SCRIPT, 1, self.key, self.token))
        self.acquired = False
        return released
