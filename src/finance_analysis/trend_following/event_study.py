"""Official snapshot events and T-close research evaluations, never a portfolio backtest."""

from collections import defaultdict
from statistics import mean, median

from finance_analysis.core.time import utc_now
from finance_analysis.integrations.market_data.research import (
    exchange_calendar,
    following_sessions,
    valid_bar,
    valid_close,
)
from .config import DEFAULT_CONFIG

STRATEGIES = ("TREND_FOLLOWING", "BOX_BREAKOUT", "PULLBACK_RESUME", "MEAN_REVERSION")
REGIMES = ("RISK_ON", "NEUTRAL", "RISK_OFF")
HORIZONS = (5, 10, 20)
CONTEXT_FIELDS = (
    "alpha_score",
    "trend_score",
    "rs_score",
    "trend_lifecycle",
    "state",
    "ma20_slope",
    "fragility_score",
    "entry_type",
    "entry_score",
    "box_quality",
    "box_window_days",
    "box_width_pct",
    "box_breakout_distance_atr",
    "pullback_depth_atr",
    "reclaim_distance_atr",
    "rsi14",
    "distance_from_ma20_atr",
    "return_3d",
    "return_5d",
    "close_location_value",
    "mr_quality",
)
NUMERIC_CONTEXT = tuple(
    k
    for k in CONTEXT_FIELDS
    if k
    not in (
        "alpha_score",
        "trend_score",
        "rs_score",
        "trend_lifecycle",
        "state",
        "fragility_score",
        "entry_type",
    )
)


def feature_available(row, strategy):
    if strategy == "TREND_FOLLOWING":
        return row.get("previous_state") is not None
    if strategy == "BOX_BREAKOUT":
        return (
            row.get("box_state") is not None
            and row.get("box_breakout_fresh") is not None
            and row.get("box_episode_consumed") is not None
        )
    if strategy == "PULLBACK_RESUME":
        return row.get("trend_resume") is not None
    return row.get("mr_state") is not None


def derive_events(rows):
    events = []
    for row in rows:
        flags = {
            "TREND_FOLLOWING": row["state"] == "TRENDING" and row.get("previous_state") != "TRENDING",
            "BOX_BREAKOUT": row.get("box_state") == "BOX_BREAKOUT" and row.get("box_breakout_fresh") is True,
            "PULLBACK_RESUME": row.get("trend_resume") is True,
            "MEAN_REVERSION": row.get("mr_state") == "MR_REBOUND",
        }
        for strategy, flag in flags.items():
            if flag and feature_available(row, strategy):
                events.append(
                    {
                        "market": row["market"],
                        "trade_date": row["trade_date"],
                        "code": row["code"],
                        "name": row.get("name"),
                        "strategy": strategy,
                        "regime": row["market_regime"],
                        "signal_price": row["reference_price"],
                        "context": {key: row.get(key) for key in CONTEXT_FIELDS},
                    }
                )
    return events


def evaluate_event(event, plan, bars, benchmark, now):
    day, code = event["trade_date"], event["code"]
    base, benchmark_base = bars.get((code, day)), bars.get((benchmark, day))
    horizons = []
    for horizon in HORIZONS:
        target_day, close = plan[horizon - 1]
        stock_target, benchmark_target = bars.get((code, target_day)), bars.get((benchmark, target_day))
        state = (
            "pending" if close > now else "available" if valid_close(base) and valid_close(stock_target) else "missing"
        )
        benchmark_state = (
            "pending"
            if close > now
            else "available" if valid_close(benchmark_base) and valid_close(benchmark_target) else "missing"
        )
        value = stock_target["close"] / base["close"] - 1 if state == "available" else None
        benchmark_value = (
            benchmark_target["close"] / benchmark_base["close"] - 1 if benchmark_state == "available" else None
        )
        horizons.append(
            {
                "days": horizon,
                "target_date": target_day,
                "status": state,
                "value": value,
                "benchmark_status": benchmark_state,
                "benchmark_return": benchmark_value,
                "excess_status": (
                    "pending"
                    if close > now
                    else "available" if value is not None and benchmark_value is not None else "missing"
                ),
                "excess_return": value - benchmark_value if value is not None and benchmark_value is not None else None,
            }
        )
    closed = [d for d, close in plan if close <= now]
    missing = [d for d in closed if not valid_bar(bars.get((code, d)))]
    status = "pending" if len(closed) < 20 else "missing" if missing or not valid_close(base) else "available"
    # Only complete 20-session paths are aggregated. Never silently skip a suspension.
    path = [bars[(code, d)] for d in closed] if status == "available" else []
    return {
        **event,
        "evaluation_base_price": base["close"] if valid_close(base) else None,
        "horizons": horizons,
        "excursion_status": status,
        "observed_sessions": len(closed) - len(missing),
        "missing_dates": missing,
        "mfe20": max(r["high"] / base["close"] - 1 for r in path) if path else None,
        "mae20": min(r["low"] / base["close"] - 1 for r in path) if path else None,
    }


def stats(values):
    return {"mean": mean(values) if values else None, "median": median(values) if values else None}


def aggregate(events, strategy, regime, coverage):
    horizons = []
    for horizon in HORIZONS:
        points = [next(p for p in e["horizons"] if p["days"] == horizon) for e in events]
        values = [p["value"] for p in points if p["status"] == "available"]
        excess = [p["excess_return"] for p in points if p["excess_status"] == "available"]
        horizons.append(
            {
                "days": horizon,
                "matured_count": len(values),
                "excess_matured_count": len(excess),
                "pending_count": sum(p["status"] == "pending" for p in points),
                "missing_count": sum(p["status"] == "missing" for p in points),
                "mean_return": stats(values)["mean"],
                "median_return": stats(values)["median"],
                "win_rate": sum(v > 0 for v in values) / len(values) if values else None,
                "mean_excess_return": stats(excess)["mean"],
                "median_excess_return": stats(excess)["median"],
                "excess_win_rate": sum(v > 0 for v in excess) / len(excess) if excess else None,
            }
        )
    return {
        "strategy": strategy,
        "regime": regime,
        "event_count": len(events),
        **coverage,
        "horizons": horizons,
        "mfe20": stats([e["mfe20"] for e in events if e["mfe20"] is not None]),
        "mae20": stats([e["mae20"] for e in events if e["mae20"] is not None]),
        "excursion_count": sum(e["excursion_status"] == "available" for e in events),
    }


def feature_coverage(rows, strategy, missing_snapshot_dates=()):
    available = [r for r in rows if feature_available(r, strategy)]
    dates = defaultdict(list)
    for row in rows:
        dates[row["trade_date"]].append(feature_available(row, strategy))
    incomplete = {d for d, flags in dates.items() if not all(flags)} | set(missing_snapshot_dates)
    last_incomplete = max(incomplete, default=None)
    complete_suffix = sorted(
        d for d, flags in dates.items() if all(flags) and (last_incomplete is None or d > last_incomplete)
    )
    return {
        "feature_coverage": len(available) / len(rows) if rows else None,
        "feature_snapshot_count": len(available),
        "snapshot_count": len(rows),
        "status": "complete" if rows and not incomplete else "insufficient_feature_history",
        "continuous_complete_since": min(complete_suffix, default=None),
        "incomplete_dates": sorted(incomplete),
    }


def run_event_study(repo, market, start_date, end_date, *, strategy="ALL", regime="ALL", offset=0, limit=100, now=None):
    now = now or utc_now()
    if start_date > end_date or (end_date - start_date).days > DEFAULT_CONFIG.event_study_max_days:
        raise ValueError("日期范围必须按顺序且不超过730天")
    cal = exchange_calendar(market)
    expected_dates = {
        session.date()
        for session in cal.sessions_in_range(start_date, end_date)
        if cal.session_close(session).to_pydatetime() <= now
    }
    rows = repo.event_study_rows(start_date, end_date)
    missing_snapshot_dates = sorted(expected_dates - {r["trade_date"] for r in rows})
    events = derive_events(rows)
    if strategy != "ALL":
        events = [e for e in events if e["strategy"] == strategy]
    if regime != "ALL":
        events = [e for e in events if e["regime"] == regime]
    plans = {e["trade_date"]: None for e in events}
    for day in plans:
        plans[day] = following_sessions(market, day, 20)
    matured = [d for plan in plans.values() for d, close in plan if close <= now]
    benchmark = DEFAULT_CONFIG.benchmark_codes[market]
    # One bounded OHLC read includes every event symbol and the benchmark.
    data = (
        repo.event_study_bars(
            {e["code"] for e in events} | {benchmark},
            min(plans),
            max(matured + list(plans)),
        )
        if plans
        else []
    )
    bars = {(row["code"], row["date"]): row for row in data}
    evaluated = [evaluate_event(e, plans[e["trade_date"]], bars, benchmark, now) for e in events]
    groups = []
    for key in STRATEGIES if strategy == "ALL" else (strategy,):
        for layer in ("ALL", *REGIMES) if regime == "ALL" else (regime,):
            selected_rows = [r for r in rows if layer == "ALL" or r["market_regime"] == layer]
            selected_events = [
                e for e in evaluated if e["strategy"] == key and (layer == "ALL" or e["regime"] == layer)
            ]
            coverage = feature_coverage(selected_rows, key, missing_snapshot_dates)
            groups.append(aggregate(selected_events, key, layer, coverage))
    evaluated.sort(key=lambda e: (-e["trade_date"].toordinal(), e["code"], e["strategy"]))
    box_coverage = feature_coverage(rows, "BOX_BREAKOUT", missing_snapshot_dates)
    mr_coverage = feature_coverage(rows, "MEAN_REVERSION", missing_snapshot_dates)
    return {
        "market": market,
        "start_date": start_date,
        "end_date": end_date,
        "method": "signal_close_v1",
        "benchmark": benchmark,
        "evaluated_at": now,
        "snapshot_dates": sorted({r["trade_date"] for r in rows}),
        "box_feature_coverage": box_coverage,
        "mr_feature_coverage": mr_coverage,
        "missing_snapshot_dates": missing_snapshot_dates,
        "groups": groups,
        "event_count": len(evaluated),
        "events": evaluated[offset : offset + limit],
        "offset": offset,
        "limit": limit,
    }
