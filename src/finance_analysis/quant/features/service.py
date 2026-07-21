"""Compute and persist one point-in-time, market-scoped daily research snapshot."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.database.repositories.stock import MarketDataSymbolRepository
from finance_analysis.quant.config import get_quant_config
from finance_analysis.quant.data import DailyBarLoader
from finance_analysis.quant.events.scoring import score_events
from finance_analysis.quant.exceptions import BenchmarkDataMissingError, FeatureDataMissingError
from finance_analysis.quant.features.daily import add_relative_strength, build_daily_features
from finance_analysis.quant.markets import (
    get_quant_market_config,
    get_quant_universe_codes,
    validate_universe_for_market,
)
from finance_analysis.quant.price_modes import DEFAULT_QUANT_PRICE_MODE
from finance_analysis.quant.regime.service import MarketRegimeService


class DailyResearchService:
    def __init__(self, repository=None, symbol_repository=None):
        self.repository = repository or QuantRepository()
        self.symbol_repository = symbol_repository or MarketDataSymbolRepository()
        self.config = get_quant_config()

    def run(self, market: str, universe_key: str, trade_date: date) -> dict:
        market_config = get_quant_market_config(market)
        universe_key = validate_universe_for_market(market_config.market, universe_key)
        universe = self.repository.get_universe(universe_key)
        if (
            not universe
            or universe.market != market_config.market
            or not getattr(universe, "enabled", True)
        ):
            raise ValueError(f"Supported {market_config.market} universe {universe_key} is not available")
        universe_codes = get_quant_universe_codes(market_config.market)
        symbols = self.symbol_repository.list_enabled_daily_by_codes(
            market_config.market,
            universe_codes,
        )
        symbols_by_code = {symbol.code: symbol for symbol in symbols}
        required_benchmarks = set(market_config.benchmark_dependencies)
        loaded = DailyBarLoader(self.repository).load(
            market_config.market,
            universe_codes | required_benchmarks,
            trade_date - timedelta(days=500),
            trade_date,
            DEFAULT_QUANT_PRICE_MODE,
        )
        frames = {
            code: group.rename(columns={"datetime": "date"}).drop(columns="instrument").reset_index(drop=True)
            for code, group in loaded.frame.groupby("instrument")
        }
        missing_benchmarks = {
            code for code in required_benchmarks if code not in frames or len(frames[code]) < 61
        }
        if missing_benchmarks:
            raise BenchmarkDataMissingError(
                f"Missing {market_config.market} benchmark history: {sorted(missing_benchmarks)}"
            )
        stale_benchmarks = {
            code
            for code in required_benchmarks
            if pd.Timestamp(frames[code]["date"].iloc[-1]).date() != trade_date
        }
        if stale_benchmarks:
            raise BenchmarkDataMissingError(
                f"{market_config.market} benchmark data is not ready for {trade_date}: {sorted(stale_benchmarks)}"
            )

        missing_symbols = universe_codes - set(symbols_by_code)
        missing_daily = {
            code
            for code in universe_codes
            if code not in frames
            or frames[code].empty
            or pd.Timestamp(frames[code]["date"].iloc[-1]).date() != trade_date
        }
        eligible_codes = sorted(universe_codes - missing_symbols - missing_daily)
        if not eligible_codes:
            raise FeatureDataMissingError(
                f"No rankable {market_config.market} fixed-universe symbols for {trade_date}; "
                f"missing_symbols={sorted(missing_symbols)} missing_daily={sorted(missing_daily)}"
            )
        member_frames = {code: frames[code] for code in eligible_codes}
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

        cutoff = datetime.combine(
            trade_date,
            market_config.market_close_time,
            ZoneInfo(market_config.timezone),
        )
        daily_values = []
        event_values = []
        for code in eligible_codes:
            symbol = symbols_by_code[code]
            bars = member_frames[code]
            features = add_relative_strength(
                build_daily_features(bars),
                frames[market_config.primary_benchmark],
                frames[market_config.primary_benchmark],
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
                    "sector_score": None,
                    "event_score": event["event_score"],
                    "features": {
                        "market": market_config.market,
                        "sector_key": None,
                        "sector_benchmark_code": None,
                        "sector_proxy_code": market_config.primary_benchmark,
                        "price_mode": DEFAULT_QUANT_PRICE_MODE.value,
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
        warnings = []
        if missing_daily:
            warnings.append(f"excluded_missing_daily={len(missing_daily)}")
        if missing_symbols:
            warnings.append(f"excluded_missing_symbol={len(missing_symbols)}")
        return {
            "market_regime": regime,
            "sectors": [],
            "feature_count": len(daily_values),
            "eligible_codes": eligible_codes,
            "coverage": {
                "universe_members": len(universe_codes),
                "rankable_members": len(eligible_codes),
                "symbol_missing": len(missing_symbols),
                "daily_data_missing": len(missing_daily),
                "adjustment": loaded.adjustment_coverage,
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
