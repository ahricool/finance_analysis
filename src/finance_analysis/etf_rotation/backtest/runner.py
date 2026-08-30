"""Run the fixed A-I ETF rotation suite for one market and write reports."""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

from finance_analysis.etf_rotation.backtest.analysis import build_analysis, write_analysis
from finance_analysis.etf_rotation.backtest.data import load_ohlcv_from_url
from finance_analysis.etf_rotation.backtest.diagnostics import entry1_return_split, entry_rank_forward_returns
from finance_analysis.etf_rotation.backtest.metrics import compute_metrics
from finance_analysis.etf_rotation.backtest.rankings import compute_entry_rankings
from finance_analysis.etf_rotation.backtest.reports import (
    DEFAULT_REPORT_DIR,
    comparison_row,
    write_comparison,
    write_entry1_split,
    write_rank_forward,
    write_strategy_files,
)
from finance_analysis.etf_rotation.backtest.simulator import simulate_strategy
from finance_analysis.etf_rotation.backtest.strategies import STRATEGIES
from finance_analysis.etf_rotation.backtest.types import OhlcvBar, StrategyResult
from finance_analysis.etf_rotation.config import DEFAULT_CONFIG
from finance_analysis.etf_rotation.universe import enabled_etfs, normalize_etf_market

WARMUP_CALENDAR_DAYS = 180


def subtract_months(value: date, months: int) -> date:
    if months < 0:
        raise ValueError("months must be >= 0")
    year = value.year
    month = value.month - months
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def latest_bar_date(bars_by_code: dict[str, list[OhlcvBar]]) -> date | None:
    dates = [bar.trade_date for bars in bars_by_code.values() for bar in bars]
    return max(dates) if dates else None


def _first_execution_date(ranking_dates: Sequence[date], calendar: Sequence[date]) -> date | None:
    if not ranking_dates or not calendar:
        return None
    first_signal = min(ranking_dates)
    for day in calendar:
        if day > first_signal:
            return day
    return None


def run_market(
    market: str,
    database_url: str,
    *,
    start: date | None = None,
    end: date | None = None,
    months: int | None = None,
    report_dir: Path = DEFAULT_REPORT_DIR,
    initial_equity: float = 1.0,
) -> list[StrategyResult]:
    market = normalize_etf_market(market)
    members = enabled_etfs(market)
    codes = sorted({member.code for member in members} | {DEFAULT_CONFIG.benchmark_codes[market]})
    probe_end = end or date.today()
    if start is not None:
        probe_start = start - timedelta(days=WARMUP_CALENDAR_DAYS)
    elif months:
        probe_start = subtract_months(probe_end, months) - timedelta(days=WARMUP_CALENDAR_DAYS)
    else:
        probe_start = date(2015, 1, 1)
    bars = load_ohlcv_from_url(database_url, codes, probe_start, probe_end, market=market)
    if not bars:
        raise RuntimeError(f"no daily bars loaded for market={market}")
    data_end = latest_bar_date(bars)
    assert data_end is not None
    window_end = min(end, data_end) if end else data_end
    rankings = compute_entry_rankings(bars, members)
    calendar = sorted({bar.trade_date for values in bars.values() for bar in values})
    if start is not None:
        window_start = start
    elif months:
        window_start = subtract_months(window_end, months)
    else:
        window_start = _first_execution_date(list(rankings), calendar) or min(calendar)
    if window_start > window_end:
        raise RuntimeError(f"empty window for market={market}: {window_start} > {window_end}")

    market_dir = report_dir / market
    results: list[StrategyResult] = []
    for spec in STRATEGIES:
        fills, equity, closed = simulate_strategy(
            spec, rankings, bars, window_start, window_end, initial_equity=initial_equity
        )
        metrics = compute_metrics(equity, closed, fills, initial_equity=initial_equity)
        result = StrategyResult(
            market=market,
            spec=spec,
            start=window_start,
            end=window_end,
            universe_size=len(members),
            fills=tuple(fills),
            equity=tuple(equity),
            closed_trades=tuple(closed),
            metrics=metrics,
        )
        write_strategy_files(result, report_dir)
        results.append(result)

    write_comparison(market_dir / "strategy_comparison.csv", results)
    forward = entry_rank_forward_returns(rankings, bars, window_start, window_end)
    split = entry1_return_split(rankings, bars, window_start, window_end)
    write_rank_forward(market_dir / "diagnostics_entry_rank_forward.csv", forward)
    write_entry1_split(market_dir / "diagnostics_entry1_split.csv", split)
    rows = [comparison_row(result) for result in results]
    write_analysis(market_dir / "analysis.md", build_analysis(market, rows, split))
    return results


__all__ = ["WARMUP_CALENDAR_DAYS", "latest_bar_date", "run_market", "subtract_months"]
