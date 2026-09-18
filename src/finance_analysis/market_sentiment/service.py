"""Bounded collection and per-day backfill. Read APIs never instantiate this service."""

import logging
from datetime import date
from finance_analysis.database.repositories.market_sentiment import MarketSentimentRepository
from finance_analysis.integrations.market_data.service import MarketDataService
from finance_analysis.integrations.market_data.providers.fuyao import FuyaoError
from finance_analysis.market_sentiment.calendar import expected_date, sessions_through, validate_day
from finance_analysis.market_sentiment.config import SentimentConfig

logger = logging.getLogger(__name__)


def failure_summary(exc):
    # Only FuyaoError is guaranteed to contain sanitized path/code, never credentials.
    return str(exc) if isinstance(exc, FuyaoError) else type(exc).__name__


class MarketSentimentService:
    def __init__(self, repository=None, market_data=None, config=SentimentConfig()):
        self.repository = repository or MarketSentimentRepository()
        self.market_data = market_data or MarketDataService()
        self.config = config

    def run(self, trade_date=None, backfill_days=None, missing_only=True):
        if trade_date is not None and backfill_days is not None:
            raise ValueError("trade_date 与 backfill_days 不能同时提供")
        day = trade_date or expected_date()
        validate_day(day)
        if backfill_days is None:
            return self.collect(day)
        if type(backfill_days) is not int or not 1 <= backfill_days <= self.config.max_backfill_days:
            raise ValueError("backfill_days 必须在 1..31")
        days = sessions_through(day, backfill_days)
        outcomes = []
        for target in days:
            existing = self.repository.overview(target) if missing_only else None
            if existing and not existing["quality"].get("optional_errors"):
                outcomes.append({"trade_date": target.isoformat(), "status": "existing"})
                continue
            try:
                outcomes.append(self.collect(target, include_ladder=target == days[-1]))
            except Exception as exc:
                logger.warning("Market sentiment %s collection failed: %s", target, failure_summary(exc))
                outcomes.append({"trade_date": target.isoformat(), "status": "failed", "error": failure_summary(exc)})
        return {
            "status": "partial" if any(r["status"] == "failed" for r in outcomes) else "completed",
            "days": outcomes,
        }

    def collect(self, day: date, include_ladder=True):
        validate_day(day)
        sources = {"limit_up": self.market_data.get_limit_up_pool(day)}
        errors = {}
        for kind in ("limit_down", "limit_break", "ladder"):
            if kind == "ladder" and not include_ladder:
                continue
            try:
                sources[kind] = (
                    self.market_data.get_limit_up_ladder()
                    if kind == "ladder"
                    else getattr(self.market_data, f"get_{kind}_pool")(day)
                )
            except Exception as exc:
                # Provider exceptions are sanitized; never serialize response payloads or credentials.
                errors[kind] = failure_summary(exc)
                logger.warning("Market sentiment %s optional %s unavailable: %s", day, kind, failure_summary(exc))
        return self.repository.publish(day, sources, errors, self.config)
