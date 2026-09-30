"""Summary cache shares official snapshot commit generation and stale-fill protection."""
from finance_analysis.core.snapshot_cache import SnapshotRankingCache


class EventStudyCache(SnapshotRankingCache):
    namespace = "trend_following"
    schema_version = "v2"
    ttl_seconds = 1800

    def __init__(self, market, start_date, end_date, regime):
        super().__init__(market, end_date)
        self.key = f"trend:event-study:summary:v2:{market}:{start_date}:{end_date}:{regime}"
