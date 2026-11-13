"""Causal intraday structure from the latest hour, independent of opportunity scores."""
from datetime import timedelta

import numpy as np

from finance_analysis.market_stream.config import market_trading_date
from finance_analysis.market_stream.session import session_bounds
from finance_analysis.market_stream.patterns.features import swing_high_indices, swing_low_indices, true_ranges

MINUTE = timedelta(minutes=1)
MIN_MAIN_BARS = 24  # Same 80% coverage floor as the existing 30-minute box detector.
MIN_RECENT_BARS = 4
SHORT_MOVE_ATR = .2
SHORT_EFFICIENCY = .35
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
    if len(values) < MIN_MAIN_BARS or not values or values[-1].bar_time != end:
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
    """Replay in time order; an active event owns its pre-trigger box for 15 minutes."""
    event = None
    triggered = None
    previous = None
    side = 0
    for bar in bars:
        if bar.bar_time > end:
            break
        when = bar.bar_time + MINUTE
        if triggered is not None and bar.bar_time - triggered >= 15 * MINUTE:
            event, triggered = None, None
        # Only discover a new box when no event owns one. Breakout candles can
        # never move the bounds/ATR of a forming, confirmed, retest or failed event.
        bounds = event["box"] if event is not None else box(bars, bar.bar_time - MINUTE)
        if bounds is None:
            previous = bar
            continue
        price = float(bar.close)
        direction = (1 if price > bounds["upper"] + .2 * bounds["atr"] else
                     -1 if price < bounds["lower"] - .2 * bounds["atr"] else 0)
        adjacent = previous is not None and bar.bar_time - previous.bar_time == MINUTE
        if event is None or event["phase"] == "failed":
            if direction:
                side, triggered = direction, bar.bar_time
                event = {
                    "kind": "breakout_up" if side > 0 else "breakout_down", "phase": "forming",
                    "since": when.isoformat(), "confirmed_at": None, "box": bounds,
                    "reasons": ["突破前30分钟形成多次触碰的横向箱体，边界与ATR已固定",
                                "尚未连续两根闭合K确认突破"],
                }
        elif event["confirmed_at"] is None:
            previous_direction = (
                previous is not None
                and (float(previous.close) - (bounds["upper"] if side > 0 else bounds["lower"])) * side
                > .2 * bounds["atr"]
            )
            if direction == side and adjacent and previous_direction:
                event.update(phase="confirmed", since=when.isoformat(), confirmed_at=when.isoformat())
                event["reasons"][1] = "连续两根闭合K越过固定边界0.2 ATR"
            elif direction == -side:
                # A direct opposite attempt starts on this candle; it still needs
                # a second adjacent close and cannot reuse the first confirmation.
                side, triggered = direction, bar.bar_time
                event.update(kind="breakout_up" if side > 0 else "breakout_down", since=when.isoformat())
            elif direction == 0:
                event, triggered = None, None
        else:
            level = bounds["upper"] if side > 0 else bounds["lower"]
            inside = (price - level) * side <= 0
            prev_inside = previous is not None and (float(previous.close) - level) * side <= 0
            if inside and prev_inside and adjacent:
                event.update(kind="failed_up" if side > 0 else "failed_down", phase="failed",
                             since=when.isoformat(),
                             reasons=["突破后连续两根闭合K收回突破边界内侧，突破失效"])
            else:
                extreme = float(bar.low if side > 0 else bar.high)
                if (event["phase"] != "retest" and adjacent and abs(extreme - level) <= .3 * bounds["atr"]
                        and (price - level) * side > .2 * bounds["atr"]):
                    event.update(phase="retest", since=when.isoformat())
                    event["reasons"].append("回踩固定边界后收于边界外0.2 ATR，标记回踩守住")
        previous = bar
    if triggered is not None and end - triggered >= 15 * MINUTE:
        return None
    return event


def raw_structure(bars, end):
    main = segment(bars, end, 30)
    recent = segment(bars, end, 5)
    points = pivots(main)
    background = segment(bars, end, 60)
    slope60, _, _ = metrics(background)
    background_move = abs(float(background[-1].close / background[0].close) - 1) if background else 0
    bias = ("bullish" if slope60 > 0 else "bearish") if background_move >= .0002 else "neutral"
    result = {"kind": "unclear", "phase": "waiting", "since": (end + MINUTE).isoformat(),
              "background": bias, "confirmed_at": None, "box": None, "pivots": points, "reasons": [], "oversold": False}
    if len(main) < MIN_MAIN_BARS:
        result["reasons"] = [f"最近30分钟仅{len(main)}根有效K，至少需要{MIN_MAIN_BARS}根，等待结构"]
        return result
    scale = atr(main)
    if scale <= 0:
        return result
    event = box_event(bars, end)
    if event:
        return {**result, **event}
    slope, stability, efficiency = metrics(main)
    short, _, short_efficiency = metrics(recent)
    recent_complete = len(recent) >= MIN_RECENT_BARS and recent[-1].bar_time == end
    short_move = float(recent[-1].close - recent[0].close) if recent else 0.0
    short_direction = (
        (1 if short > 0 else -1)
        if recent_complete and short * short_move > 0
        and abs(short_move) >= SHORT_MOVE_ATR * scale and short_efficiency >= SHORT_EFFICIENCY
        else 0
    )
    highs = [p for p in points if p["kind"] == "high"]
    lows = [p for p in points if p["kind"] == "low"]
    price = float(main[-1].close)
    # Reversal means reversal of the short leg, not a confirmed change in the long trend.
    for direction, kind, prior_points in ((1, "rebound", highs), (-1, "pullback", lows)):
        if (slope * direction < 0 and slope60 * direction < 0 and short * direction > 0
                and short_direction == direction and prior_points
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
            if not recent_complete:
                phase, detail = "forming", "最近5分钟有效K不足4根或末根缺失，短线阶段待确认"
            elif short_direction == direction:
                phase, detail = "continuing", "最近5分钟沿主趋势有效推进"
            elif short_direction == -direction:
                phase, detail = "pullback", "最近5分钟反向移动至少0.2 ATR且路径效率至少35%，回撤观察"
            else:
                phase, detail = "pausing", "最近5分钟缺乏有效单向推进，短线停顿，不把微小反向波动当作回撤"
            return {**result, "kind": kind, "phase": phase,
                    "reasons": [f"30分钟稳定度{stability:.0%}、路径效率{efficiency:.0%}",
                                "确认高低点同向推进" if stepping else "平滑单向推进，尚无足够交替拐点",
                                detail]}
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
    elif result["kind"] not in {"unclear", "breakout_up", "breakout_down", "failed_up", "failed_down"}:
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
