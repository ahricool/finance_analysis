"""One metrics implementation shared by all engine outputs."""

from __future__ import annotations

import math
from statistics import mean, pstdev

from finance_analysis.backtest.types import BacktestEquityResult, BacktestTradeResult


class BacktestMetricsCalculator:
    @staticmethod
    def calculate(
        initial_cash: float,
        equity: list[BacktestEquityResult],
        trades: list[BacktestTradeResult],
    ) -> dict[str, float | int | None]:
        final_equity = equity[-1].total_equity if equity else initial_cash
        total_return = (final_equity / initial_cash - 1) * 100 if initial_cash else 0.0
        days = max(1, (equity[-1].trading_date - equity[0].trading_date).days) if len(equity) > 1 else 1
        annualized = ((final_equity / initial_cash) ** (365 / days) - 1) * 100 if initial_cash > 0 else 0.0
        daily = [point.daily_return_pct / 100 for point in equity[1:]]
        volatility = pstdev(daily) * math.sqrt(252) * 100 if len(daily) > 1 else 0.0
        sharpe = mean(daily) / pstdev(daily) * math.sqrt(252) if len(daily) > 1 and pstdev(daily) else None
        benchmark_return = (
            equity[-1].benchmark_return_pct if equity and equity[-1].benchmark_return_pct is not None else 0.0
        )
        exits = [item for item in trades if item.side == "sell" and item.return_pct is not None]
        wins = [item for item in exits if (item.pnl or 0) > 0]
        gains = sum(max(0.0, item.pnl or 0.0) for item in exits)
        losses = abs(sum(min(0.0, item.pnl or 0.0) for item in exits))
        buy_dates = [item.trade_date for item in trades if item.side == "buy"]
        sell_dates = [item.trade_date for item in trades if item.side == "sell"]
        holding_days = sum(max(0, (sell - buy).days) for buy, sell in zip(buy_dates, sell_dates))
        return {
            "initial_cash": round(initial_cash, 4),
            "final_equity": round(final_equity, 4),
            "total_return_pct": round(total_return, 6),
            "annualized_return_pct": round(annualized, 6),
            "benchmark_return_pct": round(benchmark_return or 0.0, 6),
            "excess_return_pct": round(total_return - (benchmark_return or 0.0), 6),
            "max_drawdown_pct": round(min((point.drawdown_pct for point in equity), default=0.0), 6),
            "sharpe_ratio": round(sharpe, 6) if sharpe is not None else None,
            "volatility_pct": round(volatility, 6),
            "trade_count": len(trades),
            "buy_count": sum(item.side == "buy" for item in trades),
            "sell_count": sum(item.side == "sell" for item in trades),
            "win_rate_pct": round(len(wins) / len(exits) * 100, 6) if exits else 0.0,
            "profit_factor": round(gains / losses, 6) if losses else None,
            "average_trade_return_pct": round(mean(item.return_pct for item in exits), 6) if exits else 0.0,
            "holding_days": holding_days,
        }


def finalize_equity(
    points: list[BacktestEquityResult], initial_cash: float, benchmark_closes: dict | None = None
) -> list[BacktestEquityResult]:
    peak = initial_cash
    previous = initial_cash
    benchmark_closes = benchmark_closes or {}
    benchmark_base = next(iter(benchmark_closes.values()), None)
    for point in points:
        peak = max(peak, point.total_equity)
        point.daily_return_pct = (point.total_equity / previous - 1) * 100 if previous else 0.0
        point.cumulative_return_pct = (point.total_equity / initial_cash - 1) * 100 if initial_cash else 0.0
        point.drawdown_pct = (point.total_equity / peak - 1) * 100 if peak else 0.0
        if benchmark_base and point.trading_date in benchmark_closes:
            point.benchmark_return_pct = (benchmark_closes[point.trading_date] / benchmark_base - 1) * 100
            point.benchmark_equity = initial_cash * (1 + point.benchmark_return_pct / 100)
        previous = point.total_equity
    return points
