"""Pure, explainable calculations on closed regular-session bars."""

from datetime import datetime, timedelta
from math import isfinite
from . import config as c


def ratio(value, base):
    return value / base - 1 if value is not None and base is not None and base > 0 else None


def closed_bars(bars, session, until):
    slots = set(session.slots(until, c.BAR_MINUTES))
    valid = {}
    for bar in bars:
        if (
            bar.bar_start in slots
            and bar.bar_end == bar.bar_start + timedelta(minutes=c.BAR_MINUTES)
            and bar.bar_end <= until
            and bar.trade_date == session.day
            and all(isfinite(v) and v > 0 for v in (bar.open, bar.high, bar.low, bar.close))
            and bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
        ):
            valid[bar.bar_start] = bar
    return [valid[t] for t in sorted(valid)]


def metrics(quote, bars, benchmark, history, session, now):
    m = {
        "relative_to_industry": None,
        "relative_to_etf": None,
        "industry_unavailable_reason": "无可靠行业盘中收益及对应映射",
        "etf_unavailable_reason": "无可靠股票到 ETF 映射",
        "benchmark_code": c.BENCHMARKS[session.market],
    }
    usable_quote = (
        quote is not None
        and quote.quote_time is not None
        and quote.quote_time.tzinfo is not None
        and session.opened <= quote.quote_time <= min(now, session.closed)
    )
    m.update(
        quote_time=quote.quote_time if quote else None,
        provider=quote.provider if quote else None,
        data_age_seconds=(now - quote.quote_time).total_seconds() if usable_quote else None,
        quote_usable=usable_quote,
    )
    stamp = quote.quote_time if usable_quote else session.opened
    bars = closed_bars(bars, session, stamp)
    m["bar_time"] = bars[-1].bar_end if bars else None
    fresh = usable_quote and (now - stamp).total_seconds() <= c.MAX_DATA_AGE_SECONDS
    m["data_fresh"] = (
        fresh and bool(bars) and (stamp - bars[-1].bar_end).total_seconds() <= c.MAX_COMPARISON_SKEW_SECONDS
    )
    price = quote.price if usable_quote else None
    opened = quote.open_price if usable_quote else None
    m.update(price=price, open=opened, previous_close=quote.pre_close if usable_quote else None)
    m["gap_pct"] = ratio(opened, m["previous_close"])
    gap = m["gap_pct"]
    m["gap_status"] = (
        "unavailable"
        if gap is None
        else (
            "低开"
            if gap < -c.GAP_FLAT
            else (
                "平开"
                if gap < c.GAP_FLAT
                else "轻微高开" if gap < c.GAP_OBVIOUS else "明显高开" if gap < c.GAP_EXCESSIVE else "过度高开"
            )
        )
    )
    m["intraday_return"] = ratio(price, opened)
    m["return_from_previous_close"] = ratio(price, m["previous_close"])
    for window in c.WINDOWS:
        end = session.opened + timedelta(minutes=window)
        window_bars = [b for b in bars if b.bar_end <= end]
        complete = stamp >= end and [b.bar_start for b in window_bars] == session.slots(end, c.BAR_MINUTES)
        m[f"return_{window}m"] = ratio(window_bars[-1].close, opened) if complete and window_bars else None
        m[f"high_{window}m"] = max(b.high for b in window_bars) if complete and window_bars else None
        m[f"low_{window}m"] = min(b.low for b in window_bars) if complete and window_bars else None
    high, low = m[f"high_{c.OPENING_MINUTES}m"], m[f"low_{c.OPENING_MINUTES}m"]
    m.update(opening_range_high=high, opening_range_low=low)
    tail = bars[-c.BREAK_BARS :]
    consecutive = (
        len(tail) == c.BREAK_BARS
        and all(b.bar_start >= session.opened + timedelta(minutes=c.OPENING_MINUTES) for b in tail)
        and all(a.bar_end == b.bar_start for a, b in zip(tail, tail[1:]))
    )
    m["break_above_opening_range"] = (
        all(b.close > high * (1 + c.BREAK_BUFFER) for b in tail) if consecutive and high is not None else None
    )
    m["break_below_opening_range"] = (
        all(b.close < low * (1 - c.BREAK_BUFFER) for b in tail) if consecutive and low is not None else None
    )
    complete = bool(bars) and [b.bar_start for b in bars] == session.slots(bars[-1].bar_end, c.BAR_MINUTES)
    reliable_volume = complete and all(b.volume is not None and isfinite(b.volume) and b.volume >= 0 for b in bars)
    total = sum(b.volume for b in bars) if reliable_volume else None
    vwap = sum((b.high + b.low + b.close) / 3 * b.volume for b in bars) / total if total else None
    m.update(
        vwap=vwap,
        vwap_distance_pct=ratio(price, vwap),
        price_vs_vwap=ratio(price, vwap),
        above_vwap=price > vwap if price is not None and vwap is not None else None,
        vwap_method="provisional_typical_price_closed_5m" if vwap is not None else "unavailable",
        vwap_unavailable_reason=None if vwap is not None else "闭合分钟线缺失、不连续或成交量不足",
    )
    prior = [b.volume for b in history[-c.VOLUME_DAYS :]]
    avg = (
        sum(prior) / len(prior)
        if len(prior) == c.VOLUME_DAYS and all(v is not None and v >= 0 for v in prior)
        else None
    )
    fraction = session.elapsed(bars[-1].bar_end) / session.elapsed(session.closed) if bars else 0
    vr = total / (avg * fraction) if total is not None and avg and fraction else None
    m.update(
        volume_ratio=vr,
        volume_status=(
            "unavailable"
            if vr is None
            else "LOW" if vr < c.VOLUME_LOW else "EXPANDING" if vr >= c.VOLUME_EXPANDING else "NORMAL"
        ),
        volume_method="daily_average_elapsed_fraction_approximation" if vr is not None else "unavailable",
        volume_as_of=bars[-1].bar_end if reliable_volume else None,
    )
    benchmark_ok = (
        usable_quote
        and benchmark is not None
        and benchmark.quote_time is not None
        and benchmark.quote_time.tzinfo is not None
        and session.opened <= benchmark.quote_time <= now
        and abs((stamp - benchmark.quote_time).total_seconds()) <= c.MAX_COMPARISON_SKEW_SECONDS
    )
    br = ratio(benchmark.price, benchmark.open_price) if benchmark_ok else None
    m.update(
        benchmark_quote_time=benchmark.quote_time if benchmark else None,
        benchmark_return=br,
        relative_to_market=m["intraday_return"] - br if br is not None and m["intraday_return"] is not None else None,
    )
    return m


def decision(m, trend):
    reasons = []

    def reason(code, text):
        reasons.append({"code": code, "text": text})

    above = m["break_above_opening_range"]
    below = m["break_below_opening_range"]
    vwap = m["vwap_distance_pct"]
    rs = m["relative_to_market"]
    volume = m["volume_ratio"]
    healthy_window = m["return_15m"] is not None and m["return_15m"] >= 0
    weak_window = any(m[f"return_{w}m"] is not None and m[f"return_{w}m"] <= c.WINDOW_WEAK for w in (15, 30))
    fade = (
        m["gap_pct"] is not None
        and m["gap_pct"] >= c.GAP_OBVIOUS
        and m["intraday_return"] is not None
        and m["intraday_return"] <= c.GAP_FADE
    )
    weak_vwap = vwap is not None and vwap <= c.VWAP_WEAK
    weak_rs = rs is not None and rs <= c.RS_WEAK
    intact = trend.get("impact") in {"intact", "improving"}
    broken = trend.get("impact") == "broken"
    fail = bool(
        (below and (weak_vwap or weak_rs or weak_window or fade or broken)) or (broken and weak_vwap and weak_rs)
    )
    confirm = bool(
        above
        and vwap is not None
        and vwap > 0
        and healthy_window
        and not fade
        and rs is not None
        and rs >= c.RS_CONFIRM
        and volume is not None
        and volume >= c.VOLUME_EXPANDING
        and intact
    )
    chase = sum(
        value is not None and value >= threshold
        for value, threshold in (
            (m["gap_pct"], c.GAP_EXCESSIVE),
            (m["return_from_previous_close"], c.CHASE_RETURN),
            (vwap, c.CHASE_VWAP),
            (m["return_30m"], c.CHASE_30M),
        )
    )
    risk = "HIGH" if chase else "MEDIUM" if m["gap_pct"] is not None and m["gap_pct"] >= c.GAP_OBVIOUS else "LOW"
    if above:
        reason("opening_breakout", f"连续{c.BREAK_BARS}根闭合5分钟线突破开盘区间高点（buffer {c.BREAK_BUFFER:.1%}）")
    if below:
        reason("opening_breakdown", f"连续{c.BREAK_BARS}根闭合5分钟线跌破开盘区间低点")
    if vwap is not None:
        reason("vwap", f"价格相对 provisional VWAP {vwap:+.2%}")
    if rs is not None:
        reason("relative_market", f"开盘以来相对 {m['benchmark_code']} {rs:+.2%}")
    if volume is not None:
        reason("volume", f"量能 {volume:.2f}x（日均量按交易时间线性近似）")
    if m["return_15m"] is not None:
        reason("opening_15m", f"完整开盘15分钟收益 {m['return_15m']:+.2%}")
    if fade:
        reason("gap_fade", f"高开 {m['gap_pct']:+.2%} 后自开盘回落 {m['intraday_return']:+.2%}")
    reason("trend", f"Temporary Trend: {trend.get('impact', 'unavailable')}")
    if chase:
        reason("chase_risk", "价格过度扩张，确认不代表适合追入")
    if not m["data_fresh"]:
        reason("data_unavailable", "行情过期或闭合分钟线不足，不推进确认状态")
    if not confirm and not fail:
        reason("waiting", "等待价格结构、相对强度、量能及趋势共同确认；缺失数据不视为负向")
    components = {
        "price": (
            (0.5 if above is None else float(above))
            + (0.5 if vwap is None else float(vwap > 0))
            + (0.5 if m["return_15m"] is None else float(healthy_window))
        )
        / 3,
        "relative_strength": 0.5 if rs is None else float(rs >= c.RS_CONFIRM),
        "volume": 0.5 if volume is None else min(1, volume / c.VOLUME_EXPANDING),
        "trend": 0.5 if trend.get("impact") == "unavailable" else float(intact),
    }
    scores = {f"{key}_score": round(value * c.SCORE_WEIGHTS[key], 2) for key, value in components.items()}
    scores["risk_penalty"] = c.RISK_PENALTY[risk]
    score = max(0, min(100, sum(v for k, v in scores.items() if k != "risk_penalty") - scores["risk_penalty"]))
    raw = "FAILED" if fail else "CONFIRMED" if confirm else "WAIT"
    return dict(
        proposed_state=raw if m["data_fresh"] else "WAIT",
        reasons=reasons,
        confirmation_score=round(score, 2),
        score_breakdown=scores,
        chase_risk=risk,
    )


def stabilize(current, previous, observation, now):
    """Only distinct newer closed bars count. CONFIRMED is latched until structural failure."""
    old = previous or {}
    state = old.get("state", "WAIT")
    proposed = current["proposed_state"]
    stamp = observation.isoformat() if observation else None
    pending, count = old.get("pending_state"), old.get("pending_count", 0)
    before = datetime.fromisoformat(old["last_observation"]) if old.get("last_observation") else None
    since = old.get("pending_since")
    if state == "FAILED":
        current["current_price_recovered"] = proposed == "CONFIRMED"
    elif observation is not None and (before is None or observation > before):
        continuous = before is not None and (observation - before).total_seconds() <= c.MAX_OBSERVATION_GAP_SECONDS
        if proposed in {"CONFIRMED", "FAILED"} and proposed != state:
            if pending == proposed and continuous:
                count += 1
            else:
                pending, count, since = proposed, 1, stamp
            if (
                count >= c.STABLE_EVALUATIONS
                and (observation - datetime.fromisoformat(since)).total_seconds() >= c.STABLE_SECONDS
            ):
                state = proposed
                pending, count, since = None, 0, None
        else:
            pending, count, since = None, 0, None
    elif proposed == "WAIT":
        pending, count, since = None, 0, None
    changed = state != old.get("state", "WAIT")
    current.update(
        state=state,
        pending_state=pending,
        pending_count=count,
        pending_since=since,
        last_observation=max(filter(None, (stamp, old.get("last_observation"))), default=None),
        first_confirmed_at=old.get("first_confirmed_at") or (now.isoformat() if state == "CONFIRMED" else None),
        failed_at=old.get("failed_at") or (now.isoformat() if state == "FAILED" else None),
        max_confirmation_score=max(old.get("max_confirmation_score", 0), current["confirmation_score"]),
        state_reasons=current["reasons"][:] if changed else old.get("state_reasons", []),
        current_price_recovered=current.get("current_price_recovered", False),
    )
    if state != proposed:
        current["reasons"].append(
            {
                "code": "state_stability",
                "text": (
                    "FAILED 当日锁定；CONFIRMED 仅在稳定结构性失败后改变"
                    if state != "WAIT"
                    else f"等待连续 {c.STABLE_EVALUATIONS} 次新闭合线评估确认"
                ),
            }
        )
    return current
