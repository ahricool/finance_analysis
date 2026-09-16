"""Independent, database-only trend-following strategy domain."""

from finance_analysis.trend_following.config import DEFAULT_CONFIG, TrendFollowingConfig


def __getattr__(name):
    # Repository read-model imports must not recursively initialize the service.
    if name == "TrendFollowingService":
        from finance_analysis.trend_following.service import TrendFollowingService

        return TrendFollowingService
    raise AttributeError(name)


__all__ = ["DEFAULT_CONFIG", "TrendFollowingConfig", "TrendFollowingService"]
