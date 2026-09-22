"""Shared A-share cross-section calculation; only the formal run persists to PostgreSQL."""

import logging
from datetime import date, timedelta

from sqlalchemy.exc import SQLAlchemyError

from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.industry_strength import IndustryStrengthRepository
from finance_analysis.integrations.market_data.service import MarketDataService
from finance_analysis.integrations.market_data.providers.fuyao import FuyaoError
from finance_analysis.market_review.trading_calendar import (
    get_completed_trading_days,
    get_market_now,
    get_trading_days_between,
    is_market_open,
)
from .config import DEFAULT_CONFIG
from .features import aligned_closes, breadth, constituent_observations, index_features, overlay, current_quote
from .scoring import rank_rows
from .state import classify

logger = logging.getLogger(__name__)


class IndustryReadinessError(ValueError):
    pass


class IndustryStrengthService:
    def __init__(self, repository=None, market_data=None, config=DEFAULT_CONFIG):
        self.repository = repository or IndustryStrengthRepository()
        self.market_data = market_data or MarketDataService()
        self.config = config

    def sessions(self, day):
        sessions = get_trading_days_between("cn", day - timedelta(days=self.config.lookback_days), day)[-21:]
        if len(sessions) != 21 or sessions[-1] != day:
            raise IndustryReadinessError("A-share calendar history is not ready")
        return sessions

    def run(self, trade_date: date | None = None):
        latest = get_completed_trading_days("cn", 1)[-1]
        day = trade_date or latest
        if day > latest or not is_market_open("cn", day):
            raise IndustryReadinessError("Industry Strength requires a completed trading session")
        historical = day < get_market_now("cn").date()
        # Current membership cannot be used to fabricate historical breadth.
        if trade_date is None and historical:
            raise IndustryReadinessError(
                "Official breadth requires today's completed A-share session; no historical backfill"
            )
        if historical and any(r.get("members_observed_at") is not None for r in self.repository.ranking(day)):
            raise IndustryReadinessError("Saved historical breadth must not be overwritten by index-only backfill")
        rows, constituents, _ = self.calculate(day, historical)
        self.repository.save(day, rows, constituents=None if historical else constituents)
        return {
            "status": "completed",
            "trade_date": day.isoformat(),
            "industries": len(rows),
            "catalog_count": rows[0]["quality"]["catalog_count"],
            "excluded": rows[0]["quality"]["excluded"],
        }

    def calculate(self, day, historical, *, preview=False):
        """Fetch and calculate one cross-section in memory; callers own publication."""
        sessions = self.sessions(day)
        catalog = self.market_data.get_industry_catalog()
        if not catalog:
            raise IndustryReadinessError("Industry catalog is empty")
        history_end = sessions[-2] if preview else day
        index_quotes = (
            self.market_data.get_index_quotes([self.config.benchmark] + [item["thscode"] for item in catalog])
            if preview
            else {}
        )
        stamps = []
        benchmark, _ = self.market_data.get_index_history(self.config.benchmark, sessions[0], history_end)
        if preview:
            quote = index_quotes.get(self.config.benchmark)
            benchmark = overlay(benchmark, quote, day, sessions[-2])
            if current_quote(quote, day):
                stamps.append(quote.quote_time)
        try:
            aligned_closes(benchmark, sessions)
        except ValueError as exc:
            raise IndustryReadinessError(f"CSI300 benchmark not ready for {day}: {exc}") from None
        ready, failures, memberships, breadth_failures = [], {}, {}, {}
        for item in catalog:
            code = item["thscode"]
            try:
                bars, timestamp = self.market_data.get_index_history(code, sessions[0], history_end)
                if preview:
                    quote = index_quotes.get(code)
                    bars = overlay(bars, quote, day, sessions[-2])
                    timestamp = quote.quote_time if current_quote(quote, day) else None
                features = index_features(bars, benchmark, sessions)
                if preview:
                    stamps.append(timestamp)
                ready.append(
                    {
                        "trade_date": day,
                        "industry_code": code,
                        "industry_name": item["name"],
                        "data_timestamp": timestamp,
                        "members_observed_at": None if historical else utc_now(),
                        **features,
                    }
                )
            except (FuyaoError, ValueError) as exc:
                failures[code] = str(exc)
                logger.warning("Industry %s excluded: %s", code, exc)
        self._coverage(len(ready), len(catalog), failures)
        for row in ready:
            code = row["industry_code"]
            if historical:
                memberships[code] = []
                continue
            try:
                memberships[code] = self.market_data.get_index_constituents(code)
                if not memberships[code]:
                    raise ValueError("empty constituent list")
            except (FuyaoError, ValueError) as exc:
                memberships[code] = []
                breadth_failures[code] = str(exc)
        codes = sorted({m["thscode"] for r in ready for m in memberships[r["industry_code"]]})
        # Retain the existing history fetch path; breadth failure cannot discard valid indices.
        try:
            stocks = self.load_member_history(codes, sessions[:-1] if preview else sessions) if codes else {}
        except Exception as exc:
            stocks = {}
            breadth_failures["history"] = str(exc)
        if preview and codes:
            try:
                quotes = self.market_data.get_realtime_quotes(codes).data
                stocks = {
                    code: overlay(stocks.get(code, []), quotes.get(code), day, sessions[-2], stock=True)
                    for code in codes
                }
                stamps.extend(quote.quote_time for quote in quotes.values() if current_quote(quote, day))
            except Exception as exc:
                stocks = {}
                breadth_failures["quotes"] = str(exc)
        trend_ranks = {}
        if codes:
            try:
                trend_ranks = self.repository.latest_cn_trend_ranks(codes)
            except SQLAlchemyError:
                logger.warning("Latest CN Trend ranks unavailable; publishing null ranks", exc_info=True)
        current_constituents = []
        valid = ready
        for row in valid:
            code = row["industry_code"]
            observations = constituent_observations(memberships[code], stocks, sessions)
            for item in observations:
                current_constituents.append(
                    {
                        "industry_code": code,
                        "stock_code": item["code"],
                        "stock_name": item["name"],
                        **{key: value for key, value in item.items() if key not in {"code", "name"}},
                        "trend_rank": trend_ranks.get(item["code"]),
                    }
                )
            row.update(breadth(observations, self.config.minimum_breadth_coverage))
            if historical:
                row["quality"]["breadth_status"] = "unavailable_historical_members"
                for key in (
                    "constituent_count",
                    "daily_valid_count",
                    "ma5_valid_count",
                    "ma20_valid_count",
                    "above_ma5_count",
                    "above_ma20_count",
                    "up_count",
                    "down_count",
                    "flat_count",
                ):
                    row[key] = None
        past = self.repository.history(sessions[-2], limit=5)
        history = {(r["trade_date"], r["industry_code"]): r for r in past}
        rank_rows(valid, history, sessions[:-1], self.config)
        for row in valid:
            row["state"] = classify(row, len(valid), history.get((sessions[-4], row["industry_code"])), self.config)
            row["quality"] = {
                **row["quality"],
                "breadth_errors": breadth_failures,
                "version": self.config.version,
                "catalog_count": len(catalog),
                "ranked_count": len(valid),
                "coverage": len(valid) / len(catalog),
                "excluded": failures,
                "benchmark": self.config.benchmark,
                "breadth_basis": (
                    "unavailable_historical_members" if historical else "observed_current_members_at_close"
                ),
                "catalog_basis": "current_catalog",
                "member_codes": [m["thscode"] for m in memberships[row["industry_code"]]],
            }
        if not historical and get_market_now("cn").date() != day:
            raise IndustryReadinessError("Collection crossed the Shanghai date boundary; no snapshot written")
        return valid, current_constituents, stamps

    def _coverage(self, count, total, failures):
        if not total or count / total < self.config.minimum_coverage:
            raise IndustryReadinessError(
                f"Industry coverage {count}/{total} below {self.config.minimum_coverage:.0%}; "
                f"no snapshot written. Exclusions: {failures}"
            )

    def load_member_history(self, codes, sessions):
        """Read the full forward-adjusted stock window from DB for either run mode."""
        return self.market_data.get_daily_bars(
            codes,
            sessions[0],
            sessions[-1],
            adjustment="forward",
            source_policy="db_only",
        ).data
