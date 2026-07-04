"""Backtest orchestration, preflight, submission, and worker execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import logging
import uuid
from typing import Any

import exchange_calendars as xcals

from finance_analysis.backtest.engines.registry import create_engine, get_engine_definition
from finance_analysis.backtest.market_rules import MarketRuleRegistry
from finance_analysis.backtest.strategies.registry import get_strategy
from finance_analysis.backtest.types import BacktestRequest, DailyBar
from finance_analysis.database.repositories.backtest import BacktestRepository
from finance_analysis.database.repositories.stock import MarketDataSymbolRepository, StockRepository

logger = logging.getLogger(__name__)

RAW_PRICE_WARNING = "当前行情未进行公司行动调整，拆股、分红或除权可能影响结果。"
CALENDAR_BY_MARKET = {"US": "XNYS", "CN": "XSHG", "HK": "XHKG"}


@dataclass
class BacktestPreflightResult:
    ready: bool
    engine: str
    engine_version: str | None
    strategy_key: str
    market: str
    code: str
    available_date_from: date | None
    available_date_to: date | None
    requested_trading_days: int
    available_trading_days: int
    coverage_ratio: float
    warmup_days: int
    warnings: list[str]
    errors: list[str]


class BacktestService:
    def __init__(
        self,
        backtests: BacktestRepository | None = None,
        symbols: MarketDataSymbolRepository | None = None,
        stocks: StockRepository | None = None,
    ):
        self.backtests = backtests or BacktestRepository()
        self.symbols = symbols or MarketDataSymbolRepository()
        self.stocks = stocks or StockRepository()

    @staticmethod
    def _expected_dates(market: str, start_date: date, end_date: date) -> list[date]:
        calendar = xcals.get_calendar(CALENDAR_BY_MARKET[market])
        return [item.date() for item in calendar.sessions_in_range(start_date, end_date)]

    def preflight(self, values: dict[str, Any]) -> BacktestPreflightResult:
        engine_key = str(values.get("engine") or "").lower()
        strategy_key = str(values.get("strategy_key") or "")
        market = str(values.get("market") or "").upper()
        code = str(values.get("code") or "").upper()
        start_date = values["start_date"]
        end_date = values["end_date"]
        errors: list[str] = []
        warnings = [RAW_PRICE_WARNING]
        definition = get_engine_definition(engine_key)
        strategy = get_strategy(strategy_key)
        parameters = strategy.validate_parameters(values.get("parameters"))
        if not definition.available:
            errors.append(definition.unavailable_reason or "回测引擎不可用")
        if strategy_key not in definition.supported_strategies or engine_key not in strategy.supported_engines:
            errors.append("当前引擎不支持该策略")
        if market not in definition.supported_markets or market not in strategy.supported_markets:
            errors.append("当前引擎和策略组合不支持该市场")
        if start_date > end_date:
            errors.append("开始日期不能晚于结束日期")
        symbol = self.symbols.get_by_code(code)
        if symbol is None or symbol.market != market or not symbol.enabled or not symbol.sync_daily:
            errors.append("标的不存在、市场不匹配或未启用日线数据")
        warmup_days = parameters["slow_window"] + 1
        coverage = {
            "available_date_from": None,
            "available_date_to": None,
            "available_trading_days": 0,
            "missing_open_days": 0,
        }
        expected_dates: list[date] = []
        bars = []
        if market in CALENDAR_BY_MARKET and start_date <= end_date:
            expected_dates = self._expected_dates(market, start_date, end_date)
        if symbol is not None:
            coverage = self.stocks.daily_coverage(symbol.id, start_date, end_date)
            bars = self.stocks.get_with_warmup(code, start_date, end_date, warmup_days)
        requested_days = len(expected_dates)
        actual_dates = {item.date for item in bars if start_date <= item.date <= end_date}
        available_days = len(actual_dates.intersection(expected_dates))
        ratio = available_days / requested_days if requested_days else 0.0
        if not available_days:
            errors.append("请求区间没有日线行情")
        elif ratio < 0.95:
            errors.append(f"日线覆盖率不足：{ratio:.2%}")
        elif ratio < 1:
            warnings.append(f"请求区间存在少量缺失交易日，覆盖率 {ratio:.2%}")
        if coverage["missing_open_days"]:
            errors.append(f"存在 {coverage['missing_open_days']} 个无有效开盘价的交易日")
        warmup_count = sum(item.date < start_date for item in bars)
        if warmup_count < warmup_days:
            errors.append(f"预热数据不足：需要 {warmup_days} 个交易日，实际 {warmup_count} 个")
        consecutive = longest = 0
        for trading_date in expected_dates:
            consecutive = 0 if trading_date in actual_dates else consecutive + 1
            longest = max(longest, consecutive)
        if longest >= 5:
            errors.append(f"存在连续 {longest} 个交易日的数据缺口")
        if market == "CN" and bars:
            requested_bars = [item for item in bars if start_date <= item.date <= end_date and not item.suspended]
            if any(item.limit_up is None or item.limit_down is None for item in requested_bars):
                errors.append("A 股日线缺少涨跌停价格，无法安全执行撮合")
        if market == "HK" and symbol is not None and not symbol.lot_size:
            errors.append("港股标的缺少每手股数 lot_size")
        benchmark = values.get("benchmark_code")
        if benchmark:
            benchmark_symbol = self.symbols.get_by_code(str(benchmark).upper())
            if benchmark_symbol is None or benchmark_symbol.market != market:
                errors.append("基准标的不存在或市场不匹配")
            elif not self.stocks.get_range(str(benchmark).upper(), start_date, end_date):
                errors.append("基准标的在请求区间没有日线行情")
        return BacktestPreflightResult(
            ready=not errors,
            engine=engine_key,
            engine_version=definition.version,
            strategy_key=strategy_key,
            market=market,
            code=code,
            available_date_from=coverage["available_date_from"],
            available_date_to=coverage["available_date_to"],
            requested_trading_days=requested_days,
            available_trading_days=available_days,
            coverage_ratio=round(ratio, 6),
            warmup_days=warmup_days,
            warnings=warnings,
            errors=errors,
        )

    def create_run(self, uid: int, values: dict[str, Any]):
        preflight = self.preflight(values)
        if not preflight.ready:
            raise ValueError("; ".join(preflight.errors))
        strategy = get_strategy(preflight.strategy_key)
        parameters = strategy.validate_parameters(values.get("parameters"))
        symbol = self.symbols.get_by_code(preflight.code)
        assert symbol is not None
        rules = MarketRuleRegistry.get(preflight.market)
        task_id = uuid.uuid4().hex
        rates = self._fee_rates(preflight.market)
        run = self.backtests.create_run(
            {
                "uid": uid,
                "task_id": task_id,
                "engine": preflight.engine,
                "engine_version": preflight.engine_version,
                "engine_config": {
                    **rates,
                    "frequency": "1d",
                    "signal_timing": "close",
                    "execution_timing": "next_open",
                    "target_position_pct": 100,
                },
                "strategy_key": strategy.key,
                "strategy_name": strategy.name,
                "strategy_version": strategy.version,
                "market": preflight.market,
                "symbol_id": symbol.id,
                "code": preflight.code,
                "start_date": values["start_date"],
                "end_date": values["end_date"],
                "initial_cash": float(values.get("initial_cash", 100000)),
                "benchmark_code": values.get("benchmark_code") or None,
                "parameters": parameters,
                "price_mode": "raw",
                "market_rule_version": rules.version,
                "status": "pending",
                "progress": 0,
                "summary": {},
                "warnings": preflight.warnings,
            }
        )
        try:
            from finance_analysis.tasks.celery.jobs.backtest.tasks import run_backtest
            from finance_analysis.tasks.celery.schedule import QUEUE_ANALYSIS

            run_backtest.apply_async(
                kwargs={"backtest_run_id": run.id, "owner_uid": uid},
                queue=QUEUE_ANALYSIS,
                task_id=task_id,
            )
        except Exception:
            self.backtests.fail_run(run.id, "回测任务提交失败")
            raise
        return run

    @staticmethod
    def _fee_rates(market: str) -> dict[str, float]:
        if market == "CN":
            return {"commission_rate": 0.0008, "stamp_tax_rate": 0.0005, "transfer_fee_rate": 0.00001}
        return {"commission_rate": 0.0008, "stamp_tax_rate": 0.0, "transfer_fee_rate": 0.0}

    @staticmethod
    def _daily_bar(row) -> DailyBar:
        return DailyBar(
            trading_date=row.date,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
            amount=float(row.amount) if row.amount is not None else None,
            limit_up=float(row.limit_up) if row.limit_up is not None else None,
            limit_down=float(row.limit_down) if row.limit_down is not None else None,
            suspended=bool(row.suspended),
        )

    def _request_for_run(self, run) -> BacktestRequest:
        warmup_days = int(run.parameters["slow_window"]) + 1
        bars = self.stocks.get_with_warmup(run.code, run.start_date, run.end_date, warmup_days)
        benchmark_bars = (
            self.stocks.get_range(run.benchmark_code, run.start_date, run.end_date)
            if run.benchmark_code
            else []
        )
        config = run.engine_config or {}
        return BacktestRequest(
            engine=run.engine,
            strategy_key=run.strategy_key,
            market=run.market,
            code=run.code,
            symbol_id=run.symbol_id,
            start_date=run.start_date,
            end_date=run.end_date,
            initial_cash=run.initial_cash,
            parameters=run.parameters,
            bars=tuple(self._daily_bar(item) for item in bars),
            benchmark_code=run.benchmark_code,
            benchmark_bars=tuple(self._daily_bar(item) for item in benchmark_bars),
            commission_rate=float(config.get("commission_rate", 0.0008)),
            stamp_tax_rate=float(config.get("stamp_tax_rate", 0.0)),
            transfer_fee_rate=float(config.get("transfer_fee_rate", 0.0)),
            price_mode=run.price_mode,
        )

    def execute_run(self, run_id: int) -> dict[str, Any]:
        run = self.backtests.claim_run(run_id)
        if run is None:
            raise RuntimeError(f"Backtest run {run_id} is not pending and cannot be executed twice")
        logger.info(
            "backtest start run_id=%s engine=%s strategy=%s market=%s code=%s dates=%s..%s",
            run.id, run.engine, run.strategy_key, run.market, run.code, run.start_date, run.end_date,
        )
        try:
            request = self._request_for_run(run)
            engine = create_engine(run.engine)
            self.backtests.update_progress(run.id, 30)
            result = engine.run(request)
            if result.engine != run.engine:
                raise RuntimeError(f"Engine identity mismatch: requested {run.engine}, got {result.engine}")
            self.backtests.update_progress(run.id, 85)
            self.backtests.complete_run(run.id, result)
            logger.info("backtest complete run_id=%s engine=%s trades=%s", run.id, run.engine, len(result.trades))
            return {
                "backtest_run_id": run.id,
                "engine": run.engine,
                "strategy_key": run.strategy_key,
                "status": "completed",
                "trade_count": len(result.trades),
                "total_return_pct": result.summary["total_return_pct"],
            }
        except Exception as exc:
            self.backtests.fail_run(run.id, f"{type(exc).__name__}: {exc}")
            logger.exception("backtest failed run_id=%s engine=%s", run.id, run.engine)
            raise


__all__ = ["BacktestPreflightResult", "BacktestService", "RAW_PRICE_WARNING"]
