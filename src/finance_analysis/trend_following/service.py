"""Database-only orchestration for the independent Trend Following strategy."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from typing import Any

from finance_analysis.database.repositories.trend_following import TrendFollowingRepository
from finance_analysis.trend_following.config import DEFAULT_CONFIG, TrendFollowingConfig
from finance_analysis.trend_following.features import calculate_features
from finance_analysis.trend_following.models import DailyBar
from finance_analysis.trend_following.ranking import rank_candidates
from finance_analysis.trend_following.regime import calculate_market_regime
from finance_analysis.trend_following.state import transition_state
from finance_analysis.trend_following.universe import get_universe, normalize_market

logger = logging.getLogger(__name__)


class TrendFollowingService:
    """Read raw DB bars, calculate all strategy outputs, and persist snapshots."""

    def __init__(
        self,
        market: str = "CN",
        repository: TrendFollowingRepository | None = None,
        *,
        config: TrendFollowingConfig = DEFAULT_CONFIG,
    ) -> None:
        self.market = normalize_market(market)
        self.repository = repository or TrendFollowingRepository(self.market)
        if normalize_market(getattr(self.repository, "market", self.market)) != self.market:
            raise ValueError("Trend Following repository market does not match service market")
        self.config = config

    def resolve_trade_date(self, requested: date | None = None) -> date:
        if requested is not None:
            return requested
        benchmark = self.config.benchmark_codes[self.market]
        latest = self.repository.latest_daily_date(benchmark)
        if latest is None:
            raise ValueError(f"No raw DB daily data is available for benchmark {benchmark}")
        return latest

    def run(self, trade_date: date | None = None) -> dict[str, Any]:
        effective_date = self.resolve_trade_date(trade_date)
        members = get_universe(self.market)
        member_by_code = {member.code: member for member in members}
        universe_codes = set(member_by_code)
        benchmark_code = self.config.benchmark_codes[self.market]
        universe_key = self.config.universe_keys[self.market]
        requested_codes = universe_codes | {benchmark_code}
        ready_codes = self.repository.daily_codes_on_date(universe_codes, effective_date)
        benchmark_ready = benchmark_code in self.repository.daily_codes_on_date({benchmark_code}, effective_date)
        data_coverage = len(ready_codes) / len(universe_codes) if universe_codes else 0.0
        warnings: list[str] = []
        if data_coverage < self.config.minimum_data_coverage:
            warnings.append(
                f"daily data coverage {data_coverage:.1%} is below {self.config.minimum_data_coverage:.1%}"
            )
        if not benchmark_ready:
            warning = f"benchmark {benchmark_code} has no raw DB bar on {effective_date}"
            logger.warning("market=%s job=trend_following status=incomplete warning=%s", self.market, warning)
            return {
                "status": "incomplete", "market": self.market, "trade_date": effective_date.isoformat(),
                "universe_size": len(universe_codes), "data_ready_count": len(ready_codes),
                "data_coverage": data_coverage, "rankable_count": 0, "snapshot_count": 0,
                "candidate_count": 0, "warnings": [*warnings, warning],
            }

        rows = self.repository.load_daily_history(
            requested_codes, effective_date, calendar_lookback_days=self.config.calendar_lookback_days
        )
        histories: dict[str, list[DailyBar]] = defaultdict(list)
        for item in rows:
            histories[str(item["code"])].append(DailyBar(
                trade_date=item["trade_date"], open=float(item["open"]), high=float(item["high"]),
                low=float(item["low"]), close=float(item["close"]), volume=float(item["volume"]),
                amount=None if item["amount"] is None else float(item["amount"]),
            ))
        benchmark_bars = histories.get(benchmark_code, [])[-self.config.history_bars :]
        if len(benchmark_bars) < self.config.minimum_history_bars:
            warning = f"benchmark {benchmark_code} has insufficient history: {len(benchmark_bars)} bars"
            logger.warning("market=%s job=trend_following status=incomplete warning=%s", self.market, warning)
            return {
                "status": "incomplete", "market": self.market, "trade_date": effective_date.isoformat(),
                "universe_size": len(universe_codes), "data_ready_count": len(ready_codes),
                "data_coverage": data_coverage, "rankable_count": 0, "snapshot_count": 0,
                "candidate_count": 0, "warnings": [*warnings, warning],
            }
        benchmark_close = [bar.close for bar in benchmark_bars]
        benchmark_return_20d = benchmark_close[-1] / benchmark_close[-21] - 1.0
        benchmark_return_60d = benchmark_close[-1] / benchmark_close[-61] - 1.0
        features: list[dict[str, Any]] = []
        sufficient_histories: dict[str, list[DailyBar]] = {}
        for code in sorted(ready_codes):
            bars = histories.get(code, [])[-self.config.history_bars :]
            result = calculate_features(bars, self.config.minimum_history_bars)
            if result is None or not bars or bars[-1].trade_date != effective_date:
                continue
            result.update(
                code=code,
                rs_20d=result["return_20d"] - benchmark_return_20d,
                rs_60d=result["return_60d"] - benchmark_return_60d,
            )
            features.append(result)
            sufficient_histories[code] = bars
        if len(features) / len(universe_codes) < self.config.minimum_data_coverage:
            warnings.append(f"sufficient history coverage is partial: {len(features)}/{len(universe_codes)}")

        regime = calculate_market_regime(
            benchmark_bars, sufficient_histories, market=self.market, trade_date=effective_date,
            benchmark_code=benchmark_code, config=self.config,
        )
        ranked = rank_candidates(features, self.config)
        previous = self.repository.previous_snapshots(effective_date, universe_codes)
        snapshots: list[dict[str, Any]] = []
        internal_keys = {"code", "is_candidate", "setup", "trend_score", "rs_score", "breakout_score",
                         "alpha_score", "score_breakdown", "rank"}
        for row in ranked:
            decision = transition_state(
                row, previous.get(row["code"]), trade_date=effective_date,
                market_regime=regime["market_regime"], config=self.config,
            )
            snapshots.append({
                "market": self.market,
                "trade_date": effective_date,
                "code": row["code"],
                "universe_key": universe_key,
                "market_regime": regime["market_regime"],
                "market_score": regime["market_score"],
                "rank": row["rank"],
                "trend_score": row["trend_score"],
                "rs_score": row["rs_score"],
                "breakout_score": row["breakout_score"],
                "alpha_score": row["alpha_score"],
                "features": {key: value for key, value in row.items() if key not in internal_keys},
                "score_breakdown": row["score_breakdown"],
                "setup": row["setup"],
                "reference_price": row["reference_price"],
                "atr": row["atr20"],
                "intraday_confirmation": "UNAVAILABLE",
                **decision.to_dict(),
            })
        snapshot_count = self.repository.upsert_snapshots(snapshots)
        counts = {action: sum(item["action"] == action for item in snapshots) for action in (
            "ENTRY", "ADD", "HOLD", "REDUCE", "EXIT"
        )}
        summary = {
            "market": self.market,
            "trade_date": effective_date,
            "universe_key": universe_key,
            "benchmark_code": benchmark_code,
            "market_regime": regime["market_regime"],
            "market_score": regime["market_score"],
            "suggested_max_exposure": regime["suggested_max_exposure"],
            "universe_size": len(universe_codes),
            "data_ready_count": len(ready_codes),
            "data_coverage": data_coverage,
            "rankable_count": len(ranked),
            "candidate_count": sum(bool(row["is_candidate"]) for row in ranked),
            "entry_count": counts["ENTRY"],
            "add_count": counts["ADD"],
            "hold_count": counts["HOLD"],
            "reduce_count": counts["REDUCE"],
            "exit_count": counts["EXIT"],
            "warnings": warnings,
            "features": regime["features"],
            "score_breakdown": regime["score_breakdown"],
        }
        self.repository.upsert_summary(summary)
        result = {
            "status": "completed", **summary, "trade_date": effective_date.isoformat(),
            "snapshot_count": snapshot_count,
        }
        logger.info(
            "market=%s job=trend_following trade_date=%s regime=%s snapshots=%s warnings=%s",
            self.market, effective_date, regime["market_regime"], snapshot_count, warnings,
        )
        return result


__all__ = ["TrendFollowingService"]
