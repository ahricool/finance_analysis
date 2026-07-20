"""Compute and persist one point-in-time, market-scoped daily research snapshot."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select

from finance_analysis.database.models.stock import MarketDataSymbol, StockDaily
from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.quant.config import get_quant_config
from finance_analysis.quant.events.scoring import score_events
from finance_analysis.quant.exceptions import BenchmarkDataMissingError, FeatureDataMissingError
from finance_analysis.quant.features.daily import add_relative_strength, build_daily_features
from finance_analysis.quant.markets import get_quant_market_config
from finance_analysis.quant.regime.service import MarketRegimeService
from finance_analysis.quant.sectors.service import SectorRegimeService, build_synthetic_sector_benchmark


class DailyResearchService:
    def __init__(self, repository=None):
        self.repository = repository or QuantRepository()
        self.config = get_quant_config()

    def run(self, market: str, universe_key: str, trade_date: date) -> dict:
        market_config = get_quant_market_config(market)
        universe = self.repository.get_universe(universe_key)
        if not universe or universe.market != market_config.market:
            raise ValueError(f"Unknown {market_config.market} universe {universe_key}")
        members = self.repository.active_members(universe.id, trade_date)
        if not members:
            raise FeatureDataMissingError(f"No active universe members for {trade_date}")

        member_codes = {symbol.code for _, symbol in members}
        real_sector_benchmarks = {
            member.sector_benchmark_code
            for member, _ in members
            if member.sector_benchmark_code and not member.sector_benchmark_code.startswith("CN-SECTOR-")
        }
        required_benchmarks = set(market_config.benchmark_dependencies)
        frames = self._load(
            market_config.market,
            member_codes | required_benchmarks | real_sector_benchmarks,
            trade_date - timedelta(days=500),
            trade_date,
        )
        missing_benchmarks = {
            code for code in required_benchmarks if code not in frames or len(frames[code]) < 61
        }
        if missing_benchmarks:
            raise BenchmarkDataMissingError(f"Missing {market_config.market} benchmark history: {sorted(missing_benchmarks)}")
        stale_benchmarks = {
            code
            for code in required_benchmarks
            if pd.Timestamp(frames[code]["date"].iloc[-1]).date() != trade_date
        }
        if stale_benchmarks:
            raise BenchmarkDataMissingError(
                f"{market_config.market} benchmark data is not ready for {trade_date}: {sorted(stale_benchmarks)}"
            )

        missing_daily = {
            symbol.code
            for _, symbol in members
            if symbol.code not in frames
            or frames[symbol.code].empty
            or pd.Timestamp(frames[symbol.code]["date"].iloc[-1]).date() != trade_date
        }
        missing_mapping = {
            symbol.code
            for member, symbol in members
            if not member.sector_key or not member.sector_benchmark_code
        }
        missing_sector_benchmark = {
            symbol.code
            for member, symbol in members
            if member.sector_benchmark_code
            and not member.sector_benchmark_code.startswith("CN-SECTOR-")
            and member.sector_benchmark_code not in frames
        }
        excluded = missing_daily | missing_mapping | missing_sector_benchmark
        eligible_members = [(member, symbol) for member, symbol in members if symbol.code not in excluded]
        if not eligible_members:
            raise FeatureDataMissingError(
                f"No rankable {market_config.market} universe members for {trade_date}; "
                f"missing_daily={sorted(missing_daily)} missing_sector_mapping={sorted(missing_mapping)}"
            )
        member_frames = {symbol.code: frames[symbol.code] for _, symbol in eligible_members}
        market_result = MarketRegimeService(self.config.regime).calculate(
            frames[market_config.primary_benchmark],
            frames[market_config.broad_benchmark],
            frames[market_config.risk_benchmark],
            member_frames,
            benchmark_labels=(
                market_config.primary_benchmark,
                market_config.broad_benchmark,
                market_config.risk_benchmark,
            ),
        )
        regime = self.repository.save_market_regime(
            {
                "market": market_config.market,
                "trade_date": trade_date,
                "model_version": self.config.regime_model_version,
                "regime": market_result.regime,
                "market_score": market_result.market_score,
                "max_equity_exposure": market_result.max_equity_exposure,
                "sector_permissions": market_result.sector_permissions,
                "features": market_result.features,
                "reasons": market_result.reasons,
            }
        )

        grouped: dict[str, list] = {}
        for member, symbol in eligible_members:
            grouped.setdefault(member.sector_key, []).append((member, symbol))
        sector_inputs = {}
        for sector_key, sector_members in grouped.items():
            benchmark_code = sector_members[0][0].sector_benchmark_code
            sector_member_frames = {symbol.code: member_frames[symbol.code] for _, symbol in sector_members}
            if benchmark_code.startswith("CN-SECTOR-"):
                benchmark_frame = build_synthetic_sector_benchmark(sector_member_frames)
            else:
                benchmark_frame = frames.get(benchmark_code)
            if benchmark_frame is None or len(benchmark_frame) < 61:
                excluded.update(symbol.code for _, symbol in sector_members)
                continue
            sector_inputs[sector_key] = (benchmark_code, benchmark_frame, sector_member_frames)
        sectors = SectorRegimeService().rank(
            sector_inputs,
            frames[market_config.primary_benchmark],
            market_result.regime,
        )
        self.repository.save_sector_regimes(
            [
                {
                    "market": market_config.market,
                    "trade_date": trade_date,
                    "model_version": self.config.sector_model_version,
                    **row,
                }
                for row in sectors
            ]
        )
        sector_scores = {row["sector_key"]: row["sector_score"] for row in sectors}
        eligible_members = [
            (member, symbol)
            for member, symbol in eligible_members
            if symbol.code not in excluded and member.sector_key in sector_scores
        ]
        if not eligible_members:
            raise FeatureDataMissingError("No universe members remain after sector benchmark validation")

        cutoff = datetime.combine(
            trade_date,
            market_config.market_close_time,
            ZoneInfo(market_config.timezone),
        )
        daily_values = []
        event_values = []
        for member, symbol in eligible_members:
            bars = member_frames[symbol.code]
            if member.sector_benchmark_code.startswith("CN-SECTOR-"):
                sector_bars = sector_inputs[member.sector_key][1]
            else:
                sector_bars = frames[member.sector_benchmark_code]
            features = add_relative_strength(
                build_daily_features(bars),
                frames[market_config.primary_benchmark],
                sector_bars,
            ).iloc[-1]
            portfolio_metadata = self._portfolio_metadata(bars, features, trade_date)
            events = self.repository.available_events(symbol.id, cutoff, cutoff - timedelta(days=90))
            event = score_events(events, cutoff)
            explicit = {
                key: None if pd.isna(features.get(key)) else float(features[key])
                for key in (
                    "ret_1d", "ret_5d", "ret_20d", "ret_60d", "price_ma20_ratio",
                    "price_ma60_ratio", "volume_ratio_5d", "atr_14", "realized_vol_20d",
                    "distance_from_20d_high", "gap_return", "rsi_14", "relative_5d_to_market",
                    "relative_20d_to_market", "relative_5d_to_sector", "relative_20d_to_sector",
                )
            }
            daily_values.append(
                {
                    "trade_date": trade_date,
                    "symbol_id": symbol.id,
                    "feature_version": self.config.feature_version,
                    **explicit,
                    "market_score": market_result.market_score,
                    "sector_score": sector_scores[member.sector_key],
                    "event_score": event["event_score"],
                    "features": {
                        "market": market_config.market,
                        "sector_key": member.sector_key,
                        "sector_benchmark_code": member.sector_benchmark_code,
                        "price_mode": "raw",
                        **portfolio_metadata,
                    },
                }
            )
            event_values.append(
                {
                    "trade_date": trade_date,
                    "symbol_id": symbol.id,
                    "feature_version": self.config.event_feature_version,
                    "positive_event_count_3d": event["positive_event_count_3d"],
                    "negative_event_count_3d": event["negative_event_count_3d"],
                    "event_score": event["event_score"],
                    "negative_event_veto": event["negative_event_veto"],
                    "feature_payload": {"components": event["components"]},
                }
            )
        self.repository.save_daily_features(daily_values)
        self.repository.save_event_features(event_values)
        warnings = ["price_mode=raw"]
        if missing_daily:
            warnings.append(f"excluded_missing_daily={len(missing_daily)}")
        if missing_mapping:
            warnings.append(f"excluded_missing_sector_mapping={len(missing_mapping)}")
        if missing_sector_benchmark:
            warnings.append(f"excluded_missing_sector_benchmark={len(missing_sector_benchmark)}")
        return {
            "market_regime": regime,
            "sectors": sectors,
            "feature_count": len(daily_values),
            "eligible_codes": [symbol.code for _, symbol in eligible_members],
            "coverage": {
                "universe_members": len(members),
                "rankable_members": len(eligible_members),
                "sector_mapping_missing": len(missing_mapping),
                "daily_data_missing": len(missing_daily),
            },
            "warnings": warnings,
        }

    @staticmethod
    def _portfolio_metadata(bars: pd.DataFrame, features: pd.Series, trade_date: date) -> dict:
        ordered = bars.sort_values("date").reset_index(drop=True)
        close = pd.to_numeric(ordered["close"], errors="coerce")
        volume = pd.to_numeric(ordered["volume"], errors="coerce")
        amount = (
            pd.to_numeric(ordered["amount"], errors="coerce")
            if "amount" in ordered
            else pd.Series(float("nan"), index=ordered.index)
        )
        turnover = amount.where(amount > 0, close * volume)
        recent_turnover = turnover.tail(20).dropna()
        liquidity = float(recent_turnover.mean()) if not recent_turnover.empty else 0.0
        realized_volatility = features.get("realized_vol_20d")
        if pd.isna(realized_volatility):
            realized_volatility = close.pct_change().tail(20).std(ddof=1) * math.sqrt(252)
        risk_penalty = (
            0.15
            if pd.isna(realized_volatility)
            else min(0.15, max(0.0, float(realized_volatility)) * 0.10)
        )
        required_features = (
            "ret_60d", "price_ma60_ratio", "realized_vol_20d",
            "relative_20d_to_market", "relative_20d_to_sector",
        )
        latest_date = pd.Timestamp(ordered["date"].iloc[-1]).date()
        has_sufficient_data = (
            len(ordered) >= 61
            and latest_date == trade_date
            and all(pd.notna(features.get(key)) for key in required_features)
        )
        return {
            "has_sufficient_data": bool(has_sufficient_data),
            "liquidity": liquidity,
            "risk_penalty": risk_penalty,
            "close": float(close.iloc[-1]),
        }

    def _load(self, market: str, codes: set[str], start: date, end: date) -> dict[str, pd.DataFrame]:
        with self.repository.db.get_session() as session:
            rows = session.execute(
                select(
                    MarketDataSymbol.code, StockDaily.date, StockDaily.open, StockDaily.high,
                    StockDaily.low, StockDaily.close, StockDaily.volume, StockDaily.amount,
                )
                .join(StockDaily, StockDaily.symbol_id == MarketDataSymbol.id)
                .where(
                    MarketDataSymbol.market == market,
                    MarketDataSymbol.code.in_(codes),
                    StockDaily.date.between(start, end),
                )
                .order_by(MarketDataSymbol.code, StockDaily.date)
            ).all()
        frame = pd.DataFrame(
            rows,
            columns=["code", "date", "open", "high", "low", "close", "volume", "amount"],
        )
        return {
            code: group.drop(columns="code").reset_index(drop=True)
            for code, group in frame.groupby("code")
        }
