from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any


class FakePipeline:
    def __init__(self, redis: "FakeRedis") -> None:
        self.redis = redis
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str):
        def queue(*args: Any, **kwargs: Any) -> "FakePipeline":
            self.calls.append((name, args, kwargs))
            return self

        return queue

    async def execute(self) -> list[Any]:
        if self.redis.fail_execute:
            self.redis.fail_execute = False
            raise RuntimeError("redis unavailable")
        results = []
        self.redis.pipeline_executes += 1
        for name, args, kwargs in self.calls:
            results.append(await getattr(self.redis, name)(*args, **kwargs))
        return results


class FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = defaultdict(dict)
        self.zsets: dict[str, dict[str, float]] = defaultdict(dict)
        self.strings: dict[str, str] = {}
        self.expires: dict[str, int] = {}
        self.pipeline_executes = 0
        self.fail_execute = False
        self.closed = False

    def pipeline(self, transaction: bool = False) -> FakePipeline:
        return FakePipeline(self)

    async def hset(self, key: str, *args: Any, mapping: dict[str, Any] | None = None) -> int:
        if mapping is None and len(args) == 2:
            mapping = {str(args[0]): args[1]}
        before = len(self.hashes[key])
        self.hashes[key].update({str(k): str(v) for k, v in (mapping or {}).items()})
        return len(self.hashes[key]) - before

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def hmget(self, key: str, fields: list[str]) -> list[str | None]:
        return [self.hashes.get(key, {}).get(field) for field in fields]

    async def hdel(self, key: str, *fields: str) -> int:
        removed = 0
        for field in fields:
            removed += int(self.hashes.get(key, {}).pop(str(field), None) is not None)
        return removed

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        before = len(self.zsets[key])
        self.zsets[key].update({str(k): float(v) for k, v in mapping.items()})
        return len(self.zsets[key]) - before

    async def zcard(self, key: str) -> int:
        return len(self.zsets.get(key, {}))

    def _ordered(self, key: str) -> list[str]:
        return [item[0] for item in sorted(self.zsets.get(key, {}).items(), key=lambda item: (item[1], item[0]))]

    async def zrange(self, key: str, start: int, end: int) -> list[str]:
        values = self._ordered(key)
        if start < 0:
            start = max(0, len(values) + start)
        if end < 0:
            end = len(values) + end
        return values[start : end + 1]

    async def zrangebyscore(self, key: str, minimum: float, maximum: float) -> list[str]:
        return [
            field
            for field in self._ordered(key)
            if float(minimum) <= self.zsets[key][field] <= float(maximum)
        ]

    async def zrem(self, key: str, *fields: str) -> int:
        removed = 0
        for field in fields:
            removed += int(self.zsets.get(key, {}).pop(str(field), None) is not None)
        return removed

    async def expire(self, key: str, seconds: int) -> bool:
        self.expires[key] = int(seconds)
        return True

    async def ttl(self, key: str) -> int:
        return self.expires.get(key, -1)

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.strings:
            return False
        self.strings[key] = value
        if ex:
            self.expires[key] = ex
        return True

    async def eval(self, script: str, numkeys: int, key: str, token: str, *args: Any) -> int:
        if self.strings.get(key) != token:
            return 0
        if "EXPIRE" in script:
            self.expires[key] = int(args[0])
            return 1
        self.strings.pop(key, None)
        return 1

    async def aclose(self) -> None:
        self.closed = True


class FakeStreamingClient:
    instances: list["FakeStreamingClient"] = []

    def __init__(self, *, operation_delay: float = 0) -> None:
        self.operation_delay = operation_delay
        self.operations: list[tuple[str, Any]] = []
        self.active: set[str] = set()
        self.event_sink = None
        self.generation = 0
        self.closed = False
        self.fail_health = False
        self.in_operation = 0
        self.max_concurrent_operations = 0
        self.__class__.instances.append(self)

    async def connect(self, generation: int, event_sink: Any) -> None:
        self.generation = generation
        self.event_sink = event_sink
        self.operations.append(("connect", generation))

    async def _operation(self, name: str, symbols: set[str]) -> None:
        self.in_operation += 1
        self.max_concurrent_operations = max(self.max_concurrent_operations, self.in_operation)
        if self.operation_delay:
            await asyncio.sleep(self.operation_delay)
        self.operations.append((name, frozenset(symbols)))
        if name == "subscribe":
            self.active.update(symbols)
        else:
            self.active.difference_update(symbols)
        self.in_operation -= 1

    async def subscribe(self, symbols: set[str]) -> None:
        await self._operation("subscribe", symbols)

    async def unsubscribe(self, symbols: set[str]) -> None:
        await self._operation("unsubscribe", symbols)

    async def health_check(self) -> None:
        self.operations.append(("health", None))
        if self.fail_health:
            raise RuntimeError("connection closed")

    async def close(self) -> None:
        self.closed = True
        self.operations.append(("close", None))


async def wait_until(predicate: Any, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.005)
