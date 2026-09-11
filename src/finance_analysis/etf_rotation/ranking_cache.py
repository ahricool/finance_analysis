"""Official etf_rotation ranking cache (preview is separate)."""

from finance_analysis.core.snapshot_cache import SnapshotRankingCache, invalidate_namespace


class RankingCache(SnapshotRankingCache):
    namespace = "etf_rotation"


def invalidate_market(market: str) -> None:
    invalidate_namespace("etf_rotation", market)
