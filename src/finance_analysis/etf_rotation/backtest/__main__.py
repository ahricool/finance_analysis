"""CLI for the fixed A-I ETF momentum rotation research backtest.

Signals are T-close rankings; fills are T+1 open.  No fees, no slippage.

    ENV_FILE=~/svr/finance_analysis/.env \\
      uv run python -m finance_analysis.etf_rotation.backtest --market CN US
"""

from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from finance_analysis.config import load_env
from finance_analysis.etf_rotation.backtest.reports import (
    DEFAULT_REPORT_DIR,
    comparison_row,
    write_comparison,
)
from finance_analysis.etf_rotation.backtest.runner import run_market
from finance_analysis.etf_rotation.universe import normalize_etf_market


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}; expected YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ETF rotation research backtest (fixed strategies A-I)")
    parser.add_argument("--market", nargs="+", default=["CN", "US"], help="Markets to run (default: CN US)")
    parser.add_argument("--months", type=int, help="Lookback months ending at the latest bar; omit for full sample")
    parser.add_argument("--start", type=_parse_iso_date, help="Inclusive start date")
    parser.add_argument("--end", type=_parse_iso_date, help="Inclusive end date")
    parser.add_argument("--database-url", help="PostgreSQL URL; defaults to DATABASE_URL")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR, help="CSV/MD output directory")
    return parser


def _database_url(explicit: str | None) -> str:
    url = (explicit or os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        raise SystemExit("DATABASE_URL is not set; pass --database-url or export DATABASE_URL")
    return url


def _print_table(market: str, rows: list[dict]) -> None:
    print(f"\n== {market} ==")
    header = f"{'id':<18} {'CAGR':>8} {'Sharpe':>8} {'MaxDD':>8} {'Win%':>8} {'HoldD':>7} {'Trades':>7} {'TO':>8} {'Cash':>8}"
    print(header)
    for row in rows:
        sharpe = row.get("sharpe")
        print(
            f"{row['strategy_id']:<18} "
            f"{_fmt_pct(row.get('cagr')):>8} "
            f"{_fmt_num(sharpe):>8} "
            f"{_fmt_pct(row.get('max_drawdown')):>8} "
            f"{_fmt_pct(row.get('win_rate')):>8} "
            f"{_fmt_num(row.get('avg_holding_days')):>7} "
            f"{int(row.get('trade_count') or 0):>7} "
            f"{_fmt_pct(row.get('turnover')):>8} "
            f"{_fmt_pct(row.get('cash_ratio')):>8}"
        )


def _fmt_pct(value) -> str:
    return "" if value in (None, "") else f"{float(value):.1%}"


def _fmt_num(value) -> str:
    return "" if value in (None, "") else f"{float(value):.2f}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.months is not None and args.months <= 0:
        raise SystemExit("--months must be positive")
    load_env()
    database_url = _database_url(args.database_url)
    all_results = []
    for raw_market in args.market:
        market = normalize_etf_market(raw_market)
        results = run_market(
            market,
            database_url,
            start=args.start,
            end=args.end,
            months=args.months,
            report_dir=args.report_dir,
        )
        all_results.extend(results)
        rows = [comparison_row(result) for result in results]
        _print_table(market, rows)
        analysis_path = args.report_dir / market / "analysis.md"
        if analysis_path.exists():
            print(analysis_path.read_text(encoding="utf-8"))
    if all_results:
        write_comparison(args.report_dir / "strategy_comparison.csv", all_results)
    print(f"Reports written to {args.report_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
