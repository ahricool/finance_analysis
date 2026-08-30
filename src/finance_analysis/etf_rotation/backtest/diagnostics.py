"""Forward-return diagnostics that are not used as trading signals."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from statistics import mean
from typing import Any

from finance_analysis.etf_rotation.backtest.simulator import index_bars  # pragma: allowlist secret
from finance_analysis.etf_rotation.backtest.types import Fill, OhlcvBar  # pragma: allowlist secret

RANK_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("rank_1", 1, 1),
    ("rank_2", 2, 2),
    ("rank_3", 3, 3),
    ("rank_4_5", 4, 5),
    ("rank_6_10", 6, 10),
)
HOLD_DAYS = (1, 3, 5, 10)


def _close_after(calendar: Sequence[date], start: date, hold_days: int) -> date | None:
    try:
        index = calendar.index(start)
    except ValueError:
        return None
    target = index + hold_days - 1
    if target >= len(calendar):
        return None
    return calendar[target]


def _return(entry_open: float, exit_close: float) -> float | None:
    if entry_open <= 0 or exit_close <= 0:
        return None
    return exit_close / entry_open - 1.0


def entry_rank_forward_returns(
    rankings: Mapping[date, Sequence[Mapping[str, Any]]],
    bars_by_code: Mapping[str, Sequence[OhlcvBar]],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    lookup = index_bars(bars_by_code)
    calendar = sorted({bar.trade_date for bars in bars_by_code.values() for bar in bars})
    samples: dict[tuple[str, int], list[float]] = defaultdict(list)
    for signal_date, rows in rankings.items():
        if signal_date < start or signal_date > end:
            continue
        try:
            exec_index = calendar.index(signal_date) + 1
        except ValueError:
            continue
        if exec_index >= len(calendar):
            continue
        exec_date = calendar[exec_index]
        for row in rows:
            rank = int(row["entry_rank"])
            bucket = next((name for name, lo, hi in RANK_BUCKETS if lo <= rank <= hi), None)
            if bucket is None:
                continue
            code = str(row["code"])
            open_bar = lookup.get(code, {}).get(exec_date)
            if open_bar is None or open_bar.open <= 0:
                continue
            for hold in HOLD_DAYS:
                exit_date = _close_after(calendar, exec_date, hold)
                if exit_date is None:
                    continue
                close_bar = lookup.get(code, {}).get(exit_date)
                if close_bar is None or close_bar.close <= 0:
                    continue
                value = _return(open_bar.open, close_bar.close)
                if value is not None:
                    samples[(bucket, hold)].append(value)
    report: list[dict[str, Any]] = []
    for bucket, _lo, _hi in RANK_BUCKETS:
        row: dict[str, Any] = {"bucket": bucket}
        for hold in HOLD_DAYS:
            values = samples.get((bucket, hold), [])
            row[f"n_{hold}d"] = len(values)
            row[f"mean_{hold}d"] = mean(values) if values else None
            row[f"win_rate_{hold}d"] = sum(item > 0 for item in values) / len(values) if values else None
        report.append(row)
    return report


def entry1_return_split(
    rankings: Mapping[date, Sequence[Mapping[str, Any]]],
    bars_by_code: Mapping[str, Sequence[OhlcvBar]],
    start: date,
    end: date,
) -> dict[str, Any]:
    lookup = index_bars(bars_by_code)
    calendar = sorted({bar.trade_date for bars in bars_by_code.values() for bar in bars})
    overnight: list[float] = []
    intraday: list[float] = []
    open_3d: list[float] = []
    open_5d: list[float] = []
    for signal_date, rows in rankings.items():
        if signal_date < start or signal_date > end:
            continue
        leader = next((row for row in rows if int(row["entry_rank"]) == 1), None)
        if leader is None:
            continue
        try:
            exec_index = calendar.index(signal_date) + 1
        except ValueError:
            continue
        if exec_index >= len(calendar):
            continue
        code = str(leader["code"])
        signal_bar = lookup.get(code, {}).get(signal_date)
        exec_bar = lookup.get(code, {}).get(calendar[exec_index])
        if signal_bar is None or exec_bar is None or signal_bar.close <= 0 or exec_bar.open <= 0:
            continue
        overnight.append(exec_bar.open / signal_bar.close - 1.0)
        if exec_bar.close > 0:
            intraday.append(exec_bar.close / exec_bar.open - 1.0)
        for hold, bucket in ((3, open_3d), (5, open_5d)):
            exit_date = _close_after(calendar, calendar[exec_index], hold)
            if exit_date is None:
                continue
            close_bar = lookup.get(code, {}).get(exit_date)
            if close_bar is None or close_bar.close <= 0:
                continue
            bucket.append(close_bar.close / exec_bar.open - 1.0)

    def _summary(values: list[float]) -> dict[str, float | int | None]:
        return {
            "n": len(values),
            "mean": mean(values) if values else None,
            "win_rate": sum(item > 0 for item in values) / len(values) if values else None,
        }

    return {
        "t_close_to_next_open": _summary(overnight),
        "t1_open_to_t1_close": _summary(intraday),
        "t1_open_to_3d_close": _summary(open_3d),
        "t1_open_to_5d_close": _summary(open_5d),
    }


def rotation_speed_diagnostics(
    rankings: Mapping[date, Sequence[Mapping[str, Any]]],
    fills: Sequence[Fill],
) -> dict[str, float | int | None]:
    """Measure leader capture and stale-hold delay from point-in-time signals."""
    ordered_dates = sorted(rankings)
    buys = {(fill.signal_date, fill.code) for fill in fills if fill.side == "buy"}
    leader_delays: list[int] = []
    missed_leader_episodes = 0
    active_leaders: set[str] = set()
    episode_starts: dict[str, int] = {}
    for index, trade_date in enumerate(ordered_dates):
        rows = rankings[trade_date]
        leaders = {str(row["code"]) for row in rows if int(row["rank"]) <= 4}
        for code in leaders - active_leaders:
            episode_starts[code] = index
        for code in leaders:
            if code in episode_starts and ((trade_date, code) in buys or any(
                str(row["code"]) == code and bool(row.get("is_candidate")) for row in rows
            )):
                leader_delays.append(index - episode_starts[code])
                episode_starts.pop(code, None)
        for code in active_leaders - leaders:
            if code in episode_starts:
                missed_leader_episodes += 1
                episode_starts.pop(code, None)
        active_leaders = leaders
    missed_leader_episodes += len(episode_starts)

    rank_by_date = {
        trade_date: {str(row["code"]): int(row["rank"]) for row in rows}
        for trade_date, rows in rankings.items()
    }
    stale_delays: list[int] = []
    for fill in fills:
        if fill.side != "sell":
            continue
        signal_index = ordered_dates.index(fill.signal_date) if fill.signal_date in rank_by_date else -1
        if signal_index < 0 or rank_by_date[fill.signal_date].get(fill.code, 0) <= 6:
            continue
        delay = 0
        for index in range(signal_index, -1, -1):
            rank = rank_by_date[ordered_dates[index]].get(fill.code)
            if rank is None or rank <= 6:
                break
            delay += 1
        stale_delays.append(delay)
    return {
        "leader_capture_delay": mean(leader_delays) if leader_delays else None,
        "leader_capture_samples": len(leader_delays),
        "missed_leader_episodes": missed_leader_episodes,
        "stale_hold_days": mean(stale_delays) if stale_delays else 0.0,
        "stale_hold_samples": len(stale_delays),
    }


__all__ = ["entry1_return_split", "entry_rank_forward_returns", "rotation_speed_diagnostics"]
