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


def validate_range(start_date, end_date):
    if start_date > end_date or (end_date - start_date).days > DEFAULT_CONFIG.event_study_max_days:
        raise ValueError("日期范围必须按顺序且不超过730天")


def aggregate_coverage(rows, strategy, missing_snapshot_dates=()):
    dates = defaultdict(lambda: [0, 0])
    for row in rows:
        dates[row["trade_date"]][0] += row["snapshot_count"]
        dates[row["trade_date"]][1] += row[strategy]
    total = sum(v[0] for v in dates.values())
    available = sum(v[1] for v in dates.values())
    incomplete = {d for d, (n, count) in dates.items() if n != count} | set(missing_snapshot_dates)
    last = max(incomplete, default=None)
    return {
        "feature_coverage": available / total if total else None,
        "feature_snapshot_count": available, "snapshot_count": total,
        "status": "complete" if total and not incomplete else "insufficient_feature_history",
        "continuous_complete_since": min((d for d, (n, count) in dates.items()
                                          if n == count and (last is None or d > last)), default=None),
        "incomplete_dates": sorted(incomplete),
    }


def evaluate_events(repo, market, events, now):
    from time import perf_counter

    started = perf_counter()
    plans = {day: following_sessions(market, day, 20) for day in {e["trade_date"] for e in events}}
    benchmark = DEFAULT_CONFIG.benchmark_codes[market]
    pairs = set()
    for event in events:
        day, code = event["trade_date"], event["code"]
        pairs.update(((code, day), (benchmark, day)))
        for index, (target, close) in enumerate(plans[day], 1):
            if close <= now:
                pairs.add((code, target))
                if index in HORIZONS:
                    pairs.add((benchmark, target))
    data = repo.event_study_required_bars(pairs) if pairs else []
    bars = {(r["code"], r["date"]): r for r in data}
    ohlc_seconds = perf_counter() - started
    started = perf_counter()
    evaluated = [evaluate_event(e, plans[e["trade_date"]], bars, benchmark, now) for e in events]
    return evaluated, len(data), ohlc_seconds, perf_counter() - started


def run_event_study_summary(repo, market, start_date, end_date, *, regime="ALL", now=None):
    import logging
    from time import perf_counter

    started = perf_counter()
    now = now or utc_now()
    validate_range(start_date, end_date)
    events, _ = repo.event_study_events(start_date, end_date, regime=regime)
    event_seconds = perf_counter() - started
    step = perf_counter()
    rows = repo.event_study_coverage(start_date, end_date)
    coverage_seconds = perf_counter() - step
    cal = exchange_calendar(market)
    expected = {d.date() for d in cal.sessions_in_range(start_date, end_date)
                if cal.session_close(d).to_pydatetime() <= now}
    dates = {r["trade_date"] for r in rows}
    missing = sorted(expected - dates)
    evaluated, row_count, ohlc_seconds, evaluation_seconds = evaluate_events(repo, market, events, now)
    step = perf_counter()
    groups = []
    for strategy in STRATEGIES:
        for layer in ("ALL", *REGIMES) if regime == "ALL" else (regime,):
            selected = [r for r in rows if layer == "ALL" or r["market_regime"] == layer]
            groups.append(aggregate(
                [e for e in evaluated if e["strategy"] == strategy and (layer == "ALL" or e["regime"] == layer)],
                strategy, layer, aggregate_coverage(selected, strategy, missing),
            ))
    evaluation_seconds += perf_counter() - step
    logging.getLogger(__name__).info(
        "event_study_summary market=%s start=%s end=%s regime=%s event_query_seconds=%.4f "
        "coverage_query_seconds=%.4f ohlc_query_seconds=%.4f evaluation_seconds=%.4f "
        "total_seconds=%.4f event_count=%s ohlc_row_count=%s",
        market, start_date, end_date, regime, event_seconds, coverage_seconds, ohlc_seconds,
        evaluation_seconds, perf_counter() - started, len(events), row_count,
    )
    return {
        "market": market, "start_date": start_date, "end_date": end_date, "method": "signal_close_v1",
        "benchmark": DEFAULT_CONFIG.benchmark_codes[market], "evaluated_at": now,
        "snapshot_dates": sorted(dates), "missing_snapshot_dates": missing,
        "box_feature_coverage": aggregate_coverage(rows, "BOX_BREAKOUT", missing),
        "mr_feature_coverage": aggregate_coverage(rows, "MEAN_REVERSION", missing),
        "groups": groups, "event_count": len(events),
    }


def run_event_study_events(repo, market, start_date, end_date, *, strategy, regime="ALL", offset=0, limit=100, now=None):
    import logging
    from time import perf_counter

    started = perf_counter()
    now = now or utc_now()
    validate_range(start_date, end_date)
    events, count = repo.event_study_events(start_date, end_date, strategy, regime, offset=offset, limit=limit)
    query_seconds = perf_counter() - started
    evaluated, row_count, ohlc_seconds, evaluation_seconds = evaluate_events(repo, market, events, now)
    logging.getLogger(__name__).info(
        "event_study_events market=%s start=%s end=%s regime=%s strategy=%s offset=%s limit=%s "
        "query_seconds=%.4f ohlc_seconds=%.4f evaluation_seconds=%.4f total_seconds=%.4f "
        "returned_count=%s ohlc_row_count=%s",
        market, start_date, end_date, regime, strategy, offset, limit, query_seconds, ohlc_seconds,
        evaluation_seconds, perf_counter() - started, len(evaluated), row_count,
    )
    return {"events": evaluated, "event_count": count, "offset": offset, "limit": limit}


def run_event_study(repo, market, start_date, end_date, *, strategy="ALL", regime="ALL", offset=0, limit=100, now=None):
    """Compatibility endpoint; new clients request summary and event pages separately."""
    summary = run_event_study_summary(repo, market, start_date, end_date, regime=regime, now=now)
    page = run_event_study_events(repo, market, start_date, end_date, strategy=strategy,
                                 regime=regime, offset=offset, limit=limit, now=now)
    if strategy != "ALL":
        summary["groups"] = [g for g in summary["groups"] if g["strategy"] == strategy]
    return {**summary, **page}
