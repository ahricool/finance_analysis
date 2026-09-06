"""Publication-first freshness for news facts in a relevant usage context."""

from sqlalchemy import func, select

from finance_analysis.database.models.news import NewsIntel, NewsIntelUsage


def effective_news_time(*usage_conditions):
    """Use publication time, or the latest matching observation if unpublished."""
    observed_at = (
        select(func.max(NewsIntelUsage.observed_at))
        .where(NewsIntelUsage.news_intel_id == NewsIntel.id, *usage_conditions)
        .correlate(NewsIntel)
        .scalar_subquery()
    )
    return func.coalesce(NewsIntel.published_date, observed_at)
