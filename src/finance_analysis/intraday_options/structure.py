"""Causal intraday structure from the latest hour, independent of opportunity scores."""
from datetime import timedelta

import numpy as np

from finance_analysis.market_stream.config import market_trading_date
from finance_analysis.market_stream.session import session_bounds
from finance_analysis.market_stream.patterns.features import swing_high_indices, swing_low_indices, true_ranges

MINUTE = timedelta(minutes=1)
LABELS = {
    "uptrend": "持续走强", "downtrend": "持续走弱", "range": "震荡横盘",
    "breakout_up": "箱体向上突破", "breakout_down": "箱体向下突破",
    "failed_up": "向上突破失败", "failed_down": "向下突破失败",
    "rebound": "下跌后反弹", "pullback": "上涨后回落", "unclear": "结构不明确",
}


def metrics(bars):
    if len(bars) < 2:
        return 0.0, 0.0, 0.0
    y = np.log([float(b.close) for b in bars])
    x = np.array([(b.bar_time - bars[0].bar_time).total_seconds() / 60 for b in bars])
    slope = float(np.dot(x - x.mean(), y - y.mean()) / np.sum((x - x.mean()) ** 2))
    variance = float(np.sum((y - y.mean()) ** 2))
    r2 = max(0, 1 - float(np.sum((y - (y.mean() + slope * (x - x.mean()))) ** 2)) / variance) if variance else 0
    path = float(np.abs(np.diff(y)).sum())
    efficiency = abs(float(y[-1] - y[0])) / path if path else 0
    return slope, r2, efficiency


def atr(bars):
    return float(sum(true_ranges(bars[-20:])) / len(bars[-20:])) if bars else 0


def pivots(bars):
    # Reject pivots spanning missing minutes; right-side bars confirm, never backdate detection.
    output = []
    for kind, indices in (("high", swing_high_indices(bars, 2)), ("low", swing_low_indices(bars, 2))):
        for i in indices:
            if bars[i + 2].bar_time - bars[i - 2].bar_time == 4 * MINUTE:
                output.append({"kind": kind, "at": bars[i].bar_time.isoformat(),
                               "confirmed_at": (bars[i + 2].bar_time + MINUTE).isoformat(),
                               "price": float(bars[i].high if kind == "high" else bars[i].low)})
    return sorted(output, key=lambda p: p["at"])


def segment(bars, end, minutes):
    return [b for b in bars if end - (minutes - 1) * MINUTE <= b.bar_time <= end]


def touches(bars, level, tolerance, side):
    last = None
    count = 0
    for bar in bars:
        price = float(bar.high if side == "high" else bar.low)
        if abs(price - level) <= tolerance and (last is None or bar.bar_time - last >= 3 * MINUTE):
            count += 1
            last = bar.bar_time
    return count


def box(bars, end):
    values = segment(bars, end, 30)
    if not bars or end - bars[0].bar_time < 29 * MINUTE:
        return None
    if len(values) < 24 or not values or values[-1].bar_time != end:
        return None
    scale = atr(values)
    if scale <= 0:
        return None
    high, low = max(float(b.high) for b in values), min(float(b.low) for b in values)
    slope, _, efficiency = metrics(values)
    drift = abs(slope) * 30 * float(values[-1].close)
    if high - low < 2 * scale or efficiency > 0.25 or drift > scale:
        return None
    if min(touches(values, high, .3 * scale, "high"), touches(values, low, .3 * scale, "low")) < 2:
        return None
    return {"upper": high, "lower": low, "start_at": (end - 29 * MINUTE).isoformat(),
            "end_at": (end + MINUTE).isoformat(), "atr": scale}


def box_event(bars, end):
    # Search only recent events. Each candidate's bounds are frozen before its breakout.
    for age in range(1, 16):
        boundary = end - age * MINUTE
        bounds = box(bars, boundary)
        if bounds is None:
            continue
        following = [b for b in bars if boundary < b.bar_time <= end]
        side = 0
        confirmed = None
        phase = "forming"
        occurred = None
        previous = None
        failed = None
        for b in following:
            price = float(b.close)
            above = price > bounds["upper"] + .2 * bounds["atr"]
            below = price < bounds["lower"] - .2 * bounds["atr"]
            direction = 1 if above else -1 if below else 0
            adjacent = previous is not None and b.bar_time - previous.bar_time == MINUTE
            if side == 0:
                if direction:
                    side, occurred = direction, b.bar_time + MINUTE
            elif confirmed is None:
                if direction == side and adjacent:
                    confirmed, phase = b.bar_time + MINUTE, "confirmed"
                elif direction != side:
                    side, occurred = direction, b.bar_time + MINUTE if direction else None
            else:
                level = bounds["upper"] if side > 0 else bounds["lower"]
                inside = (price - level) * side <= 0
                prev_inside = previous is not None and (float(previous.close) - level) * side <= 0
                if inside and prev_inside and adjacent:
                    failed = {"kind": "failed_up" if side > 0 else "failed_down", "phase": "failed",
                            "since": (b.bar_time + MINUTE).isoformat(), "box": bounds,
                            "reasons": ["突破后连续两根闭合K收回突破边界内侧，突破失效"]}
                    side, confirmed, phase, previous = 0, None, "forming", b
                    continue
                level = bounds["upper"] if side > 0 else bounds["lower"]
                extreme = float(b.low if side > 0 else b.high)
                if adjacent and abs(extreme - level) <= .3 * bounds["atr"] and (price - level) * side > .2 * bounds["atr"]:
                    phase = "retest"
            previous = b
        if side and occurred:
            return {"kind": "breakout_up" if side > 0 else "breakout_down", "phase": phase,
                    "since": (confirmed or occurred).isoformat(), "box": bounds,
                    "reasons": ["突破前30分钟形成多次触碰的横向箱体，边界已固定",
                                "连续两根闭合K越过边界0.2 ATR" if confirmed else "尚未连续两根闭合K确认突破"]}
        if failed:
            return failed
    return None


def raw_structure(bars, end):
    main = segment(bars, end, 30)
    recent = segment(bars, end, 5)
    points = pivots(main)
    background = segment(bars, end, 60)
    slope60, _, _ = metrics(background)
    background_move = abs(float(background[-1].close / background[0].close) - 1) if background else 0
    bias = ("bullish" if slope60 > 0 else "bearish") if background_move >= .0002 else "neutral"
    result = {"kind": "unclear", "phase": "waiting", "since": (end + MINUTE).isoformat(),
              "background": bias, "box": None, "pivots": points, "reasons": [], "oversold": False}
    if len(main) < 2:
        result["reasons"] = ["有效分钟数据不足，等待结构"]
        return result
    scale = atr(main)
    if scale <= 0:
        return result
    event = box_event(bars, end)
    if event:
        return {**result, **event}
    slope, stability, efficiency = metrics(main)
    short, _, short_efficiency = metrics(recent)
    highs = [p for p in points if p["kind"] == "high"]
    lows = [p for p in points if p["kind"] == "low"]
    price = float(main[-1].close)
    # Reversal means reversal of the short leg, not a confirmed change in the long trend.
    for direction, kind, prior_points in ((1, "rebound", highs), (-1, "pullback", lows)):
        if (slope * direction < 0 and slope60 * direction < 0 and short * direction > 0
                and short_efficiency >= .35 and prior_points
                and (price - prior_points[-1]["price"]) * direction > .2 * scale):
            before = [b for b in main if b.bar_time <= end - 5 * MINUTE]
            if len(before) < 5:
                continue
            move = (float(before[-1].close) - float(before[0].close)) * direction
            if move > -2 * scale:
                continue
            ema = float(before[0].close)
            for b in before[1:]:
                ema += 2 / 21 * (float(b.close) - ema)
            oversold = direction == 1 and (ema - float(before[-1].close)) / scale >= 2.5
            return {**result, "kind": kind, "phase": "confirmed", "oversold": oversold,
                    "reasons": ["30/60分钟背景尚未反转，最近5分钟转向并越过已确认局部拐点",
                                "此前下跌偏离EMA20超过2.5 ATR，标记超跌反弹" if oversold else "此前逆向移动超过2 ATR"]}
    for direction, kind in ((1, "uptrend"), (-1, "downtrend")):
        stepping = (len(highs) >= 2 and len(lows) >= 2
                    and (highs[-1]["price"] - highs[-2]["price"]) * direction > .1 * scale
                    and (lows[-1]["price"] - lows[-2]["price"]) * direction > .1 * scale)
        # Smooth monotone trends need not manufacture alternating swing pivots.
        smooth = stability >= .85 and efficiency >= .7
        meaningful = abs(price - float(main[0].close)) >= max(.5 * scale, .0002 * price)
        if meaningful and slope * direction > 0 and stability >= .6 and efficiency >= .35 and (stepping or smooth):
            return {**result, "kind": kind, "phase": "continuing" if short * direction > 0 else "pullback",
                    "reasons": [f"30分钟稳定度{stability:.0%}、路径效率{efficiency:.0%}",
                                "确认高低点同向推进" if stepping else "平滑单向推进，尚无足够交替拐点"]}
    bounds = box(bars, end)
    if efficiency <= .25 and abs(slope) * 30 * price <= scale:
        return {**result, "kind": "range", "phase": "inside", "box": bounds,
                "reasons": ["30分钟净位移较小、路径效率低" + ("，上下沿存在多次独立触碰" if bounds else "，尚无可靠箱体边界")]}
    result["reasons"] = ["趋势、箱体或反弹条件尚未形成一致证据"]
    return result


def calculate_structure(ordered):
    end = ordered[-1].bar_time
    opening, _ = session_bounds("US", market_trading_date(end, "US"))
    start = max(opening, end - 59 * MINUTE)
    # The input is closed/session filtered by the scoring boundary.
    bars = [b for b in ordered if start <= b.bar_time <= end and b.is_valid() and not b.partial and not b.sampled]
    expected = int((end - start) / MINUTE) + 1
    missing = expected - len(bars)
    result = raw_structure(bars, end)
    if end - opening < 29 * MINUTE:
        result.update(kind="unclear", phase="warming", reasons=["结构观察等待当日30分钟背景"])
    elif result["kind"] not in {"breakout_up", "breakout_down", "failed_up", "failed_down"}:
        previous = raw_structure([b for b in bars if b.bar_time < end], end - MINUTE)
        if result["kind"] != previous["kind"] or not {end, end - MINUTE} <= {b.bar_time for b in bars}:
            candidate = LABELS[result["kind"]]
            result.update(kind="unclear", phase="forming", reasons=[f"{candidate}尚需连续两次闭合分钟确认"])
    result.update(as_of=(end + MINUTE).isoformat(), available_bars=len(bars), missing_bars=missing,
                  reference=missing > 0)
    if expected < 60:
        result["reasons"].append("60分钟背景尚未齐全，使用当日已有背景")
    if missing:
        result["reasons"].append(f"最近观察区间缺{missing}根有效K，结构仅供参考")
    return result
