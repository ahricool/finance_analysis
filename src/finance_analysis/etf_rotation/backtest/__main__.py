"""CLI for the CN ETF rotation backtest.

Run against PostgreSQL daily bars (T+1 open, no fees):

    uv run python -m finance_analysis.etf_rotation.backtest --months 6
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta

from finance_analysis.config import load_env
from finance_analysis.etf_rotation.backtest.data import load_ohlcv_from_url
from finance_analysis.etf_rotation.backtest.runner import (
    WARMUP_CALENDAR_DAYS,
    format_result,
    latest_bar_date,
    result_to_dict,
    run_rotation_backtest,
    subtract_months,
)
from finance_analysis.etf_rotation.universe import enabled_etfs


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}; expected YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CN ETF rotation backtest using T+1 open fills")
    parser.add_argument("--months", type=int, default=6, help="Lookback window ending at the latest bar (default: 6)")
    parser.add_argument("--start", type=_parse_iso_date, help="Inclusive start date (overrides --months)")
    parser.add_argument("--end", type=_parse_iso_date, help="Inclusive end date (default: latest bar in DB)")
    parser.add_argument("--database-url", help="PostgreSQL URL; defaults to DATABASE_URL")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    return parser


def _database_url(explicit: str | None) -> str:
    url = (explicit or os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        raise SystemExit("DATABASE_URL is not set; pass --database-url or export DATABASE_URL")
    return url


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.months <= 0:
        raise SystemExit("--months must be positive")
    load_env()
    members = enabled_etfs("CN")
    codes = [member.code for member in members]
    probe_end = args.end or date.today()
    probe_start = (args.start or subtract_months(probe_end, args.months)) - timedelta(days=WARMUP_CALENDAR_DAYS)
    bars = load_ohlcv_from_url(_database_url(args.database_url), codes, probe_start, probe_end)
    if not bars:
        raise SystemExit("no daily bars loaded for the CN ETF universe")
    end = args.end or latest_bar_date(bars)
    if end is None:
        raise SystemExit("no daily bars loaded for the CN ETF universe")
    start = args.start or subtract_months(end, args.months)
    result = run_rotation_backtest(bars, members, start, end)
    if args.json:
        json.dump(result_to_dict(result), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
