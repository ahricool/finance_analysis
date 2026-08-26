"""Application service orchestrating the pure ETF rotation engine."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from finance_analysis.database.repositories.etf_rotation import ETFRotationRepository
from finance_analysis.etf_rotation.classifier import classify_state, is_overheated
from finance_analysis.etf_rotation.config import DEFAULT_CONFIG, ETFRotationConfig
from finance_analysis.etf_rotation.features import calculate_features
from finance_analysis.etf_rotation.models import DailyBar
from finance_analysis.etf_rotation.ranking import calculate_rank_changes, rank_cross_section
from finance_analysis.etf_rotation.readiness import require_minimum_coverage
from finance_analysis.etf_rotation.risk import calculate_stop_loss_pct, calculate_suggested_stop_price
from finance_analysis.etf_rotation.scoring import calculate_entry_score, calculate_momentum_score
from finance_analysis.etf_rotation.selector import select_candidates
from finance_analysis.etf_rotation.universe import enabled_etfs, normalize_etf_market
from finance_analysis.market_review.trading_calendar import get_completed_trading_days

logger = logging.getLogger(__name__)


class ETFRotationService:
    def __init__(
        self,
        market: str = "CN",
        repository: ETFRotationRepository | None = None,
        *,
        config: ETFRotationConfig = DEFAULT_CONFIG,
        now: datetime | None = None,
    ) -> None:
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
        universe_size = len(codes)
        warnings: list[str] = []

        if trade_date is None:
            latest_dates = self.repository.latest_daily_dates(codes)
            ready_codes = {code for code in codes if latest_dates.get(code) == effective_date}
        else:
            # Historical point-in-time reruns remain possible after newer bars arrive.
            ready_codes = self.repository.daily_codes_on_date(codes, effective_date)
        data_coverage, warning = require_minimum_coverage(
            label="daily data",
            available=len(ready_codes),
            expected=universe_size,
            minimum=self.config.minimum_data_coverage,
        )
        if warning:
            warnings.append(warning)

        history_rows = self.repository.load_daily_history(ready_codes, effective_date)
        histories: dict[str, list[DailyBar]] = defaultdict(list)
        symbol_ids: dict[str, int] = {}
        for row in history_rows:
            code = str(row["code"])
            symbol_ids[code] = int(row["symbol_id"])
            histories[code].append(
                DailyBar(
                    trade_date=row["trade_date"],
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    amount=None if row["amount"] is None else float(row["amount"]),
                )
            )

        feature_rows: list[dict[str, Any]] = []
        for code in sorted(ready_codes):
            bars = histories.get(code, [])
            if not bars or bars[-1].trade_date != effective_date:
                continue
            features = calculate_features(bars)
            if features is None:
                continue
            member = member_by_code[code]
            feature_rows.append(
                {
                    "trade_date": effective_date,
                    "market": self.market,
                    "symbol_id": symbol_ids[code],
                    "code": code,
                    "name": member.name,
                    "category": member.category,
                    "theme": member.theme,
                    "risk_group": member.risk_group,
                    **features.to_dict(),
                }
            )

        rankable_count = len(feature_rows)
        rankable_coverage, warning = require_minimum_coverage(
            label="rankable",
            available=rankable_count,
            expected=universe_size,
            minimum=self.config.minimum_rankable_coverage,
        )
        if warning:
            warnings.append(warning)

        ranked = rank_cross_section(feature_rows)
        historical = self.repository.historical_rank_5d(effective_date, codes)
        evaluated: list[dict[str, Any]] = []
        for row in ranked:
            row.update(calculate_rank_changes(int(row["rank_5d"]), historical.get(str(row["code"]), {})))
            momentum_score = calculate_momentum_score(row, self.config)
            entry_score, components = calculate_entry_score(row, momentum_score, self.config)
            stop_loss_pct = calculate_stop_loss_pct(float(row["realized_vol_20d"]), self.config)
            row.update(
                {
                    "momentum_score": momentum_score,
                    "entry_score": entry_score,
                    "score_components": components,
                    "stop_loss_pct": stop_loss_pct,
                    "suggested_stop_price": calculate_suggested_stop_price(
                        float(row["reference_price"]), stop_loss_pct
                    ),
                    "overheated": is_overheated(row, self.config),
                    "state": classify_state(row, momentum_score, self.config),
                    "is_candidate": False,
                    "candidate_rank": None,
                }
            )
            evaluated.append(row)

        candidate_codes = select_candidates(evaluated, self.config)
        candidate_rank = {code: index + 1 for index, code in enumerate(candidate_codes)}
        for row in evaluated:
            rank = candidate_rank.get(str(row["code"]))
            row["is_candidate"] = rank is not None
            row["candidate_rank"] = rank

        snapshot_count = self.repository.upsert_snapshots(evaluated)
        summary = {
            "status": "completed",
            "market": self.market,
            "trade_date": effective_date.isoformat(),
            "universe_size": universe_size,
            "data_ready_count": len(ready_codes),
            "data_coverage": data_coverage,
            "rankable_count": rankable_count,
            "rankable_coverage": rankable_coverage,
            "snapshot_count": snapshot_count,
            "candidate_count": len(candidate_codes),
            "candidate_codes": candidate_codes,
            "warnings": warnings,
        }
        logger.info(
            "market=%s job=etf_rotation trade_date=%s universe_size=%s data_coverage=%.2f "
            "rankable_count=%s snapshot_count=%s candidate_count=%s warnings=%s",
            self.market,
            effective_date,
            universe_size,
            data_coverage,
            rankable_count,
            snapshot_count,
            len(candidate_codes),
            warnings,
        )
        return summary


__all__ = ["ETFRotationService"]
