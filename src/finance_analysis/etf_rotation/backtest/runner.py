"""Windowing, metrics, and orchestration for the A-share ETF rotation backtest."""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from finance_analysis.etf_rotation.backtest.rankings import compute_entry_rankings
from finance_analysis.etf_rotation.backtest.simulator import simulate_rotation
from finance_analysis.etf_rotation.backtest.types import OhlcvBar, RotationBacktestResult
from finance_analysis.etf_rotation.universe import ETFUniverseMember

WARMUP_CALENDAR_DAYS = 180
CALENDAR_DAYS_PER_YEAR = 365
TRADING_DAYS_PER_YEAR = 252


def subtract_months(value: date, months: int) -> date:
    if months < 0:
        raise ValueError("months must be >= 0")
    year = value.year
    month = value.month - months
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def annualized_return(
    initial_equity: float,
    final_equity: float,
    start: date,
    end: date,
    *,
    trading_days: int | None = None,
) -> tuple[float, float]:
    if initial_equity <= 0:
        raise ValueError("initial_equity must be positive")
    total = final_equity / initial_equity
    calendar_days = max((end - start).days, 1)
    calendar = total ** (CALENDAR_DAYS_PER_YEAR / calendar_days) - 1.0
    periods = trading_days if trading_days and trading_days > 0 else calendar_days
    trading = total ** (TRADING_DAYS_PER_YEAR / periods) - 1.0
    return calendar, trading


def run_rotation_backtest(
    bars_by_code: Mapping[str, Sequence[OhlcvBar]],
    members: Sequence[ETFUniverseMember],
    start: date,
    end: date,
    *,
    initial_equity: float = 1.0,
) -> RotationBacktestResult:
    if start > end:
        raise ValueError("start must be on or before end")
    rankings = compute_entry_rankings(bars_by_code, members)
    trades, equity, final_position = simulate_rotation(
        rankings, bars_by_code, start, end, initial_equity=initial_equity
    )
    final_equity = equity[-1].total_equity if equity else initial_equity
    first_mark = equity[0].trade_date if equity else start
    last_mark = equity[-1].trade_date if equity else end
    calendar_ann, trading_ann = annualized_return(
        initial_equity,
        final_equity,
        first_mark,
        last_mark,
        trading_days=max(len(equity) - 1, 1) if equity else 1,
    )
    return RotationBacktestResult(
        start=start,
        end=end,
        universe_size=len(members),
        ranking_days=len(rankings),
        execution_days=len(equity),
        initial_equity=initial_equity,
        final_equity=final_equity,
        total_return=final_equity / initial_equity - 1.0,
        annualized_return=calendar_ann,
        annualized_return_252=trading_ann,
        trade_count=len(trades),
        trades=tuple(trades),
        equity=tuple(equity),
        final_position=final_position,
    )


def result_to_dict(result: RotationBacktestResult) -> dict[str, Any]:
    return {
        "start": result.start.isoformat(),
        "end": result.end.isoformat(),
        "universe_size": result.universe_size,
        "ranking_days": result.ranking_days,
        "execution_days": result.execution_days,
        "initial_equity": result.initial_equity,
        "final_equity": result.final_equity,
        "total_return": result.total_return,
        "annualized_return": result.annualized_return,
        "annualized_return_252": result.annualized_return_252,
        "trade_count": result.trade_count,
        "final_position": result.final_position,
        "trades": [
            {
                "trade_date": item.trade_date.isoformat(),
                "side": item.side,
                "code": item.code,
                "price": item.price,
                "shares": item.shares,
                "cash_after": item.cash_after,
                "signal_date": item.signal_date.isoformat(),
                "entry_rank": item.entry_rank,
            }
            for item in result.trades
        ],
    }


def format_result(result: RotationBacktestResult) -> str:
    return "\n".join(
        [
            "A股 ETF 轮动回测（entry 排名，T+1 开盘，跌出前二换仓）",
            f"区间: {result.start.isoformat()} ~ {result.end.isoformat()}",
            f"Universe: {result.universe_size} 只 A 股行业/主题 ETF",
            f"排名交易日: {result.ranking_days}",
            f"执行交易日: {result.execution_days}",
            f"成交笔数: {result.trade_count}",
            f"期末持仓: {result.final_position or '空仓'}",
            f"累计收益率: {result.total_return:.2%}",
            f"年化收益率: {result.annualized_return:.2%}",
            f"年化收益率(252): {result.annualized_return_252:.2%}",
        ]
    )


def latest_bar_date(bars_by_code: Mapping[str, Sequence[OhlcvBar]]) -> date | None:
    dates = [bar.trade_date for bars in bars_by_code.values() for bar in bars]
    return max(dates) if dates else None


__all__ = [
    "WARMUP_CALENDAR_DAYS",
    "annualized_return",
    "format_result",
    "latest_bar_date",
    "result_to_dict",
    "run_rotation_backtest",
    "subtract_months",
]
