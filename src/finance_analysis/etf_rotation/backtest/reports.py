"""CSV report writers under ``etf_rotation/backtest/report``."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from finance_analysis.etf_rotation.backtest.types import StrategyResult

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_REPORT_DIR = PACKAGE_DIR / "report"

COMPARISON_FIELDS = (
    "market",
    "strategy_id",
    "strategy_name",
    "start",
    "end",
    "cagr",
    "sharpe",
    "max_drawdown",
    "win_rate",
    "avg_trade_return",
    "avg_holding_days",
    "trade_count",
    "trades_per_year",
    "turnover",
    "mae",
    "mfe",
    "cash_ratio",
    "total_return",
    "final_equity",
)


def _write_rows(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _format(row.get(key)) for key in fieldnames})


def _format(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.10g}"
    return value


def write_strategy_files(result: StrategyResult, report_dir: Path) -> Path:
    folder = report_dir / result.market / result.spec.strategy_id
    _write_rows(
        folder / "trades.csv",
        (
            "trade_date",
            "signal_date",
            "side",
            "code",
            "price",
            "shares",
            "notional",
            "reason",
            "entry_rank",
            "momentum_rank",
            "pnl_pct",
            "holding_days",
            "mae",
            "mfe",
        ),
        [
            {
                "trade_date": fill.trade_date.isoformat(),
                "signal_date": fill.signal_date.isoformat(),
                "side": fill.side,
                "code": fill.code,
                "price": fill.price,
                "shares": fill.shares,
                "notional": fill.notional,
                "reason": fill.reason,
                "entry_rank": fill.entry_rank,
                "momentum_rank": fill.momentum_rank,
                "pnl_pct": fill.pnl_pct,
                "holding_days": fill.holding_days,
                "mae": fill.mae,
                "mfe": fill.mfe,
            }
            for fill in result.fills
        ],
    )
    _write_rows(
        folder / "equity_curve.csv",
        (
            "trade_date",
            "equity",
            "cash",
            "cash_ratio",
            "n_positions",
            "daily_return",
            "drawdown",
            "turnover",
            "positions",
        ),
        [
            {
                "trade_date": point.trade_date.isoformat(),
                "equity": point.equity,
                "cash": point.cash,
                "cash_ratio": point.cash_ratio,
                "n_positions": point.n_positions,
                "daily_return": point.daily_return,
                "drawdown": point.drawdown,
                "turnover": point.turnover,
                "positions": point.positions,
            }
            for point in result.equity
        ],
    )
    return folder


def comparison_row(result: StrategyResult) -> dict[str, Any]:
    metrics = result.metrics
    return {
        "market": result.market,
        "strategy_id": result.spec.strategy_id,
        "strategy_name": result.spec.name,
        "start": result.start.isoformat(),
        "end": result.end.isoformat(),
        **{key: metrics.get(key) for key in COMPARISON_FIELDS if key not in {"market", "strategy_id", "strategy_name", "start", "end"}},
    }


def write_comparison(path: Path, results: Sequence[StrategyResult]) -> None:
    _write_rows(path, COMPARISON_FIELDS, [comparison_row(result) for result in results])


def write_rank_forward(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        return
    fields = list(rows[0].keys())
    _write_rows(path, fields, rows)


def write_entry1_split(path: Path, payload: Mapping[str, Mapping[str, Any]]) -> None:
    rows = [{"leg": leg, **stats} for leg, stats in payload.items()]
    _write_rows(path, ("leg", "n", "mean", "win_rate"), rows)


__all__ = [
    "COMPARISON_FIELDS",
    "DEFAULT_REPORT_DIR",
    "comparison_row",
    "write_comparison",
    "write_entry1_split",
    "write_rank_forward",
    "write_strategy_files",
]
