"""PostgreSQL-frame to Backtrader PandasData adapter and engine."""

from __future__ import annotations

import importlib.metadata

import backtrader as bt
import pandas as pd

from finance_analysis.backtest.market_rules import MarketRuleRegistry
from finance_analysis.backtest.metrics import BacktestMetricsCalculator, finalize_equity
from finance_analysis.backtest.strategies.sma_cross.backtrader_strategy import SmaCrossBacktraderStrategy
from finance_analysis.backtest.types import BacktestRequest, BacktestResult


class MarketCommissionInfo(bt.CommInfoBase):
    params = (
        ("commission", 0.0),
        ("stamp_tax", 0.0),
        ("transfer_fee", 0.0),
        ("min_commission", 0.0),
        ("percabs", True),
    )

    def _getcommission(self, size, price, pseudoexec):
        del pseudoexec
        gross = abs(size) * price
        commission = max(self.p.min_commission if gross else 0.0, gross * self.p.commission)
        tax = gross * self.p.stamp_tax if size < 0 else 0.0
        return commission + tax + gross * self.p.transfer_fee


class PostgreSQLPandasData(bt.feeds.PandasData):
    lines = ("limit_up", "limit_down", "suspended")
    params = (("limit_up", -1), ("limit_down", -1), ("suspended", -1))


def bars_to_pandas(request: BacktestRequest) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {
                "datetime": bar.trading_date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "openinterest": 0,
                "limit_up": bar.limit_up,
                "limit_down": bar.limit_down,
                "suspended": int(bar.suspended),
            }
            for bar in request.bars
        ]
    )
    return frame.set_index(pd.to_datetime(frame.pop("datetime")))


class BacktraderBacktestEngine:
    engine_key = "backtrader"

    def run(self, request: BacktestRequest) -> BacktestResult:
        if request.strategy_key != "sma_cross":
            raise ValueError(f"Backtrader does not support strategy {request.strategy_key}")
        rules = MarketRuleRegistry.get(request.market)
        cerebro = bt.Cerebro(stdstats=False, cheat_on_open=True)
        cerebro.broker.setcash(request.initial_cash)
        cerebro.broker.set_coo(True)
        cerebro.broker.addcommissioninfo(
            MarketCommissionInfo(
                commission=request.commission_rate,
                stamp_tax=request.stamp_tax_rate,
                transfer_fee=request.transfer_fee_rate,
                min_commission=5.0 if request.market == "CN" else 0.0,
            )
        )
        cerebro.adddata(PostgreSQLPandasData(dataname=bars_to_pandas(request)))
        cerebro.addstrategy(
            SmaCrossBacktraderStrategy,
            fast_window=request.parameters["fast_window"],
            slow_window=request.parameters["slow_window"],
            request_start=request.start_date,
            code=request.code,
            market_rules=rules,
            commission_rate=request.commission_rate,
            stamp_tax_rate=request.stamp_tax_rate,
            transfer_fee_rate=request.transfer_fee_rate,
        )
        strategies = cerebro.run(runonce=False)
        strategy = strategies[0]
        benchmark = {bar.trading_date: bar.close for bar in request.benchmark_bars}
        equity = finalize_equity(strategy.equity_out, request.initial_cash, benchmark)
        summary = BacktestMetricsCalculator.calculate(request.initial_cash, equity, strategy.trades_out)
        return BacktestResult(
            engine=self.engine_key,
            engine_version=importlib.metadata.version("backtrader"),
            strategy_key=request.strategy_key,
            market=request.market,
            code=request.code,
            start_date=request.start_date,
            end_date=request.end_date,
            trades=strategy.trades_out,
            equity_curve=equity,
            summary=summary,
            warnings=["当前行情未进行公司行动调整，拆股、分红或除权可能影响结果。"],
            engine_debug={"cheat_on_open": True, "data_adapter": "PandasData"},
        )


__all__ = ["BacktraderBacktestEngine", "bars_to_pandas"]
