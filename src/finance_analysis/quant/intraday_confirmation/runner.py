"""Database-backed minute confirmation runner with no network fallback."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select

from finance_analysis.database.models.quant import (
    PortfolioRecommendation,
    PortfolioRecommendationItem,
    QuantUniverseMember,
)
from finance_analysis.database.models.stock import MarketDataSymbol, StockMinute
from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.quant.cache import QuantLatestCache, cache_keys
from finance_analysis.quant.intraday_confirmation.service import IntradayConfirmationService
from finance_analysis.quant.markets import get_quant_market_config


class IntradayConfirmationRunner:
    def __init__(self, repository=None, cache=None):
        self.repository = repository or QuantRepository()
        self.cache = cache or QuantLatestCache()

    def run(self, trade_date: date, evaluated_at: datetime | None = None, market: str = "US") -> dict:
        config = get_quant_market_config(market)
        universe = self.repository.supported_universe(config.market)
        evaluated_at = evaluated_at or datetime.now(timezone.utc)
        with self.repository.db.get_session() as session:
            recommendation = session.execute(
                select(PortfolioRecommendation)
                .where(
                    PortfolioRecommendation.market == config.market,
                    PortfolioRecommendation.universe_id == universe.id,
                    PortfolioRecommendation.trade_date < trade_date,
                )
                .order_by(PortfolioRecommendation.trade_date.desc())
                .limit(1)
            ).scalar_one_or_none()
            if not recommendation:
                return {
                    "market": config.market,
                    "trade_date": str(trade_date),
                    "count": 0,
                    "status": "insufficient_data",
                    "reason": "No previous recommendation",
                }
            items = list(
                session.execute(
                    select(PortfolioRecommendationItem).where(
                        PortfolioRecommendationItem.recommendation_id == recommendation.id,
                        PortfolioRecommendationItem.action.in_(("buy", "increase", "watch")),
                    )
                ).scalars()
            )
            mappings = {
                row.symbol_id: row.sector_benchmark_code
                for row in session.execute(
                    select(QuantUniverseMember).where(
                        QuantUniverseMember.universe_id == recommendation.universe_id
                    )
                ).scalars()
            }
            candidates = [
                (item.id, item.symbol_id, item.code, item.constraints, mappings.get(item.symbol_id))
                for item in items
            ]

        values = []
        service = IntradayConfirmationService()
        for item_id, symbol_id, code, constraints, sector_code in candidates:
            own = self._bars(code, config.market, trade_date, evaluated_at, config.timezone)
            market_bars = self._bars(
                config.primary_benchmark,
                config.market,
                trade_date,
                evaluated_at,
                config.timezone,
            )
            usable_sector = sector_code if sector_code and not sector_code.startswith("CN-SECTOR-") else None
            sector_bars = self._bars(
                usable_sector or config.primary_benchmark,
                config.market,
                trade_date,
                evaluated_at,
                config.timezone,
            )
            result = service.evaluate(
                code,
                own,
                market_bars,
                sector_bars,
                evaluated_at,
                vetoed="veto_or_insufficient_data" in (constraints or {}).get("applied", []),
            )
            feature = result["features"]
            values.append(
                {
                    "trade_date": trade_date,
                    "symbol_id": symbol_id,
                    "code": code,
                    "recommendation_item_id": item_id,
                    "evaluated_at": evaluated_at,
                    "decision": result["decision"],
                    "confidence": result["confidence"],
                    "price": feature.get("price"),
                    "vwap": feature.get("vwap"),
                    "price_vs_vwap": feature.get("price_vs_vwap"),
                    "vwap_slope": feature.get("vwap_slope"),
                    "first_30m_return": feature.get("first_30m_return"),
                    "intraday_high_drawdown": feature.get("intraday_high_drawdown"),
                    "volume_ratio": feature.get("volume_ratio"),
                    "relative_strength_market": feature.get("relative_strength_market"),
                    "relative_strength_sector": feature.get("relative_strength_sector"),
                    "reasons": result["reasons"],
                    "features": feature,
                }
            )
            self.cache.set(cache_keys(config.market, code=code)["intraday"], result)
        self.repository.save_confirmations(values)
        return {
            "market": config.market,
            "trade_date": str(trade_date),
            "count": len(values),
            "decisions": {
                state: sum(item["decision"] == state for item in values)
                for state in ("confirm", "wait", "reject", "insufficient_data")
            },
        }

    def _bars(
        self,
        code: str,
        market: str,
        start_date: date,
        evaluated_at: datetime,
        timezone_name: str,
    ) -> pd.DataFrame:
        market_timezone = ZoneInfo(timezone_name)
        start = datetime.combine(start_date, time.min, tzinfo=market_timezone).astimezone(timezone.utc)
        end = min(evaluated_at, start + timedelta(days=2))
        with self.repository.db.get_session() as session:
            rows = session.execute(
                select(
                    StockMinute.bar_time,
                    StockMinute.open,
                    StockMinute.high,
                    StockMinute.low,
                    StockMinute.close,
                    StockMinute.volume,
                    StockMinute.amount,
                )
                .join(MarketDataSymbol, MarketDataSymbol.id == StockMinute.symbol_id)
                .where(
                    MarketDataSymbol.market == market,
                    MarketDataSymbol.code == code,
                    StockMinute.bar_time >= start,
                    StockMinute.bar_time < end,
                )
                .order_by(StockMinute.bar_time)
            ).all()
        return pd.DataFrame(
            rows,
            columns=["bar_time", "open", "high", "low", "close", "volume", "amount"],
        )
