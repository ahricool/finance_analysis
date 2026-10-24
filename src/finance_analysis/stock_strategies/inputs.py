"""Bulk persisted inputs, frozen membership and bounded in-memory sharing."""

from datetime import date, timedelta
from hashlib import sha256
import json

from finance_analysis.database.repositories.stock_strategies import StockStrategyRepository
from finance_analysis.database.repositories.universe import UniverseRepository, UniverseResolver
from finance_analysis.market_review.trading_calendar import get_trading_days_between
from finance_analysis.stock_strategies.features import DailyInputs, DataNotReady, etf_strength, indicators

BENCHMARKS = {"CN": "510300.SH", "US": "SPY.US"}


class InputLoader:
    def __init__(self, db_manager=None, resolver=None, repository=None):
        self.repo = repository or StockStrategyRepository(db_manager)
        self.resolver = resolver or UniverseResolver(UniverseRepository(self.repo.db))

    def freeze(self, market):
        stocks = self.resolver.resolve_universe("cn_trend" if market == "CN" else "us_trend")
        etfs = self.resolver.resolve_universe("cn_index_etf" if market == "CN" else "us_index_etf")
        breadth = self.resolver.resolve_universe("us_sp500") if market == "US" else stocks
        stock_codes = sorted(r.code for r in stocks if r.instrument_type == "STOCK" and r.listing_status == "ACTIVE")
        etf_codes = sorted(r.code for r in etfs if r.instrument_type == "ETF" and r.listing_status == "ACTIVE")
        if not stock_codes or not etf_codes or not breadth:
            raise DataNotReady("等待股票/ETF/广度Universe主数据同步")
        metadata = {r.code: dict(name=r.name, type=r.instrument_type) for r in (*stocks, *etfs, *breadth)}
        metadata.setdefault(BENCHMARKS[market], dict(name="沪深300ETF" if market == "CN" else "SPY", type="ETF"))
        frozen = dict(
            stocks=stock_codes,
            etfs=etf_codes,
            breadth=sorted(r.code for r in breadth if r.instrument_type == "STOCK"),
            instruments=metadata,
        )
        frozen["hash"] = sha256(json.dumps(frozen, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return frozen

    def load(self, market, day, universe, anchor_dates=()):
        start = day - timedelta(days=550)
        sessions = get_trading_days_between(market.lower(), start, day)[-270:]
        start = sessions[0] if sessions else start
        future = get_trading_days_between(market.lower(), day + timedelta(days=1), day + timedelta(days=30))
        if not future or not sessions or sessions[-1] != day:
            raise DataNotReady("交易日历缺少当前或下一交易日")
        codes = sorted(set(universe["stocks"] + universe["etfs"] + universe["breadth"] + [BENCHMARKS[market]]))
        if len(codes) > 10000:
            raise DataNotReady("冻结范围超过10000证券的计算预算，请核对Universe配置")
        anchors = set(anchor_dates) | {d.isoformat() for d in sessions[-2:]}
        features, prices = {}, {}
        digest = sha256()
        for code, rows in self.repo.daily_groups(codes, start, day):
            if rows:
                features[code] = indicators(rows, sessions)
                prices[code] = {r["date"].isoformat(): r["close"] for r in rows if r["date"].isoformat() in anchors}
                digest.update(code.encode())
                for row in rows:
                    digest.update(json.dumps(row, default=str, sort_keys=True).encode())
        older_anchors = sorted(date.fromisoformat(d) for d in anchors if d and d < start.isoformat())
        if older_anchors:
            for code, anchor_date, close in self.repo.anchor_prices(codes, older_anchors):
                prices.setdefault(code, {})[anchor_date.isoformat()] = close
                digest.update(json.dumps([code, str(anchor_date), close]).encode())
        ready = sum(bool(features.get(c, {}).get("valid")) for c in universe["stocks"])
        coverage = ready / len(universe["stocks"])
        if coverage < 0.98:
            raise DataNotReady(f"{day}股票收盘覆盖率{coverage:.1%}，要求至少98%")
        etf_ready = sum(bool(features.get(c, {}).get("valid")) for c in universe["etfs"])
        if etf_ready / len(universe["etfs"]) < 0.98:
            raise DataNotReady(f"{day}ETF收盘覆盖不足98%")
        regimes, etf_regime, etf_generated, trend60 = self.repo.market_context(market, day)
        return DailyInputs(
            market=market,
            day=day,
            next_day=future[0],
            month_end=future[0].month != day.month,
            features=features,
            instruments=universe["instruments"],
            stocks=tuple(universe["stocks"]),
            etfs=tuple(universe["etfs"]),
            breadth_codes=tuple(universe["breadth"]),
            prices=prices,
            trends={40: etf_strength(features, BENCHMARKS[market]), 60: trend60} if trend60 else {},
            regimes=regimes,
            etf_regime=etf_regime,
            benchmark=BENCHMARKS[market],
            provenance=dict(
                universe_hash=universe["hash"],
                price_window_hash=digest.hexdigest(),
                anchor_dates=sorted(d for d in anchors if d),
                window_start=start.isoformat(),
                window_end=day.isoformat(),
                coverage=coverage,
                etf_generated_at=etf_generated,
                trend_regimes=regimes,
                etf_strength="discovery_Trend40_RS40_frozen_stock_ETF_cross_section",
                benchmark=BENCHMARKS[market],
            ),
        )
