"""RQAlpha engine using a project-owned PostgreSQL DataSource mod."""

from __future__ import annotations

import importlib.metadata

import rqalpha

from finance_analysis.backtest.engines.rqalpha_data_source import (
    PostgreSQLRQAlphaDataSource,
    _ACTIVE_DATA_SOURCE,
)
from finance_analysis.backtest.market_rules import MarketRuleRegistry
from finance_analysis.backtest.metrics import BacktestMetricsCalculator, finalize_equity
from finance_analysis.backtest.strategies.sma_cross.rqalpha_strategy import (
    RQAlphaCollector,
    build_rqalpha_functions,
)
from finance_analysis.backtest.types import BacktestRequest, BacktestResult


class RQAlphaBacktestEngine:
    engine_key = "rqalpha"

    def run(self, request: BacktestRequest) -> BacktestResult:
        if request.market != "CN":
            raise ValueError("RQAlpha implementation currently supports CN only")
        if request.strategy_key != "sma_cross":
            raise ValueError(f"RQAlpha does not support strategy {request.strategy_key}")
        source = PostgreSQLRQAlphaDataSource(request)
        rules = MarketRuleRegistry.get(request.market)
        collector = RQAlphaCollector()
        funcs = build_rqalpha_functions(request, rules, collector)
        token = _ACTIVE_DATA_SOURCE.set(source)
        try:
            rqalpha.run_func(
                config={
                    "base": {
                        "start_date": request.bars[0].trading_date.isoformat(),
                        "end_date": request.end_date.isoformat(),
                        "frequency": "1d",
                        "accounts": {"stock": request.initial_cash},
                        "auto_update_bundle": False,
                        "capital_gain_tax_rate": 0,
                    },
                    "extra": {"log_level": "error"},
                    "mod": {
                        "finance_postgresql": {
                            "enabled": True,
                            "lib": "finance_analysis.backtest.engines.rqalpha_data_source",
                            "priority": 200,
                        },
                        "sys_progress": {"enabled": False},
                        "sys_analyser": {"enabled": False},
                        "sys_scheduler": {"enabled": False},
                        "sys_accounts": {"stock_t1": True},
                        "sys_simulation": {
                            "matching_type": "current_bar",
                            "price_limit": True,
                            "volume_limit": False,
                            "inactive_limit": True,
                            "slippage": 0,
                        },
                        "sys_transaction_cost": {
                            "stock_commission_multiplier": request.commission_rate / 0.0008,
                            "stock_min_commission": 5.0,
                            "tax_multiplier": request.stamp_tax_rate / 0.001,
                            "pit_tax": False,
                        },
                    },
                },
                **funcs,
            )
        finally:
            _ACTIVE_DATA_SOURCE.reset(token)
        benchmark = {bar.trading_date: bar.close for bar in request.benchmark_bars}
        equity = finalize_equity(collector.equity, request.initial_cash, benchmark)
        summary = BacktestMetricsCalculator.calculate(request.initial_cash, equity, collector.trades)
        return BacktestResult(
            engine=self.engine_key,
            engine_version=importlib.metadata.version("rqalpha"),
            strategy_key=request.strategy_key,
            market=request.market,
            code=request.code,
            start_date=request.start_date,
            end_date=request.end_date,
            trades=collector.trades,
            equity_curve=equity,
            summary=summary,
            warnings=["当前行情未进行公司行动调整，拆股、分红或除权可能影响结果。"],
            engine_debug={
                "data_source": "PostgreSQLRQAlphaDataSource",
                "bundle_download": False,
                "execution": "open_auction",
            },
        )


__all__ = ["RQAlphaBacktestEngine"]
