"""Independent, database-only trend-following strategy domain."""

from finance_analysis.trend_following.config import DEFAULT_CONFIG, TrendFollowingConfig
from finance_analysis.trend_following.service import TrendFollowingService

__all__ = ["DEFAULT_CONFIG", "TrendFollowingConfig", "TrendFollowingService"]
