"""DB-backed stock analysis with read-only benchmark tail refresh."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from time import monotonic
from typing import Any

from ..core.time import utc_isoformat, utc_now
from ..database.repositories.trend_following import TrendFollowingRepository
from ..integrations.market_data.preview import (
    CN_PREVIEW_PROVIDER,
    PreviewQuoteError,
    US_PREVIEW_PROVIDER,
    collect_preview_daily_bars,
)
from ..integrations.market_data.service import MarketDataService
from ..market_review.trading_calendar import (
    get_completed_trading_days,
    get_market_now,
    get_trading_days_between,
)
from .config import DEFAULT_CONFIG, TrendFollowingConfig
from .duration import DURATION_CALENDAR_LOOKBACK_DAYS, count_trend_duration_days
from .features import calculate_features
from .models import DailyBar
from .preview_cache import save_preview
from .ranking import rank_candidates
from .regime import calculate_market_regime
from .state import transition_state
from .universe import get_universe, normalize_market

logger = logging.getLogger(__name__)


def _to_daily_bar(bar: Any) -> DailyBar:
    return DailyBar(bar.trade_date, bar.open, bar.high, bar.low, bar.close, bar.volume, bar.amount)


def _bars_before(bars: list[DailyBar], trade_date: date) -> list[DailyBar]:
    return [item for item in bars if item.trade_date < trade_date]


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

    def resolve_preview_trade_date(self, requested: date | None = None) -> date:
        if requested is not None:
            return requested
        return get_market_now(self.market.lower()).date()

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

    def run_preview(
        self,
        trade_date: date | None = None,
        *,
        preview_time: datetime | None = None,
    ) -> dict[str, Any]:
        """Compute today's trend using official T-1 state plus a temporary today bar.

        Preview never writes ``trend_following_snapshot`` and never feeds later
        official or preview runs. Each call reloads the previous official snapshot.
        """
        started = monotonic()
        effective_date = self.resolve_preview_trade_date(trade_date)
        members = get_universe(self.market)
        universe_codes = {member.code for member in members}
        benchmark_code = self.config.benchmark_codes[self.market]
        requested = sorted(universe_codes | {benchmark_code})
        provider = CN_PREVIEW_PROVIDER if self.market == "CN" else US_PREVIEW_PROVIDER
        quote_count = 0
        data_as_of = None
        try:
            bars, provider, quote_count, data_as_of = collect_preview_daily_bars(
                self.market_data,
                self.market,
                requested,
                effective_date,
            )
            overlay = {
                code: DailyBar(
                    trade_date=bar.trade_date,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=float(bar.volume),
                    amount=bar.amount,
                )
                for code, bar in bars.items()
            }
            result = self._run_single_date(effective_date, persist=False, overlay_bars=overlay)
        except PreviewQuoteError as exc:
            elapsed = round(monotonic() - started, 3)
            generated_at = preview_time or utc_now()
            logger.exception(
                "market=%s job=trend_following_preview provider=%s snapshot_failed elapsed_seconds=%s",
                self.market,
                provider,
                elapsed,
            )
            save_preview(
                self.market,
                {
                    "status": "failed",
                    "market": self.market,
                    "trade_date": effective_date.isoformat(),
                    "preview_time": utc_isoformat(generated_at),
                    "data_as_of": utc_isoformat(data_as_of),
                    "provider": provider,
                    "quote_count": quote_count,
                    "universe_size": len(universe_codes),
                    "data_coverage": 0.0,
                    "rankable_count": 0,
                    "snapshot_count": 0,
                    "candidate_count": 0,
                    "snapshots": [],
                    "warnings": [str(exc)],
                    "elapsed_seconds": elapsed,
                },
            )
            raise
        elapsed = round(monotonic() - started, 3)
        generated_at = preview_time or utc_now()
        payload = {
            **result,
            "preview_time": utc_isoformat(generated_at),
            "data_as_of": utc_isoformat(data_as_of),
            "provider": provider,
            "quote_count": quote_count,
            "elapsed_seconds": elapsed,
        }
        payload.setdefault("snapshots", [])
        logger.info(
            "market=%s job=trend_following_preview preview_time=%s provider=%s universe_size=%s "
            "quote_count=%s data_coverage=%s rankable_count=%s snapshot_count=%s candidate_count=%s "
            "elapsed_seconds=%s status=%s",
            self.market,
            payload["preview_time"],
            provider,
            payload.get("universe_size"),
            quote_count,
            payload.get("data_coverage"),
            payload.get("rankable_count"),
            payload.get("snapshot_count"),
            payload.get("candidate_count"),
            elapsed,
            payload.get("status"),
        )
        save_preview(self.market, payload)
        return payload

    def _duration_calendar_lookback_days(self) -> int:
        return max(self.config.calendar_lookback_days, DURATION_CALENDAR_LOOKBACK_DAYS)

    def _forward_adjusted_histories(
        self,
        codes: set[str],
        effective_date: date,
        *,
        calendar_lookback_days: int | None = None,
    ) -> dict[str, list[DailyBar]]:
        """Read-only benchmark tails. Official and preview share this db_fresh path."""
        if not codes:
            return {}
        lookback = self.config.calendar_lookback_days if calendar_lookback_days is None else calendar_lookback_days
        result = self.market_data.get_daily_bars(
            sorted(codes),
            effective_date - timedelta(days=lookback),
            effective_date,
            adjustment="forward",
            source_policy="db_fresh",
        ).data
        histories: dict[str, list[DailyBar]] = {}
        for code, bars in result.items():
            histories[code] = [
                _to_daily_bar(bar)
                for bar in sorted(bars, key=lambda item: item.trade_date)
                if bar.trade_date <= effective_date
            ]
        return histories

    def _load_db_histories(
        self,
        codes: set[str],
        effective_date: date,
        *,
        drop_today: bool,
        calendar_lookback_days: int | None = None,
    ) -> dict[str, list[DailyBar]]:
        histories: dict[str, list[DailyBar]] = defaultdict(list)
        lookback = self.config.calendar_lookback_days if calendar_lookback_days is None else calendar_lookback_days
        rows = self.repository.load_daily_history(
            codes, effective_date, calendar_lookback_days=lookback
        )
        for item in rows:
            if item["trade_date"] > effective_date:
                continue
            if drop_today and item["trade_date"] == effective_date:
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
        return histories

    def _apply_overlay_bars(
        self,
        histories: dict[str, list[DailyBar]],
        overlay_bars: dict[str, DailyBar],
        effective_date: date,
    ) -> None:
        for code, bar in overlay_bars.items():
            prior = _bars_before(histories.get(code, []), effective_date)
            prior.append(bar)
            histories[code] = prior

    def _run_single_date(
        self,
        effective_date: date,
        *,
        persist: bool = True,
        overlay_bars: dict[str, DailyBar] | None = None,
    ) -> dict[str, Any]:
        members = get_universe(self.market)
        member_by_code = {member.code: member for member in members}
        universe_codes = set(member_by_code)
        benchmark_code = self.config.benchmark_codes[self.market]
        universe_key = self.config.universe_keys[self.market]
        duration_lookback = self._duration_calendar_lookback_days()
        benchmark_history = self._forward_adjusted_histories(
            {benchmark_code}, effective_date, calendar_lookback_days=duration_lookback
        ).get(benchmark_code, [])
        drop_today = overlay_bars is not None
        if overlay_bars is None:
            ready_codes = self.repository.daily_codes_on_date(universe_codes, effective_date)
            benchmark_ready = bool(benchmark_history and benchmark_history[-1].trade_date == effective_date)
        else:
            ready_codes = {code for code in universe_codes if code in overlay_bars}
            overlay_benchmark = overlay_bars.get(benchmark_code)
            benchmark_ready = overlay_benchmark is not None and overlay_benchmark.trade_date == effective_date
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

        histories = self._load_db_histories(
            universe_codes,
            effective_date,
            drop_today=drop_today,
            calendar_lookback_days=duration_lookback,
        )
        if overlay_bars is None:
            benchmark_bars = benchmark_history
        else:
            histories[benchmark_code] = _bars_before(benchmark_history, effective_date)
            self._apply_overlay_bars(histories, overlay_bars, effective_date)
            benchmark_bars = histories.get(benchmark_code, [])
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
            result = calculate_features(bars, self.config.minimum_history_bars, self.config)
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
        decisions = {
            row["code"]: transition_state(row, previous.get(row["code"]), config=self.config)
            for row in ranked
        }
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

        from .fragility import calculate_fragility
        from .lifecycle import classify_lifecycle
        from .health_config import DEFAULT_CONFIG as HEALTH_CONFIG

        health_history = self.repository.health_history(effective_date, universe_codes)
        for snapshot in snapshots:
            snapshot["trend_duration_days"] = count_trend_duration_days(
                histories.get(str(snapshot["code"]), []),
                as_of=effective_date,
                minimum_bars=self.config.minimum_history_bars,
            )

            code = str(snapshot["code"])
            snapshot["features"]["rank_percentile"] = (snapshot["rank"] - 1) / max(len(ranked) - 1, 1)
            snapshot.update(calculate_fragility(snapshot, health_history.get(code, {}), as_of=effective_date))
            snapshot["trend_lifecycle"] = classify_lifecycle(snapshot)

        summary = {
            "market": self.market,
            "trade_date": effective_date,
            "universe_key": universe_key,
            "benchmark_code": benchmark_code,
            "market_regime": regime["market_regime"],
            "market_score": regime["market_score"],
            "universe_size": len(universe_codes),
            "data_ready_count": len(ready_codes),
            "data_coverage": data_coverage,
            "rankable_count": len(ranked),
            "candidate_count": sum(item["state"] == "CANDIDATE" for item in snapshots),
            "warnings": warnings,
            "features": {
                **regime["features"],
                "lifecycle_counts": {stage: sum(s.get("trend_lifecycle") == stage for s in snapshots)
                                     for stage in ("IGNITION", "EMERGING", "EXPANSION", "MATURE", "EXHAUSTION", "BROKEN")},
                "high_fragility_count": sum(s.get("fragility_score") is not None
                                            and s["fragility_score"] >= HEALTH_CONFIG.high_fragility
                                            and s.get("trend_lifecycle") != "BROKEN" for s in snapshots),
            },
            "score_breakdown": regime["score_breakdown"],
        }
        if persist:
            snapshot_count = self.repository.replace_day(effective_date, snapshots, summary)
        else:
            for item in snapshots:
                member = member_by_code.get(str(item["code"]))
                if member is not None:
                    item["name"] = member.name
            snapshot_count = len(snapshots)
        result = {
            "status": "completed",
            **summary,
            "trade_date": effective_date.isoformat(),
            "snapshot_count": snapshot_count,
        }
        if not persist:
            result["snapshots"] = snapshots
        logger.info(
            "market=%s job=%s trade_date=%s regime=%s snapshots=%s warnings=%s",
            self.market,
            "trend_following" if persist else "trend_following_preview",
            effective_date,
            regime["market_regime"],
            snapshot_count,
            warnings,
        )
        return result


__all__ = ["TrendFollowingService"]
