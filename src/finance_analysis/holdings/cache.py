# -*- coding: utf-8 -*-
"""Redis snapshots for holdings. PostgreSQL remains the durable source of generation/hash."""  # pragma: allowlist secret

from __future__ import annotations

import json
from typing import Any

from finance_analysis.holdings.config import get_holdings_config  # pragma: allowlist secret
from finance_analysis.holdings.models import HoldingsSnapshot  # pragma: allowlist secret

SNAPSHOT_KEY = "holdings:snapshot:{uid}:{source_id}:{generation}"
LATEST_KEY = "holdings:latest:{uid}:{source_id}"
CONTEXT_KEY = "holdings:context:{uid}:{source_id}:{content_hash}"
RISK_LATEST_KEY = "risk:latest:{uid}:{source_id}:{account_id}"
BARS_KEY = "md:bars:5m:{provider}:{symbol}:{adjustment}"


def snapshot_key(uid: int, source_id: int, generation: int) -> str:
    return SNAPSHOT_KEY.format(uid=uid, source_id=source_id, generation=generation)


def latest_key(uid: int, source_id: int) -> str:
    return LATEST_KEY.format(uid=uid, source_id=source_id)


def context_key(uid: int, source_id: int, content_hash: str) -> str:
    return CONTEXT_KEY.format(uid=uid, source_id=source_id, content_hash=content_hash)


class HoldingsCache:
    def __init__(self, redis_client: Any, *, ttl_seconds: int | None = None) -> None:
        self.redis = redis_client
        self.ttl_seconds = ttl_seconds or get_holdings_config().snapshot_ttl_seconds

    def write_snapshot(self, snapshot: HoldingsSnapshot, *, context_text: str | None = None) -> None:
        key = snapshot_key(snapshot.uid, snapshot.source_id, snapshot.generation)
        payload = snapshot.model_dump_json()
        self.redis.set(key, payload, ex=self.ttl_seconds)
        self.redis.set(
            latest_key(snapshot.uid, snapshot.source_id),
            json.dumps({"generation": snapshot.generation, "content_hash": snapshot.content_hash}),
            ex=self.ttl_seconds,
        )
        if context_text is not None:
            self.redis.set(
                context_key(snapshot.uid, snapshot.source_id, snapshot.content_hash),
                context_text,
                ex=self.ttl_seconds,
            )

    def get_snapshot(self, uid: int, source_id: int, generation: int | None = None) -> HoldingsSnapshot | None:
        if generation is None:
            raw_latest = self.redis.get(latest_key(uid, source_id))
            if not raw_latest:
                return None
            if isinstance(raw_latest, bytes):
                raw_latest = raw_latest.decode("utf-8")
            generation = int(json.loads(raw_latest)["generation"])
        raw = self.redis.get(snapshot_key(uid, source_id, generation))
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return HoldingsSnapshot.model_validate_json(raw)

    def get_context(self, uid: int, source_id: int, content_hash: str) -> str | None:
        raw = self.redis.get(context_key(uid, source_id, content_hash))
        if raw is None:
            return None
        return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

    def clear_source(self, uid: int, source_id: int, generation: int | None = None) -> None:
        latest = self.redis.get(latest_key(uid, source_id))
        if latest:
            if isinstance(latest, bytes):
                latest = latest.decode("utf-8")
            info = json.loads(latest)
            self.redis.delete(snapshot_key(uid, source_id, int(info["generation"])))
            self.redis.delete(context_key(uid, source_id, str(info.get("content_hash") or "")))
        if generation is not None:
            self.redis.delete(snapshot_key(uid, source_id, generation))
        self.redis.delete(latest_key(uid, source_id))
