"""Official trend_following ranking cache (preview is separate)."""

from finance_analysis.core.snapshot_cache import SnapshotRankingCache, invalidate_namespace


class RankingCache(SnapshotRankingCache):
    namespace = "trend_following"
    schema_version = "v2"


def invalidate_market(market: str) -> None:
    invalidate_namespace("trend_following", market)
