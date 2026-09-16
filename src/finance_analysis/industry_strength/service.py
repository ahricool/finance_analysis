"""A-share close-only orchestration. HTTP reads never calculate the cross-section."""

import logging
from datetime import timedelta

from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.industry_strength import IndustryStrengthRepository
from finance_analysis.integrations.market_data.service import MarketDataService
from finance_analysis.integrations.market_data.providers.fuyao import FuyaoError
from finance_analysis.market_review.trading_calendar import (
    get_completed_trading_days,
    get_market_now,
    get_trading_days_between,
)
from .config import DEFAULT_CONFIG
from .features import aligned_closes, breadth, constituent_observations, index_features
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

    def run(self):
        day = get_completed_trading_days("cn", 1)[-1]
        # Current membership cannot be used to fabricate historical breadth.
        if day != get_market_now("cn").date():
            raise IndustryReadinessError(
                "Official breadth requires today's completed A-share session; no historical backfill"
            )
        sessions = self.sessions(day)
        catalog = self.market_data.get_industry_catalog()
        if not catalog:
            raise IndustryReadinessError("Industry catalog is empty")
        benchmark, _ = self.market_data.get_index_history(self.config.benchmark, sessions[0], day)
        try:
            aligned_closes(benchmark, sessions)
        except ValueError as exc:
            raise IndustryReadinessError(f"CSI300 benchmark not ready for {day}: {exc}") from None
        ready, failures, memberships = [], {}, {}
        for item in catalog:
            code = item["thscode"]
            try:
                bars, timestamp = self.market_data.get_index_history(code, sessions[0], day)
                features = index_features(bars, benchmark, sessions)
                memberships[code] = self.market_data.get_index_constituents(code)
                if not memberships[code]:
                    raise ValueError("empty constituent list")
                ready.append(
                    {
                        "trade_date": day,
                        "industry_code": code,
                        "industry_name": item["name"],
                        "data_timestamp": timestamp,
                        "members_observed_at": utc_now(),
                        **features,
                    }
                )
            except (FuyaoError, ValueError) as exc:
                failures[code] = str(exc)
                logger.warning("Industry %s excluded: %s", code, exc)
        self._coverage(len(ready), len(catalog), failures)
        codes = sorted({m["thscode"] for r in ready for m in memberships[r["industry_code"]]})
        # Existing stock capability batches all constituents, never introduces another quote provider.
        stocks = self.load_member_history(codes, sessions)
        valid = []
        for row in ready:
            code = row["industry_code"]
            metrics = breadth(constituent_observations(memberships[code], stocks, sessions))
            if metrics["valid_constituent_count"] / metrics["constituent_count"] < self.config.minimum_breadth_coverage:
                failures[code] = (
                    f"Breadth daily readiness {metrics['valid_constituent_count']}/{metrics['constituent_count']}"
                )
                logger.warning("Industry %s excluded: %s", code, failures[code])
                continue
            row.update(metrics)
            valid.append(row)
        self._coverage(len(valid), len(catalog), failures)
        past = self.repository.history(sessions[-2], limit=5)
        history = {(r["trade_date"], r["industry_code"]): r for r in past}
        rank_rows(valid, history, sessions[:-1], self.config)
        for row in valid:
            row["state"] = classify(row, len(valid), history.get((sessions[-4], row["industry_code"])), self.config)
            row["quality"] = {
                "version": self.config.version,
                "catalog_count": len(catalog),
                "ranked_count": len(valid),
                "coverage": len(valid) / len(catalog),
                "excluded": failures,
                "benchmark": self.config.benchmark,
                "breadth_basis": "observed_current_members_at_close",
                "member_codes": [m["thscode"] for m in memberships[row["industry_code"]]],
            }
        if get_market_now("cn").date() != day:
            raise IndustryReadinessError("Collection crossed the Shanghai date boundary; no snapshot written")
        self.repository.save(day, valid)
        return {
            "status": "completed",
            "trade_date": day.isoformat(),
            "industries": len(valid),
            "catalog_count": len(catalog),
            "excluded": failures,
        }

    def _coverage(self, count, total, failures):
        if not total or count / total < self.config.minimum_coverage:
            raise IndustryReadinessError(
                f"Industry coverage {count}/{total} below {self.config.minimum_coverage:.0%}; "
                f"no snapshot written. Exclusions: {failures}"
            )

    def load_member_history(self, codes, sessions):
        day = sessions[-1]
        stored = self.market_data.get_daily_bars(
            codes,
            sessions[0],
            day,
            adjustment="forward",
            source_policy="db_only",
        ).data
        missing = []
        for code in codes:
            try:
                aligned_closes(stored.get(code, []), sessions[-20:])
            except ValueError:
                missing.append(code)
        # cn_daily_sync intentionally covers a narrower universe than all THS constituents.
        # Fetch missing full windows through the existing provider chain, without DB writes.
        if missing:
            remote = self.market_data.get_daily_bars(
                missing,
                sessions[0],
                day,
                adjustment="forward",
                source_policy="remote_only",
            )
            for code in missing:
                # A validated, complete fallback is sufficient for a read-only calculation.
                # Sticky errors are a full-history persistence guard, not a ban on fallback reads.
                stored[code] = remote.data.get(code, [])
        return stored

    def constituents(self, code):
        day = get_completed_trading_days("cn", 1)[-1]
        sessions = self.sessions(day)
        members = self.market_data.get_index_constituents(code)
        stocks = self.load_member_history([m["thscode"] for m in members], sessions)
        rows = constituent_observations(members, stocks, sessions)
        return {
            "industry_code": code,
            "trade_date": day,
            "members_observed_at": utc_now(),
            "basis": "current_members_latest_completed_close",
            "items": rows,
            **breadth(rows),
        }
