"""Causal Entry episodes, separate from the legacy Alpha setup/candidate rules."""

from .config import DEFAULT_CONFIG
from .features import absolute_trend_passes, calculate_atr, weighted_log_regression

ENTRY_KINDS = ("breakout", "ma5", "ma10", "retest")
ENTRY_NUMERIC_FIELDS = tuple(f"entry_{kind}_score" for kind in ENTRY_KINDS) + (
    "entry_version",
    "entry_execution_ma5",
    "entry_execution_ma10",
    "entry_recent_trend_age",
)
ENTRY_STRING_FIELDS = tuple(f"entry_{kind}_{field}" for kind in ENTRY_KINDS for field in ("status", "reason"))


def _clv(bar):
    return (bar.close - bar.low) / (bar.high - bar.low) if bar.high > bar.low else None


def entry_context(bars, config=DEFAULT_CONFIG, *, sessions=None):
    """Use each session's prior MA/ATR and freeze resistance before a breakout.

    The prior 10-session qualification is the existing four absolute trend gates,
    not today's cross-sectional Alpha/percentile retroactively applied to history.
    """
    ordered = sorted(bars, key=lambda b: b.trade_date)
    result = {
        "recent_trend_date": None,
        "recent_trend_age": None,
        "history_ready": False,
        "long_structure_healthy": False,
        "ma5": None,
        "ma10": None,
        "pullbacks": {},
    }
    long, lookback = config.trend_period, config.entry_trend_lookback
    if len(ordered) < long + 2:
        return result
    closes = [b.close for b in ordered]
    last = len(ordered) - 1
    start = max(long + 1, last - lookback)
    required = long + lookback + 2
    expected = list(sessions or [])[-required:]
    if len(expected) >= lookback + 1:
        cutoff = expected[-lookback - 1]
        start = max(start, next((i for i, b in enumerate(ordered) if b.trade_date >= cutoff), last))
    observed_dates = {b.trade_date for b in ordered}
    trend_cache = {}

    def trend_at(i):
        if i in trend_cache:
            return trend_cache[i]
        if i < long:
            return False
        values = closes[: i + 1]
        short_ma = sum(values[-config.short_window :]) / config.short_window
        long_ma = sum(values[-long:]) / long
        slope, _ = weighted_log_regression(values, long)
        trend_cache[i] = absolute_trend_passes(
            (values[-1] > short_ma, short_ma > long_ma, values[-1] > values[-config.short_window - 1], slope > 0)
        )
        return trend_cache[i]

    qualified = [i for i in range(start, last) if trend_at(i)]
    ma_long = sum(closes[-long:]) / long
    prior_long = sum(closes[-long - 1 : -1]) / long
    result.update(
        history_ready=(
            len(ordered) >= required
            and (sessions is None or len(expected) == required and all(day in observed_dates for day in expected))
        ),
        long_structure_healthy=ma_long > prior_long and closes[-1] >= ma_long,
        recent_trend_date=ordered[qualified[-1]].trade_date.isoformat() if qualified else None,
        recent_trend_age=last - qualified[-1] if qualified else None,
        ma5=sum(closes[-6:-1]) / 5,
        ma10=sum(closes[-11:-1]) / 10,
        atr=calculate_atr(ordered[:-1], long),
    )
    if result["atr"] <= 0:
        return result

    def observe(window=None, breakout_index=None, level=None, breakout_window=None):
        touch = None
        advanced = None
        failed = False
        max_depth = None
        support = None
        atr = None
        first = start if breakout_index is None else breakout_index + 1
        for i in range(first, last + 1):
            bar = ordered[i]
            prior = ordered[:i]
            atr = calculate_atr(prior, long)
            if atr <= 0:
                continue
            support = level if level is not None else sum(closes[i - window : i]) / window
            # A frozen breakout level exists immediately after its confirmation;
            # an early failure cannot be erased by a later qualifying advance.
            if level is not None and bar.low < support - config.entry_support_failure_atr * atr:
                failed = True
            # An advance must already be observable before this day's low.
            approached = (
                closes[i - 1] >= support + config.entry_approach_atr * atr
                and closes[i - 1] - min(closes[max(0, i - lookback) : i]) >= config.entry_advance_atr * atr
                and trend_at(i - 1)
            )
            if touch is None and approached:
                advanced = i - 1
            if advanced is None:
                continue
            if bar.low < support - config.entry_support_failure_atr * atr:
                failed = True
            near = (
                bar.low <= support + config.entry_touch_atr * atr and bar.high >= support - config.entry_touch_atr * atr
            )
            declined = bar.low <= closes[advanced] - config.entry_pullback_decline_atr * atr
            if touch is None and near and declined:
                touch = i
            if touch is not None:
                depth = (support - bar.low) / atr
                max_depth = max(depth, max_depth) if max_depth is not None else depth
        if support is None or atr is None or atr <= 0:
            return {"status": "WAITING_PULLBACK", "reason": "历史数据不足，等待支撑与上涨过程预热"}
        distance = (closes[-1] - support) / atr
        recovered = bool(
            touch is not None
            and closes[-1] > support + config.entry_recovery_atr * atr
            and (closes[-1] > closes[-2] or closes[-1] > ordered[-1].open)
            and _clv(ordered[-1]) is not None
            and _clv(ordered[-1]) >= config.entry_clv_min
        )
        if not result["history_ready"]:
            status, reason = "WAITING_PULLBACK", "回踩窗口或历史指标预热不足，等待完整数据"
        elif not result["long_structure_healthy"] or failed:
            status, reason = "INVALIDATED", "长期均线结构转弱或回踩支撑已失效"
        elif not qualified:
            status, reason = "WAITING_PULLBACK", f"此前{lookback}个交易日未达到绝对趋势门槛"
        elif advanced is None:
            status, reason = "WAITING_PULLBACK", "缺少先前上涨过程，触碰支撑不足以确认"
        elif touch is None:
            status, reason = "WAITING_PULLBACK", "此前上涨已具备，等待回踩支撑"
        elif distance > config.entry_extended_atr:
            status, reason = "EXTENDED", "回踩后距支撑过远，已超出执行窗口"
        elif recovered:
            status, reason = "CONFIRMED", "先上涨、后回踩，当前已收回支撑并恢复"
        else:
            status, reason = "PULLING_BACK", "已触及支撑，等待收回与恢复确认"
        return {
            "status": status,
            "reason": reason,
            "support": support,
            "distance_atr": distance,
            "depth_atr": max_depth,
            "reclaim_atr": distance,
            "advanced_date": (ordered[advanced].trade_date.isoformat() if advanced is not None else None),
            "touch_date": ordered[touch].trade_date.isoformat() if touch is not None else None,
            "breakout_date": ordered[breakout_index].trade_date.isoformat() if breakout_index is not None else None,
            "breakout_level": level,
            "breakout_window": breakout_window,
            "recovered": recovered,
            "support_intact": not failed,
        }

    result["pullbacks"] = {"ma5": observe(window=5), "ma10": observe(window=10)}
    retests = []
    # All candidates exclude today and calculate the resistance from even earlier bars.
    for i in range(start, last):
        atr = calculate_atr(ordered[:i], long)
        clv = _clv(ordered[i])
        levels = set()
        for window in (long, config.short_window):
            level = max(b.high for b in ordered[i - window : i])
            if level in levels:
                continue
            levels.add(level)
            if (
                atr > 0
                and ordered[i].close >= level + config.entry_breakout_min_atr * atr
                and clv is not None
                and clv >= config.entry_clv_min
            ):
                retests.append(observe(breakout_index=i, level=level, breakout_window=window))
    priority = {"CONFIRMED": 0, "PULLING_BACK": 1, "EXTENDED": 2, "WAITING_PULLBACK": 3, "INVALIDATED": 4}
    result["pullbacks"]["retest"] = (
        min(retests, key=lambda r: priority[r["status"]])
        if retests
        else {
            "status": "WAITING_PULLBACK",
            "reason": f"此前{lookback}个交易日没有已确认的突破位，等待突破后回测",
        }
    )
    return result
