"""Performance statistics for one ETF rotation strategy."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date
from statistics import mean, pstdev

from finance_analysis.etf_rotation.backtest.types import ClosedTrade, EquityPoint, Fill
from finance_analysis.etf_rotation.risk import TRADING_DAYS_PER_YEAR

CALENDAR_DAYS_PER_YEAR = 365


def compute_metrics(
    equity: Sequence[EquityPoint],
    closed_trades: Sequence[ClosedTrade],
    fills: Sequence[Fill],
    *,
    initial_equity: float = 1.0,
) -> dict[str, float | int | None]:
    final_equity = equity[-1].equity if equity else initial_equity
    start = equity[0].trade_date if equity else date.min
    end = equity[-1].trade_date if equity else date.min
    calendar_days = max((end - start).days, 1) if equity else 1
    total_return = final_equity / initial_equity - 1.0 if initial_equity else 0.0
    cagr = (final_equity / initial_equity) ** (CALENDAR_DAYS_PER_YEAR / calendar_days) - 1.0 if initial_equity else 0.0
    daily = [point.daily_return for point in equity[1:]]
    vol = pstdev(daily) if len(daily) > 1 else 0.0
    sharpe = mean(daily) / vol * math.sqrt(TRADING_DAYS_PER_YEAR) if vol else None
    max_dd = min((point.drawdown for point in equity), default=0.0)
    wins = [trade for trade in closed_trades if trade.return_pct > 0]
    buy_count = sum(1 for fill in fills if fill.side == "buy")
    years = calendar_days / CALENDAR_DAYS_PER_YEAR
    return {
        "start": start.isoformat() if equity else None,
        "end": end.isoformat() if equity else None,
        "cagr": cagr,
        "total_return": total_return,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "win_rate": len(wins) / len(closed_trades) if closed_trades else 0.0,
        "avg_trade_return": mean(trade.return_pct for trade in closed_trades) if closed_trades else 0.0,
        "avg_holding_days": mean(trade.holding_days for trade in closed_trades) if closed_trades else 0.0,
        "trade_count": len(closed_trades),
        "buy_count": buy_count,
        "trades_per_year": (len(closed_trades) / years) if years else 0.0,
        "turnover": mean(point.turnover for point in equity) if equity else 0.0,
        "mae": mean(trade.mae for trade in closed_trades) if closed_trades else 0.0,
        "mfe": mean(trade.mfe for trade in closed_trades) if closed_trades else 0.0,
        "cash_ratio": mean(point.cash_ratio for point in equity) if equity else 1.0,
        "final_equity": final_equity,
        "execution_days": len(equity),
    }


__all__ = ["CALENDAR_DAYS_PER_YEAR", "compute_metrics"]
