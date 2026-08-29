"""Application service orchestrating the point-in-time ETF Rotation V2 engine."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from finance_analysis.database.repositories.etf_rotation import ETFRotationRepository
from finance_analysis.etf_rotation.classifier import classify_state, is_overheated
from finance_analysis.etf_rotation.config import DEFAULT_CONFIG, ETFRotationConfig
from finance_analysis.etf_rotation.correlation import rolling_correlations
from finance_analysis.etf_rotation.eligibility import is_absolute_trend_eligible, is_liquidity_eligible
from finance_analysis.etf_rotation.features import calculate_features
from finance_analysis.etf_rotation.models import DailyBar
from finance_analysis.etf_rotation.ranking import (
    FACTOR_RANK_DIRECTIONS,
    calculate_rank_changes,
    rank_cross_section,
    rank_features,
)
from finance_analysis.etf_rotation.readiness import require_minimum_coverage
from finance_analysis.etf_rotation.regime import calculate_market_regime
from finance_analysis.etf_rotation.risk import calculate_stop_loss_pct, calculate_suggested_stop_price
from finance_analysis.etf_rotation.scoring import calculate_entry_score, calculate_factor_scores
from finance_analysis.etf_rotation.selector import public_rotation_action, select_candidates
from finance_analysis.etf_rotation.universe import enabled_etfs, normalize_etf_market
from finance_analysis.market_review.trading_calendar import get_completed_trading_days

logger = logging.getLogger(__name__)

class ETFRotationService:
    def __init__(self, market: str = "CN", repository: ETFRotationRepository | None = None, *,
                 config: ETFRotationConfig = DEFAULT_CONFIG, now: datetime | None = None) -> None:
        self.market = normalize_etf_market(market)
        repository_market = getattr(repository, "market", self.market)
        if normalize_etf_market(repository_market) != self.market:
            raise ValueError(
                f"ETF Rotation service market={self.market} does not match repository market={repository_market}"
            )
        self.repository = repository or ETFRotationRepository(self.market)
        self.config = config
        self.now = now or datetime.now(timezone.utc)

    def resolve_trade_date(self, requested: date | None = None) -> date:
        return requested or get_completed_trading_days(self.market.lower(), 1, self.now)[-1]

    def run(self, trade_date: date | None = None) -> dict[str, Any]:
        effective_date = self.resolve_trade_date(trade_date)
        members = enabled_etfs(self.market)
        member_by_code = {member.code: member for member in members}
        codes = set(member_by_code)
        benchmark_code = self.config.benchmark_codes[self.market]
        warnings: list[str] = []
        latest_dates = self.repository.latest_daily_dates(codes | {benchmark_code})
        if trade_date is None:
            ready_codes = {code for code in codes if latest_dates.get(code) == effective_date}
            benchmark_ready = latest_dates.get(benchmark_code) == effective_date
        else:
            ready_codes = self.repository.daily_codes_on_date(codes, effective_date)
            benchmark_ready = benchmark_code in self.repository.daily_codes_on_date({benchmark_code}, effective_date)
        data_coverage, warning = require_minimum_coverage(
            label="daily data",
            available=len(ready_codes),
            expected=len(codes),
            minimum=self.config.minimum_data_coverage,
        )
        if warning:
            warnings.append(warning)
        if not benchmark_ready:
            warnings.append(f"benchmark {benchmark_code} is missing on completed trading date {effective_date}")

        requested_codes = ready_codes | ({benchmark_code} if benchmark_ready else set())
        history_rows = self.repository.load_daily_history(requested_codes, effective_date)
        histories: dict[str, list[DailyBar]] = defaultdict(list)
        symbol_ids: dict[str, int] = {}
        for item in history_rows:
            code = str(item["code"])
            symbol_ids[code] = int(item["symbol_id"])
            histories[code].append(DailyBar(
                trade_date=item["trade_date"], close=float(item["close"]), volume=float(item["volume"]),
                amount=None if item["amount"] is None else float(item["amount"]),
            ))
        benchmark_features = (
            calculate_features(histories.get(benchmark_code, ()), self.config) if benchmark_ready else None
        )
        benchmark_ready = benchmark_features is not None and histories[benchmark_code][-1].trade_date == effective_date
        if not benchmark_ready and not any("benchmark" in item for item in warnings):
            warnings.append(f"benchmark {benchmark_code} has insufficient aligned history")

        feature_rows: list[dict[str, Any]] = []
        for code in sorted(ready_codes):
            bars = histories.get(code, [])
            if not bars or bars[-1].trade_date != effective_date:
                continue
            features = calculate_features(bars, self.config)
            if features is None:
                continue
            payload = features.to_dict()
            if benchmark_ready and benchmark_features is not None:
                payload["rs_20d"] = payload["ret_20d"] - benchmark_features.ret_20d
                payload["rs_60d"] = payload["ret_60d"] - benchmark_features.ret_60d
            else:
                payload["rs_20d"] = payload["rs_60d"] = None
            member = member_by_code[code]
            feature_rows.append({
                "trade_date": effective_date, "market": self.market, "symbol_id": symbol_ids[code],
                "code": code, "name": member.name, "category": member.category, "theme": member.theme,
                "risk_group": member.risk_group, "relative_strength_ready": benchmark_ready,
                "diagnostics": {"relative_strength": "ready" if benchmark_ready else "benchmark_missing"}, **payload,
            })

        rankable_count = len(feature_rows)
        rankable_coverage, warning = require_minimum_coverage(
            label="rankable",
            available=rankable_count,
            expected=len(codes),
            minimum=self.config.minimum_rankable_coverage,
        )
        if warning:
            warnings.append(warning)
        ranked = rank_features(rank_cross_section(feature_rows), FACTOR_RANK_DIRECTIONS)
        historical = self.repository.historical_rank_5d(effective_date, codes)
        evaluated: list[dict[str, Any]] = []
        for row in ranked:
            row.update(calculate_rank_changes(int(row["rank_5d"]), historical.get(str(row["code"]), {})))
            row.update(calculate_factor_scores(row, self.config))
            row["momentum_score"] = row["momentum_strength_score"]
            row["absolute_trend_eligible"] = is_absolute_trend_eligible(row, self.config)
            row["liquidity_eligible"] = is_liquidity_eligible(row, self.market, self.config)
            evaluated.append(row)

        ranked_composite = rank_features(evaluated, {"composite_score": True})
        for row in ranked_composite:
            row["rank"] = row.pop("rank_composite_score")
            row.pop("pct_rank_composite_score", None)
            composite = float(row["composite_score"] or 0.0)
            entry_score, entry_components = calculate_entry_score(row, composite, self.config)
            factor_components = {
                key.removesuffix("_score"): row.get(key) for key in (
                    "momentum_strength_score", "trend_quality_score", "relative_strength_score",
                    "acceleration_score", "efficiency_score", "risk_adjusted_score", "composite_score",
                )
            }
            row["entry_score"] = entry_score
            row["score_components"] = {**factor_components, **entry_components}
            stop_loss_pct = calculate_stop_loss_pct(float(row["realized_vol_20d"]), self.config)
            row["stop_loss_pct"] = stop_loss_pct
            row["suggested_stop_price"] = calculate_suggested_stop_price(float(row["reference_price"]), stop_loss_pct)
            row["overheated"] = is_overheated(row, self.config)
            row["state"] = classify_state(row, composite, self.config)
            row["is_candidate"] = False
            row["candidate_rank"] = None

        market_snapshot = None
        regime = "NEUTRAL"
        if benchmark_ready and benchmark_features is not None:
            market_snapshot = calculate_market_regime(
                ranked_composite, benchmark_features.to_dict(), market=self.market, trade_date=effective_date,
                benchmark_code=benchmark_code, config=self.config,
            )
            regime = str(market_snapshot["regime"])
            self.repository.upsert_market_snapshot(market_snapshot)
        previous = self.repository.previous_candidate_codes(effective_date)
        correlations = rolling_correlations(
            {code: histories[code] for code in ready_codes}, self.config.correlation_window
        )
        candidate_codes = select_candidates(
            ranked_composite, self.config, previous_candidate_codes=previous, regime=regime, correlations=correlations
        )
        selected = set(candidate_codes)
        candidate_rank = {code: index + 1 for index, code in enumerate(candidate_codes)}
        for row in ranked_composite:
            code = str(row["code"])
            row["is_candidate"] = code in selected
            row["candidate_rank"] = candidate_rank.get(code)
            row["action"] = public_rotation_action(code, selected, previous)
            known = [value for pair, value in correlations.items() if code in pair and value is not None]
            row["diagnostics"]["correlation"] = {
                "window": self.config.correlation_window,
                "max_with_universe": max(known) if known else None,
                "status": "ready" if known else "insufficient_history",
            }

        snapshot_count = self.repository.upsert_snapshots(ranked_composite)
        summary = {
            "status": "completed", "market": self.market, "trade_date": effective_date.isoformat(),
            "universe_size": len(codes), "data_ready_count": len(ready_codes), "data_coverage": data_coverage,
            "rankable_count": rankable_count, "rankable_coverage": rankable_coverage,
            "snapshot_count": snapshot_count, "candidate_count": len(candidate_codes),
            "candidate_codes": candidate_codes, "regime": regime, "warnings": warnings,
        }
        logger.info("market=%s job=etf_rotation_v2 trade_date=%s regime=%s snapshots=%s candidates=%s warnings=%s",
                    self.market, effective_date, regime, snapshot_count, candidate_codes, warnings)
        return summary


__all__ = ["ETFRotationService"]
