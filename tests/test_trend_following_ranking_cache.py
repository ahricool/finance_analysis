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
        assert count == 2 and ttl in (86400, 1800)
        self.last_ttl = ttl
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


def test_study_cache_keys_ttl_and_snapshot_generation_invalidation(cache_client):
    from finance_analysis.trend_following.event_study_cache import EventStudyCache
    start, end = date(2026, 8, 1), date(2026, 9, 30)
    cache = EventStudyCache("CN", start, end, "ALL")
    assert cache.key == "trend:event-study:summary:v2:CN:2026-08-01:2026-09-30:ALL"
    assert cache.load() is None
    cache.save(b'{"groups":[]}')
    assert cache_client.last_ttl == 1800
    assert cache.load() == b'{"groups":[]}'
    assert EventStudyCache("US", start, end, "ALL").load() is None
    assert EventStudyCache("CN", start, end, "RISK_ON").load() is None
    assert EventStudyCache("CN", start, date(2026, 9, 29), "ALL").load() is None
    assert EventStudyCache("CN", date(2026, 8, 2), end, "ALL").load() is None
    stale = EventStudyCache("CN", start, end, "ALL")
    stale.load()
    ranking_cache.invalidate_market("CN")
    assert cache.load() is None
    stale.save(b'{"stale":true}')
    assert cache.load() is None


def test_repository_commit_invalidates_study_cache(cache_client):
    from finance_analysis.database.repositories.trend_following import TrendFollowingRepository
    from finance_analysis.trend_following.event_study_cache import EventStudyCache
    from tests.test_trend_following_repository import _Database, _summary
    day = date(2026, 9, 10)
    repo = TrendFollowingRepository("US", _Database())
    cache = EventStudyCache("US", day, day, "ALL")
    cache.load()
    cache.save(b'{"old":true}')
    repo.replace_day(day, [], _summary(day))
    assert cache.load() is None
    cache.save(b'{"new":true}')
    assert cache.load() == b'{"new":true}'
    repo.invalidate_from(day)
    assert cache.load() is None
