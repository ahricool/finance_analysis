"""Atomically publish small read views alongside an existing preview document."""

import json
from typing import Any, Callable


def encode(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def publish(client: Any, key: str, body: bytes, views: dict[str, Any], ttl: int) -> None:
    # Replace the whole hash so removed securities cannot survive a new generation.
    view_key = f"{key}:views:v1"
    transaction = client.pipeline(transaction=True)
    transaction.set(key, body, ex=ttl)
    transaction.delete(view_key)
    transaction.hset(view_key, mapping={"_present": "1", **{name: encode(value) for name, value in views.items()}})
    transaction.expire(view_key, ttl)
    transaction.execute()


def read(client: Any, key: str, field: str, fallback: Callable[[], Any]) -> bytes | str | None:
    """Old deployments remain readable until their next scheduled publication; GET never writes."""
    present, value = client.hmget(f"{key}:views:v1", "_present", field)
    if present:
        return value
    payload = fallback()
    return encode(payload) if payload is not None else None
