"""Offline cache contract and commit invalidation regression tests."""
from datetime import date

import pytest

from finance_analysis.trend_following import ranking_cache
from finance_analysis.core import snapshot_cache


class MemoryRedis:
    def __init__(self):
        self.values = {}

    def mget(self, *keys):
        return [self.values.get(key) for key in keys]

    def incr(self, key):
        self.values[key] = str(int(self.values.get(key, b"0")) + 1).encode()

    def scan_iter(self, *, match, count):
        return iter([key for key in self.values if key.startswith(match[:-1])])

    def delete(self, key):
        self.values.pop(key, None)

    def eval(self, script, count, revision_key, key, revision, body, ttl):
        assert count == 2 and ttl == 86400
        if self.values.get(revision_key, b"0") == revision:
            self.values[key] = body
            return 1
        return 0


@pytest.fixture
def cache_client(monkeypatch):
    client = MemoryRedis()
    monkeypatch.setattr(snapshot_cache, "redis_client", lambda: client)
    return client


def test_cache_miss_hit_and_market_date_isolation(cache_client):
    cn = ranking_cache.RankingCache("CN", date(2026, 9, 10))
    assert cn.key == "trend_following:ranking:CN:2026-09-10"
    assert cn.load() is None
    cn.save(b'{"items":[]}')
    assert cn.load() == b'{"items":[]}'
    assert ranking_cache.RankingCache("US", date(2026, 9, 10)).load() is None
    assert ranking_cache.RankingCache("CN", date(2026, 9, 9)).load() is None


def test_invalidation_clears_dependent_dates_and_prevents_stale_fill(cache_client):
    old_request = ranking_cache.RankingCache("CN", date(2026, 9, 10))
    old_request.load()
    for market in ("CN", "US"):
        for day in (8, 9, 10):
            cache = ranking_cache.RankingCache(market, date(2026, 9, day))
            cache.load()
            cache.save(b'{}')
    ranking_cache.invalidate_market("CN")
    old_request.save(b'{"stale":true}')
    assert ranking_cache.RankingCache("CN", date(2026, 9, 10)).load() is None
    assert ranking_cache.RankingCache("US", date(2026, 9, 10)).load() == b'{}'
    assert not any(key.startswith('trend_following:ranking:CN:') for key in cache_client.values)


def test_redis_failure_is_fail_open_and_does_not_cache(monkeypatch):
    def unavailable():
        raise ConnectionError("offline")
    monkeypatch.setattr(snapshot_cache, "redis_client", unavailable)
    cache = ranking_cache.RankingCache("CN", date(2026, 9, 10))
    assert cache.load() is None
    cache.save(b'{}')
    ranking_cache.invalidate_market("CN")


def test_etf_cache_uses_separate_namespace_and_active_invalidation(cache_client):
    from finance_analysis.etf_rotation.ranking_cache import RankingCache, invalidate_market
    cache = RankingCache("CN", date(2026, 9, 10))
    assert cache.key == "etf_rotation:ranking:CN:2026-09-10"
    assert cache.load() is None
    cache.save(b'{"etf":true}')
    assert RankingCache("CN", date(2026, 9, 10)).load() == b'{"etf":true}'
    invalidate_market("CN")
    assert cache.load() is None
