"""Best-effort official read cache with commit invalidation and stale-fill protection."""

import logging
from datetime import date
from functools import lru_cache

logger = logging.getLogger(__name__)
TTL_SECONDS = 86400
SCHEMA_VERSION = "v1"


@lru_cache(maxsize=1)
def redis_client():
    import redis
    from finance_analysis.database.config import get_database_config

    return redis.Redis.from_url(
        get_database_config().redis_url, socket_connect_timeout=0.2, socket_timeout=0.2,
    )


class SnapshotRankingCache:
    namespace: str

    def __init__(self, market: str, trade_date: date):
        self.key = f"{self.namespace}:ranking:{market}:{trade_date}"
        self.revision_key = f"{self.namespace}:ranking_revision:{market}"
        self.revision = None

    def load(self) -> bytes | None:
        try:
            client = redis_client()
            # Read the generation and value atomically. A writer can never make an
            # old value appear to belong to a newer generation.
            revision, value = client.mget(self.revision_key, self.key)
            self.revision = revision or b"0"
            prefix = SCHEMA_VERSION.encode() + b":" + self.revision + b"\n"
            return value[len(prefix):] if value and value.startswith(prefix) else None
        except Exception:
            logger.warning("Snapshot ranking cache read unavailable", exc_info=True)
            return None

    def save(self, body: bytes) -> None:
        if self.revision is None:
            return
        try:
            prefix = SCHEMA_VERSION.encode() + b":" + self.revision + b"\n"
            redis_client().eval(
                "if (redis.call('GET', KEYS[1]) or '0') == ARGV[1] then "
                "return redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3]) end return 0",
                2, self.revision_key, self.key, self.revision, prefix + body, TTL_SECONDS,
            )
        except Exception:
            logger.warning("Snapshot ranking cache write unavailable", exc_info=True)


def invalidate_namespace(namespace: str, market: str) -> None:
    """Called after commit; invalidate dependent future rank/change views as well."""
    try:
        client = redis_client()
        client.incr(f"{namespace}:ranking_revision:{market}")
        # Generation invalidates immediately, even while deleting many date keys.
        for key in client.scan_iter(match=f"{namespace}:ranking:{market}:*", count=100):
            client.delete(key)
    except Exception:
        logger.warning("Snapshot ranking cache invalidation unavailable market=%s", market, exc_info=True)
