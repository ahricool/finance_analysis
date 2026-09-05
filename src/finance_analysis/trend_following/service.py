"""DB-backed stock analysis with read-only CSI2000 and benchmark tail refresh."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from ..database.repositories.trend_following import TrendFollowingRepository
from ..database.repositories.universe import UniverseResolver
from ..integrations.market_data.service import MarketDataService
from ..market_review.trading_calendar import get_completed_trading_days, get_trading_days_between
from .config import DEFAULT_CONFIG, TrendFollowingConfig
from .features import calculate_features
from .models import DailyBar
from .ranking import rank_candidates
from .regime import calculate_market_regime
from .state import (
    apply_exposure_gate,
    apply_regime_exposure_reduction,
    evaluate_close,
    execute_pending_at_open,
)
from .universe import get_universe, normalize_market

logger = logging.getLogger(__name__)


class TrendFollowingService:
    """Read canonical forward-adjusted DB bars, calculate outputs, and persist snapshots."""

    def __init__(
        self,
        market: str = "CN",
        repository: TrendFollowingRepository | None = None,
        *,
        config: TrendFollowingConfig = DEFAULT_CONFIG,
        market_data: MarketDataService | None = None,
    ) -> None:
        self.market = normalize_market(market)
        self.repository = repository or TrendFollowingRepository(self.market)
        if normalize_market(getattr(self.repository, "market", self.market)) != self.market:
            raise ValueError("Trend Following repository market does not match service market")
        self.config = config
        self.market_data = market_data or MarketDataService()

    def resolve_trade_date(self, requested: date | None = None) -> date:
        if requested is not None:
            return requested
        return get_completed_trading_days(self.market.lower(), 1)[-1]

    def _rebuild_dates(self, requested: date | None) -> list[date]:
        latest_available = self.resolve_trade_date(requested)
        latest_snapshot = self.repository.latest_snapshot_date()
        if requested is None:
            if latest_snapshot is None or latest_snapshot >= latest_available:
                return [latest_available]
            return [
                item
                for item in get_trading_days_between(self.market.lower(), latest_snapshot, latest_available)
                if item > latest_snapshot
            ]
        if latest_snapshot is None or latest_snapshot <= requested:
            if latest_snapshot is None or latest_snapshot == requested:
                return [requested]
            return [
                item
                for item in get_trading_days_between(self.market.lower(), latest_snapshot, requested)
                if item > latest_snapshot
            ]
        dates = get_trading_days_between(self.market.lower(), requested, latest_snapshot)
        return sorted(set([requested, *dates]))

    def run(self, trade_date: date | None = None) -> dict[str, Any]:
        initial_latest = self.repository.latest_snapshot_date()
        dates = self._rebuild_dates(trade_date)
        results: list[dict[str, Any]] = []
        for current in dates:
            try:
                result = self._run_single_date(current)
            except Exception as exc:
                if trade_date is not None and initial_latest is not None and current <= initial_latest:
                    self.repository.invalidate_from(current)
                logger.exception(
                    "market=%s job=trend_following rebuild_failed_at=%s",
                    self.market,
                    current,
                )
                return {
                    "status": "failed",
                    "market": self.market,
                    "trade_date": current.isoformat(),
                    "rebuilt_from": dates[0].isoformat(),
                    "rebuilt_dates": [item["trade_date"] for item in results],
                    "rebuild_count": len(results),
                    "rebuild_status": "stopped",
                    "rebuild_stopped_at": current.isoformat(),
                    "warnings": [f"Trend Following rebuild failed: {exc}"],
                }
            results.append(result)
            if result["status"] != "completed":
                if trade_date is not None and initial_latest is not None and current <= initial_latest:
                    self.repository.invalidate_from(current)
                return {
                    **result,
                    "rebuilt_from": dates[0].isoformat(),
                    "rebuilt_dates": [item["trade_date"] for item in results],
                    "rebuild_count": len(results),
                    "rebuild_status": "stopped",
                    "rebuild_stopped_at": current.isoformat(),
                }
        last = results[-1]
        if len(results) == 1:
            return last
        return {
            **last,
            "rebuilt_from": dates[0].isoformat(),
            "rebuilt_dates": [item["trade_date"] for item in results],
            "rebuild_count": len(results),
            "rebuild_status": "completed",
        }

    def _run_single_date(self, effective_date: date) -> dict[str, Any]:
        members = get_universe(self.market)
        member_by_code = {member.code: member for member in members}
        universe_codes = set(member_by_code)
        benchmark_code = self.config.benchmark_codes[self.market]
        universe_key = self.config.universe_keys[self.market]
        csi2000_codes = (
            {item.code for item in UniverseResolver().resolve_universe("cn_csi2000")} & universe_codes
            if self.market == "CN"
            else set()
        )
        requested_codes = universe_codes - csi2000_codes
        ready_codes = self.repository.daily_codes_on_date(requested_codes, effective_date)
        supplemental = {}
        if csi2000_codes:
            supplemental = self.market_data.get_daily_bars(
                sorted(csi2000_codes),
                effective_date - timedelta(days=self.config.calendar_lookback_days),
                effective_date,
                adjustment="forward",
                source_policy="db_fresh",
            ).data
            ready_codes.update(
                code
                for code in csi2000_codes
                if any(bar.trade_date == effective_date for bar in supplemental.get(code, []))
            )
        # All other main-universe stocks remain DB-only.
        benchmark_result = self.market_data.get_daily_bars(
            [benchmark_code],
            effective_date - timedelta(days=self.config.calendar_lookback_days),
            effective_date,
            adjustment="forward",
            source_policy="db_fresh",
        )
        benchmark_bars = [
            DailyBar(
                trade_date=bar.trade_date,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                amount=bar.amount,
            )
            for bar in sorted(benchmark_result.data.get(benchmark_code, []), key=lambda bar: bar.trade_date)
        ]
        benchmark_ready = bool(benchmark_bars and benchmark_bars[-1].trade_date == effective_date)
        data_coverage = len(ready_codes) / len(universe_codes) if universe_codes else 0.0
        warnings: list[str] = []
        if data_coverage < self.config.minimum_data_coverage:
            warnings.append(f"daily data coverage {data_coverage:.1%} is below {self.config.minimum_data_coverage:.1%}")
        if not benchmark_ready:
            warning = f"benchmark {benchmark_code} has no daily bar on {effective_date}"
            logger.warning("market=%s job=trend_following status=incomplete warning=%s", self.market, warning)
            return {
                "status": "incomplete",
                "market": self.market,
                "trade_date": effective_date.isoformat(),
                "universe_size": len(universe_codes),
                "data_ready_count": len(ready_codes),
                "data_coverage": data_coverage,
                "rankable_count": 0,
                "snapshot_count": 0,
                "candidate_count": 0,
                "warnings": [*warnings, warning],
            }
        if data_coverage < self.config.minimum_data_coverage:
            logger.warning(
                "market=%s job=trend_following status=incomplete coverage=%.4f",
                self.market,
                data_coverage,
            )
            return {
                "status": "incomplete",
                "market": self.market,
                "trade_date": effective_date.isoformat(),
                "universe_size": len(universe_codes),
                "data_ready_count": len(ready_codes),
                "data_coverage": data_coverage,
                "rankable_count": 0,
                "snapshot_count": 0,
                "candidate_count": 0,
                "warnings": warnings,
            }

        rows = self.repository.load_daily_history(
            requested_codes, effective_date, calendar_lookback_days=self.config.calendar_lookback_days
        )
        histories: dict[str, list[DailyBar]] = defaultdict(list)
        for item in rows:
            if item["trade_date"] > effective_date:
                continue
            histories[str(item["code"])].append(
                DailyBar(
                    trade_date=item["trade_date"],
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    volume=float(item["volume"]),
                    amount=None if item["amount"] is None else float(item["amount"]),
                )
            )
        for code, bars in supplemental.items():
            histories[code] = [
                DailyBar(bar.trade_date, bar.open, bar.high, bar.low, bar.close, bar.volume, bar.amount)
                for bar in sorted(bars, key=lambda bar: bar.trade_date)
                if bar.trade_date <= effective_date
            ]
        benchmark_bars = benchmark_bars[-self.config.history_bars :]
        if len(benchmark_bars) < self.config.minimum_history_bars:
            warning = f"benchmark {benchmark_code} has insufficient history: {len(benchmark_bars)} bars"
            logger.warning("market=%s job=trend_following status=incomplete warning=%s", self.market, warning)
            return {
                "status": "incomplete",
                "market": self.market,
                "trade_date": effective_date.isoformat(),
                "universe_size": len(universe_codes),
                "data_ready_count": len(ready_codes),
                "data_coverage": data_coverage,
                "rankable_count": 0,
                "snapshot_count": 0,
                "candidate_count": 0,
                "warnings": [*warnings, warning],
            }
        benchmark_close = [bar.close for bar in benchmark_bars]
        benchmark_return_5d = benchmark_close[-1] / benchmark_close[-6] - 1.0
        benchmark_return_10d = benchmark_close[-1] / benchmark_close[-11] - 1.0
        benchmark_return_20d = benchmark_close[-1] / benchmark_close[-21] - 1.0
        features: list[dict[str, Any]] = []
        sufficient_histories: dict[str, list[DailyBar]] = {}
        for code in sorted(ready_codes):
            bars = histories.get(code, [])[-self.config.history_bars :]
            result = calculate_features(bars, self.config.minimum_history_bars)
            if result is None or not bars or bars[-1].trade_date != effective_date:
                continue
            result.update(
                code=code,
                rs_5d=result["return_5d"] - benchmark_return_5d,
                rs_10d=result["return_10d"] - benchmark_return_10d,
                rs_20d=result["return_20d"] - benchmark_return_20d,
            )
            features.append(result)
            sufficient_histories[code] = bars
        history_coverage = len(features) / len(universe_codes) if universe_codes else 0.0
        if history_coverage < self.config.minimum_data_coverage:
            warning = f"sufficient history coverage is partial: {len(features)}/{len(universe_codes)}"
            logger.warning(
                "market=%s job=trend_following status=incomplete warning=%s",
                self.market,
                warning,
            )
            return {
                "status": "incomplete",
                "market": self.market,
                "trade_date": effective_date.isoformat(),
                "universe_size": len(universe_codes),
                "data_ready_count": len(ready_codes),
                "data_coverage": data_coverage,
                "rankable_count": len(features),
                "snapshot_count": 0,
                "candidate_count": 0,
                "warnings": [*warnings, warning],
            }

        regime = calculate_market_regime(
            benchmark_bars,
            sufficient_histories,
            market=self.market,
            trade_date=effective_date,
            benchmark_code=benchmark_code,
            config=self.config,
        )
        ranked = rank_candidates(features, self.config)
        previous = self.repository.previous_snapshots(effective_date, universe_codes)
        opened = {
            row["code"]: execute_pending_at_open(
                row,
                previous.get(row["code"]),
                trade_date=effective_date,
                config=self.config,
            )
            for row in ranked
        }
        allocated = apply_exposure_gate(
            ranked,
            opened,
            previous,
            config=self.config,
        )
        decisions = {
            row["code"]: evaluate_close(
                row,
                allocated[row["code"]],
                trade_date=effective_date,
                market_regime=regime["market_regime"],
                max_exposure=regime["suggested_max_exposure"],
                config=self.config,
            )
            for row in ranked
        }
        decisions = apply_regime_exposure_reduction(
            ranked,
            decisions,
            trade_date=effective_date,
            market_regime=regime["market_regime"],
            max_exposure=regime["suggested_max_exposure"],
            previous=previous,
        )
        snapshots: list[dict[str, Any]] = []
        internal_keys = {
            "code",
            "is_candidate",
            "setup",
            "trend_score",
            "rs_score",
            "breakout_score",
            "alpha_score",
            "score_breakdown",
            "rank",
        }
        for row in ranked:
            decision = decisions[row["code"]]
            snapshots.append(
                {
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
                    **decision.to_dict(),
                }
            )

        ranked_codes = {str(row["code"]) for row in ranked}
        for code, prior in previous.items():
            if code in ranked_codes:
                continue
            prior_state = str(prior.get("state"))
            prior_units = int(prior.get("units") or 0)
            if prior_state in {"ENTRY", "PYRAMIDING", "HOLDING", "WEAKENING", "REDUCE"} and prior_units > 0:
                carried = {
                    key: prior.get(key)
                    for key in (
                        "code",
                        "universe_key",
                        "rank",
                        "trend_score",
                        "rs_score",
                        "breakout_score",
                        "alpha_score",
                        "features",
                        "score_breakdown",
                        "setup",
                        "state",
                        "reference_price",
                        "atr",
                        "entry_price",
                        "signal_date",
                        "signal_price",
                        "last_add_price",
                        "highest_close",
                        "initial_stop",
                        "trailing_stop",
                        "next_add_price",
                        "exit_level",
                        "units",
                        "opened_at",
                        "suggested_initial_weight",
                        "suggested_max_weight",
                        "pending_action",
                        "pending_since",
                        "pending_regime",
                        "pending_max_exposure",
                    )
                }
                pending = str(prior.get("pending_action") or "")
                preserve_pending = pending in {"EXIT", "REDUCE"}
                carried.update(
                    market=self.market,
                    trade_date=effective_date,
                    universe_key=universe_key,
                    market_regime=regime["market_regime"],
                    market_score=regime["market_score"],
                    action="HOLD",
                    reasons=[
                        *(prior.get("reasons") or []),
                        "current daily data unavailable; active state carried forward",
                        *(
                            [f"pending {pending} preserved until the next executable open"]
                            if preserve_pending
                            else (
                                [f"pending {pending} expired because execution data was unavailable"] if pending else []
                            )
                        ),
                    ],
                )
                if not preserve_pending:
                    carried.update(
                        pending_action=None,
                        pending_since=None,
                        pending_regime=None,
                        pending_max_exposure=None,
                    )
                snapshots.append(carried)
            elif prior_state == "CANDIDATE":
                expired = {
                    key: prior.get(key)
                    for key in (
                        "code",
                        "universe_key",
                        "rank",
                        "trend_score",
                        "rs_score",
                        "breakout_score",
                        "alpha_score",
                        "features",
                        "score_breakdown",
                        "setup",
                        "reference_price",
                        "atr",
                    )
                }
                expired.update(
                    market=self.market,
                    trade_date=effective_date,
                    universe_key=universe_key,
                    market_regime=regime["market_regime"],
                    market_score=regime["market_score"],
                    state="WATCHING",
                    action="WATCH",
                    units=0,
                    signal_date=None,
                    signal_price=None,
                    pending_action=None,
                    pending_since=None,
                    reasons=["candidate expired because next-session execution data was unavailable"],
                )
                snapshots.append(expired)

        counts = {
            action: sum(item["action"] == action for item in snapshots)
            for action in ("ENTRY", "ADD", "HOLD", "REDUCE", "EXIT")
        }
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
            "candidate_count": sum(item["state"] == "CANDIDATE" for item in snapshots),
            "entry_count": counts["ENTRY"],
            "add_count": counts["ADD"],
            "hold_count": counts["HOLD"],
            "reduce_count": counts["REDUCE"],
            "exit_count": counts["EXIT"],
            "warnings": warnings,
            "features": regime["features"],
            "score_breakdown": regime["score_breakdown"],
        }
        snapshot_count = self.repository.replace_day(effective_date, snapshots, summary)
        result = {
            "status": "completed",
            **summary,
            "trade_date": effective_date.isoformat(),
            "snapshot_count": snapshot_count,
        }
        logger.info(
            "market=%s job=trend_following trade_date=%s regime=%s snapshots=%s warnings=%s",
            self.market,
            effective_date,
            regime["market_regime"],
            snapshot_count,
            warnings,
        )
        return result


__all__ = ["TrendFollowingService"]
