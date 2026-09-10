"""Application service orchestrating the point-in-time ETF Rotation V2 engine."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from time import monotonic
from typing import Any

from finance_analysis.core.ranking import calculate_rank_changes  # pragma: allowlist secret
from finance_analysis.core.time import utc_isoformat, utc_now  # pragma: allowlist secret
from finance_analysis.database.repositories.etf_rotation import ETFRotationRepository  # pragma: allowlist secret
from finance_analysis.integrations.market_data.preview import (  # pragma: allowlist secret
    CN_PREVIEW_PROVIDER,
    PreviewQuoteError,
    US_PREVIEW_PROVIDER,
    collect_symbol_preview_daily_bars,
)
from finance_analysis.integrations.market_data.service import MarketDataService  # pragma: allowlist secret
from finance_analysis.etf_rotation.classifier import classify_state, is_overheated  # pragma: allowlist secret
from finance_analysis.etf_rotation.config import DEFAULT_CONFIG, ETFRotationConfig  # pragma: allowlist secret
from finance_analysis.etf_rotation.correlation import rolling_correlations  # pragma: allowlist secret
from finance_analysis.etf_rotation.eligibility import (  # pragma: allowlist secret
    is_absolute_trend_eligible,
    is_liquidity_eligible,
)
from finance_analysis.etf_rotation.features import calculate_features  # pragma: allowlist secret
from finance_analysis.etf_rotation.models import DailyBar  # pragma: allowlist secret
from finance_analysis.etf_rotation.preview_cache import save_preview  # pragma: allowlist secret
from finance_analysis.etf_rotation.ranking import (  # pragma: allowlist secret
    FACTOR_RANK_DIRECTIONS,
    rank_cross_section,
    rank_features,
)
from finance_analysis.etf_rotation.readiness import require_minimum_coverage  # pragma: allowlist secret
from finance_analysis.etf_rotation.regime import calculate_market_regime  # pragma: allowlist secret
from finance_analysis.etf_rotation.risk import (  # pragma: allowlist secret
    calculate_stop_loss_pct,
    calculate_suggested_stop_price,
)
from finance_analysis.etf_rotation.scoring import (  # pragma: allowlist secret
    calculate_entry_score,
    calculate_factor_scores,
)
from finance_analysis.etf_rotation.selector import public_rotation_action, select_candidates  # pragma: allowlist secret
from finance_analysis.etf_rotation.universe import enabled_etfs, normalize_etf_market  # pragma: allowlist secret
from finance_analysis.market_review.trading_calendar import (  # pragma: allowlist secret
    get_completed_trading_days,
    get_market_now,
)

logger = logging.getLogger(__name__)


def _to_daily_bar(bar: Any) -> DailyBar:
    return DailyBar(
        trade_date=bar.trade_date,
        close=float(bar.close),
        volume=float(bar.volume),
        amount=None if getattr(bar, "amount", None) is None else float(bar.amount),
    )


class ETFRotationService:
    def __init__(
        self,
        market: str = "CN",
        repository: ETFRotationRepository | None = None,
        *,
        config: ETFRotationConfig = DEFAULT_CONFIG,
        now: datetime | None = None,
        market_data: MarketDataService | None = None,
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
        self.market_data = market_data or MarketDataService()

    def resolve_trade_date(self, requested: date | None = None) -> date:
        return requested or get_completed_trading_days(self.market.lower(), 1, self.now)[-1]

    def resolve_preview_trade_date(self, requested: date | None = None) -> date:
        if requested is not None:
            return requested
        return get_market_now(self.market.lower()).date()

    def _incomplete_summary(
        self,
        *,
        trade_date: date,
        universe_size: int,
        data_ready_count: int,
        data_coverage: float,
        warnings: list[str],
    ) -> dict[str, Any]:
        summary = {
            "status": "incomplete",
            "signal_status": "SIGNAL_UNAVAILABLE",
            "market": self.market,
            "trade_date": trade_date.isoformat(),
            "universe_size": universe_size,
            "data_ready_count": data_ready_count,
            "data_coverage": data_coverage,
            "rankable_count": 0,
            "rankable_coverage": 0.0,
            "snapshot_count": 0,
            "candidate_count": 0,
            "candidate_codes": [],
            "regime": None,
            "warnings": warnings,
        }
        logger.warning(
            "market=%s job=etf_rotation_v2 trade_date=%s status=incomplete warnings=%s",
            self.market,
            trade_date,
            warnings,
        )
        return summary

    def run(self, trade_date: date | None = None) -> dict[str, Any]:
        return self._run_single_date(self.resolve_trade_date(trade_date), persist=True)

    def run_preview(
        self,
        trade_date: date | None = None,
        *,
        preview_time: datetime | None = None,
    ) -> dict[str, Any]:
        """Compute today's rotation using official T-1 state plus a temporary today bar.

        Preview never writes ``ETFMarketRotationSnapshot`` or ``ETFMomentumSnapshot``.
        Each call reloads previous official candidates and historical ranks.
        """
        started = monotonic()
        effective_date = self.resolve_preview_trade_date(trade_date)
        members = enabled_etfs(self.market)
        universe_codes = {member.code for member in members}
        benchmark_code = self.config.benchmark_codes[self.market]
        requested = sorted(universe_codes | {benchmark_code})
        provider = CN_PREVIEW_PROVIDER if self.market == "CN" else US_PREVIEW_PROVIDER
        quote_count = 0
        data_as_of = None
        try:
            bars, provider, quote_count, data_as_of = collect_symbol_preview_daily_bars(
                self.market_data,
                self.market,
                requested,
                effective_date,
            )
            overlay = {code: _to_daily_bar(bar) for code, bar in bars.items()}
            result = self._run_single_date(effective_date, persist=False, overlay_bars=overlay)
        except PreviewQuoteError as exc:
            elapsed = round(monotonic() - started, 3)
            generated_at = preview_time or utc_now()
            logger.exception(
                "market=%s job=etf_rotation_preview provider=%s quote_failed elapsed_seconds=%s",
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
                    "data_ready_count": 0,
                    "data_coverage": 0.0,
                    "rankable_count": 0,
                    "rankable_coverage": 0.0,
                    "snapshot_count": 0,
                    "candidate_count": 0,
                    "candidate_codes": [],
                    "regime": None,
                    "market_snapshot": None,
                    "warnings": [str(exc)],
                    "elapsed_seconds": elapsed,
                    "items": [],
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
        payload.setdefault("items", [])
        payload.setdefault("market_snapshot", None)
        logger.info(
            "market=%s job=etf_rotation_preview preview_time=%s provider=%s universe_size=%s "
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

    def _load_histories(
        self,
        codes: set[str],
        effective_date: date,
        overlay_bars: dict[str, DailyBar] | None,
    ) -> dict[str, list[DailyBar]]:
        fetched = self.market_data.get_daily_bars(
            sorted(codes),
            effective_date - timedelta(days=500),
            effective_date,
            adjustment="forward",
            source_policy="db_fresh",
        )
        histories = {
            code: [_to_daily_bar(bar) for bar in sorted(bars, key=lambda item: item.trade_date)]
            for code, bars in fetched.data.items()
        }
        if overlay_bars is None:
            return histories
        for code, bars in list(histories.items()):
            histories[code] = [bar for bar in bars if bar.trade_date < effective_date]
        for code, bar in overlay_bars.items():
            if bar.trade_date != effective_date:
                continue
            prior = histories.get(code, [])
            prior.append(_to_daily_bar(bar))
            histories[code] = prior
        return histories

    def _run_single_date(
        self,
        effective_date: date,
        *,
        persist: bool = True,
        overlay_bars: dict[str, DailyBar] | None = None,
    ) -> dict[str, Any]:
        members = enabled_etfs(self.market)
        member_by_code = {member.code: member for member in members}
        codes = set(member_by_code)
        benchmark_code = self.config.benchmark_codes[self.market]
        warnings: list[str] = []
        # Daily sync maintains the Index ETF pool; refresh only stale tails.
        # Remote fallback is calculation-only and never writes stock_daily.
        histories = self._load_histories(codes | {benchmark_code}, effective_date, overlay_bars)
        ready_codes = {
            code for code in codes if histories.get(code) and histories[code][-1].trade_date == effective_date
        }
        benchmark_ready = bool(
            histories.get(benchmark_code) and histories[benchmark_code][-1].trade_date == effective_date
        )
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
            if not self.config.allow_missing_relative_strength:
                return self._preview_or_official_incomplete(
                    persist=persist,
                    trade_date=effective_date,
                    universe_size=len(codes),
                    data_ready_count=len(ready_codes),
                    data_coverage=data_coverage,
                    warnings=warnings,
                )

        benchmark_features = (
            calculate_features(histories.get(benchmark_code, ()), self.config) if benchmark_ready else None
        )
        benchmark_ready = benchmark_features is not None and histories[benchmark_code][-1].trade_date == effective_date
        if not benchmark_ready and not any("benchmark" in item for item in warnings):
            warnings.append(f"benchmark {benchmark_code} has insufficient aligned history")
        if not benchmark_ready and not self.config.allow_missing_relative_strength:
            return self._preview_or_official_incomplete(
                persist=persist,
                trade_date=effective_date,
                universe_size=len(codes),
                data_ready_count=len(ready_codes),
                data_coverage=data_coverage,
                warnings=warnings,
            )

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
                for window in self.config.relative_strength_windows:
                    payload[f"rs_{window}d"] = payload[f"ret_{window}d"] - getattr(benchmark_features, f"ret_{window}d")
            else:
                for window in self.config.relative_strength_windows:
                    payload[f"rs_{window}d"] = None
            member = member_by_code[code]
            feature_rows.append(
                {
                    "trade_date": effective_date,
                    "market": self.market,
                    "code": code,
                    "name": member.name,
                    "category": member.category,
                    "theme": member.theme,
                    "risk_group": member.risk_group,
                    "relative_strength_ready": benchmark_ready,
                    "diagnostics": {"relative_strength": "ready" if benchmark_ready else "benchmark_missing"},
                    **payload,
                }
            )

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
        evaluated: list[dict[str, Any]] = []
        for row in ranked:
            row.update(calculate_factor_scores(row, self.config))
            row["momentum_score"] = row["momentum_strength_score"]
            row["absolute_trend_eligible"] = is_absolute_trend_eligible(row, self.config)
            row["liquidity_eligible"] = is_liquidity_eligible(row, self.market, self.config)
            evaluated.append(row)

        ranked_composite = rank_features(evaluated, {"composite_score": True})
        historical = self.repository.historical_composite_ranks(effective_date, codes)
        for row in ranked_composite:
            row["rank"] = row.pop("rank_composite_score")
            row.pop("pct_rank_composite_score", None)
            row.update(calculate_rank_changes(int(row["rank"]), historical.get(str(row["code"]), {})))
            composite = float(row["composite_score"] or 0.0)
            entry_score, entry_components = calculate_entry_score(row, composite, self.config)
            factor_components = {
                key.removesuffix("_score"): row.get(key)
                for key in (
                    "momentum_strength_score",
                    "trend_quality_score",
                    "relative_strength_score",
                    "acceleration_score",
                    "efficiency_score",
                    "composite_score",
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
                ranked_composite,
                benchmark_features.to_dict(),
                market=self.market,
                trade_date=effective_date,
                benchmark_code=benchmark_code,
                config=self.config,
            )
            regime = str(market_snapshot["regime"])
            if persist:
                self.repository.upsert_market_snapshot(market_snapshot)
        previous = self.repository.previous_candidate_codes(effective_date)
        correlations = rolling_correlations(
            {code: histories[code] for code in ready_codes}, self.config.correlation_window
        )
        candidate_codes = select_candidates(
            ranked_composite,
            self.config,
            previous_candidate_codes=previous,
            regime=regime,
            correlations=correlations,
            diagnostics=warnings,
        )
        selected = set(candidate_codes)
        candidate_rank = {code: index + 1 for index, code in enumerate(candidate_codes)}
        for row in ranked_composite:
            code = str(row["code"])
            row["is_candidate"] = code in selected
            row["candidate_rank"] = candidate_rank.get(code)
            row["action"] = public_rotation_action(row, selected, previous, self.config)
            known = [value for pair, value in correlations.items() if code in pair and value is not None]
            row["diagnostics"]["correlation"] = {
                "window": self.config.correlation_window,
                "max_with_universe": max(known) if known else None,
                "status": "ready" if known else "insufficient_history",
            }

        snapshot_count = (
            self.repository.upsert_snapshots(ranked_composite) if persist else len(ranked_composite)
        )
        summary = {
            "status": "completed",
            "market": self.market,
            "trade_date": effective_date.isoformat(),
            "universe_size": len(codes),
            "data_ready_count": len(ready_codes),
            "data_coverage": data_coverage,
            "rankable_count": rankable_count,
            "rankable_coverage": rankable_coverage,
            "snapshot_count": snapshot_count,
            "candidate_count": len(candidate_codes),
            "candidate_codes": candidate_codes,
            "regime": regime,
            "warnings": warnings,
        }
        logger.info(
            "market=%s job=%s trade_date=%s regime=%s snapshots=%s candidates=%s warnings=%s",
            self.market,
            "etf_rotation_v2" if persist else "etf_rotation_preview",
            effective_date,
            regime,
            snapshot_count,
            candidate_codes,
            warnings,
        )
        if persist:
            return summary
        return {**summary, "items": ranked_composite, "market_snapshot": market_snapshot}

    def _preview_or_official_incomplete(
        self,
        *,
        persist: bool,
        trade_date: date,
        universe_size: int,
        data_ready_count: int,
        data_coverage: float,
        warnings: list[str],
    ) -> dict[str, Any]:
        summary = self._incomplete_summary(
            trade_date=trade_date,
            universe_size=universe_size,
            data_ready_count=data_ready_count,
            data_coverage=data_coverage,
            warnings=warnings,
        )
        if persist:
            return summary
        return {**summary, "items": [], "market_snapshot": None}


__all__ = ["ETFRotationService"]
