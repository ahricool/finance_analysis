"""Official trend_following ranking cache (preview is separate)."""

from finance_analysis.core.snapshot_cache import SnapshotRankingCache, invalidate_namespace


class RankingCache(SnapshotRankingCache):
    namespace = "trend_following"
    schema_version = "v11"

    def __init__(self, market, trade_date, trend_period=20, *, table=False):
        super().__init__(market, trade_date)
        self.key += f":{trend_period}"
        if table:
            self.key += ":table:v1"


def invalidate_market(market: str) -> None:
    invalidate_namespace("trend_following", market)
